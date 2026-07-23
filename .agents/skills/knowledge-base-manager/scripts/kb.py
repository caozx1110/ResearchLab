#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

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

from research.common import add_project_root_argument, confirm_command, parse_iso_datetime, print_resolved_project_roots, shell_command, skill_script_for_command, warn_if_cwd_differs_from_project_root
from research.core import (
    build_index,
    audit_workspace,
    candidate_pools_path,
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
    search_records,
    sync_storage_layout,
    topic_taxonomy_path,
    undo_last_operation,
    write_record,
)
from research.git_ops import dirty_kb_paths
from research.journal import abort_op, incomplete_ops, mutation_transaction
from research.paths import KB_GITIGNORE_LINES, TEXT_REWRITE_SUFFIXES, kb_gitignore_path, kb_root, runtime_preferences_path, user_root

COMMAND_PREFIX = "${RESEARCH_PYTHON:-python3}"
SCRIPT_BY_KIND = {
    "paper": ".agents/skills/paper-analyst/scripts/paper.py",
    "repo": ".agents/skills/repo-analyst/scripts/repo.py",
    "dataset": ".agents/skills/dataset-analyst/scripts/dataset.py",
    "blog": ".agents/skills/blog-analyst/scripts/blog.py",
    "idea": ".agents/skills/idea-workbench/scripts/idea.py",
    "experiment": ".agents/skills/experiment-workbench/scripts/experiment.py",
}
ID_ARG_BY_KIND = {
    "paper": "--paper-id",
    "repo": "--repo-id",
    "dataset": "--dataset-id",
    "blog": "--blog-id",
    "idea": "--idea-id",
    "experiment": "--experiment-id",
}
NEXT_COMMAND_BY_KIND = {
    "paper": "screen",
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
        root / "kb" / "config" / "research-settings.md",
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
            root / "kb" / "index.yaml",
            root / "kb" / "index.md",
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
        old_root = root / "kb" / "units" / f"{item.get('kind')}s" / str(item.get("old_id") or "")
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
        updated = confirm_unit(
            record,
            kind,
            confirmed_by=confirmed_by,
            evidence=evidence,
            method=method,
            project_root=root,
            user_authorization=user_authorization,
            authorization_source=authorization_source,
        )
        written.append(write_record(root, updated))
    return written


def partition_review_tracks(hits: list[dict]) -> tuple[list[dict], list[dict]]:
    """Split pending items into the two confirmation tracks (SSOT §3.11 decision ①).

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
    """Two-track grouped review queue (SSOT §3.11: fact metadata vs judgement).

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
        "注意：确认收件箱当前只覆盖 knowledge unit；实验诊断子项 / decision-log 待决策 / "
        "learnings 可能另有待确认，请分别查看。"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the research knowledge base.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize the knowledge base layout")
    subparsers.add_parser("lint", help="Validate record schemas and lifecycle fields")
    subparsers.add_parser("audit", help="Run layered, read-only KB health checks for the Agent")
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
    compact_ids.add_argument("--kind", choices=["paper", "repo", "dataset", "blog", "idea", "experiment"])
    compact_ids.add_argument("--apply", action="store_true", help="Actually rename ids and unit folders")
    migrate_dataset = subparsers.add_parser("migrate-dataset", help="Reclassify a recognized dataset stored as repo")
    migrate_dataset.add_argument("--repo-id", required=True)
    migrate_dataset.add_argument("--apply", action="store_true")
    subparsers.add_parser("rebuild-governance", help="Rebuild topic taxonomy and candidate pool catalogs")

    query = subparsers.add_parser("query", help="Search records by title, summary, tags, topics, or pools")
    query.add_argument("--query", required=True)
    query.add_argument("--kind", choices=["paper", "repo", "dataset", "blog", "idea", "experiment"])
    query.add_argument("--pool", default="")
    query.add_argument("--confirmation-status", choices=["auto_confirmed", "pending_user_confirmation", "confirmed", "rejected"])

    review = subparsers.add_parser("review-queue", help="List records waiting for confirmation")
    review.add_argument("--kind", choices=["paper", "repo", "dataset", "blog", "idea", "experiment"])
    review.add_argument("--confirmation-status", default="pending_user_confirmation", choices=["auto_confirmed", "pending_user_confirmation", "confirmed", "rejected"])
    review.add_argument("--limit", type=int, default=50)
    review.add_argument("--confirm", action="store_true", help="Confirm the listed records in place")
    review.add_argument("--confirmed-by", default="")
    review.add_argument("--evidence", action="append", default=[])

    confirm = subparsers.add_parser("confirm", help="Confirm multiple records with one explicit evidence authorization")
    confirm.add_argument("--id", action="append", default=[])
    confirm.add_argument("--all-reviewed", action="store_true", help="Confirm the current review queue")
    confirm.add_argument("--kind", choices=["paper", "repo", "dataset", "blog", "idea", "experiment"])
    confirm.add_argument("--limit", type=int, default=0)
    confirm.add_argument("--confirmed-by", default="")
    confirm.add_argument("--evidence", action="append", required=True)
    confirm.add_argument("--user-authorization", default="")
    confirm.add_argument("--authorization-source", default="")

    refresh = subparsers.add_parser("refresh-schema", help="Backfill the latest record schema")
    refresh.add_argument("--id", action="append", default=[])
    refresh.add_argument("--kind", choices=["paper", "repo", "dataset", "blog", "idea", "experiment"])

    govern = subparsers.add_parser("govern", help="Apply topic / tag / candidate-pool governance")
    govern.add_argument("--id", action="append", default=[])
    govern.add_argument("--kind", choices=["paper", "repo", "dataset", "blog", "idea", "experiment"])
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
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    if args.command not in {"audit", "resume", "undo", "restore"}:
        print_resolved_project_roots(root)

    if args.command == "init":
        warn_if_cwd_differs_from_project_root(root, command="kb.py init")
        init_paths = mutation_targets(root, index_mutation_targets(root))
        with mutation_transaction(root, "initialize_workspace", init_paths):
            ensure_workspace(root)
            build_index(root)
        checkpoint_and_report(
            root,
            trigger="milestone",
            message="milestone: initialize knowledge workspace",
            target_paths=init_paths,
        )
        print("[ok] initialized kb core workspace")
        return 0
    if args.command == "storage-sync":
        storage_paths = mutation_targets(root, storage_sync_operation_targets(root))
        with mutation_transaction(root, "storage_sync", storage_paths):
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
        print(f"repo_path: {payload['repo_path']}")
        print(f"created: {payload['created']}")
        print(f"initial_commit: {payload['initial_commit']}")
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
            abort_op(root, op_id)
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
        report = audit_workspace(root)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1 if report["status"] == "FAIL" else 0
    if args.command == "index":
        index_paths = mutation_targets(root, index_mutation_targets(root))
        with mutation_transaction(root, "rebuild_index", index_paths):
            ensure_workspace(root)
            yaml_path, md_path = build_index(root)
        print(f"[ok] rebuilt index: {yaml_path.relative_to(root)} and {md_path.relative_to(root)}")
        return 0
    if args.command == "compact-ids":
        ensure_workspace_transaction(root)
        plan = compact_unit_ids(root, kind=args.kind, apply=False)
        if args.apply and plan.get("changed"):
            compact_paths = mutation_targets(root, compact_operation_targets(root, plan))
            with mutation_transaction(root, "compact_unit_ids", compact_paths):
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
        with mutation_transaction(root, "migrate_repo_to_dataset", migration_paths):
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
        governance_paths = mutation_targets(root, [topic_taxonomy_path(root), candidate_pools_path(root)])
        with mutation_transaction(root, "rebuild_governance", governance_paths):
            ensure_workspace(root)
            taxonomy_path, pools_path = rebuild_governance_catalogs(root)
        print(f"[ok] rebuilt {taxonomy_path.relative_to(root)}")
        print(f"[ok] rebuilt {pools_path.relative_to(root)}")
        return 0
    if args.command == "query":
        hits = search_records(root, args.query, kind=args.kind, pool=args.pool or None, confirmation_status=args.confirmation_status)
        for item in hits:
            pools = ",".join(item.get("candidate_pools", []))
            score = item.get("_search_score")
            score_text = f" | score={score}" if score is not None else ""
            print(
                f"- {item['id']} | {item['kind']} | {item['title']} | "
                f"{item.get('status')} | {item.get('confirmation_status')} | pools={pools or '-'}{score_text}"
            )
            # Status-aware next-step hint (SSOT 3.11/A4), natural language only:
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
            # Batch --confirm is the fact-track light-confirm path (SSOT §3.11): only
            # factual metadata is eligible for blind batch confirmation. Judgement-track
            # items need per-item substance + evidence and are never confirmed here.
            fact_track, judgement_track = partition_review_tracks(hits)
            batch_paths = mutation_targets(root, record_targets(fact_track, root), index_mutation_targets(root))
            with mutation_transaction(root, "batch_confirm_review_queue", batch_paths):
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
        with mutation_transaction(root, "batch_confirm", batch_paths):
            ensure_workspace(root)
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
        with mutation_transaction(root, "refresh_record_schemas", operation_paths):
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
        with mutation_transaction(root, "govern_records", operation_paths):
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
        with mutation_transaction(root, "link_records", operation_paths):
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
        with mutation_transaction(root, "promote_record", operation_paths):
            ensure_workspace(root)
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
