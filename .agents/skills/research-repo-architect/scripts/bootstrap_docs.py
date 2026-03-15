#!/usr/bin/env python3
from __future__ import annotations

import argparse
from pathlib import Path

from _doc_utils import (
    default_doc_root,
    dump_yaml_text,
    human_dir,
    load_facts,
    relative_to_root,
    repo_doc_dir,
    resolve_repo_paths,
    seed_summary,
    summary_path,
)


TEMPLATE_MAP = {
    "overview-template.md": "overview.md",
    "architecture-template.md": "architecture.md",
    "workflows-template.md": "workflows.md",
    "research-notes-template.md": "research-notes.md",
    "todo-template.md": "todo.md",
}


def render_template(path: Path, repo_name: str) -> str:
    return path.read_text(encoding="utf-8").replace("<repo-name>", repo_name)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create missing architecture-doc files from scan facts and bundled templates.")
    parser.add_argument("repo_paths", nargs="+", help="One or more local repository paths")
    parser.add_argument("--doc-root", type=Path, default=None, help="Directory that contains doc/repos/<repo>/")
    parser.add_argument("--templates-root", type=Path, default=Path(__file__).resolve().parent.parent / "assets" / "templates", help="Template directory")
    parser.add_argument("--refresh-summary", action="store_true", help="Overwrite agent/summary.yaml from scan facts")
    parser.add_argument("--with-index", action="store_true", help="Create doc/repos/index.md from the index template if it is missing and several repos are passed")
    return parser.parse_args()


def maybe_write(path: Path, content: str, overwrite: bool) -> bool:
    if path.exists() and not overwrite:
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return True


def create_index(doc_root: Path, templates_root: Path, repo_names: list[str]) -> bool:
    index_path = doc_root / "index.md"
    if index_path.exists():
        return False
    template = render_template(templates_root / "index-template.md", "Repository Index")
    rows = "\n".join(f"| `{name}` |  |  |  |  |" for name in repo_names)
    template = template.replace("|  |  |  |  |  |", rows)
    index_path.write_text(template, encoding="utf-8")
    return True


def main() -> int:
    args = parse_args()
    repo_paths = resolve_repo_paths(args.repo_paths)
    doc_root = args.doc_root.resolve() if args.doc_root else default_doc_root(repo_paths)
    templates_root = args.templates_root.resolve()

    for repo_path in repo_paths:
        doc_dir = repo_doc_dir(doc_root, repo_path.name)
        facts = load_facts(doc_dir)
        created = []
        repo_human_dir = human_dir(doc_dir)
        agent_summary_path = summary_path(doc_dir)
        if maybe_write(agent_summary_path, dump_yaml_text(seed_summary(facts)), overwrite=args.refresh_summary):
            created.append(relative_to_root(agent_summary_path, doc_root))
        for template_name, output_name in TEMPLATE_MAP.items():
            output_path = repo_human_dir / output_name
            content = render_template(templates_root / template_name, repo_path.name)
            if maybe_write(output_path, content, overwrite=False):
                created.append(relative_to_root(output_path, doc_root))
        if created:
            print(f"[ok] bootstrapped {repo_path.name}: {', '.join(created)}")
        else:
            print(f"[ok] no changes for {repo_path.name}")

    if args.with_index and len(repo_paths) > 1:
        if create_index(doc_root, templates_root, [path.name for path in repo_paths]):
            print(f"[ok] created {relative_to_root(doc_root / 'index.md', doc_root)}")
    return 0
if __name__ == "__main__":
    raise SystemExit(main())
