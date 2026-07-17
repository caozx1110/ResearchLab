#!/usr/bin/env python3
"""Paper analyst: script prepares fillable structure + verifies evidence; a runtime
agent fills the understanding (SSOT Principle 1 / §3.2).

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
import re
import sys
from contextvars import ContextVar
from datetime import datetime
from functools import wraps
from pathlib import Path
from typing import Any, Sequence

SCRIPT_PATH = Path(__file__).resolve()
for candidate in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents]:
    lib = candidate / ".agents" / "lib"
    if lib.exists():
        sys.path.insert(0, str(lib))
        PROJECT_ROOT = candidate
        break
else:
    raise SystemExit("Could not locate .agents/lib")

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.common import add_project_root_argument, clean_text, extract_pdf_context_pages, load_yaml, print_resolved_project_roots, read_text_excerpt, write_text_if_changed, write_yaml_if_changed
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
    confirm_unit,
    load_runtime_preferences,
    locate_record,
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


def _index_targets(root: Path) -> list[Path]:
    return [
        root / "kb" / "index.yaml",
        root / "kb" / "index.md",
        topic_taxonomy_path(root),
        candidate_pools_path(root),
    ]


def _transactional(op_name: str, target_builder):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            root, targets = target_builder(*args, **kwargs)
            active_token = _ACTIVE_MUTATION.set(True)
            checkpoint_token = _PENDING_CHECKPOINT.set(None)
            try:
                with command_mutation(root, f"paper-analyst:{op_name}", targets):
                    result = function(*args, **kwargs)
                pending = _PENDING_CHECKPOINT.get()
            finally:
                _PENDING_CHECKPOINT.reset(checkpoint_token)
                _ACTIVE_MUTATION.reset(active_token)
            if pending is not None:
                checkpoint_and_report(
                    pending[0], trigger=pending[1], message=pending[2], target_paths=pending[3]
                )
            return result

        return wrapped

    return decorate

PAPER_TYPES: tuple[str, ...] = ("method_system", "benchmark", "survey")

# --------------------------------------------------------------------------- #
# Per-paper-type 5-element fill contracts (SSOT §3.2).                         #
#                                                                             #
# A runtime agent classifies the paper during screening and fills the selected #
# five elements; every element is a judgement-class claim and MUST carry >=1   #
# evidence_ref. The script only selects, verifies, and routes the structure.    #
# --------------------------------------------------------------------------- #
ELEMENT_SETS: dict[str, tuple[str, ...]] = {
    "method_system": ("motivation", "method", "experiment", "limitation", "insight"),
    "benchmark": ("motivation", "task_design", "metrics", "coverage_limitation", "insight"),
    "survey": ("scope", "taxonomy", "trends", "gaps", "insight"),
}

# Compatibility alias for callers that explicitly refer to the historical set.
NOTE_ELEMENTS: tuple[str, ...] = ELEMENT_SETS["method_system"]

# Every element is judgement-class so research.evidence.validate_claims enforces a
# non-empty evidence_refs on each (SSOT Principle 2 gate interlock).
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


def elements_for(record_or_type: dict | str) -> tuple[str, ...]:
    """Select the agent-authored element set; missing/unknown type is method_system."""
    if isinstance(record_or_type, str):
        paper_type = record_or_type
    elif isinstance(record_or_type, dict):
        payload = record_or_type.get("payload")
        quick_screen = payload.get("quick_screen") if isinstance(payload, dict) else None
        paper_type = quick_screen.get("paper_type") if isinstance(quick_screen, dict) else record_or_type.get("paper_type")
    else:
        paper_type = ""
    normalized = str(paper_type or "").strip().lower()
    return ELEMENT_SETS.get(normalized, ELEMENT_SETS["method_system"])

# Reusable, machine-readable description of the evidence_ref shape an agent must fill.
EVIDENCE_REF_FORMAT: dict[str, str] = {
    "source_unit_id": "p-... (this paper unit id)",
    "artifact": "parse-cache.yaml (unit-relative artifact the quote lives in)",
    "locator": "PDF: page=N ; HTML: section or section:<anchor> (B4)",
    "quote": "short verbatim snippet — script checks it is a whitespace-normalized substring of the artifact",
    "summary": "optional one-line paraphrase",
}


def add_confirmation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--confirmed-by", default="")
    parser.add_argument("--evidence", action="append", required=True)
    parser.add_argument("--user-authorization", default="")
    parser.add_argument("--authorization-source", default="")


def _source_paths(root: Path, record: dict) -> list[Path]:
    paths: list[Path] = []
    source = record.get("source", {})
    for backup in source.get("backup_paths", []):
        path = root / str(backup)
        if path.exists():
            paths.append(path)
    original_uri = str(source.get("original_uri") or "")
    if original_uri and not original_uri.startswith("http"):
        path = resolve_local_reference(root, original_uri) or Path(original_uri).expanduser()
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


def _paper_preferences(root: Path) -> dict[str, Any]:
    return load_runtime_preferences(root).get("paper", {})


def _load_or_refresh_cache(root: Path, record: dict, unit_root: Path, *, force: bool = False) -> tuple[list[dict], Path]:
    preferences = _paper_preferences(root)
    cache_path = _cache_path(unit_root)
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
    """Derive the evidence locator string for a parse-cache chunk (B4 two families).

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

    This is the "备料" (transport) half of Principle 1: it hands the agent the raw
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
    judgement field from this list (SSOT Principle 1).
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
                "Agent fills worth_deep_reading (yes|no|maybe) + judgement_reason + "
                "paper_type (method_system|benchmark|survey) + relevance_to_current_research, "
                "and attaches judgement claims to `claims` "
                "with verbatim evidence. Then run `screen --phase verify` to validate + persist. "
                "The script does NOT decide worth — that judgement is the agent's (SSOT §3.2)."
            ),
            "worth_deep_reading": "agent fills: yes|no|maybe",
            "paper_type": "agent fills: method_system|benchmark|survey",
            "judgement_reason": "agent fills: list of short reasons",
            "relevance_to_current_research": "agent fills: strong|moderate|weak + why",
            "claims": "agent attaches judgement claims backing paper_type and worth_deep_reading",
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
    worth = str(payload.get("worth_deep_reading") or "").strip().lower()
    if worth not in {"yes", "no", "maybe"}:
        violations.append(
            f"worth_deep_reading: agent must fill one of yes|no|maybe (got {worth or '<blank>'!r})"
        )
    claims = read_claims(payload)
    violations.extend(validate_claims(claims))
    for claim in claims:
        for violation in verify_claim_evidence(claim, unit_dir):
            violations.append(f"screening claim: {violation}")
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
    """Produce the selected type's fillable note skeleton; script authors nothing."""
    digest = _evidence_digest(source_chunks, cache_locator_kind, chunk_limit=digest_chunks, excerpt_chars=digest_chars)
    required_elements = elements_for(record)
    paper_type = str(record.get("payload", {}).get("quick_screen", {}).get("paper_type") or "method_system")
    if paper_type not in ELEMENT_SETS:
        paper_type = "method_system"
    elements = [
        {
            "element": name,
            "claim_type": ELEMENT_CLAIM_TYPE[name],
            "content": "",
            "evidence_refs": [],
        }
        for name in required_elements
    ]
    return {
        "paper_id": record["id"],
        "kind": "paper",
        "paper_type": paper_type,
        "status": "awaiting_agent_fill",
        "phase": "prepare",
        "fill_contract": {
            "description": (
                "Agent fills all required_elements for the selected paper_type with its own understanding, each "
                "backed by >=1 verbatim evidence_ref. Then run `complete-note --phase verify` "
                "to validate + verbatim-check evidence + write note.md + core_content. Empty or "
                "unevidenced elements are rejected; the script never authors content (SSOT §3.2)."
            ),
            "required_elements": list(required_elements),
            "element_claim_types": {name: ELEMENT_CLAIM_TYPE[name] for name in required_elements},
            "evidence_ref_format": EVIDENCE_REF_FORMAT,
        },
        "evidence_digest": digest,
        # --- agent fills each element.content + element.evidence_refs below ---
        "elements": elements,
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


def _claim_from_element(name: str, element: dict) -> dict:
    return {
        "id": f"claim-{name}",
        "text": clean_text(str(element.get("content") or "")),
        "claim_type": str(element.get("claim_type") or ELEMENT_CLAIM_TYPE.get(name, "inference")),
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": element.get("evidence_refs") or [],
    }


def verify_note_fill(fill: Any, unit_dir: Path, record: dict | None = None) -> tuple[list[str], list[dict]]:
    """Validate an agent-filled type-specific note. Returns (violations, claims).

    Violations name the offending element. All selected elements must be present, carry
    non-empty content, be structurally valid (validate_claims), and every evidence_ref
    quote must verify verbatim against the artifact (verify_claim_evidence).
    """
    violations: list[str] = []
    elements = _elements_by_name(fill)
    required_elements = elements_for(record or "method_system")
    unexpected = sorted(set(elements) - set(required_elements))
    for name in unexpected:
        violations.append(f"element '{name}': unexpected for selected paper type")
    claims: list[dict] = []
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
        "> 本笔记由 runtime agent 依据 parse-cache 填写；脚本已逐字校验每条 evidence（SSOT 原则1/原则2）。",
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
        "status": "pending_user_confirmation",
        "information_types": ["fact", "inference", "unverified"],
        "candidate_figures": mentions,
        "key_figures": extracted_assets or [],
        "open_questions": [
            "caption 裁剪是否已经覆盖了论文里真正需要复用的整张 Figure / Table？",
            "是否仍有极少数跨栏或无 caption 的对象需要人工补裁？",
        ],
    }


def _extract_pdf_images(root: Path, record: dict, unit_root: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    pdf_path = next((path for path in _source_paths(root, record) if path.suffix.lower() == ".pdf"), None)
    if pdf_path is None:
        return [], [{"status": "missing-pdf", "reason": "No PDF source found"}], {"mode": "none", "captions_detected": 0}
    preferences = load_runtime_preferences(root).get("pdf", {})
    include_tables = bool(preferences.get("figure_include_tables", True))
    filter_blank_and_mask = bool(preferences.get("filter_blank_and_mask_images", True))
    render_scale = float(preferences.get("figure_render_scale") or LAYOUT_DEFAULT_RENDER_SCALE)
    crop_padding_pt = float(preferences.get("figure_crop_padding_pt") or LAYOUT_DEFAULT_CROP_PADDING_PT)
    figures_root = unit_root / "figures"

    return extract_caption_region_assets(
        lambda path: rel(root, path),
        pdf_path,
        figures_root,
        include_tables=include_tables,
        render_scale=render_scale,
        crop_padding_pt=crop_padding_pt,
        filter_blank_and_mask=filter_blank_and_mask,
    )


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
    lambda root, record, unit_root, source_chunks, *, defer_post_actions: (
        root,
        [unit_root / "record.yaml", unit_root / "figures.yaml", unit_root / "figures", *([] if defer_post_actions else _index_targets(root))],
    ),
)
def _run_extract_figures(
    root: Path, record: dict, unit_root: Path, source_chunks: list[dict], *, defer_post_actions: bool
) -> int:
    """Extract figure assets (best-effort; empty when no PDF backend / no figures)
    and index figure mentions. Shared by the CLI dispatch and the auto-post-note step."""
    figures_path = unit_root / "figures.yaml"
    extracted_assets, filtered_assets, extraction_meta = _extract_pdf_images(root, record, unit_root)
    payload = extract_figure_mentions(source_chunks, extracted_assets=extracted_assets)
    payload["filtered_assets"] = filtered_assets
    payload["asset_counts"] = {"kept": len(extracted_assets), "filtered": len(filtered_assets)}
    payload["filter_policy"] = {
        "mode": extraction_meta.get("mode"),
        "captions_detected": extraction_meta.get("captions_detected", 0),
        "fallback_used": extraction_meta.get("fallback_used", False),
        "white_ratio_threshold": WHITE_RATIO_THRESHOLD,
        "gray_ratio_threshold": GRAY_RATIO_THRESHOLD,
        "low_color_threshold": LOW_COLOR_THRESHOLD,
        "discard_filtered_files": True,
    }
    write_yaml_if_changed(figures_path, payload)
    record["payload"]["figures"]["extraction_status"] = "pending_user_confirmation"
    record["payload"]["figures"]["candidate_figures"] = payload["candidate_figures"]
    record["payload"]["figures"]["key_figures"] = payload["key_figures"]
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    record["information_types"] = sorted(set(record.get("information_types", [])) | {"fact", "inference", "unverified"})
    append_history(
        record,
        action="paper-figures-extracted",
        summary="Extracted figure assets when possible and indexed figure mentions.",
        information_types=["fact", "inference", "unverified"],
        artifacts=[rel(root, figures_path)],
    )
    write_record(root, record)
    print(f"[ok] wrote {figures_path.relative_to(root)}")
    _finalize_post_actions(
        root, trigger="milestone", message=f"milestone: extract paper figures {record['id']}", defer_post_actions=defer_post_actions,
        target_paths=[unit_root / "record.yaml", figures_path, unit_root / "figures"],
    )
    return 0


def _auto_post_note_steps(
    root: Path, record: dict, unit_root: Path, source_chunks: list[dict], cache_path: Path, paper_preferences: dict, defer_post_actions: bool
) -> None:
    """SSOT 3.2 auto-refresh: after a successful note verify, auto-run the safe
    post-note steps the prefs enable, gated by autonomy.auto_execute_scope. Never
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


def _resolve_fill_input(unit_root: Path, default_name: str, explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = unit_root / explicit
        return candidate
    return unit_root / default_name


def next_for_agent_note(root: Path, record: dict, cache_path: Path, fill_path: Path) -> str:
    """One machine-readable navigation line for the ingestion auto-drive (SSOT §7).

    Pure navigation: it names the parse-cache artifact to read, the elements to fill
    (each needs a verbatim quote + locator), and the exact verify command to run after.
    It authors no judgement — the agent still fills the understanding.
    """
    elements = ",".join(elements_for(record))
    verify_cmd = (
        f"${{RESEARCH_PYTHON:-python3}} {SCRIPT_PATH} --root {root} "
        f"complete-note --paper-id {record['id']} --phase verify --input {fill_path.name}"
    )
    return (
        f"NEXT FOR AGENT: read {rel(root, cache_path)} (source quotes) then fill {rel(root, fill_path)} "
        f"elements [{elements}] — each needs content + >=1 verbatim quote+locator "
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

    screen = subparsers.add_parser("screen")
    screen.add_argument("--paper-id", required=True)
    screen.add_argument("--phase", choices=["prepare", "verify"], default="prepare")
    screen.add_argument("--input", default="")
    screen.add_argument("--mode", default="auto")
    screen.add_argument("--defer-post-actions", action="store_true")

    note = subparsers.add_parser("complete-note")
    note.add_argument("--paper-id", required=True)
    note.add_argument("--phase", choices=["prepare", "verify"], default="prepare")
    note.add_argument("--input", default="")
    note.add_argument("--mode", default="auto")
    note.add_argument("--defer-post-actions", action="store_true")

    figures = subparsers.add_parser("extract-figures")
    figures.add_argument("--paper-id", required=True)
    figures.add_argument("--defer-post-actions", action="store_true")

    structure = subparsers.add_parser("refresh-structure")
    structure.add_argument("--paper-id", required=True)
    structure.add_argument("--defer-post-actions", action="store_true")

    confirm = subparsers.add_parser("confirm")
    confirm.add_argument("--paper-id", required=True)
    add_confirmation_arguments(confirm)
    confirm.add_argument("--defer-post-actions", action="store_true")

    reject = subparsers.add_parser("reject")
    reject.add_argument("--paper-id", required=True)
    reject.add_argument("--defer-post-actions", action="store_true")
    return parser


@_transactional(
    "screen",
    lambda args, root, record, unit_root, cache_path, source_chunks, paper_preferences, defer_post_actions: (
        root,
        [unit_root / "record.yaml", unit_root / "screening.yaml", *([] if defer_post_actions else _index_targets(root))],
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
        record["payload"]["quick_screen"]["recommended_next_action"] = "screen --phase verify (after agent fills)"
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
    fill_path = _resolve_fill_input(unit_root, "screening.yaml", args.input)
    if not fill_path.exists():
        raise SystemExit(f"screen --phase verify: fill input not found: {fill_path}")
    payload = load_yaml(fill_path, default={})
    if not isinstance(payload, dict):
        raise SystemExit(f"screen --phase verify: {fill_path} is not a mapping")
    violations = verify_screening_fill(payload, unit_root)
    if violations:
        print("[reject] screening fill failed verification:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        raise SystemExit(1)

    worth = str(payload.get("worth_deep_reading") or "").strip().lower()
    paper_type = str(payload.get("paper_type") or "").strip().lower()
    reasons = [str(item).strip() for item in (payload.get("judgement_reason") or []) if str(item).strip()]
    relevance = str(payload.get("relevance_to_current_research") or "").strip()
    attach_claims(payload, read_claims(payload))
    payload["status"] = "verified"
    payload["phase"] = "verify"
    write_yaml_if_changed(screen_path, payload)
    record = apply_record_governance(root, record, infer_missing=True, source_label="paper-analyst")
    quick = record["payload"]["quick_screen"]
    quick["paper_type"] = paper_type
    quick["worth_deep_reading"] = worth
    quick["judgement_reason"] = reasons
    quick["relevance_to_current_research"] = relevance
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
    _finalize_post_actions(root, trigger="milestone", message=f"milestone: verify screen {args.paper_id}", defer_post_actions=defer_post_actions,
                           target_paths=[unit_root / "record.yaml", screen_path])
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
    cache_locator_kind = _cache_locator_kind(cache_path)
    mode = str(args.mode or "auto")
    if mode == "auto":
        mode = str(paper_preferences.get("complete_note_mode") or "scaffold")

    if args.phase == "prepare":
        payload = build_note_scaffold(
            record,
            source_chunks,
            cache_locator_kind,
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
        summary="Prepared type-specific fillable note skeleton (script authored nothing).",
            information_types=["inference", "unverified"],
            artifacts=[rel(root, fill_scaffold_path), rel(root, cache_path)],
        )
        write_record(root, record)
        print(f"[ok] wrote {fill_scaffold_path.relative_to(root)}")
        required = "/".join(elements_for(record))
        print(f"下一步：runtime agent 为 5 要素({required})填内容+证据，再运行 complete-note --phase verify。")
        print(next_for_agent_note(root, record, cache_path, fill_scaffold_path))
        _finalize_post_actions(root, trigger="milestone", message=f"milestone: scaffold note {args.paper_id}", defer_post_actions=defer_post_actions,
                               target_paths=[unit_root / "record.yaml", fill_scaffold_path])
        return 0

    # verify
    fill_path = _resolve_fill_input(unit_root, "note-fill.yaml", args.input)
    if not fill_path.exists():
        raise SystemExit(f"complete-note --phase verify: fill input not found: {fill_path}")
    fill = load_yaml(fill_path, default={})
    if not isinstance(fill, dict):
        raise SystemExit(f"complete-note --phase verify: {fill_path} is not a mapping")
    violations, claims = verify_note_fill(fill, unit_root, record)
    if violations:
        print("[reject] note fill failed verification:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        raise SystemExit(1)

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
    print(f"[ok] verified + wrote {note_path.relative_to(root)} (core_content filled, {len(claims)} elements)")
    _auto_post_note_steps(root, record, unit_root, source_chunks, cache_path, paper_preferences, defer_post_actions)
    _finalize_post_actions(root, trigger="milestone", message=f"milestone: verify note {args.paper_id}", defer_post_actions=defer_post_actions,
                           target_paths=[unit_root / "record.yaml", note_path, unit_root / "note-claims.yaml", unit_root / "structure.yaml", unit_root / "figures.yaml", unit_root / "figures"])
    return 0


@_transactional(
    "confirm",
    lambda args, root, record, unit_root, defer_post_actions: (
        root,
        [unit_root / "record.yaml", *([] if defer_post_actions else _index_targets(root))],
    ),
)
def _run_confirm(args, root: Path, record: dict, unit_root: Path, defer_post_actions: bool) -> int:
    record = confirm_unit(
        record,
        "paper",
        confirmed_by=args.confirmed_by,
        evidence=args.evidence,
        user_authorization=args.user_authorization,
        authorization_source=args.authorization_source,
        method="paper.py confirm",
        project_root=root,
    )
    write_record(root, record)
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


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    runtime_preferences = load_runtime_preferences(root)
    paper_preferences = runtime_preferences.get("paper", {})
    record, path = locate_record(root, args.paper_id, kind="paper")
    if record.get("kind") != "paper":
        raise SystemExit(f"{args.paper_id} is not a paper record")
    unit_root = path.parent
    defer_post_actions = bool(getattr(args, "defer_post_actions", False))

    source_chunks: list[dict] = []
    cache_path = _cache_path(unit_root)
    if args.command in {"prewarm-cache", "screen", "complete-note", "extract-figures", "refresh-structure"}:
        # refresh-structure re-derives structure.yaml from the EXISTING parse-cache;
        # it must NOT force a re-parse — doing so re-runs prewarm with the truncation
        # prefs (front_limit/back_limit) and overwrites the full intake cache, deleting
        # later pages and breaking evidence idempotency (F-a). Only explicit --force
        # (prewarm-cache) may re-parse.
        force_cache = bool(getattr(args, "force", False))
        if force_cache or not cache_path.exists():
            with command_mutation(root, "paper-analyst:prewarm-cache", [cache_path]):
                source_chunks, cache_path = _load_or_refresh_cache(
                    root,
                    record,
                    unit_root,
                    force=force_cache,
                )
        else:
            source_chunks, cache_path = _load_or_refresh_cache(
                root,
                record,
                unit_root,
                force=False,
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
        return _run_extract_figures(root, record, unit_root, source_chunks, defer_post_actions=defer_post_actions)

    if args.command == "refresh-structure":
        return _run_refresh_structure(root, record, unit_root, source_chunks, cache_path, defer_post_actions=defer_post_actions)

    if args.command == "confirm":
        return _run_confirm(args, root, record, unit_root, defer_post_actions)

    if args.command == "reject":
        return _run_reject(args, root, record, unit_root, defer_post_actions)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
