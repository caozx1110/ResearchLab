#!/usr/bin/env python3
"""Shared helpers for the research knowledge browser skill."""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import quote

for candidate in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
    lib_root = candidate / ".agents" / "lib"
    if (lib_root / "research_v11" / "common.py").exists():
        sys.path.insert(0, str(lib_root))
        break

from research_v11.common import (  # type: ignore
    ensure_dir,
    ensure_research_runtime,
    find_project_root,
    load_index,
    load_yaml,
    preferred_runtime_record,
    utc_now_iso,
)


SERVICE_NAME = "research-kb-browser"
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
PORT_SCAN_LIMIT = 12
READY_TIMEOUT_SECONDS = 8.0
POLL_INTERVAL_SECONDS = 0.25
SNAPSHOT_POLL_MS = 3000
WATCH_DEBOUNCE_SECONDS = 1.5


def skill_root_from_script(script_path: Path) -> Path:
    return script_path.resolve().parents[1]


def project_root_from_script(script_path: Path, explicit_root: str = "") -> Path:
    if explicit_root:
        return Path(explicit_root).resolve()
    return find_project_root(script_path.resolve())


def research_root(project_root: Path) -> Path:
    return project_root / "doc" / "research"


def kb_root(project_root: Path) -> Path:
    return research_root(project_root) / "user" / "kb"


def kb_assets_root(project_root: Path) -> Path:
    return kb_root(project_root) / "assets"


def kb_runtime_root(project_root: Path) -> Path:
    return kb_root(project_root) / ".runtime"


def snapshot_path(project_root: Path) -> Path:
    return kb_root(project_root) / "snapshot.json"


def index_html_path(project_root: Path) -> Path:
    return kb_root(project_root) / "index.html"


def launcher_state_path(project_root: Path) -> Path:
    return kb_runtime_root(project_root) / "launcher-state.json"


def build_status_path(project_root: Path) -> Path:
    return kb_runtime_root(project_root) / "build-status.json"


def server_log_path(project_root: Path) -> Path:
    return kb_runtime_root(project_root) / "server.log"


def base_url(host: str, port: int) -> str:
    return f"http://{host}:{port}"


def browser_url(host: str, port: int) -> str:
    return f"{base_url(host, port)}/doc/research/user/kb/index.html"


def health_url(host: str, port: int) -> str:
    return f"{base_url(host, port)}/api/healthz"


def version_url(host: str, port: int) -> str:
    return f"{base_url(host, port)}/api/version"


def compact_text(text: Any, limit: int = 180) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: max(0, limit - 3)].rstrip() + "..."


def normalize_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if value is None:
        return []
    text = str(value).strip()
    return [text] if text else []


def relative_path(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def web_path(rel_path: str) -> str:
    rel = str(rel_path or "").strip().lstrip("/")
    return f"/{quote(rel, safe='/')}" if rel else ""


def strip_frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        return text
    parts = text.split("\n---\n", 1)
    return parts[1] if len(parts) == 2 else text


def markdown_preview(path: Path, limit: int = 220) -> str:
    if not path.exists():
        return ""
    text = strip_frontmatter(path.read_text(encoding="utf-8"))
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or line.startswith("```"):
            continue
        lines.append(line)
        if len(" ".join(lines)) >= limit:
            break
    return compact_text(" ".join(lines), limit=limit)


def read_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _atomic_write_text(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False, dir=str(path.parent)) as handle:
        handle.write(text)
        temp_path = Path(handle.name)
    temp_path.replace(path)


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    text = json.dumps(payload, indent=2, ensure_ascii=False) + "\n"
    _atomic_write_text(path, text)


def write_text_atomic(path: Path, text: str) -> None:
    _atomic_write_text(path, text)


def default_build_status(project_root: Path) -> dict[str, Any]:
    return {
        "ok": False,
        "service": SERVICE_NAME,
        "project_root": str(project_root),
        "snapshot_version": "",
        "generated_at": "",
        "build_status": "missing",
        "last_error": "",
        "last_attempt_at": "",
        "last_success_at": "",
    }


def load_build_status(project_root: Path) -> dict[str, Any]:
    payload = read_json(build_status_path(project_root)) or {}
    status = default_build_status(project_root)
    status.update({key: value for key, value in payload.items() if key in status})
    return status


def inspect_browser_runtime(python_executable: str) -> dict[str, Any]:
    script = (
        "import importlib.util, json, sys\n"
        "mods = {name: bool(importlib.util.find_spec(name)) for name in ('yaml', 'watchdog')}\n"
        "print(json.dumps({\n"
        "  'python': sys.executable,\n"
        "  'version': sys.version.split()[0],\n"
        "  'yaml_support': mods['yaml'],\n"
        "  'watchdog_support': mods['watchdog'],\n"
        "}, ensure_ascii=False))\n"
    )
    completed = subprocess.run(
        [python_executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        return {
            "python": python_executable,
            "version": "",
            "yaml_support": False,
            "watchdog_support": False,
            "probe_error": completed.stderr.strip() or completed.stdout.strip() or "runtime probe failed",
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "python": python_executable,
            "version": "",
            "yaml_support": False,
            "watchdog_support": False,
            "probe_error": "runtime probe returned invalid json",
        }
    return payload


def choose_browser_runtime(project_root: Path) -> str:
    current = inspect_browser_runtime(sys.executable)
    if current.get("yaml_support") and current.get("watchdog_support"):
        return str(current.get("python") or sys.executable)
    preferred = preferred_runtime_record(project_root)
    if preferred:
        candidate = inspect_browser_runtime(str(preferred.get("python") or ""))
        if candidate.get("yaml_support") and candidate.get("watchdog_support"):
            return str(candidate.get("python") or "")
    missing = []
    if not current.get("yaml_support"):
        missing.append("PyYAML")
    if not current.get("watchdog_support"):
        missing.append("watchdog")
    lines = [
        (
            f"{SERVICE_NAME} needs a runtime with {', '.join(missing) or 'PyYAML and watchdog'}, "
            "but the current interpreter cannot provide it."
        ),
        f"Current python: {current.get('python', sys.executable)}",
    ]
    if preferred:
        lines.append(
            "A remembered runtime exists, but it does not appear to satisfy the browser requirements. "
            "Refresh it with `python3 .agents/skills/research-conductor/scripts/manage_workspace.py remember-runtime --python <path> --label research-default`."
        )
    else:
        lines.append(
            "No remembered runtime is stored yet. Register one with "
            "`python3 .agents/skills/research-conductor/scripts/manage_workspace.py remember-runtime --python <path> --label research-default`."
        )
    raise SystemExit("\n".join(lines))


def fetch_json(url: str, timeout: float = 0.6) -> dict[str, Any] | None:
    request = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None
    return payload if isinstance(payload, dict) else None


def port_is_busy(host: str, port: int, timeout: float = 0.2) -> bool:
    import socket

    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def is_matching_service(host: str, port: int, project_root: Path) -> bool:
    payload = fetch_json(health_url(host, port))
    return bool(
        payload
        and payload.get("ok") is True
        and payload.get("service") == SERVICE_NAME
        and payload.get("project_root") == str(project_root)
    )


def choose_port(host: str, preferred_port: int, project_root: Path) -> tuple[int, bool]:
    if is_matching_service(host, preferred_port, project_root):
        return preferred_port, True
    if not port_is_busy(host, preferred_port):
        return preferred_port, False
    for candidate in range(preferred_port + 1, preferred_port + PORT_SCAN_LIMIT + 1):
        if is_matching_service(host, candidate, project_root):
            return candidate, True
        if not port_is_busy(host, candidate):
            return candidate, False
    raise RuntimeError(f"Could not find a free knowledge-browser port near {preferred_port}.")


def wait_until_ready(host: str, port: int, project_root: Path, timeout_seconds: float = READY_TIMEOUT_SECONDS) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if is_matching_service(host, port, project_root):
            return
        time.sleep(POLL_INTERVAL_SECONDS)
    raise RuntimeError(f"{SERVICE_NAME} did not become ready within {timeout_seconds:.1f}s.")


def relative_link_payload(project_root: Path, rel_path: str) -> dict[str, str]:
    rel = str(rel_path or "").strip()
    return {
        "path": rel,
        "href": web_path(rel),
    }


def _max_timestamp(*values: str) -> str:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    return max(cleaned) if cleaned else ""


def _numeric_year(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _safe_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _load_if_exists(path: Path, default: Any | None = None) -> Any:
    return load_yaml(path, default=default)


def _collection_count(payload: Any, candidate_keys: list[str]) -> int:
    if isinstance(payload, list):
        return len(payload)
    if not isinstance(payload, dict):
        return 0
    for key in candidate_keys:
        value = payload.get(key)
        if isinstance(value, list):
            return len(value)
    return 0


def _idea_sort_key(item: dict[str, Any]) -> tuple[int, str, str]:
    status = str(item.get("status") or "")
    return (0 if status == "selected" else 1, str(item.get("updated_at") or ""), str(item.get("idea_id") or ""))


def build_workspace_profile(project_root: Path) -> dict[str, Any]:
    profile_path = research_root(project_root) / "memory" / "domain-profile.yaml"
    payload = _safe_dict(_load_if_exists(profile_path, {}))
    tagging = _safe_dict(payload.get("tagging"))
    repo_roles = _safe_dict(payload.get("repo_roles"))
    rules = tagging.get("rules", [])
    short_terms = normalize_list(_safe_dict(payload.get("tokenization")).get("short_terms"))
    return {
        "profile_name": str(payload.get("profile_name") or ""),
        "generated_at": str(payload.get("generated_at") or ""),
        "short_terms": short_terms,
        "tag_rule_count": len(rules) if isinstance(rules, list) else 0,
        "taxonomy_seed_count": len(_safe_dict(payload.get("taxonomy_seeds"))),
        "repo_role_count": len(repo_roles),
        "domain_profile_path": relative_path(project_root, profile_path),
        "domain_profile_href": web_path(relative_path(project_root, profile_path)),
    }


def build_literature_items(project_root: Path) -> list[dict[str, Any]]:
    index_path = research_root(project_root) / "library" / "literature" / "index.yaml"
    index = load_index(index_path, "literature-index", "research-kb-browser")
    items: list[dict[str, Any]] = []
    for source_id, row in index.get("items", {}).items():
        if not isinstance(row, dict):
            continue
        source_id = str(source_id)
        lit_root = research_root(project_root) / "library" / "literature" / source_id
        metadata_path = lit_root / "metadata.yaml"
        note_path = lit_root / "note.md"
        claims_path = lit_root / "claims.yaml"
        metadata = _safe_dict(_load_if_exists(metadata_path, {}))
        claims = _safe_dict(_load_if_exists(claims_path, {}))
        source_paths = _safe_dict(row.get("source_paths"))
        primary_pdf = str(source_paths.get("primary_pdf") or "")
        landing_html = str(source_paths.get("landing_html") or "")
        items.append(
            {
                "source_id": source_id,
                "title": str(row.get("canonical_title") or metadata.get("canonical_title") or source_id),
                "year": _numeric_year(row.get("year") or metadata.get("year")),
                "authors": normalize_list(row.get("authors") or metadata.get("authors")),
                "short_summary": str(row.get("short_summary") or metadata.get("short_summary") or ""),
                "source_kind": str(row.get("source_kind") or metadata.get("source_kind") or ""),
                "canonical_url": str(row.get("canonical_url") or metadata.get("canonical_url") or ""),
                "site_fingerprint": str(row.get("site_fingerprint") or metadata.get("site_fingerprint") or ""),
                "tags": normalize_list(row.get("tags") or metadata.get("tags")),
                "topics": normalize_list(row.get("topics") or metadata.get("topics")),
                "external_ids": _safe_dict(row.get("external_ids") or metadata.get("external_ids")),
                "claims_status": str(claims.get("claim_status") or claims.get("status") or ""),
                "claims_usage_guidance": compact_text(claims.get("usage_guidance", ""), limit=220),
                "note_preview": markdown_preview(note_path),
                "links": {
                    "metadata": relative_link_payload(project_root, relative_path(project_root, metadata_path)),
                    "note": relative_link_payload(project_root, relative_path(project_root, note_path)) if note_path.exists() else {"path": "", "href": ""},
                    "claims": relative_link_payload(project_root, relative_path(project_root, claims_path)) if claims_path.exists() else {"path": "", "href": ""},
                    "primary_pdf": relative_link_payload(project_root, primary_pdf) if primary_pdf else {"path": "", "href": ""},
                    "landing_html": relative_link_payload(project_root, landing_html) if landing_html else {"path": "", "href": ""},
                },
                "generated_at": _max_timestamp(str(metadata.get("generated_at") or ""), str(row.get("generated_at") or "")),
            }
        )
    items.sort(key=lambda item: (-int(item.get("year") or 0), str(item.get("title") or "").lower(), str(item.get("source_id") or "")))
    return items


def build_repo_items(project_root: Path) -> list[dict[str, Any]]:
    index_path = research_root(project_root) / "library" / "repos" / "index.yaml"
    index = load_index(index_path, "repo-index", "research-kb-browser")
    items: list[dict[str, Any]] = []
    for repo_id, row in index.get("items", {}).items():
        if not isinstance(row, dict):
            continue
        repo_id = str(repo_id)
        repo_root = research_root(project_root) / "library" / "repos" / repo_id
        summary_path = repo_root / "summary.yaml"
        notes_path = repo_root / "repo-notes.md"
        summary = _safe_dict(_load_if_exists(summary_path, {}))
        items.append(
            {
                "repo_id": repo_id,
                "repo_name": str(row.get("repo_name") or summary.get("repo_name") or repo_id),
                "short_summary": str(row.get("short_summary") or summary.get("short_summary") or ""),
                "canonical_remote": str(row.get("canonical_remote") or summary.get("canonical_remote") or ""),
                "owner_name": str(row.get("owner_name") or summary.get("owner_name") or ""),
                "import_type": str(row.get("import_type") or summary.get("import_type") or ""),
                "frameworks": normalize_list(row.get("frameworks") or summary.get("frameworks")),
                "entrypoints": normalize_list(row.get("entrypoints") or summary.get("entrypoints")),
                "tags": normalize_list(row.get("tags") or summary.get("tags")),
                "topics": normalize_list(row.get("topics") or summary.get("topics")),
                "links": {
                    "summary": relative_link_payload(project_root, relative_path(project_root, summary_path)) if summary_path.exists() else {"path": "", "href": ""},
                    "notes": relative_link_payload(project_root, relative_path(project_root, notes_path)) if notes_path.exists() else {"path": "", "href": ""},
                    "source": relative_link_payload(project_root, relative_path(project_root, repo_root / "source")) if (repo_root / "source").exists() else {"path": "", "href": ""},
                },
                "generated_at": _max_timestamp(str(summary.get("generated_at") or ""), str(row.get("generated_at") or "")),
            }
        )
    items.sort(key=lambda item: (str(item.get("repo_name") or "").lower(), str(item.get("repo_id") or "")))
    return items


def build_tag_items(project_root: Path, literature_items: list[dict[str, Any]], repo_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    taxonomy_path = research_root(project_root) / "library" / "literature" / "tag-taxonomy.yaml"
    taxonomy = _safe_dict(_load_if_exists(taxonomy_path, {}))
    taxonomy_items = _safe_dict(taxonomy.get("items"))
    all_tags = set(taxonomy_items.keys())
    for item in literature_items:
        all_tags.update(normalize_list(item.get("tags")))
    for item in repo_items:
        all_tags.update(normalize_list(item.get("tags")))
    tags: list[dict[str, Any]] = []
    for tag in sorted(all_tags):
        tax = _safe_dict(taxonomy_items.get(tag))
        related_literature = [item for item in literature_items if tag in normalize_list(item.get("tags"))]
        related_repos = [item for item in repo_items if tag in normalize_list(item.get("tags"))]
        tags.append(
            {
                "tag": tag,
                "canonical_tag": str(tax.get("canonical_tag") or tag),
                "aliases": normalize_list(tax.get("aliases")),
                "description": str(tax.get("description") or ""),
                "topic_hints": normalize_list(tax.get("topic_hints")),
                "status": str(tax.get("status") or ("discovered" if tag not in taxonomy_items else "active")),
                "literature_count": len(related_literature),
                "repo_count": len(related_repos),
                "sample_literature": [
                    {"source_id": item["source_id"], "title": item["title"]}
                    for item in related_literature[:5]
                ],
                "sample_repos": [
                    {"repo_id": item["repo_id"], "repo_name": item["repo_name"]}
                    for item in related_repos[:5]
                ],
                "links": {
                    "taxonomy": relative_link_payload(project_root, relative_path(project_root, taxonomy_path)) if taxonomy_path.exists() else {"path": "", "href": ""},
                },
                "generated_at": str(taxonomy.get("generated_at") or ""),
            }
        )
    tags.sort(key=lambda item: (-(int(item.get("literature_count") or 0) + int(item.get("repo_count") or 0)), str(item.get("tag") or "")))
    return tags


def build_landscape_items(project_root: Path) -> list[dict[str, Any]]:
    landscapes_root = research_root(project_root) / "library" / "landscapes"
    items: list[dict[str, Any]] = []
    if not landscapes_root.exists():
        return items
    for directory in sorted(path for path in landscapes_root.iterdir() if path.is_dir()):
        report_path = directory / "landscape-report.yaml"
        summary_path = directory / "summary.md"
        report = _safe_dict(_load_if_exists(report_path, {}))
        if not report and not summary_path.exists():
            continue
        snapshot = _safe_dict(report.get("snapshot"))
        retrieval = _safe_dict(report.get("retrieval"))
        candidates = []
        for program in report.get("candidate_programs", []) or []:
            if not isinstance(program, dict):
                continue
            candidates.append(
                {
                    "program_seed_id": str(program.get("program_seed_id") or ""),
                    "suggested_program_id": str(program.get("suggested_program_id") or ""),
                    "title": str(program.get("title") or ""),
                    "question": compact_text(program.get("question", ""), limit=180),
                    "goal": compact_text(program.get("goal", ""), limit=180),
                    "why_now": compact_text(program.get("why_now", ""), limit=180),
                    "bootstrap_prompt": str(program.get("bootstrap_prompt") or ""),
                    "conductor_prompt": str(program.get("conductor_prompt") or ""),
                }
            )
        items.append(
            {
                "survey_id": str(report.get("id") or directory.name),
                "field": str(report.get("field") or directory.name),
                "scope": str(report.get("scope") or ""),
                "matched_literature_count": int(snapshot.get("matched_literature_count") or 0),
                "matched_repo_count": int(snapshot.get("matched_repo_count") or 0),
                "query_tags": normalize_list(retrieval.get("query_tags")),
                "summary_preview": markdown_preview(summary_path),
                "candidate_programs": candidates,
                "links": {
                    "report": relative_link_payload(project_root, relative_path(project_root, report_path)) if report_path.exists() else {"path": "", "href": ""},
                    "summary": relative_link_payload(project_root, relative_path(project_root, summary_path)) if summary_path.exists() else {"path": "", "href": ""},
                },
                "generated_at": str(report.get("generated_at") or ""),
            }
        )
    items.sort(key=lambda item: (str(item.get("generated_at") or ""), str(item.get("survey_id") or "")), reverse=True)
    return items


def _idea_entry(project_root: Path, program_root: Path, idea_id: str, row: dict[str, Any]) -> dict[str, Any]:
    proposal_path = program_root / "ideas" / idea_id / "proposal.yaml"
    review_path = program_root / "ideas" / idea_id / "review.yaml"
    decision_path = program_root / "ideas" / idea_id / "decision.yaml"
    proposal = _safe_dict(_load_if_exists(proposal_path, {}))
    review = _safe_dict(_load_if_exists(review_path, {}))
    decision = _safe_dict(_load_if_exists(decision_path, {}))
    repo_context = proposal.get("repo_context", []) if isinstance(proposal.get("repo_context"), list) else []
    repo_ids = [str(item.get("repo_id") or "") for item in repo_context[:3] if isinstance(item, dict) and str(item.get("repo_id") or "").strip()]
    return {
        "idea_id": idea_id,
        "title": str(proposal.get("title") or row.get("title") or idea_id),
        "status": str(decision.get("decision") or decision.get("status") or row.get("status") or ""),
        "recommended_bucket": str(decision.get("recommended_bucket") or row.get("recommended_bucket") or ""),
        "hypothesis": compact_text(proposal.get("core_hypothesis", ""), limit=180),
        "novelty_claim": compact_text(proposal.get("novelty_claim", ""), limit=180),
        "repo_ids": repo_ids,
        "review_recommendation": str(review.get("recommendation") or ""),
        "reason": compact_text(decision.get("reason", "") or review.get("failure_modes", {}), limit=180) if decision.get("reason") else "",
        "updated_at": str(row.get("updated_at") or decision.get("generated_at") or review.get("generated_at") or proposal.get("generated_at") or ""),
        "links": {
            "proposal": relative_link_payload(project_root, relative_path(project_root, proposal_path)) if proposal_path.exists() else {"path": "", "href": ""},
            "review": relative_link_payload(project_root, relative_path(project_root, review_path)) if review_path.exists() else {"path": "", "href": ""},
            "decision": relative_link_payload(project_root, relative_path(project_root, decision_path)) if decision_path.exists() else {"path": "", "href": ""},
        },
    }


def _selected_idea_id(state: dict[str, Any], ideas: list[dict[str, Any]]) -> str:
    selected = str(state.get("selected_idea_id") or "").strip()
    if selected:
        return selected
    for item in ideas:
        if str(item.get("status") or "") == "selected":
            return str(item.get("idea_id") or "")
    return ""


def build_program_items(project_root: Path) -> list[dict[str, Any]]:
    programs_root = research_root(project_root) / "programs"
    items: list[dict[str, Any]] = []
    if not programs_root.exists():
        return items
    for program_root in sorted(path for path in programs_root.iterdir() if path.is_dir()):
        program_id = program_root.name
        charter_path = program_root / "charter.yaml"
        state_path = program_root / "workflow" / "state.yaml"
        literature_map_path = program_root / "evidence" / "literature-map.yaml"
        ideas_index_path = program_root / "ideas" / "index.yaml"
        repo_choice_path = program_root / "design" / "repo-choice.yaml"
        design_doc_path = program_root / "design" / "system-design.md"
        interfaces_path = program_root / "design" / "interfaces.yaml"
        selected_idea_path = program_root / "design" / "selected-idea.yaml"
        runbook_path = program_root / "experiments" / "runbook.md"
        matrix_path = program_root / "experiments" / "matrix.yaml"
        decision_log_path = program_root / "workflow" / "decision-log.md"
        open_questions_path = program_root / "workflow" / "open-questions.yaml"
        evidence_requests_path = program_root / "workflow" / "evidence-requests.yaml"
        preferences_path = program_root / "workflow" / "preferences.yaml"
        charter = _safe_dict(_load_if_exists(charter_path, {}))
        state = _safe_dict(_load_if_exists(state_path, {}))
        literature_map = _safe_dict(_load_if_exists(literature_map_path, {}))
        ideas_index = load_index(ideas_index_path, f"{program_id}-ideas", "research-kb-browser")
        repo_choice = _safe_dict(_load_if_exists(repo_choice_path, {}))
        matrix = _safe_dict(_load_if_exists(matrix_path, {}))
        open_questions = _safe_dict(_load_if_exists(open_questions_path, {}))
        evidence_requests = _safe_dict(_load_if_exists(evidence_requests_path, {}))
        ideas: list[dict[str, Any]] = []
        for idea_id, row in ideas_index.get("items", {}).items():
            if not isinstance(row, dict):
                continue
            ideas.append(_idea_entry(project_root, program_root, str(idea_id), row))
        ideas.sort(key=_idea_sort_key)
        selected_id = _selected_idea_id(state, ideas)
        selected_idea = next((item for item in ideas if item.get("idea_id") == selected_id), {})
        retrieval = _safe_dict(literature_map.get("retrieval"))
        top_sources = []
        for source in retrieval.get("selected_sources", []) or []:
            if not isinstance(source, dict):
                continue
            top_sources.append(
                {
                    "source_id": str(source.get("source_id") or ""),
                    "title": str(source.get("title") or source.get("source_id") or ""),
                    "short_summary": compact_text(source.get("short_summary", ""), limit=180),
                    "score": source.get("score"),
                    "tags": normalize_list(source.get("tags")),
                    "topics": normalize_list(source.get("topics")),
                }
            )
        current_selected_repo = str(state.get("selected_repo_id") or repo_choice.get("selected_repo") or "")
        items.append(
            {
                "program_id": program_id,
                "question": str(charter.get("question") or ""),
                "goal": str(charter.get("goal") or ""),
                "stage": str(state.get("stage") or ""),
                "active_idea_id": str(state.get("active_idea_id") or ""),
                "selected_idea_id": selected_id,
                "selected_idea_title": str(selected_idea.get("title") or ""),
                "selected_repo_id": current_selected_repo,
                "selected_repo_summary": str(repo_choice.get("selected_repo_summary") or ""),
                "idea_count": len(ideas),
                "ideas": ideas,
                "top_sources": top_sources[:5],
                "design_preview": markdown_preview(design_doc_path),
                "runbook_preview": markdown_preview(runbook_path),
                "decision_log_preview": markdown_preview(decision_log_path),
                "open_question_count": _collection_count(open_questions, ["items", "questions", "open_questions"]),
                "evidence_request_count": _collection_count(evidence_requests, ["items", "requests", "evidence_requests"]),
                "experiment_count": _collection_count(matrix, ["items", "experiments", "rows", "entries", "matrix"]),
                "links": {
                    "charter": relative_link_payload(project_root, relative_path(project_root, charter_path)) if charter_path.exists() else {"path": "", "href": ""},
                    "state": relative_link_payload(project_root, relative_path(project_root, state_path)) if state_path.exists() else {"path": "", "href": ""},
                    "literature_map": relative_link_payload(project_root, relative_path(project_root, literature_map_path)) if literature_map_path.exists() else {"path": "", "href": ""},
                    "ideas_index": relative_link_payload(project_root, relative_path(project_root, ideas_index_path)) if ideas_index_path.exists() else {"path": "", "href": ""},
                    "repo_choice": relative_link_payload(project_root, relative_path(project_root, repo_choice_path)) if repo_choice_path.exists() else {"path": "", "href": ""},
                    "design_doc": relative_link_payload(project_root, relative_path(project_root, design_doc_path)) if design_doc_path.exists() else {"path": "", "href": ""},
                    "interfaces": relative_link_payload(project_root, relative_path(project_root, interfaces_path)) if interfaces_path.exists() else {"path": "", "href": ""},
                    "selected_idea": relative_link_payload(project_root, relative_path(project_root, selected_idea_path)) if selected_idea_path.exists() else {"path": "", "href": ""},
                    "runbook": relative_link_payload(project_root, relative_path(project_root, runbook_path)) if runbook_path.exists() else {"path": "", "href": ""},
                    "matrix": relative_link_payload(project_root, relative_path(project_root, matrix_path)) if matrix_path.exists() else {"path": "", "href": ""},
                    "decision_log": relative_link_payload(project_root, relative_path(project_root, decision_log_path)) if decision_log_path.exists() else {"path": "", "href": ""},
                    "open_questions": relative_link_payload(project_root, relative_path(project_root, open_questions_path)) if open_questions_path.exists() else {"path": "", "href": ""},
                    "evidence_requests": relative_link_payload(project_root, relative_path(project_root, evidence_requests_path)) if evidence_requests_path.exists() else {"path": "", "href": ""},
                    "preferences": relative_link_payload(project_root, relative_path(project_root, preferences_path)) if preferences_path.exists() else {"path": "", "href": ""},
                },
                "generated_at": _max_timestamp(
                    str(charter.get("generated_at") or ""),
                    str(state.get("generated_at") or ""),
                    str(literature_map.get("generated_at") or ""),
                    str(ideas_index.get("generated_at") or ""),
                    str(repo_choice.get("generated_at") or ""),
                    str(matrix.get("generated_at") or ""),
                    str(open_questions.get("generated_at") or ""),
                    str(evidence_requests.get("generated_at") or ""),
                ),
            }
        )
    items.sort(key=lambda item: (str(item.get("generated_at") or ""), str(item.get("program_id") or "")), reverse=True)
    return items


def build_snapshot_payload(project_root: Path) -> dict[str, Any]:
    ensure_research_runtime(project_root, SERVICE_NAME)
    profile = build_workspace_profile(project_root)
    literature_items = build_literature_items(project_root)
    repo_items = build_repo_items(project_root)
    tag_items = build_tag_items(project_root, literature_items, repo_items)
    landscape_items = build_landscape_items(project_root)
    program_items = build_program_items(project_root)
    generated_at = utc_now_iso()
    snapshot_version = generated_at
    last_updated = _max_timestamp(
        generated_at,
        str(profile.get("generated_at") or ""),
        *[str(item.get("generated_at") or "") for item in literature_items[:5]],
        *[str(item.get("generated_at") or "") for item in repo_items[:5]],
        *[str(item.get("generated_at") or "") for item in landscape_items[:5]],
        *[str(item.get("generated_at") or "") for item in program_items[:5]],
    )
    return {
        "service": SERVICE_NAME,
        "project_root": str(project_root),
        "project_name": project_root.name,
        "generated_at": generated_at,
        "snapshot_version": snapshot_version,
        "last_updated": last_updated,
        "workspace_profile": profile,
        "global_stats": {
            "literature_count": len(literature_items),
            "repo_count": len(repo_items),
            "tag_count": len(tag_items),
            "landscape_count": len(landscape_items),
            "program_count": len(program_items),
            "selected_program_count": sum(1 for item in program_items if item.get("selected_idea_id")),
        },
        "literature_items": literature_items,
        "repo_items": repo_items,
        "tag_items": tag_items,
        "landscape_items": landscape_items,
        "program_items": program_items,
    }


def install_static_assets(project_root: Path, *, script_path: Path) -> None:
    skill_root = skill_root_from_script(script_path)
    assets_root = skill_root / "assets" / "ui"
    output_root = kb_root(project_root)
    output_assets = kb_assets_root(project_root)
    ensure_dir(output_assets)
    replacements = {
        "{{PAGE_TITLE}}": f"{project_root.name} 研究知识库浏览器",
        "{{VERSION_POLL_MS}}": str(SNAPSHOT_POLL_MS),
    }
    template_text = (assets_root / "index-template.html").read_text(encoding="utf-8")
    for key, value in replacements.items():
        template_text = template_text.replace(key, value)
    write_text_atomic(output_root / "index.html", template_text)
    for file_name in ("kb.css", "kb.js"):
        source = (assets_root / file_name).read_text(encoding="utf-8")
        write_text_atomic(output_assets / file_name, source)


def write_snapshot(project_root: Path, snapshot: dict[str, Any]) -> None:
    write_json_atomic(snapshot_path(project_root), snapshot)


def write_success_status(project_root: Path, snapshot: dict[str, Any]) -> dict[str, Any]:
    status = {
        "ok": True,
        "service": SERVICE_NAME,
        "project_root": str(project_root),
        "snapshot_version": str(snapshot.get("snapshot_version") or ""),
        "generated_at": str(snapshot.get("generated_at") or ""),
        "build_status": "ready",
        "last_error": "",
        "last_attempt_at": utc_now_iso(),
        "last_success_at": str(snapshot.get("generated_at") or ""),
    }
    write_json_atomic(build_status_path(project_root), status)
    return status


def write_failure_status(project_root: Path, error: Exception) -> dict[str, Any]:
    previous = load_build_status(project_root)
    has_snapshot = snapshot_path(project_root).exists()
    status = {
        "ok": has_snapshot,
        "service": SERVICE_NAME,
        "project_root": str(project_root),
        "snapshot_version": str(previous.get("snapshot_version") or ""),
        "generated_at": str(previous.get("generated_at") or ""),
        "build_status": "stale" if has_snapshot else "failed",
        "last_error": compact_text(f"{type(error).__name__}: {error}", limit=380),
        "last_attempt_at": utc_now_iso(),
        "last_success_at": str(previous.get("last_success_at") or previous.get("generated_at") or ""),
    }
    write_json_atomic(build_status_path(project_root), status)
    return status


def build_site_once(project_root: Path, *, script_path: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = build_snapshot_payload(project_root)
    install_static_assets(project_root, script_path=script_path)
    write_snapshot(project_root, snapshot)
    status = write_success_status(project_root, snapshot)
    return snapshot, status


def safe_rebuild(project_root: Path, *, script_path: Path) -> dict[str, Any]:
    try:
        _, status = build_site_once(project_root, script_path=script_path)
        return status
    except Exception as exc:  # noqa: BLE001
        return write_failure_status(project_root, exc)
