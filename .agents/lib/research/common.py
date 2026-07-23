from __future__ import annotations

import copy
import fcntl
import hashlib
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from html import unescape
from pathlib import Path
from shlex import quote
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .dedup import canonicalize_url, normalize_remote_url, parse_arxiv_id
from .slugs import KEYWORD_BLACKLIST, STOPWORDS, normalize_list, normalize_person_name, normalize_ref_key, normalize_title, parse_wikilinks, simple_slug, slugify, slugify_tag
from .yaml_io import dump_yaml, load_yaml, write_text_if_changed, write_yaml_if_changed, yaml_duplicate_key_issues


RUNTIME_MODULES = ("yaml", "markdownify", "bs4", "pymupdf4llm", "fitz", "PyPDF2", "pypdf")
COMMAND_PREFIX = "${RESEARCH_PYTHON:-python3}"
CONFIRM_SCRIPT_BY_KIND = {
    "paper": ".agents/skills/paper-analyst/scripts/paper.py",
    "repo": ".agents/skills/repo-analyst/scripts/repo.py",
    "dataset": ".agents/skills/dataset-analyst/scripts/dataset.py",
    "blog": ".agents/skills/blog-analyst/scripts/blog.py",
    "experiment": ".agents/skills/experiment-workbench/scripts/experiment.py",
}
CONFIRM_ID_ARG_BY_KIND = {
    "paper": "--paper-id",
    "repo": "--repo-id",
    "dataset": "--dataset-id",
    "blog": "--blog-id",
    "experiment": "--experiment-id",
}


def shell_command(parts: list[str], *, command_prefix: str = COMMAND_PREFIX) -> str:
    rendered: list[str] = []
    preserve_command_prefix = command_prefix if command_prefix.startswith("${") and command_prefix.endswith("}") else ""
    for index, part in enumerate(parts):
        text = str(part)
        if (index == 0 and preserve_command_prefix and text == preserve_command_prefix) or (text.startswith("${") and text.endswith("}")):
            rendered.append(text)
        else:
            rendered.append(quote(text))
    return " ".join(rendered)


def confirm_command(
    record: dict[str, Any],
    *,
    command_prefix: str = COMMAND_PREFIX,
    direct_kinds: tuple[str, ...] | None = None,
) -> str:
    kind = str(record.get("kind") or "")
    unit_id = str(record.get("id") or "")
    direct_kind_set = set(CONFIRM_SCRIPT_BY_KIND) if direct_kinds is None else set(direct_kinds)
    if kind in direct_kind_set and kind in CONFIRM_SCRIPT_BY_KIND:
        script = skill_script_for_command(CONFIRM_SCRIPT_BY_KIND[kind])
        return shell_command(
            [
                command_prefix,
                script,
                "confirm",
                CONFIRM_ID_ARG_BY_KIND[kind],
                unit_id,
                "--confirmed-by",
                "${RESEARCH_CONFIRMED_BY:?set-human-identity}",
                "--evidence",
                "${RESEARCH_CONFIRM_EVIDENCE:?set-human-evidence}",
            ],
            command_prefix=command_prefix,
        )
    return shell_command(
        [
            command_prefix,
            skill_script_for_command(".agents/skills/knowledge-base-manager/scripts/kb.py"),
            "promote",
            "--id",
            unit_id,
            "--confirmation-status",
            "confirmed",
            "--confirmed-by",
            "${RESEARCH_CONFIRMED_BY:?set-human-identity}",
            "--evidence",
            "${RESEARCH_CONFIRM_EVIDENCE:?set-human-evidence}",
        ],
        command_prefix=command_prefix,
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def find_project_root(start: Path | None = None, *, explicit_root: str | Path | None = None) -> Path:
    explicit = str(explicit_root or os.getenv("RESEARCH_PROJECT_ROOT") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    current = (start or Path.cwd()).resolve()
    for candidate in [current] + list(current.parents):
        if (candidate / ".agents").exists() and (
            (candidate / "AGENTS.md").exists()
            or (candidate / "README.md").exists()
            or (candidate / "kb").exists()
            or (candidate / "docs").exists()
            or (candidate / "doc").exists()
        ):
            return candidate
    raise FileNotFoundError(f"Could not locate project root from {current}")


def skills_root(start: Path | None = None, *, explicit_home: str | Path | None = None) -> Path:
    explicit = str(explicit_home or os.getenv("RESEARCH_SKILLS_HOME") or "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    current = (start or Path(__file__)).resolve()
    search_from = current if current.is_dir() else current.parent
    for candidate in [search_from] + list(search_from.parents):
        if (candidate / ".agents" / "skills").exists():
            return candidate
    raise FileNotFoundError(f"Could not locate skills root from {current}")


def skill_script_for_command(relative_path: str, *, cwd: Path | None = None) -> str:
    if str(os.getenv("RESEARCH_SKILLS_HOME") or "").strip():
        return (skills_root() / relative_path).as_posix()
    local_script = (cwd or Path.cwd()) / relative_path
    if local_script.exists():
        return relative_path
    try:
        installed_script = skills_root() / relative_path
    except FileNotFoundError:
        return relative_path
    if installed_script.exists():
        return installed_script.as_posix()
    return relative_path


def add_project_root_argument(parser: Any) -> None:
    parser.add_argument(
        "--root",
        default="",
        help="Explicit project root (overrides RESEARCH_PROJECT_ROOT and auto-discovery).",
    )


def print_resolved_project_roots(project_root: Path) -> None:
    print(f"[root] project: {project_root.resolve()}")
    print(f"[root] kb: {research_root(project_root).resolve()}")


def warn_if_cwd_differs_from_project_root(project_root: Path, *, command: str) -> None:
    cwd = Path.cwd().resolve()
    root = project_root.resolve()
    if cwd != root:
        print(f"[warn] {command}: cwd differs from resolved project root")
        print(f"[warn] cwd: {cwd}")
        print(f"[warn] project root: {root}")


def research_root(project_root: Path) -> Path:
    kb_root = project_root / "kb"
    legacy_root = project_root / "doc" / "research"
    if kb_root.exists():
        return kb_root
    if legacy_root.exists():
        return legacy_root
    return kb_root


def program_root(project_root: Path, program_id: str) -> Path:
    return research_root(project_root) / "programs" / program_id


def raw_root(project_root: Path) -> Path:
    return research_root(project_root) / "raw"


def output_root(project_root: Path) -> Path:
    return research_root(project_root) / "output"


def runtime_memory_path(project_root: Path) -> Path:
    return research_root(project_root) / "memory" / "runtime-environments.yaml"


def domain_profile_path(project_root: Path) -> Path:
    return research_root(project_root) / "memory" / "domain-profile.yaml"


def blank_runtime_registry(generated_by: str = "research-config-manager") -> dict[str, Any]:
    return {
        **yaml_default("runtime-environments", generated_by, status="active", confidence=0.9),
        "preferred_runtime_id": "",
        "items": {},
        "history": [],
    }


def blank_domain_profile(generated_by: str = "research-config-manager") -> dict[str, Any]:
    return {
        **yaml_default("domain-profile", generated_by, status="active", confidence=0.85),
        "profile_name": "",
        "tokenization": {"short_terms": []},
        "tagging": {"rules": []},
        "taxonomy_seeds": {},
        "repo_roles": {},
    }


def yaml_default(doc_id: str, generated_by: str, status: str = "ready", confidence: float = 1.0) -> dict[str, Any]:
    return {
        "id": doc_id,
        "status": status,
        "generated_by": generated_by,
        "generated_at": utc_now_iso(),
        "inputs": [],
        "confidence": confidence,
    }


def parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    normalized = text.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


_FILE_LOCK_GUARD = threading.Lock()
_FILE_THREAD_LOCKS: dict[str, threading.RLock] = {}
_FILE_LOCK_LOCAL = threading.local()


def _in_process_file_lock(key: str) -> threading.RLock:
    with _FILE_LOCK_GUARD:
        return _FILE_THREAD_LOCKS.setdefault(key, threading.RLock())


@contextmanager
def exclusive_file_lock(path: Path):
    """Cross-process file lock that is reentrant within the current thread."""
    ensure_dir(path.parent)
    key = path.resolve().as_posix()
    thread_lock = _in_process_file_lock(key)
    with thread_lock:
        held = getattr(_FILE_LOCK_LOCAL, "held", None)
        if held is None:
            held = {}
            _FILE_LOCK_LOCAL.held = held
        current = held.get(key)
        if current is not None:
            current["depth"] += 1
            try:
                yield current["handle"]
            finally:
                current["depth"] -= 1
            return

        with path.open("a+", encoding="utf-8") as handle:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            held[key] = {"handle": handle, "depth": 1}
            try:
                yield handle
            finally:
                held.pop(key, None)
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def program_lock_path(project_root: Path, program_id: str) -> Path:
    from .journal import operation_lock_path

    return operation_lock_path(project_root, program_root(project_root, program_id) / "state.yaml")


@contextmanager
def program_file_lock(project_root: Path, program_id: str):
    with exclusive_file_lock(program_lock_path(project_root, program_id)) as handle:
        yield handle


def first_author_key(authors: list[str]) -> str:
    if not authors:
        return ""
    tokens = normalize_person_name(authors[0]).split()
    return tokens[-1] if tokens else ""


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def is_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _resolved_project_root(project_root: Path | None = None) -> Path | None:
    if project_root is not None:
        return project_root.resolve()
    try:
        return find_project_root()
    except FileNotFoundError:
        return None


def _normalize_domain_tagging_rule(item: dict[str, Any]) -> dict[str, Any] | None:
    phrases = []
    for raw_value in item.get("phrases", []):
        phrase = normalize_title(str(raw_value))
        if phrase:
            phrases.append(phrase)
    topic = str(item.get("topic") or "").strip()
    tag = str(item.get("tag") or "").strip()
    if not phrases or (not topic and not tag):
        return None
    return {"phrases": sorted(set(phrases)), "topic": topic, "tag": tag}


def _normalize_domain_taxonomy_seed(canonical_tag: str, item: dict[str, Any]) -> dict[str, Any] | None:
    canonical = normalize_title(canonical_tag).replace(" ", "-").strip("-")
    if not canonical:
        return None
    aliases = sorted(
        {
            normalize_title(str(alias)).replace(" ", "-").strip("-")
            for alias in item.get("aliases", [])
            if normalize_title(str(alias)).replace(" ", "-").strip("-")
        }
    )
    topics = sorted({str(topic).strip() for topic in item.get("topic_hints", []) if str(topic).strip()})
    return {
        "canonical_tag": canonical,
        "aliases": [alias for alias in aliases if alias and alias != canonical],
        "topic_hints": topics,
        "description": str(item.get("description") or "").strip(),
        "status": str(item.get("status") or "active").strip() or "active",
    }


@lru_cache(maxsize=16)
def _load_domain_profile_cached(project_root_str: str) -> dict[str, Any]:
    project_root = Path(project_root_str)
    payload = load_yaml(domain_profile_path(project_root), default={})
    if not isinstance(payload, dict):
        payload = blank_domain_profile()
    payload.setdefault("id", "domain-profile")
    payload.setdefault("status", "active")
    payload.setdefault("generated_by", "research-config-manager")
    payload.setdefault("generated_at", utc_now_iso())
    payload.setdefault("inputs", [])
    payload.setdefault("confidence", 0.85)
    payload["profile_name"] = str(payload.get("profile_name") or "").strip()

    tokenization = payload.get("tokenization", {})
    tokenization = tokenization if isinstance(tokenization, dict) else {}
    tokenization["short_terms"] = sorted(
        {
            normalize_title(str(item)).replace(" ", "")
            for item in tokenization.get("short_terms", [])
            if normalize_title(str(item)).replace(" ", "")
        }
    )
    payload["tokenization"] = tokenization

    tagging = payload.get("tagging", {})
    tagging = tagging if isinstance(tagging, dict) else {}
    rules: list[dict[str, Any]] = []
    for item in tagging.get("rules", []):
        if not isinstance(item, dict):
            continue
        normalized = _normalize_domain_tagging_rule(item)
        if normalized:
            rules.append(normalized)
    tagging["rules"] = rules
    payload["tagging"] = tagging

    taxonomy_seeds = payload.get("taxonomy_seeds", {})
    normalized_seeds: dict[str, Any] = {}
    if isinstance(taxonomy_seeds, dict):
        for key, item in taxonomy_seeds.items():
            if not isinstance(item, dict):
                continue
            normalized = _normalize_domain_taxonomy_seed(str(key), item)
            if normalized:
                normalized_seeds[normalized["canonical_tag"]] = normalized
    payload["taxonomy_seeds"] = {key: normalized_seeds[key] for key in sorted(normalized_seeds)}

    repo_roles = payload.get("repo_roles", {})
    normalized_roles: dict[str, list[str]] = {}
    if isinstance(repo_roles, dict):
        for role_name, phrases in repo_roles.items():
            if not isinstance(phrases, list):
                continue
            cleaned = sorted({normalize_title(str(item)) for item in phrases if normalize_title(str(item))})
            if cleaned:
                normalized_roles[str(role_name).strip()] = cleaned
    payload["repo_roles"] = normalized_roles
    return payload


def load_domain_profile(project_root: Path | None = None) -> dict[str, Any]:
    resolved = _resolved_project_root(project_root)
    if resolved is None:
        return blank_domain_profile()
    return copy.deepcopy(_load_domain_profile_cached(str(resolved)))


def domain_short_terms(project_root: Path | None = None) -> set[str]:
    profile = load_domain_profile(project_root)
    tokenization = profile.get("tokenization", {})
    if not isinstance(tokenization, dict):
        return set()
    return {str(item).strip() for item in tokenization.get("short_terms", []) if str(item).strip()}


def domain_tagging_rules(project_root: Path | None = None) -> list[dict[str, Any]]:
    profile = load_domain_profile(project_root)
    tagging = profile.get("tagging", {})
    if not isinstance(tagging, dict):
        return []
    rules = tagging.get("rules", [])
    return [dict(item) for item in rules if isinstance(item, dict)]


def domain_taxonomy_seeds(project_root: Path | None = None) -> dict[str, Any]:
    profile = load_domain_profile(project_root)
    seeds = profile.get("taxonomy_seeds", {})
    return seeds if isinstance(seeds, dict) else {}


def domain_repo_roles(project_root: Path | None = None) -> dict[str, list[str]]:
    profile = load_domain_profile(project_root)
    repo_roles = profile.get("repo_roles", {})
    return repo_roles if isinstance(repo_roles, dict) else {}


def infer_repo_roles(text: str, *, project_root: Path | None = None) -> list[str]:
    normalized_text = normalize_title(text)
    roles = [
        role_name
        for role_name, phrases in domain_repo_roles(project_root).items()
        if any(phrase and phrase in normalized_text for phrase in phrases)
    ]
    return sorted(set(roles)) or ["general-stack"]


def infer_topics_and_tags(text: str, *, project_root: Path | None = None) -> tuple[list[str], list[str]]:
    lowered = normalize_title(text)
    topics: set[str] = set()
    tags: set[str] = set()
    for rule in domain_tagging_rules(project_root):
        phrases = rule.get("phrases", [])
        if any(phrase and phrase in lowered for phrase in phrases):
            topic = str(rule.get("topic") or "").strip()
            tag = str(rule.get("tag") or "").strip()
            if topic:
                topics.add(topic)
            if tag:
                tags.add(tag)
    if not topics:
        topics.add("uncategorized")
    if not tags:
        tags.add("research")
    return sorted(topics), sorted(tags)


class _FitzPageAdapter:
    def __init__(self, page: Any):
        self._page = page

    def extract_text(self) -> str:
        return str(self._page.get_text("text") or "")


class _FitzReaderAdapter:
    """Expose the small PdfReader interface used by legacy metadata helpers."""

    def __init__(self, path: str):
        import fitz  # type: ignore

        self._document = fitz.open(path)
        raw_metadata = dict(self._document.metadata or {})
        aliases = {
            "title": "Title",
            "author": "Author",
            "subject": "Subject",
            "keywords": "Keywords",
            "creator": "Creator",
            "producer": "Producer",
            "creationDate": "CreationDate",
            "modDate": "ModDate",
        }
        self.metadata = dict(raw_metadata)
        for source_key, target_key in aliases.items():
            if raw_metadata.get(source_key):
                self.metadata[target_key] = raw_metadata[source_key]
        self.pages = [_FitzPageAdapter(self._document[index]) for index in range(len(self._document))]


def pdf_backend() -> Any:
    try:
        import fitz  # type: ignore  # noqa: F401

        return _FitzReaderAdapter
    except ModuleNotFoundError:
        pass
    try:
        from PyPDF2 import PdfReader  # type: ignore

        return PdfReader
    except ModuleNotFoundError:
        try:
            from pypdf import PdfReader  # type: ignore

            return PdfReader
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "PDF parsing requires pymupdf4llm/fitz, PyPDF2, or pypdf in the active research runtime."
            ) from exc


def current_runtime_capabilities() -> dict[str, Any]:
    module_status = {name: importlib.util.find_spec(name) is not None for name in RUNTIME_MODULES}
    pdf_backend_name = (
        "pymupdf4llm"
        if module_status["pymupdf4llm"] and module_status["fitz"]
        else (
            "fitz"
            if module_status["fitz"]
            else ("PyPDF2" if module_status["PyPDF2"] else ("pypdf" if module_status["pypdf"] else ""))
        )
    )
    return {
        "python": sys.executable,
        "version": sys.version.split()[0],
        "modules": module_status,
        "yaml_support": module_status["yaml"],
        "markdown_support": module_status["markdownify"] and module_status["bs4"],
        "pdf_support": bool(pdf_backend_name),
        "pdf_backend": pdf_backend_name,
    }


def inspect_python_runtime(python_executable: str) -> dict[str, Any]:
    script = (
        "import importlib.util, json, sys\n"
        "mods = {name: bool(importlib.util.find_spec(name)) for name in ('yaml', 'markdownify', 'bs4', 'pymupdf4llm', 'fitz', 'PyPDF2', 'pypdf')}\n"
        "backend = ('pymupdf4llm' if mods['pymupdf4llm'] and mods['fitz'] else "
        "('fitz' if mods['fitz'] else ('PyPDF2' if mods['PyPDF2'] else ('pypdf' if mods['pypdf'] else ''))))\n"
        "print(json.dumps({\n"
        "    'python': sys.executable,\n"
        "    'version': sys.version.split()[0],\n"
        "    'modules': mods,\n"
        "    'yaml_support': mods['yaml'],\n"
        "    'markdown_support': mods['markdownify'] and mods['bs4'],\n"
        "    'pdf_support': bool(backend),\n"
        "    'pdf_backend': backend,\n"
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
            "modules": {name: False for name in RUNTIME_MODULES},
            "yaml_support": False,
            "markdown_support": False,
            "pdf_support": False,
            "pdf_backend": "",
            "probe_error": clean_text(completed.stderr or completed.stdout or "unknown runtime probe failure"),
        }
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        return {
            "python": python_executable,
            "version": "",
            "modules": {name: False for name in RUNTIME_MODULES},
            "yaml_support": False,
            "markdown_support": False,
            "pdf_support": False,
            "pdf_backend": "",
            "probe_error": clean_text(completed.stdout or "runtime probe returned invalid JSON"),
        }
    return payload


def _coerce_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if value is None or value == "":
        return []
    if isinstance(value, tuple):
        return list(value)
    return [value]


def load_runtime_registry(project_root: Path) -> dict[str, Any]:
    payload = load_yaml(runtime_memory_path(project_root), default={})
    if not isinstance(payload, dict):
        payload = blank_runtime_registry()
    payload.setdefault("id", "runtime-environments")
    payload.setdefault("status", "active")
    payload.setdefault("generated_by", "research-config-manager")
    payload.setdefault("generated_at", utc_now_iso())
    payload["inputs"] = [str(item) for item in _coerce_list(payload.get("inputs")) if str(item).strip()]
    payload["confidence"] = float(payload.get("confidence", 0.9) or 0.9)
    payload["preferred_runtime_id"] = str(payload.get("preferred_runtime_id") or "")
    payload["history"] = [item for item in _coerce_list(payload.get("history")) if isinstance(item, dict)]
    items = payload.get("items", {})
    payload["items"] = items if isinstance(items, dict) else {}
    for runtime_id, record in list(payload["items"].items()):
        if not isinstance(record, dict):
            payload["items"].pop(runtime_id, None)
            continue
        record.setdefault("runtime_id", str(runtime_id))
        record.setdefault("label", str(record.get("runtime_id") or runtime_id))
        record.setdefault("python", "")
        record.setdefault("version", "")
        modules = record.get("modules", {})
        record["modules"] = modules if isinstance(modules, dict) else {}
        record["yaml_support"] = bool(record.get("yaml_support"))
        record["markdown_support"] = bool(record.get("markdown_support"))
        record["pdf_support"] = bool(record.get("pdf_support"))
        record["pdf_backend"] = str(record.get("pdf_backend") or "")
        record["captured_at"] = str(record.get("captured_at") or "")
        record["notes"] = str(record.get("notes") or "")
    return payload


def preferred_runtime_record(project_root: Path) -> dict[str, Any] | None:
    registry = load_runtime_registry(project_root)
    runtime_id = registry.get("preferred_runtime_id", "")
    if runtime_id and runtime_id in registry["items"]:
        return registry["items"][runtime_id]
    return None


def ensure_research_runtime(project_root: Path, skill_name: str, *, require_pdf_backend: bool = False) -> None:
    capabilities = current_runtime_capabilities()
    missing: list[str] = []
    if not capabilities["yaml_support"]:
        missing.append("PyYAML")
    if not capabilities.get("markdown_support"):
        missing.append("Markdown source conversion")
    if require_pdf_backend and not capabilities["pdf_support"]:
        missing.append("PyPDF2 or pypdf")
    if not missing:
        return
    preferred = preferred_runtime_record(project_root)
    lines = [
        (
            f"{skill_name} requires a stable research runtime, but the current interpreter is missing: "
            f"{', '.join(missing)}."
        ),
        f"Current python: {capabilities['python']}",
        f"Current version: {capabilities['version']}",
        (
            "Current capabilities: "
            f"yaml={capabilities['yaml_support']}, "
            f"markdown={capabilities.get('markdown_support', False)}, "
            f"pdf={capabilities['pdf_support']} ({capabilities['pdf_backend'] or 'missing'})"
        ),
    ]
    if preferred:
        lines.extend(
            [
                (
                    f"Remembered preferred runtime: {preferred.get('label', '') or preferred.get('runtime_id', '')} "
                    f"at {preferred.get('python', '')}"
                ),
                (
                    "Retry with the remembered interpreter or update your environment to point "
                    "at a Python runtime with the missing modules."
                ),
            ]
        )
    else:
        lines.extend(
            [
                "No remembered research runtime is stored yet.",
                (
                    "Set RESEARCH_PYTHON or run the command with a Python interpreter that has "
                    "the missing modules installed."
                ),
            ]
        )
    raise SystemExit("\n".join(lines))


def clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = text.replace("\u200b", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _normalize_pdf_metadata(reader: Any) -> dict[str, str]:
    metadata = reader.metadata or {}
    normalized: dict[str, str] = {}
    for key, value in metadata.items():
        normalized[str(key).lstrip("/")] = clean_text(str(value))
    return normalized


def _extract_pdf_pages(reader: Any, limit: int = 4) -> list[str]:
    pages: list[str] = []
    for idx in range(min(limit, len(reader.pages))):
        try:
            text = reader.pages[idx].extract_text() or ""
        except Exception:
            text = ""
        pages.append(clean_text(text))
    return pages


def extract_pdf_context_pages(
    pdf_path: Path,
    *,
    front_limit: int = 8,
    back_limit: int = 4,
    per_page_char_limit: int = 4000,
) -> dict[str, Any]:
    reader_backend = pdf_backend()
    reader = reader_backend(str(pdf_path))
    total_pages = len(reader.pages)
    selected_indices: list[int] = list(range(min(front_limit, total_pages)))
    if back_limit > 0 and total_pages > front_limit:
        selected_indices.extend(range(max(front_limit, total_pages - back_limit), total_pages))

    pages: list[dict[str, Any]] = []
    seen: set[int] = set()
    for idx in selected_indices:
        if idx in seen or idx < 0 or idx >= total_pages:
            continue
        seen.add(idx)
        try:
            raw_text = reader.pages[idx].extract_text() or ""
        except Exception:
            raw_text = ""
        text = clean_text(raw_text)
        if not text:
            continue
        if per_page_char_limit and len(text) > per_page_char_limit:
            trimmed = text[:per_page_char_limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
            text = f"{trimmed or text[:per_page_char_limit]}..."
        pages.append(
            {
                "page": idx + 1,
                "text": text,
            }
        )

    return {
        "total_pages": total_pages,
        "pages": pages,
    }


def _parse_authors(raw: str) -> list[str]:
    if not raw:
        return []
    normalized = raw.replace(" and ", ";")
    if ";" not in normalized:
        normalized = normalized.replace(",", ";")
    names: list[str] = []
    seen: set[str] = set()
    for chunk in normalized.split(";"):
        name = clean_text(re.sub(r"[\d*†‡§¶]+", " ", chunk))
        if not name:
            continue
        if name not in seen:
            seen.add(name)
            names.append(name)
    return names[:20]


def _pdf_page_lines(text: str) -> list[str]:
    cleaned = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", text.replace("\r", "\n"))
    return [clean_text(line) for line in cleaned.splitlines() if clean_text(line)]


def _looks_like_author_line(line: str) -> bool:
    lowered = line.lower()
    if any(token in lowered for token in ("abstract", "university", "institute", "department", "correspondence", "proceedings", "http", "www.", "@")):
        return False
    if len(line.split()) < 2:
        return False
    if not (re.search(r"[,;]", line) or " and " in lowered or re.search(r"[A-Za-z][*∗†‡]?,\d", line)):
        return False
    if not re.search(r"\d", line) and any(token in lowered.split() for token in ("for", "with", "using", "from", "via", "toward", "towards", "into")):
        return False
    cleaned = re.sub(r"[\d*†‡§¶,.;()/]", " ", line)
    tokens = [token for token in cleaned.split() if token]
    capitalized = sum(1 for token in tokens if re.fullmatch(r"[A-Z][A-Za-z'`.-]+", token))
    return capitalized >= 2


def _looks_like_affiliation_line(line: str) -> bool:
    lowered = line.lower()
    return any(
        token in lowered
        for token in (
            "university",
            "institute",
            "department",
            "laboratory",
            "lab",
            "school",
            "college",
            "correspondence",
            "proceedings",
            "physical intelligence",
            "uc berkeley",
            "stanford",
            "california, berkeley",
        )
    )


def _title_lines_from_pdf(metadata: dict[str, str], pages: list[str], fallback: str) -> list[str]:
    embedded = clean_text(metadata.get("Title", ""))
    if len(embedded.split()) >= 3:
        return [embedded]
    first_page = pages[0] if pages else fallback
    lines = _pdf_page_lines(first_page)
    title_lines: list[str] = []
    for line in lines[:16]:
        lowered = line.lower()
        if "abstract" in lowered:
            break
        if title_lines and (_looks_like_author_line(line) or _looks_like_affiliation_line(line) or "http" in lowered or "arxiv:" in lowered):
            break
        if not title_lines and (_looks_like_author_line(line) or _looks_like_affiliation_line(line)):
            continue
        if 1 <= len(line.split()) <= 18:
            title_lines.append(line)
            if len(title_lines) >= 3:
                break
    if title_lines:
        return title_lines
    return [fallback.replace("_", " ").replace("-", " ")]


def _guess_pdf_year(metadata: dict[str, str], pages: list[str], file_name: str) -> int | None:
    for key in ("CreationDate", "ModDate"):
        value = metadata.get(key, "")
        match = re.search(r"D:(\d{4})", value)
        if match:
            return int(match.group(1))
    arxiv_id = parse_arxiv_id(file_name)
    if arxiv_id:
        return 2000 + int(arxiv_id[:2])
    combined = "\n".join(pages[:2])
    match = re.search(r"\b(20\d{2})\b", combined)
    if match:
        return int(match.group(1))
    return None


def _is_probable_person_name(name: str) -> bool:
    lowered = name.lower()
    if any(
        token in lowered
        for token in (
            "university",
            "institute",
            "department",
            "laboratory",
            "lab",
            "school",
            "college",
            "correspondence",
            "proceedings",
            "conference",
            "physical intelligence",
            "berkeley",
            "stanford",
        )
    ):
        return False
    if re.search(r"\d", name):
        return False
    tokens = [token for token in name.split() if token]
    if not 2 <= len(tokens) <= 5:
        return False
    capitalized = sum(1 for token in tokens if re.fullmatch(r"[A-Z][A-Za-z'`.-]+", token))
    return capitalized >= 2


def _guess_pdf_authors(metadata: dict[str, str], pages: list[str], title_lines: list[str]) -> list[str]:
    metadata_authors = _parse_authors(metadata.get("Author", ""))
    if metadata_authors:
        return metadata_authors
    first_page = pages[0] if pages else ""
    lines = _pdf_page_lines(first_page)
    skip = min(len(title_lines), len(lines))
    block_lines: list[str] = []
    for line in lines[skip: skip + 12]:
        lowered = line.lower()
        if "abstract" in lowered:
            break
        if _looks_like_affiliation_line(line):
            continue
        if "http" in lowered or "www." in lowered or "@" in lowered or lowered.startswith("arxiv:"):
            continue
        block_lines.append(line)
    block = "\n".join(block_lines)
    block = re.sub(r"https?://\S+|www\.\S+|\S+@\S+", " ", block)
    block = re.sub(r"(?<=\d)\s+(?=[A-Z])", "; ", block)
    block = re.sub(r"(?<=\d)(?=[A-Z])", "; ", block)
    block = re.sub(r"[\d*∗†‡§¶]+", " ", block)
    block = block.replace(" and ", "; ")
    block = block.replace(",", ";")
    candidates: list[str] = []
    seen: set[str] = set()
    for chunk in re.split(r"[;\n]+", block):
        name = clean_text(chunk)
        if not name or not _is_probable_person_name(name):
            continue
        if name not in seen:
            seen.add(name)
            candidates.append(name)
    return candidates[:20]


def _is_intro_heading(line: str) -> bool:
    compact = re.sub(r"[^a-z]", "", line.lower())
    return compact.endswith("introduction") or compact in {"introduction", "background"}


def _normalize_abstract_text(text: str) -> str:
    normalized = text.replace("\r", "\n")
    normalized = re.sub(r"(?<=\w)-\s*\n\s*(?=\w)", "", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return clean_text(normalized)


def _guess_pdf_abstract(pages: list[str], title_lines: list[str]) -> str:
    lines: list[str] = []
    for page in pages[:2]:
        lines.extend(_pdf_page_lines(page))

    collected: list[str] = []
    in_abstract = False
    for line in lines[:240]:
        if not in_abstract:
            if re.match(r"(?i)^abstract\b", line):
                in_abstract = True
                remainder = re.sub(r"(?i)^abstract\b\s*[:\-\u2013\u2014 ]*", "", line).strip()
                if remainder:
                    collected.append(remainder)
            continue
        if _is_intro_heading(line):
            break
        if re.search(r"(?i)\b(correspondence|proceedings of the|copyright)\b", line):
            continue
        collected.append(line)
        if sum(len(item) for item in collected) >= 2400:
            break

    if collected:
        return _normalize_abstract_text(" ".join(collected))[:2000]

    fallback_lines: list[str] = []
    skip = len(title_lines)
    for line in lines[skip:]:
        if _is_intro_heading(line):
            break
        if _looks_like_author_line(line) or _looks_like_affiliation_line(line):
            continue
        if "http" in line.lower() or "www." in line.lower() or "@" in line:
            continue
        fallback_lines.append(line)
        if sum(len(item) for item in fallback_lines) >= 1800:
            break
    return _normalize_abstract_text(" ".join(fallback_lines))[:1800]


def extract_pdf_record(pdf_path: Path) -> dict[str, Any]:
    reader_backend = pdf_backend()
    reader = reader_backend(str(pdf_path))
    metadata = _normalize_pdf_metadata(reader)
    pages = _extract_pdf_pages(reader, limit=4)
    title_lines = _title_lines_from_pdf(metadata, pages, pdf_path.stem)
    title = clean_text(" ".join(title_lines))
    authors = _guess_pdf_authors(metadata, pages, title_lines)
    abstract = _guess_pdf_abstract(pages, title_lines)
    arxiv_id = parse_arxiv_id(
        "\n".join(
            [
                pdf_path.name,
                metadata.get("Subject", ""),
                metadata.get("Title", ""),
                metadata.get("arXivID", ""),
                "\n".join(pages[:2]),
                abstract,
            ]
        )
    )
    year = _guess_pdf_year(metadata, pages, pdf_path.name)
    if arxiv_id:
        arxiv_year = 2000 + int(arxiv_id[:2])
        # Some arXiv PDFs carry stale template creation dates; prefer the arXiv submission year
        # whenever the embedded PDF year is missing or clearly inconsistent.
        if year is None or abs(year - arxiv_year) > 1:
            year = arxiv_year
    doi_match = re.search(
        r"(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)",
        "\n".join([metadata.get("DOI", ""), abstract, "\n".join(pages[:2]), metadata.get("Subject", "")]),
    )
    topics, tags = infer_topics_and_tags(f"{title}\n{abstract}")
    return {
        "title": title,
        "authors": authors,
        "abstract": abstract,
        "year": year,
        "arxiv_id": arxiv_id,
        "doi": doi_match.group(1) if doi_match else "",
        "topics": topics,
        "tags": tags,
        "metadata": metadata,
        "text_preview": "\n\n".join(pages),
    }


# Default hard cap on any single download, in bytes. Guards against pulling a
# multi-GB artifact into the workspace by accident. Callers may lower it, and
# the source-intake pipeline passes an explicit ~50MB cap for PDF downloads.
FETCH_MAX_BYTES = 50 * 1024 * 1024


class FetchTooLarge(Exception):
    """Raised when a download exceeds the configured size cap."""


def _read_capped(response: Any, max_bytes: int) -> bytes:
    """Read a response body but refuse to buffer more than ``max_bytes``.

    Reading incrementally means a hostile or mislabeled URL cannot exhaust
    memory before we notice it is oversized.
    """

    if max_bytes is None or max_bytes <= 0:
        return response.read()
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = response.read(65536)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise FetchTooLarge(f"download exceeded size cap of {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_url(
    url: str,
    *,
    binary: bool = False,
    timeout: int = 20,
    retries: int = 2,
    retry_backoff: float = 1.5,
    max_bytes: int | None = FETCH_MAX_BYTES,
) -> tuple[bytes | str, str]:
    """Fetch ``url`` with a simple bounded retry and a hard size cap.

    Transient failures (timeouts, connection resets, and 5xx/429 responses)
    are retried up to ``retries`` extra times with linear backoff; definitive
    failures (404/403/other 4xx) are not retried so callers probing a fallback
    chain fail fast. ``max_bytes`` bounds the buffered payload.
    """

    request = Request(url, headers={"User-Agent": "Mozilla/5.0 Codex Research Skills/1.1"})
    attempts = max(1, retries + 1)
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310
                content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
                payload = _read_capped(response, max_bytes)
            if binary:
                return payload, content_type
            return payload.decode("utf-8", errors="ignore"), content_type
        except FetchTooLarge:
            raise
        except HTTPError as exc:
            last_error = exc
            # Only server-side/transient statuses are worth retrying.
            if exc.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                time.sleep(retry_backoff * (attempt + 1))
                continue
            raise
        except (URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(retry_backoff * (attempt + 1))
                continue
            raise
    # Unreachable in practice: the loop either returns or raises.
    raise last_error if last_error else RuntimeError(f"fetch_url failed: {url}")


def html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def blank_index(doc_id: str, generated_by: str) -> dict[str, Any]:
    payload = yaml_default(doc_id, generated_by)
    payload["items"] = {}
    return payload


def blank_list_document(doc_id: str, generated_by: str) -> dict[str, Any]:
    payload = yaml_default(doc_id, generated_by)
    payload["items"] = []
    return payload


def blank_reporting_events(program_id: str, generated_by: str = "weekly-report-author") -> dict[str, Any]:
    payload = blank_list_document(f"{program_id}-reporting-events", generated_by)
    payload["program_id"] = program_id
    return payload


def load_index(path: Path, doc_id: str, generated_by: str) -> dict[str, Any]:
    payload = load_yaml(path)
    if not isinstance(payload, dict):
        return blank_index(doc_id, generated_by)
    payload.setdefault("id", doc_id)
    payload.setdefault("status", "ready")
    payload.setdefault("generated_by", generated_by)
    payload.setdefault("generated_at", utc_now_iso())
    payload["inputs"] = [str(item) for item in _coerce_list(payload.get("inputs")) if str(item).strip()]
    payload.setdefault("confidence", 1.0)
    items = payload.get("items", {})
    payload["items"] = items if isinstance(items, dict) else {}
    return payload


def load_list_document(path: Path, doc_id: str, generated_by: str) -> dict[str, Any]:
    payload = load_yaml(path)
    if not isinstance(payload, dict):
        return blank_list_document(doc_id, generated_by)
    payload.setdefault("id", doc_id)
    payload.setdefault("status", "ready")
    payload.setdefault("generated_by", generated_by)
    payload.setdefault("generated_at", utc_now_iso())
    payload["inputs"] = [str(item) for item in _coerce_list(payload.get("inputs")) if str(item).strip()]
    payload.setdefault("confidence", 1.0)
    payload["items"] = _coerce_list(payload.get("items"))
    return payload


def _kb_project_root_for_path(path: Path) -> Path | None:
    resolved = path.resolve(strict=False)
    for candidate in [resolved.parent, *resolved.parents]:
        if candidate.name == "kb":
            return candidate.parent
    return None


def _append_list_item_unlocked(
    path: Path,
    doc_id: str,
    generated_by: str,
    item: dict[str, Any],
    *,
    default_status: str = "",
) -> Path:
    payload = load_list_document(path, doc_id, generated_by)
    items = [entry for entry in payload.get("items", []) if isinstance(entry, dict)]
    normalized = dict(item)
    normalized.setdefault("id", f"{doc_id}-{len(items) + 1:03d}")
    normalized.setdefault("created_at", utc_now_iso())
    if default_status:
        normalized.setdefault("status", default_status)
    items.append(normalized)
    payload["items"] = items
    payload["generated_by"] = generated_by
    payload["generated_at"] = utc_now_iso()
    write_yaml_if_changed(path, payload)
    return path


def append_list_item(path: Path, doc_id: str, generated_by: str, item: dict[str, Any], *, default_status: str = "") -> Path:
    project_root = _kb_project_root_for_path(path)
    if project_root is None:
        return _append_list_item_unlocked(
            path,
            doc_id,
            generated_by,
            item,
            default_status=default_status,
        )

    from .journal import mutation_transaction

    with mutation_transaction(project_root, "append_list_item", [path]):
        return _append_list_item_unlocked(
            path,
            doc_id,
            generated_by,
            item,
            default_status=default_status,
        )


def program_reporting_events_path(project_root: Path, program_id: str) -> Path:
    return program_root(project_root, program_id) / "workflow" / "reporting-events.yaml"


def load_program_reporting_events(project_root: Path, program_id: str) -> list[dict[str, Any]]:
    payload = load_list_document(
        program_reporting_events_path(project_root, program_id),
        f"{program_id}-reporting-events",
        "weekly-report-author",
    )
    events: list[dict[str, Any]] = []
    for item in payload.get("items", []):
        if not isinstance(item, dict):
            continue
        event = dict(item)
        event["timestamp_dt"] = parse_iso_datetime(item.get("timestamp"))
        events.append(event)
    events.sort(key=lambda item: item.get("timestamp_dt") or datetime.min.replace(tzinfo=timezone.utc))
    return events


def append_program_reporting_event(
    project_root: Path,
    program_id: str,
    event: dict[str, Any],
    *,
    generated_by: str,
) -> Path:
    # Local import avoids the common <-> journal module cycle while keeping the
    # shared load-modify-write transaction guarded by the stable on-disk lock.
    from .journal import mutation_transaction

    path = program_reporting_events_path(project_root, program_id)
    with mutation_transaction(project_root, "append_program_reporting_event", [path]):
        payload = load_list_document(path, f"{program_id}-reporting-events", generated_by)
        payload["program_id"] = program_id
        payload["generated_by"] = generated_by
        payload["generated_at"] = utc_now_iso()
        items = [item for item in payload.get("items", []) if isinstance(item, dict)]
        normalized = dict(event)
        normalized.setdefault("timestamp", utc_now_iso())
        normalized["source_skill"] = str(normalized.get("source_skill") or generated_by).strip() or generated_by
        normalized["event_type"] = str(normalized.get("event_type") or "update").strip() or "update"
        normalized["title"] = str(normalized.get("title") or "").strip()
        normalized["summary"] = str(normalized.get("summary") or "").strip()
        for key in ("artifacts", "idea_ids", "paper_ids", "repo_ids", "tags"):
            values = normalized.get(key, [])
            if isinstance(values, list):
                normalized[key] = [str(item) for item in values if str(item).strip()]
            else:
                normalized[key] = []
        if "stage" in normalized:
            normalized["stage"] = str(normalized.get("stage") or "").strip()
        items.append(normalized)
        payload["items"] = items
        write_yaml_if_changed(path, payload)
    return path


def read_text_excerpt(path: Path, limit: int = 4000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")[:limit]
