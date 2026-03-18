#!/usr/bin/env python3
"""Catalog local and GitHub repositories into doc/research/library/repos."""

from __future__ import annotations

import argparse
import re
import shutil
import subprocess
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
    copytree_filtered,
    ensure_research_runtime,
    find_project_root,
    git_head_commit,
    git_remote_url,
    infer_topics_and_tags,
    is_url,
    load_index,
    load_legacy_repo_facts,
    load_list_document,
    load_yaml,
    make_repo_id,
    normalize_remote_url,
    owner_name_from_remote,
    pending_repo_reviews_path,
    raw_root,
    read_text_excerpt,
    rebuild_repo_index,
    repo_index_path,
    research_root,
    resolved_repo_reviews_path,
    score_fuzzy_repo_match,
    slugify,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
)


def intake_root(project_root: Path) -> Path:
    return research_root(project_root) / "intake" / "repos" / "downloads"


NOTE_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "assets" / "repo-note-template.md"
MANUAL_NOTE_HEADERS = ("## Working Notes", "## Manual Notes")
NOTE_CONTEXT_NAME = "repo-note-context.md"
NOTE_SCAFFOLD_MARKER = "<!-- repo-note-scaffold -->"
LEGACY_AUTO_NOTE_MARKERS = ("Auto-generated repo analysis note.", NOTE_SCAFFOLD_MARKER)
NOTE_AUTHOR_SCRIPT = Path(__file__).resolve().parents[2] / "research-note-author" / "scripts" / "prepare_note_assets.py"


def canonical_repo_root(project_root: Path, repo_id: str) -> Path:
    return research_root(project_root) / "library" / "repos" / repo_id


def unique_repo_id(project_root: Path, base_id: str) -> str:
    payload = load_index(repo_index_path(project_root), "repo-index", "repo-cataloger")
    if base_id not in payload.get("items", {}):
        return base_id
    suffix = 2
    while f"{base_id}-{suffix}" in payload["items"]:
        suffix += 1
    return f"{base_id}-{suffix}"


def _to_manifest_value(candidate: dict[str, Any]) -> dict[str, Any]:
    return {**candidate, "staged_source": str(candidate["staged_source"])}


def _from_manifest_value(candidate: dict[str, Any]) -> dict[str, Any]:
    candidate["staged_source"] = Path(candidate["staged_source"])
    return candidate


def prepare_note_assets_for_repo(repo_id: str, *, rewrite_generated_notes: bool = False) -> None:
    cmd = [sys.executable, str(NOTE_AUTHOR_SCRIPT), "prepare-repo-note", "--repo-id", repo_id]
    if rewrite_generated_notes:
        cmd.append("--rewrite-generated-notes")
    subprocess.run(cmd, check=True)


def _read_repo_context(stage_source: Path) -> str:
    readme = next(iter(sorted(stage_source.glob("README*"))), None)
    return read_text_excerpt(readme) if readme else ""


def _load_note_template() -> str:
    return NOTE_TEMPLATE_PATH.read_text(encoding="utf-8")


def _format_inline_values(values: list[str]) -> str:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return "n/a"
    return ", ".join(f"`{value}`" for value in cleaned)


def _truncate_summary(text: str, max_chars: int = 320) -> str:
    text = clean_text(text)
    if len(text) <= max_chars:
        return text
    trimmed = text[: max_chars - 3].rsplit(" ", 1)[0].rstrip(" ,;:-")
    if not trimmed:
        trimmed = text[: max_chars - 3]
    return f"{trimmed}..."


def _clean_repo_context(text: str) -> str:
    text = str(text or "").replace("\r", "")
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    cleaned_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            cleaned_lines.append("")
            continue
        if line.startswith("#") or line.startswith("![") or line.startswith("<img"):
            continue
        if line.startswith(">"):
            continue
        line = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"<[^>]+>", " ", line)
        line = re.sub(r"https?://\S+", " ", line)
        line = re.sub(r"`([^`]*)`", r"\1", line)
        line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
        line = re.sub(r"[|]{2,}", " ", line)
        if re.fullmatch(r"[-*_=\s]+", line):
            continue
        lowered = line.lower()
        if "primary contact" in lowered or "@" in lowered:
            continue
        cleaned_lines.append(clean_text(line))
    return "\n".join(cleaned_lines).strip()


def _repo_sentences(text: str) -> list[str]:
    cleaned = clean_text(re.sub(r"\s+", " ", text))
    if not cleaned:
        return []
    parts = [clean_text(part) for part in re.split(r"(?<=[.!?])\s+", cleaned) if clean_text(part)]
    return parts or [cleaned]


def _looks_like_repo_meta_sentence(sentence: str) -> bool:
    lowered = clean_text(sentence).lower()
    if not lowered:
        return True
    if any(
        token in lowered
        for token in (
            "primary contact",
            "project website",
            "we welcome discussion",
            "no concrete timeline for open-sourcing",
            "let's go for",
            "continuously updating",
        )
    ):
        return True
    if lowered.startswith("towards ") and len(lowered.split()) <= 12:
        return True
    if lowered.count(",") >= 6:
        return True
    return False


def _informative_repo_sentences(sentences: list[str], repo_name: str) -> list[str]:
    repo_lower = repo_name.lower().strip()
    preferred = [
        sentence
        for sentence in sentences
        if not _looks_like_repo_meta_sentence(sentence)
        and repo_lower
        and repo_lower in sentence.lower()
        and " is " in sentence.lower()
    ]
    if preferred:
        return preferred
    preferred = [
        sentence
        for sentence in sentences
        if not _looks_like_repo_meta_sentence(sentence)
        and any(
            token in sentence.lower()
            for token in (" is ", " are ", " framework", " repository", " codebase", " enables ", " supports ", " provides ")
        )
    ]
    if preferred:
        return preferred
    return [sentence for sentence in sentences if not _looks_like_repo_meta_sentence(sentence)] or sentences


def build_repo_short_summary(candidate: dict[str, Any], facts: dict[str, Any], context: str, *, max_chars: int = 320) -> str:
    repo_name = str(candidate.get("repo_name") or facts.get("repo_name") or "repository")
    cleaned_context = _clean_repo_context(context)
    sentences = _repo_sentences(cleaned_context)
    preferred = _informative_repo_sentences(sentences, repo_name)
    for sentence in preferred + sentences:
        lowered = sentence.lower()
        if len(sentence) < 40:
            continue
        if repo_name.lower() in lowered and len(sentence.split()) <= 6:
            continue
        if _looks_like_repo_meta_sentence(sentence):
            continue
        if not (
            repo_name.lower() in lowered
            or any(token in lowered for token in (" is ", " framework", " repository", " codebase", " enables ", " supports ", " provides "))
        ):
            continue
        return _truncate_summary(sentence, max_chars=max_chars)

    repo_type = str(candidate.get("repo_type") or facts.get("repo_type_hint") or "research codebase").replace("-", " ")
    primary_language = str(candidate.get("primary_language") or facts.get("primary_language") or "unknown language")
    frameworks = [str(item).strip() for item in candidate.get("frameworks", []) or facts.get("framework_hints", []) if str(item).strip()]
    entrypoints = [
        str(item.get("path") or "").strip()
        for item in facts.get("entrypoints", [])
        if isinstance(item, dict) and str(item.get("path") or "").strip()
    ] or [str(item).strip() for item in candidate.get("entrypoints", []) if str(item).strip()]
    key_dirs = [str(item).strip() for item in facts.get("key_dirs", []) if str(item).strip()]

    summary = f"{repo_name} is a {repo_type} repository"
    if primary_language and primary_language != "unknown language":
        summary += f" primarily written in {primary_language}"
    summary += "."
    if frameworks:
        summary += f" Framework hints include {', '.join(frameworks[:2])}."
    elif entrypoints:
        summary += f" Useful entrypoints include {', '.join(entrypoints[:2])}."
    elif key_dirs:
        summary += f" Key directories include {', '.join(key_dirs[:3])}."
    return _truncate_summary(summary, max_chars=max_chars)


def ensure_summary_short_summary(summary: dict[str, Any], facts: dict[str, Any], context: str, *, rewrite: bool = False) -> str:
    existing = clean_text(str(summary.get("short_summary") or ""))
    if existing and not rewrite:
        return existing
    short_summary = build_repo_short_summary(summary, facts, context)
    summary["short_summary"] = short_summary
    return short_summary


def _format_note_list(items: list[str], fallback: str) -> str:
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in items:
        normalized = _truncate_summary(clean_text(item), max_chars=280)
        if normalized and normalized not in seen:
            seen.add(normalized)
            cleaned.append(normalized)
    if not cleaned:
        cleaned = [fallback]
    return "\n".join(f"- {item}" for item in cleaned)


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


def _note_context_path(note_path: Path) -> Path:
    return note_path.parent / NOTE_CONTEXT_NAME


def _is_generated_note_text(text: str) -> bool:
    normalized = str(text or "")
    return any(marker in normalized for marker in LEGACY_AUTO_NOTE_MARKERS)


def _render_bullets(items: list[str]) -> str:
    return "\n".join(f"- {item}" for item in items)


def _context_language(path: Path) -> str:
    suffix = path.suffix.lower()
    return {
        ".py": "python",
        ".sh": "bash",
        ".zsh": "bash",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".toml": "toml",
        ".json": "json",
        ".md": "markdown",
    }.get(suffix, "")


def _select_repo_context_files(source_root: Path, facts: dict[str, Any]) -> list[str]:
    selected: list[str] = []
    seen: set[str] = set()

    def add(rel_path: str) -> None:
        path = str(rel_path or "").strip()
        if not path or path in seen or not (source_root / path).exists():
            return
        seen.add(path)
        selected.append(path)

    readme = next(iter(sorted(source_root.glob("README*"))), None)
    if readme:
        add(readme.relative_to(source_root).as_posix())

    categorized = _categorize_entrypoints(facts)
    for bucket, limit in (("train", 2), ("eval", 1), ("deploy", 1), ("data", 1), ("other", 2)):
        for rel_path in categorized[bucket][:limit]:
            add(rel_path)

    return selected[:8]


def build_repo_note_context(repo_id: str, summary: dict[str, Any], facts: dict[str, Any], context_text: str, *, note_path: Path) -> str:
    source_root = note_path.parent / "source"
    selected_files = _select_repo_context_files(source_root, facts)
    readme_excerpt = _clean_repo_context(context_text or _read_repo_context(source_root))

    lines = [
        f"# Close-Reading Context: {summary.get('repo_name') or repo_id}",
        "",
        f"- Repo ID: `{repo_id}`",
        f"- Note target: `repo-notes.md`",
        f"- Helper context: `{NOTE_CONTEXT_NAME}`",
        f"- Canonical remote: {summary.get('canonical_remote') or 'n/a'}",
        f"- Primary language: `{summary.get('primary_language') or facts.get('primary_language') or 'unknown'}`",
        f"- Repo type: `{summary.get('repo_type') or facts.get('repo_type_hint') or 'unknown'}`",
        "",
        "## Writing Targets",
        "",
        "- Read the README plus representative train/eval/deploy entrypoints before rewriting `repo-notes.md`.",
        "- Focus on what the repo is for, how the main workflow is structured, what is reusable, and what is still risky or ambiguous.",
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
        lines.extend(
            [
                "",
                "## README Excerpt",
                "",
                readme_excerpt[:10000],
            ]
        )

    if selected_files:
        lines.extend(
            [
                "",
                "## Selected File Excerpts",
                "",
            ]
        )
        for rel_path in selected_files:
            path = source_root / rel_path
            excerpt = read_text_excerpt(path, limit=2800).rstrip()
            if not excerpt:
                continue
            lines.extend(
                [
                    f"### `{rel_path}`",
                    "",
                    f"```{_context_language(path)}".rstrip(),
                    excerpt,
                    "```",
                    "",
                ]
            )

    return "\n".join(lines).rstrip() + "\n"


def _working_notes_block(note_path: Path) -> str:
    default_block = (
        "## Working Notes\n\n"
        "- Replace the placeholder sections above after reading `repo-note-context.md`, the README, and the main entrypoints.\n"
        "- Keep any concrete file-level evidence or open architecture questions here for future reuse.\n"
    )
    if note_path.exists():
        existing = note_path.read_text(encoding="utf-8")
        for header in MANUAL_NOTE_HEADERS:
            start = existing.find(header)
            if start >= 0:
                preserved = existing[start:].strip()
                legacy_default = (
                    "## Working Notes\n\n"
                    "- Manual follow-up: verify architecture, runnable workflows, strengths, risks, and extension points against the real source tree."
                )
                if (
                    preserved
                    and preserved != legacy_default
                    and "Pending deeper read: replace this scaffold with concrete architecture findings, risks, and extension points." not in preserved
                ):
                    return preserved
    return default_block


def build_repo_note(repo_id: str, summary: dict[str, Any], facts: dict[str, Any], context_text: str, *, note_path: Path) -> str:
    source_root = note_path.parent / "source"
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
        f"- Helper digest: `{NOTE_CONTEXT_NAME}`",
        f"- Suggested files to inspect next: {_format_inline_values(selected_files)}",
        "- Read at least one train/eval/deploy entrypoint if the repo exposes them before finalizing the note prose.",
    ]

    note = _load_note_template()
    context = {
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
        "note_marker": NOTE_SCAFFOLD_MARKER,
        "source_reading_coverage": "\n".join(reading_lines),
        "executive_summary": _render_bullets(
            [
                "Replace with a short close-reading summary after reading the README and representative source files.",
                "State the repo's scope, the main workflow it supports, and how reusable it looks for this workspace.",
            ]
        ),
        "goal_scope": _render_bullets(
            [
                "Describe what problem the repo tries to solve and what deliverables it exposes.",
                "Call out whether it is mostly training code, deployment code, data tooling, or a mixed stack.",
            ]
        ),
        "architecture_analysis": _render_bullets(
            [
                "Summarize the main subsystem boundaries and how responsibilities are split across packages/scripts.",
                "Mention config roots, core modules, and any obvious integration seams.",
            ]
        ),
        "workflow_analysis": _render_bullets(
            [
                "Trace the runnable path: how someone trains, evaluates, or deploys with this repo.",
                "Name the most important entrypoints and the handoff between them.",
            ]
        ),
        "strengths": _render_bullets(
            [
                "Record what makes the repo reusable: coverage, documentation, modularity, testing, or clean interfaces.",
            ]
        ),
        "limitations": _render_bullets(
            [
                "Record what is still risky or ambiguous: missing tests, missing configs, partial release, brittle setup, or unclear control flow.",
            ]
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
        "working_notes_block": _working_notes_block(note_path),
    }
    for key, value in context.items():
        note = note.replace(f"{{{{{key}}}}}", value)
    return note.rstrip() + "\n"


def _write_note_assets(
    repo_id: str,
    summary: dict[str, Any],
    facts: dict[str, Any],
    context_text: str,
    *,
    note_path: Path,
    rewrite_generated_note: bool = False,
) -> int:
    changed = 0
    context_path = _note_context_path(note_path)
    context_payload = build_repo_note_context(repo_id, summary, facts, context_text, note_path=note_path)
    before_context = context_path.read_text(encoding="utf-8") if context_path.exists() else ""
    write_text_if_changed(context_path, context_payload)
    if context_payload != before_context:
        changed += 1

    should_write_note = not note_path.exists()
    if not should_write_note and rewrite_generated_note:
        existing = note_path.read_text(encoding="utf-8")
        should_write_note = _is_generated_note_text(existing)
    if should_write_note:
        note_payload = build_repo_note(repo_id, summary, facts, context_text, note_path=note_path)
        before_note = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
        write_text_if_changed(note_path, note_payload)
        if note_payload != before_note:
            changed += 1
    return changed


def refresh_repo_notes(
    project_root: Path,
    repo_ids: list[str] | None = None,
    *,
    rewrite_summary: bool = False,
    rewrite_generated_notes: bool = False,
) -> int:
    repo_root = research_root(project_root) / "library" / "repos"
    summary_paths = (
        [repo_root / repo_id / "summary.yaml" for repo_id in repo_ids]
        if repo_ids
        else sorted(repo_root.glob("*/summary.yaml"))
    )
    changed = 0
    for summary_path in summary_paths:
        if not summary_path.exists():
            raise SystemExit(f"Missing repo summary: {summary_path}")
        summary = load_yaml(summary_path, default={})
        if not isinstance(summary, dict) or not summary.get("repo_id"):
            raise SystemExit(f"Invalid repo summary: {summary_path}")
        repo_id = str(summary["repo_id"])
        source_root = summary_path.parent / "source"
        facts = load_legacy_repo_facts(project_root, source_root)
        context = _read_repo_context(source_root)
        before_summary = clean_text(str(summary.get("short_summary") or ""))
        short_summary = ensure_summary_short_summary(summary, facts, context, rewrite=rewrite_summary)
        if short_summary != before_summary:
            write_yaml_if_changed(summary_path, summary)
            changed += 1
        note_path = summary_path.parent / "repo-notes.md"
        changed += _write_note_assets(
            repo_id,
            summary,
            facts,
            context,
            note_path=note_path,
            rewrite_generated_note=rewrite_generated_notes,
        )
    rebuild_repo_index(project_root)
    return changed


def stage_repo(project_root: Path, raw_source: str) -> tuple[Path, dict[str, Any]]:
    intake_id = f"repo-intake-{utc_now_iso().replace(':', '-').replace('+00:00', 'z')}-{slugify(raw_source, max_words=4)}"
    stage_dir = intake_root(project_root) / intake_id
    stage_source = stage_dir / "source"
    stage_source.parent.mkdir(parents=True, exist_ok=True)
    import_type = "local-path"
    source_label = raw_source
    canonical_remote = ""
    source_head_commit = ""

    if is_url(raw_source):
        import_type = "github-url"
        subprocess.run(
            ["git", "clone", "--depth", "1", raw_source, str(stage_source)],
            check=True,
        )
        canonical_remote = normalize_remote_url(raw_source)
        explicit_repo_name = Path(canonical_remote.rstrip("/")).name or "repo"
        source_head_commit = git_head_commit(stage_source)
    else:
        local_path = Path(raw_source).resolve()
        canonical_remote = git_remote_url(local_path)
        source_head_commit = git_head_commit(local_path)
        if local_path.is_relative_to(raw_root(project_root).resolve()):
            shutil.move(str(local_path), stage_source)
        else:
            copytree_filtered(local_path, stage_source)
        explicit_repo_name = local_path.name
        if explicit_repo_name.lower() in {"source", "repo"} and canonical_remote:
            explicit_repo_name = Path(canonical_remote.rstrip("/")).name or explicit_repo_name

    facts = load_legacy_repo_facts(project_root, stage_source)
    repo_name = explicit_repo_name or facts.get("repo_name", stage_source.name)
    canonical_remote = normalize_remote_url(canonical_remote or git_remote_url(stage_source))
    owner_name = owner_name_from_remote(canonical_remote) or slugify(repo_name, max_words=4)
    context = _read_repo_context(stage_source)
    topics, tags = infer_topics_and_tags(f"{repo_name}\n{context}")
    candidate = {
        "intake_id": intake_id,
        "repo_name": repo_name,
        "canonical_remote": canonical_remote,
        "owner_name": owner_name,
        "import_type": import_type,
        "frameworks": facts.get("framework_hints", []),
        "entrypoints": [item["path"] for item in facts.get("entrypoints", [])],
        "topics": topics,
        "tags": tags,
        "repo_type": facts.get("repo_type_hint", ""),
        "primary_language": facts.get("primary_language", ""),
        "source_label": source_label,
        "head_commit": source_head_commit or git_head_commit(stage_source),
        "readme_excerpt": context,
        "staged_source": stage_source,
    }
    write_yaml_if_changed(stage_dir / "manifest.yaml", {"candidate": _to_manifest_value(candidate)})
    return stage_dir, candidate


def load_manifest_candidate(stage_dir: Path) -> dict[str, Any]:
    payload = load_yaml(stage_dir / "manifest.yaml", default={})
    if not isinstance(payload, dict) or not isinstance(payload.get("candidate"), dict):
        raise SystemExit(f"Invalid repo intake manifest: {stage_dir / 'manifest.yaml'}")
    return _from_manifest_value(payload["candidate"])


def register_resolved_review(project_root: Path, review_item: dict[str, Any]) -> None:
    payload = load_list_document(resolved_repo_reviews_path(project_root), "resolved-repo-reviews", "repo-cataloger")
    payload["generated_at"] = utc_now_iso()
    payload["items"].append(review_item)
    write_yaml_if_changed(resolved_repo_reviews_path(project_root), payload)


def append_pending_review(project_root: Path, review_item: dict[str, Any]) -> None:
    payload = load_list_document(pending_repo_reviews_path(project_root), "pending-repo-reviews", "repo-cataloger")
    payload["generated_at"] = utc_now_iso()
    payload["items"].append(review_item)
    write_yaml_if_changed(pending_repo_reviews_path(project_root), payload)


def remove_pending_review(project_root: Path, review_id: str) -> dict[str, Any]:
    payload = load_list_document(pending_repo_reviews_path(project_root), "pending-repo-reviews", "repo-cataloger")
    kept: list[dict[str, Any]] = []
    matched: dict[str, Any] | None = None
    for item in payload["items"]:
        if item.get("review_id") == review_id:
            matched = item
        else:
            kept.append(item)
    if matched is None:
        raise SystemExit(f"Pending repo review not found: {review_id}")
    payload["items"] = kept
    payload["generated_at"] = utc_now_iso()
    write_yaml_if_changed(pending_repo_reviews_path(project_root), payload)
    return matched


def exact_match(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    if existing.get("canonical_remote") and existing.get("canonical_remote") == candidate.get("canonical_remote"):
        return True
    if existing.get("owner_name") and existing.get("owner_name") == candidate.get("owner_name") and existing.get("repo_name") == candidate.get("repo_name"):
        return True
    return False


def attach_alias(project_root: Path, canonical_id: str, candidate: dict[str, Any], *, resolution: str) -> None:
    summary_path = research_root(project_root) / "library" / "repos" / canonical_id / "summary.yaml"
    summary = load_yaml(summary_path, default={})
    if not isinstance(summary, dict):
        raise SystemExit(f"Missing canonical repo summary: {summary_path}")
    alias_entry = {
        "alias_id": candidate["intake_id"],
        "source_label": candidate["source_label"],
        "canonical_remote": candidate.get("canonical_remote", ""),
        "head_commit": candidate.get("head_commit", ""),
        "resolved_at": utc_now_iso(),
        "resolution": resolution,
    }
    summary.setdefault("aliases", [])
    summary["aliases"].append(alias_entry)
    write_yaml_if_changed(summary_path, summary)

    payload = load_index(repo_index_path(project_root), "repo-index", "repo-cataloger")
    item = payload["items"].get(canonical_id, {})
    item.setdefault("aliases", [])
    item["aliases"].append(alias_entry)
    payload["items"][canonical_id] = item
    write_yaml_if_changed(repo_index_path(project_root), payload)
    rebuild_repo_index(project_root)

    if candidate.get("staged_source") and Path(candidate["staged_source"]).exists():
        shutil.rmtree(candidate["staged_source"])


def finalize_new_repo(project_root: Path, candidate: dict[str, Any]) -> str:
    repo_id = unique_repo_id(project_root, make_repo_id(candidate))
    entry_root = canonical_repo_root(project_root, repo_id)
    source_root = entry_root / "source"
    source_root.parent.mkdir(parents=True, exist_ok=True)
    if source_root.exists():
        shutil.rmtree(source_root)
    shutil.move(str(candidate["staged_source"]), source_root)
    facts = load_legacy_repo_facts(project_root, source_root)
    repo_inputs = [f"intake:{candidate['intake_id']}"]
    if candidate.get("canonical_remote"):
        repo_inputs.append(candidate["canonical_remote"])
    repo_inputs.append(source_root.relative_to(find_project_root()).as_posix())

    summary = {
        **yaml_default(repo_id, "repo-cataloger", status="active", confidence=0.9),
        "inputs": repo_inputs,
        "repo_id": repo_id,
        "repo_name": candidate["repo_name"],
        "short_summary": "",
        "canonical_remote": candidate.get("canonical_remote", ""),
        "owner_name": candidate.get("owner_name", ""),
        "import_type": candidate.get("import_type", ""),
        "primary_language": candidate.get("primary_language", ""),
        "frameworks": candidate.get("frameworks", []),
        "topics": candidate.get("topics", []),
        "tags": candidate.get("tags", []),
        "repo_type": candidate.get("repo_type", ""),
        "entrypoints": candidate.get("entrypoints", []),
        "aliases": [],
        "head_commit": candidate.get("head_commit", ""),
    }
    short_summary = ensure_summary_short_summary(summary, facts, candidate.get("readme_excerpt", ""), rewrite=True)
    entrypoints = {
        **yaml_default(f"{repo_id}-entrypoints", "repo-cataloger"),
        "inputs": repo_inputs,
        "entrypoints": facts.get("entrypoints", []),
    }
    modules = {
        **yaml_default(f"{repo_id}-modules", "repo-cataloger"),
        "inputs": repo_inputs,
        "modules": [
            {
                "module_id": f"{repo_id}-module-{idx + 1}",
                "path": path,
                "role": "key-dir",
            }
            for idx, path in enumerate(facts.get("key_dirs", []))
        ]
        + [
            {
                "module_id": f"{repo_id}-subsystem-{idx + 1}",
                "path": item["path"],
                "role": "subsystem",
                "children": item.get("children", []),
            }
            for idx, item in enumerate(facts.get("subsystems", []))
        ],
    }
    write_yaml_if_changed(entry_root / "summary.yaml", summary)
    write_yaml_if_changed(entry_root / "entrypoints.yaml", entrypoints)
    write_yaml_if_changed(entry_root / "modules.yaml", modules)
    prepare_note_assets_for_repo(repo_id, rewrite_generated_notes=True)

    payload = load_index(repo_index_path(project_root), "repo-index", "repo-cataloger")
    payload["generated_at"] = utc_now_iso()
    payload["items"][repo_id] = {
        "id": repo_id,
        "repo_name": candidate["repo_name"],
        "short_summary": short_summary,
        "canonical_remote": candidate.get("canonical_remote", ""),
        "owner_name": candidate.get("owner_name", ""),
        "aliases": [],
        "import_type": candidate.get("import_type", ""),
        "frameworks": candidate.get("frameworks", []),
        "entrypoints": candidate.get("entrypoints", []),
        "topics": candidate.get("topics", []),
        "tags": candidate.get("tags", []),
    }
    write_yaml_if_changed(repo_index_path(project_root), payload)
    rebuild_repo_index(project_root)
    return repo_id


def catalog_candidate(project_root: Path, candidate: dict[str, Any]) -> tuple[str, str]:
    payload = load_index(repo_index_path(project_root), "repo-index", "repo-cataloger")
    items = payload.get("items", {})
    for repo_id, existing in items.items():
        if exact_match(existing, candidate):
            attach_alias(project_root, repo_id, candidate, resolution="exact-duplicate")
            return "merged", repo_id

    fuzzy_matches: list[tuple[float, str, list[str]]] = []
    for repo_id, existing in items.items():
        score, reasons = score_fuzzy_repo_match(existing, candidate)
        if score >= 0.8:
            fuzzy_matches.append((score, repo_id, reasons))
    fuzzy_matches.sort(reverse=True)
    if fuzzy_matches:
        top_score, top_repo_id, reasons = fuzzy_matches[0]
        review_id = f"repo-review-{candidate['intake_id']}"
        append_pending_review(
            project_root,
            {
                "review_id": review_id,
                "intake_id": candidate["intake_id"],
                "candidate_repo_name": candidate["repo_name"],
                "candidate_remote": candidate.get("canonical_remote", ""),
                "suggested_canonical_id": top_repo_id,
                "similarity": round(top_score, 2),
                "reasons": reasons,
                "status": "pending",
            },
        )
        return "pending-review", review_id
    return "imported", finalize_new_repo(project_root, candidate)


def persist_manifest(stage_dir: Path, candidate: dict[str, Any], *, status: str, result: str) -> None:
    write_yaml_if_changed(
        stage_dir / "manifest.yaml",
        {
            "candidate": _to_manifest_value(candidate),
            "status": status,
            "result": result,
            "updated_at": utc_now_iso(),
        },
    )


def ingest_sources(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    if not args.repo:
        raise SystemExit("At least one --repo source is required.")
    for raw_source in args.repo:
        stage_dir, candidate = stage_repo(project_root, raw_source)
        status, result = catalog_candidate(project_root, candidate)
        persist_manifest(stage_dir, candidate, status=status, result=result)
        if status == "pending-review":
            print(f"[review] {candidate['repo_name']} -> {result}")
        else:
            register_resolved_review(
                project_root,
                {
                    "review_id": f"resolved-{candidate['intake_id']}",
                    "intake_id": candidate["intake_id"],
                    "repo_name": candidate["repo_name"],
                    "resolution": status,
                    "canonical_id": result,
                },
            )
            print(f"[ok] {candidate['repo_name']} -> {result} ({status})")
    return 0


def resolve_review(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    review_item = remove_pending_review(project_root, args.review_id)
    stage_dir = intake_root(project_root) / review_item["intake_id"]
    candidate = load_manifest_candidate(stage_dir)
    if args.decision == "existing":
        if not args.canonical_id:
            raise SystemExit("--canonical-id is required when decision=existing")
        attach_alias(project_root, args.canonical_id, candidate, resolution="confirmed-duplicate")
        resolution = args.canonical_id
    else:
        resolution = finalize_new_repo(project_root, candidate)
    persist_manifest(stage_dir, candidate, status="resolved", result=resolution)
    register_resolved_review(
        project_root,
        {
            "review_id": review_item["review_id"],
            "intake_id": review_item["intake_id"],
            "repo_name": review_item["candidate_repo_name"],
            "resolution": args.decision,
            "canonical_id": resolution,
        },
    )
    print(f"[ok] resolved {args.review_id} -> {resolution}")
    return 0


def refresh_notes_cmd(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    summary_paths = (
        [research_root(project_root) / "library" / "repos" / repo_id / "summary.yaml" for repo_id in args.repo_id]
        if args.repo_id
        else sorted((research_root(project_root) / "library" / "repos").glob("*/summary.yaml"))
    )
    changed = 0
    for summary_path in summary_paths:
        summary = load_yaml(summary_path, default={})
        if not isinstance(summary, dict) or not summary.get("repo_id"):
            raise SystemExit(f"Invalid repo summary: {summary_path}")
        source_root = summary_path.parent / "source"
        facts = load_legacy_repo_facts(project_root, source_root)
        before_summary = clean_text(str(summary.get("short_summary") or ""))
        short_summary = ensure_summary_short_summary(summary, facts, _read_repo_context(source_root), rewrite=args.rewrite_summary)
        if short_summary != before_summary:
            write_yaml_if_changed(summary_path, summary)
            changed += 1
        prepare_note_assets_for_repo(str(summary["repo_id"]), rewrite_generated_notes=args.rewrite_generated_notes)
    print(f"[ok] delegated repo note preparation to research-note-author ({changed} summary updates)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Catalog local and remote repositories into the research library.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_cmd = subparsers.add_parser("ingest", help="Catalog repo sources")
    ingest_cmd.add_argument("--repo", action="append", default=[], help="Local path or GitHub URL")
    ingest_cmd.set_defaults(func=ingest_sources)

    resolve_cmd = subparsers.add_parser("resolve-review", help="Resolve a pending duplicate review")
    resolve_cmd.add_argument("--review-id", required=True)
    resolve_cmd.add_argument("--decision", choices=["existing", "new"], required=True)
    resolve_cmd.add_argument("--canonical-id", default="")
    resolve_cmd.set_defaults(func=resolve_review)

    rebuild_cmd = subparsers.add_parser("rebuild-index", help="Rebuild the repo index from canonical repo summaries")
    rebuild_cmd.set_defaults(func=lambda _args: (rebuild_repo_index(find_project_root()), print("[ok] rebuilt repo index"), 0)[2])

    refresh_notes = subparsers.add_parser("refresh-notes", help="Refresh short_summary and delegate note asset preparation to research-note-author")
    refresh_notes.add_argument("--repo-id", action="append", default=[], help="Canonical repo ID to refresh")
    refresh_notes.add_argument("--rewrite-summary", action="store_true", help="Regenerate short_summary even if one already exists")
    refresh_notes.add_argument(
        "--rewrite-generated-notes",
        action="store_true",
        help="Replace notes only when they still look auto-generated or scaffolding-based",
    )
    refresh_notes.set_defaults(func=refresh_notes_cmd)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    project_root = find_project_root()
    ensure_research_runtime(project_root, "repo-cataloger")
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
