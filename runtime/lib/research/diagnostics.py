"""Local-only structured diagnostics for skill evolution.

This module records deterministic, redacted issue summaries.  It deliberately
does not accept raw command output or infer a root cause.  Automatic callers
must use :func:`capture_runtime_failure`; :func:`record_diagnostic_issue` is the
explicit user/agent capture surface and therefore remains available when the
automatic policy is off.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import sys
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .journal import mutation_transaction
from .paths import kb_root
from .prefs import load_runtime_preferences
from .yaml_io import (
    dump_yaml,
    load_yaml,
    load_yaml_mapping_bytes_strict,
    write_yaml_if_changed,
)


DIAGNOSTIC_MODES = {"off", "errors-only", "developer"}
SKILL_MODES = {"inherit", *DIAGNOSTIC_MODES}
DETAIL_LEVELS = {"redacted", "local-detailed"}
SKILL_DETAIL_LEVELS = {"inherit", *DETAIL_LEVELS}
SEVERITIES = {"info", "low", "medium", "high", "critical"}
SEVERITY_ORDER = {value: index for index, value in enumerate(("info", "low", "medium", "high", "critical"))}
STATUSES = {"pending", "confirmed", "dismissed", "resolved"}
REVIEW_STATUSES = {"confirmed", "dismissed", "resolved"}
SOURCES = {"user", "agent", "runtime"}
REPRODUCIBLE_VALUES = {"unknown", "yes", "no", "intermittent"}
PRIVACY_CLASSIFICATION = "local-redacted"
DETAIL_PRIVACY_CLASSIFICATION = "local-detailed"
INTAKE_FAILURE_STAGES = frozenset(
    {
        "source-recognition",
        "prepare-freeze",
        "materialization",
        "canonical-transaction",
        "checkpoint",
        "unknown",
    }
)

_FAILURE_STAGE_RECEIPT_DIRECTORY = "kb/.runtime/diagnostics/failure-stages"
_FAILURE_STAGE_RECEIPT_SCHEMA = 1
_FAILURE_STAGE_RECEIPT_MAX_BYTES = 1024
_FAILURE_STAGE_RECEIPT_TTL_SECONDS = 120

_ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_TRACEBACK_RE = re.compile(r"(?is)\btraceback\s*\(most recent call last\).*?(?=(?:\n\S)|\Z)")
_FILE_FRAME_RE = re.compile(r"(?i)\bfile\s+[\"'][^\"']+[\"'](?:,\s*line\s*\d+)?")
_WINDOWS_PATH_RE = re.compile(r"(?i)(?<![A-Za-z0-9_])[A-Z]:\\(?:[^\s\\]+\\)*[^\s,;:]*")
_POSIX_PATH_RE = re.compile(r"(?<![A-Za-z0-9_:])/(?:[^\s/]+/)*[^\s,;:]*")
_SECRET_RE = re.compile(
    r"(?i)\b(api[-_ ]?key|access[-_ ]?token|token|auth(?:orization)?|password|passwd|secret|bearer)"
    r"\s*[:= ]\s*[^\s,;]+"
)
_EMAIL_RE = re.compile(r"(?i)\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b")
_STANDALONE_CREDENTIAL_RE = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:"
    r"sk-[A-Za-z0-9][A-Za-z0-9_-]{9,}|"
    r"github_pat_[A-Za-z0-9_]{15,}|"
    r"gh[pousr]_[A-Za-z0-9]{15,}|"
    r"xox[baprs]-[A-Za-z0-9-]{10,}|"
    r"AKIA[0-9A-Z]{16}"
    r")(?![A-Za-z0-9])"
)
_ENV_ASSIGNMENT_RE = re.compile(r"\b[A-Z_][A-Z0-9_]{1,63}=\S+")
_URL_CREDENTIAL_RE = re.compile(r"(?i)(https?://)[^/@\s:]+:[^/@\s]+@")
_SAFE_IDENTIFIER_RE = re.compile(r"[^a-z0-9_.-]+")
_AUTOMATIC_RUNTIME_CAPTURE = object()

_DETAIL_SCHEMA = "skill-diagnostic-detail/v1"
_DETAIL_DIRECTORY = "kb/memory/skill-evolution/.private/details"
_DETAIL_REF_PREFIX = "memory/skill-evolution/.private/details"
_DETAIL_MAX_BYTES = 64 * 1024
_DETAIL_HISTORY_LIMIT = 5
_DETAIL_FRAME_LIMIT = 8
_DETAIL_EVENT_LIMIT = 4
_DETAIL_LIST_LIMIT = 5
_DETAIL_TEXT_LIMIT = 300
_DETAIL_ENVELOPE_KEYS = frozenset(
    {
        "schema",
        "exception_class",
        "failure_stage",
        "frames",
        "events",
        "runtime_version",
        "dependency_versions",
    }
)
_DETAIL_ENVELOPE_SCHEMA = "diagnostic-mechanical-envelope/v1"
_DETAIL_EVENT_CODES = frozenset(
    {
        "owner-nonzero-exit",
        "dispatcher-capture",
        "failure-stage-consumed",
        "failure-stage-unknown",
        "checkpoint-failure",
    }
)
def diagnostics_path(project_root: Path) -> Path:
    return kb_root(project_root) / "memory" / "skill-evolution" / "issues.yaml"


def diagnostic_detail_path(project_root: Path, issue_id: str) -> Path:
    normalized = _safe_identifier(issue_id)
    if not normalized or normalized != str(issue_id or "").strip().lower():
        raise ValueError("diagnostic issue id must be one safe identifier")
    return kb_root(project_root) / _DETAIL_REF_PREFIX / f"{normalized}.yaml"


def _integer(value: Any, default: int, *, minimum: int) -> int:
    try:
        return max(minimum, int(value))
    except (TypeError, ValueError):
        return default


def _safe_identifier(value: str, *, default: str = "", limit: int = 80) -> str:
    normalized = _SAFE_IDENTIFIER_RE.sub("-", str(value or "").strip().lower()).strip("-.")
    return (normalized or default)[:limit]


def _safe_error_class(value: str) -> str:
    """Keep only a stable class token, never free-form exception text."""

    text = str(value or "").strip()
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9_.-]{0,79}", text):
        return text.lower()
    match = re.match(r"[A-Za-z][A-Za-z0-9_.-]{0,79}", text)
    return match.group(0).lower() if match else "unspecified"


def _safe_failure_stage(value: object, *, default: str = "unknown") -> str:
    normalized = str(value or "").strip().lower()
    return normalized if normalized in INTAKE_FAILURE_STAGES else default


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _open_failure_stage_directory(project_root: Path, *, create: bool) -> int:
    """Open the private handoff directory without following workspace links."""

    descriptor = os.open(project_root.resolve(strict=True), _directory_flags())
    try:
        for part in _FAILURE_STAGE_RECEIPT_DIRECTORY.split("/"):
            try:
                child = os.open(part, _directory_flags(), dir_fd=descriptor)
            except FileNotFoundError:
                if not create:
                    raise
                try:
                    os.mkdir(part, 0o700, dir_fd=descriptor)
                except FileExistsError:
                    pass
                child = os.open(part, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        metadata = os.fstat(descriptor)
        if (
            not stat.S_ISDIR(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
        ):
            raise PermissionError("failure-stage handoff directory is not private")
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _failure_stage_receipt_name(parent_pid: int) -> str:
    if isinstance(parent_pid, bool) or not 1 <= int(parent_pid) <= 2**31 - 1:
        raise ValueError("parent pid is outside the supported range")
    return f"{int(parent_pid)}.json"


def _claim_failure_stage_receipt(
    directory: int,
    filename: str,
) -> tuple[str, tuple[int, int]] | None:
    """Atomically move one safe receipt to a private one-consumer name."""

    try:
        metadata = os.stat(filename, dir_fd=directory, follow_symlinks=False)
    except OSError:
        return None
    if (
        not stat.S_ISREG(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o600
        or metadata.st_size > _FAILURE_STAGE_RECEIPT_MAX_BYTES
    ):
        return None
    claimed = f".{filename}.{uuid.uuid4().hex}.claim"
    try:
        os.replace(filename, claimed, src_dir_fd=directory, dst_dir_fd=directory)
    except OSError:
        return None
    return claimed, (metadata.st_dev, metadata.st_ino)


def _write_failure_stage_receipt(project_root: Path, payload: Mapping[str, Any]) -> None:
    directory = _open_failure_stage_directory(project_root, create=True)
    filename = _failure_stage_receipt_name(int(payload["parent_pid"]))
    temporary = f".{filename}.{uuid.uuid4().hex}.tmp"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    data = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
        "ascii"
    )
    if len(data) > _FAILURE_STAGE_RECEIPT_MAX_BYTES:
        os.close(directory)
        raise ValueError("failure-stage receipt exceeds its byte budget")
    try:
        descriptor = os.open(temporary, flags, 0o600, dir_fd=directory)
        try:
            view = memoryview(data)
            written = 0
            while written < len(view):
                written += os.write(descriptor, view[written:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.replace(temporary, filename, src_dir_fd=directory, dst_dir_fd=directory)
        os.fsync(directory)
    finally:
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        os.close(directory)


def publish_runtime_failure_stage(
    project_root: Path,
    *,
    skill: str,
    operation: str,
    failure_stage: str,
) -> bool:
    """Best-effort, allowlisted child-to-dispatcher failure-stage handoff.

    This receipt exists only long enough for the parent dispatcher to consume
    it after a nonzero child exit.  It never contains source text, arguments,
    output, exception text, environment values, or paths.  Failure to publish
    must never replace the owner's original failure.
    """

    try:
        normalized_skill = _safe_identifier(skill, default="unknown-skill")
        normalized_operation = _safe_identifier(operation, default="unknown-operation")
        normalized_stage = _safe_failure_stage(failure_stage)
        if not diagnostics_policy(project_root, normalized_skill).get("automatic_capture"):
            return False
        parent_pid = os.getppid()
        payload = {
            "schema": _FAILURE_STAGE_RECEIPT_SCHEMA,
            "parent_pid": parent_pid,
            "skill": normalized_skill,
            "operation": normalized_operation,
            "failure_stage": normalized_stage,
            "created_at_epoch": int(time.time()),
        }
        _write_failure_stage_receipt(project_root, payload)
        return True
    except Exception:  # noqa: BLE001 - optional diagnostics never replace the owner failure
        return False


def _consume_runtime_failure_stage(
    project_root: Path,
    *,
    skill: str,
    operation: str,
) -> str:
    """Consume only the current dispatcher's fresh, bounded regular receipt."""

    try:
        directory = _open_failure_stage_directory(project_root, create=False)
    except (OSError, ValueError):
        return "unknown"
    filename = _failure_stage_receipt_name(os.getpid())
    claim = _claim_failure_stage_receipt(directory, filename)
    if claim is None:
        os.close(directory)
        return "unknown"
    claimed, claimed_identity = claim
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor: int | None = None
    identity: tuple[int, int] | None = claimed_identity
    data = b""
    try:
        try:
            descriptor = os.open(claimed, flags, dir_fd=directory)
        except OSError:
            return "unknown"
        metadata = os.fstat(descriptor)
        identity = (metadata.st_dev, metadata.st_ino)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or identity != claimed_identity
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size > _FAILURE_STAGE_RECEIPT_MAX_BYTES
        ):
            return "unknown"
        chunks: list[bytes] = []
        remaining = _FAILURE_STAGE_RECEIPT_MAX_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 4096))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        if len(data) > _FAILURE_STAGE_RECEIPT_MAX_BYTES:
            return "unknown"
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if identity is not None:
            try:
                current = os.stat(claimed, dir_fd=directory, follow_symlinks=False)
                if (
                    stat.S_ISREG(current.st_mode)
                    and (current.st_dev, current.st_ino) == identity
                ):
                    os.unlink(claimed, dir_fd=directory)
                    os.fsync(directory)
            except OSError:
                pass
        os.close(directory)

    try:
        payload = json.loads(data.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return "unknown"
    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "parent_pid",
        "skill",
        "operation",
        "failure_stage",
        "created_at_epoch",
    }:
        return "unknown"
    try:
        age = int(time.time()) - int(payload["created_at_epoch"])
        parent_pid = int(payload["parent_pid"])
    except (TypeError, ValueError):
        return "unknown"
    if (
        payload.get("schema") != _FAILURE_STAGE_RECEIPT_SCHEMA
        or parent_pid != os.getpid()
        or age < -5
        or age > _FAILURE_STAGE_RECEIPT_TTL_SECONDS
        or payload.get("skill") != _safe_identifier(skill, default="unknown-skill")
        or payload.get("operation") != _safe_identifier(operation, default="unknown-operation")
    ):
        return "unknown"
    return _safe_failure_stage(payload.get("failure_stage"))


def _redacted_context_reference(value: str) -> str:
    """Retain correlation without persisting free-form/user/evidence text."""

    text = str(value or "")
    if not text.strip():
        return ""
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return f"context-sha256:{digest[:16]}"


def diagnostics_policy(project_root: Path, skill: str = "") -> dict[str, Any]:
    """Return a pure-read, normalized effective diagnostics policy."""

    preferences = load_runtime_preferences(project_root)
    raw = preferences.get("diagnostics", {})
    if not isinstance(raw, dict):
        raw = {}
    workspace_mode = str(raw.get("mode") or "off").strip().lower()
    if workspace_mode not in DIAGNOSTIC_MODES:
        workspace_mode = "off"
    normalized_skill = _safe_identifier(skill)
    overrides = raw.get("per_skill", {})
    if not isinstance(overrides, dict):
        overrides = {}
    skill_mode = str(overrides.get(normalized_skill) or "inherit").strip().lower() if normalized_skill else "inherit"
    if skill_mode not in SKILL_MODES:
        skill_mode = "inherit"
    effective_mode = workspace_mode if skill_mode == "inherit" else skill_mode
    workspace_detail_level = str(raw.get("detail_level") or "redacted").strip().lower()
    if workspace_detail_level not in DETAIL_LEVELS:
        workspace_detail_level = "redacted"
    detail_overrides = raw.get("per_skill_detail_level", {})
    if not isinstance(detail_overrides, dict):
        detail_overrides = {}
    skill_detail_level = (
        str(detail_overrides.get(normalized_skill) or "inherit").strip().lower()
        if normalized_skill
        else "inherit"
    )
    if skill_detail_level not in SKILL_DETAIL_LEVELS:
        skill_detail_level = "inherit"
    effective_detail_level = (
        workspace_detail_level
        if skill_detail_level == "inherit"
        else skill_detail_level
    )
    token_budget = _integer(raw.get("token_budget_per_task"), 0, minimum=0)
    policy = {
        "mode": effective_mode,
        "effective_mode": effective_mode,
        "workspace_mode": workspace_mode,
        "skill": normalized_skill,
        "skill_mode": skill_mode,
        "detail_level": effective_detail_level,
        "effective_detail_level": effective_detail_level,
        "workspace_detail_level": workspace_detail_level,
        "skill_detail_level": skill_detail_level,
        # This is forced rather than trusted from disk in D1.
        "local_only": True,
        "token_budget_per_task": token_budget,
        "max_issues_per_task": _integer(raw.get("max_issues_per_task"), 20, minimum=1),
        "dedup_window_seconds": _integer(raw.get("dedup_window_seconds"), 604800, minimum=0),
        "cooldown_seconds": _integer(raw.get("cooldown_seconds"), 0, minimum=0),
        "automatic_capture": effective_mode in {"errors-only", "developer"},
        "allow_agent_retrospective": effective_mode == "developer" and token_budget > 0,
        "persist_local_detail": (
            effective_mode in {"errors-only", "developer"}
            and effective_detail_level == "local-detailed"
        ),
        "governance_profile": (
            "personal" if str(preferences.get("governance_profile") or "") == "personal" else "strict"
        ),
    }
    return policy


def _now(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def redact_diagnostic_text(value: str, *, limit: int = 500) -> str:
    """Deterministically project untrusted text to a short local-safe summary."""

    text = str(value or "")
    text = _ANSI_RE.sub("", text)
    text = _TRACEBACK_RE.sub("<traceback-redacted>", text)
    text = _FILE_FRAME_RE.sub("file <path>", text)
    text = _URL_CREDENTIAL_RE.sub(r"\1<credentials-redacted>@", text)
    text = _EMAIL_RE.sub("<email-redacted>", text)
    text = _SECRET_RE.sub(lambda match: f"{match.group(1).lower().replace(' ', '-')}:<secret-redacted>", text)
    text = _STANDALONE_CREDENTIAL_RE.sub("<credential-redacted>", text)
    text = _ENV_ASSIGNMENT_RE.sub("<env-redacted>", text)
    text = _WINDOWS_PATH_RE.sub("<path>", text)
    text = _POSIX_PATH_RE.sub("<path>", text)
    chars: list[str] = []
    for char in text:
        category = unicodedata.category(char)
        if category in {"Cf", "Cs"}:
            continue
        if category == "Cc" and char not in {"\n", "\t"}:
            continue
        chars.append(char)
    text = " ".join("".join(chars).replace("\r", "\n").split())
    if len(text) > limit:
        text = text[: max(0, limit - 1)].rstrip() + "…"
    return text


def _dedup_text(value: str) -> str:
    text = redact_diagnostic_text(value, limit=500).casefold()
    return " ".join("".join(char if char.isalnum() else " " for char in text).split())


def _fingerprint(*, category: str, skill: str, summary: str, trigger: str, error_class: str) -> str:
    signature = "\x1f".join(
        (
            category,
            skill,
            _dedup_text(summary),
            _dedup_text(trigger),
            _safe_error_class(error_class),
        )
    )
    return hashlib.sha256(signature.encode("utf-8")).hexdigest()


def _detail_ref(issue_id: str) -> str:
    return f"{_DETAIL_REF_PREFIX}/{issue_id}.yaml"


def _detail_directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )


def _directory_identity(metadata: os.stat_result) -> tuple[int, int, int]:
    return metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)


def _close_fd_quietly(descriptor: int) -> None:
    try:
        os.close(descriptor)
    except OSError:
        pass


def _open_detail_directory(project_root: Path, *, create: bool) -> int:
    """Open the durable private detail directory without following links."""

    descriptor = os.open(project_root.resolve(strict=True), _detail_directory_flags())
    try:
        parts = _DETAIL_DIRECTORY.split("/")
        for index, part in enumerate(parts):
            private_component = index >= len(parts) - 2
            created_component = False
            try:
                expected = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                if not create:
                    raise
                desired_mode = 0o700 if private_component else 0o755
                try:
                    os.mkdir(part, desired_mode, dir_fd=descriptor)
                    created_component = True
                except FileExistsError:
                    pass
                expected = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                if created_component:
                    if not stat.S_ISDIR(expected.st_mode) or expected.st_uid != os.getuid():
                        raise PermissionError("diagnostic detail directory creation was displaced")
                    # A restrictive umask can remove the owner's search bits,
                    # so repair only the directory this process just created
                    # before attempting the anchored no-follow open.
                    os.chmod(
                        part,
                        desired_mode,
                        dir_fd=descriptor,
                        follow_symlinks=False,
                    )
            child: int | None = None
            try:
                child = os.open(part, _detail_directory_flags(), dir_fd=descriptor)
                opened = os.fstat(child)
                visible = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                if not (
                    _directory_identity(expected)
                    == _directory_identity(opened)
                    == _directory_identity(visible)
                ):
                    raise PermissionError("diagnostic detail directory creation was displaced")
                if created_component:
                    os.fchmod(child, 0o700 if private_component else 0o755)
                opened = os.fstat(child)
                visible = os.stat(part, dir_fd=descriptor, follow_symlinks=False)
                if _directory_identity(opened) != _directory_identity(visible):
                    raise PermissionError("diagnostic detail directory creation was displaced")
                if private_component and (
                    not stat.S_ISDIR(opened.st_mode)
                    or opened.st_uid != os.getuid()
                    or stat.S_IMODE(opened.st_mode) & 0o077
                ):
                    raise PermissionError("diagnostic detail directory is not private")
            except BaseException:
                if child is not None:
                    _close_fd_quietly(child)
                raise
            try:
                os.close(descriptor)
            except BaseException:
                _close_fd_quietly(child)
                raise
            descriptor = child
        return descriptor
    except BaseException:
        _close_fd_quietly(descriptor)
        raise


def _assert_detail_directory_visible(project_root: Path, descriptor: int) -> None:
    """Confirm an anchored detail directory is still the visible no-follow chain."""

    visible = _open_detail_directory(project_root, create=False)
    try:
        if _directory_identity(os.fstat(descriptor)) != _directory_identity(os.fstat(visible)):
            raise PermissionError("diagnostic detail directory is no longer visible")
    finally:
        os.close(visible)


def _read_private_detail_file_at(directory: int, filename: str) -> tuple[bytes, os.stat_result]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor = os.open(filename, flags, dir_fd=directory)
    try:
        metadata = os.fstat(descriptor)
        visible = os.stat(filename, dir_fd=directory, follow_symlinks=False)
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
            or metadata.st_size > _DETAIL_MAX_BYTES
            or _directory_identity(metadata) != _directory_identity(visible)
        ):
            raise PermissionError("diagnostic detail artifact is not a bounded private file")
        chunks: list[bytes] = []
        remaining = _DETAIL_MAX_BYTES + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(remaining, 8192))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        current = os.fstat(descriptor)
        visible = os.stat(filename, dir_fd=directory, follow_symlinks=False)
        identity_fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
        if (
            len(data) != metadata.st_size
            or len(data) > _DETAIL_MAX_BYTES
            or any(getattr(metadata, field) != getattr(current, field) for field in identity_fields)
            or _directory_identity(current) != _directory_identity(visible)
        ):
            raise PermissionError("diagnostic detail artifact changed during its anchored read")
        return data, current
    finally:
        os.close(descriptor)


def _read_detail_bytes(project_root: Path, issue_id: str) -> bytes:
    directory = _open_detail_directory(project_root, create=False)
    filename = f"{issue_id}.yaml"
    try:
        _assert_detail_directory_visible(project_root, directory)
        data, _ = _read_private_detail_file_at(directory, filename)
        _assert_detail_directory_visible(project_root, directory)
        return data
    finally:
        os.close(directory)


def _write_detail_bytes(project_root: Path, issue_id: str, data: bytes) -> None:
    if len(data) > _DETAIL_MAX_BYTES:
        raise ValueError("diagnostic detail artifact exceeds its byte budget")
    directory = _open_detail_directory(project_root, create=True)
    filename = f"{issue_id}.yaml"
    nonce = uuid.uuid4().hex
    temporary = f".{filename}.{nonce}.tmp"
    backup = f".{filename}.recovery.bak"
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_NOFOLLOW", 0)
        | getattr(os, "O_CLOEXEC", 0)
    )
    descriptor: int | None = None
    backup_created = False
    preserve_backup = False
    try:
        _assert_detail_directory_visible(project_root, directory)
        try:
            existing = os.stat(filename, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            existing = None
        if existing is not None and (
            not stat.S_ISREG(existing.st_mode)
            or existing.st_uid != os.getuid()
            or stat.S_IMODE(existing.st_mode) != 0o600
        ):
            raise PermissionError("diagnostic detail artifact is not a private regular file")
        try:
            backup_metadata = os.stat(backup, dir_fd=directory, follow_symlinks=False)
        except FileNotFoundError:
            backup_metadata = None
        if backup_metadata is not None:
            if existing is None:
                raise PermissionError("diagnostic detail recovery backup has no visible peer")
            visible_bytes, _ = _read_private_detail_file_at(directory, filename)
            backup_bytes, opened_backup = _read_private_detail_file_at(directory, backup)
            current_backup = os.stat(backup, dir_fd=directory, follow_symlinks=False)
            if (
                visible_bytes != backup_bytes
                or _directory_identity(opened_backup) != _directory_identity(current_backup)
            ):
                raise PermissionError("diagnostic detail recovery backup requires manual inspection")
            os.unlink(backup, dir_fd=directory)
            os.fsync(directory)
        descriptor = os.open(temporary, flags, 0o600, dir_fd=directory)
        os.fchmod(descriptor, 0o600)
        view = memoryview(data)
        written = 0
        while written < len(view):
            count = os.write(descriptor, view[written:])
            if count <= 0:
                raise OSError("diagnostic detail write made no progress")
            written += count
        os.fsync(descriptor)
        written_metadata = os.fstat(descriptor)
        _assert_detail_directory_visible(project_root, directory)
        if existing is not None:
            os.link(
                filename,
                backup,
                src_dir_fd=directory,
                dst_dir_fd=directory,
                follow_symlinks=False,
            )
            backup_created = True
            linked = os.stat(backup, dir_fd=directory, follow_symlinks=False)
            current = os.stat(filename, dir_fd=directory, follow_symlinks=False)
            if not (
                _directory_identity(existing)
                == _directory_identity(linked)
                == _directory_identity(current)
            ):
                raise PermissionError("diagnostic detail artifact changed before replacement")
        _assert_detail_directory_visible(project_root, directory)
        os.replace(temporary, filename, src_dir_fd=directory, dst_dir_fd=directory)
        try:
            installed = os.stat(filename, dir_fd=directory, follow_symlinks=False)
        except BaseException:
            preserve_backup = backup_created
            raise
        if _directory_identity(installed) != _directory_identity(written_metadata):
            preserve_backup = backup_created
            raise PermissionError("diagnostic detail artifact replacement was displaced")
        os.fsync(directory)
        try:
            _assert_detail_directory_visible(project_root, directory)
        except BaseException:
            try:
                current = os.stat(filename, dir_fd=directory, follow_symlinks=False)
            except OSError:
                preserve_backup = backup_created
            else:
                if _directory_identity(current) == _directory_identity(written_metadata):
                    if backup_created:
                        os.replace(backup, filename, src_dir_fd=directory, dst_dir_fd=directory)
                        backup_created = False
                    else:
                        os.unlink(filename, dir_fd=directory)
                    os.fsync(directory)
                else:
                    preserve_backup = backup_created
            raise
        if backup_created:
            os.unlink(backup, dir_fd=directory)
            backup_created = False
            os.fsync(directory)
    finally:
        if descriptor is not None:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory)
        except FileNotFoundError:
            pass
        if backup_created and not preserve_backup:
            try:
                os.unlink(backup, dir_fd=directory)
            except FileNotFoundError:
                pass
        os.close(directory)


def _safe_version(value: object, *, default: str = "") -> str:
    candidate = str(value or "").strip()
    if re.fullmatch(r"[0-9A-Za-z][0-9A-Za-z.+_-]{0,63}", candidate):
        return candidate
    return default


def _normalize_repo_frame(value: object) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != {"path", "line", "function"}:
        raise ValueError("detail frame must use exactly path, line, and function")
    raw_path = str(value.get("path") or "").strip().replace("\\", "/")
    candidate = PurePosixPath(raw_path)
    if not raw_path or candidate.is_absolute() or any(part in {"", ".", ".."} for part in candidate.parts):
        raise ValueError("detail frame path must be a safe repository-relative path")
    parts = candidate.parts
    if parts[:2] == (".agents", "skills"):
        parts = parts[1:]
    elif parts[:3] == (".agents", "lib", "research"):
        parts = ("runtime", "lib", *parts[2:])
    allowed = parts[:1] == ("skills",) or parts[:3] == ("runtime", "lib", "research")
    if not allowed:
        raise ValueError("detail frame path is outside managed product source")
    try:
        line = int(value.get("line"))
    except (TypeError, ValueError) as exc:
        raise ValueError("detail frame line must be an integer") from exc
    if isinstance(value.get("line"), bool) or not 1 <= line <= 10_000_000:
        raise ValueError("detail frame line is outside the supported range")
    function = str(value.get("function") or "").strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_.<>-]{0,79}", function):
        raise ValueError("detail frame function must be one safe symbol")
    return {"path": PurePosixPath(*parts).as_posix(), "line": line, "function": function}


def _normalize_detail_envelope(value: Mapping[str, Any] | None, *, failure_stage: str) -> dict[str, Any]:
    raw: Mapping[str, Any] = value if value is not None else {
        "schema": _DETAIL_ENVELOPE_SCHEMA,
        "exception_class": "owner-nonzero-exit",
        "failure_stage": failure_stage or "unknown",
        "frames": [],
        "events": ["owner-nonzero-exit", "dispatcher-capture"],
        "runtime_version": f"python-{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
        "dependency_versions": {},
    }
    if set(raw) != _DETAIL_ENVELOPE_KEYS or raw.get("schema") != _DETAIL_ENVELOPE_SCHEMA:
        raise ValueError("diagnostic detail envelope has unsupported fields or schema")
    frames_raw = raw.get("frames")
    if not isinstance(frames_raw, list):
        raise ValueError("diagnostic detail frames must be a list")
    frames = [_normalize_repo_frame(item) for item in frames_raw[: _DETAIL_FRAME_LIMIT + 1]]
    if len(frames) > _DETAIL_FRAME_LIMIT:
        raise ValueError("diagnostic detail frame limit exceeded")
    events_raw = raw.get("events")
    if not isinstance(events_raw, list):
        raise ValueError("diagnostic detail events must be a list")
    events: list[str] = []
    for item in events_raw[: _DETAIL_EVENT_LIMIT + 1]:
        code = str(item or "").strip().lower()
        if code not in _DETAIL_EVENT_CODES:
            raise ValueError("diagnostic detail event is not allowlisted")
        if code not in events:
            events.append(code)
    if len(events) > _DETAIL_EVENT_LIMIT:
        raise ValueError("diagnostic detail event limit exceeded")
    dependencies_raw = raw.get("dependency_versions")
    if not isinstance(dependencies_raw, Mapping) or len(dependencies_raw) > 8:
        raise ValueError("diagnostic dependency versions must be a small mapping")
    dependencies: dict[str, str] = {}
    for name, version in sorted(dependencies_raw.items(), key=lambda item: str(item[0])):
        safe_name = _safe_identifier(str(name or ""))
        safe_version = _safe_version(version)
        if not safe_name or not safe_version:
            raise ValueError("diagnostic dependency version is not a stable token")
        dependencies[safe_name] = safe_version
    return {
        "exception_class": _safe_error_class(str(raw.get("exception_class") or "")),
        "failure_stage": _safe_failure_stage(raw.get("failure_stage") or failure_stage),
        "frames": frames,
        "events": events,
        "runtime_version": _safe_version(raw.get("runtime_version"), default="unknown"),
        "dependency_versions": dependencies,
    }


def _detail_signature(*, owner: str, operation: str, envelope: Mapping[str, Any]) -> str:
    stable = {
        "owner": owner,
        "operation": operation,
        "exception_class": envelope["exception_class"],
        "failure_stage": envelope["failure_stage"],
        "frames": envelope["frames"],
    }
    return hashlib.sha256(
        json.dumps(stable, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).hexdigest()


def _retrospective_state(policy: Mapping[str, Any]) -> dict[str, str]:
    mode = str(policy.get("effective_mode") or "off")
    budget = _integer(policy.get("token_budget_per_task"), 0, minimum=0)
    if mode != "developer":
        return {"status": "not-run", "reason": "mode-errors-only", "explanation": ""}
    if budget <= 0:
        return {"status": "not-run", "reason": "budget-zero", "explanation": ""}
    return {"status": "pending", "reason": "awaiting-agent", "explanation": ""}


def _detail_snapshot(
    *,
    timestamp: str,
    mechanical: Mapping[str, Any],
    envelope: Mapping[str, Any],
    policy: Mapping[str, Any],
    bundle_version: str,
    source_commit: str,
) -> dict[str, Any]:
    return {
        "captured_at": timestamp,
        "observation": {
            "category": str(mechanical.get("category") or "runtime-failure"),
            "owner": str(mechanical.get("owner") or "unknown-skill"),
            "operation": str(mechanical.get("operation") or "unknown-operation"),
            "return_code": int(mechanical.get("return_code") or 1),
            "exception_class": str(envelope["exception_class"]),
            "failure_stage": str(envelope["failure_stage"]),
            "bundle_version": bundle_version,
            "source_commit": source_commit,
            "runtime_version": str(envelope["runtime_version"]),
            "dependency_versions": dict(envelope["dependency_versions"]),
        },
        "root_cause": _retrospective_state(policy),
        "reproduction": [],
        "relevant_trace": list(envelope["frames"]),
        "safe_events": list(envelope["events"]),
        "output_excerpt": [],
        "optimization_candidates": [],
        "next_validation": [],
    }


def _load_detail_document(project_root: Path, issue_id: str) -> tuple[dict[str, Any], bytes]:
    data = _read_detail_bytes(project_root, issue_id)
    payload = load_yaml_mapping_bytes_strict(data)
    if not isinstance(payload, dict) or payload.get("schema") != _DETAIL_SCHEMA:
        raise ValueError("diagnostic detail artifact schema is invalid")
    if payload.get("issue_id") != issue_id:
        raise ValueError("diagnostic detail artifact identity is invalid")
    return payload, data


def _serialize_detail_document(document: Mapping[str, Any]) -> bytes:
    data = dump_yaml(dict(document)).encode("utf-8")
    if len(data) > _DETAIL_MAX_BYTES:
        raise ValueError("diagnostic detail artifact exceeds its byte budget")
    return data


def _load_document(project_root: Path) -> dict[str, Any]:
    payload = load_yaml(diagnostics_path(project_root), default={})
    if not isinstance(payload, dict):
        return {"schema_version": 1, "generated_by": "skill-evolution-advisor", "issues": []}
    issues = payload.get("issues", [])
    payload["issues"] = [item for item in issues if isinstance(item, dict)] if isinstance(issues, list) else []
    payload.setdefault("schema_version", 1)
    payload.setdefault("generated_by", "skill-evolution-advisor")
    return payload


def list_diagnostic_issues(
    project_root: Path,
    *,
    status: str = "",
    skill: str = "",
) -> list[dict[str, Any]]:
    """Pure-read issue listing, newest occurrence first."""

    normalized_status = str(status or "").strip().lower()
    if normalized_status and normalized_status not in STATUSES:
        raise ValueError(f"status must be one of: {', '.join(sorted(STATUSES))}")
    normalized_skill = _safe_identifier(skill)
    selected = []
    for issue in _load_document(project_root)["issues"]:
        if normalized_status and str(issue.get("status") or "") != normalized_status:
            continue
        if normalized_skill and str(issue.get("skill") or "") != normalized_skill:
            continue
        selected.append(dict(issue))
    return sorted(selected, key=lambda item: (str(item.get("last_seen_at") or ""), str(item.get("id") or "")), reverse=True)


def _local_version(project_root: Path) -> tuple[str, str]:
    bundle_version = ""
    source_commit = ""
    try:
        bundle_version = (project_root / ".agents" / "VERSION").read_text(encoding="utf-8").strip()[:64]
    except OSError:
        pass
    try:
        manifest = json.loads((project_root / ".agents" / ".install-manifest.json").read_text(encoding="utf-8"))
        if isinstance(manifest, dict):
            candidate = str(manifest.get("source_commit") or "").strip().lower()
            if re.fullmatch(r"[0-9a-f]{7,64}", candidate):
                source_commit = candidate
    except (OSError, ValueError, TypeError):
        pass
    if not re.fullmatch(r"[0-9A-Za-z.+-]{1,64}", bundle_version):
        bundle_version = ""
    return bundle_version, source_commit


def _validated(value: str, allowed: set[str], field: str) -> str:
    normalized = str(value or "").strip().lower()
    if normalized not in allowed:
        raise ValueError(f"{field} must be one of: {', '.join(sorted(allowed))}")
    return normalized


def _occurrences(issue: dict[str, Any]) -> int:
    return _integer(issue.get("occurrences"), 1, minimum=1)


def _runtime_metadata(value: object) -> dict[str, Any]:
    """Normalize the only four plaintext fields personal automatic capture may add."""

    if not isinstance(value, Mapping):
        return {}

    def stable_identifier(raw: object, default: str) -> str:
        candidate = str(raw or "").strip().lower()
        return candidate if re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,79}", candidate) else default

    category = stable_identifier(value.get("category"), "runtime-failure")
    owner = stable_identifier(value.get("owner"), "unknown-skill")
    operation = stable_identifier(value.get("operation"), "unknown-operation")
    raw_return_code = value.get("return_code")
    if isinstance(raw_return_code, bool):
        return_code = 1
    else:
        try:
            return_code = int(raw_return_code)
        except (TypeError, ValueError):
            return_code = 1
    return {
        "category": category,
        "owner": owner,
        "operation": operation,
        "return_code": return_code,
    }


def record_diagnostic_issue(
    project_root: Path,
    *,
    category: str,
    severity: str,
    skill: str,
    summary: str,
    expected: str = "",
    actual: str = "",
    trigger: str = "",
    source: str = "runtime",
    reproducible: str = "unknown",
    context: str = "",
    error_class: str = "",
    now: datetime | None = None,
    _automatic_runtime_metadata: Mapping[str, Any] | None = None,
    _automatic_failure_stage: str = "",
    _automatic_detail_envelope: Mapping[str, Any] | None = None,
    _suppress_detail: bool = False,
    _capture_token: object | None = None,
) -> tuple[dict[str, Any], bool]:
    """Record an explicit issue even when automatic diagnostics are off."""

    normalized_category = _safe_identifier(category)
    if not normalized_category:
        raise ValueError("category must be a non-empty safe identifier")
    normalized_severity = _validated(severity, SEVERITIES, "severity")
    normalized_source = _validated(source, SOURCES, "source")
    normalized_reproducible = _validated(reproducible, REPRODUCIBLE_VALUES, "reproducible")
    normalized_skill = _safe_identifier(skill, default="unknown-skill")
    safe_summary = redact_diagnostic_text(summary, limit=300)
    if not safe_summary:
        raise ValueError("summary must not be empty after redaction")
    safe_trigger = redact_diagnostic_text(trigger, limit=160)
    safe_error_class = _safe_error_class(error_class)
    summary_fingerprint = _fingerprint(
        category=normalized_category,
        skill=normalized_skill,
        summary=safe_summary,
        trigger=safe_trigger,
        error_class=safe_error_class,
    )
    timestamp = _now(now)
    path = diagnostics_path(project_root)
    bundle_version, source_commit = _local_version(project_root)
    mechanical = (
        _runtime_metadata(_automatic_runtime_metadata)
        if _capture_token is _AUTOMATIC_RUNTIME_CAPTURE
        else {}
    )
    automatic_failure_stage = (
        _safe_failure_stage(_automatic_failure_stage)
        if _capture_token is _AUTOMATIC_RUNTIME_CAPTURE and _automatic_failure_stage
        else ""
    )
    policy = (
        diagnostics_policy(project_root, normalized_skill)
        if _capture_token is _AUTOMATIC_RUNTIME_CAPTURE
        else {}
    )
    summary_mechanical = (
        mechanical if policy.get("governance_profile") == "personal" else {}
    )
    detail_envelope: dict[str, Any] | None = None
    detail_signature = ""
    if mechanical and policy.get("persist_local_detail") and not _suppress_detail:
        detail_envelope = _normalize_detail_envelope(
            _automatic_detail_envelope,
            failure_stage=automatic_failure_stage or "unknown",
        )
        detail_signature = _detail_signature(
            owner=str(mechanical.get("owner") or "unknown-skill"),
            operation=str(mechanical.get("operation") or "unknown-operation"),
            envelope=detail_envelope,
        )
    fingerprint = (
        hashlib.sha256(
            f"{summary_fingerprint}\x1f{detail_signature}".encode("ascii")
        ).hexdigest()
        if detail_envelope is not None
        else summary_fingerprint
    )
    issue_id = f"diag-{fingerprint[:16]}"
    detail_path = diagnostic_detail_path(project_root, issue_id) if detail_envelope is not None else None
    if detail_path is not None:
        directory = _open_detail_directory(project_root, create=True)
        os.close(directory)

    transaction_targets = [path, detail_path] if detail_path is not None else [path]

    with mutation_transaction(
        project_root,
        "record-diagnostic-issue",
        transaction_targets,
        undoable=False,
        operation_role="diagnostics",
    ):
        document = _load_document(project_root)
        issues = document["issues"]
        for issue in issues:
            if str(issue.get("fingerprint") or "") != fingerprint:
                continue
            issue["occurrences"] = _occurrences(issue) + 1
            issue["last_seen_at"] = timestamp
            old_severity = str(issue.get("severity") or "info")
            if SEVERITY_ORDER.get(normalized_severity, 0) > SEVERITY_ORDER.get(old_severity, 0):
                issue["severity"] = normalized_severity
            if summary_mechanical:
                issue.update(summary_mechanical)
            if automatic_failure_stage:
                issue["failure_stage"] = automatic_failure_stage
            if detail_envelope is not None and detail_path is not None:
                try:
                    detail_document, old_detail_bytes = _load_detail_document(project_root, issue_id)
                except FileNotFoundError as exc:
                    if issue.get("detail_ref"):
                        raise ValueError("diagnostic detail reference is dangling") from exc
                    detail_document = {
                        "schema": _DETAIL_SCHEMA,
                        "issue_id": issue_id,
                        "summary_fingerprint": summary_fingerprint,
                        "detail_signature": detail_signature,
                        "privacy_classification": DETAIL_PRIVACY_CLASSIFICATION,
                        "created_at": timestamp,
                        "updated_at": timestamp,
                        "occurrence_history": [],
                        "dropped_history_count": 0,
                    }
                    old_detail_bytes = b""
                if (
                    old_detail_bytes
                    and str(issue.get("detail_digest") or "")
                    != hashlib.sha256(old_detail_bytes).hexdigest()
                ):
                    raise ValueError("diagnostic detail digest no longer matches the summary index")
                history = detail_document.get("occurrence_history", [])
                if not isinstance(history, list):
                    raise ValueError("diagnostic detail history is invalid")
                history.append(
                    _detail_snapshot(
                        timestamp=timestamp,
                        mechanical=mechanical,
                        envelope=detail_envelope,
                        policy=policy,
                        bundle_version=bundle_version,
                        source_commit=source_commit,
                    )
                )
                dropped = _integer(detail_document.get("dropped_history_count"), 0, minimum=0)
                if len(history) > _DETAIL_HISTORY_LIMIT:
                    dropped += len(history) - _DETAIL_HISTORY_LIMIT
                    history = history[-_DETAIL_HISTORY_LIMIT:]
                detail_document["occurrence_history"] = history
                detail_document["dropped_history_count"] = dropped
                detail_document["updated_at"] = timestamp
                detail_bytes = _serialize_detail_document(detail_document)
                _write_detail_bytes(project_root, issue_id, detail_bytes)
                issue["detail_ref"] = _detail_ref(issue_id)
                issue["detail_digest"] = hashlib.sha256(detail_bytes).hexdigest()
                issue["retrospective_status"] = history[-1]["root_cause"]["status"]
            write_yaml_if_changed(path, document)
            return dict(issue), False

        issue = {
            "id": issue_id,
            "fingerprint": fingerprint,
            "category": normalized_category,
            "severity": normalized_severity,
            "status": "pending",
            "skill": normalized_skill,
            "summary": safe_summary,
            "expected": redact_diagnostic_text(expected, limit=300),
            "actual": redact_diagnostic_text(actual, limit=300),
            "trigger": safe_trigger,
            "source": normalized_source,
            "reproducible": normalized_reproducible,
            "occurrences": 1,
            "first_seen_at": timestamp,
            "last_seen_at": timestamp,
            "bundle_version": bundle_version,
            "source_commit": source_commit,
            "context": _redacted_context_reference(context),
            "error_class": safe_error_class,
            "privacy_classification": PRIVACY_CLASSIFICATION,
        }
        if summary_mechanical:
            issue.update(summary_mechanical)
        if automatic_failure_stage:
            issue["failure_stage"] = automatic_failure_stage
        if detail_envelope is not None and detail_path is not None:
            snapshot = _detail_snapshot(
                timestamp=timestamp,
                mechanical=mechanical,
                envelope=detail_envelope,
                policy=policy,
                bundle_version=bundle_version,
                source_commit=source_commit,
            )
            detail_document = {
                "schema": _DETAIL_SCHEMA,
                "issue_id": issue_id,
                "summary_fingerprint": summary_fingerprint,
                "detail_signature": detail_signature,
                "privacy_classification": DETAIL_PRIVACY_CLASSIFICATION,
                "created_at": timestamp,
                "updated_at": timestamp,
                "occurrence_history": [snapshot],
                "dropped_history_count": 0,
            }
            detail_bytes = _serialize_detail_document(detail_document)
            _write_detail_bytes(project_root, issue_id, detail_bytes)
            issue["detail_ref"] = _detail_ref(issue_id)
            issue["detail_digest"] = hashlib.sha256(detail_bytes).hexdigest()
            issue["retrospective_status"] = snapshot["root_cause"]["status"]
        issues.append(issue)
        issues.sort(key=lambda item: str(item.get("id") or ""))
        write_yaml_if_changed(path, document)
        return dict(issue), True


def capture_runtime_failure(
    project_root: Path,
    *,
    skill: str,
    operation: str,
    returncode: int,
    public_summary: str = "",
    detail_envelope: Mapping[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Capture one nonzero owner exit when the effective policy allows it."""

    policy = diagnostics_policy(project_root, skill)
    if int(returncode) == 0 or not policy.get("automatic_capture"):
        return None
    normalized_skill = _safe_identifier(skill, default="unknown-skill")
    normalized_operation = _safe_identifier(operation, default="unknown-operation")
    failure_stage = ""
    if normalized_skill == "source-intake" and normalized_operation == "add":
        failure_stage = _consume_runtime_failure_stage(
            project_root,
            skill=normalized_skill,
            operation=normalized_operation,
        )
    summary = public_summary or "The requested knowledge-base operation did not complete."
    automatic_metadata = {
        "category": "runtime-failure",
        "owner": skill,
        "operation": operation,
        "return_code": int(returncode),
    }
    record_kwargs = {
        "category": "runtime-failure",
        "severity": "medium",
        "skill": skill,
        "summary": summary,
        "expected": "The operation completes successfully.",
        "actual": f"The operation returned nonzero status {int(returncode)}.",
        "trigger": operation,
        "source": "runtime",
        "reproducible": "unknown",
        "error_class": (
            f"owner-nonzero-exit.{failure_stage}"
            if failure_stage
            else "owner-nonzero-exit"
        ),
        "_automatic_runtime_metadata": automatic_metadata,
        "_automatic_failure_stage": failure_stage,
        "_automatic_detail_envelope": detail_envelope,
        "_capture_token": _AUTOMATIC_RUNTIME_CAPTURE,
    }
    try:
        issue, _ = record_diagnostic_issue(project_root, **record_kwargs)
    except (Exception, SystemExit):
        if not policy.get("persist_local_detail"):
            raise
        # Optional detail persistence is fail-soft.  The original operation has
        # already failed; retain the legacy redacted summary without weakening
        # its exit code, public text, or recovery semantics.
        record_kwargs["_suppress_detail"] = True
        issue, _ = record_diagnostic_issue(project_root, **record_kwargs)
    return issue


def load_diagnostic_detail(project_root: Path, *, issue_id: str) -> dict[str, Any]:
    """Pure-read one private detail artifact after verifying its summary binding."""

    normalized_issue_id = _safe_identifier(issue_id)
    issue = next(
        (
            item
            for item in _load_document(project_root)["issues"]
            if str(item.get("id") or "") == normalized_issue_id
        ),
        None,
    )
    if issue is None or not issue.get("detail_ref"):
        raise ValueError(f"diagnostic detail not found: {normalized_issue_id}")
    if issue.get("detail_ref") != _detail_ref(normalized_issue_id):
        raise ValueError("diagnostic detail reference is outside the private store")
    document, data = _load_detail_document(project_root, normalized_issue_id)
    digest = hashlib.sha256(data).hexdigest()
    if str(issue.get("detail_digest") or "") != digest:
        raise ValueError("diagnostic detail digest no longer matches the summary index")
    return dict(document)


def _safe_agent_text(value: object, *, field: str, required: bool) -> str:
    safe = redact_diagnostic_text(str(value or ""), limit=_DETAIL_TEXT_LIMIT)
    if required and not safe:
        raise ValueError(f"{field} must not be empty after sanitization")
    return safe


def _safe_agent_text_list(value: object, *, field: str, required: bool = False) -> list[str]:
    if not isinstance(value, list) or len(value) > _DETAIL_LIST_LIMIT:
        raise ValueError(f"{field} must be a list of at most {_DETAIL_LIST_LIMIT} items")
    items = [
        _safe_agent_text(item, field=field, required=True)
        for item in value
    ]
    if required and not items:
        raise ValueError(f"{field} must contain at least one item")
    return items


def apply_diagnostic_retrospective(
    project_root: Path,
    *,
    issue_id: str,
    expected_detail_digest: str,
    explanation: str,
    reproduction: list[str],
    optimization_candidates: list[str],
    next_validation: list[str],
) -> dict[str, Any]:
    """Apply one digest-bound Agent hypothesis to the current private snapshot."""

    normalized_issue_id = _safe_identifier(issue_id)
    if normalized_issue_id != str(issue_id or "").strip().lower():
        raise ValueError("diagnostic issue id must be one safe identifier")
    expected_digest = str(expected_detail_digest or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected_digest):
        raise ValueError("expected detail digest must be one sha256 value")
    safe_explanation = _safe_agent_text(explanation, field="explanation", required=True)
    safe_reproduction = _safe_agent_text_list(reproduction, field="reproduction")
    safe_optimizations = _safe_agent_text_list(
        optimization_candidates,
        field="optimization_candidates",
        required=True,
    )
    safe_next_validation = _safe_agent_text_list(
        next_validation,
        field="next_validation",
        required=True,
    )
    summary_path = diagnostics_path(project_root)
    detail_path = diagnostic_detail_path(project_root, normalized_issue_id)
    directory = _open_detail_directory(project_root, create=False)
    os.close(directory)
    with mutation_transaction(
        project_root,
        "apply-diagnostic-retrospective",
        [summary_path, detail_path],
        undoable=False,
        operation_role="diagnostics",
    ):
        summary = _load_document(project_root)
        issue = next(
            (
                item
                for item in summary["issues"]
                if str(item.get("id") or "") == normalized_issue_id
            ),
            None,
        )
        if issue is None or issue.get("detail_ref") != _detail_ref(normalized_issue_id):
            raise ValueError(f"diagnostic detail not found: {normalized_issue_id}")
        document, old_bytes = _load_detail_document(project_root, normalized_issue_id)
        actual_digest = hashlib.sha256(old_bytes).hexdigest()
        if actual_digest != expected_digest or str(issue.get("detail_digest") or "") != actual_digest:
            raise ValueError("diagnostic detail changed; prepare a fresh retrospective")
        history = document.get("occurrence_history")
        if not isinstance(history, list) or not history or not isinstance(history[-1], dict):
            raise ValueError("diagnostic detail history is invalid")
        current = history[-1]
        root_cause = current.get("root_cause")
        if not isinstance(root_cause, dict) or root_cause.get("status") != "pending":
            raise ValueError("diagnostic retrospective is not pending Agent analysis")
        current["root_cause"] = {
            "status": "hypothesis",
            "reason": "agent-applied",
            "explanation": safe_explanation,
        }
        current["reproduction"] = safe_reproduction
        current["optimization_candidates"] = safe_optimizations
        current["next_validation"] = safe_next_validation
        document["updated_at"] = _now()
        new_bytes = _serialize_detail_document(document)
        _write_detail_bytes(project_root, normalized_issue_id, new_bytes)
        issue["detail_digest"] = hashlib.sha256(new_bytes).hexdigest()
        issue["retrospective_status"] = "hypothesis"
        write_yaml_if_changed(summary_path, summary)
        return {
            "issue_id": normalized_issue_id,
            "detail_digest": issue["detail_digest"],
            "retrospective_status": "hypothesis",
        }


def review_diagnostic_issue(project_root: Path, *, issue_id: str, status: str) -> dict[str, Any]:
    normalized_status = _validated(status, REVIEW_STATUSES, "status")
    path = diagnostics_path(project_root)
    with mutation_transaction(
        project_root,
        "review-diagnostic-issue",
        [path],
        undoable=False,
        operation_role="diagnostics",
    ):
        document = _load_document(project_root)
        for issue in document["issues"]:
            if str(issue.get("id") or "") == str(issue_id or "").strip():
                issue["status"] = normalized_status
                write_yaml_if_changed(path, document)
                return dict(issue)
    raise ValueError(f"diagnostic issue not found: {issue_id}")


def export_diagnostic_preview(
    project_root: Path,
    *,
    authorized: bool = False,
    status: str = "",
    skill: str = "",
) -> dict[str, Any]:
    """Return a redacted, local preview; never writes or uploads anything."""

    if not authorized:
        raise PermissionError("diagnostic export preview requires explicit current-user authorization")
    safe_fields = (
        "id",
        "category",
        "severity",
        "status",
        "skill",
        "summary",
        "expected",
        "actual",
        "trigger",
        "source",
        "reproducible",
        "occurrences",
        "first_seen_at",
        "last_seen_at",
        "bundle_version",
        "source_commit",
        "error_class",
        "failure_stage",
        "privacy_classification",
    )
    issues = []
    for issue in list_diagnostic_issues(project_root, status=status, skill=skill):
        projected: dict[str, Any] = {}
        for field in safe_fields:
            value = issue.get(field, "")
            if field in {"summary", "expected", "actual", "trigger"}:
                projected[field] = redact_diagnostic_text(str(value), limit=300)
            else:
                projected[field] = value
        issues.append(projected)
    return {
        "schema_version": 1,
        "local_only": True,
        "redacted": True,
        "issues": issues,
    }


__all__ = [
    "DETAIL_LEVELS",
    "DETAIL_PRIVACY_CLASSIFICATION",
    "DIAGNOSTIC_MODES",
    "INTAKE_FAILURE_STAGES",
    "PRIVACY_CLASSIFICATION",
    "REVIEW_STATUSES",
    "SEVERITIES",
    "STATUSES",
    "apply_diagnostic_retrospective",
    "capture_runtime_failure",
    "diagnostic_detail_path",
    "diagnostics_path",
    "diagnostics_policy",
    "export_diagnostic_preview",
    "load_diagnostic_detail",
    "list_diagnostic_issues",
    "publish_runtime_failure_stage",
    "record_diagnostic_issue",
    "redact_diagnostic_text",
    "review_diagnostic_issue",
]
