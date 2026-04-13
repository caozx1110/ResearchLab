from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from functools import lru_cache
from html import unescape
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urljoin, urlparse, urlunparse
from urllib.request import Request, urlopen

try:
    import yaml as _yaml
except ModuleNotFoundError:
    _yaml = None


SOURCE_KINDS = {"paper", "blog", "project-page", "survey", "note"}
PDF_MIME_TYPES = {"application/pdf", "application/x-pdf"}
RUNTIME_MODULES = ("yaml", "PyPDF2", "pypdf")
STOPWORDS = {
    "a",
    "an",
    "and",
    "as",
    "at",
    "for",
    "from",
    "in",
    "into",
    "of",
    "on",
    "or",
    "the",
    "to",
    "with",
}
KEYWORD_BLACKLIST = {
    "analysis",
    "approach",
    "approaches",
    "architecture",
    "architectures",
    "benchmark",
    "benchmarks",
    "data",
    "dataset",
    "datasets",
    "efficient",
    "evaluation",
    "framework",
    "frameworks",
    "general",
    "improve",
    "improved",
    "improving",
    "large",
    "learning",
    "method",
    "methods",
    "model",
    "models",
    "new",
    "novel",
    "paper",
    "pipeline",
    "pipelines",
    "research",
    "result",
    "results",
    "robot",
    "robots",
    "robotic",
    "robotics",
    "robust",
    "scale",
    "scalable",
    "scaling",
    "simple",
    "study",
    "system",
    "systems",
    "task",
    "tasks",
    "train",
    "training",
    "work",
}
GENERIC_KEYWORD_PHRASES = {
    "end-to-end",
    "real-world",
    "state-of-the-art",
}


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def find_project_root(start: Path | None = None) -> Path:
    current = (start or Path.cwd()).resolve()
    for candidate in [current] + list(current.parents):
        if (candidate / ".agents").exists() and (candidate / "doc").exists():
            return candidate
    raise FileNotFoundError(f"Could not locate project root from {current}")


def research_root(project_root: Path) -> Path:
    return project_root / "doc" / "research"


def program_root(project_root: Path, program_id: str) -> Path:
    return research_root(project_root) / "programs" / program_id


def raw_root(project_root: Path) -> Path:
    return project_root / "raw"


def runtime_memory_path(project_root: Path) -> Path:
    return research_root(project_root) / "memory" / "runtime-environments.yaml"


def domain_profile_path(project_root: Path) -> Path:
    return research_root(project_root) / "memory" / "domain-profile.yaml"


def blank_runtime_registry(generated_by: str = "research-conductor") -> dict[str, Any]:
    return {
        **yaml_default("runtime-environments", generated_by, status="active", confidence=0.9),
        "preferred_runtime_id": "",
        "items": {},
        "history": [],
    }


def blank_domain_profile(generated_by: str = "research-conductor") -> dict[str, Any]:
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


def yaml_scalar(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def yaml_lines(value: Any, indent: int = 0) -> list[str]:
    prefix = " " * indent
    if isinstance(value, dict):
        if not value:
            return [prefix + "{}"]
        lines: list[str] = []
        for key, item in value.items():
            if isinstance(item, (dict, list)):
                if not item:
                    empty = "{}" if isinstance(item, dict) else "[]"
                    lines.append(f"{prefix}{key}: {empty}")
                else:
                    lines.append(f"{prefix}{key}:")
                    lines.extend(yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}{key}: {yaml_scalar(item)}")
        return lines
    if isinstance(value, list):
        if not value:
            return [prefix + "[]"]
        lines = []
        for item in value:
            if isinstance(item, (dict, list)):
                if isinstance(item, dict) and item:
                    first_key = next(iter(item))
                    first_value = item[first_key]
                    if isinstance(first_value, (dict, list)):
                        lines.append(f"{prefix}- {first_key}:")
                        lines.extend(yaml_lines(first_value, indent + 4))
                        for key in list(item.keys())[1:]:
                            nested = item[key]
                            if isinstance(nested, (dict, list)):
                                if not nested:
                                    empty = "{}" if isinstance(nested, dict) else "[]"
                                    lines.append(f"{' ' * (indent + 2)}{key}: {empty}")
                                else:
                                    lines.append(f"{' ' * (indent + 2)}{key}:")
                                    lines.extend(yaml_lines(nested, indent + 4))
                            else:
                                lines.append(f"{' ' * (indent + 2)}{key}: {yaml_scalar(nested)}")
                    else:
                        lines.append(f"{prefix}- {first_key}: {yaml_scalar(first_value)}")
                        for key in list(item.keys())[1:]:
                            nested = item[key]
                            if isinstance(nested, (dict, list)):
                                if not nested:
                                    empty = "{}" if isinstance(nested, dict) else "[]"
                                    lines.append(f"{' ' * (indent + 2)}{key}: {empty}")
                                else:
                                    lines.append(f"{' ' * (indent + 2)}{key}:")
                                    lines.extend(yaml_lines(nested, indent + 4))
                            else:
                                lines.append(f"{' ' * (indent + 2)}{key}: {yaml_scalar(nested)}")
                else:
                    lines.append(prefix + "-")
                    lines.extend(yaml_lines(item, indent + 2))
            else:
                lines.append(f"{prefix}- {yaml_scalar(item)}")
        return lines
    return [prefix + yaml_scalar(value)]


def _parse_scalar(text: str) -> Any:
    stripped = text.strip()
    if stripped == "":
        return ""
    if stripped == "null":
        return None
    if stripped == "true":
        return True
    if stripped == "false":
        return False
    if stripped == "[]":
        return []
    if stripped == "{}":
        return {}
    if stripped.startswith('"') and stripped.endswith('"'):
        try:
            return json.loads(stripped)
        except json.JSONDecodeError:
            return stripped[1:-1]
    if stripped.startswith("'") and stripped.endswith("'"):
        return stripped[1:-1]
    if re.fullmatch(r"-?\d+", stripped):
        return int(stripped)
    if re.fullmatch(r"-?\d+\.\d+", stripped):
        return float(stripped)
    return stripped


def _next_significant_line(lines: list[str], start: int) -> int:
    index = start
    while index < len(lines):
        stripped = lines[index].strip()
        if stripped and not stripped.startswith("#"):
            return index
        index += 1
    return index


def _parse_mapping_entries(lines: list[str], index: int, indent: int, current: dict[str, Any] | None = None) -> tuple[dict[str, Any], int]:
    data = current or {}
    index = _next_significant_line(lines, index)
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        current_indent = len(raw) - len(raw.lstrip(" "))
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        if current_indent < indent or stripped.startswith("-"):
            break
        key, sep, remainder = stripped.partition(":")
        if not sep:
            raise ValueError(f"Invalid YAML mapping line: {raw}")
        key = key.strip()
        remainder = remainder.strip()
        if remainder == "":
            index += 1
            next_index = _next_significant_line(lines, index)
            if next_index >= len(lines):
                data[key] = {}
                index = next_index
                break
            next_raw = lines[next_index]
            next_indent = len(next_raw) - len(next_raw.lstrip(" "))
            if next_indent <= current_indent:
                data[key] = {}
                index = next_index
                continue
            nested, index = _parse_block(lines, next_index, next_indent)
            data[key] = nested
        else:
            data[key] = _parse_scalar(remainder)
            index += 1
    return data, index


def _parse_list(lines: list[str], index: int, indent: int) -> tuple[list[Any], int]:
    items: list[Any] = []
    index = _next_significant_line(lines, index)
    while index < len(lines):
        raw = lines[index]
        stripped = raw.strip()
        current_indent = len(raw) - len(raw.lstrip(" "))
        if not stripped or stripped.startswith("#"):
            index += 1
            continue
        if current_indent < indent or not stripped.startswith("-"):
            break
        remainder = stripped[1:].lstrip()
        if remainder == "":
            nested, index = _parse_block(lines, index + 1, indent + 2)
            items.append(nested)
            continue
        if ":" in remainder and not remainder.startswith(('"', "'")):
            key, sep, value = remainder.partition(":")
            seed: dict[str, Any] = {}
            key = key.strip()
            value = value.strip()
            if value == "":
                nested, next_index = _parse_block(lines, index + 1, indent + 4)
                seed[key] = nested
                index = next_index
            else:
                seed[key] = _parse_scalar(value)
                index += 1
            seed, index = _parse_mapping_entries(lines, index, indent + 2, seed)
            items.append(seed)
            continue
        items.append(_parse_scalar(remainder))
        index += 1
    return items, index


def _parse_block(lines: list[str], index: int, indent: int) -> tuple[Any, int]:
    index = _next_significant_line(lines, index)
    if index >= len(lines):
        return {}, index
    raw = lines[index]
    stripped = raw.strip()
    current_indent = len(raw) - len(raw.lstrip(" "))
    if current_indent < indent:
        return {}, index
    if stripped.startswith("-"):
        return _parse_list(lines, index, current_indent)
    return _parse_mapping_entries(lines, index, current_indent, {})


def _simple_yaml_load(text: str) -> Any:
    lines = text.splitlines()
    start = _next_significant_line(lines, 0)
    if start >= len(lines):
        return None
    value, _ = _parse_block(lines, start, len(lines[start]) - len(lines[start].lstrip(" ")))
    return value


def load_yaml(path: Path, default: Any | None = None, *, allow_simple_fallback: bool = False) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return default
    if _yaml is not None:
        return _yaml.safe_load(text)
    if allow_simple_fallback:
        return _simple_yaml_load(text)
    raise RuntimeError(
        "PyYAML is required to read research workspace YAML safely. "
        f"Current runtime cannot parse {path} without risking corrupted metadata."
    )


def dump_yaml(value: Any) -> str:
    if _yaml is not None:
        return _yaml.safe_dump(value, allow_unicode=True, sort_keys=False)
    return "\n".join(yaml_lines(value)) + "\n"


def write_text_if_changed(path: Path, text: str) -> None:
    ensure_dir(path.parent)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    path.write_text(text, encoding="utf-8")


def write_yaml_if_changed(path: Path, value: Any) -> None:
    write_text_if_changed(path, dump_yaml(value))


def slugify(text: str, *, max_words: int = 8) -> str:
    normalized = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    words = [word for word in normalized.split() if word]
    if not words:
        return "item"
    filtered = [word for word in words if word not in STOPWORDS]
    chosen = filtered if filtered else words
    return "-".join(chosen[:max_words])


def normalize_title(text: str) -> str:
    lowered = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(lowered.split())


def slugify_tag(text: str) -> str:
    normalized = normalize_title(text).replace(" ", "-")
    normalized = re.sub(r"-{2,}", "-", normalized)
    return normalized.strip("-")


def normalize_person_name(text: str) -> str:
    lowered = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    lowered = re.sub(r"[^a-z0-9]+", " ", lowered)
    return " ".join(lowered.split())


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


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = re.sub(r"/+", "/", parsed.path or "/")
    query_pairs = parse_qs(parsed.query, keep_blank_values=False)
    keep_keys = []
    if "openreview.net" in netloc:
        keep_keys = ["id"]
    elif "doi.org" in netloc:
        keep_keys = []
    query = "&".join(f"{key}={query_pairs[key][0]}" for key in keep_keys if key in query_pairs)
    return urlunparse((scheme, netloc, path.rstrip("/") or "/", "", query, ""))


def parse_arxiv_id(value: str) -> str:
    match = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", value)
    return match.group(1) if match else ""


def parse_openreview_id(url: str) -> str:
    parsed = urlparse(url)
    if "openreview.net" not in parsed.netloc.lower():
        return ""
    query = parse_qs(parsed.query)
    return query.get("id", [""])[0]


def canonical_literature_source(external_ids: dict[str, str] | None = None) -> tuple[str, str]:
    external_ids = external_ids or {}
    arxiv_id = str(external_ids.get("arxiv_id") or "").strip()
    if arxiv_id:
        return canonicalize_url(f"https://arxiv.org/abs/{arxiv_id}"), "arxiv.org"
    doi = str(external_ids.get("doi") or "").strip()
    if doi:
        return canonicalize_url(f"https://doi.org/{doi}"), "doi.org"
    openreview_id = str(external_ids.get("openreview_id") or "").strip()
    if openreview_id:
        return canonicalize_url(f"https://openreview.net/forum?id={openreview_id}"), "openreview.net"
    return "", ""


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
    payload = load_yaml(domain_profile_path(project_root), default={}, allow_simple_fallback=True)
    if not isinstance(payload, dict):
        payload = blank_domain_profile()
    payload.setdefault("id", "domain-profile")
    payload.setdefault("status", "active")
    payload.setdefault("generated_by", "research-conductor")
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


def query_keyword_terms(text: str, *, stopwords: set[str] | None = None, project_root: Path | None = None) -> list[str]:
    tokens = normalize_title(text).split()
    active_stopwords = stopwords or set()
    short_terms = domain_short_terms(project_root)
    return sorted(
        {
            token
            for token in tokens
            if token
            and token not in active_stopwords
            and (len(token) >= 4 or token in short_terms or any(char.isdigit() for char in token))
        }
    )


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


def _known_tag_slugs(project_root: Path | None = None) -> set[str]:
    known: set[str] = set()
    for rule in domain_tagging_rules(project_root):
        tag = slugify_tag(str(rule.get("tag") or ""))
        if tag:
            known.add(tag)
    for canonical, item in domain_taxonomy_seeds(project_root).items():
        canonical_slug = slugify_tag(canonical)
        if canonical_slug:
            known.add(canonical_slug)
        if isinstance(item, dict):
            for alias in item.get("aliases", []):
                alias_slug = slugify_tag(str(alias))
                if alias_slug:
                    known.add(alias_slug)
    return known


def _valid_keyword_phrase(tokens: list[str], slug: str) -> bool:
    if not tokens or not slug or len(tokens) > 4:
        return False
    if tokens[0] in STOPWORDS or tokens[-1] in STOPWORDS:
        return False
    if slug in GENERIC_KEYWORD_PHRASES:
        return False
    if any(len(token) == 1 and not token.isdigit() for token in tokens):
        return False
    content_tokens = [token for token in tokens if token not in STOPWORDS]
    if not content_tokens:
        return False
    if len(tokens) == 1:
        token = content_tokens[0]
        if token in KEYWORD_BLACKLIST:
            return False
        if len(token) < 5 and not any(char.isdigit() for char in token):
            return False
        return True
    strong_tokens = [
        token
        for token in content_tokens
        if token not in KEYWORD_BLACKLIST and (len(token) >= 4 or any(char.isdigit() for char in token))
    ]
    return bool(strong_tokens)


def _keyword_phrase_candidates(tokens: list[str], *, max_ngram: int) -> list[list[str]]:
    chunks: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in STOPWORDS:
            if current:
                chunks.append(current)
                current = []
            continue
        current.append(token)
    if current:
        chunks.append(current)

    phrases: list[list[str]] = []
    seen: set[tuple[str, ...]] = set()
    for chunk in chunks:
        trimmed = list(chunk)
        while len(trimmed) > 1 and trimmed[0] in KEYWORD_BLACKLIST:
            trimmed = trimmed[1:]
        while len(trimmed) > 1 and trimmed[-1] in KEYWORD_BLACKLIST:
            trimmed = trimmed[:-1]
        if not trimmed:
            continue

        candidates: list[list[str]] = []
        if len(trimmed) <= max_ngram:
            candidates.append(trimmed)
        else:
            candidates.append(trimmed[:max_ngram])
            candidates.append(trimmed[-max_ngram:])
        if len(trimmed) >= 2:
            candidates.append(trimmed[:2])
            candidates.append(trimmed[-2:])
        if len(trimmed) >= 3:
            candidates.append(trimmed[:3])
            candidates.append(trimmed[-3:])
        if len(trimmed) == 1:
            candidates.append(trimmed)

        for candidate in candidates:
            key = tuple(candidate)
            if key in seen:
                continue
            seen.add(key)
            phrases.append(candidate)
    return phrases


def discover_keyword_tags(
    title: str,
    abstract: str,
    *,
    project_root: Path | None = None,
    existing_tags: list[str] | None = None,
    limit: int = 4,
) -> list[dict[str, Any]]:
    known_slugs = _known_tag_slugs(project_root)
    existing_slugs = {slugify_tag(tag) for tag in (existing_tags or []) if slugify_tag(tag)}
    existing_token_union = {
        token
        for slug in existing_slugs
        for token in slug.split("-")
        if token
    }
    title_text = normalize_title(title)
    abstract_text = normalize_title(abstract)
    scores: dict[str, float] = {}
    phrases: dict[str, str] = {}
    sources: dict[str, set[str]] = {}

    def register_phrase(source_name: str, normalized_text: str, *, base_weight: float, max_ngram: int) -> None:
        tokens = normalized_text.split()
        if not tokens:
            return
        local_counts: dict[str, int] = {}
        local_phrase: dict[str, str] = {}
        for phrase_tokens in _keyword_phrase_candidates(tokens, max_ngram=max_ngram):
            phrase = " ".join(phrase_tokens)
            slug = slugify_tag(phrase)
            if not slug or slug in known_slugs or slug in existing_slugs:
                continue
            if not _valid_keyword_phrase(phrase_tokens, slug):
                continue
            local_counts[slug] = local_counts.get(slug, 0) + 1
            local_phrase.setdefault(slug, phrase)
        for slug, count in local_counts.items():
            phrase = local_phrase.get(slug, slug.replace("-", " "))
            phrase_tokens = phrase.split()
            score = base_weight + max(len(phrase_tokens) - 1, 0) * 0.6 + min(count - 1, 2) * 0.7
            scores[slug] = scores.get(slug, 0.0) + score
            phrases.setdefault(slug, phrase)
            sources.setdefault(slug, set()).add(source_name)

    register_phrase("title", title_text, base_weight=3.4, max_ngram=4)
    register_phrase("abstract", abstract_text, base_weight=1.6, max_ngram=3)

    for acronym in sorted(set(re.findall(r"\b[A-Z][A-Z0-9]{1,9}\b", title))):
        slug = slugify_tag(acronym)
        if not slug or slug in known_slugs or slug in existing_slugs:
            continue
        if len(slug) < 2:
            continue
        scores[slug] = max(scores.get(slug, 0.0), 3.0)
        phrases.setdefault(slug, acronym)
        sources.setdefault(slug, set()).add("title-acronym")

    ranked = sorted(
        scores.items(),
        key=lambda item: (-item[1], -len(item[0].split("-")), item[0]),
    )
    selected: list[dict[str, Any]] = []
    selected_slugs: list[str] = []
    for slug, score in ranked:
        if score < 3.0:
            continue
        if existing_token_union and set(slug.split("-")) <= existing_token_union:
            continue
        if any(
            slug == chosen
            or slug.startswith(f"{chosen}-")
            or chosen.startswith(f"{slug}-")
            for chosen in selected_slugs
        ):
            continue
        selected.append(
            {
                "tag": slug,
                "phrase": phrases.get(slug, slug.replace("-", " ")),
                "score": round(score, 2),
                "sources": sorted(sources.get(slug, set())),
            }
        )
        selected_slugs.append(slug)
        if len(selected) >= limit:
            break
    return selected


def merge_keyword_tags(base_tags: list[str], keyword_candidates: list[dict[str, Any]], *, limit: int = 2) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    generic_placeholder = {"research"}
    base_values = list(base_tags)
    if keyword_candidates:
        base_values = [tag for tag in base_values if slugify_tag(tag) not in generic_placeholder]
    for tag in base_values:
        slug = slugify_tag(tag)
        if not slug or slug in seen:
            continue
        seen.add(slug)
        merged.append(slug)
    added = 0
    for candidate in keyword_candidates:
        slug = slugify_tag(str(candidate.get("tag") or ""))
        if not slug or slug in seen:
            continue
        merged.append(slug)
        seen.add(slug)
        added += 1
        if added >= limit:
            break
    return merged


def guess_source_kind(url: str, title: str = "", content_type: str = "") -> str:
    lowered_url = url.lower()
    lowered_title = title.lower()
    lowered_type = content_type.lower()
    if any(token in lowered_url for token in ("arxiv.org", "openreview.net", "/doi/")):
        return "paper"
    if lowered_url.endswith(".pdf") or lowered_type in PDF_MIME_TYPES:
        return "paper"
    if "blog" in lowered_url or "blog" in lowered_title:
        return "blog"
    if "project" in lowered_url or "homepage" in lowered_title:
        return "project-page"
    return "note"


def pdf_backend() -> Any:
    try:
        from PyPDF2 import PdfReader  # type: ignore

        return PdfReader
    except ModuleNotFoundError:
        try:
            from pypdf import PdfReader  # type: ignore

            return PdfReader
        except ModuleNotFoundError as exc:
            raise ModuleNotFoundError(
                "PDF parsing requires PyPDF2 or pypdf in the active research runtime."
            ) from exc


def current_runtime_capabilities() -> dict[str, Any]:
    module_status = {name: importlib.util.find_spec(name) is not None for name in RUNTIME_MODULES}
    pdf_backend_name = "PyPDF2" if module_status["PyPDF2"] else ("pypdf" if module_status["pypdf"] else "")
    return {
        "python": sys.executable,
        "version": sys.version.split()[0],
        "modules": module_status,
        "yaml_support": module_status["yaml"],
        "pdf_support": bool(pdf_backend_name),
        "pdf_backend": pdf_backend_name,
    }


def inspect_python_runtime(python_executable: str) -> dict[str, Any]:
    script = (
        "import importlib.util, json, sys\n"
        "mods = {name: bool(importlib.util.find_spec(name)) for name in ('yaml', 'PyPDF2', 'pypdf')}\n"
        "backend = 'PyPDF2' if mods['PyPDF2'] else ('pypdf' if mods['pypdf'] else '')\n"
        "print(json.dumps({\n"
        "    'python': sys.executable,\n"
        "    'version': sys.version.split()[0],\n"
        "    'modules': mods,\n"
        "    'yaml_support': mods['yaml'],\n"
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
    payload = load_yaml(runtime_memory_path(project_root), default={}, allow_simple_fallback=True)
    if not isinstance(payload, dict):
        payload = blank_runtime_registry()
    payload.setdefault("id", "runtime-environments")
    payload.setdefault("status", "active")
    payload.setdefault("generated_by", "research-conductor")
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


def _runtime_record_id(items: dict[str, Any], label: str, python_executable: str) -> str:
    existing = next(
        (
            runtime_id
            for runtime_id, record in items.items()
            if isinstance(record, dict) and str(record.get("python") or "") == python_executable
        ),
        "",
    )
    if existing:
        return existing
    base = slugify(label or Path(python_executable).name, max_words=6)
    runtime_id = f"runtime-{base}"
    suffix = 2
    while runtime_id in items:
        runtime_id = f"runtime-{base}-{suffix}"
        suffix += 1
    return runtime_id


def remember_runtime(
    project_root: Path,
    python_executable: str,
    *,
    label: str = "",
    notes: str = "",
    set_default: bool = True,
    recorded_by: str = "research-conductor",
) -> dict[str, Any]:
    registry = load_runtime_registry(project_root)
    probe = inspect_python_runtime(python_executable)
    runtime_label = label or Path(str(probe.get("python") or python_executable)).name
    runtime_id = _runtime_record_id(registry["items"], runtime_label, str(probe.get("python") or python_executable))
    record = {
        "runtime_id": runtime_id,
        "label": runtime_label,
        "python": str(probe.get("python") or python_executable),
        "version": str(probe.get("version") or ""),
        "modules": probe.get("modules", {}),
        "yaml_support": bool(probe.get("yaml_support")),
        "pdf_support": bool(probe.get("pdf_support")),
        "pdf_backend": str(probe.get("pdf_backend") or ""),
        "probe_error": str(probe.get("probe_error") or ""),
        "captured_at": utc_now_iso(),
        "notes": notes,
        "recorded_by": recorded_by,
    }
    registry["generated_at"] = utc_now_iso()
    registry["items"][runtime_id] = record
    if set_default or not registry.get("preferred_runtime_id"):
        registry["preferred_runtime_id"] = runtime_id
    registry["history"].append(
        {
            "timestamp": utc_now_iso(),
            "type": "runtime-remembered",
            "runtime_id": runtime_id,
            "python": record["python"],
            "set_default": set_default,
        }
    )
    write_yaml_if_changed(runtime_memory_path(project_root), registry)
    return record


def format_runtime_report(runtime: dict[str, Any]) -> str:
    modules = runtime.get("modules", {})
    return (
        f"runtime_id: {runtime.get('runtime_id', '')}\n"
        f"label: {runtime.get('label', '')}\n"
        f"python: {runtime.get('python', '')}\n"
        f"version: {runtime.get('version', '')}\n"
        f"yaml_support: {bool(runtime.get('yaml_support'))}\n"
        f"pdf_support: {bool(runtime.get('pdf_support'))}\n"
        f"pdf_backend: {runtime.get('pdf_backend', '') or 'missing'}\n"
        f"modules: yaml={bool(modules.get('yaml'))}, PyPDF2={bool(modules.get('PyPDF2'))}, pypdf={bool(modules.get('pypdf'))}"
    )


def ensure_research_runtime(project_root: Path, skill_name: str, *, require_pdf_backend: bool = False) -> None:
    capabilities = current_runtime_capabilities()
    missing: list[str] = []
    if not capabilities["yaml_support"]:
        missing.append("PyYAML")
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
                    "Retry with the remembered interpreter or refresh it with "
                    "`python3 .agents/skills/research-conductor/scripts/manage_workspace.py remember-runtime "
                    "--python <path-to-python> --label research-default`."
                ),
            ]
        )
    else:
        lines.extend(
            [
                "No remembered research runtime is stored yet.",
                (
                    "Register one with "
                    "`python3 .agents/skills/research-conductor/scripts/manage_workspace.py remember-runtime "
                    "--python <path-to-python> --label research-default`."
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


def _guess_pdf_title(metadata: dict[str, str], pages: list[str], fallback: str) -> str:
    return clean_text(" ".join(_title_lines_from_pdf(metadata, pages, fallback)))


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


def fetch_url(url: str, *, binary: bool = False, timeout: int = 20) -> tuple[bytes | str, str]:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 Codex Research Skills/1.1"})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310
        content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
        payload = response.read()
    if binary:
        return payload, content_type
    return payload.decode("utf-8", errors="ignore"), content_type


def html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", " ", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def find_first_pdf_link(html: str, base_url: str) -> str:
    for match in re.finditer(r'href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\']', html, flags=re.IGNORECASE):
        href = unescape(match.group(1))
        return urljoin(base_url, href)
    return ""


def literature_index_path(project_root: Path) -> Path:
    return research_root(project_root) / "library" / "literature" / "index.yaml"


def literature_graph_path(project_root: Path) -> Path:
    return research_root(project_root) / "library" / "literature" / "graph.yaml"


def literature_tags_path(project_root: Path) -> Path:
    return research_root(project_root) / "library" / "literature" / "tags.yaml"


def literature_tag_taxonomy_path(project_root: Path) -> Path:
    return research_root(project_root) / "library" / "literature" / "tag-taxonomy.yaml"


def repo_index_path(project_root: Path) -> Path:
    return research_root(project_root) / "library" / "repos" / "index.yaml"


def wiki_root(project_root: Path) -> Path:
    return research_root(project_root) / "wiki"


def wiki_index_path(project_root: Path) -> Path:
    return wiki_root(project_root) / "index.md"


def wiki_log_path(project_root: Path) -> Path:
    return wiki_root(project_root) / "log.md"


def wiki_queries_root(project_root: Path) -> Path:
    return wiki_root(project_root) / "queries"


def wiki_lint_root(project_root: Path) -> Path:
    return wiki_root(project_root) / "lint"


def wiki_lint_latest_path(project_root: Path) -> Path:
    return wiki_lint_root(project_root) / "latest.md"


def pending_paper_reviews_path(project_root: Path) -> Path:
    return research_root(project_root) / "intake" / "papers" / "review" / "pending.yaml"


def resolved_paper_reviews_path(project_root: Path) -> Path:
    return research_root(project_root) / "intake" / "papers" / "review" / "resolved.yaml"


def pending_repo_reviews_path(project_root: Path) -> Path:
    return research_root(project_root) / "intake" / "repos" / "review" / "pending.yaml"


def resolved_repo_reviews_path(project_root: Path) -> Path:
    return research_root(project_root) / "intake" / "repos" / "review" / "resolved.yaml"


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
    path = program_reporting_events_path(project_root, program_id)
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


def build_literature_graph(records: list[dict[str, Any]], generated_by: str = "literature-corpus-builder") -> dict[str, Any]:
    graph = yaml_default("literature-graph", generated_by)
    graph["inputs"] = [f"lit:{record['id']}" for record in records if record.get("id")]
    graph["nodes"] = []
    graph["edges"] = []
    for record in records:
        graph["nodes"].append(
            {
                "id": record["id"],
                "title": record.get("canonical_title", ""),
                "topics": record.get("topics", []),
                "tags": record.get("tags", []),
            }
        )
    for idx, left in enumerate(records):
        for right in records[idx + 1 :]:
            shared_topics = sorted(set(left.get("topics", [])) & set(right.get("topics", [])))
            shared_tags = sorted(set(left.get("tags", [])) & set(right.get("tags", [])))
            if not shared_topics and not shared_tags:
                continue
            score = (len(shared_topics) * 2) + len(shared_tags)
            graph["edges"].append(
                {
                    "source": left["id"],
                    "target": right["id"],
                    "shared_topics": shared_topics,
                    "shared_tags": shared_tags,
                    "score": score,
                }
            )
    graph["edges"].sort(key=lambda item: (-item["score"], item["source"], item["target"]))
    return graph


def literature_record_from_metadata(metadata_path: Path) -> dict[str, Any]:
    payload = load_yaml(metadata_path, default={})
    if not isinstance(payload, dict):
        return {}
    return payload


def load_literature_records(project_root: Path) -> list[dict[str, Any]]:
    literature_root = research_root(project_root) / "library" / "literature"
    records: list[dict[str, Any]] = []
    for metadata_path in sorted(literature_root.glob("*/metadata.yaml")):
        payload = literature_record_from_metadata(metadata_path)
        if payload.get("id"):
            records.append(payload)
    return records


def build_literature_tag_index(
    records: list[dict[str, Any]],
    generated_by: str = "literature-tagger",
    taxonomy_items: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = blank_index("literature-tags", generated_by)
    taxonomy_items = taxonomy_items or {}
    payload["inputs"] = [f"lit:{record['id']}" for record in records if record.get("id")]
    for record in records:
        source_id = str(record.get("id") or "")
        if not source_id:
            continue
        for tag in record.get("tags", []):
            item = payload["items"].setdefault(
                tag,
                {
                    "id": tag,
                    "tag": tag,
                    "count": 0,
                    "source_ids": [],
                    "topics": [],
                },
            )
            item["count"] += 1
            item["source_ids"].append(source_id)
            item["source_ids"] = sorted(set(item["source_ids"]))
            item["topics"] = sorted(set(item.get("topics", [])) | set(record.get("topics", [])))
    for tag, item in payload["items"].items():
        taxonomy_item = taxonomy_items.get(tag)
        if not isinstance(taxonomy_item, dict):
            continue
        item["aliases"] = sorted(set(str(alias).strip() for alias in taxonomy_item.get("aliases", []) if str(alias).strip()))
        item["topic_hints"] = sorted(set(str(topic).strip() for topic in taxonomy_item.get("topic_hints", []) if str(topic).strip()))
        item["description"] = str(taxonomy_item.get("description") or "").strip()
        item["status"] = str(taxonomy_item.get("status") or "active").strip() or "active"
    payload["generated_at"] = utc_now_iso()
    return payload


def rebuild_literature_tag_index(project_root: Path, *, generated_by: str = "literature-tagger") -> dict[str, Any]:
    records = load_literature_records(project_root)
    taxonomy_payload = load_yaml(literature_tag_taxonomy_path(project_root), default={})
    taxonomy_items = taxonomy_payload.get("items", {}) if isinstance(taxonomy_payload, dict) else {}
    payload = build_literature_tag_index(records, generated_by=generated_by, taxonomy_items=taxonomy_items if isinstance(taxonomy_items, dict) else {})
    write_yaml_if_changed(literature_tags_path(project_root), payload)
    return payload


def score_fuzzy_literature_match(existing: dict[str, Any], candidate: dict[str, Any]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    if normalize_title(existing.get("canonical_title", "")) == normalize_title(candidate.get("title", "")):
        score += 0.65
        reasons.append("normalized-title-match")
    if existing.get("year") and candidate.get("year") and existing["year"] == candidate["year"]:
        score += 0.1
        reasons.append("year-match")
    if first_author_key(existing.get("authors", [])) and first_author_key(existing.get("authors", [])) == first_author_key(candidate.get("authors", [])):
        score += 0.15
        reasons.append("author-prefix-match")
    if existing.get("site_fingerprint") and existing.get("site_fingerprint") == candidate.get("site_fingerprint"):
        score += 0.1
        reasons.append("site-fingerprint-match")
    return score, reasons


def score_fuzzy_repo_match(existing: dict[str, Any], candidate: dict[str, Any]) -> tuple[float, list[str]]:
    reasons: list[str] = []
    score = 0.0
    if slugify(existing.get("repo_name", ""), max_words=4) == slugify(candidate.get("repo_name", ""), max_words=4):
        score += 0.6
        reasons.append("repo-name-match")
    if existing.get("owner_name") and existing.get("owner_name") == candidate.get("owner_name"):
        score += 0.3
        reasons.append("owner-name-match")
    if set(existing.get("frameworks", [])) & set(candidate.get("frameworks", [])):
        score += 0.1
        reasons.append("framework-overlap")
    return score, reasons


def make_source_id(candidate: dict[str, Any]) -> str:
    if candidate.get("external_ids", {}).get("arxiv_id"):
        return f"lit-arxiv-{slugify(candidate['external_ids']['arxiv_id'], max_words=4)}"
    title = candidate.get("title", "literature")
    year = candidate.get("year") or "unknown"
    return f"lit-{year}-{slugify(title, max_words=6)}"


def make_repo_id(candidate: dict[str, Any]) -> str:
    owner_name = candidate.get("owner_name") or slugify(candidate.get("repo_name", "repo"), max_words=4)
    return f"repo-{slugify(owner_name, max_words=4)}"


def normalize_remote_url(url: str) -> str:
    if not url:
        return ""
    normalized = url.strip()
    normalized = normalized.replace("git@github.com:", "https://github.com/")
    normalized = re.sub(r"\.git$", "", normalized)
    if normalized.startswith("git://"):
        normalized = normalized.replace("git://", "https://", 1)
    if normalized.startswith("ssh://git@github.com/"):
        normalized = normalized.replace("ssh://git@github.com/", "https://github.com/", 1)
    return canonicalize_url(normalized)


def owner_name_from_remote(url: str) -> str:
    normalized = normalize_remote_url(url)
    parsed = urlparse(normalized)
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2:
        return f"{parts[-2]}-{parts[-1]}"
    return ""


def copytree_filtered(src: Path, dst: Path) -> None:
    def ignore(path: str, names: list[str]) -> set[str]:
        ignored = {
            ".git",
            ".hg",
            ".svn",
            "__pycache__",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            "node_modules",
            "checkpoints",
            "weights",
            "logs",
            "dist",
            "build",
        }
        return {name for name in names if name in ignored}

    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=ignore)


def git_remote_url(repo_path: Path) -> str:
    config = repo_path / ".git" / "config"
    if not config.exists():
        return ""
    text = config.read_text(encoding="utf-8", errors="ignore")
    match = re.search(r'url\s*=\s*(.+)', text)
    return normalize_remote_url(match.group(1).strip()) if match else ""


def git_head_commit(repo_path: Path) -> str:
    head = repo_path / ".git" / "HEAD"
    if not head.exists():
        return ""
    head_text = head.read_text(encoding="utf-8", errors="ignore").strip()
    if head_text.startswith("ref:"):
        ref_path = repo_path / ".git" / head_text.split(" ", 1)[1]
        if ref_path.exists():
            return ref_path.read_text(encoding="utf-8", errors="ignore").strip()
    return head_text


def _fallback_repo_files(repo_path: Path, *, max_depth: int = 6) -> list[Path]:
    ignored_dirs = {
        ".git",
        ".hg",
        ".svn",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "venv",
        "node_modules",
        "dist",
        "build",
        "checkpoints",
        "weights",
        "logs",
    }
    files: list[Path] = []
    repo_path = repo_path.resolve()
    for root, dirs, filenames in os.walk(repo_path):
        root_path = Path(root)
        try:
            rel_parts = root_path.relative_to(repo_path).parts
        except ValueError:
            rel_parts = ()
        if len(rel_parts) >= max_depth:
            dirs[:] = []
        else:
            dirs[:] = [name for name in dirs if name not in ignored_dirs]
        for filename in filenames:
            path = root_path / filename
            try:
                path.relative_to(repo_path)
            except ValueError:
                continue
            files.append(path)
    return files


def _fallback_repo_facts(repo_path: Path, *, max_depth: int = 6, entrypoint_limit: int = 24) -> dict[str, Any]:
    files = _fallback_repo_files(repo_path, max_depth=max_depth)
    ext_to_language = {
        ".py": "Python",
        ".ipynb": "Jupyter",
        ".rs": "Rust",
        ".cpp": "C++",
        ".cc": "C++",
        ".cxx": "C++",
        ".c": "C",
        ".hpp": "C++",
        ".h": "C/C++",
        ".cu": "CUDA",
        ".go": "Go",
        ".java": "Java",
        ".scala": "Scala",
        ".js": "JavaScript",
        ".jsx": "JavaScript",
        ".ts": "TypeScript",
        ".tsx": "TypeScript",
        ".sh": "Shell",
        ".bash": "Shell",
        ".zsh": "Shell",
        ".nix": "Nix",
        ".md": "Markdown",
        ".toml": "TOML",
        ".yaml": "YAML",
        ".yml": "YAML",
        ".json": "JSON",
    }
    language_counts: dict[str, int] = {}
    key_dirs: list[str] = []
    first_level_dirs: dict[str, int] = {}
    config_roots: set[str] = set()
    docs_dirs: set[str] = set()
    test_dirs: set[str] = set()
    frameworks: list[str] = []
    entrypoint_candidates: list[tuple[int, str, str]] = []
    repo_text_paths: list[Path] = []

    framework_markers = [
        ("PyTorch", ("torch", "pytorch")),
        ("Transformers", ("transformers", "huggingface", "hf download")),
        ("Diffusers", ("diffusers", "stable diffusion")),
        ("DeepSpeed", ("deepspeed",)),
        ("Accelerate", ("accelerate",)),
        ("LeRobot", ("lerobot",)),
        ("MuJoCo", ("mujoco",)),
        ("Isaac Lab", ("isaac lab", "isaaclab", "omni.isaac.lab")),
        ("Isaac Sim", ("isaac sim", "isaacsim", "omni.isaac")),
        ("ROS", ("ros2", "rclpy", "roslaunch", "catkin")),
        ("OpenCV", ("opencv", "cv2")),
        ("Gradio", ("gradio",)),
        ("Streamlit", ("streamlit",)),
        ("JAX", ("jax", "flax")),
        ("TensorFlow", ("tensorflow",)),
        ("Tyro", ("tyro",)),
        ("WandB", ("wandb",)),
        ("Pinocchio", ("pinocchio",)),
        ("ZeroMQ", ("zeromq", "zmq")),
        ("Nix", ("flake.nix", "nix/", "pkgs.", "mkShell")),
        ("Unitree SDK2", ("unitree", "sdk2")),
        ("uv", ("uv sync", "uv.lock", "[tool.uv")),
    ]

    def add_framework(name: str) -> None:
        if name not in frameworks:
            frameworks.append(name)

    for path in files:
        rel_path = path.relative_to(repo_path).as_posix()
        parts = rel_path.split("/")
        if len(parts) > 1 and parts[0]:
            first_level_dirs[parts[0]] = first_level_dirs.get(parts[0], 0) + 1
        suffix = path.suffix.lower()
        language = ext_to_language.get(suffix)
        if language:
            language_counts[language] = language_counts.get(language, 0) + 1
        elif path.name == "Dockerfile":
            language_counts["Docker"] = language_counts.get("Docker", 0) + 1

        lowered_path = rel_path.lower()
        if any(token in lowered_path for token in ("config", "configs", "conf/", "cfg", ".yaml", ".yml", ".toml", ".json")):
            config_roots.add(parts[0] if parts else rel_path)
        if any(token in lowered_path for token in ("docs/", "doc/", "readme", "examples/", "example/")):
            docs_dirs.add(parts[0] if parts else rel_path)
        if any(token in lowered_path for token in ("tests/", "test/", "_test.", "test_")):
            test_dirs.add(parts[0] if parts else rel_path)

        is_shell = suffix in {".sh", ".bash", ".zsh"}
        is_python = suffix == ".py"
        executable_name = path.stem.lower()
        in_scripts = "scripts/" in lowered_path or lowered_path.startswith("scripts/")
        priority = None
        kind = ""
        if is_shell:
            priority = 0 if any(token in executable_name for token in ("train", "eval", "deploy", "serve", "run")) else 2
            kind = "shell-script"
        elif is_python and in_scripts:
            priority = 1
            kind = "python-script"
        elif is_python and executable_name in {"main", "app", "train", "eval", "deploy", "serve"}:
            priority = 2
            kind = "python-entrypoint"
        elif path.name == "pyproject.toml":
            priority = 4
            kind = "package-config"
        if priority is not None:
            entrypoint_candidates.append((priority, rel_path, kind))

        if path.name.lower().startswith("readme") or path.suffix.lower() in {".md", ".toml", ".txt", ".yaml", ".yml", ".py", ".sh", ".nix"}:
            repo_text_paths.append(path)

    for name, _count in sorted(first_level_dirs.items(), key=lambda item: (-item[1], item[0])):
        if name.startswith("."):
            continue
        if name not in key_dirs:
            key_dirs.append(name)
        if len(key_dirs) >= 8:
            break

    for path in repo_text_paths[:40]:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")[:12000].lower()
        except OSError:
            continue
        text = clean_text(text)
        for framework_name, markers in framework_markers:
            if any(marker in text for marker in markers):
                add_framework(framework_name)

    primary_language = ""
    filtered_language_counts = {
        name: count
        for name, count in language_counts.items()
        if name not in {"Markdown", "YAML", "JSON", "TOML"}
    }
    if filtered_language_counts:
        primary_language = max(filtered_language_counts.items(), key=lambda item: (item[1], item[0]))[0]
    elif language_counts:
        primary_language = max(language_counts.items(), key=lambda item: (item[1], item[0]))[0]

    repo_type_hint = "Research software repository"
    if {"src", "scripts", "baselines"} & set(first_level_dirs):
        repo_type_hint = "Mixed-language robotics or systems monorepo"
    elif {"src", "scripts", "real"} & set(first_level_dirs):
        repo_type_hint = "Robotics training and deployment repository"
    elif "notebooks" in first_level_dirs or "examples" in first_level_dirs:
        repo_type_hint = "Research codebase with runnable examples"
    elif primary_language == "Python":
        repo_type_hint = "Python research repository"

    entrypoints: list[dict[str, Any]] = []
    seen_entrypoints: set[str] = set()
    for _priority, rel_path, kind in sorted(entrypoint_candidates, key=lambda item: (item[0], item[1])):
        if rel_path in seen_entrypoints:
            continue
        seen_entrypoints.add(rel_path)
        entrypoints.append({"path": rel_path, "kind": kind})
        if len(entrypoints) >= entrypoint_limit:
            break

    subsystems: list[dict[str, Any]] = []
    for dir_name in key_dirs[:6]:
        if dir_name in {"assets", "docs", "examples"}:
            continue
        child_names = sorted(
            {
                child.name
                for child in (repo_path / dir_name).iterdir()
                if child.is_dir() and not child.name.startswith(".")
            }
        )[:8] if (repo_path / dir_name).exists() else []
        subsystems.append({"path": dir_name, "children": child_names})

    return {
        "repo_name": repo_path.name,
        "repo_type_hint": repo_type_hint,
        "primary_language": primary_language or "unknown",
        "framework_hints": frameworks,
        "entrypoints": entrypoints,
        "key_dirs": key_dirs,
        "config_roots": sorted(config_roots),
        "docs_dirs": sorted(docs_dirs),
        "test_dirs": sorted(test_dirs),
        "subsystems": subsystems,
    }


def load_legacy_repo_facts(project_root: Path, repo_path: Path, *, max_depth: int = 6, entrypoint_limit: int = 24) -> dict[str, Any]:
    scanner_path = project_root / ".agents" / "skills" / "research-repo-architect" / "scripts" / "scan_repo.py"
    if not scanner_path.exists():
        return _fallback_repo_facts(repo_path, max_depth=max_depth, entrypoint_limit=entrypoint_limit)
    scan_dir = scanner_path.parent
    sys.path.insert(0, str(scan_dir))
    try:
        spec = importlib.util.spec_from_file_location("legacy_scan_repo", scanner_path)
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Could not load legacy repo scanner from {scanner_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        files = module.iter_files(repo_path, max_depth=max_depth)
        return module.build_facts(repo_path, files, entrypoint_limit=entrypoint_limit)
    except FileNotFoundError:
        return _fallback_repo_facts(repo_path, max_depth=max_depth, entrypoint_limit=entrypoint_limit)
    finally:
        if str(scan_dir) in sys.path:
            sys.path.remove(str(scan_dir))


def read_text_excerpt(path: Path, limit: int = 4000) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")[:limit]


def _default_wiki_index_markdown() -> str:
    return (
        "# Research Wiki Index\n\n"
        "This index is generated from `doc/research/library` and `doc/research/programs`.\n"
    )


def _default_wiki_log_markdown() -> str:
    return (
        "# Research Wiki Log\n\n"
        "Append-only operational log for wiki/query/lint events.\n"
    )


def ensure_wiki_workspace(project_root: Path) -> None:
    ensure_dir(wiki_root(project_root))
    ensure_dir(wiki_queries_root(project_root))
    ensure_dir(wiki_lint_root(project_root))
    if not wiki_index_path(project_root).exists():
        write_text_if_changed(wiki_index_path(project_root), _default_wiki_index_markdown())
    if not wiki_log_path(project_root).exists():
        write_text_if_changed(wiki_log_path(project_root), _default_wiki_log_markdown())


def _markdown_single_line(value: Any, *, fallback: str = "") -> str:
    text = clean_text(str(value or ""))
    text = text.replace("\n", " ").replace("|", "/")
    return text if text else fallback


def _coerce_event_timestamp(value: str | datetime | None = None) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc).replace(microsecond=0)
        return value.astimezone(timezone.utc).replace(microsecond=0)
    parsed = parse_iso_datetime(value) if value is not None else None
    if parsed is not None:
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0)
    return datetime.now(timezone.utc).replace(microsecond=0)


def _serialize_log_value(value: Any) -> str:
    if isinstance(value, (list, tuple, dict)):
        return _markdown_single_line(json.dumps(value, ensure_ascii=False, sort_keys=True))
    return _markdown_single_line(value)


def _relative_display_path(path: Path, project_root: Path) -> str:
    try:
        return path.relative_to(project_root).as_posix()
    except ValueError:
        return path.as_posix()


def _compact_summary_line(text: str, *, limit: int = 180, fallback: str = "No summary available.") -> str:
    cleaned = _markdown_single_line(text)
    if not cleaned:
        return fallback
    if len(cleaned) <= limit:
        return cleaned
    trimmed = cleaned[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{trimmed or cleaned[:limit]}..."


def append_wiki_log_event(
    project_root: Path,
    event_type: str,
    title: str,
    *,
    summary: str = "",
    metadata: dict[str, Any] | None = None,
    occurred_at: str | datetime | None = None,
    generated_by: str = "llm-wiki",
) -> Path:
    ensure_wiki_workspace(project_root)
    timestamp = _coerce_event_timestamp(occurred_at)
    event_type_norm = re.sub(r"[^a-z0-9._-]+", "-", _markdown_single_line(event_type, fallback="event").lower()).strip("-") or "event"
    title_norm = _markdown_single_line(title, fallback="untitled")
    summary_norm = _compact_summary_line(summary, limit=220, fallback="")
    heading = f"## [{timestamp.strftime('%Y-%m-%d')}] {event_type_norm} | {title_norm}"

    entry_lines = [
        heading,
        f"- timestamp: {timestamp.isoformat()}",
        f"- type: {event_type_norm}",
        f"- title: {title_norm}",
        f"- generated_by: {_markdown_single_line(generated_by, fallback='unknown')}",
    ]
    if summary_norm:
        entry_lines.append(f"- summary: {summary_norm}")
    for raw_key, raw_value in sorted((metadata or {}).items(), key=lambda item: str(item[0])):
        key = re.sub(r"[^a-z0-9._-]+", "-", str(raw_key).strip().lower()).strip("-") or "meta"
        value = _serialize_log_value(raw_value)
        if value:
            entry_lines.append(f"- {key}: {value}")
    entry_lines.append("")

    path = wiki_log_path(project_root)
    existing = path.read_text(encoding="utf-8") if path.exists() else _default_wiki_log_markdown()
    if not existing.endswith("\n"):
        existing += "\n"
    existing += "\n".join(entry_lines)
    write_text_if_changed(path, existing)
    return path


def _load_query_artifact_summary(path: Path) -> tuple[str, str]:
    title = path.stem
    summary = ""
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return title, "Unreadable query artifact."
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            title = stripped[2:].strip() or title
            break
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("- query:"):
            summary = stripped.split(":", 1)[1].strip()
            break
    if not summary:
        for line in text.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or stripped.startswith("- "):
                continue
            summary = stripped
            break
    return _markdown_single_line(title, fallback=path.stem), _compact_summary_line(summary)


def rebuild_wiki_index_markdown(project_root: Path) -> Path:
    ensure_wiki_workspace(project_root)
    generated_at = utc_now_iso()

    literature_root = research_root(project_root) / "library" / "literature"
    repo_root_dir = research_root(project_root) / "library" / "repos"
    programs_dir = research_root(project_root) / "programs"

    literature_payload = load_index(literature_index_path(project_root), "literature-index", "literature-corpus-builder")
    repo_payload = load_index(repo_index_path(project_root), "repo-index", "repo-cataloger")

    literature_items = literature_payload.get("items", {}) if isinstance(literature_payload, dict) else {}
    repo_items = repo_payload.get("items", {}) if isinstance(repo_payload, dict) else {}
    if not isinstance(literature_items, dict):
        literature_items = {}
    if not isinstance(repo_items, dict):
        repo_items = {}

    literature_dirs = (
        sorted(path for path in literature_root.iterdir() if path.is_dir() and (path / "metadata.yaml").exists())
        if literature_root.exists()
        else []
    )
    repo_dirs = (
        sorted(path for path in repo_root_dir.iterdir() if path.is_dir() and (path / "summary.yaml").exists())
        if repo_root_dir.exists()
        else []
    )
    program_dirs = (
        sorted(path for path in programs_dir.iterdir() if path.is_dir() and not path.name.startswith("."))
        if programs_dir.exists()
        else []
    )

    lines: list[str] = [
        "# Research Wiki Index",
        "",
        f"_Generated at: {generated_at}_",
        "",
        "## Snapshot",
        f"- literature: index={len(literature_items)}, canonical_dirs={len(literature_dirs)}",
        f"- repos: index={len(repo_items)}, canonical_dirs={len(repo_dirs)}",
        f"- programs: {len(program_dirs)}",
        "",
        "## Literature",
    ]

    if literature_items:
        for lit_id in sorted(literature_items):
            item = literature_items.get(lit_id)
            if not isinstance(item, dict):
                continue
            title = _markdown_single_line(item.get("canonical_title"), fallback=lit_id)
            year = str(item.get("year") or "").strip()
            summary = _compact_summary_line(str(item.get("short_summary") or ""), fallback="No literature summary yet.")
            prefix = f"{year} · " if year else ""
            lines.append(f"- `{lit_id}`: {prefix}{title} - {summary}")
    else:
        lines.append("- No literature entries indexed yet.")

    lines.extend(["", "## Repositories"])
    if repo_items:
        for repo_id in sorted(repo_items):
            item = repo_items.get(repo_id)
            if not isinstance(item, dict):
                continue
            repo_name = _markdown_single_line(item.get("repo_name"), fallback=repo_id)
            summary = _compact_summary_line(str(item.get("short_summary") or ""), fallback="No repository summary yet.")
            lines.append(f"- `{repo_id}`: {repo_name} - {summary}")
    else:
        lines.append("- No repository entries indexed yet.")

    lines.extend(["", "## Programs"])
    if program_dirs:
        for program_dir in program_dirs:
            charter = load_yaml(program_dir / "charter.yaml", default={}, allow_simple_fallback=True)
            state = load_yaml(program_dir / "workflow" / "state.yaml", default={}, allow_simple_fallback=True)
            charter = charter if isinstance(charter, dict) else {}
            state = state if isinstance(state, dict) else {}
            program_id = _markdown_single_line(charter.get("program_id"), fallback=program_dir.name)
            stage = _markdown_single_line(state.get("stage"), fallback="unknown")
            question = _compact_summary_line(str(charter.get("question") or ""), fallback="")
            goal = _compact_summary_line(str(charter.get("goal") or ""), fallback="")
            one_line = question or goal or "No charter summary yet."
            lines.append(f"- `{program_id}`: stage={stage} - {one_line}")
    else:
        lines.append("- No programs found.")

    query_files = (
        sorted(wiki_queries_root(project_root).glob("*.md"), key=lambda item: item.name, reverse=True)
        if wiki_queries_root(project_root).exists()
        else []
    )
    lines.extend(["", "## Queries"])
    if query_files:
        for query_path in query_files[:20]:
            title, summary = _load_query_artifact_summary(query_path)
            lines.append(f"- `{query_path.name}`: {title} - {summary}")
    else:
        lines.append("- No query artifacts yet.")

    lint_path = wiki_lint_latest_path(project_root)
    lines.extend(["", "## Lint"])
    if lint_path.exists():
        lint_text = lint_path.read_text(encoding="utf-8", errors="ignore")
        status_match = re.search(r"^- status:\s*(.+)$", lint_text, flags=re.MULTILINE)
        issues_match = re.search(r"^- total_issues:\s*(\d+)$", lint_text, flags=re.MULTILINE)
        status = _markdown_single_line(status_match.group(1) if status_match else "UNKNOWN")
        total_issues = _markdown_single_line(issues_match.group(1) if issues_match else "unknown")
        lines.append(f"- latest: `{_relative_display_path(lint_path, project_root)}` (status={status}, issues={total_issues})")
    else:
        lines.append("- No lint report yet.")

    lines.append("")
    write_text_if_changed(wiki_index_path(project_root), "\n".join(lines))
    return wiki_index_path(project_root)


def write_query_artifact(
    project_root: Path,
    query_text: str,
    result_markdown: str,
    *,
    title: str = "",
    query_type: str = "query",
    metadata: dict[str, Any] | None = None,
    occurred_at: str | datetime | None = None,
    generated_by: str = "llm-wiki",
) -> Path:
    ensure_wiki_workspace(project_root)
    timestamp = _coerce_event_timestamp(occurred_at)
    query_line = _markdown_single_line(query_text, fallback="(empty-query)")
    title_line = _markdown_single_line(title, fallback="")
    if not title_line:
        title_line = _compact_summary_line(query_line, limit=80, fallback="untitled-query")
    query_type_norm = re.sub(r"[^a-z0-9._-]+", "-", _markdown_single_line(query_type, fallback="query").lower()).strip("-") or "query"
    artifact_slug = slugify(title_line, max_words=8)
    artifact_name = f"{timestamp.strftime('%Y%m%d-%H%M%S')}-{artifact_slug}.md"
    artifact_path = wiki_queries_root(project_root) / artifact_name
    suffix = 2
    while artifact_path.exists():
        artifact_path = wiki_queries_root(project_root) / f"{timestamp.strftime('%Y%m%d-%H%M%S')}-{artifact_slug}-{suffix}.md"
        suffix += 1

    artifact_lines = [
        f"# {title_line}",
        "",
        f"- timestamp: {timestamp.isoformat()}",
        f"- type: {query_type_norm}",
        f"- query: {query_line}",
        f"- generated_by: {_markdown_single_line(generated_by, fallback='llm-wiki')}",
    ]
    for raw_key, raw_value in sorted((metadata or {}).items(), key=lambda item: str(item[0])):
        key = re.sub(r"[^a-z0-9._-]+", "-", str(raw_key).strip().lower()).strip("-") or "meta"
        value = _serialize_log_value(raw_value)
        if value:
            artifact_lines.append(f"- {key}: {value}")
    artifact_lines.extend(
        [
            "",
            "## Result",
            "",
            result_markdown.strip() or "_No result content provided._",
            "",
        ]
    )
    write_text_if_changed(artifact_path, "\n".join(artifact_lines))

    log_metadata = dict(metadata or {})
    log_metadata.update(
        {
            "query": query_line,
            "artifact_path": _relative_display_path(artifact_path, project_root),
        }
    )
    append_wiki_log_event(
        project_root,
        query_type_norm,
        title_line,
        summary=query_line,
        metadata=log_metadata,
        occurred_at=timestamp,
        generated_by=generated_by,
    )
    rebuild_wiki_index_markdown(project_root)
    return artifact_path


def lint_wiki_workspace(project_root: Path, *, generated_by: str = "llm-wiki") -> Path:
    ensure_wiki_workspace(project_root)
    generated_at = utc_now_iso()

    programs_dir = research_root(project_root) / "programs"
    literature_root = research_root(project_root) / "library" / "literature"
    repos_root = research_root(project_root) / "library" / "repos"

    missing_reporting_events: list[str] = []
    if programs_dir.exists():
        for program_dir in sorted(path for path in programs_dir.iterdir() if path.is_dir() and not path.name.startswith(".")):
            if not (program_dir / "workflow" / "reporting-events.yaml").exists():
                missing_reporting_events.append(program_dir.name)

    literature_dirs = (
        sorted(path for path in literature_root.iterdir() if path.is_dir() and (path / "metadata.yaml").exists())
        if literature_root.exists()
        else []
    )
    repo_dirs = (
        sorted(path for path in repos_root.iterdir() if path.is_dir() and (path / "summary.yaml").exists())
        if repos_root.exists()
        else []
    )

    literature_index_payload = load_index(literature_index_path(project_root), "literature-index", "literature-corpus-builder")
    repo_index_payload = load_index(repo_index_path(project_root), "repo-index", "repo-cataloger")

    literature_items = literature_index_payload.get("items", {}) if isinstance(literature_index_payload, dict) else {}
    repo_items = repo_index_payload.get("items", {}) if isinstance(repo_index_payload, dict) else {}
    literature_index_count = len(literature_items) if isinstance(literature_items, dict) else 0
    repo_index_count = len(repo_items) if isinstance(repo_items, dict) else 0

    literature_count_mismatch = literature_index_count != len(literature_dirs)
    repo_count_mismatch = repo_index_count != len(repo_dirs)

    missing_literature_notes = [path.name for path in literature_dirs if not (path / "note.md").exists()]
    missing_repo_notes = [path.name for path in repo_dirs if not (path / "repo-notes.md").exists()]

    total_issues = (
        len(missing_reporting_events)
        + (1 if literature_count_mismatch else 0)
        + (1 if repo_count_mismatch else 0)
        + len(missing_literature_notes)
        + len(missing_repo_notes)
    )
    status = "PASS" if total_issues == 0 else "FAIL"

    lines: list[str] = [
        "# Wiki Lint Report",
        "",
        f"_Generated at: {generated_at}_",
        "",
        "## Summary",
        f"- status: {status}",
        f"- generated_by: {_markdown_single_line(generated_by, fallback='llm-wiki')}",
        f"- total_issues: {total_issues}",
        "",
        "## Missing Program Reporting Events",
    ]
    if missing_reporting_events:
        for program_id in missing_reporting_events:
            lines.append(f"- `{program_id}` is missing `workflow/reporting-events.yaml`.")
    else:
        lines.append("- No missing `reporting-events.yaml` files.")

    lines.extend(
        [
            "",
            "## Library Index Count Mismatch",
            f"- literature: index={literature_index_count}, canonical_dirs={len(literature_dirs)}, mismatch={str(literature_count_mismatch).lower()}",
            f"- repos: index={repo_index_count}, canonical_dirs={len(repo_dirs)}, mismatch={str(repo_count_mismatch).lower()}",
            "",
            "## Missing Canonical Notes",
        ]
    )
    if missing_literature_notes:
        for entry_id in missing_literature_notes:
            lines.append(f"- literature `{entry_id}` is missing `note.md`.")
    else:
        lines.append("- All canonical literature entries include `note.md`.")
    if missing_repo_notes:
        for entry_id in missing_repo_notes:
            lines.append(f"- repo `{entry_id}` is missing `repo-notes.md`.")
    else:
        lines.append("- All canonical repo entries include `repo-notes.md`.")
    lines.append("")

    report_path = wiki_lint_latest_path(project_root)
    write_text_if_changed(report_path, "\n".join(lines))
    rebuild_wiki_index_markdown(project_root)
    return report_path


def bootstrap_workspace(project_root: Path) -> None:
    ensure_dir(raw_root(project_root))
    for directory in (
        research_root(project_root) / "intake" / "papers" / "downloads",
        research_root(project_root) / "intake" / "repos" / "downloads",
        research_root(project_root) / "library" / "literature",
        research_root(project_root) / "library" / "repos",
        research_root(project_root) / "library" / "search" / "results",
        research_root(project_root) / "library" / "benchmarks",
        research_root(project_root) / "memory" / "history",
        research_root(project_root) / "programs",
        wiki_queries_root(project_root),
        wiki_lint_root(project_root),
    ):
        ensure_dir(directory)
    paths_with_defaults: list[tuple[Path, dict[str, Any]]] = [
        (pending_paper_reviews_path(project_root), blank_list_document("pending-paper-reviews", "research-conductor")),
        (resolved_paper_reviews_path(project_root), blank_list_document("resolved-paper-reviews", "research-conductor")),
        (pending_repo_reviews_path(project_root), blank_list_document("pending-repo-reviews", "research-conductor")),
        (resolved_repo_reviews_path(project_root), blank_list_document("resolved-repo-reviews", "research-conductor")),
        (literature_index_path(project_root), blank_index("literature-index", "literature-corpus-builder")),
        (
            literature_graph_path(project_root),
            {
                **yaml_default("literature-graph", "literature-corpus-builder"),
                "nodes": [],
                "edges": [],
            },
        ),
        (literature_tags_path(project_root), blank_index("literature-tags", "literature-tagger")),
        (
            literature_tag_taxonomy_path(project_root),
            {
                **yaml_default("literature-tag-taxonomy", "literature-tagger", status="active", confidence=0.8),
                "policy": {
                    "canonical_style": "lowercase-hyphen-slug",
                    "unknown_tag_policy": "allow-with-lint",
                    "notes": "Canonical tags should be short, reusable, and stable across papers.",
                },
                "items": {},
            },
        ),
        (repo_index_path(project_root), blank_index("repo-index", "repo-cataloger")),
        (
            research_root(project_root) / "library" / "benchmarks" / "index.yaml",
            blank_index("benchmark-index", "research-conductor"),
        ),
        (
            research_root(project_root) / "memory" / "user-profile.yaml",
            {
                **yaml_default("user-profile", "research-conductor", status="active"),
                "research_interests": [],
                "constraints": {"compute": "", "data": "", "hardware": ""},
                "available_resources": [],
                "language_preference": "zh-CN",
                "risk_preference": "balanced",
                "long_term_topics": [],
            },
        ),
        (
            research_root(project_root) / "memory" / "skill-preferences.yaml",
            {
                **yaml_default("skill-preferences", "research-conductor", status="active"),
                "preferences": {
                    "literature-corpus-builder": {"confirm_fuzzy_duplicates": True},
                    "idea-review-board": {"novelty_bar": "high"},
                    "method-designer": {"prefer_existing_repo": True},
                },
            },
        ),
        (domain_profile_path(project_root), blank_domain_profile()),
        (runtime_memory_path(project_root), blank_runtime_registry()),
    ]
    for path, payload in paths_with_defaults:
        if not path.exists():
            write_yaml_if_changed(path, payload)
    ensure_wiki_workspace(project_root)


def bootstrap_program(project_root: Path, program_id: str, *, question: str, goal: str, constraints: dict[str, str] | None = None) -> Path:
    program_root = research_root(project_root) / "programs" / program_id
    ensure_dir(program_root)
    ensure_dir(program_root / "workflow")
    ensure_dir(program_root / "evidence")
    ensure_dir(program_root / "ideas")
    ensure_dir(program_root / "design")
    ensure_dir(program_root / "experiments")
    ensure_dir(program_root / "weekly")
    defaults = {
        program_root / "charter.yaml": {
            **yaml_default(program_id, "research-conductor", status="active"),
            "program_id": program_id,
            "question": question,
            "goal": goal,
            "constraints": constraints or {"compute": "", "data": "", "hardware": ""},
            "success_metrics": [],
            "non_goals": [],
        },
        program_root / "workflow" / "state.yaml": {
            **yaml_default(f"{program_id}-state", "research-conductor", status="active"),
            "program_id": program_id,
            "stage": "problem-framing",
            "active_idea_id": "",
            "selected_idea_id": "",
            "selected_repo_id": "",
        },
        program_root / "workflow" / "reporting-events.yaml": blank_reporting_events(program_id),
        program_root / "workflow" / "open-questions.yaml": blank_list_document(f"{program_id}-open-questions", "research-conductor"),
        program_root / "workflow" / "evidence-requests.yaml": blank_list_document(f"{program_id}-evidence-requests", "research-conductor"),
        program_root / "workflow" / "preferences.yaml": {
            **yaml_default(f"{program_id}-preferences", "research-conductor"),
            "preferences": {},
        },
        program_root / "evidence" / "literature-map.yaml": {
            **yaml_default(f"{program_id}-literature-map", "literature-analyst", status="draft", confidence=0.0),
            "program_id": program_id,
            "retrieval": {"query_text": "", "query_terms": [], "query_tags": [], "selected_sources": []},
            "problem_frame": "",
            "clusters": [],
            "agreements": [],
            "conflicts": [],
            "gaps": [],
            "candidate_directions": [],
            "paper_refs": [],
        },
        program_root / "ideas" / "index.yaml": blank_index(f"{program_id}-ideas", "idea-forge"),
        program_root / "design" / "selected-idea.yaml": {
            **yaml_default(f"{program_id}-selected-idea", "method-designer", status="draft", confidence=0.0),
            "idea_id": "",
        },
        program_root / "design" / "repo-choice.yaml": {
            **yaml_default(f"{program_id}-repo-choice", "method-designer", status="draft", confidence=0.0),
            "selected_repo": "",
            "alternatives": [],
            "selection_reason": "",
            "edit_surfaces": [],
            "risks": [],
        },
        program_root / "design" / "interfaces.yaml": {
            **yaml_default(f"{program_id}-interfaces", "method-designer", status="draft", confidence=0.0),
            "new_modules": [],
            "modified_modules": [],
            "config_keys": [],
            "metrics": [],
            "artifacts": [],
        },
        program_root / "experiments" / "matrix.yaml": {
            **yaml_default(f"{program_id}-matrix", "method-designer", status="draft", confidence=0.0),
            "baseline": [],
            "main_experiment": [],
            "ablations": [],
            "success_criteria": [],
            "stop_conditions": [],
        },
    }
    for path, payload in defaults.items():
        if not path.exists():
            write_yaml_if_changed(path, payload)
    decision_log = program_root / "workflow" / "decision-log.md"
    if not decision_log.exists():
        write_text_if_changed(
            decision_log,
            "# Decision Log\n\n"
            f"- {utc_now_iso()}: program `{program_id}` created.\n",
        )
    system_design = program_root / "design" / "system-design.md"
    if not system_design.exists():
        write_text_if_changed(
            system_design,
            "# System Design\n\n"
            "## Goal\n\n"
            f"- Program: `{program_id}`\n\n"
            "## Architecture\n\n"
            "- Pending selection.\n",
        )
    runbook = program_root / "experiments" / "runbook.md"
    if not runbook.exists():
        write_text_if_changed(
            runbook,
            "# Experiment Runbook\n\n"
            "- Pending method design.\n",
        )
    return program_root


def rebuild_literature_index(project_root: Path, *, generated_by: str = "literature-corpus-builder") -> dict[str, Any]:
    records = load_literature_records(project_root)
    payload = blank_index("literature-index", generated_by)
    payload["inputs"] = [f"lit:{record['id']}" for record in records if record.get("id")]
    for record in records:
        source_id = str(record.get("id") or "")
        if not source_id:
            continue
        payload["items"][source_id] = {
            "id": source_id,
            "source_kind": record.get("source_kind", "paper"),
            "canonical_title": record.get("canonical_title", ""),
            "short_summary": record.get("short_summary", ""),
            "authors": record.get("authors", []),
            "year": record.get("year"),
            "canonical_url": record.get("canonical_url", ""),
            "site_fingerprint": record.get("site_fingerprint", ""),
            "external_ids": record.get("external_ids", {}),
            "aliases": record.get("aliases", []),
            "topics": record.get("topics", []),
            "tags": record.get("tags", []),
            "source_paths": record.get("source_paths", {}),
            "file_hashes": record.get("file_hashes", []),
        }
    payload["generated_at"] = utc_now_iso()
    write_yaml_if_changed(literature_index_path(project_root), payload)
    write_yaml_if_changed(literature_graph_path(project_root), build_literature_graph(records, generated_by=generated_by))
    return payload


def load_repo_summaries(project_root: Path) -> list[dict[str, Any]]:
    repo_root = research_root(project_root) / "library" / "repos"
    records: list[dict[str, Any]] = []
    for summary_path in sorted(repo_root.glob("*/summary.yaml")):
        payload = load_yaml(summary_path, default={})
        if isinstance(payload, dict) and payload.get("repo_id"):
            records.append(payload)
    return records


def rebuild_repo_index(project_root: Path) -> dict[str, Any]:
    records = load_repo_summaries(project_root)
    payload = blank_index("repo-index", "repo-cataloger")
    payload["inputs"] = [f"repo:{record.get('repo_id') or record.get('id')}" for record in records if record.get("repo_id") or record.get("id")]
    for record in records:
        repo_id = str(record.get("repo_id") or record.get("id") or "")
        if not repo_id:
            continue
        payload["items"][repo_id] = {
            "id": repo_id,
            "repo_name": record.get("repo_name", ""),
            "short_summary": record.get("short_summary", ""),
            "canonical_remote": record.get("canonical_remote", ""),
            "owner_name": record.get("owner_name", ""),
            "aliases": record.get("aliases", []),
            "import_type": record.get("import_type", ""),
            "frameworks": record.get("frameworks", []),
            "entrypoints": record.get("entrypoints", []),
            "topics": record.get("topics", []),
            "tags": record.get("tags", []),
        }
    payload["generated_at"] = utc_now_iso()
    write_yaml_if_changed(repo_index_path(project_root), payload)
    return payload
