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

from research.v2 import (
    build_index,
    candidate_pools_path,
    compact_unit_ids,
    ensure_kb_git_repo,
    ensure_v2_workspace,
    git_checkpoint,
    govern_records,
    kb_git_log,
    kb_git_status,
    link_records,
    lint_records,
    checkpoint_and_report,
    project_root,
    promote_record,
    rebuild_governance_catalogs,
    refresh_record_schemas,
    search_records,
    sync_storage_layout,
    topic_taxonomy_path,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the v2 research knowledge base.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize the v2 knowledge base layout")
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
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT)

    if args.command == "init":
        ensure_v2_workspace(root)
        build_index(root)
        print("[ok] initialized kb v2 workspace")
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
        hits = search_records(root, args.query, kind=args.kind, pool=args.pool or None)
        for item in hits:
            pools = ",".join(item.get("candidate_pools", []))
            print(
                f"- {item['id']} | {item['kind']} | {item['title']} | "
                f"{item.get('status')} | {item.get('confirmation_status')} | pools={pools or '-'}"
            )
        if not hits:
            print("[ok] no matches")
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
        path = promote_record(root, args.id, status=args.status, maturity=args.maturity, confirmation_status=args.confirmation_status)
        build_index(root)
        print(f"[ok] updated {path.relative_to(root)}")
        checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: promote {args.id}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
