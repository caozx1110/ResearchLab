#!/usr/bin/env python3
"""Shared helpers for paper-research-workbench scripts."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

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

TAG_RULES = [
    ("vision-language-action", "vla"),
    ("vla", "vla"),
    ("action tokenization", "action-tokenization"),
    ("tokenization", "action-tokenization"),
    ("hierarchical", "hierarchical-policy"),
    ("open-world", "open-world-generalization"),
    ("generalization", "generalization"),
    ("generalist", "generalist-robotics"),
    ("instruction", "instruction-following"),
    ("flow model", "flow-model"),
    ("policy", "policy-learning"),
    ("robot", "robot-control"),
    ("experience", "learning-from-experience"),
    ("language", "language-conditioned-control"),
]

TAG_LABELS_CN = {
    "vla": "Vision-Language-Action (VLA)",
    "action-tokenization": "动作 tokenization",
    "hierarchical-policy": "层级策略",
    "instruction-following": "指令跟随",
    "flow-model": "flow model",
    "policy-learning": "策略学习",
    "robot-control": "机器人控制",
    "generalist-robotics": "通用机器人",
    "open-world-generalization": "开放世界泛化",
    "learning-from-experience": "从经验中学习",
    "language-conditioned-control": "语言条件控制",
    "generalization": "泛化能力",
    "robotics-paper": "机器人论文",
}

TOPIC_LABELS_CN = {
    "vision-language-action": "Vision-Language-Action",
    "robot-learning": "机器人学习",
    "open-world-generalization": "开放世界泛化",
    "continual-learning": "持续学习",
    "robotics": "机器人研究",
}


def utc_now_iso() -> str:
    """Return UTC timestamp in ISO format without microseconds."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def find_project_root(start: Path) -> Path:
    resolved = start.resolve()
    for candidate in [resolved] + list(resolved.parents):
        if (candidate / "raw").exists() and (candidate / "doc").exists():
            return candidate
    raise FileNotFoundError(f"Could not locate project root from: {start}")


def find_skill_root(start: Path, skill_name: str = "paper-research-workbench") -> Path:
    resolved = start.resolve()
    for candidate in [resolved] + list(resolved.parents):
        if candidate.name == skill_name and (candidate / "SKILL.md").exists():
            return candidate
    raise FileNotFoundError(f"Could not locate skill root from: {start}")


def resolve_from_project_or_skill(
    candidate: str | Path,
    *,
    project_root: Path,
    skill_root: Path,
) -> Path:
    path = Path(candidate)
    if path.is_absolute():
        return path
    project_path = (project_root / path).resolve()
    if project_path.exists():
        return project_path
    skill_path = (skill_root / path).resolve()
    if skill_path.exists():
        return skill_path
    return project_path


def clean_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = text.replace("\u200b", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def clean_title(text: str) -> str:
    text = text.replace("\\pi", "pi")
    text = text.replace("$", "")
    text = text.replace("{", "")
    text = text.replace("}", "")
    text = text.replace("_", "")
    return clean_text(text)


def slugify(text: str, *, max_words: int = 6) -> str:
    normalized = (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    )
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    words = [w for w in normalized.split() if w]
    if not words:
        return "paper"
    filtered = [w for w in words if w not in STOPWORDS]
    use_words = filtered if filtered else words
    return "-".join(use_words[:max_words])


def parse_author_string(raw: str) -> list[str]:
    if not raw:
        return []
    normalized = raw.replace(" and ", ";")
    if ";" in normalized:
        chunks = normalized.split(";")
    else:
        chunks = normalized.split(",")
    out: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        name = clean_text(chunk)
        if not name:
            continue
        name = (
            unicodedata.normalize("NFKD", name)
            .encode("ascii", "ignore")
            .decode("ascii")
        )
        name = re.sub(r"\s*\*+\s*$", "", name)
        name = re.sub(r"(?<=[A-Za-z])\d+", "", name)
        name = re.sub(r"^\d+", "", name)
        name = re.sub(r"\b\d+\b", "", name)
        name = re.sub(r"\s+", " ", name).strip()
        if len(name) < 2:
            continue
        if not any(ch.isalpha() for ch in name):
            continue
        if name not in seen:
            seen.add(name)
            out.append(name)
    return out


def extract_urls(text: str) -> list[str]:
    urls = re.findall(r"https?://[^\s\]\)]+", text)
    deduped: list[str] = []
    seen: set[str] = set()
    for url in urls:
        normalized = url.rstrip(".,;:")
        if normalized not in seen:
            seen.add(normalized)
            deduped.append(normalized)
    return deduped


def normalize_arxiv_id(value: str) -> str:
    if not value:
        return ""
    match = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", value)
    return match.group(1) if match else ""


def infer_year_from_arxiv_id(arxiv_id: str) -> int | None:
    match = re.match(r"^(\d{2})(\d{2})\.\d{4,5}(?:v\d+)?$", arxiv_id)
    if not match:
        return None
    return 2000 + int(match.group(1))


def infer_tags_topics(title: str, abstract: str) -> tuple[list[str], list[str]]:
    text = f"{title}\n{abstract}".lower()
    tags = {tag for keyword, tag in TAG_RULES if keyword in text}
    if not tags:
        tags.add("robotics-paper")

    topics: set[str] = set()
    if any(
        tag in tags
        for tag in (
            "vla",
            "action-tokenization",
            "hierarchical-policy",
            "instruction-following",
        )
    ):
        topics.add("vision-language-action")
    if any(
        tag in tags
        for tag in ("policy-learning", "robot-control", "generalist-robotics")
    ):
        topics.add("robot-learning")
    if "open-world-generalization" in tags:
        topics.add("open-world-generalization")
    if "learning-from-experience" in tags:
        topics.add("continual-learning")
    if not topics:
        topics.add("robotics")

    return sorted(tags), sorted(topics)


def make_paper_id(
    *,
    title: str,
    authors: list[str],
    year: int | None,
    fallback_stem: str,
) -> str:
    if authors:
        last_name = authors[0].split()[-1]
        author_slug = slugify(last_name, max_words=1)
    else:
        author_slug = slugify(fallback_stem, max_words=1)
    year_token = str(year) if year else "unknown"
    short_title = slugify(title or fallback_stem, max_words=6)
    return f"{author_slug}-{year_token}-{short_title}"


def load_yaml(path: Path) -> Any:
    if not path.exists():
        return None
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def yaml_text(payload: Any) -> str:
    return yaml.safe_dump(
        payload,
        sort_keys=False,
        allow_unicode=False,
        default_flow_style=False,
    )


def write_text_if_changed(path: Path, text: str) -> bool:
    ensure_dir(path.parent)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return False
    path.write_text(text, encoding="utf-8")
    return True


def write_yaml(path: Path, payload: Any) -> None:
    write_text_if_changed(path, yaml_text(payload))


def write_yaml_if_changed(path: Path, payload: Any) -> bool:
    return write_text_if_changed(path, yaml_text(payload))


def json_text(payload: Any, *, indent: int = 2) -> str:
    return json.dumps(payload, indent=indent, ensure_ascii=True) + "\n"


def write_json_if_changed(path: Path, payload: Any, *, indent: int = 2) -> bool:
    return write_text_if_changed(path, json_text(payload, indent=indent))


def file_sha256(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def normalize_title_key(title: str) -> str:
    normalized = (
        unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode("ascii")
    )
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    words = [word for word in normalized.split() if word and word not in STOPWORDS]
    return " ".join(words[:12])


def text_tokens(text: str) -> list[str]:
    normalized = (
        unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    )
    normalized = normalized.lower()
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    return [word for word in normalized.split() if len(word) > 2 and word not in STOPWORDS]


def split_sentences(text: str) -> list[str]:
    compact = clean_text(text)
    if not compact:
        return []
    sentences = re.split(r"(?<=[\.\?!])\s+(?=[A-Z0-9\"'])", compact)
    return [sentence.strip() for sentence in sentences if sentence.strip()]


def pick_sentence(text: str, keywords: list[str], fallback_index: int = 0) -> str:
    sentences = split_sentences(text)
    if not sentences:
        return ""
    lower_keywords = [keyword.lower() for keyword in keywords]
    for sentence in sentences:
        low = sentence.lower()
        if any(keyword in low for keyword in lower_keywords):
            return sentence
    if fallback_index < len(sentences):
        return sentences[fallback_index]
    return sentences[0]


def cn_label(value: str, mapping: dict[str, str]) -> str:
    return mapping.get(value, value)


def render_cn_labels(values: list[str], mapping: dict[str, str]) -> str:
    if not values:
        return "无"
    return "、".join(cn_label(value, mapping) for value in values)


def compact_text(text: str, max_len: int = 220) -> str:
    compact = " ".join(text.split())
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3].rstrip() + "..."


def make_identity_key(
    *,
    title: str,
    authors: list[str],
    year: int | None,
    arxiv_id: str,
) -> str:
    if arxiv_id:
        return f"arxiv:{arxiv_id}"
    first_author = slugify(authors[0], max_words=2) if authors else "unknown"
    year_token = str(year) if year else "unknown"
    return f"title:{normalize_title_key(title)}|author:{first_author}|year:{year_token}"


def relative_to_project(path: Path, project_root: Path) -> str:
    try:
        return str(path.resolve().relative_to(project_root.resolve()))
    except ValueError:
        return str(path.resolve())
