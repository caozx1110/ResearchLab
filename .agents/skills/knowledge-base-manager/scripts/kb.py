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
    ensure_v2_workspace,
    govern_records,
    link_records,
    lint_records,
    project_root,
    promote_record,
    rebuild_governance_catalogs,
    refresh_record_schemas,
    search_records,
    write_candidate_pools,
    write_topic_taxonomy,
    load_candidate_pools,
    load_topic_taxonomy,
    topic_taxonomy_path,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the v2 research knowledge base.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("init", help="Initialize the v2 knowledge base layout")
    subparsers.add_parser("lint", help="Validate record schemas and lifecycle fields")
    subparsers.add_parser("index", help="Rebuild kb/index.yaml and kb/index.md")
    subparsers.add_parser("rebuild-governance", help="Rebuild topic taxonomy and candidate pool catalogs")
    subparsers.add_parser("taxonomy-sync", help="Alias of rebuild-governance")

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

    taxonomy_lint = subparsers.add_parser("taxonomy-lint", help="Check taxonomy/pool files")
    taxonomy_lint.add_argument("--strict", action="store_true")

    subparsers.add_parser("taxonomy-apply", help="Alias of govern --all")

    topic_upsert = subparsers.add_parser("topic-upsert", help="Add or update a topic entry")
    topic_upsert.add_argument("--topic", required=True)
    topic_upsert.add_argument("--description", default="")

    pool_upsert = subparsers.add_parser("pool-upsert", help="Add or update a candidate pool entry")
    pool_upsert.add_argument("--pool", required=True)
    pool_upsert.add_argument("--summary", default="")
    pool_upsert.add_argument("--topic", action="append", default=[])
    pool_upsert.add_argument("--tag", action="append", default=[])

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
    if args.command in {"rebuild-governance", "taxonomy-sync"}:
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
        return 0
    if args.command == "taxonomy-lint":
        taxonomy = load_topic_taxonomy(root)
        pools = load_candidate_pools(root)
        issues = []
        if not isinstance(taxonomy.get("topics", {}), dict):
            issues.append("topic taxonomy must contain topics mapping")
        if not isinstance(taxonomy.get("tags", {}), dict):
            issues.append("topic taxonomy must contain tags mapping")
        if not isinstance(pools.get("pools", {}), dict):
            issues.append("candidate pools must contain pools mapping")
        status = "PASS" if not issues else "FAIL"
        print(f"status: {status}")
        for issue in issues:
            print(f"- {issue}")
        return 0 if status == "PASS" or not args.strict else 1
    if args.command == "taxonomy-apply":
        paths = govern_records(root, unit_ids=None, kind=None, explicit_topics=[], explicit_tags=[], explicit_pools=[], infer_missing=True, source_label="knowledge-base-manager")
        build_index(root)
        for path in paths[:20]:
            print(f"[ok] governed {path.relative_to(root)}")
        return 0
    if args.command == "topic-upsert":
        payload = load_topic_taxonomy(root)
        topic_id = args.topic
        item = payload["topics"].setdefault(topic_id, {"id": topic_id, "aliases": [], "tags": [], "pools": [], "member_ids": [], "count": 0, "note": "", "status": "active"})
        item["note"] = args.description
        path = write_topic_taxonomy(root, payload)
        print(f"[ok] updated {path.relative_to(root)}")
        return 0
    if args.command == "pool-upsert":
        payload = load_candidate_pools(root)
        pool_id = args.pool
        item = payload["pools"].setdefault(pool_id, {"id": pool_id, "summary": "", "topic_hints": [], "tags": [], "member_ids": [], "kinds": [], "status": "active"})
        item["summary"] = args.summary
        item["topic_hints"] = sorted(set(item.get("topic_hints", [])) | set(args.topic))
        item["tags"] = sorted(set(item.get("tags", [])) | set(args.tag))
        path = write_candidate_pools(root, payload)
        print(f"[ok] updated {path.relative_to(root)}")
        return 0
    if args.command == "link":
        link_records(root, args.from_id, args.to_id, args.relation, note=args.note)
        build_index(root)
        print(f"[ok] linked {args.from_id} -> {args.to_id} ({args.relation})")
        return 0
    if args.command == "promote":
        path = promote_record(root, args.id, status=args.status, maturity=args.maturity, confirmation_status=args.confirmation_status)
        build_index(root)
        print(f"[ok] updated {path.relative_to(root)}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
