"""Deterministic record and passage retrieval primitives.

This module deliberately does not interpret or summarize research material.  It
only slices canonical text into stable passages and performs lexical ranking.
The SQLite cache lifecycle lives in :mod:`research.index`, where workspace path
and safety rules are available.
"""

from __future__ import annotations

import copy
import hashlib
import re
from typing import Any, Callable

from .relations import BLOCK_ID_RE

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+-]*|[^\W\x00-\x7f]+", re.IGNORECASE)
HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")

PASSAGE_MAX_CHARS = 900
PASSAGE_OVERLAP_CHARS = 160
PASSAGE_EXCERPT_CHARS = 320

# Repo source-code chunking: Python files split at def/class symbol boundaries,
# every other text file uses fixed overlapping line windows.
CODE_WINDOW_LINES = 40
CODE_WINDOW_OVERLAP_LINES = 8
CODE_SYMBOL_RE = re.compile(r"^([ \t]*)(?:async[ \t]+)?(def|class)[ \t]+([A-Za-z_][A-Za-z0-9_]*)")
_IDENTIFIER_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
_IDENTIFIER_PART_RE = re.compile(r"[A-Z]{2,}(?=[A-Z][a-z0-9])|[A-Z]?[a-z0-9]+|[A-Z]{2,}|[0-9]+")
CODE_IDENTIFIER_TERMS_MAX_CHARS = 2000

FIELD_WEIGHTS = {
    "title": 8,
    "summary": 5,
    "tags": 6,
    "topics": 6,
    "candidate_pools": 5,
    "payload": 2,
    "markdown": 1,
}

PASSAGE_FIELD_WEIGHTS = {
    "heading": 4,
    "text": 1,
}


def tokenize_query(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(str(text or ""))]


def _leaf_text(value: Any) -> list[str]:
    if isinstance(value, dict):
        items: list[str] = []
        for child in value.values():
            items.extend(_leaf_text(child))
        return items
    if isinstance(value, list):
        items = []
        for child in value:
            items.extend(_leaf_text(child))
        return items
    if value is None or isinstance(value, bool):
        return []
    return [str(value)]


def _read_markdown(paths: list[Any]) -> str:
    chunks: list[str] = []
    for path in paths:
        try:
            chunks.append(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError):
            continue
    return "\n".join(chunks)


def record_search_fields(record: dict[str, Any], *, markdown_paths: list[Any] | None = None) -> dict[str, str]:
    return {
        "title": str(record.get("title") or ""),
        "summary": str(record.get("summary") or ""),
        "tags": " ".join(str(item) for item in record.get("tags", []) if str(item).strip()),
        "topics": " ".join(str(item) for item in record.get("topics", []) if str(item).strip()),
        "candidate_pools": " ".join(str(item) for item in record.get("candidate_pools", []) if str(item).strip()),
        "payload": " ".join(_leaf_text(record.get("payload", {}))),
        "markdown": _read_markdown(markdown_paths or []),
    }


def score_record(record: dict[str, Any], query_tokens: list[str], *, markdown_paths: list[Any] | None = None) -> dict[str, Any]:
    fields = record_search_fields(record, markdown_paths=markdown_paths)
    score = 0
    reasons: list[str] = []
    for field, text in fields.items():
        lowered = text.lower()
        matched = [token for token in query_tokens if token in lowered]
        if not matched:
            continue
        weight = FIELD_WEIGHTS[field]
        score += weight * len(set(matched))
        reasons.append(f"{field}:{','.join(sorted(set(matched))[:3])}")
    return {"score": score, "reasons": reasons, "matched": score > 0}


def rank_records(
    records: list[dict[str, Any]],
    query: str,
    *,
    markdown_paths_for: Callable[[dict[str, Any]], list[Any]] | None = None,
) -> list[dict[str, Any]]:
    """Compatibility record ranking used by filter-only/review callers."""
    query_tokens = tokenize_query(query)
    if not query_tokens:
        return list(records)
    ranked: list[dict[str, Any]] = []
    for record in records:
        payload = score_record(record, query_tokens, markdown_paths=(markdown_paths_for(record) if markdown_paths_for else []))
        if not payload["matched"]:
            continue
        item = copy.deepcopy(record)
        item["_search_score"] = payload["score"]
        item["_search_reasons"] = payload["reasons"]
        ranked.append(item)
    ranked.sort(key=lambda item: (-int(item.get("_search_score") or 0), str(item.get("kind") or ""), str(item.get("title") or ""), str(item.get("id") or "")))
    return ranked


def _passage_id(unit_id: str, artifact: str, locator: str, text: str) -> str:
    payload = "\x00".join([unit_id, artifact, locator, text]).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _append_passage(
    passages: list[dict[str, Any]],
    *,
    record: dict[str, Any],
    artifact: str,
    locator: str,
    heading: str,
    line_start: int,
    line_end: int,
    text: str,
    source_digest: str,
) -> None:
    cleaned = text.strip()
    if not cleaned:
        return
    unit_id = str(record.get("id") or "")
    passages.append(
        {
            "passage_id": _passage_id(unit_id, artifact, locator, cleaned),
            "unit_id": unit_id,
            "kind": str(record.get("kind") or ""),
            "title": str(record.get("title") or ""),
            "summary": str(record.get("summary") or ""),
            "heading": heading,
            "text": cleaned,
            "artifact": artifact,
            "locator": locator,
            "line_start": line_start,
            "line_end": line_end,
            "source_digest": source_digest,
        }
    )


def _character_windows(text: str) -> list[str]:
    if len(text) <= PASSAGE_MAX_CHARS:
        return [text]
    step = PASSAGE_MAX_CHARS - PASSAGE_OVERLAP_CHARS
    windows: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + PASSAGE_MAX_CHARS)
        window = text[start:end].strip()
        if window:
            windows.append(window)
        if end == len(text):
            break
        start += step
    return windows


def markdown_passages(
    record: dict[str, Any],
    *,
    artifact: str,
    text: str,
    source_digest: str,
) -> list[dict[str, Any]]:
    """Split Markdown at headings/paragraphs without interpreting its content."""
    passages: list[dict[str, Any]] = []
    heading = ""
    block: list[str] = []
    block_start = 0
    fence_marker = ""
    lines = text.splitlines()

    def flush(line_end: int) -> None:
        nonlocal block, block_start
        if not block:
            return
        block_text = "\n".join(block).strip()
        windows = _character_windows(block_text)
        for index, window in enumerate(windows, start=1):
            suffix = f":part-{index}" if len(windows) > 1 else ""
            locator = f"{artifact}#L{block_start}-L{line_end}{suffix}"
            _append_passage(
                passages,
                record=record,
                artifact=artifact,
                locator=locator,
                heading=heading,
                line_start=block_start,
                line_end=line_end,
                text=window,
                source_digest=source_digest,
            )
        block = []
        block_start = 0

    for number, line in enumerate(lines, start=1):
        stripped = line.strip()
        fence_match = FENCE_RE.match(line)
        if fence_match and not fence_marker:
            if not block:
                block_start = number
            block.append(line)
            fence_marker = fence_match.group(1)
            continue
        if fence_match and fence_marker:
            candidate = fence_match.group(1)
            is_close = (
                candidate[0] == fence_marker[0]
                and len(candidate) >= len(fence_marker)
                and not fence_match.group(2).strip()
            )
            if is_close:
                block.append(line)
                fence_marker = ""
                continue
        if not fence_marker and stripped.startswith("^") and BLOCK_ID_RE.fullmatch(stripped[1:]):
            flush(number - 1)
            continue
        match = HEADING_RE.match(line) if not fence_marker else None
        if match:
            flush(number - 1)
            heading = match.group(2).strip()
            continue
        if not stripped and not fence_marker:
            flush(number - 1)
            continue
        if not block:
            block_start = number
        block.append(line)
    flush(len(lines))
    return passages


def extract_record_passages(
    record: dict[str, Any],
    *,
    record_artifact: str,
    record_digest: str,
    markdown_documents: list[dict[str, str]],
) -> list[dict[str, Any]]:
    """Create stable title/summary and Markdown passages for one canonical unit."""
    passages: list[dict[str, Any]] = []
    title = str(record.get("title") or "").strip()
    summary = str(record.get("summary") or "").strip()
    if title:
        _append_passage(
            passages,
            record=record,
            artifact=record_artifact,
            locator=f"{record_artifact}#title",
            heading="Title",
            line_start=0,
            line_end=0,
            text=title,
            source_digest=record_digest,
        )
    if summary and summary != title:
        _append_passage(
            passages,
            record=record,
            artifact=record_artifact,
            locator=f"{record_artifact}#summary",
            heading="Summary",
            line_start=0,
            line_end=0,
            text=summary,
            source_digest=record_digest,
        )
    for document in sorted(markdown_documents, key=lambda item: item["artifact"]):
        passages.extend(
            markdown_passages(
                record,
                artifact=document["artifact"],
                text=document["text"],
                source_digest=document["source_digest"],
            )
        )
    return passages


def extract_parse_cache_passages(
    record: dict[str, Any],
    *,
    artifact: str,
    chunks: list[dict[str, Any]],
    source_digest: str,
) -> list[dict[str, Any]]:
    """Project existing parse-cache chunks without changing their source text."""
    passages: list[dict[str, Any]] = []
    for chunk_number, chunk in enumerate(chunks, start=1):
        text = str(chunk.get("text") or "").strip()
        if not text:
            continue
        raw_label = str(chunk.get("label") or chunk.get("locator") or f"chunk-{chunk_number}")
        label = " ".join(raw_label.split())[:160]
        for part_number, window in enumerate(_character_windows(text), start=1):
            suffix = f":part-{part_number}" if len(text) > PASSAGE_MAX_CHARS else ""
            _append_passage(
                passages,
                record=record,
                artifact=artifact,
                locator=f"{artifact}#{label}{suffix}",
                heading=label,
                line_start=0,
                line_end=0,
                text=window,
                source_digest=source_digest,
            )
    return passages


def extract_figure_index_passages(
    record: dict[str, Any],
    *,
    artifact: str,
    index: dict[str, Any],
    source_digest: str,
) -> list[dict[str, Any]]:
    """Project already-validated figure refs and captions into search passages.

    Currentness and byte bindings are deliberately checked by the caller.  This
    helper only performs a mechanical, stable projection of canonical entries.
    """
    passages: list[dict[str, Any]] = []
    entries = index.get("entries")
    if not isinstance(entries, list):
        return passages
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ref_key = str(entry.get("ref_key") or "").strip()
        caption = str(entry.get("caption") or "").strip()
        if not ref_key or not caption:
            continue
        page = entry.get("page")
        page_label = f"page {page}" if isinstance(page, int) and page > 0 else ""
        heading = " · ".join(item for item in (ref_key, page_label) if item)
        _append_passage(
            passages,
            record=record,
            artifact=artifact,
            locator=f"{artifact}#{ref_key}",
            heading=heading,
            line_start=0,
            line_end=0,
            text=f"{ref_key}\n{caption}",
            source_digest=source_digest,
        )
    return passages


def is_code_passage(passage: dict[str, Any]) -> bool:
    """A repo source passage carries a repository-relative artifact path.

    Every Markdown/record/parse-cache passage stores a project-relative artifact
    below ``kb/``, so the artifact shape is a stable, structure-preserving
    discriminator that needs no schema change.
    """
    artifact = str(passage.get("artifact") or "")
    return bool(artifact) and not (artifact == "kb" or artifact.startswith("kb/"))


def code_identifier_terms(*texts: str) -> str:
    """Deterministic split-word helper text for identifier sub-word matching.

    ``ConsistencyRefiner`` / ``train_dynamics`` index as single FTS tokens under
    ``unicode61`` (underscores split, camel case does not), so part-word queries
    like ``Refiner`` cannot match the body column.  This emits, per first-seen
    multi-part identifier, its lowercase parts in order (`consistency refiner`),
    preserving adjacency so phrase queries still work.  Single-part identifiers
    are already body tokens and are skipped.
    """
    seen: set[str] = set()
    terms: list[str] = []
    for text in texts:
        for identifier in _IDENTIFIER_RE.findall(str(text or "")):
            if identifier in seen:
                continue
            seen.add(identifier)
            parts = [part.lower() for part in _IDENTIFIER_PART_RE.findall(identifier) if len(part) >= 2]
            if len(parts) < 2:
                continue
            terms.append(" ".join(parts))
            if sum(len(term) + 1 for term in terms) > CODE_IDENTIFIER_TERMS_MAX_CHARS:
                return " ".join(terms)[:CODE_IDENTIFIER_TERMS_MAX_CHARS]
    return " ".join(terms)[:CODE_IDENTIFIER_TERMS_MAX_CHARS]


def _python_symbol_segments(lines: list[str]) -> list[tuple[int, int, str]]:
    """Split Python lines at lexical def/class boundaries with qualified names."""
    boundaries: list[tuple[int, str]] = []
    stack: list[tuple[int, str]] = []
    for number, line in enumerate(lines, start=1):
        match = CODE_SYMBOL_RE.match(line)
        if not match:
            continue
        indent = len(match.group(1).expandtabs(4))
        keyword, name = match.group(2), match.group(3)
        while stack and stack[-1][0] >= indent:
            stack.pop()
        qualified = ".".join([item[1] for item in stack] + [name])
        stack.append((indent, name))
        boundaries.append((number, f"{keyword} {qualified}"))
    if not boundaries:
        return [(1, len(lines), "")]
    segments: list[tuple[int, int, str]] = []
    if boundaries[0][0] > 1:
        segments.append((1, boundaries[0][0] - 1, ""))
    for index, (line_number, label) in enumerate(boundaries):
        end = boundaries[index + 1][0] - 1 if index + 1 < len(boundaries) else len(lines)
        segments.append((line_number, end, label))
    return segments


def _line_windows(start: int, end: int) -> list[tuple[int, int]]:
    if end - start + 1 <= CODE_WINDOW_LINES:
        return [(start, end)]
    step = CODE_WINDOW_LINES - CODE_WINDOW_OVERLAP_LINES
    windows: list[tuple[int, int]] = []
    cursor = start
    while True:
        window_end = min(end, cursor + CODE_WINDOW_LINES - 1)
        windows.append((cursor, window_end))
        if window_end >= end:
            return windows
        cursor += step


def code_passages(
    record: dict[str, Any],
    *,
    artifact: str,
    text: str,
    source_digest: str,
) -> list[dict[str, Any]]:
    """Chunk one repo source file into passages without interpreting the code.

    ``artifact`` is the repository-relative path; the heading carries that path
    (plus the enclosing symbol for Python) so results render as file:line.
    """
    lines = text.splitlines()
    if not lines:
        return []
    passages: list[dict[str, Any]] = []
    if artifact.lower().endswith(".py"):
        segments = _python_symbol_segments(lines)
    else:
        segments = [(1, len(lines), "")]
    for segment_start, segment_end, symbol in segments:
        for window_start, window_end in _line_windows(segment_start, segment_end):
            start, end = window_start, window_end
            while start <= end and not lines[start - 1].strip():
                start += 1
            while end >= start and not lines[end - 1].strip():
                end -= 1
            if start > end:
                continue
            chunk = "\n".join(lines[start - 1 : end])
            heading = f"{artifact} · {symbol}" if symbol else artifact
            windows = _character_windows(chunk)
            for index, window in enumerate(windows, start=1):
                suffix = f":part-{index}" if len(windows) > 1 else ""
                _append_passage(
                    passages,
                    record=record,
                    artifact=artifact,
                    locator=f"{artifact}#L{start}-L{end}{suffix}",
                    heading=heading,
                    line_start=start,
                    line_end=end,
                    text=window,
                    source_digest=source_digest,
                )
    return passages


def passage_excerpt(text: str, query_tokens: list[str], *, limit: int = PASSAGE_EXCERPT_CHARS) -> str:
    compact = " ".join(str(text or "").split())
    if len(compact) <= limit:
        return compact
    lowered = compact.lower()
    offsets = [lowered.find(token) for token in query_tokens if lowered.find(token) >= 0]
    center = min(offsets) if offsets else 0
    start = max(0, center - limit // 3)
    end = min(len(compact), start + limit)
    start = max(0, end - limit)
    prefix = "…" if start else ""
    suffix = "…" if end < len(compact) else ""
    return f"{prefix}{compact[start:end].strip()}{suffix}"


def passage_result(passage: dict[str, Any], query_tokens: list[str], *, score: float) -> dict[str, Any]:
    return {
        "unit_id": passage["unit_id"],
        "kind": passage["kind"],
        "title": passage["title"],
        "excerpt": passage_excerpt(str(passage.get("text") or ""), query_tokens),
        "artifact": passage["artifact"],
        "locator": passage["locator"],
        "heading": passage.get("heading", ""),
        "line_start": int(passage.get("line_start") or 0),
        "line_end": int(passage.get("line_end") or 0),
        "_search_score": score,
    }


def rank_passages(passages: list[dict[str, Any]], query: str, *, limit: int = 5) -> list[dict[str, Any]]:
    """Deterministic in-memory fallback with the same fields as FTS results."""
    query_tokens = tokenize_query(query)
    if not query_tokens or limit <= 0:
        return []
    ranked: list[tuple[float, dict[str, Any]]] = []
    phrase = str(query or "").strip().lower()
    for passage in passages:
        score = 0.0
        matched = False
        for field, weight in PASSAGE_FIELD_WEIGHTS.items():
            lowered = str(passage.get(field) or "").lower()
            field_matches = sum(lowered.count(token) for token in query_tokens)
            if field_matches:
                matched = True
                score += float(weight * field_matches)
            if phrase and phrase in lowered:
                score += float(weight * 2)
        if matched:
            ranked.append((score, passage))
    ranked.sort(
        key=lambda item: (
            -item[0],
            str(item[1].get("unit_id") or ""),
            str(item[1].get("artifact") or ""),
            str(item[1].get("locator") or ""),
        )
    )
    return [passage_result(item, query_tokens, score=score) for score, item in ranked[:limit]]
