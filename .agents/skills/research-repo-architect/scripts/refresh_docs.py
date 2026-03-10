#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path
from _doc_utils import (
    default_doc_root,
    dump_yaml_text,
    list_from_summary_or_seed,
    load_facts,
    load_summary,
    merge_summary,
    relative_to_root,
    resolve_repo_paths,
    seed_summary,
)


def write_generated_index(doc_root: Path, repo_names: list[str]) -> Path:
    rows = []
    framework_intersection: set[str] | None = None
    for repo_name in repo_names:
        summary = load_summary(doc_root / repo_name / "summary.yaml")
        facts = load_facts(doc_root / repo_name)
        seeded = seed_summary(facts)
        frameworks = list_from_summary_or_seed(summary, seeded, "frameworks")
        entrypoints = list_from_summary_or_seed(summary, seeded, "entrypoints")
        purpose = summary.get("purpose") or ""
        notes = summary.get("repo_type") or facts.get("repo_type_hint", "")
        framework_intersection = (
            set(frameworks)
            if framework_intersection is None
            else framework_intersection & set(frameworks)
        )
        rows.append(
            f"| `{repo_name}` | {purpose} | {', '.join(frameworks[:4])} | {', '.join(entrypoints[:3])} | {notes} |"
        )

    lines = [
        "# Generated Index",
        "",
        "This file is machine-generated from `summary.yaml` and `_scan/facts.json`. Review before copying content into `index.md`.",
        "",
        "## Repository Table",
        "",
        "| Repository | Purpose | Main Stack | Primary Entrypoints | Notes |",
        "| --- | --- | --- | --- | --- |",
        *rows,
        "",
        "## Shared Framework Hints",
        "",
    ]
    if framework_intersection:
        for framework in sorted(framework_intersection):
            lines.append(f"- `{framework}`")
    else:
        lines.append("- None detected")
    lines.append("")

    output_path = doc_root / "index.generated.md"
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh seeded docs from _scan facts without overwriting hand-written narrative notes.")
    parser.add_argument("repo_paths", nargs="+", help="One or more local repository paths")
    parser.add_argument("--doc-root", type=Path, default=None, help="Directory that contains doc/<repo>/")
    parser.add_argument("--sync-derived", action="store_true", help="Overwrite derived summary fields such as repo_type, frameworks, entrypoints, key_modules, and external_dependencies")
    parser.add_argument("--write-generated-index", action="store_true", help="Write doc/index.generated.md from the refreshed summaries")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_paths = resolve_repo_paths(args.repo_paths)
    doc_root = args.doc_root.resolve() if args.doc_root else default_doc_root(repo_paths)

    for repo_path in repo_paths:
        doc_dir = doc_root / repo_path.name
        facts = load_facts(doc_dir)
        seeded = seed_summary(facts)
        scan_seed_path = doc_dir / "_scan" / "summary-seed.yaml"
        scan_seed_path.write_text(dump_yaml_text(seeded), encoding="utf-8")

        summary_path = doc_dir / "summary.yaml"
        existing = load_summary(summary_path)
        merged, changed = merge_summary(existing, seeded, sync_derived=args.sync_derived)
        if changed or not summary_path.exists():
            summary_path.write_text(dump_yaml_text(merged), encoding="utf-8")
            print(f"[ok] refreshed {relative_to_root(summary_path, doc_root)}")
        else:
            print(f"[ok] no summary changes for {repo_path.name}")
        print(f"[ok] wrote {relative_to_root(scan_seed_path, doc_root)}")

    if args.write_generated_index and len(repo_paths) > 1:
        index_path = write_generated_index(doc_root, [path.name for path in repo_paths])
        print(f"[ok] wrote {relative_to_root(index_path, doc_root)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
