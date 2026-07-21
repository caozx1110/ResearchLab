#!/usr/bin/env python3
"""Repo analyst: script prepares fillable structure + verifies evidence; a runtime
agent fills the understanding (SSOT Principle 1 / §3.3).

The script is deliberately *not* allowed to understand the repo. It (a) scans the
directory tree for mechanical facts (files, entrypoints, languages), (b) emits a
**fillable structure** (3-element capability skeleton) whose judgement fields are left
blank for a runtime agent, and (c) **verifies** every judgement the agent fills carries
legit verbatim evidence (research.evidence) before it clears the substance gate
(research.confirm) and is persisted. There is no README-heuristic -> capability
judgement anywhere: any "this repo supports X" claim must come from an agent, backed
by a real file:line quote.
"""
from __future__ import annotations

import argparse
import os
import sys
from contextvars import ContextVar
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

from research.common import (
    add_project_root_argument,
    clean_text,
    load_yaml,
    print_resolved_project_roots,
    read_text_excerpt,
    write_text_if_changed,
    write_yaml_if_changed,
)
from research.core import (
    append_history,
    apply_record_governance,
    build_index,
    candidate_pools_path,
    command_mutation,
    checkpoint_and_report,
    confirm_unit,
    load_runtime_preferences,
    locate_record,
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

IGNORE_DIRS = {
    ".git", "__pycache__", ".venv", "node_modules", "build", "dist",
    "outputs", "logs", ".mypy_cache",
}
ENTRYPOINT_HINTS = {
    "train.py", "main.py", "run.py", "eval.py", "evaluate.py",
    "infer.py", "inference.py", "demo.py", "app.py",
}

# --------------------------------------------------------------------------- #
# 3-element fill contract (SSOT §3.3 / repo paradigm shift).                   #
#                                                                             #
# A runtime agent fills these three elements; every element is a judgement-    #
# class claim and MUST carry >=1 evidence_ref (short verbatim quote from a     #
# real repo file + file:line locator). The script verifies + routes them — it #
# never authors capability judgements. Filling 'capability' clears             #
# has_substantive_content() for a repo (SUBSTANCE_CONTENT_SECTIONS["repo"] =   #
# ("capability",)).                                                            #
# --------------------------------------------------------------------------- #
CAP_ELEMENTS: tuple[str, ...] = ("capability", "reuse_points", "entry_map")

_ACTIVE_MUTATION: ContextVar[bool] = ContextVar("repo_active_mutation", default=False)
_PENDING_CHECKPOINT: ContextVar[tuple[Path, str, str, list[Path]] | None] = ContextVar(
    "repo_pending_checkpoint", default=None
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
                with command_mutation(root, f"repo-analyst:{op_name}", targets):
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
    "capability": "evaluation",
    "reuse_points": "evaluation",
    "entry_map": "inference",
}

# element -> (payload_section, field, shape)
# capability   -> payload.capability.core_capabilities  (list; clears substance gate)
# reuse_points -> payload.reuse.directly_reusable       (list)
# entry_map    -> payload.structure.entrypoints         (list)
ELEMENT_TARGET: dict[str, tuple[str, str, str]] = {
    "capability": ("capability", "core_capabilities", "list"),
    "reuse_points": ("reuse", "directly_reusable", "list"),
    "entry_map": ("structure", "entrypoints", "list"),
}

ELEMENT_HEADING: dict[str, str] = {
    "capability": "Capability",
    "reuse_points": "Reuse Points",
    "entry_map": "Entry Map",
}

# Reusable, machine-readable description of the evidence_ref shape for repo artifacts.
# Locator family: file:line (repo files use line=N, not page=N).
EVIDENCE_REF_FORMAT_REPO: dict[str, str] = {
    "source_unit_id": "r-... (this repo unit id)",
    "artifact": "path/to/file relative to repo_root (e.g. README.md, src/train.py)",
    "locator": "line=N  (line number within the repo file where the quote appears)",
    "quote": "short verbatim snippet — script checks it is a whitespace-normalized substring of the artifact file",
    "summary": "optional one-line paraphrase",
    "external_source": "{kind: repo} (base_root comes from the trusted analyzer contract, never from the claim)",
}


# --------------------------------------------------------------------------- #
# Mechanical structure scan (no capability heuristic).                         #
# --------------------------------------------------------------------------- #

def _candidate_repo_roots(root: Path, record: dict) -> list[Path]:
    paths: list[Path] = []
    source = record.get("source", {})
    if str(source.get("backup_kind") or "") in {"directory", "dir"}:
        for backup in source.get("backup_paths", []):
            path = root / str(backup)
            if path.exists():
                paths.append(path if path.is_dir() else path.parent)
    original_uri = str(source.get("original_uri") or "")
    if original_uri and not original_uri.startswith("http"):
        path = resolve_local_reference(root, original_uri) or Path(original_uri).expanduser()
        if path.exists():
            paths.append(path.resolve() if path.is_dir() else path.resolve().parent)
    deduped: list[Path] = []
    seen: set[str] = set()
    for path in paths:
        key = path.as_posix()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(path)
    return deduped


def structure_scan_applicability(root: Path, record: dict) -> tuple[bool, str]:
    """Return whether the record resolves to a real local source tree.

    Archived URL pages are deliberately ineligible even though their backup files
    share a directory. Scanning that directory would describe source.html and
    snapshot.md, not a code repository.
    """
    source = record.get("source", {})
    source = source if isinstance(source, dict) else {}
    original_uri = str(source.get("original_uri") or "").strip()
    if original_uri.lower().startswith(("http://", "https://")):
        return False, "remote_page_without_source_tree"
    if _pick_repo_root(root, record) is None:
        return False, "source_tree_unavailable"
    return True, "local_source_tree"


def _pick_repo_root(root: Path, record: dict) -> Path | None:
    for candidate in _candidate_repo_roots(root, record):
        if candidate.is_dir():
            return candidate
    return None


def scan_structure_payload(root: Path, record: dict) -> dict:
    """Mechanical directory scan — no heuristic capability inference."""
    from collections import Counter

    repo_root = _pick_repo_root(root, record)
    if repo_root is None:
        return {
            "status": "unavailable",
            "information_types": ["fact"],
            "repo_root": "",
            "top_level_dirs": [],
            "top_level_files": [],
            "languages": [],
            "core_modules": [],
            "entrypoints": [],
            "config_files": [],
            "readme_excerpt": "",
        }

    top_level_dirs = sorted(
        item.name for item in repo_root.iterdir()
        if item.is_dir() and item.name not in IGNORE_DIRS
    )
    top_level_files = sorted(item.name for item in repo_root.iterdir() if item.is_file())[:40]
    entrypoints: list[str] = []
    core_modules: set[str] = set()
    config_files: set[str] = set()
    language_counter: Counter[str] = Counter()

    for dirpath, dirnames, filenames in os.walk(repo_root):
        dirnames[:] = [name for name in dirnames if name not in IGNORE_DIRS]
        current = Path(dirpath)
        relative_dir = current.relative_to(repo_root)
        if len(relative_dir.parts) > 4:
            dirnames[:] = []
            continue
        for filename in filenames:
            path = current / filename
            relative = path.relative_to(repo_root).as_posix()
            suffix = path.suffix.lower()
            if suffix:
                language_counter[suffix] += 1
            lowered = filename.lower()
            if lowered in ENTRYPOINT_HINTS or (lowered.endswith(".sh") and "train" in lowered):
                entrypoints.append(relative)
            if any(tok in relative.lower() for tok in ("config", "configs", "hydra", ".yaml", ".toml", ".json")):
                config_files.add(relative)
            if relative_dir.parts:
                head = relative_dir.parts[0]
                if head not in {"tests", "docs"}:
                    core_modules.add(head)

    # README excerpt for agent orientation (transport only — NOT a capability judgement).
    readme_excerpt = ""
    for name in ("README.md", "README.rst", "README.txt", "README"):
        p = repo_root / name
        if p.exists():
            readme_excerpt = clean_text(read_text_excerpt(p, limit=3000))
            break

    languages = [f"{suffix}:{count}" for suffix, count in language_counter.most_common(8)]
    return {
        "status": "complete",
        "information_types": ["fact"],
        "repo_root": repo_root.as_posix(),
        "top_level_dirs": top_level_dirs,
        "top_level_files": top_level_files,
        "languages": languages,
        "core_modules": sorted(core_modules)[:20],
        "entrypoints": sorted(set(entrypoints))[:20],
        "config_files": sorted(config_files)[:20],
        "readme_excerpt": readme_excerpt[:2000],
    }


# --------------------------------------------------------------------------- #
# map-capability: prepare a fillable 3-element structure / verify a fill.      #
# --------------------------------------------------------------------------- #

def build_capability_scaffold(record: dict, structure_payload: dict, repo_root: Path | None) -> dict:
    """Produce the fillable capability skeleton (NO heuristic capability judgement).

    The three elements (capability / reuse_points / entry_map) are blank for a
    runtime agent to fill with its own understanding + verbatim file:line evidence.
    The script supplies a mechanical structure digest for the agent's orientation;
    it never judges what the repo can do.
    """
    repo_id = str(record.get("id") or "")

    # Orientation hints: purely mechanical facts for the agent to navigate.
    orientation = {
        "top_level_dirs": structure_payload.get("top_level_dirs", []),
        "entrypoints": structure_payload.get("entrypoints", []),
        "languages": structure_payload.get("languages", []),
        "config_files": structure_payload.get("config_files", [])[:10],
        "readme_excerpt_chars": len(structure_payload.get("readme_excerpt", "")),
        "repo_root": structure_payload.get("repo_root", ""),
    }

    elements = [
        {
            "element": name,
            "claim_type": ELEMENT_CLAIM_TYPE[name],
            "content": "",
            "evidence_refs": [],
        }
        for name in CAP_ELEMENTS
    ]

    return {
        "repo_id": repo_id,
        "kind": "repo",
        "status": "awaiting_agent_fill",
        "phase": "prepare",
        "fill_contract": {
            "description": (
                "Agent fills all three required_elements with its own understanding of the "
                "repo, each backed by >=1 verbatim evidence_ref (a real repo file + line). "
                "Then run `map-capability --phase verify` to validate + verbatim-check "
                "evidence + persist. Empty or unevidenced elements are rejected; the script "
                "never judges capability (SSOT §3.3)."
            ),
            "required_elements": list(CAP_ELEMENTS),
            "element_descriptions": {
                "capability": "What problem this repo solves, its core capabilities, and what it is NOT suitable for",
                "reuse_points": "Which modules / scripts / patterns are reusable, worth borrowing, or worth modifying",
                "entry_map": "Key entry-points (train/eval/inference commands), critical config keys, and core module locations",
            },
            "element_claim_types": dict(ELEMENT_CLAIM_TYPE),
            "evidence_ref_format": EVIDENCE_REF_FORMAT_REPO,
        },
        "agent_orientation": orientation,
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
    refs: list[Any] = []
    for raw_ref in element.get("evidence_refs") or []:
        if not isinstance(raw_ref, dict):
            refs.append(raw_ref)
            continue
        ref = dict(raw_ref)
        ref.setdefault("external_source", {"kind": "repo"})
        refs.append(ref)
    return {
        "id": f"claim-{name}",
        "text": clean_text(str(element.get("content") or "")),
        "claim_type": str(element.get("claim_type") or ELEMENT_CLAIM_TYPE.get(name, "evaluation")),
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": refs,
    }


def verify_capability_fill(fill: Any, repo_root: Path) -> tuple[list[str], list[dict]]:
    """Validate an agent-filled 3-element capability fill. Returns (violations, claims).

    Violations name the offending element. All three elements must be present, carry
    non-empty content, be structurally valid (validate_claims), and every evidence_ref
    quote must verify verbatim against the artifact file under repo_root
    (verify_claim_evidence). Unreachable files yield an explicit error.
    """
    violations: list[str] = []
    elements = _elements_by_name(fill)
    claims: list[dict] = []
    for name in CAP_ELEMENTS:
        element = elements.get(name)
        if element is None:
            violations.append(f"element '{name}': missing (all three elements are required)")
            continue
        content = clean_text(str(element.get("content") or ""))
        if not content:
            violations.append(f"element '{name}': empty content — the agent must fill it")
        refs = element.get("evidence_refs") or []
        if not refs:
            violations.append(
                f"element '{name}': no evidence_refs — every element must cite >=1 verbatim "
                f"quote from a real repo file (artifact=<file-relative-to-repo-root>, locator=line=N)"
            )
        claim = _claim_from_element(name, element)
        claims.append(claim)
        # verify_claim_evidence loads the artifact relative to repo_root; an unreachable
        # file yields an explicit "not found/readable" violation (never a silent pass).
        for violation in verify_claim_evidence(
            claim,
            repo_root,
            external_source={"kind": "repo", "base_root": repo_root.as_posix()},
        ):
            violations.append(f"element '{name}': {violation}")
    # Structural + judgement-evidence rules (research.evidence).
    for violation in validate_claims(claims):
        violations.append(f"claim-structure: {violation}")
    return violations, claims


def _apply_capability_fill_to_payload(record: dict, claims: list[dict]) -> None:
    """Route verified element content into canonical payload fields (in place).

    capability   -> payload.capability.core_capabilities  (list; clears substance gate)
    reuse_points -> payload.reuse.directly_reusable       (list)
    entry_map    -> payload.structure.entrypoints         (list)
    """
    payload = record.setdefault("payload", {})
    targets = {
        "capability": payload.setdefault("capability", {}),
        "reuse_points": payload.setdefault("reuse", {}),
        "entry_map": payload.setdefault("structure", {}),
    }
    field_map = {
        "capability": "core_capabilities",
        "reuse_points": "directly_reusable",
        "entry_map": "entrypoints",
    }
    by_id = {str(claim.get("id") or ""): claim for claim in claims}
    for name in CAP_ELEMENTS:
        claim = by_id.get(f"claim-{name}")
        if claim is None:
            continue
        content = clean_text(str(claim.get("text") or ""))
        if not content:
            continue
        field = field_map[name]
        target = targets[name]
        existing = target.get(field)
        items = list(existing) if isinstance(existing, list) else []
        if content not in items:
            items.append(content)
        target[field] = items


def render_capability_md(record: dict, claims: list[dict]) -> str:
    """Render repo-note.md from verified elements + their evidence citations."""
    title = str(record.get("title") or record.get("id") or "")
    repo_root = record.get("payload", {}).get("structure", {}).get("repo_root", "")
    by_id = {str(claim.get("id") or ""): claim for claim in claims}
    lines = [
        f"# {title}",
        "",
        "> 本笔记由 runtime agent 依据仓库文件填写；脚本已逐字校验每条 evidence（SSOT 原则1/原则2）。",
    ]
    if repo_root:
        lines.extend(["", f"> repo_root: `{repo_root}`"])
    lines.append("")
    for name in CAP_ELEMENTS:
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
                artifact = str(ref.get("artifact") or "?")
                locator = str(ref.get("locator") or "?")
                quote = clean_text(str(ref.get("quote") or ""))
                summary = clean_text(str(ref.get("summary") or ""))
                suffix = f" — {summary}" if summary else ""
                lines.append(f"- [{artifact}:{locator}] \"{quote}\"{suffix}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --------------------------------------------------------------------------- #
# Helpers                                                                      #
# --------------------------------------------------------------------------- #

def _finalize_post_actions(
    root: Path, *, trigger: str, message: str, defer_post_actions: bool, target_paths: Sequence[Path]
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


def _resolve_fill_input(unit_root: Path, default_name: str, explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = unit_root / explicit
        return candidate
    return unit_root / default_name


def next_for_agent_capability(root: Path, record: dict, fill_path: Path) -> str:
    """One machine-readable navigation line for the ingestion auto-drive (SSOT §7).

    Pure navigation: names the fill artifact to read (its agent_orientation digest),
    the elements to fill, and the exact verify command to run after. Repo evidence
    cites real repo files with file:line locators (artifact=<file>, locator=line=N).
    """
    elements = ",".join(CAP_ELEMENTS)
    verify_cmd = (
        f"${{RESEARCH_PYTHON:-python3}} {SCRIPT_PATH} --root {root} "
        f"map-capability --repo-id {record['id']} --phase verify --input {fill_path.name}"
    )
    return (
        f"NEXT FOR AGENT: read {rel(root, fill_path)} (agent_orientation) + repo files then fill it "
        f"elements [{elements}] — each needs content + >=1 verbatim quote+locator "
        f"(repo file:line, artifact=<file> locator=line=N), then run: {verify_cmd}"
    )


def add_confirmation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--confirmed-by", default="")
    parser.add_argument("--evidence", action="append", required=True)
    parser.add_argument("--user-authorization", default="")
    parser.add_argument("--authorization-source", default="")


# --------------------------------------------------------------------------- #
# CLI                                                                          #
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare fillable repo structures + verify agent-filled understanding."
    )
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    scan = subparsers.add_parser("scan-structure")
    scan.add_argument("--repo-id", required=True)
    scan.add_argument("--defer-post-actions", action="store_true")

    cap = subparsers.add_parser("map-capability")
    cap.add_argument("--repo-id", required=True)
    cap.add_argument("--phase", choices=["prepare", "verify"], default="prepare")
    cap.add_argument("--input", default="")
    cap.add_argument("--defer-post-actions", action="store_true")

    confirm = subparsers.add_parser("confirm")
    confirm.add_argument("--repo-id", required=True)
    add_confirmation_arguments(confirm)
    confirm.add_argument("--defer-post-actions", action="store_true")

    reject = subparsers.add_parser("reject")
    reject.add_argument("--repo-id", required=True)
    reject.add_argument("--defer-post-actions", action="store_true")

    return parser


@_transactional(
    "scan-structure",
    lambda args, root, record, unit_root, defer_post_actions: (
        root,
        [unit_root / "record.yaml", unit_root / "structure-scan.yaml", *([] if defer_post_actions else _index_targets(root))],
    ),
)
def _run_scan_structure(args, root, record, unit_root, defer_post_actions) -> int:
    scan_path = unit_root / "structure-scan.yaml"
    payload = scan_structure_payload(root, record)
    write_yaml_if_changed(scan_path, payload)
    record = apply_record_governance(root, record, infer_missing=True, source_label="repo-analyst")
    structure = record["payload"]["structure"]
    structure["scan_status"] = "complete"
    structure["scan_applicability"] = "applicable"
    structure["scan_reason"] = "local_source_tree"
    structure["repo_root"] = payload["repo_root"]
    structure["top_level_dirs"] = payload["top_level_dirs"]
    structure["top_level_files"] = payload["top_level_files"]
    structure["languages"] = payload["languages"]
    structure["core_modules"] = payload["core_modules"]
    structure["entrypoint_candidates"] = payload["entrypoints"]
    append_history(
        record,
        action="repo-structure-scanned",
        summary="Generated mechanical repo structure scan (no capability inference).",
        information_types=["fact"],
        artifacts=[rel(root, scan_path)],
    )
    write_record(root, record)
    print(f"[ok] wrote {scan_path.relative_to(root)}")
    print("下一步：运行 map-capability --phase prepare 产出三要素待填骨架。")
    _finalize_post_actions(root, trigger="milestone", message=f"milestone: scan repo structure {args.repo_id}",
                           defer_post_actions=defer_post_actions,
                           target_paths=[unit_root / "record.yaml", scan_path])
    return 0


@_transactional(
    "map-capability",
    lambda args, root, record, unit_root, defer_post_actions: (
        root,
        [
            unit_root / "record.yaml",
            unit_root / "capability-fill.yaml",
            unit_root / "repo-note.md",
            unit_root / "capability-claims.yaml",
            *([] if defer_post_actions else _index_targets(root)),
        ],
    ),
)
def _run_map_capability(args, root, record, unit_root, defer_post_actions) -> int:
    fill_path = unit_root / "capability-fill.yaml"
    note_path = unit_root / "repo-note.md"

    if args.phase == "prepare":
        structure_payload = scan_structure_payload(root, record)
        repo_root_str = structure_payload.get("repo_root", "")
        repo_root_path: Path | None = None
        if repo_root_str:
            candidate = Path(repo_root_str)
            if candidate.is_dir():
                repo_root_path = candidate

        payload = build_capability_scaffold(record, structure_payload, repo_root_path)
        write_yaml_if_changed(fill_path, payload)
        record = apply_record_governance(root, record, infer_missing=True, source_label="repo-analyst")
        record["status"] = "screened"
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        record["information_types"] = ["fact", "inference", "unverified"]
        record["payload"].setdefault("state", {})["capability_fill_status"] = "awaiting_agent_fill"
        append_history(
            record,
            action="repo-capability-scaffolded",
            summary="Prepared 3-element fillable capability skeleton (script authored nothing).",
            information_types=["inference", "unverified"],
            artifacts=[rel(root, fill_path)],
        )
        write_record(root, record)
        print(f"[ok] wrote {fill_path.relative_to(root)}")
        print(
            "下一步：runtime agent 为三要素 (capability/reuse_points/entry_map) 填内容 + "
            "file:line 逐字证据，再运行 map-capability --phase verify。"
        )
        print(next_for_agent_capability(root, record, fill_path))
        _finalize_post_actions(root, trigger="milestone", message=f"milestone: scaffold capability {args.repo_id}",
                               defer_post_actions=defer_post_actions,
                               target_paths=[unit_root / "record.yaml", fill_path])
        return 0

    # verify phase
    input_path = _resolve_fill_input(unit_root, "capability-fill.yaml", args.input)
    if not input_path.exists():
        raise SystemExit(f"map-capability --phase verify: fill input not found: {input_path}")
    fill = load_yaml(input_path, default={})
    if not isinstance(fill, dict):
        raise SystemExit(f"map-capability --phase verify: {input_path} is not a mapping")

    # Resolve repo_root for evidence reachability (cited artifacts must exist under it).
    structure_payload = scan_structure_payload(root, record)
    repo_root_str = structure_payload.get("repo_root", "")
    if not repo_root_str:
        raise SystemExit(
            "map-capability --phase verify: cannot resolve repo_root — run scan-structure first "
            "or ensure the record has a local source path."
        )
    repo_root_path = Path(repo_root_str)
    if not repo_root_path.is_dir():
        raise SystemExit(f"map-capability --phase verify: repo_root '{repo_root_str}' is not a directory")

    violations, claims = verify_capability_fill(fill, repo_root_path)
    if violations:
        print("[reject] capability fill failed verification:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        raise SystemExit(1)

    _apply_capability_fill_to_payload(record, claims)
    record["payload"].setdefault("structure", {})["repo_root"] = repo_root_path.resolve().as_posix()
    attach_claims(record.setdefault("payload", {}), claims)
    build_verification_receipt(
        record,
        unit_root,
        external_source={"kind": "repo", "base_root": repo_root_path.resolve().as_posix()},
    )
    write_text_if_changed(note_path, render_capability_md(record, claims))
    claims_payload = {"repo_id": record["id"], "kind": "repo"}
    attach_claims(claims_payload, claims)
    write_yaml_if_changed(unit_root / "capability-claims.yaml", claims_payload)

    fill["status"] = "verified"
    fill["phase"] = "verify"
    write_yaml_if_changed(fill_path, fill)

    record["maturity"] = "complete"
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    record["information_types"] = ["fact", "inference", "evaluation", "unverified"]
    record["payload"].setdefault("state", {})["capability_fill_status"] = "pending_user_confirmation"
    append_history(
        record,
        action="repo-capability-verified",
        summary="Verified + persisted agent 3-element capability fill (evidence-grounded).",
        information_types=["inference", "evaluation", "unverified"],
        artifacts=[rel(root, note_path), rel(root, fill_path)],
    )
    write_record(root, record)
    print(f"[ok] verified + wrote {note_path.relative_to(root)} (capability filled, {len(claims)} elements)")
    _finalize_post_actions(root, trigger="milestone", message=f"milestone: verify capability {args.repo_id}",
                           defer_post_actions=defer_post_actions,
                           target_paths=[unit_root / "record.yaml", fill_path, note_path, unit_root / "capability-claims.yaml"])
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
        "repo",
        confirmed_by=args.confirmed_by,
        evidence=args.evidence,
        user_authorization=args.user_authorization,
        authorization_source=args.authorization_source,
        project_root=root,
    )
    write_record(root, record)
    print(f"[ok] confirmed {args.repo_id}")
    _finalize_post_actions(root, trigger="milestone", message=f"milestone: confirm repo {args.repo_id}",
                           defer_post_actions=defer_post_actions,
                           target_paths=[unit_root / "record.yaml"])
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
    append_history(record, action="repo-rejected", summary="Repo analysis rejected or deferred.",
                   information_types=["evaluation"])
    write_record(root, record)
    print(f"[ok] rejected {args.repo_id}")
    _finalize_post_actions(root, trigger="milestone", message=f"milestone: reject repo {args.repo_id}",
                           defer_post_actions=defer_post_actions,
                           target_paths=[unit_root / "record.yaml"])
    return 0


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    record, path = locate_record(root, args.repo_id, kind="repo")
    if record.get("kind") != "repo":
        raise SystemExit(f"{args.repo_id} is not a repo record")
    unit_root = path.parent
    defer_post_actions = bool(getattr(args, "defer_post_actions", False))

    if args.command == "scan-structure":
        applicable, reason = structure_scan_applicability(root, record)
        if not applicable:
            raise SystemExit(
                "Repo structure scan requires a real local source tree; "
                f"this source is not applicable ({reason})."
            )
        return _run_scan_structure(args, root, record, unit_root, defer_post_actions)

    if args.command == "map-capability":
        return _run_map_capability(args, root, record, unit_root, defer_post_actions)

    if args.command == "confirm":
        return _run_confirm(args, root, record, unit_root, defer_post_actions)

    if args.command == "reject":
        return _run_reject(args, root, record, unit_root, defer_post_actions)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
