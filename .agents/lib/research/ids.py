"""Canonical v2 unit id helpers."""

from __future__ import annotations

import hashlib
import re

from .slugs import KEYWORD_BLACKLIST, STOPWORDS, slugify

UNIT_KIND_PREFIXES = {
    "paper": "p",
    "repo": "r",
    "blog": "b",
    "idea": "i",
    "experiment": "x",
}
COMPACT_UNIT_ID_MAX_WORDS = 3
COMPACT_UNIT_ID_MAX_CHARS = 18
COMPACT_UNIT_ID_HASH_LEN = 8
GREEK_LETTER_ALIASES = {
    "π": "pi",
    "Π": "pi",
    "ψ": "psi",
    "Ψ": "psi",
    "φ": "phi",
    "Φ": "phi",
    "α": "alpha",
    "Α": "alpha",
    "β": "beta",
    "Β": "beta",
    "γ": "gamma",
    "Γ": "gamma",
    "δ": "delta",
    "Δ": "delta",
    "λ": "lambda",
    "Λ": "lambda",
    "μ": "mu",
    "Μ": "mu",
    "σ": "sigma",
    "Σ": "sigma",
    "τ": "tau",
    "Τ": "tau",
    "ω": "omega",
    "Ω": "omega",
}


def build_unit_id(kind: str, title: str, source: str = "") -> str:
    return canonical_unit_id(kind, title=title, source=source)


def _unit_slug_seed(title: str, source: str = "") -> str:
    text = title.strip() or source.strip()
    if "://" in text:
        text = source.strip() or title.strip()
    text = re.sub(r"^\d{4}(?:[-/]\d{1,2}){1,2}\s+", "", text)
    for raw, alias in GREEK_LETTER_ALIASES.items():
        text = text.replace(raw, f" {alias} ")
    text = re.sub(r"([a-z])([A-Z][a-z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]{2,})([A-Z][a-z])", r"\1 \2", text)
    return text.strip()


def compact_unit_slug(seed: str, *, max_words: int = COMPACT_UNIT_ID_MAX_WORDS, max_chars: int = COMPACT_UNIT_ID_MAX_CHARS) -> str:
    words = (slugify(_unit_slug_seed(seed), max_words=12) or "item").split("-")
    preferred = [word for word in words if word not in STOPWORDS and word not in KEYWORD_BLACKLIST]
    candidate_words = preferred if preferred else [word for word in words if word not in STOPWORDS]
    chosen: list[str] = []
    for part in candidate_words or words:
        if len(chosen) >= max(1, max_words):
            break
        candidate = "-".join(chosen + [part]) if chosen else part
        if len(candidate) > max_chars:
            if chosen:
                continue
            return part[:max_chars].strip("-") or "item"
        chosen.append(part)
    if chosen:
        return "-".join(chosen)
    slug = "-".join((candidate_words or words)[:max(1, max_words)]) or "item"
    return slug[:max_chars].strip("-") or "item"


def canonical_unit_id(kind: str, *, title: str, source: str = "", hash_size: int = COMPACT_UNIT_ID_HASH_LEN) -> str:
    if kind not in UNIT_KIND_PREFIXES:
        raise SystemExit(f"Unsupported unit kind: {kind}")
    seed = title or source or kind
    slug_seed = title or source or kind
    prefix = UNIT_KIND_PREFIXES[kind]
    compact_slug = compact_unit_slug(slug_seed)
    short_hash = hashlib.sha1(seed.encode("utf-8")).hexdigest()[: max(6, hash_size)]
    return f"{prefix}-{compact_slug}-{short_hash}"


def canonical_unit_id_with_hash(kind: str, *, title: str, source: str = "", hash_value: str = "") -> str:
    if kind not in UNIT_KIND_PREFIXES:
        raise SystemExit(f"Unsupported unit kind: {kind}")
    compact_slug = compact_unit_slug(title or source or kind)
    normalized_hash = re.sub(r"[^0-9a-f]", "", hash_value.lower())[:16]
    if len(normalized_hash) < 6:
        return canonical_unit_id(kind, title=title, source=source)
    return f"{UNIT_KIND_PREFIXES[kind]}-{compact_slug}-{normalized_hash}"


def is_canonical_unit_id(kind: str, unit_id: str) -> bool:
    prefix = UNIT_KIND_PREFIXES.get(kind, "")
    if not prefix:
        return False
    return bool(re.fullmatch(rf"{re.escape(prefix)}-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{{6,16}}", unit_id.strip()))
