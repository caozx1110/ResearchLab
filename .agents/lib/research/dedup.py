"""Source normalization helpers used by duplicate detection."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse, urlunparse


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    netloc = parsed.netloc.lower()
    path = re.sub(r"/+", "/", parsed.path or "/")
    query_pairs = parse_qs(parsed.query, keep_blank_values=False)
    keep_keys = []
    if "arxiv.org" in netloc:
        arxiv_id = parse_arxiv_id(url)
        if arxiv_id:
            path = f"/abs/{arxiv_id}"
    elif "openreview.net" in netloc:
        keep_keys = ["id"]
    elif "doi.org" in netloc:
        keep_keys = []
    query = "&".join(f"{key}={query_pairs[key][0]}" for key in keep_keys if key in query_pairs)
    return urlunparse((scheme, netloc, path.rstrip("/") or "/", "", query, ""))


def parse_arxiv_id(value: str) -> str:
    match = re.search(r"(\d{4}\.\d{4,5}(?:v\d+)?)", value)
    return match.group(1) if match else ""


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
