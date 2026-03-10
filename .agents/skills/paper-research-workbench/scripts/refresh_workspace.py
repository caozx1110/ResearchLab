#!/usr/bin/env python3
"""Run the full paper workspace refresh pipeline."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


def project_root_from_script() -> Path:
    # <project>/skills/paper-research-workbench/scripts/refresh_workspace.py
    return Path(__file__).resolve().parents[3]


def run_step(command: list[str], project_root: Path) -> None:
    result = subprocess.run(command, cwd=project_root, check=False)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh the paper workspace from raw PDFs to KB outputs.",
    )
    parser.add_argument(
        "--input",
        default="raw",
        help="Input PDF directory or file (default: raw)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force reparsing of already-seen source files",
    )
    parser.add_argument(
        "--paper-id",
        default=None,
        help="Optional paper id to restrict note scaffolding to one paper",
    )
    args = parser.parse_args()

    project_root = project_root_from_script()
    script_root = project_root / "skills" / "paper-research-workbench" / "scripts"
    python_bin = sys.executable

    parse_cmd = [
        python_bin,
        str(script_root / "parse_pdf.py"),
        "--input",
        args.input,
        "--output-root",
        "doc/papers/papers",
        "--registry-path",
        "doc/papers/index/registry.yaml",
    ]
    if args.force:
        parse_cmd.append("--force")
    run_step(parse_cmd, project_root)

    run_step(
        [
            python_bin,
            str(script_root / "build_catalog.py"),
            "--papers-root",
            "doc/papers/papers",
            "--index-root",
            "doc/papers/index",
        ],
        project_root,
    )
    run_step(
        [
            python_bin,
            str(script_root / "build_relationship_graph.py"),
            "--papers-root",
            "doc/papers/papers",
            "--index-root",
            "doc/papers/index",
            "--graph-root",
            "doc/papers/user/graph",
        ],
        project_root,
    )

    scaffold_cmd = [
        python_bin,
        str(script_root / "scaffold_paper_note.py"),
        "--papers-root",
        "doc/papers/papers",
        "--template-root",
        "skills/paper-research-workbench/assets/templates",
        "--user-root",
        "doc/papers/user",
    ]
    if args.paper_id:
        scaffold_cmd.extend(["--paper-id", args.paper_id])
    if args.force:
        scaffold_cmd.append("--force")
    run_step(scaffold_cmd, project_root)

    run_step(
        [
            python_bin,
            str(script_root / "refresh_topic_maps.py"),
            "--topics-index",
            "doc/papers/index/topics.yaml",
            "--papers-root",
            "doc/papers/papers",
            "--output-root",
            "doc/papers/user/topic-maps",
            "--template",
            "skills/paper-research-workbench/assets/templates/topic-map-template.md",
        ],
        project_root,
    )
    run_step(
        [
            python_bin,
            str(script_root / "build_ai_kb.py"),
            "--papers-root",
            "doc/papers/papers",
            "--relationships-path",
            "doc/papers/index/relationships.yaml",
            "--kb-root",
            "doc/papers/ai",
            "--user-root",
            "doc/papers/user",
        ],
        project_root,
    )
    run_step(
        [
            python_bin,
            str(script_root / "build_corpus_ideas.py"),
            "--papers-root",
            "doc/papers/papers",
            "--relationships-path",
            "doc/papers/index/relationships.yaml",
            "--output-root",
            "doc/papers/user/syntheses",
            "--kb-root",
            "doc/papers/ai",
        ],
        project_root,
    )
    run_step(
        [
            python_bin,
            str(script_root / "build_user_hub.py"),
            "--papers-root",
            "doc/papers/papers",
            "--user-root",
            "doc/papers/user",
            "--ai-root",
            "doc/papers/ai",
            "--relationships-path",
            "doc/papers/index/relationships.yaml",
            "--topics-index",
            "doc/papers/index/topics.yaml",
            "--frontier-ideas-path",
            "doc/papers/ai/frontier-ideas.yaml",
        ],
        project_root,
    )
    print("[OK] workspace refresh completed")


if __name__ == "__main__":
    main()
