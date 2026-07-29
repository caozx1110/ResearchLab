"""Claim -> evidence binding + verbatim verification (SSOT Part 2, Principle 2).

This module is the Wave 2 **evidence layer**: it turns "有理有据" from a slogan
into something a script can check. It is purely *additive* — it exposes callable,
testable primitives (verbatim quote verification + claim-structure validation +
note/screening claim attach helpers) but has **no caller inside the system yet**,
so importing or shipping it changes zero existing behavior (the confirmation gate
and analyzers are untouched; gate interlock lands in the parallel Gate track,
which will call `validate_claims()` / `verify_claim_evidence()` from here).

The canonical schema is documented verbatim in
`lib/research/SCHEMAS.md#evidence-claims` and locked in
`.agents/lib/research/SCHEMAS.md`.

Verification model (SSOT B3/B4):
  * Every evidence_ref carries a **short verbatim `quote`**. The script loads the
    referenced `artifact` and checks the quote is a **whitespace-normalized
    verbatim substring** (consecutive whitespace folded to one space + strip;
    case preserved). Hit => grounded; miss => a violation string.
  * `locator` has two families: PDF (`page=N` / `section` / `para`) and HTML
    (`section` / `anchor`, no page numbers); repo evidence adds `line=N`.
    Recognized locator shapes are position-checked against the artifact: a
    `line=N`/`line=N-M` locator must contain the quote's starting line, a
    `page=N` locator must name the page chunk holding the quote, and a
    `section:<anchor>` locator must name an existing chunk whose own text
    contains the quote. A verbatim hit at a *different* position is a
    locator-mismatch violation whose message carries the scanned actual
    position (line=K / section label) as a repair hint. Unrecognized locator
    shapes (bare `section`/`page`, `file:line` prose, free text) are never
    rejected — they keep the historical pass-through and only warn, so legacy
    data and other analysts do not fail closed.
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

import yaml

from .common import utc_now_iso

# Vocabulary (mirrors research-record information_types + confirmation values).
CLAIM_TYPES = {"fact", "inference", "evaluation", "user_opinion", "unverified"}
# Judgement-class claims must carry evidence before they may be promoted to
# confirmed (SSOT Principle 2 / gate interlock). This module supplies the
# criterion function; the parallel Gate track wires it into the gate.
JUDGEMENT_CLAIM_TYPES = {"inference", "evaluation", "user_opinion"}
UNCONFIRMABLE_CLAIM_TYPES = {"unverified"}
CLAIM_CONFIRMATION_VALUES = {
    "pending_user_confirmation",
    "confirmed",
    "rejected",
    "auto_confirmed",
}
# Two locator families (SSOT B4): PDF sources use page/section/para; HTML
# sources use section/anchor (no page numbers).
PDF_LOCATOR_KINDS = {"page", "section", "para"}
HTML_LOCATOR_KINDS = {"section", "anchor"}
EXTERNAL_SOURCE_KINDS = {"repo"}

# Required top-level keys on every claim (validate_claims enforces presence).
REQUIRED_CLAIM_FIELDS = ("id", "text", "claim_type", "confirmation_status", "evidence_refs")
REQUIRED_EVIDENCE_REF_FIELDS = ("source_unit_id", "artifact", "locator", "quote")

CONFIRMABLE_CONTENT_SECTIONS: dict[str, tuple[str, ...]] = {
    "paper": ("core_content",),
    "repo": ("capability",),
    "dataset": ("profile", "composition", "access", "quality"),
    "blog": ("content",),
    "idea": ("problem", "hypothesis"),
    "experiment": ("results", "diagnosis"),
    "concept": ("concept", "associations", "anchor"),
    "program_decision": ("decision",),
    "idea_discussion_conclusion": ("discussion_conclusion",),
    "method_selection": ("method_selection",),
    "paper_draft_section": ("paper_draft_section", "anchor"),
}

# Side judgements often keep workflow bookkeeping beside the decision
# substance.  Only the fields below are part of the user's confirmation scope;
# unit sections without an entry remain fully bound as before.
CONFIRMABLE_CONTENT_FIELDS: dict[str, dict[str, tuple[str, ...]]] = {
    "program_decision": {
        "decision": ("text", "rationale", "stage", "alternatives"),
    },
    "idea_discussion_conclusion": {
        "discussion_conclusion": ("text", "reviewer"),
    },
    "method_selection": {
        "method_selection": ("proposed_repo_id", "selected_repo_id", "selection_reason"),
    },
}

# Locked canonical schema — kept byte-identical to
# SCHEMAS.md#evidence-claims / SSOT Part 2 Principle 2.
EVIDENCE_SCHEMA = """# 挂在每条 AI claim 上。落盘位置：note/screening 产物内的 claims 列表 + record 关联。
claim:
  id: claim-001
  text: ""                       # 断言本身
  claim_type: fact|inference|evaluation|user_opinion|unverified
  confidence: 0.0                # 可选
  confirmation_status: pending_user_confirmation|confirmed|rejected|auto_confirmed
  evidence_refs:
    - source_unit_id: p-...       # 证据所在 unit
      artifact: parse-cache.yaml  # unit 内相对路径，或 source(pdf/html)
      locator: "page=3"           # PDF: page=N|section|para ; HTML: section|anchor（B4）
      quote: ""                   # 短逐字片段（B3）——脚本校验它逐字存在于 artifact
      summary: ""                 # 可选转述
"""


@dataclass
class EvidenceRef:
    """A single evidence pointer attached to a claim (see EVIDENCE_SCHEMA)."""

    source_unit_id: str = ""
    artifact: str = ""
    locator: str = ""
    quote: str = ""
    summary: str = ""


@dataclass
class Claim:
    """An AI claim with its evidence bindings (see EVIDENCE_SCHEMA)."""

    id: str = ""
    text: str = ""
    claim_type: str = "unverified"
    confidence: float = 0.0
    confirmation_status: str = "pending_user_confirmation"
    evidence_refs: list[EvidenceRef] = field(default_factory=list)


# --------------------------------------------------------------------------- #
# Text normalization (SSOT B3: whitespace-normalized, case-sensitive verbatim) #
# --------------------------------------------------------------------------- #

_WS_RE = re.compile(r"\s+")


def normalize_ws(text: Any) -> str:
    """Fold consecutive whitespace to a single space and strip; keep case.

    This is the single normalization applied to *both* the artifact text and the
    quote before the verbatim substring test, so a quote copied across a line
    wrap or with incidental double-spaces still matches, while a fabricated quote
    does not.
    """
    if text is None:
        return ""
    return _WS_RE.sub(" ", str(text)).strip()


def _quote_digest(quote: str, limit: int = 60) -> str:
    """Short, single-line rendering of a quote for violation messages."""
    flat = normalize_ws(quote)
    if len(flat) > limit:
        return flat[: limit - 1] + "…"
    return flat


def _canonical_digest_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _canonical_digest_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_digest_value(item) for item in value]
    if isinstance(value, set):
        normalized = [_canonical_digest_value(item) for item in value]
        return sorted(normalized, key=_canonical_json)
    if isinstance(value, str):
        return normalize_ws(value)
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return normalize_ws(value)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256_canonical(value: Any) -> str:
    canonical = _canonical_digest_value(value)
    return hashlib.sha256(_canonical_json(canonical).encode("utf-8")).hexdigest()


def _without_empty_mapping_values(value: Any) -> Any:
    if isinstance(value, dict):
        compact: dict[str, Any] = {}
        for key, item in value.items():
            normalized = _without_empty_mapping_values(item)
            if normalized not in (None, "", [], {}):
                compact[str(key)] = normalized
        return compact
    if isinstance(value, (list, tuple)):
        return [_without_empty_mapping_values(item) for item in value]
    return value


def confirmation_claims(record: Any) -> list[dict[str, Any]]:
    if not isinstance(record, dict):
        return []
    payload = record.get("payload")
    claims = read_claims(payload)
    return sorted(
        claims,
        key=lambda claim: (normalize_ws(claim.get("id")), _canonical_json(_canonical_digest_value(claim))),
    )


def confirmation_claim_ids(record: Any) -> list[str]:
    return sorted(
        {
            claim_id
            for claim in confirmation_claims(record)
            if (claim_id := normalize_ws(claim.get("id")))
        }
    )


def claims_digest(claims: Any) -> str:
    """Canonical digest for the claims that passed analyzer verification."""
    normalized = [claim for claim in claims if isinstance(claim, dict)] if isinstance(claims, (list, tuple)) else []
    normalized.sort(
        key=lambda claim: (normalize_ws(claim.get("id")), _canonical_json(_canonical_digest_value(claim)))
    )
    return _sha256_canonical(normalized)


def confirmation_content_digest(record: Any) -> str:
    if not isinstance(record, dict):
        record = {}
    kind = normalize_ws(record.get("kind"))
    payload = record.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    sections: dict[str, Any] = {}
    selected_fields = CONFIRMABLE_CONTENT_FIELDS.get(kind, {})
    for section in CONFIRMABLE_CONTENT_SECTIONS.get(kind, ()):
        value = payload.get(section, {})
        fields = selected_fields.get(section)
        if fields is not None and isinstance(value, dict):
            value = {field: value.get(field) for field in fields}
        sections[section] = _without_empty_mapping_values(value)
    return _sha256_canonical({"substance": sections, "claims": confirmation_claims(record)})


def confirmation_evidence_digest(record: Any, evidence_items: Any) -> str:
    items = evidence_items if isinstance(evidence_items, (list, tuple, set)) else [evidence_items]
    normalized_items = sorted({item for value in items if (item := normalize_ws(value))})
    evidence_refs = [
        {
            "source_unit_id": ref.get("source_unit_id", ""),
            "artifact": ref.get("artifact", ""),
            "locator": ref.get("locator", ""),
            "quote": ref.get("quote", ""),
        }
        for claim in confirmation_claims(record)
        for ref in claim.get("evidence_refs", [])
        if isinstance(ref, dict)
    ]
    evidence_refs.sort(key=lambda ref: _canonical_json(_canonical_digest_value(ref)))
    payload = record.get("payload") if isinstance(record, dict) else {}
    verification = payload.get("verification") if isinstance(payload, dict) else {}
    verification_binding: dict[str, Any] = {}
    if isinstance(verification, dict):
        verification_binding = {
            "claims_digest": verification.get("claims_digest", ""),
            "evidence_digest": verification.get("evidence_digest", ""),
            "artifacts": verification.get("artifacts", []),
        }
    return _sha256_canonical(
        {
            "evidence_items": normalized_items,
            "evidence_refs": evidence_refs,
            "verification": verification_binding,
        }
    )


def _page_of_label(label: Any) -> int | None:
    """Extract a page number from a parse-cache chunk label like 'foo:page-3'."""
    if not label:
        return None
    match = re.search(r"page[-_ ]?(\d+)", str(label), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


# Locator position validation (SSOT B4 hardening): a locator is not free text —
# when its shape is recognized, the cited position must actually contain the
# quote.  Recognized families (exactly the forms the analysts document):
#   * ``line=N`` / ``line=N-M``   -> raw line positions inside the artifact file
#     (repo-file evidence per repo-analyst's ``locator=line=N`` contract; the
#     legacy colon form ``line:N`` deliberately stays unrecognized/warn-only).
#   * ``page=N``                  -> parse-cache page chunks (existing narrowing).
#   * ``section:<anchor>`` / ``anchor:<x>`` -> parse-cache section chunk labels,
#     enforced only when the artifact actually exposes section-labeled chunks
#     (a PDF ``section``-family citation on a page-only cache keeps passing).
# Anything else (bare ``section``/``page``, idea-workbench ``file:line`` prose,
# free text, URLs) keeps the pre-existing pass-through behavior and only emits a
# warning, so legacy data and other analysts are never failed closed.
_LINE_LOCATOR_RE = re.compile(
    r"^\s*lines?\s*=\s*(\d+)\s*(?:[-–~]\s*(\d+))?\s*$",
    flags=re.IGNORECASE,
)
_SECTION_LOCATOR_RE = re.compile(
    r"^\s*(section|anchor)\s*:\s*(\S.*?)\s*$",
    flags=re.IGNORECASE,
)
_BARE_LOCATOR_KINDS = {"section", "anchor", "page", "para"}


def _line_range_of_locator(locator: Any) -> tuple[int, int] | None:
    """Parse ``line=N`` / ``line=N-M`` into an inclusive 1-based range."""
    if not locator:
        return None
    match = _LINE_LOCATOR_RE.fullmatch(str(locator))
    if match is None:
        return None
    start = int(match.group(1))
    end = int(match.group(2)) if match.group(2) else start
    if start <= 0:
        return None
    if end < start:
        start, end = end, start
    return start, end


def _section_anchor_of_locator(locator: Any) -> str | None:
    """Extract ``<anchor>`` from a ``section:<anchor>`` / ``anchor:<x>`` locator."""
    if not locator:
        return None
    match = _SECTION_LOCATOR_RE.fullmatch(str(locator))
    return match.group(2).strip() if match else None


def _quote_start_lines(raw_text: str, quote: str) -> list[int]:
    """Return every 1-based line where the whitespace-normalized quote starts.

    A quote "starts" at line K when its first normalized character falls inside
    line K: either the quote's lines correspond to the file's lines from K on
    (each quote line a normalized substring of its file line), or — for quotes
    flattened across a wrap — the normalized quote occurs in the normalized
    join of lines K.. at an offset inside line K's own contribution.
    """
    flat = normalize_ws(quote)
    if not flat or not raw_text:
        return []
    norm_lines = [normalize_ws(line) for line in raw_text.splitlines()]
    quote_lines = [part for part in (normalize_ws(item) for item in str(quote).splitlines()) if part]
    candidates: list[int] = []
    total = len(norm_lines)
    for index, current in enumerate(norm_lines):
        if not current:
            continue
        if index + len(quote_lines) <= total and all(
            quote_line in norm_lines[index + offset]
            for offset, quote_line in enumerate(quote_lines)
        ):
            candidates.append(index + 1)
            continue
        window = [current]
        length = len(current)
        cursor = index + 1
        needed = len(current) + len(flat) + 1
        while length < needed and cursor < total:
            nxt = norm_lines[cursor]
            if nxt:
                window.append(nxt)
                length += len(nxt) + 1
            cursor += 1
        position = " ".join(window).find(flat)
        if 0 <= position < len(current):
            candidates.append(index + 1)
    return candidates


def _chunk_labels_of_quote(
    chunks: tuple[tuple[str, str, str], ...],
    norm_quote: str,
) -> list[str]:
    """Labels of every chunk whose normalized text contains the quote."""
    found: list[str] = []
    for label, _anchor, text in chunks:
        if norm_quote and norm_quote in normalize_ws(text):
            found.append(label or "<unlabeled>")
    return found


def _line_hint(candidates: list[int]) -> str:
    if not candidates:
        return "could not anchor the quote to any artifact line"
    rendered = ", ".join(f"line={item}" for item in candidates[:5])
    if len(candidates) > 5:
        rendered += ", …"
    return f"quote actually starts at {rendered}"


def _section_hint(found_labels: list[str]) -> str:
    if not found_labels:
        return "the quote is not inside any single chunk (it may span chunk boundaries — cite a shorter quote)"
    rendered = ", ".join(found_labels[:5])
    if len(found_labels) > 5:
        rendered += ", …"
    return f"quote actually in {rendered}"


def _locator_position_check(
    ref: dict[str, Any],
    loaded: "_LoadedArtifact",
    *,
    where: str,
    artifact: str,
    quote: str,
    norm_quote: str,
) -> tuple[str | None, str | None]:
    """Validate a recognized locator's position claim; returns (violation, warning).

    The quote is already known to be verbatim somewhere in the artifact; this
    only checks that the *cited position* is where it actually lives.  Position
    mismatch => violation with a repair hint (the scanned actual position).
    Unrecognized or unverifiable locator shapes => warning only (never reject),
    so legacy locator vocabularies keep their existing behavior.
    """
    locator_raw = str(ref.get("locator") or "")
    locator = normalize_ws(locator_raw)
    if not locator:
        return None, None

    line_range = _line_range_of_locator(locator)
    if line_range is not None:
        if not loaded.full_text:
            return None, (
                f"{where}: locator '{locator}' could not be position-checked "
                f"(artifact '{artifact}' has no raw text view); locator accepted as-is"
            )
        candidates = _quote_start_lines(loaded.full_text, quote)
        if not candidates:
            return None, (
                f"{where}: locator '{locator}' could not be position-checked "
                f"(the quote cannot be anchored to a line of artifact '{artifact}', "
                f"e.g. it may only match after YAML decoding); locator accepted as-is"
            )
        start, end = line_range
        if any(start <= item <= end for item in candidates):
            return None, None
        return (
            f"{where}: quote '{_quote_digest(quote)}' is verbatim in artifact '{artifact}' "
            f"but locator '{locator}' does not match its position ({_line_hint(candidates)})",
            None,
        )

    page = _page_of_locator(locator)
    if page is not None:
        if loaded.pages:
            cited = normalize_ws(loaded.pages.get(page, ""))
            if norm_quote in cited:
                return None, None
            found_on = sorted(p for p, t in loaded.pages.items() if norm_quote in normalize_ws(t))
            found_desc = f"page(s) {found_on}" if found_on else "outside indexed pages"
            return (
                f"{where}: quote '{_quote_digest(quote)}' grounded but locator page={page} "
                f"is wrong (found on {found_desc})",
                None,
            )
        if loaded.chunks:
            found_labels = _chunk_labels_of_quote(loaded.chunks, norm_quote)
            return (
                f"{where}: locator '{locator}' cites a page but artifact '{artifact}' has no "
                f"page-labeled chunks ({_section_hint(found_labels)})",
                None,
            )
        return None, (
            f"{where}: locator '{locator}' could not be position-checked "
            f"(artifact '{artifact}' exposes no page or chunk structure); locator accepted as-is"
        )

    anchor = _section_anchor_of_locator(locator)
    if anchor is not None:
        if not loaded.chunks:
            return None, (
                f"{where}: locator '{locator}' could not be position-checked "
                f"(artifact '{artifact}' exposes no parse-cache chunks); locator accepted as-is"
            )
        has_section_chunks = any(
            label.casefold().startswith("section:") or chunk_anchor
            for label, chunk_anchor, _text in loaded.chunks
        )
        if not has_section_chunks:
            # Page-only caches (PDF): ``section``-family locators cite paper
            # sections, not chunk labels — keep the historical pass-through.
            return None, (
                f"{where}: locator '{locator}' could not be position-checked "
                f"(artifact '{artifact}' has no section-labeled chunks); locator accepted as-is"
            )
        anchor_fold = anchor.casefold()
        locator_fold = locator.casefold()
        matched = [
            (label, chunk_anchor, text)
            for label, chunk_anchor, text in loaded.chunks
            if label.casefold() == locator_fold
            or (chunk_anchor and chunk_anchor.casefold() == anchor_fold)
            or label.casefold() == f"section:{anchor_fold}"
        ]
        found_labels = _chunk_labels_of_quote(loaded.chunks, norm_quote)
        if not matched:
            known = [label for label, _anchor, _text in loaded.chunks if label][:6]
            known_desc = f"; known labels: {', '.join(known)}" if known else ""
            return (
                f"{where}: locator '{locator}' does not name any chunk label of artifact "
                f"'{artifact}' ({_section_hint(found_labels)}{known_desc})",
                None,
            )
        if any(norm_quote in normalize_ws(text) for _label, _anchor, text in matched):
            return None, None
        return (
            f"{where}: quote '{_quote_digest(quote)}' is verbatim in artifact '{artifact}' "
            f"but locator '{locator}' does not match its position ({_section_hint(found_labels)})",
            None,
        )

    if locator.casefold() in _BARE_LOCATOR_KINDS:
        return None, (
            f"{where}: locator '{locator}' names a family but no position "
            f"(cite e.g. section:<anchor>, page=N or line=N); locator accepted as-is"
        )
    return None, (
        f"{where}: locator '{locator}' has an unrecognized shape and was not position-checked; "
        f"locator accepted as-is"
    )


# One-line, deduplicated stderr fallback for locator warnings when the caller
# supplies no warning sink (existing analysts).  Warnings never fail a verify.
_LOCATOR_WARNING_SEEN: set[str] = set()
_LOCATOR_WARNING_SEEN_MAX = 4096


def _emit_locator_warning(message: str, sink: list[str] | None) -> None:
    if sink is not None:
        sink.append(message)
        return
    if message in _LOCATOR_WARNING_SEEN:
        return
    if len(_LOCATOR_WARNING_SEEN) < _LOCATOR_WARNING_SEEN_MAX:
        _LOCATOR_WARNING_SEEN.add(message)
    print(f"[warn] {message}", file=sys.stderr)


def _page_of_locator(locator: Any) -> int | None:
    """Extract N from a `page=N` PDF locator, else None (section/anchor/etc.)."""
    if not locator:
        return None
    match = re.search(r"page\s*=\s*(\d+)", str(locator), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


def _artifact_pages(data: Any) -> dict[int, str]:
    """Map page-number -> concatenated chunk text for a parse-cache mapping.

    Only chunks whose label encodes a page number are indexed; returns {} when
    the artifact has no per-page structure (then callers fall back to full-text).
    """
    pages: dict[int, list[str]] = {}
    if not isinstance(data, dict):
        return {}
    for chunk in data.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        page = _page_of_label(chunk.get("label"))
        if page is None:
            continue
        pages.setdefault(page, []).append(str(chunk.get("text") or ""))
    return {page: "\n".join(parts) for page, parts in pages.items()}


def _artifact_chunks(data: Any) -> tuple[tuple[str, str, str], ...]:
    """Extract (label, anchor, text) triples from a parse-cache-style mapping.

    Returns () when the artifact has no ``chunks`` structure, in which case
    chunk-label locators (``section:<anchor>``) cannot be position-checked and
    keep their pre-existing pass-through behavior.
    """
    if not isinstance(data, dict):
        return ()
    triples: list[tuple[str, str, str]] = []
    for chunk in data.get("chunks") or []:
        if not isinstance(chunk, dict):
            continue
        triples.append(
            (
                str(chunk.get("label") or ""),
                str(chunk.get("anchor") or ""),
                str(chunk.get("text") or ""),
            )
        )
    return tuple(triples)


def _yaml_text_blob(data: Any) -> str:
    """Best-effort searchable text from a parsed YAML artifact.

    parse-cache.yaml stores text under `chunks[].text`; if that structure is
    absent we fall back to concatenating every string leaf so a quote can still
    be located in ad-hoc YAML artifacts.
    """
    if isinstance(data, dict):
        chunk_texts = [
            str(chunk.get("text") or "")
            for chunk in (data.get("chunks") or [])
            if isinstance(chunk, dict)
        ]
        if chunk_texts:
            return "\n".join(chunk_texts)
    parts: list[str] = []

    def _walk(node: Any) -> None:
        if isinstance(node, str):
            parts.append(node)
        elif isinstance(node, dict):
            for value in node.values():
                _walk(value)
        elif isinstance(node, (list, tuple)):
            for value in node:
                _walk(value)

    _walk(data)
    return "\n".join(parts)


@dataclass
class _LoadedArtifact:
    """Loaded artifact text: independent full-document views plus page index.

    YAML needs two views: its original UTF-8 text preserves configuration keys,
    scalar spelling, and quoting, while its parsed structure exposes chunk text
    after YAML escape/block-scalar decoding.  The views remain separate so a
    quote cannot become a false hit by spanning their concatenation boundary.
    """

    full_text: str = ""
    structured_text: str = ""
    pages: dict[int, str] = field(default_factory=dict)
    chunks: tuple[tuple[str, str, str], ...] = ()

    def searchable_texts(self) -> tuple[str, ...]:
        return tuple(text for text in (self.full_text, self.structured_text) if text)


@dataclass(frozen=True)
class ResolvedEvidenceArtifact:
    """A containment-checked artifact plus its receipt identity."""

    path: Path
    base_root: Path
    artifact: str
    source_kind: str
    source_unit_id: str = ""
    external_kind: str = ""

    @property
    def identity(self) -> str:
        if self.source_kind == "unit":
            return f"unit:{self.source_unit_id or '<unspecified>'}:{self.artifact}"
        return f"external:{self.external_kind}:{self.base_root.as_posix()}:{self.artifact}"

    def receipt_entry(self) -> dict[str, Any]:
        entry: dict[str, Any] = {
            "identity": self.identity,
            "source_kind": self.source_kind,
            "artifact": self.artifact,
            "source_unit_id": self.source_unit_id,
            "byte_sha256": hashlib.sha256(self.path.read_bytes()).hexdigest(),
        }
        if self.source_kind == "external_source":
            entry["external_source"] = {
                "kind": self.external_kind,
                "base_root": self.base_root.as_posix(),
            }
        return entry


@dataclass(frozen=True)
class EvidenceArtifactSnapshot:
    """Immutable bytes captured through a canonical unit directory capability.

    ``path`` is informational only.  Verification consumes ``raw_bytes`` and
    ``byte_sha256`` directly, so a later rename or symlink replacement of the
    lexical workspace path cannot redirect the read.
    """

    source_unit_id: str
    artifact: str
    raw_bytes: bytes
    byte_sha256: str
    path: Path
    directory_identities: tuple[tuple[int, int, int, int, int, int], ...] = ()
    file_identity: tuple[int, int, int, int, int, int] = (0, 0, 0, 0, 0, 0)

    @property
    def identity(self) -> str:
        return f"unit:{self.source_unit_id or '<unspecified>'}:{self.artifact}"

    def receipt_entry(self) -> dict[str, Any]:
        digest = hashlib.sha256(self.raw_bytes).hexdigest()
        if digest != self.byte_sha256:
            raise ValueError("anchored artifact snapshot digest mismatch")
        return {
            "identity": self.identity,
            "source_kind": "unit",
            "artifact": self.artifact,
            "source_unit_id": self.source_unit_id,
            "byte_sha256": digest,
        }

    def read_text(self, encoding: str = "utf-8") -> str:
        return self.raw_bytes.decode(encoding)


@dataclass(frozen=True)
class EvidenceSourceSnapshot:
    """All requested evidence artifacts from one anchored canonical unit."""

    source_unit_id: str
    kind: str
    artifacts: tuple[EvidenceArtifactSnapshot, ...]
    path: Path
    validate_current: Callable[[], bool] = field(repr=False, compare=False)

    def is_current(self) -> bool:
        try:
            return bool(self.validate_current())
        except (OSError, ValueError):
            return False

    def artifact_snapshot(self, artifact: str) -> EvidenceArtifactSnapshot:
        if not self.is_current():
            raise ValueError("anchored source snapshot is no longer current")
        requested = Path(str(artifact or "")).as_posix()
        matches = [item for item in self.artifacts if item.artifact == requested]
        if len(matches) != 1:
            raise ValueError(
                f"artifact {artifact!r} is absent from the anchored source snapshot"
            )
        return matches[0]


def record_external_source_contract(record: Any) -> dict[str, str] | None:
    """Return the trusted repo-root contract persisted by the repo analyzer."""
    if not isinstance(record, dict) or str(record.get("kind") or "") != "repo":
        return None
    payload = record.get("payload")
    structure = payload.get("structure") if isinstance(payload, dict) else None
    base_root = str(structure.get("repo_root") or "").strip() if isinstance(structure, dict) else ""
    if not base_root:
        return None
    return {"kind": "repo", "base_root": base_root}


def _has_absolute_syntax(artifact: str) -> bool:
    return (
        Path(artifact).is_absolute()
        or artifact.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:[\\/]", artifact) is not None
    )


def resolve_evidence_artifact(
    ref: Any,
    unit_dir: str | Path | None,
    *,
    external_source: dict[str, Any] | None = None,
) -> ResolvedEvidenceArtifact:
    """Resolve one evidence ref without permitting path or symlink escape.

    Normal evidence is always unit-relative. Repo workspace evidence must opt in
    with ``external_source: {kind: repo}`` and the caller must separately supply
    the trusted ``{kind: repo, base_root: ...}`` contract. A claim may never name
    its own base root.
    """
    if not isinstance(ref, dict):
        raise ValueError("evidence ref is not a mapping")
    artifact = str(ref.get("artifact") or "").strip()
    if not artifact:
        raise ValueError("missing artifact")
    if "\x00" in artifact:
        raise ValueError("artifact contains a NUL byte")
    if _has_absolute_syntax(artifact):
        raise ValueError(f"artifact must be relative, got absolute path {artifact!r}")
    raw_path = Path(artifact)
    if ".." in raw_path.parts:
        raise ValueError(f"artifact must not contain '..': {artifact!r}")

    declared_external = ref.get("external_source")
    if declared_external not in (None, "", {}):
        if not isinstance(declared_external, dict):
            raise ValueError("external_source must be a mapping")
        external_kind = str(declared_external.get("kind") or "").strip()
        if external_kind not in EXTERNAL_SOURCE_KINDS:
            raise ValueError(f"unsupported external_source kind {external_kind!r}")
        if declared_external.get("base_root"):
            raise ValueError("evidence ref may not supply external_source.base_root")
        if not isinstance(external_source, dict):
            raise ValueError("external_source evidence requires a trusted base-root contract")
        contract_kind = str(external_source.get("kind") or "").strip()
        if contract_kind != external_kind:
            raise ValueError(
                f"external_source kind {external_kind!r} does not match trusted contract {contract_kind!r}"
            )
        base_text = str(external_source.get("base_root") or "").strip()
        if not base_text:
            raise ValueError("external_source contract is missing base_root")
        base = Path(base_text).expanduser().resolve()
        source_kind = "external_source"
    else:
        if unit_dir is None:
            raise ValueError("cannot resolve unit artifact (no unit_dir)")
        base = Path(unit_dir).resolve()
        external_kind = ""
        source_kind = "unit"

    candidate = (base / raw_path).resolve()
    try:
        canonical_artifact = candidate.relative_to(base).as_posix()
    except ValueError as exc:
        raise ValueError(f"artifact escapes allowed {source_kind} root: {artifact!r}") from exc
    return ResolvedEvidenceArtifact(
        path=candidate,
        base_root=base,
        artifact=canonical_artifact,
        source_kind=source_kind,
        source_unit_id=str(ref.get("source_unit_id") or "").strip(),
        external_kind=external_kind,
    )


def _load_artifact_bytes(raw_bytes: bytes, *, suffix: str) -> _LoadedArtifact | None:
    """Decode one immutable artifact snapshot into searchable views."""
    try:
        raw = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        return None
    if suffix.lower() in {".yaml", ".yml"}:
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError:
            # Fall back to raw text so a quote can still be matched.
            return _LoadedArtifact(full_text=raw)
        return _LoadedArtifact(
            full_text=raw,
            structured_text=_yaml_text_blob(data),
            pages=_artifact_pages(data),
            chunks=_artifact_chunks(data),
        )
    return _LoadedArtifact(full_text=raw)


def _load_artifact_path(path: Path) -> _LoadedArtifact | None:
    """Load a containment-checked artifact's searchable text."""
    if not path.is_file():
        return None
    try:
        raw_bytes = path.read_bytes()
    except OSError:
        return None
    return _load_artifact_bytes(raw_bytes, suffix=path.suffix)


def _resolved_evidence_input(
    ref: dict[str, Any],
    unit_source: str | Path | EvidenceSourceSnapshot | None,
    *,
    external_source: dict[str, Any] | None,
) -> ResolvedEvidenceArtifact | EvidenceArtifactSnapshot:
    """Resolve an evidence ref to either anchored bytes or a legacy safe path."""
    if isinstance(unit_source, EvidenceSourceSnapshot) and not isinstance(ref.get("external_source"), dict):
        source_unit_id = str(ref.get("source_unit_id") or "").strip()
        if source_unit_id != unit_source.source_unit_id:
            raise ValueError(
                f"source_unit_id {source_unit_id or '<missing>'!r} does not match anchored source snapshot"
            )
        artifact = str(ref.get("artifact") or "").strip()
        if not artifact or "\x00" in artifact or _has_absolute_syntax(artifact) or ".." in Path(artifact).parts:
            raise ValueError(f"artifact is not a canonical relative path: {artifact!r}")
        return unit_source.artifact_snapshot(artifact)
    return resolve_evidence_artifact(ref, unit_source, external_source=external_source)


def _ref_unit_dir(
    ref: dict[str, Any],
    unit_dir: str | Path | EvidenceSourceSnapshot | None,
    source_roots: dict[str, str | Path | EvidenceSourceSnapshot] | None,
) -> str | Path | EvidenceSourceSnapshot | None:
    if isinstance(ref.get("external_source"), dict):
        # The trusted external_source contract supplies this ref's byte root;
        # cross-unit source_roots apply only to canonical KB artifacts.
        return unit_dir
    if source_roots is None:
        return unit_dir
    source_unit_id = str(ref.get("source_unit_id") or "").strip()
    if not source_unit_id or source_unit_id not in source_roots:
        raise ValueError(f"no trusted unit root for source_unit_id {source_unit_id or '<missing>'!r}")
    return source_roots[source_unit_id]


def _stale_source_snapshot_violations(
    source_roots: dict[str, str | Path | EvidenceSourceSnapshot] | None,
) -> list[str]:
    if source_roots is None:
        return []
    return [
        f"source unit {source_unit_id!r}: anchored evidence snapshot is no longer current"
        for source_unit_id, source in source_roots.items()
        if isinstance(source, EvidenceSourceSnapshot) and not source.is_current()
    ]


def verify_claim_evidence(
    claim: Any,
    unit_dir: str | Path | EvidenceSourceSnapshot | None,
    *,
    external_source: dict[str, Any] | None = None,
    source_roots: dict[str, str | Path | EvidenceSourceSnapshot] | None = None,
    locator_warnings: list[str] | None = None,
) -> list[str]:
    """Return a list of evidence violations for `claim` (empty == fully grounded).

    For each `evidence_ref` the referenced `artifact` is loaded under `unit_dir`
    and its `quote` is checked to be a whitespace-normalized verbatim substring
    (SSOT B3). Reported violations cover: missing/unverifiable quote, artifact
    that cannot be read, quote-not-found, and — when the locator's shape is
    recognized (`line=N`/`line=N-M`, `page=N`, `section:<anchor>`) — a quote
    that is verbatim in the artifact but not at the cited position (locator
    mismatch, reported with the scanned actual position as a repair hint).
    Unrecognized locator shapes are never rejected: they keep the pre-existing
    behavior and surface a warning (appended to `locator_warnings` when the
    caller supplies a list, otherwise printed once to stderr). Degenerate
    inputs (non-dict claim, no refs, `unit_dir=None`) never raise; they yield
    [] or a precise violation rather than crashing.
    """
    violations: list[str] = []
    if not isinstance(claim, dict):
        return violations
    refs = claim.get("evidence_refs") or []
    if not isinstance(refs, (list, tuple)):
        return [f"claim {claim.get('id') or '<no-id>'}: evidence_refs must be a list"]
    claim_id = str(claim.get("id") or "<no-id>")
    base = unit_dir

    for idx, ref in enumerate(refs):
        where = f"claim {claim_id} evidence_refs[{idx}]"
        if not isinstance(ref, dict):
            violations.append(f"{where}: not a mapping")
            continue
        artifact = str(ref.get("artifact") or "")
        quote = str(ref.get("quote") or "")
        norm_quote = normalize_ws(quote)
        if not norm_quote:
            violations.append(f"{where}: empty quote — nothing to verify (artifact={artifact or '?'})")
            continue
        if not artifact:
            violations.append(f"{where}: missing artifact for quote '{_quote_digest(quote)}'")
            continue
        try:
            ref_base = _ref_unit_dir(ref, base, source_roots)
            resolved = _resolved_evidence_input(ref, ref_base, external_source=external_source)
        except ValueError as exc:
            violations.append(f"{where}: {exc} for quote '{_quote_digest(quote)}'")
            continue
        if isinstance(resolved, EvidenceArtifactSnapshot):
            loaded = _load_artifact_bytes(resolved.raw_bytes, suffix=Path(resolved.artifact).suffix)
            location = resolved.path.parent
        else:
            loaded = _load_artifact_path(resolved.path)
            location = resolved.base_root
        if loaded is None:
            violations.append(
                f"{where}: artifact '{artifact}' not found/readable under {location} "
                f"for quote '{_quote_digest(quote)}'"
            )
            continue
        norm_full_views = [normalize_ws(text) for text in loaded.searchable_texts()]
        if not any(norm_quote in text for text in norm_full_views):
            violations.append(
                f"{where}: quote '{_quote_digest(quote)}' not verbatim in artifact '{artifact}'"
            )
            continue
        # Grounded in the document. Locator position validation: a recognized
        # locator (line=N / page=N / section:<anchor>) must actually contain the
        # quote; a verbatim hit at a different position is a locator-mismatch
        # violation carrying the scanned actual position as a repair hint.
        # Unrecognized locator shapes only warn and keep the verbatim result.
        violation, warning = _locator_position_check(
            ref,
            loaded,
            where=where,
            artifact=artifact,
            quote=quote,
            norm_quote=norm_quote,
        )
        if violation:
            violations.append(violation)
        elif warning:
            _emit_locator_warning(warning, locator_warnings)
    violations.extend(_stale_source_snapshot_violations(source_roots))
    return violations


def evidence_artifact_entries(
    claims: Any,
    unit_dir: str | Path | EvidenceSourceSnapshot | None,
    *,
    external_source: dict[str, Any] | None = None,
    source_roots: dict[str, str | Path | EvidenceSourceSnapshot] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Collect byte-bound canonical artifact identities for verified claims."""
    entries: dict[str, dict[str, Any]] = {}
    violations: list[str] = []
    if not isinstance(claims, (list, tuple)):
        return [], ["claims payload must be a list"]
    for claim_index, claim in enumerate(claims):
        if not isinstance(claim, dict):
            continue
        refs = claim.get("evidence_refs") or []
        if not isinstance(refs, (list, tuple)):
            continue
        for ref_index, ref in enumerate(refs):
            where = f"claims[{claim_index}].evidence_refs[{ref_index}]"
            try:
                ref_base = _ref_unit_dir(ref, unit_dir, source_roots)
                resolved = _resolved_evidence_input(ref, ref_base, external_source=external_source)
                if isinstance(resolved, ResolvedEvidenceArtifact) and not resolved.path.is_file():
                    raise ValueError(
                        f"artifact {str(ref.get('artifact') or '')!r} not found/readable under {resolved.base_root}"
                    )
                entry = resolved.receipt_entry()
            except (OSError, ValueError) as exc:
                violations.append(f"{where}: {exc}")
                continue
            entries[resolved.identity] = entry
    violations.extend(_stale_source_snapshot_violations(source_roots))
    return [entries[key] for key in sorted(entries)], violations


def verification_evidence_digest(claims: Any, artifacts: Any) -> str:
    refs = [
        {
            "source_unit_id": ref.get("source_unit_id", ""),
            "artifact": ref.get("artifact", ""),
            "external_source": ref.get("external_source", {}),
            "locator": ref.get("locator", ""),
            "quote": ref.get("quote", ""),
        }
        for claim in claims
        if isinstance(claim, dict)
        for ref in (claim.get("evidence_refs") or [])
        if isinstance(ref, dict)
    ] if isinstance(claims, (list, tuple)) else []
    refs.sort(key=lambda ref: _canonical_json(_canonical_digest_value(ref)))
    artifact_items = [item for item in artifacts if isinstance(item, dict)] if isinstance(artifacts, (list, tuple)) else []
    artifact_items.sort(key=lambda item: str(item.get("identity") or ""))
    return _sha256_canonical({"evidence_refs": refs, "artifacts": artifact_items})


def build_verification_receipt(
    record: dict[str, Any],
    unit_dir: str | Path | EvidenceSourceSnapshot,
    *,
    external_source: dict[str, Any] | None = None,
    source_roots: dict[str, str | Path | EvidenceSourceSnapshot] | None = None,
    verified_at: str = "",
) -> dict[str, Any]:
    """Validate canonical claims and persist their byte-bound verification receipt."""
    claims = confirmation_claims(record)
    if not claims:
        raise SystemExit("Verification requires non-empty canonical payload.claims.")
    violations = validate_claims(claims)
    violations.extend(
        violation
        for claim in claims
        for violation in verify_claim_evidence(
            claim,
            unit_dir,
            external_source=external_source,
            source_roots=source_roots,
        )
    )
    artifacts, artifact_violations = evidence_artifact_entries(
        claims,
        unit_dir,
        external_source=external_source,
        source_roots=source_roots,
    )
    violations.extend(artifact_violations)
    if violations:
        raise SystemExit("Verification claim/evidence violations:\n  - " + "\n  - ".join(violations))
    receipt = {
        "verified_at": str(verified_at or utc_now_iso()),
        "claims_digest": claims_digest(claims),
        "evidence_digest": verification_evidence_digest(claims, artifacts),
        "artifacts": artifacts,
    }
    payload = record.setdefault("payload", {})
    if not isinstance(payload, dict):
        raise SystemExit("Verification requires a mapping record.payload.")
    payload["verification"] = receipt
    return receipt


def verification_receipt_violations(
    record: Any,
    unit_dir: str | Path | EvidenceSourceSnapshot | None,
    *,
    external_source: dict[str, Any] | None = None,
    source_roots: dict[str, str | Path | EvidenceSourceSnapshot] | None = None,
    check_artifacts: bool = True,
) -> list[str]:
    """Return why the stored analyzer verification is not current."""
    if not isinstance(record, dict):
        return ["record must be a mapping"]
    payload = record.get("payload")
    receipt = payload.get("verification") if isinstance(payload, dict) else None
    if not isinstance(receipt, dict):
        return ["missing payload.verification receipt"]
    claims = confirmation_claims(record)
    if not claims:
        return ["canonical payload.claims must be non-empty"]
    violations: list[str] = []
    verified_at = str(receipt.get("verified_at") or "").strip()
    if not verified_at:
        violations.append("verification receipt missing verified_at")
    for field_name in ("claims_digest", "evidence_digest"):
        if re.fullmatch(r"[0-9a-f]{64}", str(receipt.get(field_name) or "")) is None:
            violations.append(f"verification receipt has invalid {field_name}")
    current_claims_digest = claims_digest(claims)
    if str(receipt.get("claims_digest") or "") != current_claims_digest:
        violations.append("verification claims_digest does not match canonical payload.claims")
    stored_artifacts = receipt.get("artifacts")
    if not isinstance(stored_artifacts, list) or not stored_artifacts:
        violations.append("verification receipt artifacts must be a non-empty list")
        stored_artifacts = []
    if check_artifacts:
        if unit_dir is None:
            violations.append("cannot validate verification artifacts without unit_dir")
        else:
            current_artifacts, artifact_violations = evidence_artifact_entries(
                claims,
                unit_dir,
                external_source=external_source,
                source_roots=source_roots,
            )
            violations.extend(artifact_violations)
            if _canonical_digest_value(stored_artifacts) != _canonical_digest_value(current_artifacts):
                violations.append("verification artifact identity or byte sha256 changed")
            current_evidence_digest = verification_evidence_digest(claims, current_artifacts)
            if str(receipt.get("evidence_digest") or "") != current_evidence_digest:
                violations.append("verification evidence_digest does not match current evidence bytes")
    return violations


def validate_claims(claims: Any) -> list[str]:
    """Validate claim structure and the judgement/evidence completeness rules.

    Returns a list of violation strings (empty == all claims well-formed). Checks
    per claim: required fields present (id/text/claim_type/confirmation_status/
    evidence_refs), `claim_type` in the enum, `confirmation_status` in the enum,
    `evidence_refs` is a list, and — the gate interlock criterion (SSOT
    Principle 2/3) — a judgement-class claim
    (`inference`/`evaluation`/`user_opinion`) must have a **non-empty**
    `evidence_refs` (empty => violation). Fact and unverified claims may carry an
    empty list, but every ref that is present must be a mapping with non-empty
    `source_unit_id`, `artifact`, `locator`, and `quote` text.

    This is a pure criterion function: it does NOT mutate any gate or record. The
    Gate track consumes it to enforce "judgement claims with no evidence must not
    be promoted to confirmed"; this module never touches the gate itself.
    """
    violations: list[str] = []
    if not isinstance(claims, (list, tuple)):
        return ["claims payload must be a list"]

    for idx, claim in enumerate(claims):
        label = f"claims[{idx}]"
        if not isinstance(claim, dict):
            violations.append(f"{label}: not a mapping")
            continue
        claim_id = str(claim.get("id") or "").strip()
        ident = claim_id or label

        for field_name in REQUIRED_CLAIM_FIELDS:
            if field_name not in claim:
                violations.append(f"{ident}: missing required field '{field_name}'")

        if not claim_id:
            violations.append(f"{label}: missing/empty 'id'")
        if not str(claim.get("text") or "").strip():
            violations.append(f"{ident}: missing/empty 'text'")

        claim_type = claim.get("claim_type")
        if claim_type is not None and claim_type not in CLAIM_TYPES:
            violations.append(
                f"{ident}: invalid claim_type '{claim_type}' (expected one of {sorted(CLAIM_TYPES)})"
            )

        status = claim.get("confirmation_status")
        if status is not None and status not in CLAIM_CONFIRMATION_VALUES:
            violations.append(
                f"{ident}: invalid confirmation_status '{status}' "
                f"(expected one of {sorted(CLAIM_CONFIRMATION_VALUES)})"
            )

        refs = claim.get("evidence_refs")
        if refs is not None and not isinstance(refs, (list, tuple)):
            violations.append(f"{ident}: evidence_refs must be a list")
            refs = None

        if claim_type in JUDGEMENT_CLAIM_TYPES and not refs:
            violations.append(
                f"{ident}: judgement-class claim ('{claim_type}') has empty evidence_refs "
                f"— cannot be confirmed without evidence"
            )
        if refs:
            for ref_index, ref in enumerate(refs):
                ref_label = f"{ident}.evidence_refs[{ref_index}]"
                if not isinstance(ref, dict):
                    violations.append(f"{ref_label}: not a mapping")
                    continue
                for field_name in REQUIRED_EVIDENCE_REF_FIELDS:
                    if field_name not in ref:
                        violations.append(f"{ref_label}: missing required field '{field_name}'")
                    elif not isinstance(ref.get(field_name), str) or not ref[field_name].strip():
                        violations.append(f"{ref_label}: missing/empty '{field_name}'")
    return violations


# --------------------------------------------------------------------------- #
# Attach / read claims on a note or screening payload (schema-consistent)      #
# --------------------------------------------------------------------------- #

CLAIMS_KEY = "claims"


def as_claim_dict(claim: Any) -> dict[str, Any]:
    """Coerce a Claim / EvidenceRef-bearing object or dict to a plain dict.

    Ensures every stored claim carries the canonical keys in a stable shape so
    downstream readers (Gate/analyzer, later waves) see a uniform schema.
    """
    if isinstance(claim, Claim):
        data = asdict(claim)
    elif isinstance(claim, dict):
        data = dict(claim)
    else:
        raise TypeError(f"claim must be a Claim or mapping, got {type(claim).__name__}")
    refs = data.get("evidence_refs") or []
    coerced_refs: list[dict[str, Any]] = []
    for ref in refs:
        if isinstance(ref, EvidenceRef):
            coerced_refs.append(asdict(ref))
        elif isinstance(ref, dict):
            coerced_refs.append(dict(ref))
        else:
            raise TypeError(f"evidence_ref must be an EvidenceRef or mapping, got {type(ref).__name__}")
    data["evidence_refs"] = coerced_refs
    return data


def attach_claims(payload: Any, claims: Any) -> dict[str, Any]:
    """Write a `claims` list onto a note/screening payload dict, return payload.

    Claims may be `Claim` dataclasses or plain dicts; they are normalized to
    dicts under `payload["claims"]` (SSOT: "note/screening 产物内的 claims 列表").
    Additive: it only sets one key and never removes existing payload fields.
    """
    if not isinstance(payload, dict):
        raise TypeError(f"payload must be a mapping, got {type(payload).__name__}")
    if claims is None:
        claims = []
    if not isinstance(claims, (list, tuple)):
        raise TypeError(f"claims must be a list, got {type(claims).__name__}")
    payload[CLAIMS_KEY] = [as_claim_dict(claim) for claim in claims]
    return payload


def read_claims(payload: Any) -> list[dict[str, Any]]:
    """Read the `claims` list from a note/screening payload (or [] if absent)."""
    if not isinstance(payload, dict):
        return []
    claims = payload.get(CLAIMS_KEY)
    if not isinstance(claims, (list, tuple)):
        return []
    return [claim for claim in claims if isinstance(claim, dict)]


__all__ = [
    "CLAIM_TYPES",
    "JUDGEMENT_CLAIM_TYPES",
    "UNCONFIRMABLE_CLAIM_TYPES",
    "CLAIM_CONFIRMATION_VALUES",
    "PDF_LOCATOR_KINDS",
    "HTML_LOCATOR_KINDS",
    "EXTERNAL_SOURCE_KINDS",
    "REQUIRED_CLAIM_FIELDS",
    "REQUIRED_EVIDENCE_REF_FIELDS",
    "CONFIRMABLE_CONTENT_SECTIONS",
    "CONFIRMABLE_CONTENT_FIELDS",
    "EVIDENCE_SCHEMA",
    "CLAIMS_KEY",
    "EvidenceRef",
    "Claim",
    "ResolvedEvidenceArtifact",
    "EvidenceArtifactSnapshot",
    "EvidenceSourceSnapshot",
    "normalize_ws",
    "confirmation_claims",
    "confirmation_claim_ids",
    "claims_digest",
    "confirmation_content_digest",
    "confirmation_evidence_digest",
    "record_external_source_contract",
    "resolve_evidence_artifact",
    "verify_claim_evidence",
    "evidence_artifact_entries",
    "verification_evidence_digest",
    "build_verification_receipt",
    "verification_receipt_violations",
    "validate_claims",
    "as_claim_dict",
    "attach_claims",
    "read_claims",
]
