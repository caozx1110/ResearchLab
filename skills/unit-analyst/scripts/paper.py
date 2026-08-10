#!/usr/bin/env python3
"""Paper analyst: script prepares fillable structure + verifies evidence; a runtime
agent fills the understanding (`docs/DESIGN.md`, "Prepare / fill / verify").

The script is deliberately *not* allowed to understand the paper. It (a) parses the
source into a parse-cache, (b) emits a **fillable structure** (screening scaffold /
5-element note skeleton) whose judgement fields are left blank for a runtime agent,
and (c) **verifies** every judgement the agent fills carries legit verbatim evidence
(research.evidence) before it clears the substance gate (research.confirm) and is
persisted. There is no keyword-count → grade heuristic anywhere: any "novelty=strong"
class judgement must come from an agent, never from Python.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Mapping, Sequence

SCRIPT_PATH = Path(__file__).resolve()
skills_dir = SCRIPT_PATH.parents[2]
if skills_dir.name != "skills":
    raise SystemExit("Could not locate the managed research runtime.")
if skills_dir.parent.name == ".agents":
    PROJECT_ROOT = skills_dir.parent.parent
    lib = PROJECT_ROOT / ".agents" / "lib"
else:
    PROJECT_ROOT = skills_dir.parent
    lib = PROJECT_ROOT / "runtime" / "lib"
if not (skills_dir / "metadata.yaml").is_file() or not (lib / "research" / "__init__.py").is_file() or not (lib / "research" / "bootstrap.py").is_file():
    raise SystemExit("Could not locate the managed research runtime.")
sys.path.insert(0, str(lib))

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

import yaml

from research.common import add_project_root_argument, clean_text, extract_pdf_context_pages, file_sha256, load_yaml, print_resolved_project_roots, read_text_excerpt, write_text_if_changed, write_yaml_if_changed
from research.figures import (
    FigureIndexError,
    build_asset_binding,
    build_figure_entry,
    build_figure_index,
    load_current_figure_index,
)
from research.pdf_layout import (
    GRAY_RATIO_THRESHOLD,
    LAYOUT_DEFAULT_CROP_PADDING_PT,
    LAYOUT_DEFAULT_RENDER_SCALE,
    LOW_COLOR_THRESHOLD,
    WHITE_RATIO_THRESHOLD,
    extract_caption_region_assets,
)
from research.core import (
    append_history,
    apply_record_governance,
    build_index,
    command_mutation,
    canonical_record_snapshot_for_record,
    confirm_unit,
    load_runtime_preferences,
    locate_record,
    kb_root,
    passage_search_cache_path,
    checkpoint_and_report,
    candidate_pools_path,
    project_root,
    rel,
    resolve_local_reference,
    topic_taxonomy_path,
    write_record,
)
from research.evidence import (
    attach_claims,
    build_verification_receipt,
    read_claims,
    validate_claims,
    verify_claim_evidence,
)
from research.preference_selection import (
    SKILL_OPERATIONS,
    operation_contract,
    resolve_task_preferences,
    selection_binding,
)

SECTION_PATTERNS = (
    "abstract",
    "introduction",
    "related work",
    "background",
    "method",
    "approach",
    "experiment",
    "results",
    "analysis",
    "discussion",
    "limitation",
    "conclusion",
    "appendix",
)

_ACTIVE_MUTATION: ContextVar[bool] = ContextVar("paper_active_mutation", default=False)
_PENDING_CHECKPOINT: ContextVar[tuple[Path, str, str, list[Path]] | None] = ContextVar(
    "paper_pending_checkpoint", default=None
)
_MAX_VERIFY_FILL_BYTES = 16 * 1024 * 1024


def _index_targets(root: Path) -> list[Path]:
    return [
        kb_root(root) / "index.yaml",
        kb_root(root) / "index.md",
        topic_taxonomy_path(root),
        candidate_pools_path(root),
        passage_search_cache_path(root),
    ]


def _transactional(op_name: str, target_builder):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            root, targets = target_builder(*args, **kwargs)
            command_args = args[0] if args else None
            temporary_fill = None
            temporary_command = False
            try:
                has_command_namespace = command_args is not None and (
                    hasattr(command_args, "command") or hasattr(command_args, "phase")
                )
                command_name = (
                    str(getattr(command_args, "command", "") or op_name)
                    if has_command_namespace
                    else op_name
                )
                if has_command_namespace and not hasattr(command_args, "command"):
                    setattr(command_args, "command", command_name)
                    temporary_command = True
                if (
                    has_command_namespace
                    and str(getattr(command_args, "phase", "") or "") == "verify"
                    and command_name in {"screen", "complete-note"}
                    and getattr(command_args, "_bound_paper_verify_fill", None) is None
                ):
                    unit_root = args[3]
                    default_name = (
                        "screening.yaml" if command_name == "screen" else "note-fill.yaml"
                    )
                    temporary_fill = _open_managed_verify_fill(
                        root,
                        unit_root,
                        command_args,
                        default_name=default_name,
                    )
                    setattr(command_args, "_bound_paper_verify_fill", temporary_fill)
                bound_fill = getattr(command_args, "_bound_paper_verify_fill", None)
                if bound_fill is not None:
                    _revalidate_managed_verify_fill(root, bound_fill)
                    _prevalidate_bound_verify_fill(
                        command_args,
                        args[2],
                        args[3],
                        bound_fill,
                    )
                    # Prevalidation reads evidence paths. Recheck the held fill once
                    # more after it returns and before command_mutation can create a
                    # journal or touch any business target.
                    _revalidate_managed_verify_fill(root, bound_fill)
            except BaseException:
                if temporary_fill is not None:
                    temporary_fill.close()
                    delattr(command_args, "_bound_paper_verify_fill")
                if temporary_command:
                    delattr(command_args, "command")
                if command_args is not None and hasattr(
                    command_args, "_prevalidated_paper_verify_fill"
                ):
                    delattr(command_args, "_prevalidated_paper_verify_fill")
                raise
            active_token = _ACTIVE_MUTATION.set(True)
            checkpoint_token = _PENDING_CHECKPOINT.set(None)
            try:
                with command_mutation(
                    root,
                    f"paper-analyst:{op_name}",
                    targets,
                    allow_operational_state=True,
                ):
                    result = function(*args, **kwargs)
                pending = _PENDING_CHECKPOINT.get()
            finally:
                _PENDING_CHECKPOINT.reset(checkpoint_token)
                _ACTIVE_MUTATION.reset(active_token)
                if temporary_fill is not None:
                    temporary_fill.close()
                    delattr(command_args, "_bound_paper_verify_fill")
                if temporary_command:
                    delattr(command_args, "command")
                if command_args is not None and hasattr(
                    command_args, "_prevalidated_paper_verify_fill"
                ):
                    delattr(command_args, "_prevalidated_paper_verify_fill")
            if pending is not None:
                checkpoint_and_report(
                    pending[0], trigger=pending[1], message=pending[2], target_paths=pending[3]
                )
            return result

        return wrapped

    return decorate

PAPER_TYPES: tuple[str, ...] = ("method_system", "benchmark", "survey")
SCREENING_DIMENSION_RATINGS: dict[str, tuple[str, ...]] = {
    # institutions is descriptive only; it must never become a prestige score.
    "institutions": ("identified", "not_disclosed", "unclear"),
    "backing_strength": ("strong", "moderate", "weak", "unclear"),
    "result_strength": ("strong", "moderate", "weak", "unclear"),
    "experiment_quality": ("strong", "moderate", "weak", "unclear"),
    "reliability": ("strong", "moderate", "weak", "unclear"),
    "novelty": ("strong", "moderate", "weak", "unclear"),
}

# --------------------------------------------------------------------------- #
# Fill contracts (.agents/lib/research/SCHEMAS.md#paper-element-sets).         #
#                                                                             #
# A runtime agent classifies the paper inside the deep-read fill and fills the  #
# selected five elements; the type and every element are judgement-class       #
# claims and MUST carry >=1 evidence_ref. The script only validates and routes. #
# --------------------------------------------------------------------------- #
ELEMENT_SETS: dict[str, tuple[str, ...]] = {
    "method_system": ("motivation", "method", "experiment", "limitation", "insight"),
    "benchmark": ("motivation", "task_design", "metrics", "coverage_limitation", "insight"),
    "survey": ("scope", "taxonomy", "trends", "gaps", "insight"),
}

# Compatibility alias for callers that explicitly refer to the historical set.
NOTE_ELEMENTS: tuple[str, ...] = ELEMENT_SETS["method_system"]

# Every element is judgement-class so research.evidence.validate_claims enforces a
# non-empty evidence_refs on each
# (.agents/lib/research/SCHEMAS.md#evidence-claims gate interlock).
ELEMENT_CLAIM_TYPE: dict[str, str] = {
    "motivation": "inference",
    "method": "inference",
    "experiment": "evaluation",
    "limitation": "evaluation",
    "insight": "inference",
    "task_design": "inference",
    "metrics": "evaluation",
    "coverage_limitation": "evaluation",
    "scope": "inference",
    "taxonomy": "inference",
    "trends": "evaluation",
    "gaps": "evaluation",
}

# element -> (payload section, field, shape). Filling motivation/method/experiment/
# insight populates core_content (4 of the 8 canonical fields), so a verified note is
# never hollow; limitation lands in critique.weak_spots. note.md renders all five.
ELEMENT_TARGET: dict[str, tuple[str, str, str]] = {
    "motivation": ("core_content", "motivation", "str"),
    "method": ("core_content", "method", "str"),
    "experiment": ("core_content", "changes_and_effects", "list"),
    "limitation": ("critique", "weak_spots", "list"),
    "insight": ("core_content", "why_it_might_work", "str"),
    "task_design": ("core_content", "method", "str"),
    "metrics": ("core_content", "changes_and_effects", "list"),
    "coverage_limitation": ("core_content", "changes_and_effects", "list"),
    "scope": ("core_content", "motivation", "str"),
    "taxonomy": ("core_content", "method", "str"),
    "trends": ("core_content", "changes_and_effects", "list"),
    "gaps": ("core_content", "changes_and_effects", "list"),
}

ELEMENT_HEADING: dict[str, str] = {
    "motivation": "Motivation",
    "method": "Method",
    "experiment": "Experiment",
    "limitation": "Limitation",
    "insight": "Insight",
    "task_design": "Task Design",
    "metrics": "Metrics",
    "coverage_limitation": "Coverage Limitation",
    "scope": "Scope",
    "taxonomy": "Taxonomy",
    "trends": "Trends",
    "gaps": "Gaps",
}


def _legacy_paper_type_from_record(record: dict) -> str:
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    quick_screen = payload.get("quick_screen")
    paper_type = quick_screen.get("paper_type") if isinstance(quick_screen, dict) else ""
    normalized = str(paper_type or "").strip().lower()
    return normalized if normalized in PAPER_TYPES else ""


def _has_legacy_quick_screen(record: dict) -> bool:
    payload = record.get("payload")
    return isinstance(payload, dict) and isinstance(payload.get("quick_screen"), dict)


def _paper_type_from_record(record: dict) -> str:
    """Read the canonical deep-read type, then the pre-R1 legacy screening type."""
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    deep_read = payload.get("deep_read")
    paper_type = deep_read.get("paper_type") if isinstance(deep_read, dict) else ""
    normalized = str(paper_type or "").strip().lower()
    if normalized in PAPER_TYPES:
        return normalized
    # Read-only compatibility: never write a new paper type back to quick_screen.
    legacy = _legacy_paper_type_from_record(record)
    if legacy:
        return legacy
    top_level = str(record.get("paper_type") or "").strip().lower()
    return top_level if top_level in PAPER_TYPES else ""


def elements_for(record_or_type: dict | str) -> tuple[str, ...]:
    """Select a persisted/legacy element set; missing type keeps legacy default."""
    if isinstance(record_or_type, str):
        paper_type = record_or_type
    elif isinstance(record_or_type, dict):
        paper_type = _paper_type_from_record(record_or_type)
    else:
        paper_type = ""
    normalized = str(paper_type or "").strip().lower()
    return ELEMENT_SETS.get(normalized, ELEMENT_SETS["method_system"])

# Reusable, machine-readable description of the evidence_ref shape an agent must fill.
EVIDENCE_REF_FORMAT: dict[str, str] = {
    "source_unit_id": "p-... (this paper unit id)",
    "artifact": "parse-cache.yaml (unit-relative artifact the quote lives in)",
    "locator": "PDF: page=N ; HTML: section or section:<anchor>",
    "quote": "short verbatim snippet — script checks it is a whitespace-normalized substring of the artifact",
    "summary": "optional one-line paraphrase",
}


def add_confirmation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--confirmed-by", default="")
    parser.add_argument("--evidence", action="append", required=True)
    parser.add_argument("--user-authorization", default="")
    parser.add_argument("--authorization-source", default="")


def _assert_safe_paper_input_path(root: Path, path: Path) -> None:
    """Reject symlink leaves and workspace-relative symlink ancestors."""
    lexical_root = root.absolute()
    lexical_path = path.absolute()
    if lexical_root.is_symlink() or lexical_path.is_symlink():
        raise ValueError("paper preference input path contains a symlink")
    try:
        relative = lexical_path.relative_to(lexical_root)
    except ValueError:
        return
    cursor = lexical_root
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("paper preference input path contains a symlink")


def _source_paths(root: Path, record: dict) -> list[Path]:
    paths: list[Path] = []
    source = record.get("source", {})
    for backup in source.get("backup_paths", []):
        path = root / str(backup)
        _assert_safe_paper_input_path(root, path)
        if path.exists():
            paths.append(path)
    original_uri = str(source.get("original_uri") or "")
    if original_uri and not original_uri.startswith("http"):
        lexical_original = Path(original_uri).expanduser()
        if not lexical_original.is_absolute():
            lexical_original = root / lexical_original
        _assert_safe_paper_input_path(root, lexical_original)
        path = resolve_local_reference(root, original_uri) or Path(original_uri).expanduser()
        _assert_safe_paper_input_path(root, path)
        if path.exists():
            paths.append(path.resolve())
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = path.as_posix()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def _load_source_chunks(
    root: Path,
    record: dict,
    *,
    front_limit: int,
    back_limit: int,
    per_page_char_limit: int,
) -> list[dict]:
    chunks: list[dict] = []
    for path in _source_paths(root, record):
        if path.suffix.lower() == ".pdf":
            try:
                payload = extract_pdf_context_pages(
                    path,
                    front_limit=front_limit,
                    back_limit=back_limit,
                    per_page_char_limit=per_page_char_limit,
                )
            except Exception:
                payload = {"pages": []}
            for page in payload.get("pages", []):
                text = clean_text(str(page.get("text") or ""))
                if text:
                    chunks.append({"label": f"{path.name}:page-{page['page']}", "text": text, "page": page["page"]})
        elif path.is_file():
            text = clean_text(read_text_excerpt(path, limit=12000))
            if text:
                chunks.append({"label": path.name, "text": text, "page": None})
    return chunks


def _cache_path(unit_root: Path) -> Path:
    return unit_root / "parse-cache.yaml"


def _load_or_refresh_cache(
    root: Path,
    record: dict,
    unit_root: Path,
    *,
    force: bool = False,
    preferences: Mapping[str, object] | None = None,
) -> tuple[list[dict], Path]:
    preferences = preferences or {}
    cache_path = _cache_path(unit_root)
    _assert_safe_paper_input_path(root, cache_path)
    if cache_path.exists():
        if force:
            raise SystemExit(
                "parse-cache.yaml is immutable derived evidence; --force cannot overwrite it in place."
            )
        payload = load_yaml(cache_path, default={})
        if isinstance(payload, dict) and isinstance(payload.get("chunks"), list):
            return payload["chunks"], cache_path
    front_limit = int(preferences.get("parse_cache_front_limit") or 8)
    back_limit = int(preferences.get("parse_cache_back_limit") or 0)
    per_page_char_limit = int(preferences.get("parse_cache_per_page_char_limit") or 3000)
    chunks = _load_source_chunks(
        root,
        record,
        front_limit=front_limit,
        back_limit=back_limit,
        per_page_char_limit=per_page_char_limit,
    )
    write_yaml_if_changed(
        cache_path,
        {
            "paper_id": record["id"],
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "cache_policy": {
                "front_limit": front_limit,
                "back_limit": back_limit,
                "per_page_char_limit": per_page_char_limit,
            },
            "chunks": chunks,
        },
    )
    return chunks, cache_path


def _cache_locator_kind(cache_path: Path) -> str:
    """Best-effort read of the parse-cache's declared locator_kind (page|section).

    Written by research.sources.write_parse_cache for dual-source intakes. Absent for
    paper.py's own cold-parse cache, in which case we infer per chunk from the label.
    """
    payload = load_yaml(cache_path, default={}) if cache_path.exists() else {}
    if isinstance(payload, dict):
        return str(payload.get("locator_kind") or "")
    return ""


def _chunk_locator(chunk: dict, cache_locator_kind: str) -> str:
    """Derive a locator using the two families in
    `.agents/lib/research/SCHEMAS.md#evidence-claims`.

    PDF chunks -> ``page=N``; HTML section chunks -> ``section:<anchor>`` / ``section``.
    This is pure transport: it copies the locator the agent should cite, it does not
    judge anything.
    """
    page = chunk.get("page")
    if isinstance(page, int):
        return f"page={page}"
    label = str(chunk.get("label") or "")
    if label.startswith("section:"):
        return label
    match = re.search(r"page[-_ ]?(\d+)", label, flags=re.IGNORECASE)
    if match:
        return f"page={match.group(1)}"
    if cache_locator_kind == "page":
        return "page"
    return "section"


def _evidence_digest(source_chunks: list[dict], cache_locator_kind: str, *, chunk_limit: int, excerpt_chars: int) -> list[dict]:
    """Build a locator-tagged excerpt list from parse-cache chunks for the agent.

    This is the transport half of `docs/DESIGN.md` "Prepare / fill / verify": it hands the agent the raw
    front-matter text with citable locators. It contains no judgement and no grade.
    """
    digest: list[dict] = []
    for chunk in source_chunks[:chunk_limit]:
        text = clean_text(str(chunk.get("text") or ""))
        if not text:
            continue
        digest.append(
            {
                "locator": _chunk_locator(chunk, cache_locator_kind),
                "artifact": "parse-cache.yaml",
                "label": str(chunk.get("label") or ""),
                "excerpt": text[:excerpt_chars],
            }
        )
    return digest


def _keyword_mentions(text: str, terms: list[str]) -> list[str]:
    """Return surface-form term mentions — an orientation HINT for the agent only.

    Deliberately not counted, scored, or turned into a grade: it merely tells the
    agent which surface terms appear so it knows where to look. No caller may derive a
    judgement field from this list (`docs/DESIGN.md`, "Prepare / fill / verify").
    """
    mentions: list[str] = []
    lowered = text.lower()
    for term in terms:
        term = term.strip().lower()
        if term and term in lowered and term not in mentions:
            mentions.append(term)
    return mentions


# --------------------------------------------------------------------------- #
# screen: prepare a fillable screening structure / verify an agent-filled one   #
# --------------------------------------------------------------------------- #


def build_screening_scaffold(
    record: dict,
    source_chunks: list[dict],
    cache_locator_kind: str,
    *,
    digest_chunks: int,
    digest_chars: int,
) -> dict:
    """Produce the fillable screening.yaml structure (NO keyword-driven grading).

    The judgement fields (paper_type / worth_deep_reading / judgement_reason /
    relevance / claims) are left blank for a runtime agent; the script only
    supplies an evidence digest with locators + an explicitly-non-judgemental
    keyword hint.
    """
    basic_info = record.get("payload", {}).get("basic_info", {})
    title = str(record.get("title") or "")
    abstract = clean_text(str(basic_info.get("abstract") or ""))
    topics = [str(item) for item in record.get("topics", []) if str(item).strip()]
    tags = [str(item) for item in record.get("tags", []) if str(item).strip()]
    digest = _evidence_digest(source_chunks, cache_locator_kind, chunk_limit=digest_chunks, excerpt_chars=digest_chars)

    hint_terms = [term for term in [*topics, *tags] if term.lower() not in {"uncategorized", "research"}]
    hint_source = clean_text(" ".join([title, abstract, *[str(d.get("excerpt") or "") for d in digest]]))

    return {
        "paper_id": record["id"],
        "kind": "paper",
        "status": "awaiting_agent_judgement",
        "phase": "prepare",
        "information_types": ["inference", "evaluation", "unverified"],
        "fill_contract": {
            "description": (
                "Agent fills worth_deep_reading with the quoted string 'yes', 'no', or 'maybe' + judgement_reason + "
                "paper_type (method_system|benchmark|survey) + relevance_to_current_research, "
                "and attaches judgement claims to `claims` "
                "with verbatim evidence. Then run `screen --phase verify` to validate + persist. "
                "The script does NOT decide worth; that judgement belongs to the runtime Agent."
            ),
            "worth_deep_reading": "agent fills one quoted string: 'yes'|'no'|'maybe'",
            "paper_type": "agent fills: method_system|benchmark|survey",
            "judgement_reason": "agent fills: list of short reasons",
            "relevance_to_current_research": "agent fills: strong|moderate|weak + why",
            "claims": "agent attaches judgement claims backing paper_type and worth_deep_reading",
            "structured_dimensions": {
                name: {
                    "status": "agent fills: assessed|not_applicable",
                    "rating": f"when assessed: {'|'.join(ratings)}",
                    "reason": "agent fills an evidence-grounded reason; required for assessed and not_applicable",
                    "claim_ids": "when assessed: one or more ids from claims with verbatim evidence",
                }
                for name, ratings in SCREENING_DIMENSION_RATINGS.items()
            },
            "prohibited_shortcuts": (
                "Do not infer ratings from author identity, institution prestige, venue, citation count, "
                "or other metadata heuristics. Institutions records disclosed affiliation only."
            ),
            "evidence_ref_format": EVIDENCE_REF_FORMAT,
        },
        "agent_hints": {
            "note": (
                "keyword_mentions are raw surface matches for orientation ONLY — they are "
                "NOT a score and MUST NOT be treated as a judgement."
            ),
            "keyword_mentions": _keyword_mentions(hint_source, hint_terms),
        },
        "evidence_digest": digest,
        # --- agent fills below (left blank on purpose) ---
        "paper_type": "",
        "worth_deep_reading": "",
        "judgement_reason": [],
        "relevance_to_current_research": "",
        **{
            name: {"status": "", "rating": "", "reason": "", "claim_ids": []}
            for name in SCREENING_DIMENSION_RATINGS
        },
        "claims": [],
    }


def verify_screening_fill(payload: dict, unit_dir: Path) -> list[str]:
    """Return violations for an agent-filled screening payload (empty == clean).

    Checks the agent actually made a judgement (worth_deep_reading), that any claims
    are structurally valid (validate_claims) and verbatim-grounded (verify_claim_
    evidence), and that a real judgement is backed by >=1 claim.
    """
    violations: list[str] = []
    paper_type = str(payload.get("paper_type") or "").strip().lower()
    if paper_type and paper_type not in PAPER_TYPES:
        violations.append(
            f"paper_type: agent must fill one of {'|'.join(PAPER_TYPES)} or leave blank "
            f"(got {paper_type!r})"
        )
    worth = _normalized_worth_deep_reading(payload.get("worth_deep_reading"))
    if worth not in {"yes", "no", "maybe"}:
        violations.append(
            f"worth_deep_reading: agent must fill one of yes|no|maybe (got {worth or '<blank>'!r})"
        )
    claims = read_claims(payload)
    violations.extend(validate_claims(claims))
    for claim in claims:
        for violation in verify_claim_evidence(claim, unit_dir):
            violations.append(f"screening claim: {violation}")
    claims_by_id = {
        str(claim.get("id") or ""): claim
        for claim in claims
        if isinstance(claim, Mapping) and str(claim.get("id") or "")
    }
    for name, ratings in SCREENING_DIMENSION_RATINGS.items():
        dimension = payload.get(name)
        if not isinstance(dimension, Mapping):
            violations.append(f"{name}: agent must fill a structured judgement object")
            continue
        status = str(dimension.get("status") or "").strip().casefold()
        rating = str(dimension.get("rating") or "").strip().casefold()
        reason = str(dimension.get("reason") or "").strip()
        raw_claim_ids = dimension.get("claim_ids")
        claim_ids = (
            [str(value).strip() for value in raw_claim_ids if str(value).strip()]
            if isinstance(raw_claim_ids, list)
            else []
        )
        if status not in {"assessed", "not_applicable"}:
            violations.append(f"{name}.status: agent must fill assessed|not_applicable")
            continue
        if not reason:
            violations.append(f"{name}.reason: required for {status}")
        if status == "not_applicable":
            if rating:
                violations.append(f"{name}.rating: must be blank when not_applicable")
            if claim_ids:
                violations.append(f"{name}.claim_ids: must be empty when not_applicable")
            continue
        if rating not in ratings:
            violations.append(f"{name}.rating: agent must fill one of {'|'.join(ratings)}")
        if not claim_ids:
            violations.append(f"{name}.claim_ids: assessed judgement requires evidence-backed claims")
        for claim_id in claim_ids:
            if claim_id not in claims_by_id:
                violations.append(f"{name}.claim_ids: unknown claim {claim_id!r}")
    # Every verified screening judgement becomes a canonical, receipt-bound claim.
    if not claims:
        violations.append(
            "screening verification has no evidence-backed claims; at least one canonical claim is required"
        )
    if paper_type and not claims:
        violations.append(
            "paper_type is an agent judgement but no evidence-backed claims were attached"
        )
    return violations


def _normalized_worth_deep_reading(value: object) -> str:
    """Normalize YAML 1.1 yes/no booleans to the canonical string enum."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value or "").strip().lower()


# --------------------------------------------------------------------------- #
# complete-note: type-specific fillable skeleton / verify + persist agent fill #
# --------------------------------------------------------------------------- #


def build_note_scaffold(
    record: dict,
    source_chunks: list[dict],
    cache_locator_kind: str,
    *,
    digest_chunks: int,
    digest_chars: int,
) -> dict:
    """Produce one unified deep-read scaffold; the script authors no judgement."""
    digest = _evidence_digest(source_chunks, cache_locator_kind, chunk_limit=digest_chunks, excerpt_chars=digest_chars)
    element_sets = {
        paper_type: [
            {
                "element": name,
                "claim_type": ELEMENT_CLAIM_TYPE[name],
                "content": "",
                "evidence_refs": [],
            }
            for name in required_elements
        ]
        for paper_type, required_elements in ELEMENT_SETS.items()
    }
    return {
        "paper_id": record["id"],
        "kind": "paper",
        "paper_type": "",
        "paper_type_reason": "",
        "paper_type_evidence_refs": [],
        "status": "awaiting_agent_fill",
        "phase": "prepare",
        "fill_contract": {
            "description": (
                "Agent selects paper_type, explains it with verbatim evidence, and fills only that type's "
                "five-element branch. Every selected element needs >=1 verbatim evidence_ref; all unselected "
                "branches stay blank. Verification writes the canonical type and note only after every claim passes."
            ),
            "paper_type": f"agent fills one of {'|'.join(PAPER_TYPES)}",
            "paper_type_reason": "agent explains the evidence-grounded classification",
            "paper_type_evidence_refs": "agent attaches >=1 verbatim evidence_ref",
            "element_sets": {name: list(elements) for name, elements in ELEMENT_SETS.items()},
            "element_claim_types": dict(ELEMENT_CLAIM_TYPE),
            "evidence_ref_format": EVIDENCE_REF_FORMAT,
        },
        "evidence_digest": digest,
        # --- agent fills type fields + exactly one branch below ---
        "element_sets": element_sets,
    }


def _elements_by_name(fill: Any) -> dict[str, dict]:
    elements: dict[str, dict] = {}
    if isinstance(fill, dict):
        raw = fill.get("elements")
        if isinstance(raw, (list, tuple)):
            for item in raw:
                if isinstance(item, dict) and str(item.get("element") or "").strip():
                    elements[str(item.get("element")).strip().lower()] = item
    return elements


def _branch_elements(fill: Any, paper_type: str) -> dict[str, dict]:
    if not isinstance(fill, dict):
        return {}
    branches = fill.get("element_sets")
    if not isinstance(branches, dict):
        return _elements_by_name(fill)
    branch = branches.get(paper_type)
    return _elements_by_name({"elements": branch})


def _all_note_evidence_items(fill: Any) -> list[dict]:
    """Return every evidence-bearing fill item for cross-unit containment checks."""
    if not isinstance(fill, dict):
        return []
    items: list[dict] = [
        {"evidence_refs": fill.get("paper_type_evidence_refs") or []}
    ]
    branches = fill.get("element_sets")
    if isinstance(branches, dict):
        for branch in branches.values():
            if isinstance(branch, list):
                items.extend(item for item in branch if isinstance(item, dict))
    else:
        items.extend(_elements_by_name(fill).values())
    return items


def _claim_from_element(name: str, element: dict) -> dict:
    return {
        "id": f"claim-{name}",
        "text": clean_text(str(element.get("content") or "")),
        "claim_type": str(element.get("claim_type") or ELEMENT_CLAIM_TYPE.get(name, "inference")),
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": element.get("evidence_refs") or [],
    }


def _claim_from_paper_type(paper_type: str, reason: str, evidence_refs: object) -> dict:
    return {
        "id": "claim-paper-type",
        # Both semantic values are copied from the Agent fill. Deterministic
        # serialization keeps the type visible in generic claim/review projection;
        # the script still makes no classification judgement of its own.
        "text": clean_text(f"paper_type={paper_type}; {reason}"),
        "claim_type": "inference",
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": evidence_refs if isinstance(evidence_refs, list) else [],
        "paper_type": paper_type,
    }


def verify_note_fill(fill: Any, unit_dir: Path, record: dict | None = None) -> tuple[list[str], list[dict]]:
    """Validate an agent-filled type-specific note. Returns (violations, claims).

    Violations name the offending element. All selected elements must be present, carry
    non-empty content, be structurally valid (validate_claims), and every evidence_ref
    quote must verify verbatim against the artifact (verify_claim_evidence).
    """
    violations: list[str] = []
    is_unified = isinstance(fill, dict) and isinstance(fill.get("element_sets"), dict)
    declared_type = str(fill.get("paper_type") or "").strip().lower() if isinstance(fill, dict) else ""
    legacy_type = _legacy_paper_type_from_record(record) if isinstance(record, dict) else ""
    legacy_record = _has_legacy_quick_screen(record) if isinstance(record, dict) else False
    if is_unified:
        if declared_type not in PAPER_TYPES:
            violations.append(
                f"paper_type: agent must fill one of {'|'.join(PAPER_TYPES)}"
            )
        selected_type = declared_type if declared_type in PAPER_TYPES else "method_system"
        branches = fill.get("element_sets")
        assert isinstance(branches, dict)
        unknown_branches = sorted(set(str(key) for key in branches) - set(PAPER_TYPES))
        for name in unknown_branches:
            violations.append(f"element_sets.{name}: unknown paper type branch")
        for paper_type in PAPER_TYPES:
            if paper_type not in branches:
                violations.append(f"element_sets.{paper_type}: missing branch")
                continue
            branch = branches.get(paper_type)
            if not isinstance(branch, list):
                violations.append(f"element_sets.{paper_type}: branch must be a list")
                continue
            names = [
                str(element.get("element") or "").strip().lower()
                for element in branch
                if isinstance(element, dict)
            ]
            if len(names) != len(branch):
                violations.append(f"element_sets.{paper_type}: every element must be a mapping")
            duplicates = sorted({name for name in names if name and names.count(name) > 1})
            for name in duplicates:
                violations.append(f"element_sets.{paper_type}.{name}: duplicate element")
            missing_names = sorted(set(ELEMENT_SETS[paper_type]) - set(names))
            unexpected_names = sorted(set(names) - set(ELEMENT_SETS[paper_type]))
            for name in missing_names:
                violations.append(f"element_sets.{paper_type}.{name}: missing element slot")
            for name in unexpected_names:
                violations.append(f"element_sets.{paper_type}.{name}: unexpected element slot")
        type_reason = clean_text(str(fill.get("paper_type_reason") or ""))
        type_refs = fill.get("paper_type_evidence_refs") or []
        if not type_reason:
            violations.append("paper_type_reason: empty — the agent must explain the classification")
        if not isinstance(type_refs, list) or not type_refs:
            violations.append("paper_type_evidence_refs: paper type requires >=1 verbatim quote")
        type_claim = _claim_from_paper_type(selected_type, type_reason, type_refs)
        claims: list[dict] = [type_claim]
        for violation in verify_claim_evidence(type_claim, unit_dir):
            violations.append(f"paper_type: {violation}")
        for paper_type in PAPER_TYPES:
            if paper_type == selected_type:
                continue
            for name, element in _branch_elements(fill, paper_type).items():
                if clean_text(str(element.get("content") or "")) or bool(element.get("evidence_refs")):
                    violations.append(
                        f"element_sets.{paper_type}.{name}: unselected branch must stay blank"
                    )
        elements = _branch_elements(fill, selected_type)
        required_elements = ELEMENT_SETS[selected_type]
    else:
        # Read-only compatibility for pre-R1 flat note fills. A current paper without
        # a legacy screening type cannot use this shape to bypass type evidence.
        if isinstance(record, dict) and not legacy_record:
            violations.append(
                "note fill uses the retired flat shape; select paper_type in the unified deep-read scaffold"
            )
        selected_type = declared_type if declared_type in PAPER_TYPES else (legacy_type or "method_system")
        if declared_type and declared_type not in PAPER_TYPES:
            violations.append(f"paper_type: invalid legacy value {declared_type!r}")
        if legacy_type and declared_type and declared_type != legacy_type:
            violations.append("paper_type: legacy fill conflicts with the persisted paper type")
        elements = _elements_by_name(fill)
        required_elements = ELEMENT_SETS[selected_type]
        claims = []
    unexpected = sorted(set(elements) - set(required_elements))
    for name in unexpected:
        violations.append(f"element '{name}': unexpected for selected paper type")
    for name in required_elements:
        element = elements.get(name)
        if element is None:
            violations.append(f"element '{name}': missing (all selected elements are required)")
            continue
        content = clean_text(str(element.get("content") or ""))
        if not content:
            violations.append(f"element '{name}': empty content — the agent must fill it")
        refs = element.get("evidence_refs") or []
        if not refs:
            violations.append(f"element '{name}': no evidence_refs — every element must cite >=1 verbatim quote")
        claim_type = str(element.get("claim_type") or "")
        if claim_type != ELEMENT_CLAIM_TYPE[name]:
            violations.append(
                f"element '{name}': claim_type must be {ELEMENT_CLAIM_TYPE[name]}"
            )
        claim = _claim_from_element(name, element)
        claims.append(claim)
        for violation in verify_claim_evidence(claim, unit_dir):
            violations.append(f"element '{name}': {violation}")
    # Structural + judgement-evidence rules (research.evidence). Prefix by claim id.
    for violation in validate_claims(claims):
        violations.append(f"claim-structure: {violation}")
    return violations, claims


def _apply_note_fill_to_payload(record: dict, claims: list[dict]) -> None:
    """Route verified element content into canonical payload fields (in place)."""
    payload = record.setdefault("payload", {})
    type_claim = next(
        (claim for claim in claims if str(claim.get("id") or "") == "claim-paper-type"),
        None,
    )
    if isinstance(type_claim, dict):
        paper_type = str(type_claim.get("paper_type") or "").strip().lower()
        if paper_type not in PAPER_TYPES:
            raise ValueError("verified paper type claim is missing a valid paper_type")
        payload.setdefault("deep_read", {})["paper_type"] = paper_type
    core = payload.setdefault("core_content", {})
    critique = payload.setdefault("critique", {})
    by_id = {str(claim.get("id") or ""): claim for claim in claims}
    for name in elements_for(record):
        claim = by_id.get(f"claim-{name}")
        if claim is None:
            continue
        content = clean_text(str(claim.get("text") or ""))
        section, field, shape = ELEMENT_TARGET[name]
        target = core if section == "core_content" else critique
        if shape == "list":
            existing = target.get(field)
            items = list(existing) if isinstance(existing, list) else []
            if content and content not in items:
                items.append(content)
            target[field] = items
        else:
            target[field] = content


def render_note_md(record: dict, claims: list[dict]) -> str:
    """Render note.md from verified elements + their evidence citations."""
    # Collapse ALL whitespace (incl. newlines) so the full title renders on the single
    # H1 line (F8). A PDF-extracted title can carry embedded newlines; `f"# {title}"`
    # would then put only the first physical line in the heading and orphan the rest as
    # body text — reading as a mid-sentence truncation. This keeps the whole title, no
    # hard character cut.
    title = " ".join(str(record.get("title") or record.get("id") or "").split())
    by_id = {str(claim.get("id") or ""): claim for claim in claims}
    lines = [
        f"# {title}",
        "",
        "> 本笔记由 runtime agent 依据 parse-cache 填写；脚本已逐字校验每条 evidence。",
        "",
    ]
    for name in elements_for(record):
        lines.append(f"## {ELEMENT_HEADING[name]}")
        lines.append("")
        claim = by_id.get(f"claim-{name}")
        content = clean_text(str(claim.get("text") or "")) if claim else ""
        lines.append(content or "-")
        lines.append("")
        refs = (claim.get("evidence_refs") if claim else None) or []
        if refs:
            lines.append("证据：")
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                locator = str(ref.get("locator") or "?")
                quote = clean_text(str(ref.get("quote") or ""))
                summary = clean_text(str(ref.get("summary") or ""))
                suffix = f" — {summary}" if summary else ""
                lines.append(f"- [{locator}] \"{quote}\"{suffix}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def detect_structure(source_chunks: list[dict], note_path: Path) -> dict:
    sections: list[dict] = []
    seen: set[str] = set()
    if note_path.exists():
        for line in note_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("## "):
                heading = clean_text(line[3:])
                key = heading.lower()
                if key and key not in seen:
                    seen.add(key)
                    sections.append({"heading": heading, "source": "note.md"})
    for chunk in source_chunks:
        for raw_line in chunk.get("text", "").splitlines():
            line = clean_text(raw_line).lower()
            if len(line) > 80:
                continue
            if any(pattern == line or line.startswith(pattern + " ") for pattern in SECTION_PATTERNS):
                if line not in seen:
                    seen.add(line)
                    sections.append({"heading": line, "source": chunk["label"], "page": chunk.get("page")})
    return {
        "status": "pending_user_confirmation",
        "information_types": ["fact", "inference", "unverified"],
        "detected_sections": sections,
        "paper_outline": [item["heading"] for item in sections],
        "open_questions": ["章节结构是否因 PDF 文本抽取而漏掉子节？"],
    }


def extract_figure_mentions(source_chunks: list[dict], *, extracted_assets: list[dict[str, Any]] | None = None) -> dict:
    mentions: list[dict[str, Any]] = []
    seen: set[str] = set()
    if extracted_assets:
        for asset in extracted_assets:
            kind = str(asset.get("kind") or "figure")
            label = str(asset.get("label") or asset.get("id") or "").strip().lower()
            key = f"{kind}:{label}:{asset.get('page')}"
            if key in seen:
                continue
            seen.add(key)
            mentions.append(
                {
                    "figure": asset.get("id") or f"{kind}-{label or 'unknown'}",
                    "kind": kind,
                    "label": label,
                    "source": asset.get("source_mode") or "caption-region",
                    "page": asset.get("page"),
                    "caption": asset.get("caption") or "",
                    "status": "pending_user_confirmation",
                }
            )
    if not mentions:
        pattern = re.compile(r"(?:figure|fig\.|table)\s*([0-9ivxlcdm]+[a-z]?)", re.IGNORECASE)
        for chunk in source_chunks:
            text = chunk.get("text", "")
            for match in pattern.finditer(text):
                label = match.group(1)
                key = f"{chunk['label']}::{label}"
                if key in seen:
                    continue
                seen.add(key)
                start = max(0, match.start() - 80)
                end = min(len(text), match.end() + 160)
                snippet = clean_text(text[start:end])
                mentions.append(
                    {
                        "figure": f"figure-{label.lower()}",
                        "kind": "figure",
                        "label": label.lower(),
                        "source": chunk["label"],
                        "page": chunk.get("page"),
                        "snippet": snippet,
                        "status": "pending_user_confirmation",
                    }
                )
    return {
        "status": "mechanically_indexed",
        "information_types": ["fact"],
        "candidate_figures": mentions,
        "key_figures": [],
        "open_questions": [
            "caption 裁剪是否已经覆盖了论文里真正需要复用的整张 Figure / Table？",
            "是否仍有极少数跨栏或无 caption 的对象需要人工补裁？",
        ],
    }


def _extract_pdf_images(
    root: Path,
    record: dict,
    unit_root: Path,
    *,
    preferences: Mapping[str, object] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    pdf_path = next((path for path in _source_paths(root, record) if path.suffix.lower() == ".pdf"), None)
    if pdf_path is None:
        return [], [{"status": "missing-pdf", "reason": "No PDF source found"}], {"mode": "none", "captions_detected": 0}
    preferences = preferences or {}
    include_tables = bool(preferences.get("figure_include_tables", True))
    filter_blank_and_mask = bool(preferences.get("filter_blank_and_mask_images", True))
    render_scale = float(preferences.get("figure_render_scale") or LAYOUT_DEFAULT_RENDER_SCALE)
    crop_padding_pt = float(preferences.get("figure_crop_padding_pt") or LAYOUT_DEFAULT_CROP_PADDING_PT)
    figures_root = unit_root / "figures"

    assets, filtered, metadata = extract_caption_region_assets(
        lambda path: path.relative_to(unit_root).as_posix(),
        pdf_path,
        figures_root,
        include_tables=include_tables,
        render_scale=render_scale,
        crop_padding_pt=crop_padding_pt,
        filter_blank_and_mask=filter_blank_and_mask,
    )
    try:
        source_artifact = pdf_path.relative_to(unit_root).as_posix()
    except ValueError:
        source_artifact = rel(root, pdf_path)
        if not source_artifact.startswith("kb/"):
            raise RuntimeError("Paper figure source must be archived inside the workspace.")
    metadata.update(
        {
            "source_artifact": source_artifact,
            "source_sha256": file_sha256(pdf_path),
            "settings": {
                "mode": metadata.get("mode"),
                "include_tables": include_tables,
                "render_scale": render_scale,
                "crop_padding_pt": crop_padding_pt,
                "filter_blank_and_mask": filter_blank_and_mask,
                "white_ratio_threshold": WHITE_RATIO_THRESHOLD,
                "gray_ratio_threshold": GRAY_RATIO_THRESHOLD,
                "low_color_threshold": LOW_COLOR_THRESHOLD,
            },
        }
    )
    return assets, filtered, metadata


def _finalize_post_actions(
    root: Path,
    *,
    trigger: str,
    message: str,
    defer_post_actions: bool,
    target_paths: Sequence[Path],
) -> dict[str, Any]:
    if defer_post_actions:
        return {"committed": False, "status": "deferred"}
    index_paths = build_index(root)
    all_targets = [*target_paths, *index_paths, topic_taxonomy_path(root), candidate_pools_path(root)]
    if _ACTIVE_MUTATION.get():
        _PENDING_CHECKPOINT.set((root, trigger, message, all_targets))
        return {"committed": False, "status": "pending-transaction-commit"}
    return checkpoint_and_report(
        root,
        trigger=trigger,
        message=message,
        target_paths=all_targets,
    )


# Governance ceiling for auto-executed safe steps (mirrors research-orchestrator's
# GOVERNANCE_MAX_AUTO_STEPS; kept local to avoid a cross-skill import).
_GOVERNANCE_MAX_AUTO_STEPS = {"screen", "build-index", "refresh", "generate-note"}


@_transactional(
    "refresh-structure",
    lambda root, record, unit_root, source_chunks, cache_path, *, defer_post_actions: (
        root,
        [unit_root / "record.yaml", unit_root / "structure.yaml", *([] if defer_post_actions else _index_targets(root))],
    ),
)
def _run_refresh_structure(
    root: Path, record: dict, unit_root: Path, source_chunks: list[dict], cache_path: Path, *, defer_post_actions: bool
) -> int:
    """Derive structure.yaml from the EXISTING parse-cache chunks (F-a invariant:
    never re-parses / overwrites the cache) and persist. Shared by the CLI
    dispatch and the auto-post-note step."""
    structure_path = unit_root / "structure.yaml"
    note_path = unit_root / "note.md"
    _assert_safe_paper_input_path(root, note_path)
    payload = detect_structure(source_chunks, note_path)
    write_yaml_if_changed(structure_path, payload)
    record["payload"]["structure"]["refresh_status"] = "pending_user_confirmation"
    record["payload"]["structure"]["detected_sections"] = payload["detected_sections"]
    record["payload"]["structure"]["paper_outline"] = payload["paper_outline"]
    record["payload"]["structure"]["open_questions"] = payload["open_questions"]
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    append_history(
        record,
        action="paper-structure-refreshed",
        summary="Refreshed paper structure hints from the existing parse cache.",
        information_types=["fact", "inference", "unverified"],
        artifacts=[rel(root, structure_path), rel(root, cache_path)],
    )
    write_record(root, record)
    print(f"[ok] wrote {structure_path.relative_to(root)}")
    _finalize_post_actions(
        root, trigger="milestone", message=f"milestone: refresh paper structure {record['id']}", defer_post_actions=defer_post_actions,
        target_paths=[unit_root / "record.yaml", structure_path],
    )
    return 0


@_transactional(
    "extract-figures",
    lambda root, record, unit_root, source_chunks, *, defer_post_actions, pdf_preferences=None: (
        root,
        [unit_root / "record.yaml", unit_root / "figures.yaml", unit_root / "figures", *([] if defer_post_actions else _index_targets(root))],
    ),
)
def _run_extract_figures(
    root: Path,
    record: dict,
    unit_root: Path,
    source_chunks: list[dict],
    *,
    defer_post_actions: bool,
    pdf_preferences: Mapping[str, object] | None = None,
) -> int:
    """Extract figure assets (best-effort; empty when no PDF backend / no figures)
    and index figure mentions. Shared by the CLI dispatch and the auto-post-note step."""
    figures_path = unit_root / "figures.yaml"
    extracted_assets, filtered_assets, extraction_meta = _extract_pdf_images(
        root, record, unit_root, preferences=pdf_preferences
    )
    current_projection = record.get("payload", {}).get("figures", {})
    current_projection = current_projection if isinstance(current_projection, dict) else {}
    prior_selected = {
        str(item).strip()
        for item in current_projection.get("key_figure_refs", [])
        if str(item).strip()
    }
    if not extraction_meta.get("source_artifact"):
        unavailable = {
            "schema": "figure-index-unavailable/v1",
            "paper_id": str(record.get("id") or ""),
            "status": "unavailable",
            "reason": "no-archived-pdf-source",
            "entries": [],
        }
        write_yaml_if_changed(figures_path, unavailable)
        record["payload"]["figures"] = {
            "schema": "figure-index/v1",
            "extraction_status": "unavailable",
            "index_artifact": "",
            "index_digest": "",
            "available_ref_keys": [],
            "key_figure_refs": [],
        }
        available_refs: set[str] = set()
    else:
        entries: list[dict[str, Any]] = []
        try:
            for asset in extracted_assets:
                relative_asset = Path(str(asset.get("path") or ""))
                asset_path = unit_root / relative_asset
                binding = build_asset_binding(
                    asset_path,
                    page=asset.get("page"),
                    caption_bbox=asset.get("caption_bbox"),
                    crop_bbox=asset.get("crop_bbox"),
                    source_mode=asset.get("source_mode"),
                )
                if binding["path"] != relative_asset.as_posix():
                    raise FigureIndexError("extracted asset path is not content-addressed")
                entries.append(
                    build_figure_entry(
                        str(record.get("id") or ""),
                        kind=asset.get("kind"),
                        number=asset.get("label"),
                        caption=asset.get("caption"),
                        page=asset.get("page"),
                        assets=[binding],
                    )
                )
            figure_index = build_figure_index(
                str(record.get("id") or ""),
                source_artifact=extraction_meta["source_artifact"],
                source_sha256=extraction_meta["source_sha256"],
                extraction_settings=extraction_meta.get("settings", {}),
                entries=entries,
            )
        except FigureIndexError as exc:
            raise SystemExit(f"图表编号或 caption 存在冲突，未更新引用索引：{exc}") from exc
        write_yaml_if_changed(figures_path, figure_index)
        load_current_figure_index(
            figures_path,
            unit_root=unit_root,
            project_root=root,
            expected_index_digest=figure_index["index_digest"],
            expected_source_sha256=extraction_meta["source_sha256"],
        )
        available_refs = {str(item["ref_key"]) for item in figure_index["entries"]}
        record["payload"]["figures"] = {
            "schema": "figure-index/v1",
            "extraction_status": "indexed" if available_refs else "indexed_empty",
            "index_artifact": "figures.yaml",
            "index_digest": figure_index["index_digest"],
            "available_ref_keys": sorted(available_refs),
            "key_figure_refs": sorted(prior_selected & available_refs),
        }
    append_history(
        record,
        action="paper-figures-extracted",
        summary=(
            f"Mechanically indexed {len(available_refs)} stable figure references; "
            f"filtered {len(filtered_assets)} crop candidates."
        ),
        information_types=["fact"],
        artifacts=[rel(root, figures_path)],
    )
    write_record(root, record)
    print(f"图表引用索引已更新：{len(available_refs)} 个稳定引用。")
    _finalize_post_actions(
        root, trigger="milestone", message=f"milestone: extract paper figures {record['id']}", defer_post_actions=defer_post_actions,
        target_paths=[unit_root / "record.yaml", figures_path, unit_root / "figures"],
    )
    return 0


def _auto_post_note_steps(
    root: Path, record: dict, unit_root: Path, source_chunks: list[dict], cache_path: Path, paper_preferences: dict, defer_post_actions: bool
) -> None:
    """After successful note verification, run the safe post-note steps described
    by `docs/DESIGN.md` "Prepare / fill / verify" when enabled by preferences and
    gated by autonomy.auto_execute_scope. Never
    auto-verifies or auto-confirms; never re-parses the cache (F-a). When deferred,
    do nothing (the caller's own defer handles it)."""
    if defer_post_actions:
        return
    autonomy = load_runtime_preferences(root).get("autonomy", {})
    configured = {str(s).strip() for s in autonomy.get("auto_execute_scope", []) if str(s).strip()}
    effective = configured & _GOVERNANCE_MAX_AUTO_STEPS
    if bool(paper_preferences.get("auto_refresh_structure_after_note", True)):
        if "refresh" in effective:
            _run_refresh_structure(root, record, unit_root, source_chunks, cache_path, defer_post_actions=True)
            print("[auto] refresh-structure 已跑（结构已更新，parse-cache 不变）")
        else:
            print(f"[next] refresh-structure 未自动跑（不在 auto_execute_scope）：refresh-structure --paper-id {record['id']}")
    if bool(paper_preferences.get("auto_extract_figures_after_note", False)):
        if "generate-note" in effective:
            _run_extract_figures(root, record, unit_root, source_chunks, defer_post_actions=True)
            print("[auto] extract-figures 已跑（无 backend/图则为空）")
        else:
            print(f"[next] extract-figures 未自动跑（不在 auto_execute_scope）：extract-figures --paper-id {record['id']}")


def _should_auto_prepare_note_after_screen(record: dict, paper_preferences: dict) -> bool:
    """Apply full-note policy only from the post-screen-verify call site."""
    if str(record.get("maturity") or "").strip() == "complete":
        return True
    if not bool(paper_preferences.get("auto_complete_note")):
        return False
    condition = str(paper_preferences.get("auto_complete_note_condition") or "suggested_worth_reading")
    quick = record.get("payload", {}).get("quick_screen", {})
    worth = str(quick.get("worth_deep_reading") or "").strip().lower()
    relevance = str(quick.get("relevance_to_current_research") or "").strip().lower()
    if condition == "after_screen":
        return True
    if condition == "strong_relevance":
        return relevance in {"strong", "moderate"}
    return worth in {"yes", "maybe"}


def _prepare_note_scaffold(
    root: Path,
    record: dict,
    unit_root: Path,
    cache_path: Path,
    source_chunks: list[dict],
    paper_preferences: dict,
    *,
    mode: str,
) -> Path:
    """Create the unified deep-read fill without requiring a screening phase."""
    fill_scaffold_path = unit_root / "note-fill.yaml"
    _assert_safe_paper_input_path(root, fill_scaffold_path)
    if fill_scaffold_path.exists():
        existing = load_yaml(fill_scaffold_path, default={})
        has_agent_fill = bool(
            isinstance(existing, dict)
            and (
                str(existing.get("paper_type") or "").strip()
                or str(existing.get("paper_type_reason") or "").strip()
                or bool(existing.get("paper_type_evidence_refs"))
                or any(
                    str(element.get("content") or "").strip()
                    or bool(element.get("evidence_refs"))
                    for element in _all_note_evidence_items(existing)[1:]
                )
            )
        )
        if has_agent_fill:
            return fill_scaffold_path
    payload = build_note_scaffold(
        record,
        source_chunks,
        _cache_locator_kind(cache_path),
        digest_chunks=int(paper_preferences.get("note_context_pages") or 8),
        digest_chars=int(paper_preferences.get("note_digest_chars") or 1600),
    )
    write_yaml_if_changed(fill_scaffold_path, payload)
    record["maturity"] = "complete"
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    record["information_types"] = ["fact", "inference", "evaluation", "unverified"]
    record["payload"]["state"]["full_note_status"] = "awaiting_agent_fill"
    record["payload"]["state"]["note_generation_mode"] = mode
    append_history(
        record,
        action="paper-note-scaffolded",
        summary="Prepared unified deep-read fill skeleton (script authored nothing).",
        information_types=["inference", "unverified"],
        artifacts=[rel(root, fill_scaffold_path), rel(root, cache_path)],
    )
    write_record(root, record)
    return fill_scaffold_path


def _resolve_fill_input(unit_root: Path, default_name: str, explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = unit_root / explicit
        return candidate
    return unit_root / default_name


class _BoundPaperVerifyFill:
    def __init__(
        self,
        *,
        operation: str,
        unit_root: Path,
        path: Path,
        filename: str,
        descriptor: int,
        unit_identity: tuple[int, int],
        file_identity: tuple[int, int],
        metadata: tuple[int, int, int],
        raw_bytes: bytes,
        payload: object,
        fingerprint: dict[str, object],
    ) -> None:
        self.operation = operation
        self.unit_root = unit_root
        self.path = path
        self.filename = filename
        self.descriptor = descriptor
        self.unit_identity = unit_identity
        self.file_identity = file_identity
        self.metadata = metadata
        self.raw_bytes = raw_bytes
        self.payload = payload
        self.fingerprint = fingerprint

    def close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _open_managed_directory(root: Path, directory: Path) -> tuple[int, tuple[int, int]]:
    """Open an in-workspace directory through no-follow ancestor descriptors."""
    lexical_root = root.absolute()
    lexical_directory = directory.absolute()
    try:
        relative = lexical_directory.relative_to(lexical_root)
    except ValueError as exc:
        raise ValueError("paper verify fill must belong to the current paper unit") from exc
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("paper verify fill must belong to the current paper unit")

    try:
        descriptor = os.open(lexical_root, _directory_open_flags())
    except OSError as exc:
        raise ValueError(
            "paper verify fill path contains a symlink or unavailable workspace root"
        ) from exc
    try:
        root_metadata = os.fstat(descriptor)
        if not stat.S_ISDIR(root_metadata.st_mode):
            raise ValueError("paper workspace root is not a managed directory")
        for part in relative.parts:
            try:
                child = os.open(part, _directory_open_flags(), dir_fd=descriptor)
            except OSError as exc:
                raise ValueError(
                    "paper verify fill path contains a symlink or unavailable ancestor"
                ) from exc
            os.close(descriptor)
            descriptor = child
            if not stat.S_ISDIR(os.fstat(descriptor).st_mode):
                raise ValueError("paper verify fill ancestor is not a managed directory")
        metadata = os.fstat(descriptor)
        return descriptor, (metadata.st_dev, metadata.st_ino)
    except Exception:
        os.close(descriptor)
        raise


def _managed_verify_fill_path(
    root: Path,
    unit_root: Path,
    args: argparse.Namespace,
    *,
    default_name: str,
) -> Path:
    explicit = str(getattr(args, "input", "") or "")
    supplied = Path(explicit).expanduser() if explicit else Path(default_name)
    if ".." in supplied.parts:
        raise ValueError("paper verify fill must belong to the current paper unit")
    candidate = supplied if supplied.is_absolute() else unit_root / supplied
    lexical_unit = unit_root.absolute()
    lexical_candidate = candidate.absolute()
    try:
        relative = lexical_candidate.relative_to(lexical_unit)
    except ValueError as exc:
        raise ValueError("paper verify fill must belong to the current paper unit") from exc
    if len(relative.parts) != 1 or relative.parts[0] in {"", ".", ".."}:
        raise ValueError("paper verify fill must belong to the current paper unit")
    if relative.suffix.casefold() not in {".yaml", ".yml"}:
        raise ValueError("paper verify fill must be a managed YAML file in the current paper unit")
    return lexical_unit / relative


def _read_descriptor_bytes(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = os.read(descriptor, min(1024 * 1024, _MAX_VERIFY_FILL_BYTES + 1 - total))
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total > _MAX_VERIFY_FILL_BYTES:
            raise ValueError("paper verify fill exceeds the managed size limit")
    os.lseek(descriptor, 0, os.SEEK_SET)
    return b"".join(chunks)


def _file_metadata(metadata: os.stat_result) -> tuple[int, int, int]:
    return (metadata.st_size, metadata.st_mtime_ns, metadata.st_ctime_ns)


def _open_managed_verify_fill(
    root: Path,
    unit_root: Path,
    args: argparse.Namespace,
    *,
    default_name: str,
) -> _BoundPaperVerifyFill:
    operation = str(getattr(args, "command", "") or "")
    if operation not in {"screen", "complete-note"} or str(getattr(args, "phase", "") or "") != "verify":
        raise ValueError("managed paper fill binding is only valid for a verify phase")
    path = _managed_verify_fill_path(root, unit_root, args, default_name=default_name)
    unit_descriptor, unit_identity = _open_managed_directory(root, unit_root)
    descriptor = -1
    try:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path.name, flags, dir_fd=unit_descriptor)
        except OSError as exc:
            raise ValueError(
                "paper verify fill path contains a symlink or unavailable leaf"
            ) from exc
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("paper verify fill must be a managed regular file")
        if before.st_nlink != 1:
            raise ValueError("paper verify fill must have a unique managed file identity")
        raw_bytes = _read_descriptor_bytes(descriptor)
        after = os.fstat(descriptor)
        visible = os.stat(path.name, dir_fd=unit_descriptor, follow_symlinks=False)
        if (
            (before.st_dev, before.st_ino) != (after.st_dev, after.st_ino)
            or (after.st_dev, after.st_ino) != (visible.st_dev, visible.st_ino)
            or _file_metadata(before) != _file_metadata(after)
        ):
            raise ValueError("paper verify fill changed while it was being bound")
        try:
            text = raw_bytes.decode("utf-8")
            payload = yaml.safe_load(text) if text.strip() else {}
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise ValueError("paper verify fill is not valid UTF-8 YAML") from exc
        fingerprint = {
            "path_identity_digest": hashlib.sha256(str(path).encode("utf-8")).hexdigest(),
            "state": "regular-file",
            "size": len(raw_bytes),
            "byte_sha256": hashlib.sha256(raw_bytes).hexdigest(),
            "inode_identity_digest": hashlib.sha256(
                f"{after.st_dev}:{after.st_ino}".encode("ascii")
            ).hexdigest(),
        }
        return _BoundPaperVerifyFill(
            operation=operation,
            unit_root=unit_root.absolute(),
            path=path,
            filename=path.name,
            descriptor=descriptor,
            unit_identity=unit_identity,
            file_identity=(after.st_dev, after.st_ino),
            metadata=_file_metadata(after),
            raw_bytes=raw_bytes,
            payload=payload,
            fingerprint=fingerprint,
        )
    except Exception:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    finally:
        os.close(unit_descriptor)


def _managed_verify_fill_fingerprint(
    root: Path,
    unit_root: Path,
    args: argparse.Namespace,
    *,
    default_name: str,
) -> dict[str, object]:
    """Build receipt context safely while allowing a not-yet-created phase fill."""
    path = _managed_verify_fill_path(root, unit_root, args, default_name=default_name)
    unit_descriptor, _unit_identity = _open_managed_directory(root, unit_root)
    try:
        try:
            visible = os.stat(path.name, dir_fd=unit_descriptor, follow_symlinks=False)
        except FileNotFoundError:
            return {
                "path_identity_digest": hashlib.sha256(str(path).encode("utf-8")).hexdigest(),
                "state": "missing",
            }
        if stat.S_ISLNK(visible.st_mode):
            raise ValueError("paper verify fill path contains a symlink leaf")
        if not stat.S_ISREG(visible.st_mode):
            raise ValueError("paper verify fill must be a managed regular file")
    finally:
        os.close(unit_descriptor)
    temporary = _open_managed_verify_fill(
        root,
        unit_root,
        args,
        default_name=default_name,
    )
    try:
        return dict(temporary.fingerprint)
    finally:
        temporary.close()


def _revalidate_managed_verify_fill(root: Path, bound: _BoundPaperVerifyFill) -> None:
    if bound.descriptor < 0:
        raise ValueError("paper verify fill binding is no longer current")
    unit_descriptor, current_unit_identity = _open_managed_directory(root, bound.unit_root)
    try:
        try:
            current = os.stat(bound.filename, dir_fd=unit_descriptor, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("paper verify fill disappeared after binding") from exc
        opened = os.fstat(bound.descriptor)
        if not stat.S_ISREG(current.st_mode) or current.st_nlink != 1:
            raise ValueError("paper verify fill is no longer a unique managed regular file")
        if current_unit_identity != bound.unit_identity:
            raise ValueError("paper verify fill unit changed after binding")
        if (current.st_dev, current.st_ino) != bound.file_identity:
            raise ValueError("paper verify fill inode changed after binding")
        if (opened.st_dev, opened.st_ino) != bound.file_identity:
            raise ValueError("paper verify fill descriptor changed after binding")
        if _file_metadata(opened) != bound.metadata:
            raise ValueError("paper verify fill metadata changed after binding")
        if _read_descriptor_bytes(bound.descriptor) != bound.raw_bytes:
            raise ValueError("paper verify fill bytes changed after binding")
    finally:
        os.close(unit_descriptor)


def _bound_verify_fill(
    root: Path,
    unit_root: Path,
    args: argparse.Namespace,
    *,
    default_name: str,
) -> _BoundPaperVerifyFill:
    bound = getattr(args, "_bound_paper_verify_fill", None)
    if not isinstance(bound, _BoundPaperVerifyFill):
        raise ValueError("paper verify fill was not safely bound")
    expected = _managed_verify_fill_path(root, unit_root, args, default_name=default_name)
    if bound.operation != str(args.command) or bound.path != expected:
        raise ValueError("paper verify fill binding belongs to another phase or unit")
    _revalidate_managed_verify_fill(root, bound)
    return bound


def _prevalidate_bound_verify_fill(
    args: argparse.Namespace,
    record: dict,
    unit_root: Path,
    bound: _BoundPaperVerifyFill,
) -> None:
    payload = bound.payload
    operation = str(getattr(args, "command", "") or "")
    if not isinstance(payload, dict):
        raise SystemExit(f"{operation} --phase verify: managed fill input is not a mapping")
    expected_paper_id = str(record.get("id") or "")
    declared_paper_id = str(payload.get("paper_id") or "").strip()
    binding_violations: list[str] = []
    if declared_paper_id and declared_paper_id != expected_paper_id:
        binding_violations.append("paper_id: fill belongs to another paper unit")
    if operation == "screen":
        violations = verify_screening_fill(payload, unit_root)
        evidence_items = read_claims(payload)
        verified_claims: list[dict] = []
        label = "screening"
    else:
        violations, verified_claims = verify_note_fill(payload, unit_root, record)
        evidence_items = _all_note_evidence_items(payload)
        label = "note"
    for item in evidence_items:
        if not isinstance(item, Mapping):
            continue
        for evidence_ref in item.get("evidence_refs") or []:
            if not isinstance(evidence_ref, Mapping):
                continue
            source_unit_id = str(evidence_ref.get("source_unit_id") or "").strip()
            if source_unit_id and source_unit_id != expected_paper_id:
                binding_violations.append(
                    "evidence_ref.source_unit_id: fill belongs to another paper unit"
                )
    violations = [*binding_violations, *violations]
    if violations:
        print(f"[reject] {label} fill failed verification:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        raise SystemExit(1)
    setattr(
        args,
        "_prevalidated_paper_verify_fill",
        {
            "operation": operation,
            "file_identity": bound.file_identity,
            "payload": payload,
            "claims": verified_claims,
        },
    )


def _prevalidated_verify_fill(
    args: argparse.Namespace,
    bound: _BoundPaperVerifyFill,
) -> tuple[dict, list[dict]]:
    validated = getattr(args, "_prevalidated_paper_verify_fill", None)
    if not isinstance(validated, Mapping):
        raise ValueError("paper verify fill was not prevalidated")
    if (
        str(validated.get("operation") or "") != bound.operation
        or validated.get("file_identity") != bound.file_identity
        or validated.get("payload") is not bound.payload
    ):
        raise ValueError("paper verify fill prevalidation belongs to another input")
    payload = validated.get("payload")
    claims = validated.get("claims")
    if not isinstance(payload, dict) or not isinstance(claims, list):
        raise ValueError("paper verify fill prevalidation is malformed")
    return payload, claims


def _unit_owned_fill_path(unit_root: Path, fill_path: Path) -> Path | None:
    """Return a checkpoint-safe fill only when it resolves inside this unit."""
    try:
        fill_path.resolve().relative_to(unit_root.resolve())
    except (OSError, ValueError):
        return None
    return fill_path


def next_for_agent_note(root: Path, record: dict, cache_path: Path, fill_path: Path) -> str:
    """One private navigation line for the Agent protocol in `docs/DESIGN.md`.

    Pure navigation: it names the parse-cache artifact to read, the elements to fill
    (each needs a verbatim quote + locator), and the exact verify command to run after.
    It authors no judgement — the agent still fills the understanding.
    """
    element_sets = ";".join(
        f"{paper_type}={','.join(elements)}"
        for paper_type, elements in ELEMENT_SETS.items()
    )
    verify_cmd = (
        f"${{RESEARCH_PYTHON:-python3}} {SCRIPT_PATH} --root {root} "
        f"complete-note --paper-id {record['id']} --phase verify --input {fill_path.name}"
    )
    return (
        f"NEXT FOR AGENT: read {rel(root, cache_path)} (source quotes) then fill {rel(root, fill_path)} "
        f"paper_type + reason/evidence, then one branch [{element_sets}] — each selected element needs content + >=1 verbatim quote+locator "
        f"(PDF page=N / HTML section:<anchor>), then run: {verify_cmd}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare fillable paper structures + verify agent-filled understanding.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    prewarm = subparsers.add_parser("prewarm-cache")
    prewarm.add_argument("--paper-id", required=True)
    prewarm.add_argument("--force", action="store_true")
    prewarm.add_argument("--defer-post-actions", action="store_true")
    prewarm.add_argument("--preference-selection-id", default="")

    screen = subparsers.add_parser("screen")
    screen.add_argument("--paper-id", required=True)
    screen.add_argument("--phase", choices=["prepare", "verify"], default="prepare")
    screen.add_argument("--input", default="")
    screen.add_argument("--mode", default="auto")
    screen.add_argument("--defer-post-actions", action="store_true")
    screen.add_argument("--preference-selection-id", default="")

    note = subparsers.add_parser("complete-note")
    note.add_argument("--paper-id", required=True)
    note.add_argument("--phase", choices=["prepare", "verify"], default="prepare")
    note.add_argument("--input", default="")
    note.add_argument("--mode", default="auto")
    note.add_argument("--defer-post-actions", action="store_true")
    note.add_argument("--preference-selection-id", default="")

    figures = subparsers.add_parser("extract-figures")
    figures.add_argument("--paper-id", required=True)
    figures.add_argument("--defer-post-actions", action="store_true")
    figures.add_argument("--preference-selection-id", default="")

    structure = subparsers.add_parser("refresh-structure")
    structure.add_argument("--paper-id", required=True)
    structure.add_argument("--defer-post-actions", action="store_true")
    structure.add_argument("--preference-selection-id", default="")

    confirm = subparsers.add_parser("confirm")
    confirm.add_argument("--paper-id", required=True)
    add_confirmation_arguments(confirm)
    confirm.add_argument("--defer-post-actions", action="store_true")

    reject = subparsers.add_parser("reject")
    reject.add_argument("--paper-id", required=True)
    reject.add_argument("--defer-post-actions", action="store_true")
    return parser


def _preference_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _record_content_digest(record: Mapping[str, object]) -> str:
    """Bind current record content without self-binding prior preference receipts."""
    snapshot = dict(record)
    payload = snapshot.get("payload")
    if isinstance(payload, Mapping):
        payload = dict(payload)
        payload.pop("preference_binding", None)
        payload.pop("preference_contract", None)
        snapshot["payload"] = payload
    return _preference_digest(snapshot)


def _artifact_fingerprint(root: Path, path: Path) -> dict[str, object]:
    """Content-bind an input without exposing its raw path in a receipt context."""
    _assert_safe_paper_input_path(root, path)
    identity = hashlib.sha256(str(path.absolute()).encode("utf-8")).hexdigest()
    fingerprint: dict[str, object] = {"path_identity_digest": identity}
    if not path.exists():
        fingerprint["state"] = "missing"
        return fingerprint
    if not path.is_file():
        fingerprint["state"] = "non-file"
        return fingerprint
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError:
        fingerprint["state"] = "unreadable"
        return fingerprint
    fingerprint.update(
        {
            "state": "regular-file",
            "size": size,
            "byte_sha256": digest.hexdigest(),
        }
    )
    return fingerprint


def paper_preference_context(
    root: Path,
    args: argparse.Namespace,
    record: Mapping[str, object],
    *,
    unit_root: Path | None = None,
) -> dict[str, object]:
    """Owner-recomputed content binding for one paper preference operation."""
    canonical_unit_root = unit_root or (
        kb_root(root) / "units" / "papers" / str(record.get("id") or "")
    )
    cache_path = _cache_path(canonical_unit_root)
    operation = str(args.command)
    phase = str(getattr(args, "phase", "") or "")
    source_identity = {
        "source": record.get("source"),
        "sources": record.get("sources"),
    }
    auxiliary: dict[str, dict[str, object]] = {}
    if operation == "complete-note" and phase == "prepare":
        for name in ("note-fill.yaml", "note.md"):
            auxiliary[name] = _artifact_fingerprint(root, canonical_unit_root / name)
    elif operation == "screen" and phase == "verify":
        auxiliary["note-fill.yaml"] = _artifact_fingerprint(
            root,
            canonical_unit_root / "note-fill.yaml"
        )
    elif operation == "refresh-structure":
        auxiliary["note.md"] = _artifact_fingerprint(root, canonical_unit_root / "note.md")

    fill_input: dict[str, object] | None = None
    if operation in {"screen", "complete-note"} and phase == "verify":
        default_name = "screening.yaml" if operation == "screen" else "note-fill.yaml"
        bound = getattr(args, "_bound_paper_verify_fill", None)
        if isinstance(bound, _BoundPaperVerifyFill):
            expected = _managed_verify_fill_path(
                root, canonical_unit_root, args, default_name=default_name
            )
            if bound.operation != operation or bound.path != expected:
                raise ValueError("paper verify fill binding belongs to another phase or unit")
            _revalidate_managed_verify_fill(root, bound)
            fill_input = dict(bound.fingerprint)
        else:
            fill_input = _managed_verify_fill_fingerprint(
                root,
                canonical_unit_root,
                args,
                default_name=default_name,
            )

    return {
        "paper_id": str(record.get("id") or ""),
        "operation": operation,
        "phase": phase,
        "mode": str(getattr(args, "mode", "") or ""),
        "force": bool(getattr(args, "force", False)),
        "defer_post_actions": bool(getattr(args, "defer_post_actions", False)),
        "record_content_digest": _record_content_digest(record),
        "source_identity_digest": _preference_digest(source_identity),
        "parse_cache": _artifact_fingerprint(root, cache_path),
        "source_artifacts": [
            _artifact_fingerprint(root, path) for path in _source_paths(root, dict(record))
        ],
        "auxiliary_artifacts": auxiliary,
        "fill_input": fill_input,
    }


def resolve_paper_preferences(
    root: Path,
    args: argparse.Namespace,
    record: Mapping[str, object],
    *,
    unit_root: Path | None = None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    """Resolve only selected soft values for the bound paper operation."""
    selection_id = str(getattr(args, "preference_selection_id", "") or "")
    if not selection_id:
        return {}, {}, {}
    effective = resolve_task_preferences(
        root,
        selection_id=selection_id,
        skill="paper-analyst",
        operation=args.command,
        canonical_inputs=paper_preference_context(root, args, record, unit_root=unit_root),
    )
    selected = {
        str(item.get("path") or ""): item.get("value")
        for item in effective.get("effective_items", [])
        if isinstance(item, dict)
    }
    paper = selected.get("runtime.paper")
    pdf = selected.get("runtime.pdf")
    return (
        dict(paper) if isinstance(paper, dict) else {},
        dict(pdf) if isinstance(pdf, dict) else {},
        selection_binding(effective),
    )


@_transactional(
    "screen",
    lambda args, root, record, unit_root, cache_path, source_chunks, paper_preferences, defer_post_actions: (
        root,
        [
            unit_root / "record.yaml",
            unit_root / "screening.yaml",
            unit_root / "note-fill.yaml",
            *([] if defer_post_actions else _index_targets(root)),
        ],
    ),
)
def _run_screen(args, root, record, unit_root, cache_path, source_chunks, paper_preferences, defer_post_actions) -> int:
    screen_path = unit_root / "screening.yaml"
    cache_locator_kind = _cache_locator_kind(cache_path)

    if args.phase == "prepare":
        payload = build_screening_scaffold(
            record,
            source_chunks,
            cache_locator_kind,
            digest_chunks=int(paper_preferences.get("screening_context_pages") or 6),
            digest_chars=int(paper_preferences.get("screening_digest_chars") or 1200),
        )
        write_yaml_if_changed(screen_path, payload)
        record = apply_record_governance(root, record, infer_missing=True, source_label="paper-analyst")
        record["status"] = "screened"
        if record.get("maturity") != "complete":
            record["maturity"] = "lightweight"
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        record["information_types"] = ["fact", "inference", "unverified"]
        record["payload"].setdefault("quick_screen", {})["recommended_next_action"] = (
            "screen --phase verify (legacy compatibility only)"
        )
        append_history(
            record,
            action="paper-screen-prepared",
            summary="Prepared fillable screening scaffold (no script grading).",
            information_types=["inference", "unverified"],
            artifacts=[rel(root, screen_path), rel(root, cache_path)],
        )
        write_record(root, record)
        print(f"[ok] wrote {screen_path.relative_to(root)}")
        print("下一步：runtime agent 填 worth_deep_reading + judgement_reason + claims(带证据)，再运行 screen --phase verify。")
        _finalize_post_actions(root, trigger="milestone", message=f"milestone: prepare screen {args.paper_id}", defer_post_actions=defer_post_actions,
                               target_paths=[unit_root / "record.yaml", screen_path])
        return 0

    # verify
    bound_fill = _bound_verify_fill(
        root, unit_root, args, default_name="screening.yaml"
    )
    payload, _verified_claims = _prevalidated_verify_fill(args, bound_fill)

    worth = _normalized_worth_deep_reading(payload.get("worth_deep_reading"))
    paper_type = str(payload.get("paper_type") or "").strip().lower()
    reasons = [str(item).strip() for item in (payload.get("judgement_reason") or []) if str(item).strip()]
    relevance = str(payload.get("relevance_to_current_research") or "").strip()
    attach_claims(payload, read_claims(payload))
    payload["worth_deep_reading"] = worth
    payload["status"] = "verified"
    payload["phase"] = "verify"
    _revalidate_managed_verify_fill(root, bound_fill)
    write_yaml_if_changed(screen_path, payload)
    record = apply_record_governance(root, record, infer_missing=True, source_label="paper-analyst")
    quick = record["payload"].setdefault("quick_screen", {})
    quick["paper_type"] = paper_type
    quick["worth_deep_reading"] = worth
    quick["judgement_reason"] = reasons
    quick["relevance_to_current_research"] = relevance
    for dimension in SCREENING_DIMENSION_RATINGS:
        value = payload.get(dimension)
        if isinstance(value, Mapping):
            quick[dimension] = {
                "status": str(value.get("status") or "").strip().casefold(),
                "rating": str(value.get("rating") or "").strip().casefold(),
                "reason": str(value.get("reason") or "").strip(),
                "claim_ids": [
                    str(item).strip()
                    for item in (value.get("claim_ids") or [])
                    if str(item).strip()
                ],
            }
    quick["recommended_next_action"] = "complete-note" if worth in {"yes", "maybe"} else "defer-or-confirm"
    attach_claims(record.setdefault("payload", {}), read_claims(payload))
    build_verification_receipt(record, unit_root)
    record["status"] = "screened"
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    record["information_types"] = ["fact", "evaluation", "inference", "unverified"]
    if reasons:
        record["summary"] = reasons[0]
    append_history(
        record,
        action="paper-screen-verified",
        summary="Verified agent screening judgement (evidence-grounded).",
        information_types=["evaluation", "inference", "unverified"],
        artifacts=[rel(root, screen_path), rel(root, cache_path)],
    )
    write_record(root, record)
    print(f"[ok] verified + persisted {screen_path.relative_to(root)} (worth_deep_reading={worth})")
    note_scaffold_path: Path | None = None
    if _should_auto_prepare_note_after_screen(record, paper_preferences):
        autonomy = load_runtime_preferences(root).get("autonomy", {})
        configured = {str(item).strip() for item in autonomy.get("auto_execute_scope", []) if str(item).strip()}
        if "generate-note" in (configured & _GOVERNANCE_MAX_AUTO_STEPS):
            mode = str(paper_preferences.get("complete_note_mode") or "scaffold")
            note_scaffold_path = _prepare_note_scaffold(
                root,
                record,
                unit_root,
                cache_path,
                source_chunks,
                paper_preferences,
                mode=mode,
            )
            print(f"[auto] 已按已验证 paper_type 准备 {note_scaffold_path.relative_to(root)}")
        else:
            print("[next] 完整笔记未自动准备（不在 auto_execute_scope）；paper_type 已验证，可继续准备类型专属笔记。")
    screen_targets = [unit_root / "record.yaml", screen_path]
    if note_scaffold_path is not None:
        screen_targets.append(note_scaffold_path)
    _finalize_post_actions(root, trigger="milestone", message=f"milestone: verify screen {args.paper_id}", defer_post_actions=defer_post_actions,
                           target_paths=screen_targets)
    return 0


@_transactional(
    "complete-note",
    lambda args, root, record, unit_root, cache_path, source_chunks, paper_preferences, defer_post_actions: (
        root,
        [
            unit_root / "record.yaml",
            unit_root / "note-fill.yaml",
            unit_root / "note.md",
            unit_root / "note-claims.yaml",
            unit_root / "structure.yaml",
            unit_root / "figures.yaml",
            unit_root / "figures",
            *([] if defer_post_actions else _index_targets(root)),
        ],
    ),
)
def _run_complete_note(args, root, record, unit_root, cache_path, source_chunks, paper_preferences, defer_post_actions) -> int:
    fill_scaffold_path = unit_root / "note-fill.yaml"
    note_path = unit_root / "note.md"
    mode = str(args.mode or "auto")
    if mode == "auto":
        mode = str(paper_preferences.get("complete_note_mode") or "scaffold")

    if args.phase == "prepare":
        _assert_safe_paper_input_path(root, fill_scaffold_path)
        _assert_safe_paper_input_path(root, note_path)
        fill_scaffold_path = _prepare_note_scaffold(
            root,
            record,
            unit_root,
            cache_path,
            source_chunks,
            paper_preferences,
            mode=mode,
        )
        print(f"[ok] wrote {fill_scaffold_path.relative_to(root)}")
        print("下一步：runtime agent 先填写论文类型、分类理由与证据，再只填写对应五要素分支。")
        print(next_for_agent_note(root, record, cache_path, fill_scaffold_path))
        _finalize_post_actions(root, trigger="milestone", message=f"milestone: scaffold note {args.paper_id}", defer_post_actions=defer_post_actions,
                               target_paths=[unit_root / "record.yaml", fill_scaffold_path])
        return 0

    # verify
    bound_fill = _bound_verify_fill(
        root, unit_root, args, default_name="note-fill.yaml"
    )
    fill_path = bound_fill.path
    _fill, claims = _prevalidated_verify_fill(args, bound_fill)

    _revalidate_managed_verify_fill(root, bound_fill)
    _apply_note_fill_to_payload(record, claims)
    attach_claims(record.setdefault("payload", {}), claims)
    build_verification_receipt(record, unit_root)
    write_text_if_changed(note_path, render_note_md(record, claims))
    note_payload = {"paper_id": record["id"], "kind": "paper"}
    attach_claims(note_payload, claims)
    write_yaml_if_changed(unit_root / "note-claims.yaml", note_payload)
    record["maturity"] = "complete"
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    record["information_types"] = ["fact", "inference", "evaluation", "user_opinion", "unverified"]
    record["payload"]["state"]["full_note_status"] = "pending_user_confirmation"
    record["payload"]["state"]["note_generation_mode"] = mode
    append_history(
        record,
        action="paper-note-verified",
        summary="Verified + persisted agent 5-element note (evidence-grounded).",
        information_types=["inference", "evaluation", "unverified"],
        artifacts=[rel(root, note_path), rel(root, cache_path)],
    )
    write_record(root, record)
    print(
        f"[ok] verified + wrote {note_path.relative_to(root)} "
        f"(paper type + {max(0, len(claims) - 1)} elements)"
    )
    _auto_post_note_steps(root, record, unit_root, source_chunks, cache_path, paper_preferences, defer_post_actions)
    note_targets = [unit_root / "record.yaml", note_path, unit_root / "note-claims.yaml", unit_root / "structure.yaml", unit_root / "figures.yaml", unit_root / "figures"]
    owned_fill = _unit_owned_fill_path(unit_root, fill_path)
    if owned_fill is not None:
        note_targets.insert(1, owned_fill)
    _finalize_post_actions(root, trigger="milestone", message=f"milestone: verify note {args.paper_id}", defer_post_actions=defer_post_actions,
                           target_paths=note_targets)
    return 0


@_transactional(
    "confirm",
    lambda args, root, record, unit_root, defer_post_actions: (
        root,
        [unit_root / "record.yaml", *([] if defer_post_actions else _index_targets(root))],
    ),
)
def _run_confirm(args, root: Path, record: dict, unit_root: Path, defer_post_actions: bool) -> int:
    expected_record_snapshot = canonical_record_snapshot_for_record(root, record)
    record = confirm_unit(
        record,
        "paper",
        confirmed_by=args.confirmed_by,
        evidence=args.evidence,
        user_authorization=args.user_authorization,
        authorization_source=args.authorization_source,
        method="paper.py confirm",
        project_root=root,
        expected_record_snapshot=expected_record_snapshot,
    )
    write_record(root, record, expected_record_snapshot=expected_record_snapshot)
    print(f"[ok] confirmed {args.paper_id}")
    _finalize_post_actions(
        root,
        trigger="milestone",
        message=f"milestone: confirm paper {args.paper_id}",
        defer_post_actions=defer_post_actions,
        target_paths=[unit_root / "record.yaml"],
    )
    return 0


@_transactional(
    "reject",
    lambda args, root, record, unit_root, defer_post_actions: (
        root,
        [unit_root / "record.yaml", *([] if defer_post_actions else _index_targets(root))],
    ),
)
def _run_reject(args, root: Path, record: dict, unit_root: Path, defer_post_actions: bool) -> int:
    record["confirmation_status"] = "rejected"
    record["status"] = "rejected"
    append_history(record, action="paper-rejected", summary="Paper analysis rejected or deferred.", information_types=["evaluation"])
    write_record(root, record)
    print(f"[ok] rejected {args.paper_id}")
    _finalize_post_actions(
        root,
        trigger="milestone",
        message=f"milestone: reject paper {args.paper_id}",
        defer_post_actions=defer_post_actions,
        target_paths=[unit_root / "record.yaml"],
    )
    return 0


def _dispatch_loaded_command(
    args: argparse.Namespace,
    root: Path,
    record: dict,
    path: Path,
) -> int:
    unit_root = path.parent
    defer_post_actions = bool(getattr(args, "defer_post_actions", False))
    paper_preferences: dict[str, object] = {}
    pdf_preferences: dict[str, object] = {}
    if args.command in SKILL_OPERATIONS["paper-analyst"]:
        paper_preferences, pdf_preferences, preference_binding = resolve_paper_preferences(
            root, args, record, unit_root=unit_root
        )
        record.setdefault("payload", {})["preference_contract"] = operation_contract(
            skill="paper-analyst", operation=args.command
        )
        if preference_binding:
            record["payload"]["preference_binding"] = preference_binding

    if args.command == "screen" and not _has_legacy_quick_screen(record):
        raise SystemExit(
            "screen is retained only for paper records created with the legacy quick-screen schema"
        )

    source_chunks: list[dict] = []
    cache_path = _cache_path(unit_root)
    if args.command in {"prewarm-cache", "screen", "complete-note", "extract-figures", "refresh-structure"}:
        _assert_safe_paper_input_path(root, cache_path)
        if (
            str(getattr(args, "phase", "") or "") == "verify"
            and args.command in {"screen", "complete-note"}
            and not cache_path.exists()
        ):
            raise SystemExit(
                "paper verify requires the existing managed parse cache; prepare the phase first"
            )
        # refresh-structure re-derives structure.yaml from the EXISTING parse-cache;
        # it must NOT force a re-parse — doing so re-runs prewarm with the truncation
        # prefs (front_limit/back_limit) and overwrites the full intake cache, deleting
        # later pages and breaking evidence idempotency (F-a). Only explicit --force
        # (prewarm-cache) may re-parse.
        force_cache = bool(getattr(args, "force", False))
        if force_cache or not cache_path.exists():
            with command_mutation(
                root,
                "paper-analyst:prewarm-cache",
                [cache_path],
                allow_operational_state=True,
            ):
                source_chunks, cache_path = _load_or_refresh_cache(
                    root,
                    record,
                    unit_root,
                    force=force_cache,
                    preferences=paper_preferences,
                )
        else:
            source_chunks, cache_path = _load_or_refresh_cache(
                root,
                record,
                unit_root,
                force=False,
                preferences=paper_preferences,
            )

    if args.command == "prewarm-cache":
        print(f"[ok] wrote {cache_path.relative_to(root)}")
        print(f"[ok] cached chunks: {len(source_chunks)}")
        return 0

    if args.command == "screen":
        return _run_screen(args, root, record, unit_root, cache_path, source_chunks, paper_preferences, defer_post_actions)

    if args.command == "complete-note":
        return _run_complete_note(args, root, record, unit_root, cache_path, source_chunks, paper_preferences, defer_post_actions)

    if args.command == "extract-figures":
        return _run_extract_figures(
            root,
            record,
            unit_root,
            source_chunks,
            defer_post_actions=defer_post_actions,
            pdf_preferences=pdf_preferences,
        )

    if args.command == "refresh-structure":
        return _run_refresh_structure(root, record, unit_root, source_chunks, cache_path, defer_post_actions=defer_post_actions)

    if args.command == "confirm":
        return _run_confirm(args, root, record, unit_root, defer_post_actions)

    if args.command == "reject":
        return _run_reject(args, root, record, unit_root, defer_post_actions)

    return 1


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    record, path = locate_record(root, args.paper_id, kind="paper")
    if record.get("kind") != "paper":
        raise SystemExit(f"{args.paper_id} is not a paper record")
    bound_fill: _BoundPaperVerifyFill | None = None
    if (
        str(getattr(args, "phase", "") or "") == "verify"
        and args.command in {"screen", "complete-note"}
    ):
        default_name = "screening.yaml" if args.command == "screen" else "note-fill.yaml"
        bound_fill = _open_managed_verify_fill(
            root,
            path.parent,
            args,
            default_name=default_name,
        )
        setattr(args, "_bound_paper_verify_fill", bound_fill)
    try:
        return _dispatch_loaded_command(args, root, record, path)
    finally:
        if bound_fill is not None:
            bound_fill.close()


if __name__ == "__main__":
    raise SystemExit(main())
