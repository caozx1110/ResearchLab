#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import subprocess
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

from research.common import add_project_root_argument, confirm_command as shared_confirm_command, extract_pdf_record, parse_arxiv_id, print_resolved_project_roots, shell_command
from research.intake_cli import add_intake_add_arguments
from research.core import (
    apply_record_governance,
    backup_source,
    build_index,
    default_record,
    detect_duplicate,
    ensure_workspace,
    load_runtime_preferences,
    load_search_stage,
    locate_record,
    mark_search_candidate,
    checkpoint_and_report,
    normalize_storage_reference,
    project_root,
    resolve_local_reference,
    resolve_search_candidate,
    stage_search_results,
    write_record,
)


def infer_title(source: str) -> str:
    if source.startswith("http"):
        return source.rstrip("/").split("/")[-1] or source
    return Path(source).stem.replace("_", " ")


def research_python() -> str:
    return os.environ.get("RESEARCH_PYTHON") or sys.executable or "python3"


def confirm_command(record: dict) -> str:
    python = research_python()
    return shared_confirm_command(record, command_prefix=python, direct_kinds=("paper", "repo", "blog"))


def infer_paper_metadata(root: Path, source: str) -> dict:
    if source.startswith("http"):
        return {}
    path = resolve_local_reference(root, source) or Path(source).expanduser()
    if not path.exists() or path.suffix.lower() != ".pdf":
        return {}
    try:
        return extract_pdf_record(path)
    except Exception:  # noqa: BLE001
        return {}


def canonical_paper_source_url(source: str, metadata: dict) -> str:
    arxiv_id = str(metadata.get("arxiv_id") or parse_arxiv_id(source) or "").strip()
    arxiv_id = arxiv_id.split("v", 1)[0] if arxiv_id else ""
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    return source if source.startswith("http") else ""


def run_paper_command(root: Path, *args: str) -> list[str]:
    cmd = [
        research_python(),
        str(root / ".agents" / "skills" / "paper-analyst" / "scripts" / "paper.py"),
        *args,
    ]
    result = subprocess.run(cmd, cwd=root, text=True, capture_output=True, check=False)
    output = [
        line.strip()
        for line in (result.stdout.splitlines() + result.stderr.splitlines())
        if line.strip()
    ]
    if result.returncode != 0:
        raise SystemExit("\n".join(output) or f"paper command failed: {' '.join(cmd)}")
    return output


def should_auto_complete_note(record: dict, preferences: dict) -> bool:
    if not bool(preferences.get("auto_complete_note")):
        return False
    condition = str(preferences.get("auto_complete_note_condition") or "suggested_worth_reading")
    quick = record.get("payload", {}).get("quick_screen", {})
    worth = str(quick.get("worth_deep_reading") or "")
    relevance = str(quick.get("relevance_to_current_research") or "")
    if condition == "after_screen":
        return True
    if condition == "strong_relevance":
        return relevance in {"strong", "moderate"}
    return worth in {"yes", "maybe"}


def guidance_hints(preferences: dict, *, has_pdf: bool, note_created: bool) -> list[str]:
    if not bool(preferences.get("prompt_for_preference_updates", True)):
        return []
    hints = [
        "查看当前文献入库默认模式："
        f"{research_python()} .agents/skills/research-config-manager/scripts/config.py guide --focus paper-intake",
    ]
    if not bool(preferences.get("auto_complete_note")):
        hints.append(
            "如需让值得读的论文默认自动生成完整笔记："
            f"{research_python()} .agents/skills/research-config-manager/scripts/config.py "
            "set-runtime-pref --section paper --key auto_complete_note --value true"
        )
    if note_created and str(preferences.get("complete_note_mode") or "scaffold") != "draft":
        hints.append(
            "如需默认直接生成更饱满的 draft："
            f"{research_python()} .agents/skills/research-config-manager/scripts/config.py "
            "set-runtime-pref --section paper --key complete_note_mode --value draft"
        )
    if has_pdf and not bool(preferences.get("auto_extract_figures_after_note")):
        hints.append(
            "如需完整笔记后自动提取 Figure / Table："
            f"{research_python()} .agents/skills/research-config-manager/scripts/config.py "
            "set-runtime-pref --section paper --key auto_extract_figures_after_note --value true"
        )
    return hints[:3]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest a source into the knowledge base.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add", help="Add a paper, repo, or blog source")
    add_intake_add_arguments(add, include_stage_options=True)

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
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    ensure_workspace(root)

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
    paper_metadata = infer_paper_metadata(root, source) if args.kind == "paper" else {}
    title = (
        args.title
        or (str(staged_candidate.get("title") or "") if staged_candidate else "")
        or str(paper_metadata.get("title") or "").strip()
        or infer_title(source)
    )

    duplicate = detect_duplicate(root, args.kind, source, title=title)
    if duplicate:
        if args.stage_id and args.candidate_id:
            mark_search_candidate(root, args.stage_id, args.candidate_id, status="duplicate", record_id=str(duplicate["id"]))
        print(f"[ok] duplicate detected: {duplicate['id']}")
        return 0

    record = default_record(args.kind, title=title, maturity=args.maturity, source={"original_uri": source})
    source_info = backup_source(root, args.kind, record["id"], source)
    record["source"] = source_info
    record["status"] = "active"
    record["summary"] = f"Lightweight {args.kind} intake for `{title}`."
    explicit_topics = list(staged_candidate.get("topics", []) if staged_candidate else [])
    explicit_tags = list(staged_candidate.get("tags", []) if staged_candidate else [])
    if args.kind == "paper":
        explicit_topics.extend(str(item) for item in paper_metadata.get("topics", []) if str(item).strip())
        explicit_tags.extend(str(item) for item in paper_metadata.get("tags", []) if str(item).strip())
    record = apply_record_governance(
        root,
        record,
        explicit_topics=explicit_topics,
        explicit_tags=explicit_tags,
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
        canonical_arxiv_id = str(paper_metadata.get("arxiv_id") or parse_arxiv_id(source) or "").split("v", 1)[0]
        record["payload"]["basic_info"]["title"] = title
        record["payload"]["basic_info"]["authors"] = list(paper_metadata.get("authors", []))
        record["payload"]["basic_info"]["year"] = str(paper_metadata.get("year") or "")
        record["payload"]["basic_info"]["source_url"] = canonical_paper_source_url(source, paper_metadata)
        record["payload"]["basic_info"]["abstract"] = str(paper_metadata.get("abstract") or "")
        record["payload"]["basic_info"]["arxiv_id"] = canonical_arxiv_id
        record["payload"]["basic_info"]["doi"] = str(paper_metadata.get("doi") or "")
    elif args.kind == "repo":
        record["payload"]["basic_info"]["name"] = title
        record["payload"]["basic_info"]["url"] = source if source.startswith("http") else ""
    else:
        record["payload"]["basic_info"]["title"] = title
        record["payload"]["basic_info"]["url"] = source if source.startswith("http") else ""
    path = write_record(root, record)
    auto_outputs: list[str] = []
    paper_preferences = load_runtime_preferences(root).get("paper", {}) if args.kind == "paper" else {}
    note_created = False
    has_pdf = bool(paper_metadata) or source.lower().endswith(".pdf")
    if args.kind == "paper":
        if bool(paper_preferences.get("parse_cache_prewarm_on_intake", True)) and not bool(
            paper_preferences.get("auto_screen_on_intake", True)
        ):
            auto_outputs.extend(run_paper_command(root, "prewarm-cache", "--paper-id", record["id"], "--defer-post-actions"))
        should_screen = bool(paper_preferences.get("auto_screen_on_intake", True)) or args.maturity == "complete"
        if should_screen:
            auto_outputs.extend(run_paper_command(root, "screen", "--paper-id", record["id"], "--mode", "auto", "--defer-post-actions"))
        if args.maturity == "complete":
            note_created = True
            auto_outputs.extend(
                run_paper_command(root, "complete-note", "--paper-id", record["id"], "--mode", "auto", "--defer-post-actions")
            )
        elif should_screen:
            refreshed_record, _ = locate_record(root, record["id"])
            if should_auto_complete_note(refreshed_record, paper_preferences):
                note_created = True
                auto_outputs.extend(
                    run_paper_command(root, "complete-note", "--paper-id", record["id"], "--mode", "auto", "--defer-post-actions")
                )
        if note_created and bool(paper_preferences.get("auto_extract_figures_after_note")):
            auto_outputs.extend(run_paper_command(root, "extract-figures", "--paper-id", record["id"], "--defer-post-actions"))
        if note_created and bool(paper_preferences.get("auto_refresh_structure_after_note", True)):
            auto_outputs.extend(run_paper_command(root, "refresh-structure", "--paper-id", record["id"], "--defer-post-actions"))
    build_index(root)
    if args.stage_id and args.candidate_id:
        mark_search_candidate(root, args.stage_id, args.candidate_id, status="materialized", record_id=str(record["id"]))
    print(f"[ok] created {path.relative_to(root)}")
    print(f"confirm: {confirm_command(record)}")
    for line in auto_outputs:
        print(f"[auto] {line}")
    checkpoint = checkpoint_and_report(root, trigger="milestone", message=f"milestone: intake {args.kind} {record['id']}")
    for hint in guidance_hints(paper_preferences, has_pdf=has_pdf, note_created=note_created):
        print(f"[hint] {hint}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
