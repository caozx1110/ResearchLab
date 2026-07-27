"""Safe, no-plugin Obsidian review-sheet exchange.

Checkboxes in the human-owned sheet are intent drafts only.  This module can
create and preview a batch, and can revalidate every displayed subject through
a caller-supplied resolver.  It deliberately does not mutate canonical owner
artifacts: the cross-owner atomic apply API is supplied by the owner integration
layer, which must consume the snapshot only after its root transaction commits.
"""
from __future__ import annotations

import calendar
import hashlib
import json
import os
import re
import stat
import time
import unicodedata
import uuid
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence

from .common import exclusive_file_lock
from .journal import current_operation_id


REVIEW_BATCH_SCHEMA = "kb-obsidian-review-batch/v1"
REVIEW_SHEET_SCHEMA = "kb-obsidian-review-sheet/v1"
SOURCE_SNAPSHOT_SCHEMA = "kb-review-snapshot/v2"
REVIEW_BATCH_REF_RE = re.compile(r"[0-9a-f]{64}")
SOURCE_TOKEN_RE = re.compile(r"[0-9a-f]{32}")
SLOT_REF_RE = re.compile(r"[0-9a-f]{24}")
SHEET_SIZE_LIMIT = 256 * 1024
LEGACY_BATCH_ITEMS = 3
MIN_PERSONAL_BATCH_ITEMS = 4
MAX_BATCH_ITEMS = 20
STRICT_TTL_SECONDS = 24 * 60 * 60
MIN_TTL_SECONDS = 60 * 60
MAX_TTL_SECONDS = 168 * 60 * 60
_RUNTIME_BATCHES_DIR = "kb/.runtime/review-batches"
_SOURCE_SNAPSHOTS_DIR = "kb/.runtime/review-snapshots"
_ANNOTATIONS_DIR = "kb/obsidian/annotations"
_SLOT_MARKER_RE = re.compile(r"^<!-- kb-review-slot:([0-9a-f]{24}) -->$")
_BATCH_MARKER_RE = re.compile(r"^<!-- kb-review-batch:([0-9a-f]{64}) -->$")
_CHECKBOX_RE = re.compile(r"^- \[([ xX])\] (确认|拒绝|暂缓)$")
_CHECKBOX_NORMALIZE_RE = re.compile(r"^- \[[ xX]\] (确认|拒绝|暂缓)$", re.MULTILINE)
_DECISION_BY_LABEL = {"确认": "confirm", "拒绝": "reject", "暂缓": "defer"}
_ALLOWED_OWNER_ACTIONS = {
    "knowledge-base-manager": {"confirm", "promote"},
    "research-orchestrator": {"confirm-decision", "reject-decision"},
    "idea-workbench": {"discuss"},
    "method-designer": {"confirm-selection", "reject-selection"},
    "literature-synthesizer": {"confirm", "reject"},
    "report-author": {"confirm-section", "reject-section"},
}


class ReviewBatchError(ValueError):
    """Stable failure class for sheet/registry validation."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ReviewBatchPreview:
    batch_ref: str
    decision_digest: str
    decisions: tuple[dict[str, Any], ...]
    review_items: tuple[dict[str, Any], ...]
    sheet_relative_path: str
    expires_at: str


@dataclass(frozen=True)
class ReviewBatchPreflight:
    preview: ReviewBatchPreview
    current_items: tuple[dict[str, Any], ...]
    requires_owner_atomic_apply: bool = True


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _timestamp_epoch(value: object) -> float | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return float(calendar.timegm(time.strptime(text, "%Y-%m-%dT%H:%M:%SZ")))
    except (OverflowError, ValueError):
        return None


def _directory_flags() -> int:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _safe_relative_parts(relative: str) -> tuple[str, ...]:
    lexical = PurePosixPath(relative)
    if lexical.is_absolute() or not lexical.parts or any(part in {"", ".", ".."} for part in lexical.parts):
        raise ReviewBatchError("tampered_or_unknown", "review container path is invalid")
    return lexical.parts


def _open_safe_directory(project_root: Path, relative: str, *, create: bool) -> int:
    """Open a workspace directory one component at a time without following links.

    Callers perform file operations relative to the returned descriptor, so an
    intermediate directory rename cannot redirect a checked operation outside
    the workspace.  The caller owns and must close the returned descriptor.
    """
    flags = _directory_flags()
    try:
        descriptor = os.open(project_root.resolve(), flags)
    except OSError as exc:
        raise ReviewBatchError("tampered_or_unknown", "review workspace is unavailable") from exc
    try:
        for part in _safe_relative_parts(relative):
            try:
                child = os.open(part, flags, dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise ReviewBatchError("tampered_or_unknown", "review container is unavailable")
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                except OSError as exc:
                    raise ReviewBatchError(
                        "tampered_or_unknown", "review container cannot be created"
                    ) from exc
                try:
                    child = os.open(part, flags, dir_fd=descriptor)
                except OSError as exc:
                    raise ReviewBatchError(
                        "tampered_or_unknown", "review container is not a safe directory"
                    ) from exc
            except OSError as exc:
                raise ReviewBatchError(
                    "tampered_or_unknown", "review container is not a safe directory"
                ) from exc
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _assert_directory_fd_is_current(project_root: Path, relative: str, descriptor: int) -> None:
    """Reject a namespace swap that occurred after the safe directory open."""
    current = _open_safe_directory(project_root, relative, create=False)
    try:
        opened = os.fstat(descriptor)
        visible = os.fstat(current)
        if (opened.st_dev, opened.st_ino) != (visible.st_dev, visible.st_ino):
            raise ReviewBatchError("tampered_or_unknown", "review container changed during access")
    finally:
        os.close(current)


def _safe_filename(filename: str) -> str:
    if not filename or filename in {".", ".."} or "/" in filename or "\x00" in filename:
        raise ReviewBatchError("tampered_or_unknown", "review filename is invalid")
    return filename


def _regular_file_bytes_at(
    project_root: Path,
    directory: str,
    filename: str,
    *,
    size_limit: int = SHEET_SIZE_LIMIT,
) -> bytes:
    directory_descriptor = _open_safe_directory(project_root, directory, create=False)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        try:
            descriptor = os.open(_safe_filename(filename), flags, dir_fd=directory_descriptor)
        except OSError as exc:
            raise ReviewBatchError("tampered_or_unknown", "review file is missing or unsafe") from exc
        try:
            metadata = os.fstat(descriptor)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > size_limit:
                raise ReviewBatchError("tampered_or_unknown", "review file is not a bounded regular file")
            chunks: list[bytes] = []
            remaining = size_limit + 1
            while remaining > 0:
                chunk = os.read(descriptor, min(64 * 1024, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            data = b"".join(chunks)
            if len(data) > size_limit:
                raise ReviewBatchError("tampered_or_unknown", "review file exceeds its size limit")
            _assert_directory_fd_is_current(project_root, directory, directory_descriptor)
            return data
        finally:
            os.close(descriptor)
    finally:
        os.close(directory_descriptor)


def _write_new_regular_file_at(project_root: Path, directory: str, filename: str, data: bytes) -> None:
    directory_descriptor = _open_safe_directory(project_root, directory, create=True)
    filename = _safe_filename(filename)
    created_identity: tuple[int, int] | None = None
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        _assert_directory_fd_is_current(project_root, directory, directory_descriptor)
        descriptor = os.open(filename, flags, 0o600, dir_fd=directory_descriptor)
        try:
            created = os.fstat(descriptor)
            created_identity = (created.st_dev, created.st_ino)
            view = memoryview(data)
            written = 0
            while written < len(view):
                written += os.write(descriptor, view[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        _assert_directory_fd_is_current(project_root, directory, directory_descriptor)
        os.fsync(directory_descriptor)
    except BaseException:
        if created_identity is not None:
            try:
                current = os.stat(filename, dir_fd=directory_descriptor, follow_symlinks=False)
                if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == created_identity:
                    os.unlink(filename, dir_fd=directory_descriptor)
                    os.fsync(directory_descriptor)
            except OSError:
                pass
        raise
    finally:
        os.close(directory_descriptor)


def _replace_regular_file_at(project_root: Path, directory: str, filename: str, data: bytes) -> None:
    """Atomically replace one existing non-symlink registry file."""
    directory_descriptor = _open_safe_directory(project_root, directory, create=False)
    filename = _safe_filename(filename)
    temporary = f".{filename}.{uuid.uuid4().hex}.tmp"
    backup = f".{filename}.{uuid.uuid4().hex}.before"
    restore = f".{filename}.{uuid.uuid4().hex}.restore"
    backup_exists = False
    restore_exists = False
    preserve_backup = False
    replacement_identity: tuple[int, int] | None = None
    try:
        _assert_directory_fd_is_current(project_root, directory, directory_descriptor)
        try:
            before = os.stat(filename, dir_fd=directory_descriptor, follow_symlinks=False)
        except OSError as exc:
            raise ReviewBatchError("tampered_or_unknown", "review registry is missing or unsafe") from exc
        if not stat.S_ISREG(before.st_mode):
            raise ReviewBatchError("tampered_or_unknown", "review registry is missing or unsafe")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        descriptor = os.open(temporary, flags, 0o600, dir_fd=directory_descriptor)
        try:
            replacement = os.fstat(descriptor)
            replacement_identity = (replacement.st_dev, replacement.st_ino)
            view = memoryview(data)
            written = 0
            while written < len(view):
                written += os.write(descriptor, view[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        current = os.stat(filename, dir_fd=directory_descriptor, follow_symlinks=False)
        if not stat.S_ISREG(current.st_mode) or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino):
            raise ReviewBatchError("tampered_or_unknown", "review registry changed during apply")
        _assert_directory_fd_is_current(project_root, directory, directory_descriptor)
        os.link(
            filename,
            backup,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
        backup_exists = True
        backup_stat = os.stat(backup, dir_fd=directory_descriptor, follow_symlinks=False)
        current = os.stat(filename, dir_fd=directory_descriptor, follow_symlinks=False)
        if (
            not stat.S_ISREG(backup_stat.st_mode)
            or not stat.S_ISREG(current.st_mode)
            or (backup_stat.st_dev, backup_stat.st_ino) != (before.st_dev, before.st_ino)
            or (current.st_dev, current.st_ino) != (before.st_dev, before.st_ino)
        ):
            raise ReviewBatchError("tampered_or_unknown", "review registry changed during backup")
        os.replace(
            temporary,
            filename,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        try:
            _assert_directory_fd_is_current(project_root, directory, directory_descriptor)
            # Commit the new target while the rollback hardlink is still
            # addressable.  Cleanup is not part of the business commit.
            os.fsync(directory_descriptor)
        except BaseException:
            preserve_backup = True
            try:
                replaced = os.stat(filename, dir_fd=directory_descriptor, follow_symlinks=False)
                if (
                    replacement_identity is not None
                    and stat.S_ISREG(replaced.st_mode)
                    and (replaced.st_dev, replaced.st_ino) == replacement_identity
                ):
                    os.link(
                        backup,
                        restore,
                        src_dir_fd=directory_descriptor,
                        dst_dir_fd=directory_descriptor,
                        follow_symlinks=False,
                    )
                    restore_exists = True
                    os.replace(
                        restore,
                        filename,
                        src_dir_fd=directory_descriptor,
                        dst_dir_fd=directory_descriptor,
                    )
                    restore_exists = False
                    os.fsync(directory_descriptor)
                    preserve_backup = False
                    os.unlink(backup, dir_fd=directory_descriptor)
                    backup_exists = False
            except OSError:
                pass
            raise
        try:
            os.unlink(backup, dir_fd=directory_descriptor)
            backup_exists = False
            # Best-effort durability for backup cleanup.  The new target was
            # already committed by the fsync above, so cleanup failure must not
            # turn a successful business write into a false rollback error.
            os.fsync(directory_descriptor)
        except OSError:
            preserve_backup = backup_exists
    finally:
        try:
            try:
                os.unlink(temporary, dir_fd=directory_descriptor)
            except FileNotFoundError:
                pass
            if restore_exists:
                try:
                    os.unlink(restore, dir_fd=directory_descriptor)
                except FileNotFoundError:
                    pass
            if backup_exists and not preserve_backup:
                try:
                    os.unlink(backup, dir_fd=directory_descriptor)
                except FileNotFoundError:
                    pass
        finally:
            os.close(directory_descriptor)


def _json_regular_file_at(project_root: Path, directory: str, filename: str) -> dict[str, Any]:
    try:
        payload = json.loads(_regular_file_bytes_at(project_root, directory, filename).decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewBatchError("tampered_or_unknown", "review registry is invalid") from exc
    if not isinstance(payload, dict):
        raise ReviewBatchError("tampered_or_unknown", "review registry must be a mapping")
    return payload


def _safe_display_text(value: object, *, field: str, max_length: int = 4096) -> str:
    text = str(value or "")
    if not text or len(text) > max_length or "\n" in text or "\r" in text:
        raise ReviewBatchError("unsafe_display", f"review {field} is empty, multiline, or too long")
    if "<!-- kb-review-" in text or re.search(r"- \[[ xX]\]", text):
        raise ReviewBatchError("unsafe_display", f"review {field} contains reserved review syntax")
    if any(unicodedata.category(character) in {"Cc", "Cf"} for character in text):
        raise ReviewBatchError("unsafe_display", f"review {field} contains unsafe control text")
    return text


def _markdown(value: object, *, field: str, max_length: int = 4096) -> str:
    text = _safe_display_text(value, field=field, max_length=max_length)
    return re.sub(r"([\\`*_{}\[\]()<>~|#])", r"\\\1", text)


def _validate_route(route: object) -> dict[str, Any]:
    if not isinstance(route, Mapping):
        raise ReviewBatchError("tampered_or_unknown", "review route is missing")
    normalized = {str(key): value for key, value in route.items()}
    owner = str(normalized.get("owner") or "")
    action = str(normalized.get("action") or "")
    if action not in _ALLOWED_OWNER_ACTIONS.get(owner, set()):
        raise ReviewBatchError("tampered_or_unknown", "review route is unsupported")
    for key, value in normalized.items():
        if key in {"owner", "action", "phase", "confirmation_status"}:
            continue
        text = str(value or "")
        if not text or len(text) > 200 or "\n" in text or "\r" in text:
            raise ReviewBatchError("tampered_or_unknown", "review route identity is invalid")
    return normalized


def _validate_review_item(item: object) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise ReviewBatchError("tampered_or_unknown", "review item is invalid")
    normalized = dict(item)
    subject = normalized.get("subject")
    binding = normalized.get("snapshot_binding")
    if not isinstance(subject, Mapping) or not isinstance(binding, Mapping):
        raise ReviewBatchError("tampered_or_unknown", "review item has no bound subject")
    kind = str(subject.get("kind") or "")
    subject_id = str(subject.get("id") or "")
    owner = str(subject.get("owner") or "")
    if not kind or not subject_id or owner not in _ALLOWED_OWNER_ACTIONS:
        raise ReviewBatchError("tampered_or_unknown", "review subject identity is invalid")
    bound_subject = binding.get("subject")
    verification = binding.get("verification")
    if not isinstance(bound_subject, Mapping) or not isinstance(verification, Mapping):
        raise ReviewBatchError("tampered_or_unknown", "review snapshot binding is incomplete")
    if any(
        str(bound_subject.get(key) or "") != expected
        for key, expected in (("kind", kind), ("id", subject_id), ("owner", owner))
    ):
        raise ReviewBatchError("tampered_or_unknown", "review snapshot subject does not match its route")
    if str(binding.get("confirmation_status") or "") != "pending_user_confirmation" or re.fullmatch(
        r"[0-9a-f]{64}", str(binding.get("content_digest") or "")
    ) is None:
        raise ReviewBatchError("tampered_or_unknown", "review snapshot binding is incomplete")
    path = str(subject.get("path") or bound_subject.get("path") or "")
    if path:
        lexical = PurePosixPath(path)
        if lexical.is_absolute() or not lexical.parts or lexical.parts[0] != "kb" or any(
            part in {"", ".", ".."} for part in lexical.parts
        ):
            raise ReviewBatchError("tampered_or_unknown", "review subject path is unsafe")
    confirm_route = _validate_route(normalized.get("confirm_route"))
    reject_route = _validate_route(normalized.get("reject_route"))
    if str(confirm_route.get("owner") or "") != owner or str(reject_route.get("owner") or "") != owner:
        raise ReviewBatchError("tampered_or_unknown", "review routes do not match their canonical owner")
    return normalized


def _validate_display_item(item: object) -> dict[str, Any]:
    if not isinstance(item, Mapping):
        raise ReviewBatchError("unsafe_display", "review display item is invalid")
    normalized = dict(item)
    _safe_display_text(normalized.get("kind_label"), field="kind label", max_length=80)
    _safe_display_text(normalized.get("title"), field="title", max_length=320)
    _safe_display_text(normalized.get("subject_id"), field="subject id", max_length=200)
    _safe_display_text(normalized.get("location_summary"), field="location summary", max_length=320)
    substance = normalized.get("substance", [])
    claims = normalized.get("claims", [])
    if not isinstance(substance, list) or not isinstance(claims, list):
        raise ReviewBatchError("unsafe_display", "review display details are invalid")
    for row in substance:
        if not isinstance(row, Mapping):
            raise ReviewBatchError("unsafe_display", "review substance is invalid")
        _safe_display_text(row.get("label"), field="substance label", max_length=80)
        _safe_display_text(row.get("text"), field="substance text")
    for claim in claims:
        if not isinstance(claim, Mapping):
            raise ReviewBatchError("unsafe_display", "review claim is invalid")
        _safe_display_text(claim.get("type_label"), field="claim label", max_length=80)
        _safe_display_text(claim.get("text"), field="claim text")
        evidence = str(claim.get("evidence") or "")
        if evidence:
            _safe_display_text(evidence, field="evidence", max_length=320)
        extra = claim.get("extra_evidence_count", 0)
        if isinstance(extra, bool):
            raise ReviewBatchError("unsafe_display", "review evidence count is invalid")
        try:
            extra_count = int(extra)
        except (TypeError, ValueError) as exc:
            raise ReviewBatchError("unsafe_display", "review evidence count is invalid") from exc
        if extra_count < 0 or extra_count > 10_000:
            raise ReviewBatchError("unsafe_display", "review evidence count is invalid")
    if not claims and not str(normalized.get("fact_summary") or "").strip():
        raise ReviewBatchError("unsafe_display", "review display has no confirmable content")
    if str(normalized.get("fact_summary") or ""):
        _safe_display_text(normalized.get("fact_summary"), field="fact summary")
    return normalized


def _render_sheet(
    batch_ref: str,
    expires_at: str,
    slots: Sequence[Mapping[str, Any]],
    displays: Sequence[Mapping[str, Any]],
) -> str:
    lines = [
        "---",
        f"schema: {REVIEW_SHEET_SCHEMA}",
        "kind: review_intent_draft",
        "---",
        "",
        "# 待确认判断",
        "",
        "> 这里的勾选只是决定草稿，不会自动修改知识库。勾选后请回到与 Agent 的对话中要求同步。",
        "> 每项只能选择一个：确认、拒绝或暂缓。",
        f"> 有效至：{_markdown(expires_at, field='expiry', max_length=40)}",
        "",
        f"<!-- kb-review-batch:{batch_ref} -->",
        "",
    ]
    for index, (slot, display) in enumerate(zip(slots, displays), start=1):
        slot_ref = str(slot.get("slot_ref") or "")
        lines.extend(
            [
                f"<!-- kb-review-slot:{slot_ref} -->",
                f"## {index}. {_markdown(display.get('kind_label'), field='kind label', max_length=80)}「{_markdown(display.get('title'), field='title', max_length=320)}」",
                "",
                f"公共编号：{_markdown(display.get('subject_id'), field='subject id', max_length=200)}",
                "",
                f"来源 / 定位：{_markdown(display.get('location_summary'), field='location summary', max_length=320)}",
                "",
            ]
        )
        fact_summary = str(display.get("fact_summary") or "")
        if fact_summary:
            lines.extend([f"待确认事实：{_markdown(fact_summary, field='fact summary')}", ""])
        substance = display.get("substance", [])
        if substance:
            lines.append("本次决定同时绑定：")
            for row in substance:
                lines.append(
                    f"- {_markdown(row.get('label'), field='substance label', max_length=80)}："
                    f"{_markdown(row.get('text'), field='substance text')}"
                )
            lines.append("")
        claims = display.get("claims", [])
        for claim in claims:
            lines.append(
                f"- {_markdown(claim.get('type_label'), field='claim label', max_length=80)}："
                f"{_markdown(claim.get('text'), field='claim text')}"
            )
            evidence = str(claim.get("evidence") or "")
            if evidence:
                lines.append(f"  - 证据摘录：{_markdown(evidence, field='evidence', max_length=320)}")
            extra = int(claim.get("extra_evidence_count") or 0)
            if extra > 0:
                lines.append(f"  - 另有 {extra} 条已核验证据。")
        lines.extend(["", "- [ ] 确认", "- [ ] 拒绝", "- [ ] 暂缓", ""])
    return "\n".join(lines).rstrip() + "\n"


def _immutable_batch_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    immutable = {
        key: payload.get(key)
        for key in (
            "schema",
            "nonce",
            "created_at",
            "expires_at",
            "source_snapshot_token",
            "review_items",
            "slots",
            "display_items",
        )
    }
    # v1 registries created before governance profiles did not bind this
    # field.  Omitting it for those payloads preserves their historical hash;
    # every newly-created registry includes and binds the effective limit.
    if "item_limit" in payload:
        immutable["item_limit"] = payload.get("item_limit")
    if "governance_profile" in payload:
        immutable["governance_profile"] = payload.get("governance_profile")
    return immutable


def _batch_ref(payload: Mapping[str, Any]) -> str:
    return _sha256(_canonical_json(_immutable_batch_payload(payload)))


def _load_source_snapshot(project_root: Path, token: str) -> dict[str, Any]:
    if SOURCE_TOKEN_RE.fullmatch(token) is None:
        raise ReviewBatchError("tampered_or_unknown", "source review snapshot token is invalid")
    payload = _json_regular_file_at(project_root, _SOURCE_SNAPSHOTS_DIR, f"{token}.json")
    if payload.get("schema") != SOURCE_SNAPSHOT_SCHEMA:
        raise ReviewBatchError("tampered_or_unknown", "source review snapshot has the wrong schema")
    return payload


def _bound_item_limit(value: object, *, legacy_default: bool = False) -> int:
    if value is None and legacy_default:
        return LEGACY_BATCH_ITEMS
    if isinstance(value, bool) or not isinstance(value, int):
        raise ReviewBatchError("invalid_batch", "review batch item limit is invalid")
    limit = value
    if limit < 1 or limit > MAX_BATCH_ITEMS:
        raise ReviewBatchError("invalid_batch", "review batch item limit is out of bounds")
    return limit


def _validate_source_policy(profile: str, item_limit: int, ttl_seconds: object) -> None:
    if profile == "strict" and item_limit != LEGACY_BATCH_ITEMS:
        raise ReviewBatchError("tampered_or_unknown", "strict review snapshot item limit is invalid")
    if profile == "personal" and item_limit < MIN_PERSONAL_BATCH_ITEMS:
        raise ReviewBatchError("tampered_or_unknown", "personal review snapshot item limit is invalid")
    # R1 dialogue snapshots always bind ttl_seconds. Older registries did not;
    # their exact expires_at remains batch-bound and readable for compatibility.
    if ttl_seconds is None:
        return
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        raise ReviewBatchError("tampered_or_unknown", "source review snapshot expiry is invalid")
    if ttl_seconds < MIN_TTL_SECONDS or ttl_seconds > MAX_TTL_SECONDS:
        raise ReviewBatchError("tampered_or_unknown", "source review snapshot expiry is invalid")
    if profile == "strict" and ttl_seconds != STRICT_TTL_SECONDS:
        raise ReviewBatchError("tampered_or_unknown", "strict review snapshot expiry is invalid")


def create_obsidian_review_batch(
    project_root: Path,
    *,
    source_snapshot_token: str,
    review_items: Sequence[Mapping[str, Any]],
    display_items: Sequence[Mapping[str, Any]],
    item_limit: int | None = None,
) -> dict[str, Any]:
    """Create one human-editable sheet bound to an existing public review snapshot."""
    source = _load_source_snapshot(project_root, source_snapshot_token)
    source_limit_raw = source.get("item_limit")
    source_profile = str(source.get("governance_profile") or "strict")
    if source_profile not in {"personal", "strict"}:
        raise ReviewBatchError("tampered_or_unknown", "source review snapshot governance profile is invalid")
    if item_limit is None:
        try:
            effective_limit = _bound_item_limit(source_limit_raw, legacy_default=True)
        except ReviewBatchError as exc:
            raise ReviewBatchError("tampered_or_unknown", "source review snapshot item limit is invalid") from exc
    else:
        effective_limit = _bound_item_limit(item_limit)
        try:
            source_limit = _bound_item_limit(source_limit_raw, legacy_default=True)
        except ReviewBatchError as exc:
            raise ReviewBatchError("tampered_or_unknown", "source review snapshot item limit is invalid") from exc
        if source_limit != effective_limit:
            raise ReviewBatchError("tampered_or_unknown", "source review snapshot item limit does not match the batch")
    _validate_source_policy(source_profile, effective_limit, source.get("ttl_seconds"))
    if not review_items or len(review_items) > effective_limit or len(review_items) != len(display_items):
        raise ReviewBatchError("invalid_batch", "review batch exceeds its bound displayed-item limit")
    normalized_items = [_validate_review_item(item) for item in review_items]
    if source.get("status") != "unused" or source.get("review_items") != normalized_items:
        raise ReviewBatchError("tampered_or_unknown", "source review snapshot does not match the displayed items")
    expires_at = _timestamp_epoch(source.get("expires_at"))
    if expires_at is None or time.time() >= expires_at:
        raise ReviewBatchError("expired", "source review snapshot expired")
    normalized_displays = [_validate_display_item(item) for item in display_items]
    slots = [{"slot_ref": uuid.uuid4().hex[:24]} for _item in normalized_items]
    payload: dict[str, Any] = {
        "schema": REVIEW_BATCH_SCHEMA,
        "nonce": uuid.uuid4().hex,
        "created_at": str(source.get("created_at") or ""),
        "expires_at": str(source.get("expires_at") or ""),
        "source_snapshot_token": source_snapshot_token,
        "review_items": normalized_items,
        "slots": slots,
        "display_items": normalized_displays,
        "item_limit": effective_limit,
        "governance_profile": source_profile,
        "status": "unused",
    }
    batch_ref = _batch_ref(payload)
    payload["batch_ref"] = batch_ref
    sheet_text = _render_sheet(batch_ref, str(payload["expires_at"]), slots, normalized_displays)
    sheet_name = f"Pending Review {batch_ref[:12]}.md"
    root = project_root.resolve()
    registry_path = root / _RUNTIME_BATCHES_DIR / f"{batch_ref}.json"
    sheet_path = root / _ANNOTATIONS_DIR / sheet_name
    try:
        _write_new_regular_file_at(
            root,
            _RUNTIME_BATCHES_DIR,
            f"{batch_ref}.json",
            (_canonical_json(payload) + "\n").encode("utf-8"),
        )
    except FileExistsError as exc:
        raise ReviewBatchError("tampered_or_unknown", "review batch identity already exists") from exc
    try:
        _write_new_regular_file_at(root, _ANNOTATIONS_DIR, sheet_name, sheet_text.encode("utf-8"))
    except BaseException as exc:
        try:
            directory_descriptor = _open_safe_directory(root, _RUNTIME_BATCHES_DIR, create=False)
            try:
                metadata = os.stat(f"{batch_ref}.json", dir_fd=directory_descriptor, follow_symlinks=False)
                if stat.S_ISREG(metadata.st_mode):
                    os.unlink(f"{batch_ref}.json", dir_fd=directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except (OSError, ReviewBatchError):
            pass
        if isinstance(exc, FileExistsError):
            raise ReviewBatchError("tampered_or_unknown", "review batch identity already exists") from exc
        raise
    return {
        "batch_ref": batch_ref,
        "sheet_relative_path": sheet_path.relative_to(project_root.resolve()).as_posix(),
        "expires_at": str(payload["expires_at"]),
        "item_count": len(normalized_items),
        "item_limit": effective_limit,
        "governance_profile": source_profile,
    }


def _load_batch(project_root: Path, batch_ref: str, *, now: float | None = None) -> dict[str, Any]:
    if REVIEW_BATCH_REF_RE.fullmatch(batch_ref) is None:
        raise ReviewBatchError("tampered_or_unknown", "review batch reference is invalid")
    payload = _json_regular_file_at(project_root, _RUNTIME_BATCHES_DIR, f"{batch_ref}.json")
    if payload.get("schema") != REVIEW_BATCH_SCHEMA or payload.get("batch_ref") != batch_ref:
        raise ReviewBatchError("tampered_or_unknown", "review batch registry has the wrong identity")
    if _batch_ref(payload) != batch_ref:
        raise ReviewBatchError("tampered_or_unknown", "review batch immutable binding was modified")
    status_value = str(payload.get("status") or "")
    if status_value == "consumed":
        raise ReviewBatchError("already_applied", "review batch was already applied")
    if status_value != "unused":
        raise ReviewBatchError("tampered_or_unknown", "review batch lifecycle is invalid")
    expires_at = _timestamp_epoch(payload.get("expires_at"))
    if expires_at is None:
        raise ReviewBatchError("tampered_or_unknown", "review batch expiry is invalid")
    if (time.time() if now is None else now) >= expires_at:
        raise ReviewBatchError("expired", "review batch expired")
    items = payload.get("review_items")
    displays = payload.get("display_items")
    slots = payload.get("slots")
    try:
        item_limit = _bound_item_limit(payload.get("item_limit"), legacy_default=True)
    except ReviewBatchError as exc:
        raise ReviewBatchError("tampered_or_unknown", "review batch item limit is invalid") from exc
    if (
        not isinstance(items, list)
        or not isinstance(displays, list)
        or not isinstance(slots, list)
        or not items
        or len(items) > item_limit
        or len(items) != len(displays)
        or len(items) != len(slots)
    ):
        raise ReviewBatchError("tampered_or_unknown", "review batch item set is invalid")
    payload["review_items"] = [_validate_review_item(item) for item in items]
    payload["display_items"] = [_validate_display_item(item) for item in displays]
    slot_refs = [str(item.get("slot_ref") or "") if isinstance(item, Mapping) else "" for item in slots]
    if any(SLOT_REF_RE.fullmatch(ref) is None for ref in slot_refs) or len(set(slot_refs)) != len(slot_refs):
        raise ReviewBatchError("tampered_or_unknown", "review batch slots are invalid")
    source = _load_source_snapshot(project_root, str(payload.get("source_snapshot_token") or ""))
    batch_profile = str(payload.get("governance_profile") or "strict")
    source_profile = str(source.get("governance_profile") or "strict")
    try:
        source_item_limit = _bound_item_limit(source.get("item_limit"), legacy_default=True)
    except ReviewBatchError as exc:
        raise ReviewBatchError("tampered_or_unknown", "source review snapshot item limit is invalid") from exc
    if (
        batch_profile not in {"personal", "strict"}
        or source_profile != batch_profile
        or source_item_limit != item_limit
        or str(source.get("expires_at") or "") != str(payload.get("expires_at") or "")
    ):
        raise ReviewBatchError("tampered_or_unknown", "source review snapshot policy no longer matches the batch")
    _validate_source_policy(batch_profile, item_limit, source.get("ttl_seconds"))
    source_status = str(source.get("status") or "")
    if source_status == "consumed":
        raise ReviewBatchError("already_applied", "source review snapshot was already applied")
    if source_status == "expired":
        raise ReviewBatchError("expired", "source review snapshot expired")
    if source_status != "unused" or source.get("review_items") != payload["review_items"]:
        raise ReviewBatchError("tampered_or_unknown", "source review snapshot no longer matches the batch")
    return payload


def _sheet_path(project_root: Path, batch_ref: str) -> Path:
    return project_root.resolve() / _ANNOTATIONS_DIR / f"Pending Review {batch_ref[:12]}.md"


def _parse_sheet_decisions(text: str, payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    batch_ref = str(payload.get("batch_ref") or "")
    slots = payload.get("slots")
    displays = payload.get("display_items")
    items = payload.get("review_items")
    expected = _render_sheet(batch_ref, str(payload.get("expires_at") or ""), slots, displays)
    normalized = _CHECKBOX_NORMALIZE_RE.sub(r"- [ ] \1", text)
    if normalized != expected:
        raise ReviewBatchError("sheet_tampered", "only the generated review checkboxes may be edited")
    lines = text.splitlines()
    batch_markers = [match.group(1) for line in lines if (match := _BATCH_MARKER_RE.fullmatch(line))]
    if batch_markers != [batch_ref]:
        raise ReviewBatchError("sheet_tampered", "review sheet batch marker is invalid")
    choices: dict[str, list[str]] = {}
    current_slot = ""
    for line in lines:
        slot_match = _SLOT_MARKER_RE.fullmatch(line)
        if slot_match:
            current_slot = slot_match.group(1)
            if current_slot in choices:
                raise ReviewBatchError("sheet_tampered", "review sheet has a duplicate slot")
            choices[current_slot] = []
            continue
        checkbox = _CHECKBOX_RE.fullmatch(line)
        if checkbox and current_slot:
            mark, label = checkbox.groups()
            if mark.lower() == "x":
                choices[current_slot].append(_DECISION_BY_LABEL[label])
    slot_refs = [str(slot.get("slot_ref") or "") for slot in slots]
    if list(choices) != slot_refs:
        raise ReviewBatchError("sheet_tampered", "review sheet slots no longer match the batch")
    decisions: list[dict[str, Any]] = []
    for slot_ref, item in zip(slot_refs, items):
        selected = choices[slot_ref]
        if len(selected) != 1:
            raise ReviewBatchError("invalid_decision", "each review item must select exactly one decision")
        decisions.append(
            {
                "slot_ref": slot_ref,
                "decision": selected[0],
                "subject": dict(item.get("subject") or {}),
                "snapshot_binding": dict(item.get("snapshot_binding") or {}),
                "confirm_route": dict(item.get("confirm_route") or {}),
                "reject_route": dict(item.get("reject_route") or {}),
            }
        )
    return tuple(decisions)


def preview_obsidian_review_batch(
    project_root: Path,
    batch_ref: str,
    *,
    now: float | None = None,
) -> ReviewBatchPreview:
    """Pure-read preview of checkbox intents; never consumes the batch."""
    root = project_root.resolve()
    payload = _load_batch(root, batch_ref, now=now)
    sheet_path = _sheet_path(root, batch_ref)
    try:
        text = _regular_file_bytes_at(
            root,
            _ANNOTATIONS_DIR,
            f"Pending Review {batch_ref[:12]}.md",
        ).decode("utf-8")
    except UnicodeError as exc:
        raise ReviewBatchError("sheet_tampered", "review sheet is not valid UTF-8") from exc
    decisions = _parse_sheet_decisions(text, payload)
    return ReviewBatchPreview(
        batch_ref=batch_ref,
        decision_digest=_sha256(
            _canonical_json(
                {
                    "batch_ref": batch_ref,
                    "decisions": decisions,
                }
            )
        ),
        decisions=decisions,
        review_items=tuple(dict(item) for item in payload["review_items"]),
        sheet_relative_path=sheet_path.relative_to(root).as_posix(),
        expires_at=str(payload.get("expires_at") or ""),
    )


def preflight_obsidian_review_batch(
    project_root: Path,
    batch_ref: str,
    *,
    current_item_resolver: Callable[[Mapping[str, Any]], Mapping[str, Any]],
    now: float | None = None,
) -> ReviewBatchPreflight:
    """Revalidate the complete displayed set without performing any writes."""
    preview = preview_obsidian_review_batch(project_root, batch_ref, now=now)
    current_items: list[dict[str, Any]] = []
    for expected in preview.review_items:
        try:
            current = dict(current_item_resolver(expected.get("subject", {})))
        except (KeyError, TypeError, ValueError) as exc:
            raise ReviewBatchError("stale_content", "a displayed review subject is no longer ready") from exc
        if (
            current.get("subject") != expected.get("subject")
            or current.get("snapshot_binding") != expected.get("snapshot_binding")
            or current.get("confirm_route") != expected.get("confirm_route")
            or current.get("reject_route") != expected.get("reject_route")
        ):
            raise ReviewBatchError("stale_content", "a displayed review subject changed after export")
        current_items.append(current)
    return ReviewBatchPreflight(preview=preview, current_items=tuple(current_items))


def obsidian_review_batch_runtime_targets(project_root: Path, batch_ref: str) -> tuple[Path, Path, Path]:
    """Return the exact mutable registry files after validating an unused batch."""
    root = project_root.resolve()
    payload = _load_batch(root, batch_ref)
    batch_path = root / _RUNTIME_BATCHES_DIR / f"{batch_ref}.json"
    source_path = root / _SOURCE_SNAPSHOTS_DIR / f"{payload['source_snapshot_token']}.json"
    return batch_path, source_path, _sheet_path(root, batch_ref)


def _consume_obsidian_review_batch_locked(project_root: Path, batch_ref: str) -> tuple[Path, Path, Path]:
    """Consume both one-time registries inside the caller's root transaction."""
    root = project_root.resolve()
    if not current_operation_id(root):
        raise ReviewBatchError("tampered_or_unknown", "review batch consumption requires a root transaction")
    payload = _load_batch(root, batch_ref)
    source_token = str(payload.get("source_snapshot_token") or "")
    source = _load_source_snapshot(root, source_token)
    if source.get("status") != "unused" or source.get("review_items") != payload.get("review_items"):
        raise ReviewBatchError("tampered_or_unknown", "source review snapshot changed during apply")
    consumed_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    sheet_name = f"Pending Review {batch_ref[:12]}.md"
    try:
        sheet_text = _regular_file_bytes_at(root, _ANNOTATIONS_DIR, sheet_name).decode("utf-8")
    except UnicodeError as exc:
        raise ReviewBatchError("sheet_tampered", "review sheet is not valid UTF-8") from exc
    title = "# 待确认判断\n"
    if title not in sheet_text:
        raise ReviewBatchError("sheet_tampered", "review sheet title is missing")
    applied_sheet = sheet_text.replace(
        title,
        "# 已处理判断\n\n"
        f"> ✅ 本批决定已于 {consumed_at} 作为一个整体应用；以下人工勾选原样保留为处理记录。\n",
        1,
    )
    consumed_batch = dict(payload)
    consumed_batch["status"] = "consumed"
    consumed_batch["consumed_at"] = consumed_at
    consumed_source = dict(source)
    consumed_source["status"] = "consumed"
    consumed_source["consumed_at"] = consumed_at
    batch_path = root / _RUNTIME_BATCHES_DIR / f"{batch_ref}.json"
    source_path = root / _SOURCE_SNAPSHOTS_DIR / f"{source_token}.json"
    sheet_path = root / _ANNOTATIONS_DIR / sheet_name
    _replace_regular_file_at(
        root,
        _RUNTIME_BATCHES_DIR,
        f"{batch_ref}.json",
        (_canonical_json(consumed_batch) + "\n").encode("utf-8"),
    )
    _replace_regular_file_at(
        root,
        _SOURCE_SNAPSHOTS_DIR,
        f"{source_token}.json",
        (_canonical_json(consumed_source) + "\n").encode("utf-8"),
    )
    _replace_regular_file_at(root, _ANNOTATIONS_DIR, sheet_name, applied_sheet.encode("utf-8"))
    return batch_path, source_path, sheet_path


def consume_obsidian_review_batch(project_root: Path, batch_ref: str) -> tuple[Path, Path, Path]:
    """Consume an Obsidian batch while excluding source-snapshot GC races."""
    root = project_root.resolve()
    lock_path = root / "kb/.runtime/review-snapshots.lock"
    with exclusive_file_lock(lock_path):
        return _consume_obsidian_review_batch_locked(root, batch_ref)


__all__ = [
    "MAX_BATCH_ITEMS",
    "REVIEW_BATCH_SCHEMA",
    "REVIEW_SHEET_SCHEMA",
    "ReviewBatchError",
    "ReviewBatchPreflight",
    "ReviewBatchPreview",
    "create_obsidian_review_batch",
    "consume_obsidian_review_batch",
    "obsidian_review_batch_runtime_targets",
    "preflight_obsidian_review_batch",
    "preview_obsidian_review_batch",
]
