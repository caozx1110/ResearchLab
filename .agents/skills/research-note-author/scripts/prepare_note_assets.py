#!/usr/bin/env python3
"""Prepare close-reading note assets for canonical literature and repos."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

for candidate in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
    lib_root = candidate / ".agents" / "lib"
    if (lib_root / "research_v11" / "common.py").exists():
        sys.path.insert(0, str(lib_root))
        break

from research_v11.common import (
    bootstrap_workspace,
    clean_text,
    ensure_research_runtime,
    extract_pdf_context_pages,
    find_project_root,
    load_legacy_repo_facts,
    load_yaml,
    read_text_excerpt,
    research_root,
    write_text_if_changed,
)


SKILL_ROOT = Path(__file__).resolve().parent.parent
LITERATURE_TEMPLATE_PATH = SKILL_ROOT / "assets" / "literature-note-template.md"
REPO_TEMPLATE_PATH = SKILL_ROOT / "assets" / "repo-note-template.md"
LITERATURE_NOTE_MARKER = "<!-- literature-note-scaffold -->"
REPO_NOTE_MARKER = "<!-- repo-note-scaffold -->"
LITERATURE_MANUAL_HEADERS = ("## Working Notes", "## Manual Notes")
REPO_MANUAL_HEADERS = ("## Working Notes", "## Manual Notes")


def _render_template(path: Path, context: dict[str, str]) -> str:
    note = path.read_text(encoding="utf-8")
    for key, value in context.items():
        note = note.replace(f"{{{{{key}}}}}", value)
    return note.rstrip() + "\n"


def _format_inline_values(values: list[str]) -> str:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return "n/a"
    return ", ".join(f"`{value}`" for value in cleaned)


def _render_bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _normalize_extracted_abstract(text: str) -> str:
    text = str(text or "").replace("\u00ad", "")
    match = re.search(r"(?i)\babstract\b\s*[:\-\u2013\u2014 ]*", text)
    if match and match.start() <= 600:
        text = text[match.end() :]
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    return clean_text(text)


def _is_noisy_abstract(text: str) -> bool:
    cleaned = clean_text(text)
    if not cleaned:
        return True
    if len(re.findall(r"/C\d{1,3}", cleaned)) >= 5:
        return True
    if sum(ch.isalpha() for ch in cleaned) < 40:
        return True
    return False


def _clean_capture_excerpt(entry_root: Path, limit: int = 8000) -> str:
    capture_path = entry_root / "source" / "capture.md"
    if not capture_path.exists():
        return ""
    text = capture_path.read_text(encoding="utf-8", errors="ignore")[:limit]
    text = re.sub(r"(?s)^# Capture\s+", "", text)
    text = re.sub(r"- URL: .*?\n", "", text)
    text = re.sub(r"- Captured At: .*?\n", "", text)
    return clean_text(text)


def _literature_working_notes(note_path: Path) -> str:
    default_block = (
        "## Working Notes\n\n"
        "- Replace the placeholder sections above after reading the primary source and any optional helper context you generated.\n"
        "- Keep concrete page/section evidence here if you want a quick audit trail for later review.\n"
    )
    if note_path.exists():
        existing = note_path.read_text(encoding="utf-8")
        for header in LITERATURE_MANUAL_HEADERS:
            start = existing.find(header)
            if start >= 0:
                preserved = existing[start:].strip()
                legacy_default = (
                    "## Working Notes\n\n"
                    "- Manual follow-up: verify motivation, method details, results, caveats, and future-work guesses against the full paper."
                )
                if preserved and preserved != legacy_default:
                    return preserved
    return default_block


def _repo_working_notes(note_path: Path) -> str:
    default_block = (
        "## Working Notes\n\n"
        "- Replace the placeholder sections above after reading the README, the main entrypoints, and any optional helper context you generated.\n"
        "- Keep any concrete file-level evidence or open architecture questions here for future reuse.\n"
    )
    if note_path.exists():
        existing = note_path.read_text(encoding="utf-8")
        for header in REPO_MANUAL_HEADERS:
            start = existing.find(header)
            if start >= 0:
                preserved = existing[start:].strip()
                legacy_default = (
                    "## Working Notes\n\n"
                    "- Manual follow-up: verify architecture, runnable workflows, strengths, risks, and extension points against the real source tree."
                )
                if preserved and preserved != legacy_default:
                    return preserved
    return default_block


def _is_generated_note(text: str, marker: str, legacy_phrase: str) -> bool:
    normalized = str(text or "")
    return marker in normalized or legacy_phrase in normalized


def _pdf_context_block(entry_root: Path) -> str:
    pdf_path = entry_root / "source" / "primary.pdf"
    if not pdf_path.exists():
        return "## PDF Excerpts\n\nNo primary PDF is available for this source.\n"
    payload = extract_pdf_context_pages(pdf_path, front_limit=8, back_limit=4, per_page_char_limit=3200)
    lines = [
        "## PDF Excerpts",
        "",
        "- Primary PDF: `source/primary.pdf`",
        f"- Total pages detected: `{payload.get('total_pages') or 'unknown'}`",
        f"- Included pages: `{', '.join(str(item.get('page')) for item in payload.get('pages', [])) or 'none'}`",
    ]
    for item in payload.get("pages", []):
        text = clean_text(str(item.get("text") or ""))
        if not text:
            continue
        lines.extend(["", f"### Page {item['page']}", "", text])
    return "\n".join(lines).rstrip() + "\n"


def build_literature_context(entry_root: Path, metadata: dict[str, Any]) -> str:
    source_id = str(metadata.get("id") or entry_root.name)
    abstract = _normalize_extracted_abstract(str(metadata.get("abstract") or ""))
    if _is_noisy_abstract(abstract):
        abstract = ""
    capture_excerpt = _clean_capture_excerpt(entry_root)
    authors = [str(author).strip() for author in metadata.get("authors", []) if str(author).strip()]
    lines = [
        f"# Close-Reading Context: {metadata.get('canonical_title') or source_id}",
        "",
        f"- Source ID: `{source_id}`",
        "- Note target: `note.md`",
        "- Helper context: `note-context.md`",
        f"- Source kind: `{metadata.get('source_kind') or 'paper'}`",
    ]
    if authors:
        lines.append(f"- Authors: {', '.join(authors)}")
    if metadata.get("year"):
        lines.append(f"- Year: `{metadata['year']}`")
    if metadata.get("canonical_url"):
        lines.append(f"- Canonical URL: {metadata['canonical_url']}")
    lines.extend(
        [
            "",
            "## Writing Targets",
            "",
            "- Summarize the motivation, novelty, method, experiments, limitations, and future work in your own words.",
            "- Prefer evidence grounded in the PDF body over abstract-only wording when the PDF is available.",
            "- Label reviewer inference clearly when it goes beyond the paper's explicit claims.",
            "",
            "## Abstract",
            "",
            abstract or "No clean abstract was extracted; rely on the PDF excerpts and capture text below.",
            "",
        ]
    )
    if capture_excerpt:
        lines.extend(["## Landing / Capture Excerpt", "", capture_excerpt, ""])
    lines.append(_pdf_context_block(entry_root).rstrip())
    return "\n".join(lines).rstrip() + "\n"


def build_literature_scaffold(entry_root: Path, metadata: dict[str, Any], *, with_context: bool = False) -> str:
    source_id = str(metadata.get("id") or entry_root.name)
    authors = [str(author).strip() for author in metadata.get("authors", []) if str(author).strip()]
    abstract = _normalize_extracted_abstract(str(metadata.get("abstract") or ""))
    if _is_noisy_abstract(abstract):
        abstract = _clean_capture_excerpt(entry_root, limit=5000) or "Abstract extraction looks noisy for this source. Inspect the PDF or landing page directly."
    retrieval_lines = [
        f"- Search tags: {_format_inline_values(metadata.get('tags', []))}",
        f"- Search topics: {_format_inline_values(metadata.get('topics', []))}",
    ]
    if authors:
        retrieval_lines.append(f"- Author cue: `{authors[0]}`")
    if metadata.get("year"):
        retrieval_lines.append(f"- Time cue: `{metadata['year']}`")
    source_reading_coverage = [
        f"- Primary PDF: {'`source/primary.pdf`' if (entry_root / 'source' / 'primary.pdf').exists() else 'not available'}",
        f"- Landing capture: {'`source/capture.md`' if (entry_root / 'source' / 'capture.md').exists() else 'not available'}",
        f"- Helper digest: {'`note-context.md`' if with_context else 'optional; generate with `--with-context` when needed'}",
        "- Read the abstract, introduction/problem framing, method section, experiments/results, and conclusion/limitations before finalizing the note.",
    ]
    context = {
        "note_marker": LITERATURE_NOTE_MARKER,
        "title": str(metadata.get("canonical_title") or source_id),
        "source_id": source_id,
        "source_kind": str(metadata.get("source_kind") or "paper"),
        "year": str(metadata.get("year") or "unknown"),
        "authors": ", ".join(authors) if authors else "n/a",
        "canonical_url": str(metadata.get("canonical_url") or "n/a"),
        "tags": _format_inline_values(metadata.get("tags", [])),
        "topics": _format_inline_values(metadata.get("topics", [])),
        "source_reading_coverage": "\n".join(source_reading_coverage),
        "executive_summary": _render_bullets(
            [
                "Replace with a 4-8 sentence professional summary after close reading.",
                "Cover the problem setting, main idea, and strongest empirical or conceptual takeaway.",
            ]
        ),
        "motivation": _render_bullets(
            [
                "Explain what gap or constraint in prior work motivates this paper.",
                "Note the assumptions that matter for later reuse.",
            ]
        ),
        "innovations": _render_bullets(
            [
                "List the paper's concrete contributions in your own words.",
                "Separate core novelty from supporting engineering choices.",
            ]
        ),
        "method_overview": _render_bullets(
            [
                "Describe the full method stack, including representation, model/policy, training recipe, and inference/control loop.",
                "Highlight the modules that matter most for downstream reuse.",
            ]
        ),
        "results_summary": _render_bullets(
            [
                "Summarize the main experiments, benchmarks, and headline metrics.",
                "Call out which ablations or baselines actually support the paper's central claim.",
            ]
        ),
        "limitations": _render_bullets(
            [
                "Record author-stated limitations first.",
                "Then add your own caveats if needed, clearly labeled as reviewer inference.",
            ]
        ),
        "future_work": _render_bullets(
            [
                "Note future work explicitly named in the paper when available.",
                "Add realistic next experiments or extensions relevant to this workspace.",
            ]
        ),
        "retrieval_cues": "\n".join(retrieval_lines),
        "abstract": abstract or "No abstract extracted yet.",
        "working_notes_block": _literature_working_notes(entry_root / "note.md"),
    }
    return _render_template(LITERATURE_TEMPLATE_PATH, context)


def _clean_repo_context(text: str) -> str:
    text = str(text or "").replace("\r", "")
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            cleaned_lines.append("")
            continue
        if line.startswith("#") or line.startswith("![") or line.startswith("<img") or line.startswith(">"):
            continue
        line = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"<[^>]+>", " ", line)
        line = re.sub(r"https?://\S+", " ", line)
        line = re.sub(r"`([^`]*)`", r"\1", line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        if re.fullmatch(r"[-*_=\s]+", line):
            continue
        cleaned_lines.append(clean_text(line))
    return "\n".join(cleaned_lines).strip()


def _categorize_entrypoints(facts: dict[str, Any]) -> dict[str, list[str]]:
    categories = {"train": [], "eval": [], "deploy": [], "data": [], "other": []}
    for item in facts.get("entrypoints", []):
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        if not path:
            continue
        lowered = path.lower()
        if any(token in lowered for token in ("train", "finetune", "fit")):
            categories["train"].append(path)
        elif any(token in lowered for token in ("eval", "benchmark", "rollout", "test")):
            categories["eval"].append(path)
        elif any(token in lowered for token in ("deploy", "serve", "server", "real", "onnx", "tensorrt", "export")):
            categories["deploy"].append(path)
        elif any(token in lowered for token in ("data", "convert", "dataset", "record", "collect", "prepare")):
            categories["data"].append(path)
        else:
            categories["other"].append(path)
    return categories


def _select_repo_context_files(source_root: Path, facts: dict[str, Any]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()

    def add(rel_path: str) -> None:
        rel = str(rel_path or "").strip()
        if not rel or rel in seen or not (source_root / rel).exists():
            return
        seen.add(rel)
        selected.append(rel)

    readme = next(iter(sorted(source_root.glob("README*"))), None)
    if readme:
        add(readme.relative_to(source_root).as_posix())

    categorized = _categorize_entrypoints(facts)
    for bucket, limit in (("train", 2), ("eval", 1), ("deploy", 1), ("data", 1), ("other", 2)):
        for rel_path in categorized[bucket][:limit]:
            add(rel_path)
    return selected[:8]


def _context_language(path: Path) -> str:
    return {
        ".py": "python",
        ".sh": "bash",
        ".zsh": "bash",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".json": "json",
        ".md": "markdown",
    }.get(path.suffix.lower(), "")


def build_repo_context(entry_root: Path, summary: dict[str, Any], facts: dict[str, Any]) -> str:
    repo_id = str(summary.get("repo_id") or entry_root.name)
    source_root = entry_root / "source"
    readme = next(iter(sorted(source_root.glob("README*"))), None)
    readme_excerpt = _clean_repo_context(read_text_excerpt(readme, limit=12000) if readme else "")
    selected_files = _select_repo_context_files(source_root, facts)
    lines = [
        f"# Close-Reading Context: {summary.get('repo_name') or repo_id}",
        "",
        f"- Repo ID: `{repo_id}`",
        "- Note target: `repo-notes.md`",
        "- Helper context: `repo-note-context.md`",
        f"- Canonical remote: {summary.get('canonical_remote') or 'n/a'}",
        f"- Primary language: `{summary.get('primary_language') or facts.get('primary_language') or 'unknown'}`",
        f"- Repo type: `{summary.get('repo_type') or facts.get('repo_type_hint') or 'unknown'}`",
        "",
        "## Writing Targets",
        "",
        "- Read the README plus representative train/eval/deploy entrypoints before rewriting `repo-notes.md`.",
        "- Focus on what the repo is for, how the main workflow is structured, what is reusable, and what is risky or ambiguous.",
        "- Keep claims grounded in the README, visible entrypoints, and the files excerpted below.",
        "",
        "## Snapshot Cues",
        "",
        f"- Frameworks: {_format_inline_values(summary.get('frameworks', []))}",
        f"- Key dirs: {_format_inline_values(facts.get('key_dirs', []))}",
        f"- Config roots: {_format_inline_values(facts.get('config_roots', []))}",
        f"- Docs dirs: {_format_inline_values(facts.get('docs_dirs', []))}",
        f"- Test dirs: {_format_inline_values(facts.get('test_dirs', []))}",
    ]
    if readme_excerpt:
        lines.extend(["", "## README Excerpt", "", readme_excerpt[:10000]])
    if selected_files:
        lines.extend(["", "## Selected File Excerpts", ""])
        for rel_path in selected_files:
            path = source_root / rel_path
            excerpt = read_text_excerpt(path, limit=2800).rstrip()
            if not excerpt:
                continue
            lines.extend([f"### `{rel_path}`", "", f"```{_context_language(path)}".rstrip(), excerpt, "```", ""])
    return "\n".join(lines).rstrip() + "\n"


def build_repo_scaffold(entry_root: Path, summary: dict[str, Any], facts: dict[str, Any], *, with_context: bool = False) -> str:
    repo_id = str(summary.get("repo_id") or entry_root.name)
    source_root = entry_root / "source"
    selected_files = _select_repo_context_files(source_root, facts)
    entrypoint_lines = []
    for item in facts.get("entrypoints", [])[:5]:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path") or "").strip()
        kind = str(item.get("kind") or "").strip()
        if path:
            entrypoint_lines.append(f"- `{path}` ({kind or 'entrypoint'})")
    if not entrypoint_lines:
        entrypoint_lines = ["- None detected"]
    structure_lines = [
        f"- Key dirs: {_format_inline_values(facts.get('key_dirs', []))}",
        f"- Config roots: {_format_inline_values(facts.get('config_roots', []))}",
        f"- Docs dirs: {_format_inline_values(facts.get('docs_dirs', []))}",
        f"- Test dirs: {_format_inline_values(facts.get('test_dirs', []))}",
    ]
    retrieval_lines = [
        f"- Search tags: {_format_inline_values(summary.get('tags', []))}",
        f"- Search topics: {_format_inline_values(summary.get('topics', []))}",
        f"- Framework hints: {_format_inline_values(summary.get('frameworks', []))}",
        f"- Repo type: `{summary.get('repo_type') or facts.get('repo_type_hint') or 'unknown'}`",
        f"- Owner/name: `{summary.get('owner_name') or summary.get('repo_name') or repo_id}`",
    ]
    reading_lines = [
        f"- README: {'available' if next(iter(sorted(source_root.glob('README*'))), None) else 'missing'}",
        f"- Helper digest: {'`repo-note-context.md`' if with_context else 'optional; generate with `--with-context` when needed'}",
        f"- Suggested files to inspect next: {_format_inline_values(selected_files)}",
        "- Read at least one train/eval/deploy entrypoint if the repo exposes them before finalizing the note.",
    ]
    context = {
        "note_marker": REPO_NOTE_MARKER,
        "repo_name": str(summary.get("repo_name") or repo_id),
        "repo_id": repo_id,
        "canonical_remote": str(summary.get("canonical_remote") or "n/a"),
        "import_type": str(summary.get("import_type") or "unknown"),
        "primary_language": str(summary.get("primary_language") or facts.get("primary_language") or "unknown"),
        "repo_type": str(summary.get("repo_type") or facts.get("repo_type_hint") or "unknown"),
        "frameworks": _format_inline_values(summary.get("frameworks", [])),
        "tags": _format_inline_values(summary.get("tags", [])),
        "topics": _format_inline_values(summary.get("topics", [])),
        "head_commit": str(summary.get("head_commit") or "n/a"),
        "source_reading_coverage": "\n".join(reading_lines),
        "executive_summary": _render_bullets(
            [
                "Replace with a short professional summary after reading the README and representative source files.",
                "State the repo's scope, main workflow, and how reusable it looks for this workspace.",
            ]
        ),
        "goal_scope": _render_bullets(
            [
                "Describe what problem the repo solves and what deliverables it exposes.",
                "Call out whether it is mainly training code, deployment code, data tooling, or a mixed stack.",
            ]
        ),
        "architecture_analysis": _render_bullets(
            [
                "Summarize the main subsystem boundaries and how responsibilities are split across packages/scripts.",
                "Mention config roots, core modules, and obvious integration seams.",
            ]
        ),
        "workflow_analysis": _render_bullets(
            [
                "Trace the runnable path: how someone trains, evaluates, or deploys with this repo.",
                "Name the most important entrypoints and the handoff between them.",
            ]
        ),
        "strengths": _render_bullets(
            ["Record what makes the repo reusable: documentation, modularity, tests, coverage, or clean interfaces."]
        ),
        "limitations": _render_bullets(
            ["Record what is still risky or ambiguous: missing tests, missing configs, brittle setup, or unclear control flow."]
        ),
        "future_work": _render_bullets(
            [
                "List the next files or extension points worth reading if this repo becomes an implementation base.",
                "Mention missing validation or refactors that would reduce reuse risk.",
            ]
        ),
        "retrieval_cues": "\n".join(retrieval_lines),
        "structure_cues": "\n".join(structure_lines),
        "entrypoints": "\n".join(entrypoint_lines),
        "working_notes_block": _repo_working_notes(entry_root / "repo-notes.md"),
    }
    return _render_template(REPO_TEMPLATE_PATH, context)


def prepare_literature_note(
    project_root: Path,
    source_ids: list[str],
    *,
    rewrite_generated_notes: bool = False,
    with_context: bool = False,
) -> int:
    changed = 0
    literature_root = research_root(project_root) / "library" / "literature"
    for source_id in source_ids:
        entry_root = literature_root / source_id
        metadata_path = entry_root / "metadata.yaml"
        metadata = load_yaml(metadata_path, default={})
        if not isinstance(metadata, dict) or not metadata.get("id"):
            raise SystemExit(f"Invalid literature metadata: {metadata_path}")
        if with_context:
            context_path = entry_root / "note-context.md"
            context_text = build_literature_context(entry_root, metadata)
            before_context = context_path.read_text(encoding="utf-8") if context_path.exists() else ""
            write_text_if_changed(context_path, context_text)
            if context_text != before_context:
                changed += 1
        note_path = entry_root / "note.md"
        should_write = not note_path.exists()
        if not should_write and rewrite_generated_notes:
            existing = note_path.read_text(encoding="utf-8")
            should_write = _is_generated_note(existing, LITERATURE_NOTE_MARKER, "Auto-generated analysis note.")
        if should_write:
            note_text = build_literature_scaffold(entry_root, metadata, with_context=with_context)
            before_note = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
            write_text_if_changed(note_path, note_text)
            if note_text != before_note:
                changed += 1
    return changed


def prepare_repo_note(
    project_root: Path,
    repo_ids: list[str],
    *,
    rewrite_generated_notes: bool = False,
    with_context: bool = False,
) -> int:
    changed = 0
    repo_root = research_root(project_root) / "library" / "repos"
    for repo_id in repo_ids:
        entry_root = repo_root / repo_id
        summary_path = entry_root / "summary.yaml"
        summary = load_yaml(summary_path, default={})
        if not isinstance(summary, dict) or not summary.get("repo_id"):
            raise SystemExit(f"Invalid repo summary: {summary_path}")
        facts = load_legacy_repo_facts(project_root, entry_root / "source")
        if with_context:
            context_path = entry_root / "repo-note-context.md"
            context_text = build_repo_context(entry_root, summary, facts)
            before_context = context_path.read_text(encoding="utf-8") if context_path.exists() else ""
            write_text_if_changed(context_path, context_text)
            if context_text != before_context:
                changed += 1
        note_path = entry_root / "repo-notes.md"
        should_write = not note_path.exists()
        if not should_write and rewrite_generated_notes:
            existing = note_path.read_text(encoding="utf-8")
            should_write = _is_generated_note(existing, REPO_NOTE_MARKER, "Auto-generated repo analysis note.")
        if should_write:
            note_text = build_repo_scaffold(entry_root, summary, facts, with_context=with_context)
            before_note = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
            write_text_if_changed(note_path, note_text)
            if note_text != before_note:
                changed += 1
    return changed


def prepare_literature_note_cmd(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    changed = prepare_literature_note(
        project_root,
        list(args.source_id),
        rewrite_generated_notes=args.rewrite_generated_notes,
        with_context=args.with_context,
    )
    print(f"[ok] prepared literature note assets ({changed} file updates)")
    return 0


def prepare_repo_note_cmd(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    changed = prepare_repo_note(
        project_root,
        list(args.repo_id),
        rewrite_generated_notes=args.rewrite_generated_notes,
        with_context=args.with_context,
    )
    print(f"[ok] prepared repo note assets ({changed} file updates)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Prepare close-reading note assets for canonical research entries.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    paper_cmd = subparsers.add_parser("prepare-literature-note", help="Prepare a scaffold note for literature entries, with optional note-context.md")
    paper_cmd.add_argument("--source-id", action="append", required=True, help="Canonical literature source ID")
    paper_cmd.add_argument("--rewrite-generated-notes", action="store_true", help="Rewrite note.md only if it still looks generated")
    paper_cmd.add_argument("--with-context", action="store_true", help="Also generate note-context.md for reuse or audit")
    paper_cmd.set_defaults(func=prepare_literature_note_cmd)

    repo_cmd = subparsers.add_parser("prepare-repo-note", help="Prepare a scaffold note for repo entries, with optional repo-note-context.md")
    repo_cmd.add_argument("--repo-id", action="append", required=True, help="Canonical repo ID")
    repo_cmd.add_argument("--rewrite-generated-notes", action="store_true", help="Rewrite repo-notes.md only if it still looks generated")
    repo_cmd.add_argument("--with-context", action="store_true", help="Also generate repo-note-context.md for reuse or audit")
    repo_cmd.set_defaults(func=prepare_repo_note_cmd)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    project_root = find_project_root()
    require_pdf = args.command == "prepare-literature-note"
    ensure_research_runtime(project_root, "research-note-author", require_pdf_backend=require_pdf)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
