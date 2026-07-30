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
import time
import unicodedata
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .journal import mutation_transaction
from .paths import kb_root
from .prefs import load_runtime_preferences
from .yaml_io import load_yaml, write_yaml_if_changed


DIAGNOSTIC_MODES = {"off", "errors-only", "developer"}
SKILL_MODES = {"inherit", *DIAGNOSTIC_MODES}
SEVERITIES = {"info", "low", "medium", "high", "critical"}
SEVERITY_ORDER = {value: index for index, value in enumerate(("info", "low", "medium", "high", "critical"))}
STATUSES = {"pending", "confirmed", "dismissed", "resolved"}
REVIEW_STATUSES = {"confirmed", "dismissed", "resolved"}
SOURCES = {"user", "agent", "runtime"}
REPRODUCIBLE_VALUES = {"unknown", "yes", "no", "intermittent"}
PRIVACY_CLASSIFICATION = "local-redacted"
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


def diagnostics_path(project_root: Path) -> Path:
    return kb_root(project_root) / "memory" / "skill-evolution" / "issues.yaml"


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
    token_budget = _integer(raw.get("token_budget_per_task"), 0, minimum=0)
    policy = {
        "mode": effective_mode,
        "effective_mode": effective_mode,
        "workspace_mode": workspace_mode,
        "skill": normalized_skill,
        "skill_mode": skill_mode,
        # This is forced rather than trusted from disk in D1.
        "local_only": True,
        "token_budget_per_task": token_budget,
        "max_issues_per_task": _integer(raw.get("max_issues_per_task"), 20, minimum=1),
        "dedup_window_seconds": _integer(raw.get("dedup_window_seconds"), 604800, minimum=0),
        "cooldown_seconds": _integer(raw.get("cooldown_seconds"), 0, minimum=0),
        "automatic_capture": effective_mode in {"errors-only", "developer"},
        "allow_agent_retrospective": effective_mode == "developer" and token_budget > 0,
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
    fingerprint = _fingerprint(
        category=normalized_category,
        skill=normalized_skill,
        summary=safe_summary,
        trigger=safe_trigger,
        error_class=safe_error_class,
    )
    issue_id = f"diag-{fingerprint[:16]}"
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

    with mutation_transaction(
        project_root,
        "record-diagnostic-issue",
        [path],
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
            if mechanical:
                issue.update(mechanical)
            if automatic_failure_stage:
                issue["failure_stage"] = automatic_failure_stage
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
        if mechanical:
            issue.update(mechanical)
        if automatic_failure_stage:
            issue["failure_stage"] = automatic_failure_stage
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
    issue, _ = record_diagnostic_issue(
        project_root,
        category="runtime-failure",
        severity="medium",
        skill=skill,
        summary=summary,
        expected="The operation completes successfully.",
        actual=f"The operation returned nonzero status {int(returncode)}.",
        trigger=operation,
        source="runtime",
        reproducible="unknown",
        error_class=(
            f"owner-nonzero-exit.{failure_stage}"
            if failure_stage
            else "owner-nonzero-exit"
        ),
        _automatic_runtime_metadata=(
            {
                "category": "runtime-failure",
                "owner": skill,
                "operation": operation,
                "return_code": int(returncode),
            }
            if policy.get("governance_profile") == "personal"
            else None
        ),
        _automatic_failure_stage=failure_stage,
        _capture_token=_AUTOMATIC_RUNTIME_CAPTURE,
    )
    return issue


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
    "DIAGNOSTIC_MODES",
    "INTAKE_FAILURE_STAGES",
    "PRIVACY_CLASSIFICATION",
    "REVIEW_STATUSES",
    "SEVERITIES",
    "STATUSES",
    "capture_runtime_failure",
    "diagnostics_path",
    "diagnostics_policy",
    "export_diagnostic_preview",
    "list_diagnostic_issues",
    "publish_runtime_failure_stage",
    "record_diagnostic_issue",
    "redact_diagnostic_text",
    "review_diagnostic_issue",
]
