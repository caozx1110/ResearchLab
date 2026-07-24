#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_PATH = Path(__file__).resolve()
for candidate in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents]:
    lib = candidate / ".agents" / "lib"
    if lib.exists():
        sys.path.insert(0, str(lib))
        PROJECT_ROOT = candidate
        break
else:
    raise SystemExit("Could not locate the managed research runtime.")

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.common import add_project_root_argument, load_yaml
from research.core import project_root
from research.paths import search_stage_path
from research.sources import (
    _validate_search_stage_target,
    build_literature_search_stage_id,
    stage_search_results,
)


MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
ALLOWED_PAYLOAD_KEYS = {
    "request",
    "stage_id",
    "note",
    "mode",
    "run_id",
    "monitor_binding",
    "scope",
    "review_protocol",
    "reviewers",
    "budget",
    "usage",
    "queries",
    "candidates",
    "coverage",
    "frontier",
    "stop",
    "partial",
}
SEARCH_STATE_KEYS = {
    "mode",
    "run_id",
    "monitor_binding",
    "scope",
    "review_protocol",
    "reviewers",
    "budget",
    "usage",
    "queries",
    "coverage",
    "frontier",
    "stop",
    "partial",
}
DEFAULT_EXPLORATORY_BUDGET = {
    "max_queries": 8,
    "max_candidates": 50,
    "max_full_reads": 8,
    "max_citation_hops": 6,
}
EMPTY_USAGE = {
    "queries": 0,
    "candidates_seen": 0,
    "full_reads": 0,
    "citation_hops": 0,
    "retryable_failures": 0,
}


def _load_payload(path: Path) -> dict[str, Any]:
    try:
        stat = path.lstat()
    except OSError:
        raise SystemExit("Literature search staging input could not be read.") from None
    if path.is_symlink() or not path.is_file() or stat.st_size > MAX_PAYLOAD_BYTES:
        raise SystemExit("Literature search staging input must be a bounded regular JSON file.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise SystemExit("Literature search staging input is not valid JSON.") from None
    if not isinstance(payload, dict):
        raise SystemExit("Literature search staging input must be a JSON object.")
    unknown = sorted(set(payload) - ALLOWED_PAYLOAD_KEYS)
    if unknown:
        raise SystemExit("Literature search staging input contains unsupported fields.")
    return payload


def stage_payload(root: Path, payload: dict[str, Any]) -> Path:
    if not isinstance(payload.get("request"), str):
        raise SystemExit("Literature search requires a textual original research question.")
    request = " ".join(payload["request"].split())
    if not request:
        raise SystemExit("Literature search requires an original research question.")
    note = payload.get("note", "")
    if not isinstance(note, str):
        raise SystemExit("Literature search note must be text.")
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        raise SystemExit("Literature search candidates must be a list.")
    explicit_stage_id = payload.get("stage_id", "")
    if not isinstance(explicit_stage_id, str):
        raise SystemExit("Literature search stage_id must be text.")
    if explicit_stage_id and re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", explicit_stage_id
    ) is None:
        raise SystemExit("Literature search stage_id must be an ASCII-safe identifier.")
    run_id = payload.get("run_id", "")
    if not isinstance(run_id, str):
        raise SystemExit("Literature search run_id must be text.")
    mode = payload.get("mode", "exploratory")
    if not isinstance(mode, str):
        raise SystemExit("Literature search mode must be text.")
    scope = payload.get("scope", {})
    if not isinstance(scope, dict):
        raise SystemExit("Literature search scope must be a mapping.")
    current_stage_id = explicit_stage_id or build_literature_search_stage_id(
        request,
        mode=mode,
        scope=scope,
        run_id=run_id,
    )
    current_path = search_stage_path(root, current_stage_id)
    _validate_search_stage_target(root, current_path)
    existing = load_yaml(current_path, default={})
    if (
        explicit_stage_id
        and isinstance(existing, dict)
        and existing.get("id")
        and existing.get("entry_skill") != "literature-search"
    ):
        # A generic/provider-era stage lacks the provenance contract required by
        # literature-search.  Preserve it untouched and start a safe new run.
        current_stage_id = build_literature_search_stage_id(
            request,
            mode=mode,
            scope=scope,
            run_id=run_id,
        )
        current_path = search_stage_path(root, current_stage_id)
        _validate_search_stage_target(root, current_path)
        existing = load_yaml(current_path, default={})
    search_state: dict[str, Any] = {
        "entry_skill": "literature-search",
        **{key: payload[key] for key in SEARCH_STATE_KEYS if key in payload},
    }
    if (
        not isinstance(existing, dict)
        or not existing.get("id")
        or existing.get("entry_skill") != "literature-search"
    ):
        search_state["mode"] = mode or "exploratory"
        search_state["budget"] = {
            **DEFAULT_EXPLORATORY_BUDGET,
            **(search_state.get("budget") if isinstance(search_state.get("budget"), dict) else {}),
        }
        search_state["usage"] = {
            **EMPTY_USAGE,
            **(search_state.get("usage") if isinstance(search_state.get("usage"), dict) else {}),
        }
        search_state.setdefault("stop", {"reason": "in_progress"})
        search_state.setdefault("partial", True)
    else:
        existing_budget = existing.get("budget") if isinstance(existing.get("budget"), dict) else {}
        incoming_budget = search_state.get("budget") if isinstance(search_state.get("budget"), dict) else {}
        search_state["budget"] = {
            **DEFAULT_EXPLORATORY_BUDGET,
            **existing_budget,
            **incoming_budget,
        }
        existing_usage = existing.get("usage") if isinstance(existing.get("usage"), dict) else {}
        incoming_usage = search_state.get("usage") if isinstance(search_state.get("usage"), dict) else {}
        search_state["usage"] = {**EMPTY_USAGE, **existing_usage, **incoming_usage}
        if not existing.get("mode") and "mode" not in search_state:
            search_state["mode"] = "exploratory"
        if "stop" not in existing and "stop" not in search_state:
            search_state["stop"] = {"reason": "in_progress"}
        if "partial" not in existing and "partial" not in search_state:
            search_state["partial"] = True
    return stage_search_results(
        root,
        kind="paper",
        query=request,
        candidates=candidates,
        stage_id=current_stage_id,
        note=note,
        search_state=search_state,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage a provider-neutral literature search stage.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    stage = subparsers.add_parser("stage", help="Validate and stage one Agent-authored search batch")
    stage.add_argument("--input", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    payload = _load_payload(Path(args.input))
    path = stage_payload(root, payload)
    persisted = load_yaml(path, default={})
    candidates = [item for item in persisted.get("candidates", []) if isinstance(item, dict)]
    stop = persisted.get("stop") if isinstance(persisted.get("stop"), dict) else {}
    if stop.get("reason") == "blocked_no_search_tool":
        print("当前没有可用的文献检索工具；已记录阻塞原因，没有把空结果当作成功。")
        return 0
    screening_counts = {"include": 0, "maybe": 0, "exclude": 0, "unassessed": 0}
    multi_reviewer = int((persisted.get("scope") or {}).get("screeners") or 1) > 1
    for candidate in candidates:
        screening_key = "effective_screening" if multi_reviewer else "screening"
        screening = candidate.get(screening_key) if isinstance(candidate.get(screening_key), dict) else {}
        decision = str(screening.get("decision") or "unassessed")
        if decision in screening_counts:
            screening_counts[decision] += 1
    print(
        f"已记录本轮文献检索结果；当前共有 {len(candidates)} 个候选，"
        f"其中初筛建议保留 {screening_counts['include']}、待定 {screening_counts['maybe']}、"
        f"排除 {screening_counts['exclude']}、尚未初筛 {screening_counts['unassessed']}。"
        "这些只是初筛；正式入库前，请先告诉我你要保留哪些候选。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
