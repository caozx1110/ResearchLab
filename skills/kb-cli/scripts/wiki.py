#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import subprocess
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

from research.common import add_project_root_argument, ensure_dir, print_resolved_project_roots, resolve_skill_script_path, simple_slug, write_text_if_changed
from research.intake_cli import add_intake_add_arguments, intake_add_argv
from research.core import audit_workspace, lint_records, project_root, search_records, synthesis_root
from research.journal import mutation_transaction


def research_python() -> str:
    return os.environ.get("RESEARCH_PYTHON") or sys.executable or "python3"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Private kb-cli wiki helper for core.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    query = subparsers.add_parser("query")
    query.add_argument("--question", required=True)
    add = subparsers.add_parser("add")
    add_intake_add_arguments(add, source_required=True)
    subparsers.add_parser("lint")
    subparsers.add_parser("audit")
    return parser


def run_intake_add(root: Path, args: argparse.Namespace) -> int:
    cmd = [
        research_python(),
        str(resolve_skill_script_path(".agents/skills/source-intake/scripts/intake.py")),
        "--root",
        str(root),
        *intake_add_argv(args),
    ]
    return subprocess.run(cmd, cwd=root, check=False).returncode


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    if args.command != "audit":
        print_resolved_project_roots(root)
    if args.command == "audit":
        report = audit_workspace(root)
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
        return 1 if report["status"] == "FAIL" else 0
    if args.command == "lint":
        status, issues = lint_records(root)
        print(f"status: {status}")
        for issue in issues:
            print(f"- {issue}")
        return 0 if status == "PASS" else 1
    if args.command == "add":
        return run_intake_add(root, args)
    results = search_records(root, args.question)
    out_root = synthesis_root(root) / "wiki"
    slug = simple_slug(args.question, "query")
    path = out_root / f"{slug}.md"
    lines = [f"# Wiki Query: {args.question}", "", "## Results", ""]
    for item in results[:20]:
        lines.append(f"- `{item['id']}` · {item['kind']} · {item['title']} · {item.get('summary', '')}")
    if len(lines) == 4:
        lines.append("- 暂无匹配结果")
    with mutation_transaction(root, "wiki-query-note", [path]):
        ensure_dir(out_root)
        write_text_if_changed(path, "\n".join(lines).strip() + "\n")
    print(path.relative_to(root))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
