#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

try:
    import tiktoken
except ImportError as exc:  # pragma: no cover - dependency failure is a CLI diagnostic
    raise SystemExit(
        "Rule token check requires the pinned dev dependencies from requirements-dev.txt."
    ) from exc


ENCODING_NAME = "cl100k_base"
DEFAULT_LIMIT = 8000
GLOBAL_RULE_FILES = (Path("runtime/AGENTS.md"), Path("runtime/AGENT_GUIDE.md"))


def discover_skill_files(project_root: Path) -> list[Path]:
    skills_root = project_root / "skills"
    return sorted(
        (path for path in skills_root.glob("*/SKILL.md") if path.is_file()),
        key=lambda path: path.parent.name,
    )


def token_count(path: Path, encoding: Any) -> int:
    return len(encoding.encode(path.read_text(encoding="utf-8")))


def measure_rule_bundles(project_root: Path, *, limit: int = DEFAULT_LIMIT) -> dict[str, Any]:
    if limit < 1:
        raise ValueError("token limit must be positive")
    encoding = tiktoken.get_encoding(ENCODING_NAME)
    globals_absolute = [project_root / path for path in GLOBAL_RULE_FILES]
    missing = [path for path in globals_absolute if not path.is_file()]
    if missing:
        raise SystemExit("Rule token check is missing a required global rule file.")
    global_counts = {
        path.relative_to(project_root).as_posix(): token_count(path, encoding)
        for path in globals_absolute
    }
    rows: list[dict[str, Any]] = []
    for skill_path in discover_skill_files(project_root):
        skill_count = token_count(skill_path, encoding)
        total = sum(global_counts.values()) + skill_count
        rows.append(
            {
                "skill": skill_path.parent.name,
                "skill_file": skill_path.relative_to(project_root).as_posix(),
                "skill_tokens": skill_count,
                "total_tokens": total,
                "within_limit": total <= limit,
            }
        )
    if not rows:
        raise SystemExit("Rule token check found no discoverable skills.")
    worst = max(rows, key=lambda row: (int(row["total_tokens"]), str(row["skill"])))
    return {
        "schema": "workspace-rule-token-budget/v1",
        "encoding": ENCODING_NAME,
        "limit": limit,
        "global_files": global_counts,
        "discoverable_skill_count": len(rows),
        "worst_skill": worst["skill"],
        "worst_total_tokens": worst["total_tokens"],
        "passed": all(bool(row["within_limit"]) for row in rows),
        "bundles": rows,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Check AGENTS.md + AGENT_GUIDE.md + one discoverable SKILL.md against a fixed token budget."
    )
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--json", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    payload = measure_rule_bundles(Path(args.root).resolve(), limit=args.limit)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        for path, count in payload["global_files"].items():
            print(f"{path}: {count}")
        for row in payload["bundles"]:
            state = "ok" if row["within_limit"] else "over"
            print(f"{row['skill']}: {row['total_tokens']} ({state})")
        print(
            f"worst={payload['worst_skill']} total={payload['worst_total_tokens']} "
            f"limit={payload['limit']} encoding={payload['encoding']}"
        )
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
