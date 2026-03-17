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
        line = re.sub(r"!\[[^\]]*\]\([^)]+\)", " ", line)
        line = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", line)
        line = re.sub(r"<[^>]+>", " ", line)
        line = re.sub(r"https?://\S+", " ", line)
        line = re.sub(r"`([^`]*)`", r"\1", line)
        line = re.sub(r"[|]{2,}", " ", line)
        if re.fullmatch(r"[-*_=\s]+", line):
            continue
        cleaned_lines.append(clean_text(line))
    return "\n".join(cleaned_lines).strip()


def _repo_sentences(text: str) -> list[str]:
    cleaned = clean_text(re.sub(r"\s+", " ", text))
    if not cleaned:
        return []
    parts = [clean_text(part) for part in re.split(r"(?<=[.!?])\s+", cleaned) if clean_text(part)]
    return parts or [cleaned]


def build_repo_short_summary(candidate: dict[str, Any], facts: dict[str, Any], context: str, *, max_chars: int = 320) -> str:
    repo_name = str(candidate.get("repo_name") or facts.get("repo_name") or "repository")
    cleaned_context = _clean_repo_context(context)
    for sentence in _repo_sentences(cleaned_context):
        lowered = sentence.lower()
        if len(sentence) < 40:
            continue
        if repo_name.lower() in lowered and len(sentence.split()) <= 6:
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


def _working_notes_block(note_path: Path) -> str:
    if note_path.exists():
        existing = note_path.read_text(encoding="utf-8")
        for header in MANUAL_NOTE_HEADERS:
            start = existing.find(header)
            if start >= 0:
                preserved = existing[start:].strip()
                if preserved:
                    return preserved
    return (
        "## Working Notes\n\n"
        "- Pending deeper read: replace this scaffold with concrete architecture findings, risks, and extension points.\n"
    )


def build_repo_note(repo_id: str, summary: dict[str, Any], facts: dict[str, Any], *, note_path: Path) -> str:
    short_summary = ensure_summary_short_summary(summary, facts, str(summary.get("readme_excerpt") or ""), rewrite=False)
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
        "short_summary": short_summary or "No short summary available yet.",
        "retrieval_cues": "\n".join(retrieval_lines),
        "structure_cues": "\n".join(structure_lines),
        "entrypoints": "\n".join(entrypoint_lines),
        "working_notes_block": _working_notes_block(note_path),
    }
    for key, value in context.items():
        note = note.replace(f"{{{{{key}}}}}", value)
    return note.rstrip() + "\n"


def refresh_repo_notes(project_root: Path, repo_ids: list[str] | None = None, *, rewrite_summary: bool = False) -> int:
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
        note_text = build_repo_note(repo_id, summary, facts, note_path=note_path)
        before_note = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
        write_text_if_changed(note_path, note_text)
        if note_text != before_note:
            changed += 1
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

    if is_url(raw_source):
        import_type = "github-url"
        subprocess.run(
            ["git", "clone", "--depth", "1", raw_source, str(stage_source)],
            check=True,
        )
        canonical_remote = normalize_remote_url(raw_source)
        explicit_repo_name = Path(canonical_remote.rstrip("/")).name or "repo"
    else:
        local_path = Path(raw_source).resolve()
        canonical_remote = git_remote_url(local_path)
        if local_path.is_relative_to(raw_root(project_root).resolve()):
            shutil.move(str(local_path), stage_source)
        else:
            copytree_filtered(local_path, stage_source)
        explicit_repo_name = local_path.name

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
        "head_commit": git_head_commit(stage_source),
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
    notes = build_repo_note(repo_id, summary, facts, note_path=entry_root / "repo-notes.md")
    write_yaml_if_changed(entry_root / "summary.yaml", summary)
    write_yaml_if_changed(entry_root / "entrypoints.yaml", entrypoints)
    write_yaml_if_changed(entry_root / "modules.yaml", modules)
    write_text_if_changed(entry_root / "repo-notes.md", notes)

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
    changed = refresh_repo_notes(project_root, repo_ids=list(args.repo_id), rewrite_summary=args.rewrite_summary)
    print(f"[ok] refreshed repo notes and summaries ({changed} file updates)")
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

    refresh_notes = subparsers.add_parser("refresh-notes", help="Refresh repo-notes.md and short_summary from canonical repo metadata")
    refresh_notes.add_argument("--repo-id", action="append", default=[], help="Canonical repo ID to refresh")
    refresh_notes.add_argument("--rewrite-summary", action="store_true", help="Regenerate short_summary even if one already exists")
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
