"""Mechanical review and confirmation owner for Research Vault v2."""

from __future__ import annotations

import argparse
import contextlib
import fcntl
import hashlib
import json
import os
import re
import secrets
import stat
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterator, Mapping, Optional, Sequence

import yaml


BINDING_SCHEMA = "research-analysis/evidence-binding/v2"
CAPTURE_SCHEMA = "research-capture/v2"
RECEIPT_SCHEMA = "research-review/confirmation-receipt/v2"
EVIDENCE_SET_SCHEMA = "research-review/evidence-set/v2"
DECISIONS = frozenset({"confirm", "reject", "defer"})
VISIBLE_STATES = {
    "confirm": "confirmed",
    "reject": "rejected",
    "defer": "deferred",
}
MAX_MARKDOWN_BYTES = 16 * 1024 * 1024
MAX_JSON_BYTES = 8 * 1024 * 1024
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_MESSAGE_CHARS = 16_384
IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z")
DIGEST_RE = re.compile(r"sha256:[0-9a-f]{64}\Z")
HEADING_RE = re.compile(r"^(?P<marks>#{1,6})\s+(?P<title>.+?)\s*$", re.MULTILINE)
FIELD_RE = re.compile(r"^\s*-\s+(?P<label>[A-Za-z][A-Za-z -]*):\s*(?P<value>.*?)\s*\Z")
ROLE_PLACEHOLDERS = frozenset(
    {"me", "myself", "user", "human", "reviewer", "owner", "我", "本人", "用户", "人类"}
)
AI_TOOL_TOKENS = frozenset(
    {
        "ai",
        "assistant",
        "agent",
        "bot",
        "chatbot",
        "llm",
        "tool",
        "model",
        "codex",
        "chatgpt",
        "gpt",
        "openai",
        "anthropic",
        "gemini",
        "bard",
        "llama",
        "mistral",
        "cohere",
        "grok",
        "copilot",
        "qwen",
        "deepseek",
        "kimi",
        "devin",
        "cursor",
        "doubao",
        "tongyi",
    }
)
MODEL_FAMILY_TOKENS = frozenset({"claude", "sonnet", "opus", "haiku", "fable"})
MODEL_VARIANTS = frozenset(
    {"beta", "chat", "instant", "latest", "max", "mini", "preview", "pro", "reasoning", "thinking", "turbo"}
)
LOCALIZED_AI_MARKERS = frozenset(
    {"人工智能", "智能助手", "小助手", "机器人助理", "工具", "模型", "通义千问", "豆包", "文心一言", "讯飞星火", "智谱清言"}
)


class ReviewContractError(ValueError):
    """Raised when a review operation cannot be performed safely."""


class ReviewConflictError(ReviewContractError):
    """Raised when an explicit target changed after it was inspected."""


@dataclass(frozen=True)
class ClaimRecord:
    claim_id: str
    text: str
    claim_class: str
    epistemic_state: str
    review_state: str
    evidence_ids: tuple[str, ...]
    limitations: str

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
    def digest(self) -> str:
        return canonical_digest(self.digest_payload())


@dataclass(frozen=True)
class EvidenceRecord:
    evidence_id: str
    source_id: str
    source_revision: str
    artifact_path: str
    locator: Mapping[str, Any]
    exact_quote: str
    artifact_digest: str
    reader_digest: str
    quote_digest: str

    def digest_payload(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "source_id": self.source_id,
            "revision": self.source_revision,
            "artifact_path": self.artifact_path,
            "locator": dict(self.locator),
            "quote": self.exact_quote,
            "artifact_digest": self.artifact_digest,
            "reader_digest": self.reader_digest,
            "quote_digest": self.quote_digest,
        }

    @property
    def digest(self) -> str:
        return canonical_digest(self.digest_payload())


@dataclass(frozen=True)
class AuditResult:
    outcome: str
    review_id: Optional[str]
    subject_path: str
    claim_id: str
    claim: Optional[ClaimRecord]
    evidence: tuple[EvidenceRecord, ...]
    claim_digest: Optional[str]
    evidence_set_digest: Optional[str]
    binding_digest: Optional[str]
    findings: tuple[str, ...]

    @property
    def confirm_eligible(self) -> bool:
        return self.outcome in {"pass", "pass-with-limitations"} and bool(self.evidence)

    @property
    def decision_eligible(self) -> bool:
        return bool(self.claim and self.claim_digest and self.evidence_set_digest)

    def as_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "subject_path": self.subject_path,
            "claim_id": self.claim_id,
            "claim_digest": self.claim_digest,
            "evidence_set_digest": self.evidence_set_digest,
            "binding_digest": self.binding_digest,
            "evidence_ids": [item.evidence_id for item in self.evidence],
            "findings": list(self.findings),
            "confirm_eligible": self.confirm_eligible,
            "decision_eligible": self.decision_eligible,
        }


@dataclass(frozen=True)
class Authorization:
    review_id: str
    claim_id: str
    decision: str
    actor_declaration: str
    authorization_digest: str
    interaction_ref: Optional[str]


@dataclass(frozen=True)
class DecisionResult:
    decision: str
    visible_status: str
    review_path: str
    receipt_path: str
    receipt_id: str
    targets: tuple[str, ...]


@dataclass(frozen=True)
class ReceiptValidation:
    valid: bool
    state: str
    reasons: tuple[str, ...]


def sha256_digest(value: str | bytes) -> str:
    payload = value.encode("utf-8") if isinstance(value, str) else value
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def canonical_digest(value: Any) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_digest(encoded)


def _identifier(value: Any, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value) or value in {".", ".."}:
        raise ReviewContractError(f"{label} must be a safe stable identifier")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise ReviewContractError(f"{label} must be a SHA-256 digest")
    normalized = value.strip().lower()
    if not normalized.startswith("sha256:") and re.fullmatch(r"[0-9a-f]{64}", normalized):
        normalized = "sha256:" + normalized
    if not DIGEST_RE.fullmatch(normalized):
        raise ReviewContractError(f"{label} must be a SHA-256 digest")
    return normalized


def _safe_relative_path(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value or "\\" in value or value.startswith("/"):
        raise ReviewContractError(f"{label} must be a vault-relative POSIX path")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise ReviewContractError(f"{label} must stay within the vault")
    return path.as_posix()


def _path_parts(value: str, label: str) -> tuple[str, ...]:
    return tuple(PurePosixPath(_safe_relative_path(value, label)).parts)


def _root_fd(workspace: Path) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        return os.open(os.fspath(workspace), flags)
    except OSError as exc:
        raise ReviewContractError(f"workspace root is not a safe directory: {exc}") from exc


def _open_directory(parent_fd: int, name: str, *, create: bool) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        return os.open(name, flags, dir_fd=parent_fd)
    except FileNotFoundError:
        if not create:
            raise
        os.mkdir(name, mode=0o755, dir_fd=parent_fd)
        return os.open(name, flags, dir_fd=parent_fd)


@contextlib.contextmanager
def _parent_directory(workspace: Path, relative: str, *, create: bool = False) -> Iterator[tuple[int, str]]:
    parts = _path_parts(relative, "target path")
    root = _root_fd(workspace)
    current = root
    opened: list[int] = []
    try:
        for part in parts[:-1]:
            try:
                next_fd = _open_directory(current, part, create=create)
            except OSError as exc:
                raise ReviewContractError(f"unsafe or missing path component {part!r}: {exc}") from exc
            opened.append(next_fd)
            current = next_fd
        yield current, parts[-1]
    finally:
        for fd in reversed(opened):
            os.close(fd)
        os.close(root)


def _read_child(parent_fd: int, name: str, max_bytes: int, label: str) -> bytes:
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        fd = os.open(name, flags, dir_fd=parent_fd)
    except OSError as exc:
        raise ReviewContractError(f"cannot read {label}: {exc}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise ReviewContractError(f"{label} must be a regular file")
        if info.st_size > max_bytes:
            raise ReviewContractError(f"{label} exceeds the byte limit")
        chunks: list[bytes] = []
        remaining = max_bytes + 1
        while remaining:
            chunk = os.read(fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > max_bytes:
            raise ReviewContractError(f"{label} exceeds the byte limit")
        return payload
    finally:
        os.close(fd)


def read_workspace_bytes(workspace: Path, relative: str, *, max_bytes: int, label: str) -> bytes:
    with _parent_directory(workspace, relative) as (parent_fd, name):
        return _read_child(parent_fd, name, max_bytes, label)


def _read_text(workspace: Path, relative: str, *, max_bytes: int, label: str) -> str:
    payload = read_workspace_bytes(workspace, relative, max_bytes=max_bytes, label=label)
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ReviewContractError(f"{label} must be UTF-8 text") from exc


def _read_json(workspace: Path, relative: str, *, label: str) -> Mapping[str, Any]:
    text = _read_text(workspace, relative, max_bytes=MAX_JSON_BYTES, label=label)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ReviewContractError(f"{label} must be valid JSON") from exc
    if not isinstance(value, Mapping):
        raise ReviewContractError(f"{label} must be a JSON object")
    return value


def _optional_bytes(workspace: Path, relative: str, *, max_bytes: int, label: str) -> Optional[bytes]:
    try:
        return read_workspace_bytes(workspace, relative, max_bytes=max_bytes, label=label)
    except ReviewContractError as exc:
        if "No such file or directory" in str(exc):
            return None
        raise


def _current_child(parent_fd: int, name: str, max_bytes: int) -> Optional[bytes]:
    try:
        return _read_child(parent_fd, name, max_bytes, "atomic target")
    except ReviewContractError as exc:
        if "No such file or directory" in str(exc):
            return None
        raise


def _atomic_write(
    workspace: Path,
    relative: str,
    payload: bytes,
    *,
    expected_digest: Optional[str],
    max_existing_bytes: int,
    mode: int,
) -> None:
    with _parent_directory(workspace, relative, create=True) as (parent_fd, name):
        current = _current_child(parent_fd, name, max_existing_bytes)
        if expected_digest is None:
            if current is not None:
                raise ReviewConflictError(f"atomic target already exists: {relative}")
        elif current is None or sha256_digest(current) != expected_digest:
            raise ReviewConflictError(f"atomic target changed: {relative}")
        temporary = f".{name}.tmp-{secrets.token_hex(8)}"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(temporary, flags, mode, dir_fd=parent_fd)
        try:
            view = memoryview(payload)
            while view:
                written = os.write(fd, view)
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)
        try:
            os.replace(temporary, name, src_dir_fd=parent_fd, dst_dir_fd=parent_fd)
            os.fsync(parent_fd)
        except BaseException:
            try:
                os.unlink(temporary, dir_fd=parent_fd)
            except OSError:
                pass
            raise


@contextlib.contextmanager
def _review_lock(workspace: Path, review_id: str, claim_id: str) -> Iterator[str]:
    lock_path = f".research/locks/review-{_identifier(review_id, 'review_id')}-{_identifier(claim_id, 'claim_id')}.lock"
    with _parent_directory(workspace, lock_path, create=True) as (parent_fd, name):
        flags = os.O_RDWR | os.O_CREAT
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode):
                raise ReviewContractError("review lock must be a regular file")
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield lock_path
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def _split_frontmatter(markdown: str, label: str) -> tuple[dict[str, Any], str]:
    if not markdown.startswith("---\n"):
        raise ReviewContractError(f"{label} must start with YAML frontmatter")
    closing = markdown.find("\n---\n", 4)
    if closing < 0:
        raise ReviewContractError(f"{label} frontmatter is not closed")
    try:
        payload = yaml.safe_load(markdown[4:closing])
    except yaml.YAMLError as exc:
        raise ReviewContractError(f"{label} frontmatter is invalid") from exc
    if not isinstance(payload, dict):
        raise ReviewContractError(f"{label} frontmatter must be a mapping")
    return payload, markdown[closing + 5 :]


def _frontmatter(payload: Mapping[str, Any]) -> str:
    rendered = yaml.safe_dump(
        dict(payload),
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
        width=120,
    ).rstrip()
    return f"---\n{rendered}\n---\n"


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
    return re.sub(rf"^{re.escape(prefix)}\s+", "", title, flags=re.IGNORECASE).strip()


def _clean_value(value: str) -> str:
    value = value.strip()
    if value.startswith("`") and value.endswith("`") and len(value) >= 2:
        value = value[1:-1]
    return value.strip()


def _fields(body: str, label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in body.splitlines():
        match = FIELD_RE.match(line)
        if not match:
            continue
        key = re.sub(r"\s+", " ", match.group("label").strip().lower())
        if key in result:
            raise ReviewContractError(f"{label} contains duplicate field {key!r}")
        result[key] = _clean_value(match.group("value"))
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


def _parse_evidence_ids(raw: str) -> tuple[str, ...]:
    values = re.findall(r"`([^`]+)`", raw)
    if not values:
        values = [item.strip() for item in raw.split(",") if item.strip()]
    return tuple(_identifier(item, "evidence_id") for item in values)


def _parse_locator(raw: str) -> Mapping[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ReviewContractError("evidence locator must be visible JSON") from exc
    if not isinstance(value, Mapping) or not isinstance(value.get("kind"), str):
        raise ReviewContractError("evidence locator must be a typed mapping")
    return dict(value)


def _parse_subject(markdown: str, claim_id: str) -> tuple[ClaimRecord, tuple[EvidenceRecord, ...], str]:
    frontmatter, body = _split_frontmatter(markdown, "subject Markdown")
    analysis_id = _identifier(frontmatter.get("analysis_id", ""), "analysis_id")
    sections = _heading_sections(body)
    claim_sections: dict[str, str] = {}
    evidence_sections: dict[str, str] = {}
    for level, title, section_body in sections:
        if level != 3:
            continue
        if title.casefold().startswith("claim "):
            item_id = _identifier(_heading_id(title, "claim"), "claim_id")
            if item_id in claim_sections:
                raise ReviewContractError(f"duplicate claim ID: {item_id}")
            claim_sections[item_id] = section_body
        if title.casefold().startswith("evidence "):
            item_id = _identifier(_heading_id(title, "evidence"), "evidence_id")
            if item_id in evidence_sections:
                raise ReviewContractError(f"duplicate evidence ID: {item_id}")
            evidence_sections[item_id] = section_body
    if claim_id not in claim_sections:
        raise ReviewContractError(f"subject has no unique claim {claim_id}")
    fields = _fields(claim_sections[claim_id], f"claim {claim_id}")
    evidence_ids = _parse_evidence_ids(fields.get("evidence", ""))
    if len(set(evidence_ids)) != len(evidence_ids):
        raise ReviewContractError("claim evidence IDs must be unique")
    claim = ClaimRecord(
        claim_id=claim_id,
        text=fields.get("claim", "").strip(),
        claim_class=fields.get("class", "").strip(),
        epistemic_state=fields.get("epistemic state", "").strip(),
        review_state=fields.get("review state", "").strip(),
        evidence_ids=evidence_ids,
        limitations=fields.get("limitations", "").strip(),
    )
    if not claim.text or not claim.claim_class or not claim.epistemic_state or not claim.review_state:
        raise ReviewContractError(f"claim {claim_id} is not structurally substantive")
    evidence: list[EvidenceRecord] = []
    for evidence_id in evidence_ids:
        body = evidence_sections.get(evidence_id)
        if body is None:
            raise ReviewContractError(f"claim {claim_id} references missing evidence {evidence_id}")
        item_fields = _fields(body, f"evidence {evidence_id}")
        quote = _quote_block(body)
        if not quote:
            raise ReviewContractError(f"evidence {evidence_id} has no exact quote")
        evidence.append(
            EvidenceRecord(
                evidence_id=evidence_id,
                source_id=_identifier(item_fields.get("source", ""), "source_id"),
                source_revision=_identifier(item_fields.get("revision", ""), "source_revision"),
                artifact_path=_safe_relative_path(item_fields.get("artifact", ""), "artifact path"),
                locator=_parse_locator(item_fields.get("locator", "")),
                exact_quote=quote,
                artifact_digest=_digest(item_fields.get("artifact digest", ""), "artifact digest"),
                reader_digest=_digest(item_fields.get("reader digest", ""), "reader digest"),
                quote_digest=_digest(item_fields.get("quote digest", ""), "quote digest"),
            )
        )
    return claim, tuple(evidence), analysis_id


def _verify_raw_record(workspace: Path, raw: Mapping[str, Any]) -> tuple[str, list[str]]:
    findings: list[str] = []
    expected = raw.get("sha256")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        return "", ["source manifest raw digest is invalid"]
    entries = raw.get("entries")
    if isinstance(entries, list):
        digest_parts: list[bytes] = []
        for entry in sorted(entries, key=lambda item: str(item.get("path", "")) if isinstance(item, Mapping) else ""):
            if not isinstance(entry, Mapping):
                findings.append("source manifest raw entry is invalid")
                continue
            path = _safe_relative_path(entry.get("raw_path", ""), "raw source path")
            payload = read_workspace_bytes(workspace, path, max_bytes=MAX_SOURCE_BYTES, label="raw source member")
            actual = hashlib.sha256(payload).hexdigest()
            if actual != entry.get("sha256") or len(payload) != entry.get("bytes"):
                findings.append(f"raw source member changed: {entry.get('path', path)}")
            digest_parts.append(
                (
                    json.dumps(
                        {"path": entry.get("path"), "sha256": actual, "bytes": len(payload)},
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n"
                ).encode("utf-8")
            )
        actual_digest = hashlib.sha256(b"".join(digest_parts)).hexdigest()
    else:
        path = _safe_relative_path(raw.get("path", ""), "raw source path")
        payload = read_workspace_bytes(workspace, path, max_bytes=MAX_SOURCE_BYTES, label="raw source")
        actual_digest = hashlib.sha256(payload).hexdigest()
        if isinstance(raw.get("bytes"), int) and len(payload) != raw["bytes"]:
            findings.append("raw source byte count changed")
    if actual_digest != expected:
        findings.append("raw source digest changed")
    return "sha256:" + actual_digest, findings


def _source_facts(workspace: Path, evidence: EvidenceRecord) -> tuple[dict[str, Any], list[str], list[str]]:
    invalid: list[str] = []
    stale: list[str] = []
    facts: dict[str, Any] = {
        "source_id": evidence.source_id,
        "source_revision": evidence.source_revision,
        "artifact_digest": None,
        "reader_digest": None,
        "raw_source_digest": None,
        "source_map_digest": None,
        "currency": "unknown",
    }
    artifact = read_workspace_bytes(
        workspace,
        evidence.artifact_path,
        max_bytes=MAX_SOURCE_BYTES,
        label=f"artifact for {evidence.evidence_id}",
    )
    artifact_digest = sha256_digest(artifact)
    facts["artifact_digest"] = artifact_digest
    if artifact_digest != evidence.artifact_digest:
        invalid.append(f"{evidence.evidence_id}: artifact digest changed")
    try:
        artifact_text = artifact.decode("utf-8")
    except UnicodeDecodeError:
        artifact_text = ""
        invalid.append(f"{evidence.evidence_id}: artifact is not UTF-8 evidence text")
    if evidence.exact_quote not in artifact_text:
        invalid.append(f"{evidence.evidence_id}: exact quote is absent from artifact")
    if sha256_digest(evidence.exact_quote) != evidence.quote_digest:
        invalid.append(f"{evidence.evidence_id}: quote digest changed")

    reader_path = f"Sources/{evidence.source_id}/reader.md"
    reader = read_workspace_bytes(workspace, reader_path, max_bytes=MAX_SOURCE_BYTES, label="source reader")
    reader_digest = sha256_digest(reader)
    facts["reader_digest"] = reader_digest
    if reader_digest != evidence.reader_digest:
        invalid.append(f"{evidence.evidence_id}: reader digest changed")
    try:
        reader_text = reader.decode("utf-8")
    except UnicodeDecodeError:
        reader_text = ""
        invalid.append(f"{evidence.evidence_id}: reader is not UTF-8 text")
    if evidence.exact_quote not in reader_text:
        invalid.append(f"{evidence.evidence_id}: exact quote is absent from reader")

    manifest_path = f"Sources/{evidence.source_id}/.source/manifest.json"
    manifest = _read_json(workspace, manifest_path, label="source manifest")
    if manifest.get("schema") != CAPTURE_SCHEMA or manifest.get("source_id") != evidence.source_id:
        invalid.append(f"{evidence.evidence_id}: source manifest identity is invalid")
    current_revision = manifest.get("current_revision_id")
    facts["current_revision"] = current_revision
    if current_revision != evidence.source_revision:
        stale.append(f"{evidence.evidence_id}: source revision is no longer current")
    revisions = [
        item
        for item in manifest.get("revisions", ())
        if isinstance(item, Mapping) and item.get("revision_id") == evidence.source_revision
    ]
    if len(revisions) != 1:
        invalid.append(f"{evidence.evidence_id}: bound source revision is missing or ambiguous")
        return facts, invalid, stale
    revision = revisions[0]
    facts["currency"] = revision.get("currency")
    if revision.get("currency") != "current":
        stale.append(f"{evidence.evidence_id}: bound source currency is not current")
    raw = revision.get("raw")
    if not isinstance(raw, Mapping):
        invalid.append(f"{evidence.evidence_id}: source revision has no raw record")
    else:
        try:
            raw_digest, raw_findings = _verify_raw_record(workspace, raw)
            facts["raw_source_digest"] = raw_digest
            invalid.extend(f"{evidence.evidence_id}: {item}" for item in raw_findings)
        except ReviewContractError as exc:
            invalid.append(f"{evidence.evidence_id}: {exc}")
    processing = revision.get("processing")
    if not isinstance(processing, Mapping):
        invalid.append(f"{evidence.evidence_id}: source processing record is missing")
        return facts, invalid, stale
    if processing.get("reader_path") != reader_path:
        invalid.append(f"{evidence.evidence_id}: source manifest reader path changed")
    if processing.get("reader_sha256") not in {evidence.reader_digest.removeprefix("sha256:"), evidence.reader_digest}:
        invalid.append(f"{evidence.evidence_id}: source manifest reader digest changed")
    current_reader = manifest.get("current_reader_sha256")
    if current_reader not in {None, evidence.reader_digest.removeprefix("sha256:"), evidence.reader_digest}:
        stale.append(f"{evidence.evidence_id}: current reader digest changed")
    allowed_artifacts = {
        value
        for value in (
            processing.get("normalized_path"),
            processing.get("reader_path"),
            raw.get("path") if isinstance(raw, Mapping) else None,
        )
        if isinstance(value, str)
    }
    if evidence.artifact_path not in allowed_artifacts:
        invalid.append(f"{evidence.evidence_id}: artifact path is not owned by the bound revision")
    source_map_path = processing.get("source_map_path")
    if isinstance(source_map_path, str) and source_map_path:
        source_map = read_workspace_bytes(
            workspace,
            _safe_relative_path(source_map_path, "source map path"),
            max_bytes=MAX_JSON_BYTES,
            label="source map",
        )
        source_map_digest = sha256_digest(source_map)
        facts["source_map_digest"] = source_map_digest
        expected_map = processing.get("source_map_sha256")
        if expected_map not in {source_map_digest, source_map_digest.removeprefix("sha256:")}:
            invalid.append(f"{evidence.evidence_id}: source map digest changed")
    return facts, invalid, stale


def audit_claim(
    workspace: Path,
    *,
    subject_path: str,
    binding_path: str,
    claim_id: str,
    review_id: Optional[str] = None,
) -> AuditResult:
    subject_path = _safe_relative_path(subject_path, "subject path")
    binding_path = _safe_relative_path(binding_path, "binding path")
    claim_id = _identifier(claim_id, "claim_id")
    if review_id is not None:
        review_id = _identifier(review_id, "review_id")
    try:
        subject_text = _read_text(
            workspace,
            subject_path,
            max_bytes=MAX_MARKDOWN_BYTES,
            label="subject Markdown",
        )
        claim, evidence, _analysis_id = _parse_subject(subject_text, claim_id)
        binding = _read_json(workspace, binding_path, label="analysis evidence binding")
    except ReviewContractError as exc:
        return AuditResult(
            "blocked",
            review_id,
            subject_path,
            claim_id,
            None,
            (),
            None,
            None,
            None,
            (str(exc),),
        )

    invalid: list[str] = []
    stale: list[str] = []
    binding_digest: Optional[str] = None
    if binding.get("schema") != BINDING_SCHEMA:
        invalid.append("binding schema is not research-analysis/evidence-binding/v2")
    if binding.get("subject_markdown") != subject_path:
        stale.append("binding subject Markdown path changed")
    if binding.get("claim_id") != claim_id:
        invalid.append("binding claim identity changed")
    if binding.get("claim_digest") != claim.digest:
        stale.append("visible claim block changed")
    if binding.get("binding_state") != "current":
        stale.append("analysis binding is not current")
    supplied_binding_digest = binding.get("binding_digest")
    if isinstance(supplied_binding_digest, str):
        try:
            binding_digest = _digest(supplied_binding_digest, "binding digest")
        except ReviewContractError as exc:
            invalid.append(str(exc))
    unsigned_binding = dict(binding)
    unsigned_binding.pop("binding_digest", None)
    expected_binding_digest = canonical_digest(unsigned_binding)
    if binding_digest != expected_binding_digest:
        invalid.append("analysis binding digest changed")

    rows = binding.get("evidence")
    if not isinstance(rows, list):
        rows = []
        invalid.append("binding evidence must be a list")
    bound_ids = [str(row.get("evidence_id", "")) for row in rows if isinstance(row, Mapping)]
    if bound_ids != list(claim.evidence_ids) or len(rows) != len(claim.evidence_ids):
        stale.append("complete evidence membership changed")
    row_by_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            invalid.append("binding evidence row is not an object")
            continue
        row_id = str(row.get("evidence_id", ""))
        if row_id in row_by_id:
            invalid.append(f"duplicate binding evidence row: {row_id}")
        row_by_id[row_id] = row

    evidence_items: list[dict[str, Any]] = []
    for item in evidence:
        row = row_by_id.get(item.evidence_id)
        expected_row = {
            "evidence_id": item.evidence_id,
            "evidence_digest": item.digest,
            "source_id": item.source_id,
            "source_revision": item.source_revision,
            "raw_artifact_path": item.artifact_path,
            "raw_artifact_digest": item.artifact_digest,
            "reader_digest": item.reader_digest,
            "locator": dict(item.locator),
            "exact_quote": item.exact_quote,
            "quote_digest": item.quote_digest,
        }
        if row is None:
            stale.append(f"{item.evidence_id}: binding row is missing")
            row_payload: Mapping[str, Any] = {}
        else:
            row_payload = dict(row)
            if row_payload != expected_row:
                stale.append(f"{item.evidence_id}: visible evidence and binding disagree")
        try:
            source_facts, source_invalid, source_stale = _source_facts(workspace, item)
            invalid.extend(source_invalid)
            stale.extend(source_stale)
        except ReviewContractError as exc:
            source_facts = {"state": "unreadable"}
            invalid.append(f"{item.evidence_id}: {exc}")
        evidence_items.append(
            {
                "evidence_id": item.evidence_id,
                "visible_evidence_digest": item.digest,
                "binding": row_payload,
                "source": source_facts,
            }
        )

    evidence_set_digest = canonical_digest(
        {
            "schema": EVIDENCE_SET_SCHEMA,
            "claim_id": claim_id,
            "binding_digest": binding_digest,
            "items": sorted(evidence_items, key=lambda row: row["evidence_id"]),
        }
    )
    findings = tuple(dict.fromkeys(invalid + stale))
    if invalid:
        outcome = "invalid"
    elif stale:
        outcome = "stale"
    elif claim.limitations:
        outcome = "pass-with-limitations"
    else:
        outcome = "pass"
    return AuditResult(
        outcome,
        review_id,
        subject_path,
        claim_id,
        claim,
        evidence,
        claim.digest,
        evidence_set_digest,
        binding_digest,
        findings,
    )


def _markdown_code(value: str) -> str:
    return value.replace("`", "\\`").replace("\r", "")


def _markdown_text(value: str) -> str:
    return " ".join(value.replace("`", "'").split())


def render_review_packet(audit: AuditResult, *, review_id: str) -> str:
    review_id = _identifier(review_id, "review_id")
    if not audit.claim or not audit.claim_digest or not audit.evidence_set_digest:
        raise ReviewContractError("blocked audit cannot produce a review packet")
    status = "awaiting-decision" if audit.confirm_eligible else audit.outcome
    frontmatter = _frontmatter({"id": review_id, "kind": "review", "status": status})
    lines = [
        frontmatter,
        f"\n# Review: {_markdown_text(audit.claim.text)}\n\n",
        "## Subject\n\n",
        f"- Subject path: `{_markdown_code(audit.subject_path)}`\n",
        f"- Claim ID: `{audit.claim_id}`\n",
        f"- Class: `{_markdown_code(audit.claim.claim_class)}`\n",
        f"- Epistemic state: `{_markdown_code(audit.claim.epistemic_state)}`\n\n",
        "## Claim under review\n\n",
        audit.claim.text + "\n\n",
    ]
    if audit.claim.limitations:
        lines.extend(("### Limitations\n\n", audit.claim.limitations + "\n\n"))
    lines.append("## Evidence under review\n\n")
    for item in audit.evidence:
        quote = "\n".join(f"> {line}" if line else ">" for line in item.exact_quote.split("\n"))
        locator = json.dumps(dict(item.locator), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        lines.extend(
            (
                f"### Evidence `{item.evidence_id}`\n\n",
                quote + "\n\n",
                f"- Source ID: `{item.source_id}`\n",
                f"- Source revision: `{item.source_revision}`\n",
                f"- Artifact: `{_markdown_code(item.artifact_path)}`\n",
                f"- Locator: `{_markdown_code(locator)}`\n\n",
            )
        )
    lines.extend(
        (
            "## Audit\n\n",
            f"- Outcome: `{audit.outcome}`\n",
            f"- Claim digest: `{audit.claim_digest}`\n",
            f"- Evidence-set digest: `{audit.evidence_set_digest}`\n",
        )
    )
    if audit.findings:
        lines.append("- Findings:\n")
        lines.extend(f"  - {_markdown_text(item)}\n" for item in audit.findings)
    else:
        lines.append("- Findings: none\n")
    lines.extend(
        (
            "\n## Requested decision\n\n",
            "Confirm, reject, or defer this claim.\n\n",
            "## Current decision\n\n",
            "Awaiting an explicit decision in the current user message.\n",
        )
    )
    return "".join(lines)


def write_review_packet(
    workspace: Path,
    *,
    subject_path: str,
    binding_path: str,
    review_path: str,
    review_id: str,
    claim_id: str,
    expected_review_digest: Optional[str] = None,
) -> AuditResult:
    review_path = _safe_relative_path(review_path, "review path")
    audit = audit_claim(
        workspace,
        subject_path=subject_path,
        binding_path=binding_path,
        claim_id=claim_id,
        review_id=review_id,
    )
    packet = render_review_packet(audit, review_id=review_id).encode("utf-8")
    with _review_lock(workspace, review_id, claim_id):
        if expected_review_digest is not None:
            expected_review_digest = _digest(expected_review_digest, "expected review digest")
        _atomic_write(
            workspace,
            review_path,
            packet,
            expected_digest=expected_review_digest,
            max_existing_bytes=MAX_MARKDOWN_BYTES,
            mode=0o644,
        )
    return audit


def actor_is_allowed(actor: str) -> bool:
    normalized = " ".join(unicodedata.normalize("NFKC", str(actor or "")).strip().casefold().split())
    if not normalized or normalized in ROLE_PLACEHOLDERS or len(normalized) > 200:
        return False
    if any(marker in normalized for marker in LOCALIZED_AI_MARKERS):
        return False
    tokens = re.findall(r"[a-z0-9]+", normalized)
    token_set = set(tokens)
    if token_set & AI_TOOL_TOKENS:
        return False
    model_tokens = token_set & MODEL_FAMILY_TOKENS
    if not model_tokens:
        return bool(normalized)
    possible_human_name_tokens = {
        token
        for token in token_set
        if token not in MODEL_FAMILY_TOKENS
        and token not in MODEL_VARIANTS
        and re.fullmatch(r"v?\d+(?:\.\d+)*", token) is None
    }
    return bool(possible_human_name_tokens)


def _message_field(message: str, labels: Sequence[str], field_name: str) -> str:
    label_pattern = "|".join(re.escape(label) for label in labels)
    matches = re.findall(rf"^\s*(?:{label_pattern})\s*[:：]\s*(.+?)\s*$", message, flags=re.MULTILINE | re.IGNORECASE)
    if len(matches) != 1:
        raise ReviewContractError(f"current user message must contain exactly one {field_name} field")
    return matches[0].strip()


def parse_current_user_authorization(
    message: str,
    *,
    trusted_role: str,
    message_origin: str,
    is_current: bool,
    expected_review_id: str,
    expected_claim_id: str,
    interaction_ref: Optional[str] = None,
) -> Authorization:
    if trusted_role != "user" or message_origin != "current_user_message" or not is_current:
        raise ReviewContractError("authorization must be the trusted current user message")
    if not isinstance(message, str) or not message.strip() or len(message) > MAX_MESSAGE_CHARS:
        raise ReviewContractError("current user message is empty or exceeds the character limit")
    review_id = _identifier(_message_field(message, ("Review", "Review ID", "审查", "审查 ID"), "review"), "review_id")
    claim_id = _identifier(_message_field(message, ("Claim", "Claim ID", "主张", "主张 ID"), "claim"), "claim_id")
    decision_raw = _message_field(message, ("Decision", "决定"), "decision").casefold()
    decision_aliases = {
        "confirm": "confirm",
        "confirmed": "confirm",
        "确认": "confirm",
        "reject": "reject",
        "rejected": "reject",
        "拒绝": "reject",
        "defer": "defer",
        "deferred": "defer",
        "暂缓": "defer",
    }
    decision = decision_aliases.get(decision_raw)
    if decision is None:
        raise ReviewContractError("current user message must choose exactly one supported decision")
    mentioned: set[str] = set()
    folded = unicodedata.normalize("NFKC", message).casefold()
    for token, normalized in decision_aliases.items():
        if re.search(rf"(?<![a-z]){re.escape(token)}(?![a-z])", folded):
            mentioned.add(normalized)
    if mentioned != {decision}:
        raise ReviewContractError("current user message contains an ambiguous decision")
    actor = _message_field(message, ("Signer", "Signed by", "签署人", "签名"), "signer")
    if not actor_is_allowed(actor):
        raise ReviewContractError("signer declaration is an AI/tool/model identity or placeholder")
    if review_id != _identifier(expected_review_id, "expected_review_id"):
        raise ReviewContractError("current user message names a different review")
    if claim_id != _identifier(expected_claim_id, "expected_claim_id"):
        raise ReviewContractError("current user message names a different claim")
    if interaction_ref is not None:
        interaction_ref = _identifier(interaction_ref, "interaction_ref")
    authorization_digest = canonical_digest(
        {
            "schema": "research-review/current-user-authorization/v1",
            "message": unicodedata.normalize("NFKC", message),
            "role": trusted_role,
            "origin": message_origin,
            "review_id": review_id,
            "claim_id": claim_id,
            "decision": decision,
            "actor_declaration": actor,
            "interaction_ref": interaction_ref,
        }
    )
    return Authorization(review_id, claim_id, decision, actor, authorization_digest, interaction_ref)


def _review_identity(review_markdown: str) -> tuple[dict[str, Any], dict[str, str]]:
    frontmatter, body = _split_frontmatter(review_markdown, "review packet")
    sections = _heading_sections(body)
    subject_sections = [section_body for level, title, section_body in sections if level == 2 and title.casefold() == "subject"]
    audit_sections = [section_body for level, title, section_body in sections if level == 2 and title.casefold() == "audit"]
    if len(subject_sections) != 1 or len(audit_sections) != 1:
        raise ReviewContractError("review packet subject or audit section is ambiguous")
    fields = _fields(subject_sections[0], "review subject")
    fields.update(_fields(audit_sections[0], "review audit"))
    return frontmatter, fields


def _decision_markdown(review_markdown: str, authorization: Authorization, receipt_id: str) -> str:
    frontmatter, body = _split_frontmatter(review_markdown, "review packet")
    frontmatter["status"] = VISIBLE_STATES[authorization.decision]
    section_match = re.search(r"^## Current decision\s*$", body, flags=re.MULTILINE)
    if section_match is None:
        raise ReviewContractError("review packet has no unique current decision section")
    if re.search(r"^## Current decision\s*$", body[section_match.end() :], flags=re.MULTILINE):
        raise ReviewContractError("review packet current decision section is ambiguous")
    next_section = re.search(r"^##\s+", body[section_match.end() :], flags=re.MULTILINE)
    end = len(body) if next_section is None else section_match.end() + next_section.start()
    verb = {"confirm": "Confirmed", "reject": "Rejected", "defer": "Deferred"}[authorization.decision]
    replacement = (
        "## Current decision\n\n"
        f"{verb} by {_markdown_text(authorization.actor_declaration)} from the current user message.\n\n"
        f"- Receipt ID: `{receipt_id}`\n"
        f"- Authorization digest: `{authorization.authorization_digest}`\n"
    )
    return _frontmatter(frontmatter) + body[: section_match.start()] + replacement + body[end:]


def _receipt_id(authorization: Authorization) -> str:
    suffix = authorization.authorization_digest.removeprefix("sha256:")[:20]
    return f"receipt-{authorization.review_id}-{authorization.claim_id}-{suffix}"


def _receipt_path(receipt_id: str) -> str:
    return f".research/receipts/{_identifier(receipt_id, 'receipt_id')}.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def apply_decision(
    workspace: Path,
    *,
    subject_path: str,
    binding_path: str,
    review_path: str,
    review_id: str,
    claim_id: str,
    current_user_message: str,
    trusted_role: str,
    message_origin: str,
    is_current_message: bool,
    interaction_ref: Optional[str] = None,
    issued_at: Optional[str] = None,
) -> DecisionResult:
    review_path = _safe_relative_path(review_path, "review path")
    authorization = parse_current_user_authorization(
        current_user_message,
        trusted_role=trusted_role,
        message_origin=message_origin,
        is_current=is_current_message,
        expected_review_id=review_id,
        expected_claim_id=claim_id,
        interaction_ref=interaction_ref,
    )
    receipt_id = _receipt_id(authorization)
    receipt_path = _receipt_path(receipt_id)
    with _review_lock(workspace, review_id, claim_id) as lock_path:
        audit = audit_claim(
            workspace,
            subject_path=subject_path,
            binding_path=binding_path,
            claim_id=claim_id,
            review_id=review_id,
        )
        if not audit.decision_eligible:
            raise ReviewContractError("current claim/evidence set cannot be bound to a decision")
        if authorization.decision == "confirm" and not audit.confirm_eligible:
            raise ReviewContractError("confirm requires a current, integrity-verified evidence set")
        review_bytes = read_workspace_bytes(
            workspace,
            review_path,
            max_bytes=MAX_MARKDOWN_BYTES,
            label="review packet",
        )
        review_text = review_bytes.decode("utf-8")
        frontmatter, fields = _review_identity(review_text)
        if frontmatter.get("id") != review_id or frontmatter.get("kind") != "review":
            raise ReviewContractError("review packet identity changed")
        if frontmatter.get("status") not in {"awaiting-decision", "pass", "pass-with-limitations", "stale", "invalid"}:
            raise ReviewContractError("review packet already contains a decision; replay rejected")
        expected_fields = {
            "subject path": subject_path,
            "claim id": claim_id,
            "claim digest": audit.claim_digest,
            "evidence-set digest": audit.evidence_set_digest,
        }
        for field, expected in expected_fields.items():
            if fields.get(field) != expected:
                raise ReviewContractError(f"review packet {field} is stale")
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "receipt_id": receipt_id,
            "review_id": review_id,
            "subject": {"path": subject_path, "claim_id": claim_id},
            "claim_digest": audit.claim_digest,
            "evidence_set_digest": audit.evidence_set_digest,
            "decision": authorization.decision,
            "actor_declaration": authorization.actor_declaration,
            "authorization_source": "current_user_message",
            "authorization_digest": authorization.authorization_digest,
            "interaction_ref": authorization.interaction_ref,
            "audit_outcome": audit.outcome,
            "issued_at": issued_at or _utc_now(),
        }
        receipt_bytes = (json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
        decided_review = _decision_markdown(review_text, authorization, receipt_id).encode("utf-8")
        existing_receipt = _optional_bytes(
            workspace,
            receipt_path,
            max_bytes=MAX_JSON_BYTES,
            label="confirmation receipt",
        )
        if existing_receipt is not None:
            if existing_receipt != receipt_bytes:
                raise ReviewConflictError("deterministic receipt target already contains different bytes")
            raise ReviewContractError("current user message was already consumed; replay rejected")
        _atomic_write(
            workspace,
            receipt_path,
            receipt_bytes,
            expected_digest=None,
            max_existing_bytes=MAX_JSON_BYTES,
            mode=0o600,
        )
        try:
            _atomic_write(
                workspace,
                review_path,
                decided_review,
                expected_digest=sha256_digest(review_bytes),
                max_existing_bytes=MAX_MARKDOWN_BYTES,
                mode=0o644,
            )
        except BaseException:
            with _parent_directory(workspace, receipt_path) as (parent_fd, name):
                try:
                    current = _read_child(parent_fd, name, MAX_JSON_BYTES, "confirmation receipt")
                    if current == receipt_bytes:
                        os.unlink(name, dir_fd=parent_fd)
                        os.fsync(parent_fd)
                except OSError:
                    pass
            raise
    return DecisionResult(
        authorization.decision,
        VISIBLE_STATES[authorization.decision],
        review_path,
        receipt_path,
        receipt_id,
        (review_path, receipt_path, lock_path),
    )


def validate_receipt(
    workspace: Path,
    *,
    subject_path: str,
    binding_path: str,
    review_path: str,
    receipt_path: str,
    review_id: str,
    claim_id: str,
) -> ReceiptValidation:
    reasons: list[str] = []
    audit = audit_claim(
        workspace,
        subject_path=subject_path,
        binding_path=binding_path,
        claim_id=claim_id,
        review_id=review_id,
    )
    if audit.outcome not in {"pass", "pass-with-limitations"}:
        reasons.append(f"current audit is {audit.outcome}")
    try:
        receipt = _read_json(workspace, _safe_relative_path(receipt_path, "receipt path"), label="confirmation receipt")
        review_text = _read_text(
            workspace,
            _safe_relative_path(review_path, "review path"),
            max_bytes=MAX_MARKDOWN_BYTES,
            label="review packet",
        )
        frontmatter, fields = _review_identity(review_text)
    except ReviewContractError as exc:
        return ReceiptValidation(False, "invalid", (str(exc),))
    decision = receipt.get("decision")
    if receipt.get("schema") != RECEIPT_SCHEMA:
        reasons.append("receipt schema is invalid")
    if receipt.get("review_id") != review_id:
        reasons.append("receipt review identity changed")
    if receipt.get("subject") != {"path": subject_path, "claim_id": claim_id}:
        reasons.append("receipt subject identity changed")
    if decision not in DECISIONS:
        reasons.append("receipt decision is invalid")
    elif frontmatter.get("status") != VISIBLE_STATES[decision]:
        reasons.append("visible review decision disagrees with receipt")
    if fields.get("claim digest") != audit.claim_digest or receipt.get("claim_digest") != audit.claim_digest:
        reasons.append("current claim block digest changed")
    if fields.get("evidence-set digest") != audit.evidence_set_digest or receipt.get("evidence_set_digest") != audit.evidence_set_digest:
        reasons.append("complete evidence-set digest changed")
    if receipt.get("authorization_source") != "current_user_message":
        reasons.append("receipt was not authorized by a current user message")
    if not actor_is_allowed(str(receipt.get("actor_declaration") or "")):
        reasons.append("receipt signer is not allowed")
    if not DIGEST_RE.fullmatch(str(receipt.get("authorization_digest") or "")):
        reasons.append("receipt authorization digest is invalid")
    expected_id = str(receipt.get("receipt_id") or "")
    expected_path = _receipt_path(expected_id) if IDENTIFIER_RE.fullmatch(expected_id) else ""
    if expected_path != receipt_path:
        reasons.append("receipt path does not match receipt identity")
    state = "current" if not reasons else "stale"
    return ReceiptValidation(not reasons, state, tuple(dict.fromkeys(reasons)))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="operation", required=True)
    for name in ("audit", "packet", "decide", "validate"):
        sub = subparsers.add_parser(name)
        sub.add_argument("--workspace", type=Path, required=True)
        sub.add_argument("--subject", required=True)
        sub.add_argument("--binding", required=True)
        sub.add_argument("--claim-id", required=True)
        sub.add_argument("--review-id", required=True)
        if name != "audit":
            sub.add_argument("--review", required=True)
        if name == "decide":
            sub.add_argument("--interaction-ref")
        if name == "validate":
            sub.add_argument("--receipt", required=True)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    common = {
        "subject_path": args.subject,
        "binding_path": args.binding,
        "claim_id": args.claim_id,
        "review_id": args.review_id,
    }
    try:
        if args.operation == "audit":
            result = audit_claim(args.workspace, **common)
            print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0 if result.outcome in {"pass", "pass-with-limitations"} else 2
        if args.operation == "packet":
            result = write_review_packet(args.workspace, review_path=args.review, **common)
            print(json.dumps(result.as_dict(), ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        if args.operation == "decide":
            message = sys.stdin.read(MAX_MESSAGE_CHARS + 1)
            result = apply_decision(
                args.workspace,
                review_path=args.review,
                current_user_message=message,
                trusted_role="user",
                message_origin="current_user_message",
                is_current_message=True,
                interaction_ref=args.interaction_ref,
                **common,
            )
            print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        result = validate_receipt(
            args.workspace,
            review_path=args.review,
            receipt_path=args.receipt,
            **common,
        )
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if result.valid else 2
    except ReviewContractError as exc:
        print(str(exc), file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
