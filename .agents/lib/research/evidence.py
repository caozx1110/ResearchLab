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
    (`section` / `anchor`, no page numbers). When a parse-cache exposes per-page
    chunks and the locator is `page=N`, verification additionally narrows to that
    page: a quote that is verbatim in the document but on a *different* page is a
    (distinct) locator-mismatch violation. The verbatim hit remains the hard
    criterion; page narrowing is a precision bonus that degrades gracefully.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

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
    "program_decision": ("decision",),
    "idea_discussion_conclusion": ("discussion_conclusion",),
    "method_selection": ("method_selection",),
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
    """Loaded artifact text: independent full-document views plus page index.

    YAML needs two views: its original UTF-8 text preserves configuration keys,
    scalar spelling, and quoting, while its parsed structure exposes chunk text
    after YAML escape/block-scalar decoding.  The views remain separate so a
    quote cannot become a false hit by spanning their concatenation boundary.
    """

    full_text: str = ""
    structured_text: str = ""
    pages: dict[int, str] = field(default_factory=dict)

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


def _load_artifact_path(path: Path) -> _LoadedArtifact | None:
    """Load a containment-checked artifact's searchable text."""
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
        return _LoadedArtifact(
            full_text=raw,
            structured_text=_yaml_text_blob(data),
            pages=_artifact_pages(data),
        )
    return _LoadedArtifact(full_text=raw)


def _ref_unit_dir(
    ref: dict[str, Any],
    unit_dir: str | Path | None,
    source_roots: dict[str, str | Path] | None,
) -> str | Path | None:
    if source_roots is None:
        return unit_dir
    source_unit_id = str(ref.get("source_unit_id") or "").strip()
    if not source_unit_id or source_unit_id not in source_roots:
        raise ValueError(f"no trusted unit root for source_unit_id {source_unit_id or '<missing>'!r}")
    return source_roots[source_unit_id]


def verify_claim_evidence(
    claim: Any,
    unit_dir: str | Path | None,
    *,
    external_source: dict[str, Any] | None = None,
    source_roots: dict[str, str | Path] | None = None,
) -> list[str]:
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
        try:
            ref_base = _ref_unit_dir(ref, base, source_roots)
            resolved = resolve_evidence_artifact(ref, ref_base, external_source=external_source)
        except ValueError as exc:
            violations.append(f"{where}: {exc} for quote '{_quote_digest(quote)}'")
            continue
        loaded = _load_artifact_path(resolved.path)
        if loaded is None:
            violations.append(
                f"{where}: artifact '{artifact}' not found/readable under {resolved.base_root} "
                f"for quote '{_quote_digest(quote)}'"
            )
            continue
        norm_full_views = [normalize_ws(text) for text in loaded.searchable_texts()]
        if not any(norm_quote in text for text in norm_full_views):
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


def evidence_artifact_entries(
    claims: Any,
    unit_dir: str | Path | None,
    *,
    external_source: dict[str, Any] | None = None,
    source_roots: dict[str, str | Path] | None = None,
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
                resolved = resolve_evidence_artifact(ref, ref_base, external_source=external_source)
                if not resolved.path.is_file():
                    raise ValueError(
                        f"artifact {str(ref.get('artifact') or '')!r} not found/readable under {resolved.base_root}"
                    )
                entry = resolved.receipt_entry()
            except (OSError, ValueError) as exc:
                violations.append(f"{where}: {exc}")
                continue
            entries[resolved.identity] = entry
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
    unit_dir: str | Path,
    *,
    external_source: dict[str, Any] | None = None,
    source_roots: dict[str, str | Path] | None = None,
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
    unit_dir: str | Path | None,
    *,
    external_source: dict[str, Any] | None = None,
    source_roots: dict[str, str | Path] | None = None,
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
