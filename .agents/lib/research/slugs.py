"""Slug and lightweight text normalization helpers."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

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


def simple_slug(text: str, fallback: str, *, limit: int = 64) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in str(text or "")).strip("-")
    return slug[:limit] or fallback


def normalize_ref_key(text: str) -> str:
    return slugify(text.strip(), max_words=12)


def parse_wikilinks(markdown: str) -> list[str]:
    targets: list[str] = []
    pattern = re.compile(r"(?<!!)\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]*)?\]\]")
    for match in pattern.finditer(markdown):
        if match.end() < len(markdown) and markdown[match.end()] == "(":
            continue
        target = match.group(1).strip()
        if target:
            targets.append(target)
    return targets


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


def normalize_list(values: Any) -> list[str]:
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        values = [values]
    return [str(item).strip() for item in values or [] if str(item).strip()]
