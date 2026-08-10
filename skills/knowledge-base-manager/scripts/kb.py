#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

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

from research.analyzer_registry import (
    UNIT_ANALYZER_ID_ARG_BY_KIND,
    UNIT_ANALYZER_SCRIPT_BY_KIND,
)
from research.common import add_project_root_argument, confirm_command, load_yaml, parse_iso_datetime, print_resolved_project_roots, shell_command, skill_script_for_command, utc_now_iso, warn_if_cwd_differs_from_project_root
from research.index import AUDIT_CATEGORIES, AUDIT_SEVERITIES
from research.core import (
    build_index,
    audit_workspace,
    candidate_pools_path,
    canonical_record_snapshot_for_record,
    compact_unit_ids,
    dataset_migration_plan,
    dataset_migration_targets,
    confirmation_track,
    confirm_unit,
    has_substantive_content,
    ensure_kb_git_repo,
    ensure_workspace,
    git_checkpoint,
    govern_records,
    kb_git_log,
    kb_git_status,
    link_records,
    lint_records,
    locate_record,
    normalize_record_snapshot,
    iter_records,
    is_ready_for_human_review,
    checkpoint_and_report,
    project_root,
    promote_record,
    record_workflow_state,
    record_path,
    rebuild_governance_catalogs,
    rel,
    restore_operation,
    migrate_repo_to_dataset,
    refresh_record_schemas,
    search_passages,
    search_records,
    sync_storage_layout,
    topic_taxonomy_path,
    undo_last_operation,
    write_record,
)
from research.git_ops import dirty_kb_paths
from research.journal import incomplete_ops, mutation_transaction
from research.judgements import apply_judgement_rejection, require_judgement_snapshot
from research.path_contract import TargetClass
from research.paths import (
    KB_GITIGNORE_LINES,
    TEXT_REWRITE_SUFFIXES,
    kb_gitignore_path,
    kb_root,
    passage_search_cache_path,
    runtime_preferences_path,
    user_root,
)
from research.workspace_layout import (
    WorkspaceLayoutError,
    initialize_workspace_layout,
    layout_marker_path,
    require_workspace_rules,
)

COMMAND_PREFIX = "${RESEARCH_PYTHON:-python3}"
SCRIPT_BY_KIND = {
    **UNIT_ANALYZER_SCRIPT_BY_KIND,
    "idea": ".agents/skills/idea-workbench/scripts/idea.py",
    "experiment": ".agents/skills/experiment-workbench/scripts/experiment.py",
}
ID_ARG_BY_KIND = {
    **UNIT_ANALYZER_ID_ARG_BY_KIND,
    "idea": "--idea-id",
    "experiment": "--experiment-id",
}
NEXT_COMMAND_BY_KIND = {
    "paper": "complete-note",
    "repo": "scan-structure",
    "dataset": "profile",
    # blog's old-flow `summarize` verb was renamed to the fillable `complete-note`
    # prepare (the analyzer no longer has `summarize`); point find/review at the
    # current mainline so the rendered next command is runnable (F7).
    "blog": "complete-note",
    "idea": "analyze",
    "experiment": "diagnose",
}


def _unique_paths(paths: list[Path]) -> list[Path]:
    return sorted({Path(path).resolve(strict=False) for path in paths}, key=lambda path: path.as_posix())


def mutation_targets(root: Path, *groups: list[Path]) -> list[Path]:
    """Combine a caller's literal targets with files created by workspace setup."""
    return _unique_paths([*workspace_creation_targets(root), *(path for group in groups for path in group)])


def _gitignore_needs_update(root: Path) -> bool:
    path = kb_gitignore_path(root)
    try:
        existing = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return True
    return any(line not in existing for line in KB_GITIGNORE_LINES if line)


def workspace_creation_targets(root: Path) -> list[Path]:
    """Exact files that ensure_workspace would create or amend right now."""
    candidates = [
        kb_root(root) / "config" / "research-settings.md",
        user_root(root) / "navigation.md",
        user_root(root) / "current-state.md",
        topic_taxonomy_path(root),
        candidate_pools_path(root),
        runtime_preferences_path(root),
    ]
    targets = [path for path in candidates if not path.exists()]
    if _gitignore_needs_update(root):
        targets.append(kb_gitignore_path(root))
    return _unique_paths(targets)


def ensure_workspace_transaction(root: Path) -> None:
    targets = workspace_creation_targets(root)
    if not targets:
        # Directory-only repair is idempotent and does not enter a checkpoint.
        ensure_workspace(root)
        return
    with mutation_transaction(root, "ensure_workspace", targets):
        ensure_workspace(root)


def index_mutation_targets(root: Path) -> list[Path]:
    return _unique_paths(
        [
            topic_taxonomy_path(root),
            candidate_pools_path(root),
            kb_root(root) / "index.yaml",
            kb_root(root) / "index.md",
            passage_search_cache_path(root),
        ]
    )


def records_for_scope(root: Path, *, unit_ids: list[str] | None = None, kind: str | None = None) -> list[dict]:
    if unit_ids:
        return [locate_record(root, unit_id, kind=kind)[0] for unit_id in unit_ids]
    return list(iter_records(root, kind=kind))


def record_targets(records: list[dict], root: Path) -> list[Path]:
    return _unique_paths(
        [record_path(root, str(record["kind"]), str(record["id"])) for record in records]
    )


def compact_operation_targets(root: Path, plan: dict) -> list[Path]:
    mapping = {str(key): str(value) for key, value in dict(plan.get("mapping") or {}).items()}
    if not mapping:
        return []
    targets = record_targets(list(iter_records(root)), root) + index_mutation_targets(root)
    research = kb_root(root)
    for path in research.rglob("*"):
        if not path.is_file() or ".git" in path.parts or ".journal" in path.parts or ".runtime" in path.parts:
            continue
        try:
            text = path.read_text(encoding="utf-8") if path.suffix.lower() in TEXT_REWRITE_SUFFIXES else ""
        except (OSError, UnicodeDecodeError):
            text = ""
        if any(old_id in text or old_id in path.name for old_id in mapping):
            targets.append(path)
            renamed_name = path.name
            for old_id, new_id in mapping.items():
                renamed_name = renamed_name.replace(old_id, new_id)
            if renamed_name != path.name:
                targets.append(path.with_name(renamed_name))
    for item in plan.get("items", []):
        if not isinstance(item, dict):
            continue
        old_root = kb_root(root) / "units" / f"{item.get('kind')}s" / str(item.get("old_id") or "")
        new_root = old_root.with_name(str(item.get("new_id") or ""))
        if old_root.exists():
            for old_path in old_root.rglob("*"):
                if old_path.is_file():
                    targets.extend([old_path, new_root / old_path.relative_to(old_root)])
    return _unique_paths(targets)


def storage_sync_operation_targets(root: Path) -> list[Path]:
    """Plan KB-local storage-sync targets before opening the transaction.

    R-track narrows sync_storage_layout to KB-local writes. Keep the planning here
    so that implementation and checkpoint receive one literal path set.
    """
    targets = index_mutation_targets(root)
    research = kb_root(root)
    legacy_markers = (str((root / "raw").resolve()), str((root / "output").resolve()), "raw/", "output/")
    for path in research.rglob("*"):
        if not path.is_file() or ".git" in path.parts or ".journal" in path.parts or ".runtime" in path.parts:
            continue
        if path.name == "record.yaml" or path.suffix.lower() in TEXT_REWRITE_SUFFIXES:
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if any(marker in text for marker in legacy_markers):
                targets.append(path)
    for name in ("raw", "output"):
        source_root = root / name
        if source_root.absolute() == (research / name).absolute():
            continue
        if not source_root.exists():
            continue
        destination_root = research / name
        for source in source_root.rglob("*"):
            if source.is_file():
                targets.append(destination_root / source.relative_to(source_root))
    for nested_git in research.glob("**/.git"):
        if nested_git == research / ".git" or not nested_git.is_dir():
            continue
        targets.extend(path for path in nested_git.rglob("*") if path.is_file())
    return _unique_paths(targets)

def review_sort_key(record: dict) -> tuple:
    timestamp = str(record.get("updated_at") or record.get("created_at") or record.get("first_ingested_at") or "")
    parsed = parse_iso_datetime(timestamp)
    # Sort by the true instant (epoch seconds) so records written with different
    # timezone offsets still order chronologically; unparseable timestamps sort last.
    if parsed:
        return (0, parsed.timestamp(), str(record.get("id") or ""))
    return (1, 0.0, str(record.get("id") or ""))


def next_unit_command(record: dict) -> str:
    kind = str(record.get("kind") or "")
    unit_id = str(record.get("id") or "")
    script = SCRIPT_BY_KIND.get(kind)
    id_arg = ID_ARG_BY_KIND.get(kind)
    command = NEXT_COMMAND_BY_KIND.get(kind)
    if not script or not id_arg or not command:
        return shell_command(
            [COMMAND_PREFIX, skill_script_for_command(".agents/skills/knowledge-base-manager/scripts/kb.py"), "query", "--query", unit_id]
        )
    return shell_command([COMMAND_PREFIX, skill_script_for_command(script), command, id_arg, unit_id])


def _is_unfilled_note_shell(record: dict) -> bool:
    """Return whether a pending record still needs work before human review."""
    return (
        str(record.get("confirmation_status") or "") == "pending_user_confirmation"
        and record_workflow_state(record) != "ready_for_review"
    )


def review_queue_records(
    root: Path,
    *,
    kind: str | None = None,
    confirmation_status: str = "pending_user_confirmation",
    limit: int = 50,
) -> list[dict]:
    hits = search_records(root, "", kind=kind, confirmation_status=confirmation_status)
    if confirmation_status == "pending_user_confirmation":
        hits = [record for record in hits if is_ready_for_human_review(record)]
    hits = sorted(hits, key=review_sort_key)
    if limit > 0:
        hits = hits[:limit]
    return hits


def all_reviewed_confirmation_records(root: Path, *, kind: str | None = None, limit: int = 0) -> tuple[list[dict], int]:
    pending = review_queue_records(root, kind=kind, confirmation_status="pending_user_confirmation", limit=0)
    if limit > 0:
        selected = pending[:limit]
        return selected, max(0, len(pending) - len(selected))
    return pending, 0


def apply_batch_confirmation(
    root: Path,
    records: list[dict],
    *,
    confirmed_by: str,
    evidence: list[str],
    method: str,
    user_authorization: str = "",
    authorization_source: str = "",
) -> list[Path]:
    written: list[Path] = []
    for record in records:
        unit_id = str(record.get("id") or "")
        confirmation_status = str(record.get("confirmation_status") or "")
        if confirmation_status != "pending_user_confirmation":
            print(f"[skip] {unit_id}: confirmation_status={confirmation_status or '-'}")
            continue
        kind = str(record.get("kind") or "")
        expected_record_snapshot = canonical_record_snapshot_for_record(root, record)
        current_record = normalize_record_snapshot(expected_record_snapshot, root)
        if current_record is None:
            raise SystemExit(f"Cannot normalize current record for confirmation: {unit_id}")
        record = current_record
        updated = confirm_unit(
            record,
            kind,
            confirmed_by=confirmed_by,
            evidence=evidence,
            method=method,
            project_root=root,
            user_authorization=user_authorization,
            authorization_source=authorization_source,
            expected_record_snapshot=expected_record_snapshot,
        )
        written.append(
            write_record(root, updated, expected_record_snapshot=expected_record_snapshot)
        )
    return written


def _prepare_review_batch_decision_bound(
    root: Path,
    item: dict,
    decision: str,
    *,
    actor: str,
    evidence: list[str],
    user_authorization: str,
    authorization_source: str,
    rejection_reason: str,
) -> tuple[dict, dict, object | None]:
    """Pure-read validation and exact target planning for a root review batch."""
    route_key = "confirm_route" if decision == "confirm" else "reject_route"
    route = item.get(route_key) if isinstance(item, dict) else None
    route = route if isinstance(route, dict) else {}
    expected_action = "confirm" if decision == "confirm" else "promote"
    if route.get("owner") != "knowledge-base-manager" or route.get("action") != expected_action:
        raise ValueError("knowledge review route is invalid")
    unit_id = str(route.get("id") or "")
    record, path = locate_record(root, unit_id)
    if not is_ready_for_human_review(record):
        raise ValueError("knowledge judgement is no longer ready")
    snapshot = item.get("snapshot_binding")
    if not isinstance(snapshot, dict):
        raise ValueError("knowledge review snapshot is missing")
    require_judgement_snapshot(
        record,
        expected_snapshot=json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        owner="knowledge-base-manager",
        path=rel(root, path),
        root=root,
    )
    candidate = copy.deepcopy(record)
    expected_record_snapshot = None
    if decision == "confirm":
        expected_record_snapshot = canonical_record_snapshot_for_record(root, record)
        confirm_unit(
            candidate,
            str(candidate.get("kind") or ""),
            confirmed_by=actor,
            evidence=evidence,
            method="kb review",
            project_root=root,
            user_authorization=user_authorization,
            authorization_source=authorization_source,
            expected_record_snapshot=expected_record_snapshot,
        )
    elif decision == "reject":
        if confirmation_track(candidate) == "judgement":
            apply_judgement_rejection(candidate, reason=rejection_reason)
        elif str(candidate.get("confirmation_status") or "") != "pending_user_confirmation":
            raise ValueError("knowledge fact is no longer pending review")
    else:
        raise ValueError("knowledge review decision is invalid")
    targets = _unique_paths(record_targets([record], root) + index_mutation_targets(root))
    plan = {
        "owner": "knowledge-base-manager",
        "decision": decision,
        "unit_id": unit_id,
        "target_paths": targets,
    }
    return plan, record, expected_record_snapshot


def prepare_review_batch_decision(
    root: Path,
    item: dict,
    decision: str,
    *,
    actor: str,
    evidence: list[str],
    user_authorization: str,
    authorization_source: str,
    rejection_reason: str,
) -> dict:
    """Pure-read public plan without exposing runtime record capabilities."""
    plan, _record, _expected = _prepare_review_batch_decision_bound(
        root,
        item,
        decision,
        actor=actor,
        evidence=evidence,
        user_authorization=user_authorization,
        authorization_source=authorization_source,
        rejection_reason=rejection_reason,
    )
    return plan


def apply_review_batch_decision(
    root: Path,
    item: dict,
    decision: str,
    *,
    actor: str,
    evidence: list[str],
    user_authorization: str,
    authorization_source: str,
    rejection_reason: str,
) -> list[Path]:
    """Apply one already-root-journaled decision without a nested transaction."""
    _plan, record, expected_record_snapshot = _prepare_review_batch_decision_bound(
        root,
        item,
        decision,
        actor=actor,
        evidence=evidence,
        user_authorization=user_authorization,
        authorization_source=authorization_source,
        rejection_reason=rejection_reason,
    )
    if decision == "confirm":
        assert expected_record_snapshot is not None
        updated = confirm_unit(
            record,
            str(record.get("kind") or ""),
            confirmed_by=actor,
            evidence=evidence,
            method="kb review",
            project_root=root,
            user_authorization=user_authorization,
            authorization_source=authorization_source,
            expected_record_snapshot=expected_record_snapshot,
        )
    elif confirmation_track(record) == "judgement":
        apply_judgement_rejection(record, reason=rejection_reason)
        updated = record
    else:
        record["confirmation_status"] = "rejected"
        record["needs_human_confirmation"] = False
        record.pop("confirmation", None)
        record["rejection"] = {"at": utc_now_iso(), "reason": rejection_reason}
        updated = record
    written = write_record(
        root,
        updated,
        expected_record_snapshot=expected_record_snapshot if decision == "confirm" else None,
    )
    build_index(root)
    return [written]


def partition_review_tracks(hits: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split pending items into the two tracks in
    `.agents/lib/research/SCHEMAS.md#confirmation-gate`.

    Returns ``(fact_track, judgement_track)``. Fact = pure factual metadata eligible
    for light/batch confirm; judgement = AI inference/evaluation needing substance +
    evidence. Order within each track is preserved (already sorted oldest-first).
    """
    fact_track: list[dict] = []
    judgement_track: list[dict] = []
    for item in hits:
        if confirmation_track(item) == "judgement":
            judgement_track.append(item)
        else:
            fact_track.append(item)
    return fact_track, judgement_track


def _print_review_item(root: Path, item: dict, *, indent: str = "  ") -> None:
    kind = str(item.get("kind") or "")
    unit_id = str(item.get("id") or "")
    path = rel(root, record_path(root, kind, unit_id)) if kind and unit_id else "-"
    timestamp = str(item.get("updated_at") or item.get("created_at") or item.get("first_ingested_at") or "-")
    print(f"- {unit_id} | {kind} | {item.get('title', '')}")
    print(f"{indent}status: {item.get('status')} | confirm: {item.get('confirmation_status')} | updated: {timestamp}")
    print(f"{indent}summary: {item.get('summary') or '-'}")
    print(f"{indent}path: {path}")


def batch_light_confirm_command(*, kind: str | None = None) -> str:
    """Render the runnable fact-track batch light-confirm command."""
    parts = [
        COMMAND_PREFIX,
        skill_script_for_command(".agents/skills/knowledge-base-manager/scripts/kb.py"),
        "review-queue",
        "--confirm",
    ]
    if kind:
        parts += ["--kind", kind]
    parts += [
        "--confirmed-by",
        "${RESEARCH_CONFIRMED_BY:?set-human-identity}",
        "--evidence",
        "${RESEARCH_CONFIRM_EVIDENCE:?set-human-evidence}",
    ]
    return shell_command(parts)


def render_review_queue(root: Path, hits: list[dict], *, kind: str | None = None) -> None:
    """Render the fact/judgement tracks defined by
    `.agents/lib/research/SCHEMAS.md#confirmation-gate`.

    Fact track: light/batch confirm supported. Judgement track: each item is marked
    'needs evidence + substantive content', and its runnable per-item confirm command
    is rendered. Judgement items whose core content is still hollow are flagged so the
    substance gate is surfaced up front; substantive judgement items are highlighted
    as ready for the user to sign off (the '主动询问' signal — no orchestrator change).
    """
    fact_track, judgement_track = partition_review_tracks(hits)

    print(f"# review queue: {len(hits)} pending ({len(fact_track)} fact-track, {len(judgement_track)} judgement-track)")

    print("")
    print(f"## fact-track metadata — light/batch confirm ok, still no self-signing ({len(fact_track)})")
    if fact_track:
        for item in fact_track:
            _print_review_item(root, item)
        print("  待你确认：可一次确认以上 fact-track 条目。")
    else:
        print("  (none)")

    print("")
    print(f"## judgement-track — needs evidence + substantive content ({len(judgement_track)})")
    if not judgement_track:
        print("  (none)")
    else:
        print("  建议主动请用户拍板（关键决策/insight 不要被动等待翻队列）：")
        for item in judgement_track:
            _print_review_item(root, item)
            if has_substantive_content(item, str(item.get("kind") or "")):
                print("  ready: 内容已具备 — 需 evidence + 人工确认；⚑ 建议主动请用户拍板")
                print(f"  待你确认：说“确认 {item.get('id')}”即可。")
            else:
                print("  ⚠ hollow: core_content 为空/仅模板 — 先补实质内容再确认；promote 到 confirmed 会被实质门控拒绝")
                print("  需先补全内容，完成后再请你确认。")


def print_non_unit_review_notice() -> None:
    print(
        "注意：这个 owner 队列只列 knowledge unit；统一的公共 kb review 会另行聚合"
        "实验诊断、program decision、idea discussion 与 method selection。"
    )


# --------------------------------------------------------------------------- #
# audit: program-link policy (fix INTEGRITY_PROGRAM_LINK false positives)      #
#                                                                              #
# Canonical link design: only the FORWARD edge is stored                       #
# (program.state.active_unit_ids -> unit); the unit-side back-link is derived  #
# at read time. A program referencing an existing, non-rejected unit whose own #
# links/program_ids are empty is therefore NOT an integrity error. Real errors #
# are only: (1) a program references a unit that does not exist, (2) a program #
# references a rejected unit, (3) a unit claims membership in a program that   #
# does not exist (or whose state payload is unreadable). The shared lint layer #
# still reports symmetric back-link gaps, so the audit surface recomputes the  #
# program-link findings here with the canonical semantics.                     #
# --------------------------------------------------------------------------- #


def _program_link_finding(subject: str, message: str) -> dict:
    return {
        "code": "INTEGRITY_PROGRAM_LINK",
        "category": "integrity",
        "severity": "error",
        "subject": str(subject or "kb"),
        "message": " ".join(str(message).split()),
    }


def _record_is_rejected_for_audit(record: dict) -> bool:
    return (
        str(record.get("confirmation_status") or "").strip().lower() == "rejected"
        or str(record.get("status") or "").strip().lower() == "rejected"
    )


def _audit_program_state_files(root: Path) -> list[tuple[str, Path]]:
    """Enumerate kb/programs/<id>/state.yaml without following symlinks."""
    programs_root = kb_root(root) / "programs"
    if programs_root.is_symlink() or not programs_root.is_dir():
        return []
    entries: list[tuple[str, Path]] = []
    for child in sorted(programs_root.iterdir()):
        if child.is_symlink() or not child.is_dir():
            continue
        state_file = child / "state.yaml"
        if state_file.is_symlink() or not state_file.is_file():
            continue
        entries.append((child.name, state_file))
    return entries


def _audit_unit_records(root: Path) -> dict[str, tuple[dict, str]]:
    """Tolerantly read every unit record.yaml as {unit_id: (payload, subject)}."""
    units_root = kb_root(root) / "units"
    records: dict[str, tuple[dict, str]] = {}
    if units_root.is_symlink() or not units_root.is_dir():
        return records
    for kind_dir in sorted(units_root.iterdir()):
        if kind_dir.is_symlink() or not kind_dir.is_dir():
            continue
        for unit_dir in sorted(kind_dir.iterdir()):
            if unit_dir.is_symlink() or not unit_dir.is_dir():
                continue
            record_file = unit_dir / "record.yaml"
            if record_file.is_symlink() or not record_file.is_file():
                continue
            payload = load_yaml(record_file, default={})
            if not isinstance(payload, dict):
                continue
            unit_id = str(payload.get("id") or "")
            if not unit_id:
                continue
            try:
                subject = rel(root, record_file)
            except (SystemExit, ValueError):
                subject = "kb"
            records[unit_id] = (payload, subject)
    return records


def _text_id_list(value) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _recomputed_program_link_findings(root: Path) -> list[dict]:
    """Program-link findings under the canonical forward-edge-only semantics."""
    findings: list[dict] = []
    records = _audit_unit_records(root)
    state_by_program: dict[str, dict | None] = {}
    for program_id, state_file in _audit_program_state_files(root):
        try:
            subject = rel(root, state_file)
        except (SystemExit, ValueError):
            subject = "kb"
        payload = load_yaml(state_file, default={})
        if not isinstance(payload, dict):
            state_by_program[program_id] = None
            findings.append(_program_link_finding(
                subject, f"Program `{program_id}` state payload is not a valid mapping."
            ))
            continue
        state_by_program[program_id] = payload
        for unit_id in _text_id_list(payload.get("active_unit_ids")):
            entry = records.get(unit_id)
            if entry is None:
                findings.append(_program_link_finding(
                    subject, f"Program `{program_id}` references missing unit `{unit_id}`."
                ))
            elif _record_is_rejected_for_audit(entry[0]):
                findings.append(_program_link_finding(
                    subject, f"Program `{program_id}` references rejected unit `{unit_id}`."
                ))
    for unit_id in sorted(records):
        record, subject = records[unit_id]
        for program_id in _text_id_list(record.get("program_ids")):
            if program_id not in state_by_program:
                findings.append(_program_link_finding(
                    subject,
                    f"Unit `{unit_id}` claims membership in nonexistent program `{program_id}`.",
                ))
            elif state_by_program[program_id] is None:
                findings.append(_program_link_finding(
                    subject,
                    f"Unit `{unit_id}` references program `{program_id}` with an invalid state payload.",
                ))
    return findings


def _apply_program_link_audit_policy(root: Path, report: dict) -> dict:
    """Replace lint-derived INTEGRITY_PROGRAM_LINK findings with canonical ones.

    Identity transform for workspaces without program-link findings or programs:
    kept findings, ordering, counts and status all reproduce audit_workspace's
    exact deterministic output shape.
    """
    findings = [item for item in report.get("findings", []) if isinstance(item, dict)]
    kept = [item for item in findings if str(item.get("code")) != "INTEGRITY_PROGRAM_LINK"]
    research = kb_root(root)
    recomputed: list[dict] = []
    if research.is_dir() and not research.is_symlink():
        recomputed = _recomputed_program_link_findings(root)
    unique = {
        (item["code"], item["category"], item["severity"], item["subject"], item["message"]): item
        for item in [*kept, *recomputed]
    }

    def _order_index(values: tuple, value: str) -> int:
        return values.index(value) if value in values else len(values)

    stable = sorted(
        unique.values(),
        key=lambda item: (
            _order_index(AUDIT_CATEGORIES, item["category"]),
            _order_index(AUDIT_SEVERITIES, item["severity"]),
            item["code"],
            item["subject"],
            item["message"],
        ),
    )
    counts = {"total": len(stable)}
    counts.update({severity: 0 for severity in AUDIT_SEVERITIES})
    counts.update({category: 0 for category in AUDIT_CATEGORIES})
    for finding in stable:
        counts[finding["severity"]] = counts.get(finding["severity"], 0) + 1
        counts[finding["category"]] = counts.get(finding["category"], 0) + 1
    status = "FAIL" if counts.get("error") else ("WARN" if stable else "PASS")
    return {"status": status, "counts": counts, "findings": stable}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the research knowledge base.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize the knowledge base layout")
    subparsers.add_parser("lint", help="Validate record schemas and lifecycle fields")
    subparsers.add_parser("audit", help="Run layered, read-only KB health checks for the Agent")
    subparsers.add_parser("current-state", help="Return a read-only core status snapshot for kb-cli")
    subparsers.add_parser("index", help="Rebuild kb/index.yaml and kb/index.md")
    subparsers.add_parser("storage-sync", help="Move legacy raw/output into kb and rewrite old storage references")
    git_init = subparsers.add_parser("git-init", help="Initialize kb as a nested Git repository")
    git_init.add_argument("--no-initial-commit", action="store_true")
    git_init.add_argument("--message", default="chore: initialize kb repo")
    subparsers.add_parser("git-status", help="Show nested kb repo Git status")
    git_log = subparsers.add_parser("git-log", help="Show nested kb repo history")
    git_log.add_argument("--limit", type=int, default=10)
    git_checkpoint_cmd = subparsers.add_parser("git-checkpoint", help="Create a Git checkpoint inside kb")
    git_checkpoint_cmd.add_argument("--message", required=True)
    subparsers.add_parser("resume", help="恢复崩溃后未完成的知识库操作")
    subparsers.add_parser("undo", help="撤销最近一次已提交的知识库操作")
    restore = subparsers.add_parser("restore", help="恢复到指定操作之前的状态")
    restore.add_argument("op_id")
    compact_ids = subparsers.add_parser("compact-ids", help="Shorten and regularize knowledge-unit ids")
    compact_ids.add_argument("--kind", choices=["paper", "repo", "dataset", "blog", "idea", "experiment", "concept"])
    compact_ids.add_argument("--apply", action="store_true", help="Actually rename ids and unit folders")
    migrate_dataset = subparsers.add_parser("migrate-dataset", help="Reclassify a recognized dataset stored as repo")
    migrate_dataset.add_argument("--repo-id", required=True)
    migrate_dataset.add_argument("--apply", action="store_true")
    subparsers.add_parser("rebuild-governance", help="Rebuild topic taxonomy and candidate pool catalogs")

    query = subparsers.add_parser("query", help="Search records by title, summary, tags, topics, or pools")
    query.add_argument("--query", required=True)
    query.add_argument("--kind", choices=["paper", "repo", "dataset", "blog", "idea", "experiment", "concept"])
    query.add_argument("--pool", default="")
    query.add_argument("--confirmation-status", choices=["auto_confirmed", "pending_user_confirmation", "confirmed", "rejected"])

    review = subparsers.add_parser("review-queue", help="List records waiting for confirmation")
    review.add_argument("--kind", choices=["paper", "repo", "dataset", "blog", "idea", "experiment", "concept"])
    review.add_argument("--confirmation-status", default="pending_user_confirmation", choices=["auto_confirmed", "pending_user_confirmation", "confirmed", "rejected"])
    review.add_argument("--limit", type=int, default=50)
    review.add_argument("--confirm", action="store_true", help="Confirm the listed records in place")
    review.add_argument("--confirmed-by", default="")
    review.add_argument("--evidence", action="append", default=[])

    confirm = subparsers.add_parser("confirm", help="Confirm multiple records with one explicit evidence authorization")
    confirm.add_argument("--id", action="append", default=[])
    confirm.add_argument("--all-reviewed", action="store_true", help="Confirm the current review queue")
    confirm.add_argument("--kind", choices=["paper", "repo", "dataset", "blog", "idea", "experiment", "concept"])
    confirm.add_argument("--limit", type=int, default=0)
    confirm.add_argument("--confirmed-by", default="")
    confirm.add_argument("--evidence", action="append", required=True)
    confirm.add_argument("--user-authorization", default="")
    confirm.add_argument("--authorization-source", default="")
    confirm.add_argument("--expected-snapshot", default="")

    refresh = subparsers.add_parser("refresh-schema", help="Backfill the latest record schema")
    refresh.add_argument("--id", action="append", default=[])
    refresh.add_argument("--kind", choices=["paper", "repo", "dataset", "blog", "idea", "experiment", "concept"])

    govern = subparsers.add_parser("govern", help="Apply topic / tag / candidate-pool governance")
    govern.add_argument("--id", action="append", default=[])
    govern.add_argument("--kind", choices=["paper", "repo", "dataset", "blog", "idea", "experiment", "concept"])
    govern.add_argument("--topic", action="append", default=[])
    govern.add_argument("--tag", action="append", default=[])
    govern.add_argument("--pool", action="append", default=[])
    govern.add_argument("--all", action="store_true")
    govern.add_argument("--no-infer", action="store_true")
    govern.add_argument("--source-label", default="knowledge-base-manager")

    link = subparsers.add_parser("link", help="Link two existing records")
    link.add_argument("--from-id", required=True)
    link.add_argument("--to-id", required=True)
    link.add_argument("--relation", required=True)
    link.add_argument("--note", default="")
    link.add_argument("--source-locator-kind", choices=["unit", "heading", "block"], default="")
    link.add_argument("--source-locator-value", default="")
    link.add_argument("--target-locator-kind", choices=["unit", "heading", "block"], default="")
    link.add_argument("--target-locator-value", default="")

    promote = subparsers.add_parser("promote", help="Promote or confirm a record")
    promote.add_argument("--id", required=True)
    promote.add_argument("--status")
    promote.add_argument("--maturity", choices=["lightweight", "complete"])
    promote.add_argument("--confirmation-status", choices=["auto_confirmed", "pending_user_confirmation", "confirmed", "rejected"])
    promote.add_argument("--confirmed-by", default="")
    promote.add_argument("--evidence", action="append", default=[])
    promote.add_argument("--user-authorization", default="")
    promote.add_argument("--authorization-source", default="")
    promote.add_argument("--expected-snapshot", default="")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    if args.command == "init":
        try:
            require_workspace_rules(root)
        except WorkspaceLayoutError as exc:
            raise SystemExit(str(exc)) from exc
        initialize_workspace_layout(root, PROJECT_ROOT)
    if args.command not in {"audit", "current-state", "resume", "undo", "restore"}:
        print_resolved_project_roots(root)

    if args.command == "current-state":
        records = iter_records(root)
        program_ids = [path.parent.name for path in sorted((kb_root(root) / "programs").glob("*/state.yaml"))]
        print(
            json.dumps(
                {
                    "record_count": len(records),
                    "ready_review_count": len([record for record in records if is_ready_for_human_review(record)]),
                    "program_ids": program_ids,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    if args.command == "init":
        warn_if_cwd_differs_from_project_root(root, command="kb.py init")
        init_transaction_paths = mutation_targets(root, index_mutation_targets(root))
        # The explicit init activates the tracked layout marker before the
        # runtime can resolve canonical targets. The marker is immutable to
        # business transactions, but it must join the exact Git checkpoint.
        init_checkpoint_paths = _unique_paths(
            [layout_marker_path(root), *init_transaction_paths]
        )
        with mutation_transaction(
            root,
            "initialize_workspace",
            init_transaction_paths,
            allowed_target_classes=(
                TargetClass.CANONICAL_ARTIFACT,
                TargetClass.OPERATIONAL_STATE,
            ),
        ):
            ensure_workspace(root)
            build_index(root)
        checkpoint_and_report(
            root,
            trigger="milestone",
            message="milestone: initialize knowledge workspace",
            target_paths=init_checkpoint_paths,
        )
        print("[ok] initialized kb core workspace")
        return 0
    if args.command == "storage-sync":
        storage_paths = mutation_targets(root, storage_sync_operation_targets(root))
        with mutation_transaction(
            root,
            "storage_sync",
            storage_paths,
            allow_operational_state=True,
        ):
            ensure_workspace(root)
            payload = sync_storage_layout(root)
            build_index(root)
        print(f"[ok] moved paths: {len(payload['moved_paths'])}")
        print(f"[ok] updated records: {len(payload['updated_records'])}")
        print(f"[ok] hydrated raw paths: {len(payload['hydrated_paths'])}")
        print(f"[ok] rewritten files: {len(payload['rewritten_files'])}")
        print(f"[ok] removed nested repo metadata: {len(payload['removed_nested_git'])}")
        return 0
    if args.command == "git-init":
        ensure_workspace_transaction(root)
        payload = ensure_kb_git_repo(root, create_initial_commit=False, initial_message=args.message)
        if not args.no_initial_commit and not payload.get("head_exists"):
            initial_paths = dirty_kb_paths(root)
            if initial_paths:
                checkpoint = git_checkpoint(
                    root,
                    args.message,
                    trigger="manual",
                    auto_init=False,
                    target_paths=initial_paths,
                )
                payload["initial_commit"] = bool(checkpoint.get("committed"))
                payload["checkpoint"] = checkpoint
        if payload["created"]:
            print("知识库版本记录已初始化。")
        else:
            print("知识库版本记录已经存在。")
        if payload["initial_commit"]:
            print("已保存初始版本。")
        return 0
    if args.command == "git-status":
        payload = kb_git_status(root)
        print(payload["text"] or "[ok] clean")
        return 0 if payload.get("repo_exists") else 1
    if args.command == "git-log":
        payload = kb_git_log(root, limit=args.limit)
        print(payload["text"] or "[ok] no commits yet")
        return 0 if payload.get("repo_exists") else 1
    if args.command == "git-checkpoint":
        checkpoint_paths = dirty_kb_paths(root)
        if not checkpoint_paths:
            print("[ok] no kb changes to commit")
            return 0
        payload = git_checkpoint(root, args.message, trigger="manual", target_paths=checkpoint_paths)
        print(payload.get("message") or args.message)
        if payload.get("committed"):
            print(f"[ok] commit: {payload.get('commit')}")
        else:
            print(f"[ok] {payload.get('status')}")
        return 0
    if args.command == "resume":
        entries = incomplete_ops(root)
        if not entries:
            print("没有未完成操作需要恢复。")
            return 0
        for entry in entries:
            op_id = str(entry["op_id"])
            payload = restore_operation(root, op_id, recovery_type="resume")
            print(f"已回滚未完成操作 {op_id} 涉及的 {len(payload['restored_paths'])} 个目标。")
        return 0
    if args.command == "undo":
        payload = undo_last_operation(root)
        print(f"已撤销最近一次操作 {payload['op_id']}。")
        print("再次使用 kb undo 会继续撤销更早一次可撤销的业务操作。")
        return 0
    if args.command == "restore":
        payload = restore_operation(root, args.op_id)
        print(f"已恢复到操作 {payload['op_id']} 之前的状态。")
        print("这次恢复不会成为新的可撤销业务操作；kb undo 仍会从最近的业务操作继续。")
        return 0
    if args.command == "lint":
        status, issues = lint_records(root)
        print(f"status: {status}")
        for issue in issues:
            print(f"- {issue}")
        return 0 if status == "PASS" else 1
    if args.command == "audit":
        report = _apply_program_link_audit_policy(root, audit_workspace(root))
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1 if report["status"] == "FAIL" else 0
    if args.command == "index":
        index_paths = mutation_targets(root, index_mutation_targets(root))
        with mutation_transaction(
            root,
            "rebuild_index",
            index_paths,
            allow_operational_state=True,
        ):
            ensure_workspace(root)
            yaml_path, md_path = build_index(root)
        print(f"[ok] rebuilt index: {yaml_path.relative_to(root)} and {md_path.relative_to(root)}")
        return 0
    if args.command == "compact-ids":
        ensure_workspace_transaction(root)
        plan = compact_unit_ids(root, kind=args.kind, apply=False)
        if args.apply and plan.get("changed"):
            compact_paths = mutation_targets(root, compact_operation_targets(root, plan))
            with mutation_transaction(
                root,
                "compact_unit_ids",
                compact_paths,
                allow_operational_state=True,
            ):
                payload = compact_unit_ids(root, kind=args.kind, apply=True)
        else:
            compact_paths = []
            payload = plan
        mode = "applied" if args.apply else "dry-run"
        print(f"mode: {mode}")
        print(f"changed: {payload['changed']}")
        for item in payload["items"]:
            print(f"- {item['old_id']} -> {item['new_id']} | {item['title']}")
        if args.apply and payload["changed"]:
            print("[ok] rebuilt governance and index")
            checkpoint_and_report(
                root,
                trigger="milestone",
                message=f"milestone: compact knowledge-unit ids ({payload['changed']})",
                target_paths=compact_paths,
            )
        return 0
    if args.command == "migrate-dataset":
        plan = dataset_migration_plan(root, args.repo_id)
        print(f"mode: {'apply' if args.apply else 'dry-run'}")
        print(f"- {plan['old_id']} -> {plan['new_id']} | {plan['title']}")
        if not args.apply:
            return 0
        migration_paths = dataset_migration_targets(root, plan)
        with mutation_transaction(
            root,
            "migrate_repo_to_dataset",
            migration_paths,
            allow_operational_state=True,
        ):
            payload = migrate_repo_to_dataset(root, args.repo_id)
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: migrate dataset {payload['new_id']}",
            target_paths=migration_paths,
        )
        print(f"[ok] migrated {payload['old_id']} -> {payload['new_id']}")
        return 0
    if args.command == "rebuild-governance":
        governance_paths = mutation_targets(
            root,
            [
                topic_taxonomy_path(root),
                candidate_pools_path(root),
                kb_root(root) / "index.yaml",
                kb_root(root) / "index.md",
            ],
        )
        transaction_paths = mutation_targets(
            root,
            [*governance_paths, passage_search_cache_path(root)],
        )
        with mutation_transaction(
            root,
            "rebuild_governance",
            transaction_paths,
            allow_operational_state=True,
        ):
            ensure_workspace(root)
            index_yaml_path, index_md_path = build_index(root)
            taxonomy_path = topic_taxonomy_path(root)
            pools_path = candidate_pools_path(root)
        checkpoint_and_report(
            root,
            trigger="milestone",
            message="milestone: rebuild knowledge taxonomy",
            target_paths=governance_paths,
        )
        print(f"[ok] rebuilt {taxonomy_path.relative_to(root)}")
        print(f"[ok] rebuilt {pools_path.relative_to(root)}")
        print(f"[ok] rebuilt {index_yaml_path.relative_to(root)}")
        print(f"[ok] rebuilt {index_md_path.relative_to(root)}")
        return 0
    if args.command == "query":
        if str(args.query or "").strip():
            payload = search_passages(
                root,
                args.query,
                kind=args.kind,
                pool=args.pool or None,
                confirmation_status=args.confirmation_status,
            )
            for item in payload["results"]:
                print(f"- {item['unit_id']} | {item['kind']} | {item['title']}")
                if item.get("heading"):
                    print(f"  {item['heading']} · {item['locator']}")
                else:
                    print(f"  {item['locator']}")
                print(f"  {item['excerpt']}")
            if not payload["results"]:
                print("[ok] no matches")
            return 0
        hits = search_records(root, args.query, kind=args.kind, pool=args.pool or None, confirmation_status=args.confirmation_status)
        for item in hits:
            pools = ",".join(item.get("candidate_pools", []))
            score = item.get("_search_score")
            score_text = f" | score={score}" if score is not None else ""
            print(
                f"- {item['id']} | {item['kind']} | {item['title']} | "
                f"{item.get('status')} | {item.get('confirmation_status')} | pools={pools or '-'}{score_text}"
            )
            # Status-aware next-step hint (`docs/DESIGN.md`, "Prepare / fill / verify"), natural language only:
            # an unfilled note shell still needs the agent to fill it; a filled item
            # pending confirmation is ready for the user to confirm.
            if _is_unfilled_note_shell(item):
                print("  下一步：请让 agent 补全该条目的笔记内容。")
            elif str(item.get("confirmation_status") or "") == "pending_user_confirmation":
                print(f"  待你确认：说“确认 {item.get('id')}”即可。")
        if not hits:
            print("[ok] no matches")
        return 0
    if args.command == "review-queue":
        hits = review_queue_records(root, kind=args.kind, confirmation_status=args.confirmation_status, limit=args.limit)
        if not hits:
            print("[ok] no pending confirmations")
            print_non_unit_review_notice()
            return 0
        if args.confirm:
            if args.confirmation_status != "pending_user_confirmation":
                raise SystemExit("review-queue --confirm only supports --confirmation-status pending_user_confirmation.")
            # Batch --confirm follows .agents/lib/research/SCHEMAS.md#confirmation-gate:
            # factual metadata is eligible for blind batch confirmation. Judgement-track
            # items need per-item substance + evidence and are never confirmed here.
            fact_track, judgement_track = partition_review_tracks(hits)
            batch_paths = mutation_targets(root, record_targets(fact_track, root), index_mutation_targets(root))
            with mutation_transaction(
                root,
                "batch_confirm_review_queue",
                batch_paths,
                allow_operational_state=True,
            ):
                ensure_workspace(root)
                written = apply_batch_confirmation(
                    root,
                    fact_track,
                    confirmed_by=args.confirmed_by,
                    evidence=args.evidence,
                    method="kb.py review-queue --confirm",
                )
                build_index(root)
            checkpoint_and_report(
                root,
                trigger="milestone",
                message=f"milestone: batch confirm review queue ({len(written)} records)",
                target_paths=batch_paths,
            )
            for path in written:
                print(f"[ok] confirmed {path.relative_to(root)}")
            if not fact_track:
                print("[ok] no fact-track metadata to light-confirm")
            if judgement_track:
                print(
                    f"[skip] {len(judgement_track)} judgement-track item(s) need per-item "
                    f"substance + evidence — run 'review-queue' (no --confirm) for their confirm commands."
                )
            return 0
        render_review_queue(root, hits, kind=args.kind)
        print_non_unit_review_notice()
        return 0
    if args.command == "confirm":
        if bool(args.id) == bool(args.all_reviewed):
            raise SystemExit("Use either --id A --id B ... or --all-reviewed.")
        records = []
        remaining = 0
        if args.all_reviewed:
            records, remaining = all_reviewed_confirmation_records(root, kind=args.kind, limit=args.limit)
            if not records:
                print("[ok] no pending confirmations")
                return 0
        else:
            for unit_id in args.id:
                record, _ = locate_record(root, unit_id, kind=args.kind)
                records.append(record)
        batch_paths = mutation_targets(root, record_targets(records, root), index_mutation_targets(root))
        with mutation_transaction(
            root,
            "batch_confirm",
            batch_paths,
            allow_operational_state=True,
        ):
            ensure_workspace(root)
            if args.expected_snapshot:
                if len(records) != 1:
                    raise SystemExit("A review snapshot can apply to exactly one knowledge judgement.")
                current, current_path = locate_record(root, str(records[0].get("id") or ""), kind=args.kind)
                try:
                    require_judgement_snapshot(
                        current,
                        expected_snapshot=args.expected_snapshot,
                        owner="knowledge-base-manager",
                        path=rel(root, current_path),
                        root=root,
                    )
                except ValueError as exc:
                    raise SystemExit(str(exc)) from exc
                records = [current]
            written = apply_batch_confirmation(
                root,
                records,
                confirmed_by=args.confirmed_by,
                evidence=args.evidence,
                method="kb.py confirm",
                user_authorization=args.user_authorization,
                authorization_source=args.authorization_source,
            )
            build_index(root)
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: batch confirm ({len(written)} records)",
            target_paths=batch_paths,
        )
        for path in written:
            print(f"[ok] confirmed {path.relative_to(root)}")
        if remaining:
            print(f"[ok] confirmed {len(written)} / {remaining} remaining, re-run")
        return 0
    if args.command == "refresh-schema":
        scoped_records = records_for_scope(root, unit_ids=args.id or None, kind=args.kind)
        operation_paths = mutation_targets(root, record_targets(scoped_records, root), index_mutation_targets(root))
        with mutation_transaction(
            root,
            "refresh_record_schemas",
            operation_paths,
            allow_operational_state=True,
        ):
            ensure_workspace(root)
            paths = refresh_record_schemas(root, unit_ids=args.id or None, kind=args.kind)
            build_index(root)
        if not paths:
            print("[ok] no records refreshed")
            return 0
        for path in paths:
            print(f"[ok] refreshed {path.relative_to(root)}")
        return 0
    if args.command == "govern":
        if not args.all and not args.id and not args.kind:
            raise SystemExit("Use --all, --kind, or --id to scope governance.")
        scoped_kind = None if args.all or args.id else args.kind
        scoped_records = records_for_scope(root, unit_ids=args.id or None, kind=scoped_kind)
        operation_paths = mutation_targets(root, record_targets(scoped_records, root), index_mutation_targets(root))
        with mutation_transaction(
            root,
            "govern_records",
            operation_paths,
            allow_operational_state=True,
        ):
            ensure_workspace(root)
            paths = govern_records(
                root,
                unit_ids=args.id or None,
                kind=scoped_kind,
                explicit_topics=args.topic,
                explicit_tags=args.tag,
                explicit_pools=args.pool,
                infer_missing=not args.no_infer,
                source_label=args.source_label,
            )
            build_index(root)
        if not paths:
            print("[ok] no records governed")
            return 0
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: update kb governance ({len(paths)} records)",
            target_paths=operation_paths,
        )
        for path in paths:
            print(f"[ok] governed {path.relative_to(root)}")
        print(f"[ok] synced {topic_taxonomy_path(root).relative_to(root)}")
        print(f"[ok] synced {candidate_pools_path(root).relative_to(root)}")
        return 0
    if args.command == "link":
        from_record, _ = locate_record(root, args.from_id)
        locate_record(root, args.to_id)
        operation_paths = mutation_targets(root, record_targets([from_record], root), index_mutation_targets(root))
        with mutation_transaction(
            root,
            "link_records",
            operation_paths,
            allow_operational_state=True,
        ):
            ensure_workspace(root)
            source_locator = (
                {"kind": args.source_locator_kind, "value": args.source_locator_value}
                if args.source_locator_kind
                else None
            )
            target_locator = (
                {"kind": args.target_locator_kind, "value": args.target_locator_value}
                if args.target_locator_kind
                else None
            )
            link_records(
                root,
                args.from_id,
                args.to_id,
                args.relation,
                note=args.note,
                source_locator=source_locator,
                target_locator=target_locator,
            )
            build_index(root)
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: link {args.from_id} to {args.to_id}",
            target_paths=operation_paths,
        )
        print(f"[ok] linked {args.from_id} -> {args.to_id} ({args.relation})")
        return 0
    if args.command == "promote":
        record, _ = locate_record(root, args.id)
        operation_paths = mutation_targets(root, record_targets([record], root), index_mutation_targets(root))
        with mutation_transaction(
            root,
            "promote_record",
            operation_paths,
            allow_operational_state=True,
        ):
            ensure_workspace(root)
            if args.expected_snapshot:
                current, current_path = locate_record(root, args.id)
                try:
                    require_judgement_snapshot(
                        current,
                        expected_snapshot=args.expected_snapshot,
                        owner="knowledge-base-manager",
                        path=rel(root, current_path),
                        root=root,
                    )
                except ValueError as exc:
                    raise SystemExit(str(exc)) from exc
            if args.expected_snapshot and args.confirmation_status == "rejected":
                # Public review rejection is a judgement decision, not a loose
                # lifecycle label: keep record and canonical claim state aligned.
                reason = "; ".join(str(item).strip() for item in args.evidence if str(item).strip())
                if confirmation_track(current) == "judgement":
                    apply_judgement_rejection(current, reason=reason)
                else:
                    if str(current.get("confirmation_status") or "") != "pending_user_confirmation":
                        raise SystemExit("Only a currently pending fact can be rejected from review.")
                    current["confirmation_status"] = "rejected"
                    current["needs_human_confirmation"] = False
                    current.pop("confirmation", None)
                    current["rejection"] = {"at": utc_now_iso(), "reason": reason}
                path = write_record(root, current)
            else:
                path = promote_record(
                    root,
                    args.id,
                    status=args.status,
                    maturity=args.maturity,
                    confirmation_status=args.confirmation_status,
                    confirmed_by=args.confirmed_by,
                    evidence=args.evidence,
                    user_authorization=args.user_authorization,
                    authorization_source=args.authorization_source,
                )
            build_index(root)
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: promote {args.id}",
            target_paths=operation_paths,
        )
        print(f"[ok] updated {path.relative_to(root)}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
