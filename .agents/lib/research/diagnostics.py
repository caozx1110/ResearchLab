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
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

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


def _redacted_context_reference(value: str) -> str:
    """Retain correlation without persisting free-form/user/evidence text."""

    text = str(value or "")
    if not text.strip():
        return ""
    digest = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    return f"context-sha256:{digest[:16]}"


def diagnostics_policy(project_root: Path, skill: str = "") -> dict[str, Any]:
    """Return a pure-read, normalized effective diagnostics policy."""

    raw = load_runtime_preferences(project_root).get("diagnostics", {})
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

    if int(returncode) == 0 or not diagnostics_policy(project_root, skill).get("automatic_capture"):
        return None
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
        error_class="owner-nonzero-exit",
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
        "privacy_classification",
    )
    return {
        "schema_version": 1,
        "local_only": True,
        "redacted": True,
        "issues": [
            {field: issue.get(field, "") for field in safe_fields}
            for issue in list_diagnostic_issues(project_root, status=status, skill=skill)
        ],
    }


__all__ = [
    "DIAGNOSTIC_MODES",
    "PRIVACY_CLASSIFICATION",
    "REVIEW_STATUSES",
    "SEVERITIES",
    "STATUSES",
    "capture_runtime_failure",
    "diagnostics_path",
    "diagnostics_policy",
    "export_diagnostic_preview",
    "list_diagnostic_issues",
    "record_diagnostic_issue",
    "redact_diagnostic_text",
    "review_diagnostic_issue",
]
