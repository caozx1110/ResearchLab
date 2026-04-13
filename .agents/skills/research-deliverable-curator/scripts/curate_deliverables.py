#!/usr/bin/env python3
"""Curate human-facing research entrypoints under kb/user/."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

for candidate in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
    lib_root = candidate / ".agents" / "lib"
    if (lib_root / "research" / "common.py").exists():
        sys.path.insert(0, str(lib_root))
        break


def _maybe_reexec_preferred_runtime() -> None:
    if os.environ.get("RESEARCH_RUNTIME_REEXEC") == "1":
        return
    try:
        import yaml  # noqa: F401
        return
    except ModuleNotFoundError:
        pass
    current = Path.cwd().resolve()
    project_root = None
    for candidate in [current] + list(current.parents):
        if (candidate / ".agents").exists() and (
            (candidate / "kb").exists() or (candidate / "doc").exists() or (candidate / "AGENTS.md").exists()
        ):
            project_root = candidate
            break
    if project_root is None:
        return
    runtime_root = project_root / "kb"
    if not runtime_root.exists():
        runtime_root = project_root / "doc" / "research"
    runtime_path = runtime_root / "memory" / "runtime-environments.yaml"
    if not runtime_path.exists():
        return
    match = re.search(r"^\s*python:\s*(.+?)\s*$", runtime_path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    if not match:
        return
    runtime_python = match.group(1).strip().strip("'\"")
    if not runtime_python or not Path(runtime_python).exists():
        return
    env = dict(os.environ)
    env["RESEARCH_RUNTIME_REEXEC"] = "1"
    os.execvpe(runtime_python, [runtime_python, __file__, *sys.argv[1:]], env)


_maybe_reexec_preferred_runtime()

from research.common import (
    ensure_dir,
    find_project_root,
    load_yaml,
    research_root,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
)


def relative_link(from_path: Path, to_path: Path) -> str:
    return os.path.relpath(to_path, start=from_path.parent).replace(os.sep, "/")


def markdown_link(from_path: Path, to_path: Path, label: str) -> str:
    return f"[{label}]({relative_link(from_path, to_path)})"


def relative_to_project(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def safe_load_yaml(path: Path, default: Any) -> Any:
    return load_yaml(path, default=default, allow_simple_fallback=True)


def safe_load_list_document(path: Path, doc_id: str, generated_by: str) -> dict[str, Any]:
    payload = safe_load_yaml(path, {})
    if not isinstance(payload, dict):
        return {**yaml_default(doc_id, generated_by), "items": []}
    payload.setdefault("id", doc_id)
    payload.setdefault("status", "ready")
    payload.setdefault("generated_by", generated_by)
    payload.setdefault("generated_at", utc_now_iso())
    payload["inputs"] = [str(item) for item in payload.get("inputs", []) if str(item).strip()] if isinstance(payload.get("inputs"), list) else []
    payload.setdefault("confidence", 1.0)
    payload["items"] = payload.get("items") if isinstance(payload.get("items"), list) else []
    return payload


def safe_append_program_reporting_event(
    project_root: Path,
    program_id: str,
    event: dict[str, Any],
    *,
    generated_by: str,
) -> None:
    path = research_root(project_root) / "programs" / program_id / "workflow" / "reporting-events.yaml"
    payload = safe_load_list_document(path, f"{program_id}-reporting-events", generated_by)
    payload["program_id"] = program_id
    payload["generated_by"] = generated_by
    payload["generated_at"] = utc_now_iso()
    payload["items"].append(event)
    write_yaml_if_changed(path, payload)


def load_user_profile(project_root: Path) -> dict[str, Any]:
    payload = safe_load_yaml(research_root(project_root) / "memory" / "user-profile.yaml", {})
    return payload if isinstance(payload, dict) else {}


def prefers_chinese(profile: dict[str, Any]) -> bool:
    return "zh" in str(profile.get("language_preference") or "").lower()


def available_program_ids(project_root: Path) -> list[str]:
    programs_root = research_root(project_root) / "programs"
    return sorted(path.name for path in programs_root.iterdir() if path.is_dir()) if programs_root.exists() else []


def resolve_program_id(project_root: Path, requested: str | None) -> str:
    if requested:
        return requested
    program_ids = available_program_ids(project_root)
    if not program_ids:
        raise SystemExit("No programs found under kb/programs")
    if len(program_ids) == 1:
        return program_ids[0]
    return program_ids[0]


def load_program_bundle(project_root: Path, program_id: str) -> dict[str, Any]:
    program_root = research_root(project_root) / "programs" / program_id
    if not program_root.exists():
        raise SystemExit(f"Program not found: {program_id}")

    bundle: dict[str, Any] = {
        "program_root": program_root,
        "charter": safe_load_yaml(program_root / "charter.yaml", {}),
        "state": safe_load_yaml(program_root / "workflow" / "state.yaml", {}),
        "evidence": safe_load_yaml(program_root / "evidence" / "literature-map.yaml", {}),
        "repo_choice": safe_load_yaml(program_root / "design" / "repo-choice.yaml", {}),
    }
    bundle["weekly_files"] = sorted((program_root / "weekly").glob("*.md"), reverse=True) if (program_root / "weekly").exists() else []
    bundle["design_files"] = [path for path in [
        program_root / "design" / "system-design.md",
        program_root / "design" / "selected-idea.yaml",
        program_root / "design" / "repo-choice.yaml",
        program_root / "design" / "interfaces.yaml",
        program_root / "experiments" / "matrix.yaml",
        program_root / "experiments" / "runbook.md",
    ] if path.exists()]
    return bundle


def literature_record_map(project_root: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    literature_root = research_root(project_root) / "library" / "literature"
    for metadata_path in sorted(literature_root.glob("*/metadata.yaml")):
        record = safe_load_yaml(metadata_path, {})
        if isinstance(record, dict) and str(record.get("id") or "").strip():
            records[str(record.get("id"))] = record
    return records


def repo_record_map(project_root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    repo_root = research_root(project_root) / "library" / "repos"
    for summary_path in sorted(repo_root.glob("*/summary.yaml")):
        record = safe_load_yaml(summary_path, {})
        if not isinstance(record, dict):
            continue
        repo_id = str(record.get("repo_id") or record.get("id") or "").strip()
        if repo_id:
            result[repo_id] = record
    return result


def compact_text(text: Any, max_chars: int = 120) -> str:
    cleaned = " ".join(str(text or "").split()).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    trimmed = cleaned[: max_chars - 3].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{trimmed or cleaned[: max_chars - 3]}..."


def selected_papers(
    project_root: Path,
    evidence: dict[str, Any],
    literature_by_id: dict[str, dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    items = []
    retrieval = evidence.get("retrieval") if isinstance(evidence, dict) else {}
    selected = retrieval.get("selected_sources") if isinstance(retrieval, dict) else []
    if isinstance(selected, list):
        for item in selected:
            if not isinstance(item, dict):
                continue
            source_id = str(item.get("source_id") or "").strip()
            if not source_id:
                continue
            record = literature_by_id.get(source_id, {})
            paper_root = research_root(project_root) / "library" / "literature" / source_id
            items.append(
                {
                    "source_id": source_id,
                    "title": str(item.get("title") or record.get("canonical_title") or source_id),
                    "summary": str(item.get("short_summary") or record.get("short_summary") or ""),
                    "score": int(item.get("score") or 0),
                    "reasons": [str(reason).strip() for reason in item.get("reasons", []) if str(reason).strip()],
                    "note_path": paper_root / "note.md",
                    "pdf_path": paper_root / "source" / "primary.pdf",
                }
            )
    return items[:limit]


def selected_repos(
    project_root: Path,
    repo_choice: dict[str, Any],
    repo_by_id: dict[str, dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    items = []
    candidates = repo_choice.get("candidate_repos") if isinstance(repo_choice, dict) else []
    if isinstance(candidates, list):
        for item in candidates:
            if not isinstance(item, dict):
                continue
            repo_id = str(item.get("repo_id") or "").strip()
            if not repo_id:
                continue
            record = repo_by_id.get(repo_id, {})
            repo_root = research_root(project_root) / "library" / "repos" / repo_id
            items.append(
                {
                    "repo_id": repo_id,
                    "repo_name": str(item.get("repo_name") or record.get("repo_name") or repo_id),
                    "summary": str(item.get("short_summary") or record.get("short_summary") or ""),
                    "score": int(item.get("score") or 0),
                    "summary_path": repo_root / "summary.yaml",
                    "source_path": repo_root / "source",
                }
            )
    return items[:limit]


def wiki_query_files(project_root: Path, limit: int) -> list[Path]:
    query_root = research_root(project_root) / "wiki" / "queries"
    if not query_root.exists():
        return []
    return sorted(query_root.glob("*.md"), reverse=True)[:limit]


def export_files(project_root: Path, limit: int) -> list[Path]:
    output_root = project_root / "output" / "doc"
    if not output_root.exists():
        return []
    return sorted([path for path in output_root.iterdir() if path.is_file()], reverse=True)[:limit]


def derive_now_open_paths(bundle: dict[str, Any], reading_list_path: Path, deliverable_index_path: Path) -> list[tuple[str, Path]]:
    state = bundle["state"] if isinstance(bundle.get("state"), dict) else {}
    stage = str(state.get("stage") or "")
    program_root = bundle["program_root"]
    preferred: list[tuple[str, Path]] = [
        ("当前阅读清单", reading_list_path),
        ("当前成果入口", deliverable_index_path),
    ]
    stage_specific = []
    if stage == "literature-analysis":
        stage_specific = [
            ("文献地图", program_root / "evidence" / "literature-map.yaml"),
            ("最新周报", bundle["weekly_files"][0] if bundle["weekly_files"] else program_root / "workflow" / "reporting-events.yaml"),
        ]
    elif stage in {"method-design", "implementation-planning"}:
        stage_specific = [
            ("系统设计", program_root / "design" / "system-design.md"),
            ("仓库选择", program_root / "design" / "repo-choice.yaml"),
            ("实验矩阵", program_root / "experiments" / "matrix.yaml"),
        ]
    else:
        stage_specific = [
            ("项目问题定义", program_root / "charter.yaml"),
            ("工作流状态", program_root / "workflow" / "state.yaml"),
        ]
    for label, path in stage_specific:
        if path.exists():
            preferred.append((label, path))
    unique: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for label, path in preferred:
        if not path.exists() or path in seen:
            continue
        seen.add(path)
        unique.append((label, path))
    return unique[:4]


def build_reading_list_markdown(
    project_root: Path,
    output_path: Path,
    program_id: str,
    bundle: dict[str, Any],
    papers: list[dict[str, Any]],
    repos: list[dict[str, Any]],
    zh: bool,
) -> str:
    charter = bundle["charter"] if isinstance(bundle.get("charter"), dict) else {}
    state = bundle["state"] if isinstance(bundle.get("state"), dict) else {}
    lines = [
        f"# 当前阅读清单：`{program_id}`" if zh else f"# Current Reading List: `{program_id}`",
        "",
        f"- 生成时间: `{utc_now_iso()}`" if zh else f"- Generated at: `{utc_now_iso()}`",
        f"- 当前阶段: `{state.get('stage') or 'unknown'}`" if zh else f"- Current stage: `{state.get('stage') or 'unknown'}`",
        f"- 研究问题: {str(charter.get('question') or '').strip()}" if zh else f"- Research question: {str(charter.get('question') or '').strip()}",
        "",
        "## 现在先精读这几篇" if zh else "## Read These First",
        "",
    ]
    top = papers[:3]
    rest = papers[3:]
    for index, paper in enumerate(top, start=1):
        note_link = markdown_link(output_path, paper["note_path"], "笔记" if zh else "note") if paper["note_path"].exists() else "`note.md`"
        pdf_link = markdown_link(output_path, paper["pdf_path"], "原始 PDF" if zh else "original PDF") if paper["pdf_path"].exists() else "`primary.pdf`"
        reason_text = "；".join(paper["reasons"][:3]) if paper["reasons"] else ("当前 evidence map 高优先级命中" if zh else "High-priority evidence-map hit")
        lines.extend(
            [
                f"### {index}. {paper['title']}",
                f"- ID: `{paper['source_id']}`",
                f"- 为什么现在看: {reason_text}" if zh else f"- Why now: {reason_text}",
                f"- 一句话: {compact_text(paper['summary'], 160)}" if zh else f"- Summary: {compact_text(paper['summary'], 160)}",
                f"- {note_link} | {pdf_link}",
                "",
            ]
        )
    if rest:
        lines.extend(
            [
                "## 延伸阅读" if zh else "## Follow-up Reading",
                "",
            ]
        )
        for paper in rest:
            note_link = markdown_link(output_path, paper["note_path"], "笔记" if zh else "note") if paper["note_path"].exists() else "`note.md`"
            pdf_link = markdown_link(output_path, paper["pdf_path"], "PDF" if zh else "PDF") if paper["pdf_path"].exists() else "`primary.pdf`"
            lines.append(
                f"- `{paper['source_id']}` {paper['title']} | {note_link} | {pdf_link} | {compact_text(paper['summary'], 100)}"
            )
        lines.append("")
    if repos:
        lines.extend(
            [
                "## 对照源码入口" if zh else "## Reference Repo Entry Points",
                "",
            ]
        )
        for repo in repos:
            summary_link = markdown_link(output_path, repo["summary_path"], "摘要" if zh else "summary") if repo["summary_path"].exists() else "`summary.yaml`"
            source_link = markdown_link(output_path, repo["source_path"], "源码" if zh else "source") if repo["source_path"].exists() else "`source/`"
            lines.append(
                f"- `{repo['repo_id']}` {repo['repo_name']} | {summary_link} | {source_link} | {compact_text(repo['summary'], 110)}"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_deliverable_index_markdown(
    project_root: Path,
    output_path: Path,
    program_id: str,
    bundle: dict[str, Any],
    reading_list_path: Path,
    query_paths: list[Path],
    export_paths: list[Path],
    zh: bool,
) -> str:
    program_root = bundle["program_root"]
    lines = [
        "# 当前成果入口" if zh else "# Current Deliverables",
        "",
        f"- 生成时间: `{utc_now_iso()}`" if zh else f"- Generated at: `{utc_now_iso()}`",
        f"- 当前 program: `{program_id}`" if zh else f"- Current program: `{program_id}`",
        "",
        "## 如果现在只打开三个文件" if zh else "## Open These First",
        "",
    ]
    for label, path in derive_now_open_paths(bundle, reading_list_path, output_path):
        if path == output_path:
            continue
        lines.append(f"- {markdown_link(output_path, path, label)}")
    lines.append("")
    lines.extend(
        [
            "## 周报与阶段产物" if zh else "## Weekly Reports and Stage Artifacts",
            "",
        ]
    )
    for path in bundle["weekly_files"][:6]:
        lines.append(f"- {markdown_link(output_path, path, path.name)}")
    for path in bundle["design_files"]:
        short_label = path.relative_to(program_root).as_posix() if path.is_relative_to(program_root) else relative_to_project(project_root, path)
        lines.append(f"- {markdown_link(output_path, path, short_label)}")
    lines.append("")
    if export_paths:
        lines.extend(
            [
                "## 导出文档" if zh else "## Exported Documents",
                "",
            ]
        )
        for path in export_paths:
            lines.append(f"- {markdown_link(output_path, path, path.name)}")
        lines.append("")
    if query_paths:
        lines.extend(
            [
                "## Wiki 查询沉淀" if zh else "## Wiki Query Artifacts",
                "",
            ]
        )
        for path in query_paths:
            lines.append(f"- {markdown_link(output_path, path, path.name)}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_navigation_markdown(
    project_root: Path,
    output_path: Path,
    program_id: str,
    bundle: dict[str, Any],
    papers: list[dict[str, Any]],
    repos: list[dict[str, Any]],
    reading_list_path: Path,
    deliverable_index_path: Path,
    zh: bool,
) -> str:
    lines = [
        "# 研究导航" if zh else "# Research Navigation",
        "",
        "这是当前工作区的人工入口页。建议先看“现在先打开什么”，再决定是否深入到更深层目录。"
        if zh
        else "This is the human-facing entry page for the current workspace.",
        "",
        "## 现在先打开什么" if zh else "## Open These First",
        "",
    ]
    for label, path in derive_now_open_paths(bundle, reading_list_path, deliverable_index_path):
        lines.append(f"- {markdown_link(output_path, path, label)}")
    lines.extend(
        [
            "",
            "## 起步入口" if zh else "## Start Here",
            "",
            f"- {markdown_link(output_path, project_root / 'AGENTS.md', '工作区 schema (AGENTS.md)' if zh else 'Workspace schema (AGENTS.md)')}",
            f"- {markdown_link(output_path, research_root(project_root) / 'wiki' / 'index.md', 'wiki/index.md')}",
            f"- {markdown_link(output_path, research_root(project_root) / 'wiki' / 'log.md', 'wiki/log.md')}",
            f"- {markdown_link(output_path, research_root(project_root) / 'wiki' / 'skill-capability-matrix.md', 'skill-capability-matrix.md')}",
            f"- {markdown_link(output_path, reading_list_path, '当前阅读清单' if zh else 'current reading list')}",
            f"- {markdown_link(output_path, deliverable_index_path, '当前成果入口' if zh else 'current deliverables')}",
            "",
            "## 当前项目" if zh else "## Current Program",
            "",
        ]
    )
    key_paths = [
        ("项目根目录", bundle["program_root"]),
        ("charter.yaml", bundle["program_root"] / "charter.yaml"),
        ("workflow/state.yaml", bundle["program_root"] / "workflow" / "state.yaml"),
        ("workflow/reporting-events.yaml", bundle["program_root"] / "workflow" / "reporting-events.yaml"),
        ("evidence/literature-map.yaml", bundle["program_root"] / "evidence" / "literature-map.yaml"),
        ("design/system-design.md", bundle["program_root"] / "design" / "system-design.md"),
        ("design/repo-choice.yaml", bundle["program_root"] / "design" / "repo-choice.yaml"),
        ("experiments/matrix.yaml", bundle["program_root"] / "experiments" / "matrix.yaml"),
        ("experiments/runbook.md", bundle["program_root"] / "experiments" / "runbook.md"),
    ]
    for label, path in key_paths:
        if path.exists():
            lines.append(f"- {markdown_link(output_path, path, label)}")
    if papers:
        lines.extend(
            [
                "",
                "## 当前重点阅读包" if zh else "## Current Priority Reading Pack",
                "",
            ]
        )
        for paper in papers:
            note_link = markdown_link(output_path, paper["note_path"], "笔记" if zh else "note") if paper["note_path"].exists() else "`note.md`"
            pdf_link = markdown_link(output_path, paper["pdf_path"], "原始 PDF" if zh else "pdf") if paper["pdf_path"].exists() else "`primary.pdf`"
            lines.append(f"- `{paper['source_id']}` {paper['title']} | {note_link} | {pdf_link}")
    if repos:
        lines.extend(
            [
                "",
                "## 当前重点仓库" if zh else "## Current Priority Repos",
                "",
            ]
        )
        for repo in repos:
            summary_link = markdown_link(output_path, repo["summary_path"], "摘要" if zh else "summary") if repo["summary_path"].exists() else "`summary.yaml`"
            source_link = markdown_link(output_path, repo["source_path"], "源码" if zh else "source") if repo["source_path"].exists() else "`source/`"
            lines.append(f"- `{repo['repo_id']}` {repo['repo_name']} | {summary_link} | {source_link}")
    lines.extend(
        [
            "",
            "## 快速重开路径" if zh else "## Reopen Paths Quickly",
            "",
            "- `kb/library/literature/<source-id>/source/primary.pdf`",
            "- `kb/library/literature/<source-id>/note.md`",
            "- `kb/library/repos/<repo-id>/summary.yaml`",
            "- `kb/library/repos/<repo-id>/source/`",
            "- `kb/programs/<program-id>/weekly/`",
            "- `output/doc/`",
            "",
        ]
    )
    return "\n".join(lines).rstrip() + "\n"


def write_reading_list(project_root: Path, program_id: str, top_papers: int, top_repos: int) -> tuple[Path, list[dict[str, Any]], list[dict[str, Any]]]:
    bundle = load_program_bundle(project_root, program_id)
    zh = prefers_chinese(load_user_profile(project_root))
    literature_by_id = literature_record_map(project_root)
    repo_by_id = repo_record_map(project_root)
    papers = selected_papers(project_root, bundle["evidence"], literature_by_id, limit=top_papers)
    repos = selected_repos(project_root, bundle["repo_choice"], repo_by_id, limit=top_repos)
    output_path = research_root(project_root) / "user" / "reading-lists" / f"{program_id}-current-reading.md"
    write_text_if_changed(output_path, build_reading_list_markdown(project_root, output_path, program_id, bundle, papers, repos, zh))
    return output_path, papers, repos


def write_deliverable_index(project_root: Path, program_id: str, reading_list_path: Path, query_limit: int, export_limit: int) -> Path:
    bundle = load_program_bundle(project_root, program_id)
    zh = prefers_chinese(load_user_profile(project_root))
    output_path = research_root(project_root) / "user" / "reports" / "current-deliverables.md"
    query_paths = wiki_query_files(project_root, query_limit)
    export_paths = export_files(project_root, export_limit)
    write_text_if_changed(
        output_path,
        build_deliverable_index_markdown(project_root, output_path, program_id, bundle, reading_list_path, query_paths, export_paths, zh),
    )
    return output_path


def write_navigation(project_root: Path, program_id: str, papers: list[dict[str, Any]], repos: list[dict[str, Any]], reading_list_path: Path, deliverable_index_path: Path) -> Path:
    bundle = load_program_bundle(project_root, program_id)
    zh = prefers_chinese(load_user_profile(project_root))
    output_path = research_root(project_root) / "user" / "navigation.md"
    write_text_if_changed(
        output_path,
        build_navigation_markdown(project_root, output_path, program_id, bundle, papers, repos, reading_list_path, deliverable_index_path, zh),
    )
    return output_path


def refresh_all(project_root: Path, program_id: str, top_papers: int, top_repos: int, query_limit: int, export_limit: int) -> list[Path]:
    reading_list_path, papers, repos = write_reading_list(project_root, program_id, top_papers, top_repos)
    deliverable_index_path = write_deliverable_index(project_root, program_id, reading_list_path, query_limit, export_limit)
    navigation_path = write_navigation(project_root, program_id, papers, repos, reading_list_path, deliverable_index_path)

    bundle = load_program_bundle(project_root, program_id)
    state = bundle["state"] if isinstance(bundle.get("state"), dict) else {}
    safe_append_program_reporting_event(
        project_root,
        program_id,
        {
            "source_skill": "research-deliverable-curator",
            "event_type": "deliverable-curation-updated",
            "title": "用户入口页已刷新",
            "summary": f"刷新了 `{program_id}` 的 navigation、reading list 和 deliverables 入口页。",
            "artifacts": [
                relative_to_project(project_root, navigation_path),
                relative_to_project(project_root, reading_list_path),
                relative_to_project(project_root, deliverable_index_path),
            ],
            "paper_ids": [paper["source_id"] for paper in papers[:6]],
            "repo_ids": [repo["repo_id"] for repo in repos[:4]],
            "idea_ids": [str(state.get("selected_idea_id") or "")] if str(state.get("selected_idea_id") or "").strip() else [],
            "stage": str(state.get("stage") or ""),
            "tags": ["deliverables", "navigation", "reading-list"],
            "timestamp": utc_now_iso(),
        },
        generated_by="research-deliverable-curator",
    )
    return [navigation_path, reading_list_path, deliverable_index_path]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", default="", help="Optional explicit project root")
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_shared(subparser: argparse.ArgumentParser) -> None:
        subparser.add_argument("--program-id", default="", help="Target program id")
        subparser.add_argument("--top-papers", type=int, default=12)
        subparser.add_argument("--top-repos", type=int, default=6)
        subparser.add_argument("--query-limit", type=int, default=8)
        subparser.add_argument("--export-limit", type=int, default=12)

    add_shared(subparsers.add_parser("refresh-all", help="Refresh navigation, reading list, and deliverable index"))
    add_shared(subparsers.add_parser("refresh-navigation", help="Refresh navigation.md and supporting curated pages"))
    add_shared(subparsers.add_parser("build-reading-list", help="Build the current reading list"))
    add_shared(subparsers.add_parser("build-deliverable-index", help="Build the current deliverable index"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    project_root = Path(args.project_root).resolve() if args.project_root else find_project_root()
    ensure_dir(research_root(project_root) / "user")
    program_id = resolve_program_id(project_root, args.program_id or None)

    if args.command in {"refresh-all", "refresh-navigation"}:
        created = refresh_all(project_root, program_id, args.top_papers, args.top_repos, args.query_limit, args.export_limit)
        for path in created:
            print(relative_to_project(project_root, path))
        return

    if args.command == "build-reading-list":
        path, _, _ = write_reading_list(project_root, program_id, args.top_papers, args.top_repos)
        print(relative_to_project(project_root, path))
        return

    if args.command == "build-deliverable-index":
        reading_list_path, _, _ = write_reading_list(project_root, program_id, args.top_papers, args.top_repos)
        path = write_deliverable_index(project_root, program_id, reading_list_path, args.query_limit, args.export_limit)
        print(relative_to_project(project_root, path))
        return

    raise SystemExit(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
