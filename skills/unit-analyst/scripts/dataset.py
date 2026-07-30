#!/usr/bin/env python3
"""Dataset analyst: prepare a fillable profile and verify runtime-agent evidence.
agent fills the understanding (`docs/DESIGN.md`, "Prepare / fill / verify").

The script is deliberately *not* allowed to understand the dataset. It (a) reads the
parse-cache produced by source-intake, (b) emits a **fillable structure** (4-element
note skeleton) whose judgement fields are left blank for a runtime agent, and (c)
**verifies** every judgement the agent fills carries legit verbatim evidence
(research.evidence) before it clears the substance gate (research.confirm) and is
persisted. There is no keyword-count heuristic or Python-inferred positioning here:
any "this dataset is suitable / high quality / reusable" claim must come from an
agent, never from Python.

Dataset cards are treated as evidence-bearing documents. Web cards use
section/anchor locators; local text/Markdown cards use the same section contract.
"""
from __future__ import annotations

import argparse
import sys
from contextvars import ContextVar
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

from research.common import (
    add_project_root_argument,
    clean_text,
    load_yaml,
    print_resolved_project_roots,
    write_text_if_changed,
    write_yaml_if_changed,
)
from research.core import (
    append_history,
    build_index,
    candidate_pools_path,
    canonical_record_snapshot_for_record,
    command_mutation,
    checkpoint_and_report,
    confirm_unit,
    locate_record,
    passage_search_cache_path,
    project_root,
    rel,
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
    canonical_digest,
    regular_file_binding,
    regular_tree_binding,
    resolve_operation_preferences,
    task_context_digest,
)

# --------------------------------------------------------------------------- #
# Fill contract (.agents/lib/research/SCHEMAS.md#unit-payload, dataset).       #
#                                                                              #
# A runtime agent fills these four elements; every element is a               #
# judgement-class claim and MUST carry >=1 evidence_ref (short verbatim       #
# quote + locator from the dataset-card parse-cache). The script only verifies + #
# routes them — it never authors content. Each element lands in a canonical   #
# payload field so a filled note clears has_substantive_content()             #
# (SUBSTANCE_CONTENT_SECTIONS["dataset"]).                                   #
# --------------------------------------------------------------------------- #
NOTE_ELEMENTS: tuple[str, ...] = (
    "positioning",
    "composition",
    "schema_access",
    "suitability_risks",
)
PREFERENCE_SKILL = "dataset-analyst"
PREFERENCE_OPERATION = "profile"
PREFERENCE_ORIENTATION_NAME = "dataset-orientation.yaml"

_ACTIVE_MUTATION: ContextVar[bool] = ContextVar("dataset_active_mutation", default=False)
_PENDING_CHECKPOINT: ContextVar[tuple[Path, str, str, list[Path]] | None] = ContextVar(
    "dataset_pending_checkpoint", default=None
)


def _index_targets(root: Path) -> list[Path]:
    return [
        root / "kb" / "index.yaml",
        root / "kb" / "index.md",
        topic_taxonomy_path(root),
        candidate_pools_path(root),
        passage_search_cache_path(root),
    ]


def _transactional(op_name: str, target_builder):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            root, targets = target_builder(*args, **kwargs)
            active_token = _ACTIVE_MUTATION.set(True)
            checkpoint_token = _PENDING_CHECKPOINT.set(None)
            try:
                with command_mutation(root, f"dataset-analyst:{op_name}", targets):
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

ELEMENT_CLAIM_TYPE: dict[str, str] = {
    "positioning": "inference",
    "composition": "inference",
    "schema_access": "inference",
    "suitability_risks": "evaluation",
}

# element -> (payload section, field, shape).
# All four elements land in canonical dataset sections covered by the substance gate.
ELEMENT_TARGET: dict[str, tuple[str, str, str]] = {
    "positioning": ("profile", "positioning", "str"),
    "composition": ("composition", "summary", "str"),
    "schema_access": ("access", "schema_access", "str"),
    "suitability_risks": ("quality", "suitability_risks", "str"),
}

ELEMENT_HEADING: dict[str, str] = {
    "positioning": "Positioning",
    "composition": "Composition",
    "schema_access": "Schema and Access",
    "suitability_risks": "Suitability and Risks",
}

# Reusable, machine-readable description of the evidence_ref shape an agent must fill.
# Dataset-card parse-cache uses section/anchor locators (HTML/text, no page numbers).
EVIDENCE_REF_FORMAT: dict[str, str] = {
    "source_unit_id": "d-... (this dataset unit id)",
    "artifact": "parse-cache.yaml (unit-relative artifact the quote lives in)",
    "locator": "HTML: section or section:<anchor> — no page numbers for web sources",
    "quote": "short verbatim snippet — script checks it is a whitespace-normalized substring of the artifact",
    "summary": "optional one-line paraphrase",
}


def add_confirmation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--confirmed-by", default="")
    parser.add_argument("--evidence", action="append", required=True)
    parser.add_argument("--user-authorization", default="")
    parser.add_argument("--authorization-source", default="")


def _cache_path(unit_root: Path) -> Path:
    return unit_root / "parse-cache.yaml"


def _load_cache_chunks(unit_root: Path) -> tuple[list[dict], str]:
    """Load chunks from parse-cache.yaml (built by source-intake). Returns (chunks, locator_kind).

    Read-compatible with either header id key: a dataset parse-cache may carry the correct
    ``dataset_id`` (or ``unit_id``) or the legacy ``paper_id`` the shared intake writer
    stamped on it. The header is normalized in memory only; parse-cache bytes are
    immutable derived evidence."""
    cache_path = _cache_path(unit_root)
    if not cache_path.exists():
        return [], "section"
    payload = load_yaml(cache_path, default={})
    if not isinstance(payload, dict):
        return [], "section"
    payload = _normalized_cache_payload(payload)
    chunks = payload.get("chunks") or []
    locator_kind = str(payload.get("locator_kind") or "section")
    if not isinstance(chunks, list):
        return [], locator_kind
    return [c for c in chunks if isinstance(c, dict)], locator_kind


# Header id keys a dataset parse-cache may carry, in preferred order.
# order. ``paper_id`` is the legacy key the shared dual-source intake writer
# (research.sources.write_parse_cache) stamps on every unit's cache — wrong semantics
# for a web unit. We accept it and normalize only the in-memory view.
_CACHE_ID_KEYS: tuple[str, ...] = ("dataset_id", "unit_id", "paper_id")


def _cache_unit_id(payload: dict) -> str:
    """Read the unit id from a parse-cache header, accepting dataset/unit/legacy keys."""
    for key in _CACHE_ID_KEYS:
        value = str(payload.get(key) or "").strip()
        if value:
            return value
    return ""


def _normalized_cache_payload(payload: dict) -> dict:
    """Return a dataset-semantic view without mutating immutable parse-cache bytes."""
    if "paper_id" not in payload or "dataset_id" in payload or "unit_id" in payload:
        return payload
    normalized = dict(payload)
    normalized["dataset_id"] = normalized.pop("paper_id")
    return normalized


def _chunk_locator(chunk: dict) -> str:
    """Derive an HTML section locator per
    `.agents/lib/research/SCHEMAS.md#evidence-claims`.

    Dataset-card parse-caches use section/anchor locators. Labels are ``section:<anchor>``
    or ``section:document``. This is pure transport — it copies the locator the
    agent should cite, it does not judge anything.
    """
    label = str(chunk.get("label") or "")
    if label.startswith("section:"):
        return label
    anchor = str(chunk.get("anchor") or "")
    if anchor:
        return f"section:{anchor}"
    return "section"


def _evidence_digest(chunks: list[dict], *, chunk_limit: int, excerpt_chars: int) -> list[dict]:
    """Build a locator-tagged excerpt list from parse-cache chunks for the agent.

    This is the transport half of `docs/DESIGN.md` "Prepare / fill / verify": it hands the agent the
    raw section text with citable locators. It contains no judgement and no grade.
    """
    digest: list[dict] = []
    for chunk in chunks[:chunk_limit]:
        text = clean_text(str(chunk.get("text") or ""))
        if not text:
            continue
        digest.append(
            {
                "locator": _chunk_locator(chunk),
                "artifact": "parse-cache.yaml",
                "label": str(chunk.get("label") or ""),
                "excerpt": text[:excerpt_chars],
            }
        )
    return digest


# --------------------------------------------------------------------------- #
# profile: 4-element fillable skeleton / verify + persist an agent fill        #
# --------------------------------------------------------------------------- #


def build_note_scaffold(
    record: dict,
    source_chunks: list[dict],
    *,
    digest_chunks: int,
    digest_chars: int,
    preference_task_context: Mapping[str, object] | None = None,
) -> dict:
    """Produce the 4-element fillable dataset profile skeleton. Each element is blank for the agent to
    fill with content + >=1 evidence_ref. The script authors nothing here."""
    digest = _evidence_digest(source_chunks, chunk_limit=digest_chunks, excerpt_chars=digest_chars)
    elements = [
        {
            "element": name,
            "claim_type": ELEMENT_CLAIM_TYPE[name],
            "content": "",
            "evidence_refs": [],
        }
        for name in NOTE_ELEMENTS
    ]
    scaffold = {
        "dataset_id": record["id"],
        "kind": "dataset",
        "status": "awaiting_agent_fill",
        "phase": "prepare",
        "fill_contract": {
            "description": (
                "Agent fills all four required_elements with its own understanding, each "
                "backed by >=1 verbatim evidence_ref from the parse-cache. Then run "
                "`profile --phase verify` to validate + verbatim-check evidence + "
                "write dataset-note.md + payload content. Empty or unevidenced elements are "
                "rejected; the script validates runtime-Agent content and never authors it."
            ),
            "required_elements": list(NOTE_ELEMENTS),
            "element_claim_types": dict(ELEMENT_CLAIM_TYPE),
            "evidence_ref_format": EVIDENCE_REF_FORMAT,
        },
        "evidence_digest": digest,
        # --- agent fills each element.content + element.evidence_refs below ---
        "elements": elements,
    }
    if preference_task_context is not None:
        context = dict(preference_task_context)
        scaffold["preference_consumer"] = {
            "skill": PREFERENCE_SKILL,
            "operation": PREFERENCE_OPERATION,
            "task_context": context,
            "task_context_digest": task_context_digest(
                skill=PREFERENCE_SKILL,
                operation=PREFERENCE_OPERATION,
                canonical_inputs=context,
            ),
        }
    return scaffold


def dataset_preference_orientation(record: Mapping[str, object]) -> dict[str, object]:
    """Immutable authoring contract kept separate from Agent-fillable fields."""
    phase_contract = {
        "prepare": "owner-writes-canonical-orientation-before-agent-authoring",
        "author": "runtime-agent",
        "verify": "owner-recomputes-context-before-business-write",
        "fillable_fields": ["elements[].content", "elements[].evidence_refs"],
    }
    return {
        "schema": "analyzer-preference-orientation/v1",
        "canonical_id": str(record.get("id") or ""),
        "canonical_kind": "dataset",
        "skill": PREFERENCE_SKILL,
        "operation": PREFERENCE_OPERATION,
        "phase_contract": phase_contract,
        "required_elements": list(NOTE_ELEMENTS),
        "element_claim_types": dict(ELEMENT_CLAIM_TYPE),
        "evidence_locator_family": "html-section-anchor",
    }


def dataset_preference_context(
    root: Path,
    record: Mapping[str, object],
    unit_root: Path,
) -> dict[str, object]:
    """Recompute the exact record/orientation/parse/source task inputs."""
    orientation_path = unit_root / PREFERENCE_ORIENTATION_NAME
    orientation_binding = regular_file_binding(
        orientation_path,
        logical_identity=PREFERENCE_ORIENTATION_NAME,
        trusted_root=root,
    )
    orientation = load_yaml(orientation_path, default={})
    expected_orientation = dataset_preference_orientation(record)
    if orientation != expected_orientation:
        raise ValueError("immutable analyzer orientation contract was modified")

    cache_path = _cache_path(unit_root)
    cache_binding = regular_file_binding(
        cache_path, logical_identity="parse-cache.yaml", trusted_root=root
    )
    cache = load_yaml(cache_path, default={})
    if not isinstance(cache, dict) or _cache_unit_id(cache) != str(record.get("id") or ""):
        raise ValueError("canonical dataset parse cache has a mismatched identity")
    record_binding = regular_file_binding(
        unit_root / "record.yaml", logical_identity="record.yaml", trusted_root=root
    )
    source_binding = regular_tree_binding(
        unit_root / "source",
        logical_identity="dataset-source-artifacts",
        trusted_root=root,
    )
    return {
        "canonical_id": str(record.get("id") or ""),
        "canonical_kind": "dataset",
        "operation": PREFERENCE_OPERATION,
        "record_content_digest": record_binding["bytes_digest"],
        "phase_contract_digest": canonical_digest(expected_orientation["phase_contract"]),
        "immutable_orientation_digest": orientation_binding["bytes_digest"],
        "parse_cache_identity_digest": cache_binding["identity_digest"],
        "parse_cache_bytes_digest": cache_binding["bytes_digest"],
        "source_artifacts_identity_digest": source_binding["identity_digest"],
        "source_artifacts_bytes_digest": source_binding["bytes_digest"],
    }


def resolve_dataset_preferences(
    root: Path,
    record: Mapping[str, object],
    unit_root: Path,
    *,
    selection_id: str,
) -> dict[str, object]:
    """Validate an optional private receipt; empty selection is strictly neutral."""
    context = dataset_preference_context(root, record, unit_root)
    resolution = resolve_operation_preferences(
        root,
        selection_id=selection_id,
        skill=PREFERENCE_SKILL,
        operation=PREFERENCE_OPERATION,
        canonical_inputs=context,
    )
    return resolution


def _persist_preference_binding(record: dict, binding: Mapping[str, object]) -> None:
    payload = record.setdefault("payload", {})
    contexts = payload.get("preference_contexts")
    contexts = dict(contexts) if isinstance(contexts, Mapping) else {}
    if binding:
        contexts[PREFERENCE_OPERATION] = dict(binding)
    else:
        contexts.pop(PREFERENCE_OPERATION, None)
    if contexts:
        payload["preference_contexts"] = contexts
    else:
        payload.pop("preference_contexts", None)


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


def verify_note_fill(fill: Any, unit_dir: Path) -> tuple[list[str], list[dict]]:
    """Validate an agent-filled 4-element dataset profile. Returns (violations, claims).

    Violations name the offending element. All four elements must be present,
    carry non-empty content, be structurally valid (validate_claims), and every
    evidence_ref quote must verify verbatim against the artifact
    (verify_claim_evidence).
    """
    violations: list[str] = []
    elements = _elements_by_name(fill)
    claims: list[dict] = []
    for name in NOTE_ELEMENTS:
        element = elements.get(name)
        if element is None:
            violations.append(f"element '{name}': missing (all four elements are required)")
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
    # Structural + judgement-evidence rules (research.evidence).
    for violation in validate_claims(claims):
        violations.append(f"claim-structure: {violation}")
    return violations, claims


def _apply_note_fill_to_payload(record: dict, claims: list[dict]) -> None:
    """Route verified element content into canonical payload fields (in place)."""
    payload = record.setdefault("payload", {})
    profile = payload.setdefault("profile", {})
    composition = payload.setdefault("composition", {})
    access = payload.setdefault("access", {})
    quality = payload.setdefault("quality", {})
    by_id = {str(claim.get("id") or ""): claim for claim in claims}
    for name in NOTE_ELEMENTS:
        claim = by_id.get(f"claim-{name}")
        if claim is None:
            continue
        text = clean_text(str(claim.get("text") or ""))
        section, field, shape = ELEMENT_TARGET[name]
        target = {
            "profile": profile,
            "composition": composition,
            "access": access,
            "quality": quality,
        }[section]
        if shape == "list":
            existing = target.get(field)
            items = list(existing) if isinstance(existing, list) else []
            if text and text not in items:
                items.append(text)
            target[field] = items
        else:
            target[field] = text


def render_note_md(record: dict, claims: list[dict]) -> str:
    """Render dataset-note.md from verified elements + their evidence citations."""
    title = str(record.get("title") or record.get("id") or "")
    by_id = {str(claim.get("id") or ""): claim for claim in claims}
    lines = [
        f"# {title}",
        "",
        "> 本笔记由 runtime agent 依据 parse-cache 填写；脚本已逐字校验每条 evidence。",
        "> 数据卡证据使用 section/anchor 定位；脚本不依据字段名或规模自动判断数据质量。",
        "",
    ]
    for name in NOTE_ELEMENTS:
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


def _finalize_post_actions(
    root: Path, *, trigger: str, message: str, defer_post_actions: bool, target_paths: Sequence[Path]
) -> dict[str, Any]:
    """Rebuild the index and (unless deferred) commit a git checkpoint.

    Mirrors paper.py / repo.py so a dataset write point persists its artifacts the same
    way: verify never leaves note.md + payload uncommitted. When a caller
    defers (batch/ingest chain), the outer driver takes the single checkpoint instead.
    """
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


def _resolve_fill_input(unit_root: Path, default_name: str, explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = unit_root / explicit
        return candidate
    return unit_root / default_name


def _unit_owned_fill_path(unit_root: Path, fill_path: Path) -> Path | None:
    """Return a checkpoint-safe fill only when it resolves inside this unit."""
    try:
        fill_path.resolve().relative_to(unit_root.resolve())
    except (OSError, ValueError):
        return None
    return fill_path


def next_for_agent_note(root: Path, record: dict, cache_path: Path, fill_path: Path) -> str:
    """One private navigation line for the Agent protocol in `docs/DESIGN.md`.

    Pure navigation: names the parse-cache artifact to read, the elements to fill
    (each needs a verbatim quote + section/anchor locator), and the exact verify
    command to run after. Dataset cards use section/anchor locators.
    """
    elements = ",".join(NOTE_ELEMENTS)
    verify_cmd = (
        f"${{RESEARCH_PYTHON:-python3}} {SCRIPT_PATH} --root {root} "
        f"profile --dataset-id {record['id']} --phase verify --input {fill_path.name}"
    )
    read_hint = rel(root, cache_path) if cache_path.exists() else "parse-cache.yaml"
    return (
        f"NEXT FOR AGENT: read {read_hint} (source quotes) then fill {rel(root, fill_path)} "
        f"elements [{elements}] — each needs content + >=1 verbatim quote+locator "
        f"(HTML section / section:<anchor>), then run: {verify_cmd}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare fillable dataset profiles + verify agent-filled understanding."
    )
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    note = subparsers.add_parser("profile")
    note.add_argument("--dataset-id", required=True)
    note.add_argument("--phase", choices=["prepare", "verify"], default="prepare")
    note.add_argument("--input", default="")
    note.add_argument("--preference-selection-id", default="", help=argparse.SUPPRESS)
    note.add_argument("--defer-post-actions", action="store_true")

    confirm = subparsers.add_parser("confirm")
    confirm.add_argument("--dataset-id", required=True)
    add_confirmation_arguments(confirm)
    confirm.add_argument("--defer-post-actions", action="store_true")

    return parser


@_transactional(
    "profile",
    lambda args, root, record, unit_root, defer_post_actions: (
        root,
        [
            unit_root / "record.yaml",
            unit_root / "dataset-fill.yaml",
            *([unit_root / PREFERENCE_ORIENTATION_NAME] if args.phase == "prepare" else []),
            unit_root / "dataset-note.md",
            unit_root / "dataset-claims.yaml",
            *([] if defer_post_actions else _index_targets(root)),
        ],
    ),
)
def _run_complete_note(args, root: Path, record: dict, unit_root: Path, defer_post_actions: bool) -> int:
    fill_scaffold_path = unit_root / "dataset-fill.yaml"
    note_path = unit_root / "dataset-note.md"
    cache_path = _cache_path(unit_root)

    if args.phase == "prepare":
        source_chunks, _locator_kind = _load_cache_chunks(unit_root)
        payload = build_note_scaffold(
            record,
            source_chunks,
            digest_chunks=12,
            digest_chars=1200,
        )
        write_yaml_if_changed(fill_scaffold_path, payload)
        orientation_path = unit_root / PREFERENCE_ORIENTATION_NAME
        write_yaml_if_changed(orientation_path, dataset_preference_orientation(record))
        record["maturity"] = "complete"
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        record["information_types"] = ["fact", "inference", "evaluation", "unverified"]
        record["payload"].setdefault("state", {})["profile_status"] = "awaiting_agent_fill"
        append_history(
            record,
            action="dataset-profile-scaffolded",
            summary="Prepared 4-element fillable dataset profile skeleton (script authored nothing).",
            information_types=["inference", "unverified"],
            artifacts=[rel(root, fill_scaffold_path), rel(root, orientation_path), rel(root, cache_path)],
        )
        write_record(root, record)
        preference_task_context = dataset_preference_context(root, record, unit_root)
        payload = build_note_scaffold(
            record,
            source_chunks,
            digest_chunks=12,
            digest_chars=1200,
            preference_task_context=preference_task_context,
        )
        write_yaml_if_changed(fill_scaffold_path, payload)
        print(f"[ok] wrote {fill_scaffold_path.relative_to(root)}")
        print(
            "下一步：agent 读 parse-cache 填四要素"
            "(positioning/composition/schema_access/suitability_risks)"
            "带证据，再运行 dataset profile 的校验阶段。"
        )
        print(next_for_agent_note(root, record, cache_path, fill_scaffold_path))
        _finalize_post_actions(
            root,
            trigger="milestone",
            message=f"milestone: scaffold dataset profile {record['id']}",
            defer_post_actions=defer_post_actions,
            target_paths=[unit_root / "record.yaml", orientation_path, fill_scaffold_path],
        )
        return 0

    # verify
    fill_path = _resolve_fill_input(unit_root, "dataset-fill.yaml", args.input)
    if not fill_path.exists():
        raise SystemExit(f"profile --phase verify: fill input not found: {fill_path}")
    fill = load_yaml(fill_path, default={})
    if not isinstance(fill, dict):
        raise SystemExit(f"profile --phase verify: {fill_path} is not a mapping")
    preference_selection_id = str(getattr(args, "preference_selection_id", "") or "")
    try:
        preference_preferences = resolve_dataset_preferences(
            root,
            record,
            unit_root,
            selection_id=preference_selection_id,
        )
    except ValueError as exc:
        print(f"[reject] dataset profile preference receipt: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    violations, claims = verify_note_fill(fill, unit_root)
    if violations:
        print("[reject] dataset profile fill failed verification:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        raise SystemExit(1)

    try:
        rechecked_preferences = resolve_dataset_preferences(
            root,
            record,
            unit_root,
            selection_id=preference_selection_id,
        )
    except ValueError as exc:
        print(f"[reject] dataset profile preference receipt: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    if (
        rechecked_preferences.get("task_context_digest")
        != preference_preferences.get("task_context_digest")
        or rechecked_preferences.get("binding") != preference_preferences.get("binding")
    ):
        print("[reject] dataset profile task context changed before write", file=sys.stderr)
        raise SystemExit(1)

    _apply_note_fill_to_payload(record, claims)
    _persist_preference_binding(record, dict(preference_preferences.get("binding") or {}))
    attach_claims(record.setdefault("payload", {}), claims)
    build_verification_receipt(record, unit_root)
    write_text_if_changed(note_path, render_note_md(record, claims))
    note_payload = {"dataset_id": record["id"], "kind": "dataset"}
    attach_claims(note_payload, claims)
    write_yaml_if_changed(unit_root / "dataset-claims.yaml", note_payload)
    record["maturity"] = "complete"
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    record["information_types"] = ["fact", "inference", "evaluation", "unverified"]
    record["payload"].setdefault("state", {})["profile_status"] = "pending_user_confirmation"
    append_history(
        record,
        action="dataset-profile-verified",
        summary="Verified + persisted agent 4-element dataset profile (evidence-grounded).",
        information_types=["inference", "evaluation", "unverified"],
        artifacts=[rel(root, note_path), rel(root, cache_path)] if cache_path.exists() else [rel(root, note_path)],
    )
    write_record(root, record)
    print(f"[ok] verified + wrote {note_path.relative_to(root)} (content filled, {len(claims)} elements)")
    note_targets = [unit_root / "record.yaml", note_path, unit_root / "dataset-claims.yaml"]
    owned_fill = _unit_owned_fill_path(unit_root, fill_path)
    if owned_fill is not None:
        note_targets.insert(1, owned_fill)
    _finalize_post_actions(
        root,
        trigger="milestone",
        message=f"milestone: dataset profile {record['id']}",
        defer_post_actions=defer_post_actions,
        target_paths=note_targets,
    )
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
        "dataset",
        confirmed_by=args.confirmed_by,
        evidence=args.evidence,
        user_authorization=args.user_authorization,
        authorization_source=args.authorization_source,
        method="dataset.py confirm",
        project_root=root,
        expected_record_snapshot=expected_record_snapshot,
    )
    write_record(root, record, expected_record_snapshot=expected_record_snapshot)
    print(f"[ok] confirmed {args.dataset_id}")
    _finalize_post_actions(
        root,
        trigger="milestone",
        message=f"milestone: confirm dataset {args.dataset_id}",
        defer_post_actions=defer_post_actions,
        target_paths=[unit_root / "record.yaml"],
    )
    return 0


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    record, path = locate_record(root, args.dataset_id, kind="dataset")
    if record.get("kind") != "dataset":
        raise SystemExit(f"{args.dataset_id} is not a dataset record")
    unit_root = path.parent
    defer_post_actions = bool(getattr(args, "defer_post_actions", False))

    if args.command == "profile":
        return _run_complete_note(args, root, record, unit_root, defer_post_actions)

    if args.command == "confirm":
        return _run_confirm(args, root, record, unit_root, defer_post_actions)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
