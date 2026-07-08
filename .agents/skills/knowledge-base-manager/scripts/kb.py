#!/usr/bin/env python3
from __future__ import annotations

import argparse
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
    candidate_pools_path,
    compact_unit_ids,
    confirm_unit,
    ensure_kb_git_repo,
    ensure_workspace,
    git_checkpoint,
    govern_records,
    kb_git_log,
    kb_git_status,
    link_records,
    lint_records,
    locate_record,
    checkpoint_and_report,
    project_root,
    promote_record,
    record_path,
    rebuild_governance_catalogs,
    rel,
    refresh_record_schemas,
    search_records,
    sync_storage_layout,
    topic_taxonomy_path,
    write_record,
)

COMMAND_PREFIX = "${RESEARCH_PYTHON:-python3}"
SCRIPT_BY_KIND = {
    "paper": ".agents/skills/paper-analyst/scripts/paper.py",
    "repo": ".agents/skills/repo-analyst/scripts/repo.py",
    "blog": ".agents/skills/blog-analyst/scripts/blog.py",
    "idea": ".agents/skills/idea-workbench/scripts/idea.py",
    "experiment": ".agents/skills/experiment-workbench/scripts/experiment.py",
}
ID_ARG_BY_KIND = {
    "paper": "--paper-id",
    "repo": "--repo-id",
    "blog": "--blog-id",
    "idea": "--idea-id",
    "experiment": "--experiment-id",
}
NEXT_COMMAND_BY_KIND = {
    "paper": "screen",
    "repo": "scan-structure",
    "blog": "summarize",
    "idea": "analyze",
    "experiment": "diagnose",
}

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


def review_queue_records(
    root: Path,
    *,
    kind: str | None = None,
    confirmation_status: str = "pending_user_confirmation",
    limit: int = 50,
) -> list[dict]:
    hits = search_records(root, "", kind=kind, confirmation_status=confirmation_status)
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


def apply_batch_confirmation(root: Path, records: list[dict], *, confirmed_by: str, evidence: list[str], method: str) -> list[Path]:
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
        )
        written.append(write_record(root, updated))
    return written


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the research knowledge base.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize the knowledge base layout")
    subparsers.add_parser("lint", help="Validate record schemas and lifecycle fields")
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
    compact_ids = subparsers.add_parser("compact-ids", help="Shorten and regularize knowledge-unit ids")
    compact_ids.add_argument("--kind", choices=["paper", "repo", "blog", "idea", "experiment"])
    compact_ids.add_argument("--apply", action="store_true", help="Actually rename ids and unit folders")
    subparsers.add_parser("rebuild-governance", help="Rebuild topic taxonomy and candidate pool catalogs")

    query = subparsers.add_parser("query", help="Search records by title, summary, tags, topics, or pools")
    query.add_argument("--query", required=True)
    query.add_argument("--kind", choices=["paper", "repo", "blog", "idea", "experiment"])
    query.add_argument("--pool", default="")
    query.add_argument("--confirmation-status", choices=["auto_confirmed", "pending_user_confirmation", "confirmed", "rejected"])

    review = subparsers.add_parser("review-queue", help="List records waiting for confirmation")
    review.add_argument("--kind", choices=["paper", "repo", "blog", "idea", "experiment"])
    review.add_argument("--confirmation-status", default="pending_user_confirmation", choices=["auto_confirmed", "pending_user_confirmation", "confirmed", "rejected"])
    review.add_argument("--limit", type=int, default=50)
    review.add_argument("--confirm", action="store_true", help="Confirm the listed records in place")
    review.add_argument("--confirmed-by", default="")
    review.add_argument("--evidence", action="append", default=[])

    confirm = subparsers.add_parser("confirm", help="Confirm multiple records with one explicit evidence authorization")
    confirm.add_argument("--id", action="append", default=[])
    confirm.add_argument("--all-reviewed", action="store_true", help="Confirm the current review queue")
    confirm.add_argument("--kind", choices=["paper", "repo", "blog", "idea", "experiment"])
    confirm.add_argument("--limit", type=int, default=0)
    confirm.add_argument("--confirmed-by", default="")
    confirm.add_argument("--evidence", action="append", required=True)

    refresh = subparsers.add_parser("refresh-schema", help="Backfill the latest record schema")
    refresh.add_argument("--id", action="append", default=[])
    refresh.add_argument("--kind", choices=["paper", "repo", "blog", "idea", "experiment"])

    govern = subparsers.add_parser("govern", help="Apply topic / tag / candidate-pool governance")
    govern.add_argument("--id", action="append", default=[])
    govern.add_argument("--kind", choices=["paper", "repo", "blog", "idea", "experiment"])
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

    promote = subparsers.add_parser("promote", help="Promote or confirm a record")
    promote.add_argument("--id", required=True)
    promote.add_argument("--status")
    promote.add_argument("--maturity", choices=["lightweight", "complete"])
    promote.add_argument("--confirmation-status", choices=["auto_confirmed", "pending_user_confirmation", "confirmed", "rejected"])
    promote.add_argument("--confirmed-by", default="")
    promote.add_argument("--evidence", action="append", default=[])
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)

    if args.command == "init":
        warn_if_cwd_differs_from_project_root(root, command="kb.py init")
        ensure_workspace(root)
        build_index(root)
        print("[ok] initialized kb core workspace")
        return 0
    if args.command == "storage-sync":
        payload = sync_storage_layout(root)
        build_index(root)
        print(f"[ok] moved paths: {len(payload['moved_paths'])}")
        print(f"[ok] updated records: {len(payload['updated_records'])}")
        print(f"[ok] hydrated raw paths: {len(payload['hydrated_paths'])}")
        print(f"[ok] rewritten files: {len(payload['rewritten_files'])}")
        print(f"[ok] removed nested repo metadata: {len(payload['removed_nested_git'])}")
        return 0
    if args.command == "git-init":
        payload = ensure_kb_git_repo(root, create_initial_commit=not args.no_initial_commit, initial_message=args.message)
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
        payload = git_checkpoint(root, args.message, trigger="manual")
        print(payload.get("message") or args.message)
        if payload.get("committed"):
            print(f"[ok] commit: {payload.get('commit')}")
        else:
            print(f"[ok] {payload.get('status')}")
        return 0
    if args.command == "lint":
        status, issues = lint_records(root)
        print(f"status: {status}")
        for issue in issues:
            print(f"- {issue}")
        return 0 if status == "PASS" else 1
    if args.command == "index":
        yaml_path, md_path = build_index(root)
        print(f"[ok] rebuilt index: {yaml_path.relative_to(root)} and {md_path.relative_to(root)}")
        return 0
    if args.command == "compact-ids":
        payload = compact_unit_ids(root, kind=args.kind, apply=args.apply)
        mode = "applied" if args.apply else "dry-run"
        print(f"mode: {mode}")
        print(f"changed: {payload['changed']}")
        for item in payload["items"]:
            print(f"- {item['old_id']} -> {item['new_id']} | {item['title']}")
        if args.apply and payload["changed"]:
            print("[ok] rebuilt governance and index")
            checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: compact knowledge-unit ids ({payload['changed']})")
        return 0
    if args.command == "rebuild-governance":
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
            print(f"  next: {next_unit_command(item)}")
            if str(item.get("confirmation_status") or "") == "pending_user_confirmation":
                print(f"  confirm: {confirm_command(item)}")
        if not hits:
            print("[ok] no matches")
        return 0
    if args.command == "review-queue":
        hits = review_queue_records(root, kind=args.kind, confirmation_status=args.confirmation_status, limit=args.limit)
        if not hits:
            print("[ok] no pending confirmations")
            return 0
        if args.confirm:
            if args.confirmation_status != "pending_user_confirmation":
                raise SystemExit("review-queue --confirm only supports --confirmation-status pending_user_confirmation.")
            written = apply_batch_confirmation(
                root,
                hits,
                confirmed_by=args.confirmed_by,
                evidence=args.evidence,
                method="kb.py review-queue --confirm",
            )
            build_index(root)
            for path in written:
                print(f"[ok] confirmed {path.relative_to(root)}")
            checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: batch confirm review queue ({len(written)} records)")
            return 0
        for item in hits:
            kind = str(item.get("kind") or "")
            unit_id = str(item.get("id") or "")
            path = rel(root, record_path(root, kind, unit_id)) if kind and unit_id else "-"
            timestamp = str(item.get("updated_at") or item.get("created_at") or item.get("first_ingested_at") or "-")
            print(f"- {unit_id} | {kind} | {item.get('title', '')}")
            print(f"  status: {item.get('status')} | confirm: {item.get('confirmation_status')} | updated: {timestamp}")
            print(f"  summary: {item.get('summary') or '-'}")
            print(f"  path: {path}")
            print(f"  confirm: {confirm_command(item)}")
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
        written = apply_batch_confirmation(
            root,
            records,
            confirmed_by=args.confirmed_by,
            evidence=args.evidence,
            method="kb.py confirm",
        )
        build_index(root)
        for path in written:
            print(f"[ok] confirmed {path.relative_to(root)}")
        if remaining:
            print(f"[ok] confirmed {len(written)} / {remaining} remaining, re-run")
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: batch confirm ({len(written)} records)")
        return 0
    if args.command == "refresh-schema":
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
        paths = govern_records(
            root,
            unit_ids=args.id or None,
            kind=None if args.all or args.id else args.kind,
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
        for path in paths:
            print(f"[ok] governed {path.relative_to(root)}")
        print(f"[ok] synced {topic_taxonomy_path(root).relative_to(root)}")
        print(f"[ok] synced {candidate_pools_path(root).relative_to(root)}")
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: update kb governance ({len(paths)} records)")
        return 0
    if args.command == "link":
        link_records(root, args.from_id, args.to_id, args.relation, note=args.note)
        build_index(root)
        print(f"[ok] linked {args.from_id} -> {args.to_id} ({args.relation})")
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: link {args.from_id} to {args.to_id}")
        return 0
    if args.command == "promote":
        path = promote_record(
            root,
            args.id,
            status=args.status,
            maturity=args.maturity,
            confirmation_status=args.confirmation_status,
            confirmed_by=args.confirmed_by,
            evidence=args.evidence,
        )
        build_index(root)
        print(f"[ok] updated {path.relative_to(root)}")
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: promote {args.id}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
