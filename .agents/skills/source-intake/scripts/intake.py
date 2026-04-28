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
    apply_record_governance,
    backup_source,
    build_index,
    default_record,
    detect_duplicate,
    ensure_v2_workspace,
    load_search_stage,
    mark_search_candidate,
    maybe_auto_checkpoint,
    normalize_storage_reference,
    project_root,
    resolve_search_candidate,
    stage_search_results,
    write_record,
)


def infer_title(source: str) -> str:
    if source.startswith("http"):
        return source.rstrip("/").split("/")[-1] or source
    return Path(source).stem.replace("_", " ")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest a source into the v2 knowledge base.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add", help="Add a paper, repo, or blog source")
    add.add_argument("--kind", required=True, choices=["paper", "repo", "blog"])
    add.add_argument("--source", default="")
    add.add_argument("--maturity", default="lightweight", choices=["lightweight", "complete"])
    add.add_argument("--title", default="")
    add.add_argument("--stage-id", default="")
    add.add_argument("--candidate-id", default="")
    add.add_argument("--pool", action="append", default=[])

    for search_name in ("search", "stage-search"):
        stage = subparsers.add_parser(search_name, help="Record search candidates before canonical intake")
        stage.add_argument("--kind", required=True, choices=["paper", "repo", "blog"])
        stage.add_argument("--query", required=True)
        stage.add_argument("--stage-id", default="")
        stage.add_argument("--candidate-url", action="append", default=[])
        stage.add_argument("--candidate-title", action="append", default=[])
        stage.add_argument("--note", default="")

    show = subparsers.add_parser("show-stage", help="Inspect a recorded search stage")
    show.add_argument("--stage-id", required=True)
    return parser


def stage_candidates(args: argparse.Namespace) -> list[dict]:
    titles = list(args.candidate_title)
    candidates = []
    for index, url in enumerate(args.candidate_url):
        title = titles[index] if index < len(titles) else ""
        candidates.append({"title": title, "url": url})
    return candidates


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT)
    ensure_v2_workspace(root)

    if args.command in {"search", "stage-search"}:
        candidates = stage_candidates(args)
        path = stage_search_results(
            root,
            kind=args.kind,
            query=args.query,
            candidates=candidates,
            stage_id=args.stage_id,
            note=args.note,
        )
        print(f"[ok] wrote {path.relative_to(root)}")
        return 0

    if args.command == "show-stage":
        payload = load_search_stage(root, args.stage_id)
        print(f"id: {payload['id']}")
        print(f"source_kind: {payload.get('source_kind')}")
        print(f"query: {payload.get('query')}")
        for candidate in payload.get("candidates", []):
            print(
                f"- {candidate.get('candidate_id')} | {candidate.get('status')} | "
                f"{candidate.get('title') or '-'} | {candidate.get('url')}"
            )
        return 0

    source = args.source
    staged_candidate = None
    if args.stage_id and args.candidate_id:
        staged_candidate = resolve_search_candidate(root, args.stage_id, args.candidate_id)
        source = source or str(staged_candidate.get("url") or "")
    if not source:
        raise SystemExit("Provide --source or use --stage-id + --candidate-id.")
    source = normalize_storage_reference(root, source) if not source.startswith("http") else source

    duplicate = detect_duplicate(root, args.kind, source)
    if duplicate:
        if args.stage_id and args.candidate_id:
            mark_search_candidate(root, args.stage_id, args.candidate_id, status="duplicate", record_id=str(duplicate["id"]))
        print(f"[ok] duplicate detected: {duplicate['id']}")
        return 0

    title = args.title or (str(staged_candidate.get("title") or "") if staged_candidate else "") or infer_title(source)
    record = default_record(args.kind, title=title, maturity=args.maturity, source={"original_uri": source})
    source_info = backup_source(root, args.kind, record["id"], source)
    record["source"] = source_info
    record["status"] = "active"
    record["summary"] = f"Lightweight {args.kind} intake for `{title}`."
    record = apply_record_governance(
        root,
        record,
        explicit_topics=(staged_candidate.get("topics", []) if staged_candidate else []),
        explicit_tags=(staged_candidate.get("tags", []) if staged_candidate else []),
        explicit_pools=args.pool + (staged_candidate.get("pool_hints", []) if staged_candidate else []),
        infer_missing=True,
        source_label="source-intake",
    )
    if staged_candidate:
        payload = record["payload"].setdefault("source_search", {})
        payload["stage_ids"] = sorted(set(payload.get("stage_ids", [])) | {args.stage_id})
        payload["candidate_ids"] = sorted(set(payload.get("candidate_ids", [])) | {args.candidate_id})
        stage_payload = load_search_stage(root, args.stage_id)
        payload["queries"] = sorted(set(payload.get("queries", [])) | {str(stage_payload.get("query") or "")})

    if args.kind == "paper":
        record["payload"]["basic_info"]["title"] = title
        record["payload"]["basic_info"]["source_url"] = source if source.startswith("http") else ""
    elif args.kind == "repo":
        record["payload"]["basic_info"]["name"] = title
        record["payload"]["basic_info"]["url"] = source if source.startswith("http") else ""
    else:
        record["payload"]["basic_info"]["title"] = title
        record["payload"]["basic_info"]["url"] = source if source.startswith("http") else ""
    path = write_record(root, record)
    build_index(root)
    if args.stage_id and args.candidate_id:
        mark_search_candidate(root, args.stage_id, args.candidate_id, status="materialized", record_id=str(record["id"]))
    print(f"[ok] created {path.relative_to(root)}")
    checkpoint = maybe_auto_checkpoint(root, trigger="milestone", message=f"milestone: intake {args.kind} {record['id']}")
    if checkpoint.get("committed"):
        print(f"[ok] git checkpoint: {checkpoint.get('commit')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
