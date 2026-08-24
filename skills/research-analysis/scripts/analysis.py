"""Mechanical support for the Research Vault v2 Markdown analysis contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional, Sequence, Tuple, Union

import yaml


CLAIM_CLASSES = frozenset(
    {
        "observation",
        "extracted_fact",
        "inference",
        "evaluation",
        "recommendation",
        "diagnosis",
        "decision",
    }
)
EPISTEMIC_STATES = frozenset({"factual", "interpretive", "uncertain"})
REVIEW_STATES = frozenset({"draft", "pending", "stale", "deferred", "rejected"})
LOCATOR_KINDS = frozenset(
    {
        "binary",
        "dataset",
        "html",
        "markdown",
        "media",
        "pdf",
        "repo",
        "slide",
        "spreadsheet",
        "whole-document",
    }
)
FACTUAL_CLASSES = frozenset({"observation", "extracted_fact"})
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*\Z")
DIGEST_RE = re.compile(r"[0-9a-f]{64}\Z")
HEADING_RE = re.compile(
    r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$",
    re.MULTILINE,
)
FIELD_RE = re.compile(
    r"^\s*-\s+(?P<label>[A-Za-z][A-Za-z -]*):\s*(?P<value>.*?)\s*\Z"
)


class AnalysisContractError(ValueError):
    """Raised when visible analysis data cannot satisfy the v2 contract."""


def sha256_digest(value: Union[str, bytes]) -> str:
    """Return a stable, explicitly typed SHA-256 digest."""

    payload = value.encode("utf-8") if isinstance(value, str) else value
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


def canonical_digest(value: Any) -> str:
    """Digest JSON data without giving hidden records semantic authority."""

    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_digest(encoded)


def _normalize_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnalysisContractError(f"{label} must be a SHA-256 digest")
    raw = value.strip().lower()
    if raw.startswith("sha256:"):
        raw = raw[7:]
    if not DIGEST_RE.fullmatch(raw):
        raise AnalysisContractError(f"{label} must be a SHA-256 digest")
    return f"sha256:{raw}"


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnalysisContractError(f"{label} must be a non-empty identifier")
    value = value.strip()
    if not IDENTIFIER_RE.fullmatch(value):
        raise AnalysisContractError(f"{label} contains unsafe characters")
    return value


def _markdown_code(value: str) -> str:
    return value.replace("`", "\\`").replace("\r", "")


def _clean_value(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`") and len(value) >= 2:
        value = value[1:-1]
    if value.startswith("**") and value.endswith("**") and len(value) >= 4:
        value = value[2:-2].strip()
    return value.strip()


def _relative_artifact_path(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AnalysisContractError("artifact path must be non-empty")
    value = value.strip()
    if "\\" in value:
        raise AnalysisContractError("artifact path must use POSIX separators")
    return value


def _validate_locator(locator: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(locator, Mapping):
        raise AnalysisContractError("locator must be a mapping")
    result = dict(locator)
    kind = result.get("kind")
    if kind not in LOCATOR_KINDS:
        raise AnalysisContractError(
            f"locator kind must be one of {sorted(LOCATOR_KINDS)}"
        )
    if kind == "whole-document":
        return result
    if not any(
        key in result
        for key in (
            "heading",
            "fragment",
            "paragraph",
            "page",
            "path",
            "line_start",
            "sheet",
            "cell",
            "row_key",
            "timestamp",
            "member",
            "object",
        )
    ):
        raise AnalysisContractError("typed locator must identify a location")
    path_value = result.get("path")
    if isinstance(path_value, str):
        if path_value.startswith("/") or "\\" in path_value:
            raise AnalysisContractError("locator path must be relative POSIX text")
        if ".." in Path(path_value).parts:
            raise AnalysisContractError("locator path must stay within the source")
    return result


@dataclass(frozen=True)
class SourceRevision:
    source_id: str
    revision: str
    artifact_path: str
    artifact_digest: str
    reader_digest: Optional[str] = None
    source_kind: str = "document"
    current: bool = True

    def __post_init__(self) -> None:
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        object.__setattr__(self, "revision", _identifier(self.revision, "revision"))
        object.__setattr__(
            self,
            "artifact_path",
            _relative_artifact_path(self.artifact_path),
        )
        object.__setattr__(
            self,
            "artifact_digest",
            _normalize_digest(self.artifact_digest, "artifact_digest"),
        )
        reader_digest = self.reader_digest or self.artifact_digest
        object.__setattr__(
            self,
            "reader_digest",
            _normalize_digest(reader_digest, "reader_digest"),
        )
        if not isinstance(self.source_kind, str) or not self.source_kind.strip():
            raise AnalysisContractError("source_kind must be non-empty")
        if not isinstance(self.current, bool):
            raise AnalysisContractError("current must be boolean")

    @classmethod
    def from_file(
        cls,
        source_id: str,
        revision: str,
        artifact_path: Union[str, Path],
        *,
        reader_digest: Optional[str] = None,
        source_kind: str = "document",
        current: bool = True,
    ) -> "SourceRevision":
        path = Path(artifact_path)
        data = _read_regular_file(path)
        return cls(
            source_id=source_id,
            revision=revision,
            artifact_path=str(path),
            artifact_digest=sha256_digest(data),
            reader_digest=reader_digest or sha256_digest(data),
            source_kind=source_kind,
            current=current,
        )

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "SourceRevision":
        return cls(
            source_id=payload.get("source_id", ""),
            revision=payload.get("revision", payload.get("source_revision", "")),
            artifact_path=payload.get("artifact_path", payload.get("artifact", "")),
            artifact_digest=payload.get("artifact_digest", ""),
            reader_digest=payload.get("reader_digest"),
            source_kind=payload.get("source_kind", "document"),
            current=payload.get("current", True),
        )

    @property
    def key(self) -> tuple[str, str]:
        return self.source_id, self.revision

    @property
    def identity(self) -> str:
        return f"{self.source_id}@{self.revision}"

    def as_visible(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "revision": self.revision,
            "artifact_path": self.artifact_path,
            "artifact_digest": self.artifact_digest,
            "reader_digest": self.reader_digest,
            "source_kind": self.source_kind,
        }


@dataclass(frozen=True)
class Evidence:
    evidence_id: str
    source_id: str
    revision: str
    artifact_path: str
    locator: Mapping[str, Any]
    quote: str
    artifact_digest: str
    reader_digest: str
    quote_digest: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "evidence_id",
            _identifier(self.evidence_id, "evidence_id"),
        )
        object.__setattr__(self, "source_id", _identifier(self.source_id, "source_id"))
        object.__setattr__(self, "revision", _identifier(self.revision, "revision"))
        object.__setattr__(
            self,
            "artifact_path",
            _relative_artifact_path(self.artifact_path),
        )
        if not isinstance(self.quote, str) or not self.quote:
            raise AnalysisContractError("evidence quote must be non-empty")
        object.__setattr__(self, "locator", _validate_locator(self.locator))
        object.__setattr__(
            self,
            "artifact_digest",
            _normalize_digest(self.artifact_digest, "artifact_digest"),
        )
        object.__setattr__(
            self,
            "reader_digest",
            _normalize_digest(self.reader_digest, "reader_digest"),
        )
        quote_digest = self.quote_digest or sha256_digest(self.quote)
        object.__setattr__(
            self,
            "quote_digest",
            _normalize_digest(quote_digest, "quote_digest"),
        )

    @property
    def source_key(self) -> tuple[str, str]:
        return self.source_id, self.revision

    def digest_payload(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_id": self.source_id,
            "revision": self.revision,
            "artifact_path": self.artifact_path,
            "locator": dict(self.locator),
            "quote": self.quote,
            "artifact_digest": self.artifact_digest,
            "reader_digest": self.reader_digest,
            "quote_digest": self.quote_digest,
        }

    @property
    def evidence_digest(self) -> str:
        return canonical_digest(self.digest_payload())


@dataclass(frozen=True)
class Claim:
    claim_id: str
    text: str
    claim_class: str
    epistemic_state: str
    evidence_ids: Tuple[str, ...]
    review_state: str = "pending"
    limitations: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(self, "claim_id", _identifier(self.claim_id, "claim_id"))
        if not isinstance(self.text, str) or not self.text.strip():
            raise AnalysisContractError("claim text must be non-empty")
        if "\n" in self.text or "\r" in self.text:
            raise AnalysisContractError("claim text must be one visible paragraph")
        if self.claim_class not in CLAIM_CLASSES:
            raise AnalysisContractError(
                f"claim class must be one of {sorted(CLAIM_CLASSES)}"
            )
        if self.epistemic_state not in EPISTEMIC_STATES:
            raise AnalysisContractError(
                f"epistemic state must be one of {sorted(EPISTEMIC_STATES)}"
            )
        if self.claim_class in FACTUAL_CLASSES:
            allowed_states = {"factual", "uncertain"}
        else:
            allowed_states = {"interpretive", "uncertain"}
        if self.epistemic_state not in allowed_states:
            raise AnalysisContractError(
                f"{self.claim_class} claims must be factual/interpretive or uncertain"
            )
        if self.review_state not in REVIEW_STATES:
            raise AnalysisContractError(
                "analysis cannot self-authorize confirmation; review state must be "
                f"one of {sorted(REVIEW_STATES)}"
            )
        evidence_ids = tuple(str(item).strip() for item in self.evidence_ids)
        if not evidence_ids or any(not item for item in evidence_ids):
            raise AnalysisContractError("every claim must reference evidence")
        if len(set(evidence_ids)) != len(evidence_ids):
            raise AnalysisContractError("claim evidence IDs must be unique")
        for evidence_id in evidence_ids:
            _identifier(evidence_id, "evidence_id")
        object.__setattr__(self, "evidence_ids", evidence_ids)
        if not isinstance(self.limitations, str):
            raise AnalysisContractError("limitations must be text")

    def digest_payload(self) -> dict[str, Any]:
        return {
            "claim_id": self.claim_id,
            "text": self.text,
            "class": self.claim_class,
            "epistemic_state": self.epistemic_state,
            "review_state": self.review_state,
            "evidence_ids": list(self.evidence_ids),
            "limitations": self.limitations,
        }

    @property
    def claim_digest(self) -> str:
        return canonical_digest(self.digest_payload())


@dataclass(frozen=True)
class ParsedAnalysis:
    analysis_id: str
    kind: str
    subject: str
    scope: str
    non_goals: Tuple[str, ...]
    source_revisions: Tuple[SourceRevision, ...]
    claims: Tuple[Claim, ...]
    evidence: Tuple[Evidence, ...]
    selection_boundary: str
    conflicts: Tuple[str, ...]
    gaps: Tuple[str, ...]

    @property
    def claims_by_id(self) -> dict[str, Claim]:
        return {claim.claim_id: claim for claim in self.claims}

    @property
    def evidence_by_id(self) -> dict[str, Evidence]:
        return {item.evidence_id: item for item in self.evidence}


@dataclass(frozen=True)
class VerificationReport:
    document: Optional[ParsedAnalysis]
    errors: Tuple[str, ...]
    stale_by_claim: Mapping[str, Tuple[str, ...]]

    @property
    def valid(self) -> bool:
        return not self.errors

    @property
    def current(self) -> bool:
        return self.valid and not self.stale_by_claim

    @property
    def ok(self) -> bool:
        return self.current

    @property
    def stale_claims(self) -> tuple[str, ...]:
        return tuple(sorted(self.stale_by_claim))

    def effective_state(self, claim_id: str) -> str:
        if claim_id in self.stale_by_claim:
            return "stale"
        if self.document is None:
            raise AnalysisContractError("no parsed document is available")
        claim = self.document.claims_by_id.get(claim_id)
        if claim is None:
            raise AnalysisContractError(f"unknown claim: {claim_id}")
        return claim.review_state


def _read_regular_file(path: Path) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise AnalysisContractError(f"cannot read source artifact {path}: {exc}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise AnalysisContractError(f"source artifact is not a regular file: {path}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise AnalysisContractError(f"cannot read source artifact {path}: {exc}") from exc


def _artifact_path(path_text: str, base_dir: Optional[Path]) -> Path:
    path = Path(path_text)
    if not path.is_absolute() and base_dir is not None:
        path = base_dir / path
    return path


def _split_frontmatter(markdown: str) -> tuple[dict[str, Any], str]:
    if not markdown.startswith("---\n"):
        raise AnalysisContractError("analysis Markdown must start with YAML frontmatter")
    closing = markdown.find("\n---\n", 4)
    if closing < 0:
        raise AnalysisContractError("analysis Markdown frontmatter is not closed")
    raw = markdown[4:closing]
    try:
        payload = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        raise AnalysisContractError(f"invalid analysis frontmatter: {exc}") from exc
    if not isinstance(payload, dict):
        raise AnalysisContractError("analysis frontmatter must be a mapping")
    return payload, markdown[closing + 5 :]


def _heading_sections(markdown: str) -> list[tuple[int, str, str]]:
    matches = list(HEADING_RE.finditer(markdown))
    sections: list[tuple[int, str, str]] = []
    for index, match in enumerate(matches):
        level = len(match.group("marks"))
        end = len(markdown)
        for next_match in matches[index + 1 :]:
            if len(next_match.group("marks")) <= level:
                end = next_match.start()
                break
        sections.append((level, match.group("title").strip(), markdown[match.end() : end]))
    return sections


def _heading_id(title: str, prefix: str) -> str:
    match = re.search(r"`([^`]+)`", title)
    if match:
        return match.group(1).strip()
    remainder = re.sub(rf"^{re.escape(prefix)}\s+", "", title, flags=re.IGNORECASE)
    return remainder.strip()


def _fields(body: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in body.splitlines():
        match = FIELD_RE.match(line)
        if match:
            label = re.sub(r"\s+", " ", match.group("label").strip().lower())
            result[label] = _clean_value(match.group("value"))
    return result


def _quote_block(body: str) -> str:
    lines: list[str] = []
    started = False
    for line in body.splitlines():
        match = re.match(r"^\s*> ?(.*)\Z", line)
        if match:
            started = True
            lines.append(match.group(1))
        elif started:
            break
    return "\n".join(lines)


def _parse_locator(raw: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise AnalysisContractError("locator must be visible JSON") from exc
    return _validate_locator(value)


def _parse_evidence_ids(raw: str) -> tuple[str, ...]:
    values = re.findall(r"`([^`]+)`", raw)
    if not values:
        values = [item.strip() for item in raw.split(",") if item.strip()]
    return tuple(values)


def _parse_source(title: str, body: str) -> SourceRevision:
    fields = _fields(body)
    identity = _heading_id(title, "source")
    source_id = fields.get("source") or identity.split("@", 1)[0]
    revision = fields.get("revision")
    if revision is None and "@" in identity:
        revision = identity.rsplit("@", 1)[1]
    return SourceRevision(
        source_id=source_id,
        revision=revision or "",
        artifact_path=fields.get("artifact", ""),
        artifact_digest=fields.get("artifact digest", ""),
        reader_digest=fields.get("reader digest"),
        source_kind=fields.get("source kind", "document"),
    )


def _parse_claim(title: str, body: str) -> Claim:
    fields = _fields(body)
    return Claim(
        claim_id=_heading_id(title, "claim"),
        text=fields.get("claim", ""),
        claim_class=fields.get("class", ""),
        epistemic_state=fields.get("epistemic state", ""),
        evidence_ids=_parse_evidence_ids(fields.get("evidence", "")),
        review_state=fields.get("review state", ""),
        limitations=fields.get("limitations", ""),
    )


def _parse_evidence(title: str, body: str) -> Evidence:
    fields = _fields(body)
    quote = _quote_block(body)
    required = {
        "source": fields.get("source", ""),
        "revision": fields.get("revision", ""),
        "artifact": fields.get("artifact", ""),
        "locator": fields.get("locator", ""),
        "artifact digest": fields.get("artifact digest", ""),
        "reader digest": fields.get("reader digest", ""),
        "quote digest": fields.get("quote digest", ""),
    }
    missing = [key for key, value in required.items() if not value]
    if missing:
        raise AnalysisContractError(
            f"evidence {_heading_id(title, 'evidence')} is missing: {', '.join(missing)}"
        )
    return Evidence(
        evidence_id=_heading_id(title, "evidence"),
        source_id=required["source"],
        revision=required["revision"],
        artifact_path=required["artifact"],
        locator=_parse_locator(required["locator"]),
        quote=quote,
        artifact_digest=required["artifact digest"],
        reader_digest=required["reader digest"],
        quote_digest=required["quote digest"],
    )


def _section_items(sections: Sequence[tuple[int, str, str]], name: str) -> tuple[str, ...]:
    for level, title, body in sections:
        if level == 2 and title.casefold() == name.casefold():
            return tuple(
                line[2:].strip()
                for line in body.splitlines()
                if line.strip().startswith("- ") and not line.strip().startswith("<!--")
            )
    return ()


def parse_analysis(markdown: Union[str, Path]) -> ParsedAnalysis:
    if isinstance(markdown, Path):
        try:
            text = markdown.read_text(encoding="utf-8")
        except OSError as exc:
            raise AnalysisContractError(f"cannot read analysis Markdown: {exc}") from exc
    else:
        text = markdown
    frontmatter, body = _split_frontmatter(text)
    analysis_id = _identifier(frontmatter.get("analysis_id", ""), "analysis_id")
    kind = frontmatter.get("kind")
    if kind not in {"single-source", "synthesis"}:
        raise AnalysisContractError("analysis kind must be single-source or synthesis")
    subject = frontmatter.get("subject")
    if not isinstance(subject, str) or not subject.strip():
        raise AnalysisContractError("analysis subject must be non-empty")
    scope = frontmatter.get("scope", "")
    if not isinstance(scope, str):
        raise AnalysisContractError("analysis scope must be text")
    raw_non_goals = frontmatter.get("non_goals", ())
    if isinstance(raw_non_goals, str):
        non_goals = (raw_non_goals,)
    elif isinstance(raw_non_goals, list):
        non_goals = tuple(str(item) for item in raw_non_goals)
    else:
        non_goals = ()
    sections = _heading_sections(body)
    source_sections = [
        (title, section_body)
        for level, title, section_body in sections
        if level == 3 and title.casefold().startswith("source ")
    ]
    claim_sections = [
        (title, section_body)
        for level, title, section_body in sections
        if level == 3 and title.casefold().startswith("claim ")
    ]
    evidence_sections = [
        (title, section_body)
        for level, title, section_body in sections
        if level == 3 and title.casefold().startswith("evidence ")
    ]
    sources = tuple(_parse_source(title, section_body) for title, section_body in source_sections)
    claims = tuple(_parse_claim(title, section_body) for title, section_body in claim_sections)
    evidence = tuple(
        _parse_evidence(title, section_body) for title, section_body in evidence_sections
    )
    if len({item.source_id for item in sources}) != len(sources):
        raise AnalysisContractError("source identities must remain separate and unique")
    if len({claim.claim_id for claim in claims}) != len(claims):
        raise AnalysisContractError("claim IDs must be unique")
    if len({item.evidence_id for item in evidence}) != len(evidence):
        raise AnalysisContractError("evidence IDs must be unique")
    selection_boundary = str(frontmatter.get("selection_boundary", "") or "").strip()
    for level, title, section_body in sections:
        if level == 2 and title.casefold() == "selection boundary":
            selection_fields = _fields(section_body)
            selection_boundary = selection_fields.get("boundary", selection_boundary)
    conflicts = _section_items(sections, "conflicts")
    gaps = _section_items(sections, "coverage gaps")
    return ParsedAnalysis(
        analysis_id=analysis_id,
        kind=kind,
        subject=subject.strip(),
        scope=scope.strip(),
        non_goals=non_goals,
        source_revisions=sources,
        claims=claims,
        evidence=evidence,
        selection_boundary=selection_boundary,
        conflicts=conflicts,
        gaps=gaps,
    )


def _frontmatter(payload: Mapping[str, Any]) -> str:
    rendered = yaml.safe_dump(
        dict(payload),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    ).rstrip()
    return f"---\n{rendered}\n---\n"


def _render_source(source: SourceRevision) -> str:
    return "\n".join(
        (
            f"### Source `{_markdown_code(source.identity)}`",
            f"- Artifact: `{_markdown_code(source.artifact_path)}`",
            f"- Artifact digest: `{source.artifact_digest}`",
            f"- Reader digest: `{source.reader_digest}`",
            f"- Source kind: `{_markdown_code(source.source_kind)}`",
            "",
        )
    )


def _render_claim(claim: Claim) -> str:
    lines = [
        f"### Claim `{_markdown_code(claim.claim_id)}`",
        f"- Claim: {claim.text}",
        f"- Class: `{claim.claim_class}`",
        f"- Epistemic state: `{claim.epistemic_state}`",
        f"- Review state: `{claim.review_state}`",
        "- Evidence: " + ", ".join(f"`{_markdown_code(item)}`" for item in claim.evidence_ids),
    ]
    if claim.limitations:
        lines.append(f"- Limitations: {claim.limitations}")
    lines.append("")
    return "\n".join(lines)


def _render_evidence(evidence: Evidence) -> str:
    quote_lines = "\n".join(f"> {line}" if line else ">" for line in evidence.quote.split("\n"))
    locator = json.dumps(
        dict(evidence.locator),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return "\n".join(
        (
            f"### Evidence `{_markdown_code(evidence.evidence_id)}`",
            f"- Source: `{_markdown_code(evidence.source_id)}`",
            f"- Revision: `{_markdown_code(evidence.revision)}`",
            f"- Artifact: `{_markdown_code(evidence.artifact_path)}`",
            f"- Locator: `{_markdown_code(locator)}`",
            f"- Artifact digest: `{evidence.artifact_digest}`",
            f"- Reader digest: `{evidence.reader_digest}`",
            f"- Quote digest: `{evidence.quote_digest}`",
            "",
            quote_lines,
            "",
        )
    )


def render_analysis(
    *,
    analysis_id: str,
    subject: str,
    kind: str,
    sources: Sequence[SourceRevision] = (),
    scope: str = "",
    non_goals: Sequence[str] = (),
    selection_boundary: str = "",
    claims: Sequence[Claim] = (),
    evidence: Sequence[Evidence] = (),
    conflicts: Sequence[str] = (),
    gaps: Sequence[str] = (),
) -> str:
    if kind not in {"single-source", "synthesis"}:
        raise AnalysisContractError("analysis kind must be single-source or synthesis")
    if not isinstance(subject, str) or not subject.strip():
        raise AnalysisContractError("analysis subject must be non-empty")
    payload = {
        "analysis_id": _identifier(analysis_id, "analysis_id"),
        "kind": kind,
        "subject": subject.strip(),
        "scope": scope.strip(),
        "non_goals": list(non_goals),
        "selection_boundary": selection_boundary.strip(),
    }
    pieces = [
        _frontmatter(payload),
        f"# Analysis: {subject.strip()}\n\n",
        "## Scope\n",
        f"- Scope: {scope.strip()}\n" if scope.strip() else "<!-- Agent fill required: scope -->\n",
        "- Non-goals: "
        + ("; ".join(str(item) for item in non_goals) if non_goals else "Agent must state non-goals")
        + "\n\n",
        "## Inputs\n\n",
    ]
    if sources:
        pieces.extend(_render_source(source) for source in sources)
    else:
        pieces.append("<!-- Source revisions are frozen by the caller before Agent fill. -->\n\n")
    pieces.append("## Selection boundary\n\n")
    if selection_boundary.strip():
        pieces.append(f"- Boundary: {selection_boundary.strip()}\n\n")
    else:
        pieces.append("<!-- Agent fill required: included and excluded sources -->\n\n")
    pieces.append("## Claims\n\n")
    if claims:
        pieces.extend(_render_claim(claim) for claim in claims)
    else:
        pieces.append("<!-- Agent fill required: claims and epistemic states -->\n\n")
    pieces.append("## Evidence\n\n")
    if evidence:
        pieces.extend(_render_evidence(item) for item in evidence)
    else:
        pieces.append("<!-- Agent fill required: exact quotes and typed locators -->\n\n")
    pieces.append("## Conflicts\n\n")
    if conflicts:
        pieces.extend(f"- {item}\n" for item in conflicts)
    else:
        pieces.append("<!-- Agent records conflicts or explicitly states none. -->\n")
    pieces.append("\n## Coverage gaps\n\n")
    if gaps:
        pieces.extend(f"- {item}\n" for item in gaps)
    else:
        pieces.append("<!-- Agent records coverage gaps or explicitly states none. -->\n")
    return "".join(pieces)


def render_synthesis(**kwargs: Any) -> str:
    kwargs["kind"] = "synthesis"
    return render_analysis(**kwargs)


def prepare_analysis(
    *,
    analysis_id: str,
    subject: str,
    kind: str,
    sources: Sequence[SourceRevision] = (),
    scope: str = "",
    non_goals: Sequence[str] = (),
    selection_boundary: str = "",
) -> str:
    """Prepare an empty page; no claim text or source interpretation is created."""

    return render_analysis(
        analysis_id=analysis_id,
        subject=subject,
        kind=kind,
        sources=sources,
        scope=scope,
        non_goals=non_goals,
        selection_boundary=selection_boundary,
    )


def _source_index(
    sources: Union[Mapping[Any, Any], Iterable[Union[SourceRevision, Mapping[str, Any]]]]
) -> tuple[dict[tuple[str, str], SourceRevision], dict[str, list[SourceRevision]]]:
    if isinstance(sources, Mapping):
        values: Iterable[Any] = sources.values()
    else:
        values = sources
    exact: dict[tuple[str, str], SourceRevision] = {}
    by_id: dict[str, list[SourceRevision]] = {}
    for raw in values:
        item = raw if isinstance(raw, SourceRevision) else SourceRevision.from_mapping(raw)
        if item.key in exact:
            raise AnalysisContractError(f"duplicate source revision: {item.identity}")
        exact[item.key] = item
        by_id.setdefault(item.source_id, []).append(item)
    return exact, by_id


def _source_current(items: Sequence[SourceRevision]) -> Optional[SourceRevision]:
    current = [item for item in items if item.current]
    if len(current) > 1:
        raise AnalysisContractError(
            f"source has multiple current revisions: {current[0].source_id}"
        )
    return current[0] if current else None


def _read_source_text(source: SourceRevision, base_dir: Optional[Path]) -> tuple[bytes, str]:
    data = _read_regular_file(_artifact_path(source.artifact_path, base_dir))
    actual_digest = sha256_digest(data)
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise AnalysisContractError(
            f"source artifact is not UTF-8 Markdown/text: {source.artifact_path}"
        ) from exc
    return data, text


def _binding_payload(
    *,
    subject_markdown: str,
    claim: Claim,
    evidence: Sequence[Evidence],
    sources: Mapping[tuple[str, str], SourceRevision],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for item in evidence:
        source = sources.get(item.source_key)
        if source is None:
            raise AnalysisContractError(
                f"evidence {item.evidence_id} references unfrozen source {item.source_id}@{item.revision}"
            )
        if item.artifact_path != source.artifact_path:
            raise AnalysisContractError(f"evidence {item.evidence_id} artifact path disagrees with source")
        if item.artifact_digest != source.artifact_digest:
            raise AnalysisContractError(f"evidence {item.evidence_id} artifact digest disagrees with source")
        if item.reader_digest != source.reader_digest:
            raise AnalysisContractError(f"evidence {item.evidence_id} reader digest disagrees with source")
        rows.append(
            {
                "evidence_id": item.evidence_id,
                "evidence_digest": item.evidence_digest,
                "source_id": item.source_id,
                "source_revision": item.revision,
                "raw_artifact_path": source.artifact_path,
                "raw_artifact_digest": source.artifact_digest,
                "reader_digest": source.reader_digest,
                "locator": dict(item.locator),
                "exact_quote": item.quote,
                "quote_digest": item.quote_digest,
            }
        )
    payload: dict[str, Any] = {
        "schema": "research-analysis/evidence-binding/v2",
        "binding_id": f"{claim.claim_id}-binding",
        "subject_markdown": subject_markdown,
        "claim_id": claim.claim_id,
        "claim_digest": claim.claim_digest,
        "evidence": rows,
        "binding_state": "current",
    }
    payload["binding_digest"] = canonical_digest(payload)
    return payload


def build_bindings(
    analysis: Union[ParsedAnalysis, str, Path],
    sources: Union[Mapping[Any, Any], Iterable[Union[SourceRevision, Mapping[str, Any]]]],
    *,
    subject_markdown: Optional[str] = None,
    base_dir: Optional[Path] = None,
) -> dict[str, dict[str, Any]]:
    document = analysis if isinstance(analysis, ParsedAnalysis) else parse_analysis(analysis)
    exact, _ = _source_index(sources)
    bindings: dict[str, dict[str, Any]] = {}
    for claim in document.claims:
        evidence_items = []
        for evidence_id in claim.evidence_ids:
            evidence = document.evidence_by_id.get(evidence_id)
            if evidence is None:
                raise AnalysisContractError(f"claim {claim.claim_id} references missing {evidence_id}")
            source = exact.get(evidence.source_key)
            if source is None:
                raise AnalysisContractError(f"missing frozen source for {evidence.source_key}")
            _, source_text = _read_source_text(source, base_dir)
            if evidence.quote not in source_text:
                raise AnalysisContractError(
                    f"evidence {evidence.evidence_id} quote is not exact source text"
                )
            evidence_items.append(evidence)
        bindings[claim.claim_id] = _binding_payload(
            subject_markdown=subject_markdown or document.subject,
            claim=claim,
            evidence=evidence_items,
            sources=exact,
        )
    return bindings


def write_bindings(bindings: Mapping[str, Mapping[str, Any]], evidence_root: Union[str, Path]) -> None:
    root = Path(evidence_root)
    root.mkdir(parents=True, exist_ok=True)
    for claim_id, payload in bindings.items():
        safe_id = _identifier(claim_id, "claim_id")
        target = root / f"{safe_id}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(dict(payload), ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(target)


def _load_bindings(
    bindings: Optional[Union[Mapping[str, Any], Sequence[Mapping[str, Any]], str, Path]]
) -> dict[str, Mapping[str, Any]]:
    if bindings is None:
        return {}
    if isinstance(bindings, (str, Path)):
        path = Path(bindings)
        paths = sorted(path.glob("*.json")) if path.is_dir() else [path]
        loaded: list[Mapping[str, Any]] = []
        for item in paths:
            try:
                parsed = json.loads(item.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise AnalysisContractError(f"cannot read binding {item}: {exc}") from exc
            if not isinstance(parsed, Mapping):
                raise AnalysisContractError(f"binding {item} must be a JSON object")
            loaded.append(parsed)
        return {str(item.get("claim_id", "")): item for item in loaded}
    if isinstance(bindings, Mapping):
        if "claim_id" in bindings:
            return {str(bindings.get("claim_id")): bindings}
        return {str(key): value for key, value in bindings.items() if isinstance(value, Mapping)}
    return {str(item.get("claim_id", "")): item for item in bindings}


def _add_stale(stale: dict[str, set[str]], claim_id: str, reason: str) -> None:
    stale.setdefault(claim_id, set()).add(reason)


def _check_synthesis(document: ParsedAnalysis, errors: list[str]) -> None:
    if document.kind != "synthesis":
        return
    if len(document.source_revisions) < 2:
        errors.append("synthesis requires at least two independently named source revisions")
    if not document.selection_boundary or document.selection_boundary.startswith("Agent "):
        errors.append("synthesis requires a visible selection boundary")
    if not document.conflicts:
        errors.append("synthesis must visibly record conflicts or state that none were found")
    if not document.gaps:
        errors.append("synthesis must visibly record coverage gaps or state that none were found")


def verify_analysis(
    analysis: Union[str, Path],
    sources: Union[Mapping[Any, Any], Iterable[Union[SourceRevision, Mapping[str, Any]]]],
    *,
    bindings: Optional[Union[Mapping[str, Any], Sequence[Mapping[str, Any]], str, Path]] = None,
    base_dir: Optional[Path] = None,
    subject_markdown: Optional[str] = None,
) -> VerificationReport:
    try:
        document = parse_analysis(analysis)
        exact, by_id = _source_index(sources)
    except AnalysisContractError as exc:
        return VerificationReport(None, (str(exc),), {})
    errors: list[str] = []
    stale: dict[str, set[str]] = {}
    _check_synthesis(document, errors)
    if document.kind == "single-source" and len(document.source_revisions) != 1:
        errors.append("single-source analysis must freeze exactly one source revision")
    if not document.source_revisions:
        errors.append("analysis must freeze at least one source revision")
    if not document.claims:
        errors.append("analysis requires at least one Agent-authored claim")
    if not document.evidence:
        errors.append("analysis requires visible exact evidence")
    claims_by_source: dict[tuple[str, str], set[str]] = {}
    for claim in document.claims:
        for evidence_id in claim.evidence_ids:
            evidence = document.evidence_by_id.get(evidence_id)
            if evidence is not None:
                claims_by_source.setdefault(evidence.source_key, set()).add(claim.claim_id)
    for visible_source in document.source_revisions:
        exact_source = exact.get(visible_source.key)
        current_source = _source_current(by_id.get(visible_source.source_id, ()))
        dependent_claims = set().union(
            *(claims_by_source.get(key, set()) for key in claims_by_source if key[0] == visible_source.source_id)
        )
        if exact_source is None:
            if current_source is not None:
                for claim_id in dependent_claims:
                    _add_stale(stale, claim_id, "source revision changed")
            else:
                errors.append(f"source revision is not present in frozen inputs: {visible_source.identity}")
            continue
        if current_source is not None and current_source.revision != visible_source.revision:
            for claim_id in dependent_claims:
                _add_stale(stale, claim_id, "source revision changed")
        if visible_source.artifact_path != exact_source.artifact_path:
            for claim_id in dependent_claims:
                _add_stale(stale, claim_id, "source artifact path changed")
        if visible_source.artifact_digest != exact_source.artifact_digest:
            for claim_id in dependent_claims:
                _add_stale(stale, claim_id, "source artifact digest changed")
        if visible_source.reader_digest != exact_source.reader_digest:
            for claim_id in dependent_claims:
                _add_stale(stale, claim_id, "reader digest changed")
        if not exact_source.current:
            for claim_id in dependent_claims:
                _add_stale(stale, claim_id, "source revision is not current")
    binding_map = _load_bindings(bindings)
    evidence_by_id = document.evidence_by_id
    for claim in document.claims:
        if not claim.evidence_ids:
            errors.append(f"claim {claim.claim_id} has no evidence")
            continue
        binding = binding_map.get(claim.claim_id)
        if binding is None:
            errors.append(f"claim {claim.claim_id} is missing hidden evidence binding")
        else:
            if binding.get("claim_id") != claim.claim_id:
                errors.append(f"binding for {claim.claim_id} has the wrong claim identity")
            if subject_markdown is not None and binding.get("subject_markdown") != subject_markdown:
                _add_stale(stale, claim.claim_id, "subject Markdown path changed")
            forbidden = {
                "claim",
                "claim_text",
                "class",
                "epistemic_state",
                "review_state",
                "limitations",
            }
            if forbidden.intersection(binding):
                errors.append(f"binding for {claim.claim_id} duplicates semantic Markdown fields")
            if binding.get("claim_digest") != claim.claim_digest:
                _add_stale(stale, claim.claim_id, "visible claim block changed")
            if binding.get("binding_state") != "current":
                _add_stale(stale, claim.claim_id, "binding state is not current")
            binding_rows = binding.get("evidence", ())
            if not isinstance(binding_rows, list):
                errors.append(f"binding for {claim.claim_id} evidence must be a list")
                binding_rows = []
            bound_ids = tuple(str(row.get("evidence_id", "")) for row in binding_rows if isinstance(row, Mapping))
            if bound_ids != claim.evidence_ids:
                _add_stale(stale, claim.claim_id, "evidence set changed")
        for evidence_id in claim.evidence_ids:
            evidence = evidence_by_id.get(evidence_id)
            if evidence is None:
                errors.append(f"claim {claim.claim_id} references missing evidence {evidence_id}")
                continue
            source = exact.get(evidence.source_key)
            visible_source = next(
                (item for item in document.source_revisions if item.key == evidence.source_key),
                None,
            )
            source_for_check = source or visible_source
            if source_for_check is None:
                errors.append(f"evidence {evidence_id} references an unknown source revision")
                continue
            if evidence.artifact_path != source_for_check.artifact_path:
                _add_stale(stale, claim.claim_id, f"evidence {evidence_id} artifact path changed")
            if evidence.artifact_digest != source_for_check.artifact_digest:
                _add_stale(stale, claim.claim_id, f"evidence {evidence_id} artifact digest changed")
            if evidence.reader_digest != source_for_check.reader_digest:
                _add_stale(stale, claim.claim_id, f"evidence {evidence_id} reader digest changed")
            if evidence.quote_digest != sha256_digest(evidence.quote):
                errors.append(f"evidence {evidence_id} quote digest is incorrect")
            try:
                raw, source_text = _read_source_text(source_for_check, base_dir)
            except AnalysisContractError as exc:
                _add_stale(stale, claim.claim_id, f"evidence {evidence_id} source cannot be read")
                raw = b""
                source_text = ""
            if raw and sha256_digest(raw) != source_for_check.artifact_digest:
                _add_stale(stale, claim.claim_id, f"evidence {evidence_id} source artifact changed")
            if source_text and evidence.quote not in source_text:
                _add_stale(stale, claim.claim_id, f"evidence {evidence_id} quote is no longer exact")
            if binding is not None:
                rows = binding.get("evidence", ())
                row = next(
                    (item for item in rows if isinstance(item, Mapping) and item.get("evidence_id") == evidence_id),
                    None,
                )
                if row is None:
                    _add_stale(stale, claim.claim_id, f"evidence {evidence_id} binding is missing")
                else:
                    expected = {
                        "evidence_digest": evidence.evidence_digest,
                        "source_id": evidence.source_id,
                        "source_revision": evidence.revision,
                        "raw_artifact_path": evidence.artifact_path,
                        "raw_artifact_digest": evidence.artifact_digest,
                        "reader_digest": evidence.reader_digest,
                        "locator": dict(evidence.locator),
                        "exact_quote": evidence.quote,
                        "quote_digest": evidence.quote_digest,
                    }
                    for field, expected_value in expected.items():
                        if row.get(field) != expected_value:
                            _add_stale(stale, claim.claim_id, f"evidence {evidence_id} binding changed")
    return VerificationReport(
        document=document,
        errors=tuple(dict.fromkeys(errors)),
        stale_by_claim={key: tuple(sorted(value)) for key, value in sorted(stale.items())},
    )


def propagate_stale(
    analysis: Union[str, Path],
    sources: Union[Mapping[Any, Any], Iterable[Union[SourceRevision, Mapping[str, Any]]]],
    *,
    bindings: Optional[Union[Mapping[str, Any], Sequence[Mapping[str, Any]], str, Path]] = None,
    base_dir: Optional[Path] = None,
) -> Mapping[str, Tuple[str, ...]]:
    """Return affected claim IDs without rewriting visible Markdown or bindings."""

    return verify_analysis(analysis, sources, bindings=bindings, base_dir=base_dir).stale_by_claim


def _source_json(path: Path) -> list[SourceRevision]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalysisContractError(f"cannot read source descriptor JSON: {exc}") from exc
    if not isinstance(payload, list):
        raise AnalysisContractError("source descriptor JSON must be a list")
    return [SourceRevision.from_mapping(item) for item in payload]


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    prepare = subparsers.add_parser("prepare")
    prepare.add_argument("--output", type=Path, required=True)
    prepare.add_argument("--analysis-id", required=True)
    prepare.add_argument("--subject", required=True)
    prepare.add_argument("--kind", choices=("single-source", "synthesis"), required=True)
    prepare.add_argument("--sources-json", type=Path, required=True)
    prepare.add_argument("--scope", default="")
    prepare.add_argument("--selection-boundary", default="")
    verify = subparsers.add_parser("verify")
    verify.add_argument("--analysis", type=Path, required=True)
    verify.add_argument("--sources-json", type=Path, required=True)
    verify.add_argument("--bindings", type=Path, required=True)
    verify.add_argument("--base-dir", type=Path)
    args = parser.parse_args(argv)
    try:
        sources = _source_json(args.sources_json)
        if args.operation == "prepare":
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                prepare_analysis(
                    analysis_id=args.analysis_id,
                    subject=args.subject,
                    kind=args.kind,
                    sources=sources,
                    scope=args.scope,
                    selection_boundary=args.selection_boundary,
                ),
                encoding="utf-8",
            )
            return 0
        report = verify_analysis(
            args.analysis,
            sources,
            bindings=args.bindings,
            base_dir=args.base_dir,
        )
        print(
            json.dumps(
                {
                    "ok": report.ok,
                    "errors": list(report.errors),
                    "stale_claims": {
                        key: list(value) for key, value in report.stale_by_claim.items()
                    },
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0 if report.ok else 1
    except AnalysisContractError as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
