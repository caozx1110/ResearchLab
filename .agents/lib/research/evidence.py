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
`temp/SYSTEM_DESIGN_SSOT.md` Part 2 / Principle 2.

Verification model (SSOT B3/B4):
  * Every evidence_ref carries a **short verbatim `quote`**. The script loads the
    referenced `artifact` and checks the quote is a **whitespace-normalized
    verbatim substring** (consecutive whitespace folded to one space + strip;
    case preserved). Hit => grounded; miss => a violation string.
  * `locator` has two families: PDF (`page=N` / `section` / `para`) and HTML
    (`section` / `anchor`, no page numbers). When a parse-cache exposes per-page
    chunks and the locator is `page=N`, verification additionally narrows to that
    page: a quote that is verbatim in the document but on a *different* page is a
    (distinct) locator-mismatch violation. The verbatim hit remains the hard
    criterion; page narrowing is a precision bonus that degrades gracefully.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

# Vocabulary (mirrors research-record information_types + confirmation values).
CLAIM_TYPES = {"fact", "inference", "evaluation", "user_opinion", "unverified"}
# Judgement-class claims must carry evidence before they may be promoted to
# confirmed (SSOT Principle 2 / gate interlock). This module supplies the
# criterion function; the parallel Gate track wires it into the gate.
JUDGEMENT_CLAIM_TYPES = {"inference", "evaluation"}
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

# Required top-level keys on every claim (validate_claims enforces presence).
REQUIRED_CLAIM_FIELDS = ("id", "text", "claim_type", "confirmation_status", "evidence_refs")

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


def _page_of_label(label: Any) -> int | None:
    """Extract a page number from a parse-cache chunk label like 'foo:page-3'."""
    if not label:
        return None
    match = re.search(r"page[-_ ]?(\d+)", str(label), flags=re.IGNORECASE)
    return int(match.group(1)) if match else None


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
    """Loaded artifact text: full blob plus optional per-page index."""

    full_text: str = ""
    pages: dict[int, str] = field(default_factory=dict)


def _load_artifact(base: Path, artifact: str) -> _LoadedArtifact | None:
    """Load an artifact's searchable text. Returns None if it cannot be read."""
    if not artifact:
        return None
    path = base / artifact
    if not path.is_file():
        return None
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if path.suffix.lower() in {".yaml", ".yml"}:
        try:
            data = yaml.safe_load(raw)
        except yaml.YAMLError:
            # Fall back to raw text so a quote can still be matched.
            return _LoadedArtifact(full_text=raw)
        return _LoadedArtifact(full_text=_yaml_text_blob(data), pages=_artifact_pages(data))
    return _LoadedArtifact(full_text=raw)


def verify_claim_evidence(claim: Any, unit_dir: str | Path | None) -> list[str]:
    """Return a list of evidence violations for `claim` (empty == fully grounded).

    For each `evidence_ref` the referenced `artifact` is loaded under `unit_dir`
    and its `quote` is checked to be a whitespace-normalized verbatim substring
    (SSOT B3). Reported violations cover: missing/unverifiable quote, artifact
    that cannot be read, quote-not-found, and — when the artifact exposes
    per-page chunks and the locator is `page=N` — a quote present in the document
    but on a different page (locator mismatch). Degenerate inputs (non-dict
    claim, no refs, `unit_dir=None`) never raise; they yield [] or a precise
    violation rather than crashing.
    """
    violations: list[str] = []
    if not isinstance(claim, dict):
        return violations
    refs = claim.get("evidence_refs") or []
    if not isinstance(refs, (list, tuple)):
        return [f"claim {claim.get('id') or '<no-id>'}: evidence_refs must be a list"]
    claim_id = str(claim.get("id") or "<no-id>")
    base = Path(unit_dir) if unit_dir is not None else None

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
        if base is None:
            violations.append(
                f"{where}: cannot resolve artifact '{artifact}' (no unit_dir) for quote '{_quote_digest(quote)}'"
            )
            continue
        loaded = _load_artifact(base, artifact)
        if loaded is None:
            violations.append(
                f"{where}: artifact '{artifact}' not found/readable under {base} for quote '{_quote_digest(quote)}'"
            )
            continue
        norm_full = normalize_ws(loaded.full_text)
        if norm_quote not in norm_full:
            violations.append(
                f"{where}: quote '{_quote_digest(quote)}' not verbatim in artifact '{artifact}'"
            )
            continue
        # Grounded in the document. Optional locator narrowing (PDF page=N): if
        # the artifact has per-page chunks, confirm the quote is on the cited
        # page; a hit on a different page is a locator-mismatch violation.
        page = _page_of_locator(ref.get("locator"))
        if page is not None and loaded.pages:
            cited = normalize_ws(loaded.pages.get(page, ""))
            if norm_quote not in cited:
                found_on = sorted(p for p, t in loaded.pages.items() if norm_quote in normalize_ws(t))
                found_desc = f"page(s) {found_on}" if found_on else "outside indexed pages"
                violations.append(
                    f"{where}: quote '{_quote_digest(quote)}' grounded but locator page={page} "
                    f"is wrong (found on {found_desc})"
                )
    return violations


def validate_claims(claims: Any) -> list[str]:
    """Validate claim *structure* and the judgement-class empty-evidence rule.

    Returns a list of violation strings (empty == all claims well-formed). Checks
    per claim: required fields present (id/text/claim_type/confirmation_status/
    evidence_refs), `claim_type` in the enum, `confirmation_status` in the enum,
    `evidence_refs` is a list, and — the gate interlock criterion (SSOT
    Principle 2/3) — a judgement-class claim (`inference`/`evaluation`) must have
    a **non-empty** `evidence_refs` (empty => violation). Fact-class claims may
    carry an empty `evidence_refs`.

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
    "CLAIM_CONFIRMATION_VALUES",
    "PDF_LOCATOR_KINDS",
    "HTML_LOCATOR_KINDS",
    "REQUIRED_CLAIM_FIELDS",
    "EVIDENCE_SCHEMA",
    "CLAIMS_KEY",
    "EvidenceRef",
    "Claim",
    "normalize_ws",
    "verify_claim_evidence",
    "validate_claims",
    "as_claim_dict",
    "attach_claims",
    "read_claims",
]
