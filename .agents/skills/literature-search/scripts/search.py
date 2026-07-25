#!/usr/bin/env python3
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
import re
import selectors
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence


SCRIPT_PATH = Path(__file__).resolve()
for candidate in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents]:
    lib = candidate / ".agents" / "lib"
    if lib.exists():
        sys.path.insert(0, str(lib))
        PROJECT_ROOT = candidate
        break
else:
    raise SystemExit("Could not locate the managed research runtime.")

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.common import add_project_root_argument, load_yaml
from research.confirm import require_user_authorization
from research.core import locate_record, project_root
from research.journal import journal_subprocess_env
from research.paths import search_stage_path
from research.preference_selection import resolve_operation_preferences
from research.sources import (
    _validate_search_stage_target,
    build_literature_search_stage_id,
    literature_candidate_semantic_digest,
    literature_stage_snapshot,
    load_search_stage,
    resolve_search_candidate,
    stage_search_results,
)
from research.surveys import literature_candidate_identity_digest


MAX_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_SELECTION_PAYLOAD_BYTES = 64 * 1024
MAX_SELECTION_CANDIDATES = 50
MAX_USER_AUTHORIZATION_BYTES = 8 * 1024
MAX_PREFERENCE_SELECTION_ID_BYTES = 256
OWNER_TIMEOUT_SECONDS = 15 * 60
INTAKE_SCRIPT = PROJECT_ROOT / ".agents" / "skills" / "source-intake" / "scripts" / "intake.py"
SELECTION_PAYLOAD_KEYS = {
    "schema",
    "stage_id",
    "candidate_ids",
    "user_authorization",
    "authorization_source",
    "preference_selection_ids",
    "display_binding",
}
SAFE_SELECTION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
SAFE_PROTOCOL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,126}\.json")
ALLOWED_PAYLOAD_KEYS = {
    "request",
    "stage_id",
    "note",
    "mode",
    "run_id",
    "monitor_binding",
    "scope",
    "review_protocol",
    "reviewers",
    "budget",
    "usage",
    "queries",
    "candidates",
    "coverage",
    "frontier",
    "stop",
    "partial",
    "preference_selection_id",
}
SEARCH_STATE_KEYS = {
    "mode",
    "run_id",
    "monitor_binding",
    "scope",
    "review_protocol",
    "reviewers",
    "budget",
    "usage",
    "queries",
    "coverage",
    "frontier",
    "stop",
    "partial",
}
DEFAULT_EXPLORATORY_BUDGET = {
    "max_queries": 8,
    "max_candidates": 50,
    "max_full_reads": 8,
    "max_citation_hops": 6,
}
EMPTY_USAGE = {
    "queries": 0,
    "candidates_seen": 0,
    "full_reads": 0,
    "citation_hops": 0,
    "retryable_failures": 0,
}


class PrivateArgumentParser(argparse.ArgumentParser):
    """Keep malformed private helper calls off the user-facing command surface."""

    def error(self, _message: str) -> None:
        raise SystemExit("Literature helper input is invalid; ask the Agent to inspect its private payload.")


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def literature_search_preference_context(
    payload: dict[str, Any],
    *,
    stage_id: str = "",
    existing: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Return bounded owner-canonical inputs for one search run."""
    frozen = effective_literature_search_inputs(payload, existing=existing)
    return {
        "stage_id": str(stage_id or ""),
        "request_digest": _canonical_digest(frozen["request"]),
        "mode": frozen["mode"],
        "run_id": frozen["run_id"],
        "scope_digest": _canonical_digest(frozen["scope"]),
        "budget_digest": _canonical_digest(frozen["budget"]),
        "review_protocol_digest": _canonical_digest(frozen["review_protocol"]),
        "reviewers_digest": _canonical_digest(frozen["reviewers"]),
        "monitor_binding_digest": _canonical_digest(frozen["monitor_binding"]),
    }


def effective_literature_search_inputs(
    payload: dict[str, Any],
    *,
    existing: dict[str, Any] | None = None,
) -> dict[str, object]:
    """Resolve the frozen search contract used by both initial and resume calls."""
    current = (
        existing
        if isinstance(existing, dict)
        and existing.get("id")
        and existing.get("entry_skill") == "literature-search"
        else {}
    )

    def chosen(key: str, default: object) -> object:
        if key in payload:
            return payload[key]
        if key in current:
            return current[key]
        return default

    request = " ".join(str(payload.get("request") or "").split())
    raw_mode = chosen("mode", "exploratory")
    raw_run_id = chosen("run_id", "")
    scope = chosen("scope", {})
    review_protocol = chosen("review_protocol", {})
    reviewers = chosen("reviewers", [])
    monitor_binding = chosen("monitor_binding", {})
    incoming_budget = payload.get("budget") if "budget" in payload else None
    existing_budget = current.get("budget") if isinstance(current.get("budget"), dict) else {}
    if incoming_budget is not None and not isinstance(incoming_budget, dict):
        raise SystemExit("Literature search budget must be a mapping.")
    budget = {
        **DEFAULT_EXPLORATORY_BUDGET,
        **existing_budget,
        **(incoming_budget or {}),
    }
    if not isinstance(raw_mode, str):
        raise SystemExit("Literature search mode must be text.")
    if not isinstance(raw_run_id, str):
        raise SystemExit("Literature search run_id must be text.")
    if not isinstance(scope, dict):
        raise SystemExit("Literature search scope must be a mapping.")
    if not isinstance(review_protocol, dict):
        raise SystemExit("Literature search review_protocol must be a mapping.")
    if not isinstance(reviewers, list):
        raise SystemExit("Literature search reviewers must be a list.")
    if not isinstance(monitor_binding, dict):
        raise SystemExit("Literature search monitor_binding must be a mapping.")
    return {
        "request": request,
        "mode": raw_mode.strip() or "exploratory",
        "run_id": raw_run_id.strip(),
        "scope": scope,
        "budget": budget,
        "review_protocol": review_protocol,
        "reviewers": reviewers,
        "monitor_binding": monitor_binding,
    }


def resolve_literature_search_preferences(
    root: Path,
    payload: dict[str, Any],
    *,
    stage_id: str = "",
    existing: dict[str, Any] | None = None,
) -> dict[str, object]:
    selection_id = payload.get("preference_selection_id", "")
    if not isinstance(selection_id, str):
        raise SystemExit("Literature search preference selection id must be text.")
    try:
        return resolve_operation_preferences(
            root,
            selection_id=selection_id,
            skill="literature-search",
            operation="search",
            canonical_inputs=literature_search_preference_context(
                payload,
                stage_id=stage_id,
                existing=existing,
            ),
        )
    except ValueError as exc:
        raise SystemExit(f"Literature search preference selection is invalid: {exc}") from exc


def _load_payload(path: Path) -> dict[str, Any]:
    try:
        stat = path.lstat()
    except OSError:
        raise SystemExit("Literature search staging input could not be read.") from None
    if path.is_symlink() or not path.is_file() or stat.st_size > MAX_PAYLOAD_BYTES:
        raise SystemExit("Literature search staging input must be a bounded regular JSON file.")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise SystemExit("Literature search staging input is not valid JSON.") from None
    if not isinstance(payload, dict):
        raise SystemExit("Literature search staging input must be a JSON object.")
    unknown = sorted(set(payload) - ALLOWED_PAYLOAD_KEYS)
    if unknown:
        raise SystemExit("Literature search staging input contains unsupported fields.")
    return payload


def _read_bounded_regular_json(path: Path, *, limit: int, label: str) -> dict[str, Any]:
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NONBLOCK", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError:
        raise SystemExit(f"{label} must be a bounded regular JSON file.") from None
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode) or metadata.st_size > limit:
            raise SystemExit(f"{label} must be a bounded regular JSON file.")
        chunks: list[bytes] = []
        remaining = limit + 1
        while remaining > 0:
            chunk = os.read(descriptor, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        data = b"".join(chunks)
        after = os.fstat(descriptor)
        if (
            len(data) > limit
            or len(data) != metadata.st_size
            or (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns)
            != (
                metadata.st_dev,
                metadata.st_ino,
                metadata.st_size,
                metadata.st_mtime_ns,
                metadata.st_ctime_ns,
            )
        ):
            raise SystemExit(f"{label} changed while it was read.")
    finally:
        os.close(descriptor)
    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON object key")
            result[key] = value
        return result

    try:
        payload = json.loads(data.decode("utf-8"), object_pairs_hook=unique_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise SystemExit(f"{label} is not valid JSON.") from None
    if not isinstance(payload, dict):
        raise SystemExit(f"{label} must be a JSON object.")
    return payload


def _load_selection_payload(path: Path) -> dict[str, Any]:
    payload = _read_bounded_regular_json(
        path,
        limit=MAX_SELECTION_PAYLOAD_BYTES,
        label="Literature selection input",
    )
    if set(payload) - SELECTION_PAYLOAD_KEYS:
        raise SystemExit("Literature selection input contains unsupported fields.")
    return payload


def _literature_stage_digest(root: Path, stage_id: str) -> str:
    return str(literature_stage_snapshot(root, stage_id)["byte_sha256"])


def _candidate_semantic_digest(candidate: Mapping[str, object]) -> str:
    return literature_candidate_semantic_digest(candidate)


def _valid_candidate_update_event(
    event: object,
    *,
    candidate_id: str,
    status: str,
) -> bool:
    if not isinstance(event, dict) or set(event) != {"timestamp", "action", "summary"}:
        return False
    if event.get("action") != "candidate-updated" or event.get("summary") != f"{candidate_id} -> {status}":
        return False
    timestamp = str(event.get("timestamp") or "")
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _valid_owner_stage_transition(
    before: Mapping[str, object],
    after: Mapping[str, object],
    *,
    candidate_id: str,
    status: str,
    record_id: str,
) -> bool:
    """Allow exactly source-intake's marker update and one canonical history event."""
    expected = copy.deepcopy(dict(before))
    candidates = expected.get("candidates")
    if not isinstance(candidates, list):
        return False
    matches = [
        candidate
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("candidate_id") == candidate_id
    ]
    if len(matches) != 1:
        return False
    matches[0]["status"] = status
    matches[0]["record_id"] = record_id
    before_history = expected.get("history")
    if not isinstance(before_history, list):
        return False
    after_history = after.get("history")
    if (
        not isinstance(after_history, list)
        or len(after_history) != len(before_history) + 1
        or after_history[:-1] != before_history
        or not _valid_candidate_update_event(
            after_history[-1],
            candidate_id=candidate_id,
            status=status,
        )
    ):
        return False
    expected["history"] = copy.deepcopy(after_history)
    return expected == dict(after)


def _candidate_screening_decision(candidate: Mapping[str, object]) -> str:
    effective = candidate.get("effective_screening")
    screening = effective if isinstance(effective, dict) else candidate.get("screening")
    if not isinstance(screening, dict):
        return ""
    return str(screening.get("decision") or "").strip()


def _selection_receipt_record_id(
    root: Path,
    *,
    stage_id: str,
    candidate: Mapping[str, object],
    user_authorization: str,
    preference_selection_id: str = "",
) -> str:
    status = str(candidate.get("status") or "")
    record_id = str(candidate.get("record_id") or "").strip()
    if status not in {"materialized", "duplicate"} or not record_id:
        return ""
    try:
        record, _path = locate_record(root, record_id, kind="paper", fuzzy=False)
    except (OSError, SystemExit, ValueError):
        return ""
    if (
        str(record.get("status") or "").strip().lower()
        in {"failed", "failed_retryable", "rejected"}
        or str(record.get("confirmation_status") or "").strip().lower() == "rejected"
    ):
        return ""
    payload = record.get("payload", {})
    if not isinstance(payload, dict):
        return ""
    source_search = payload.get("source_search", {})
    if not isinstance(source_search, dict):
        return ""
    expected = {
        "stage_id": stage_id,
        "candidate_id": str(candidate.get("candidate_id") or ""),
        "candidate_identity_digest": literature_candidate_identity_digest(dict(candidate)),
        "user_authorization": user_authorization,
        "authorization_source": "user_message",
    }
    selections = source_search.get("selections")
    if not isinstance(selections, list) or expected not in selections:
        return ""
    if preference_selection_id:
        direct = payload.get("preference_binding")
        direct_id = (
            str(direct.get("selection_id") or "") if isinstance(direct, dict) else ""
        )
        nested_ids = {
            str(item.get("selection_binding", {}).get("selection_id") or "")
            for item in source_search.get("preference_bindings", [])
            if isinstance(item, dict)
            and item.get("stage_id") == stage_id
            and item.get("candidate_id") == str(candidate.get("candidate_id") or "")
            and isinstance(item.get("selection_binding"), dict)
        }
        if preference_selection_id != direct_id and preference_selection_id not in nested_ids:
            return ""
    return record_id


def _validate_selection_payload(root: Path, payload: Mapping[str, object]) -> dict[str, object]:
    if set(payload) != SELECTION_PAYLOAD_KEYS:
        raise SystemExit("Literature selection input contains unsupported fields.")
    if payload.get("schema") != "literature-selection/v2":
        raise SystemExit("Literature selection input has an unsupported schema.")
    stage_id = payload.get("stage_id")
    if not isinstance(stage_id, str) or SAFE_SELECTION_ID.fullmatch(stage_id) is None:
        raise SystemExit("Literature selection stage id is invalid.")
    raw_candidate_ids = payload.get("candidate_ids")
    if not isinstance(raw_candidate_ids, list) or not raw_candidate_ids:
        raise SystemExit("Literature selection candidate list must not be empty.")
    if len(raw_candidate_ids) > MAX_SELECTION_CANDIDATES:
        raise SystemExit("Literature selection candidate list is too large.")
    if any(
        not isinstance(item, str) or SAFE_SELECTION_ID.fullmatch(item) is None
        for item in raw_candidate_ids
    ):
        raise SystemExit("Literature selection candidate id is invalid.")
    candidate_ids = list(raw_candidate_ids)
    if len(set(candidate_ids)) != len(candidate_ids):
        raise SystemExit("Literature selection candidate ids must be unique.")
    user_authorization = payload.get("user_authorization")
    authorization_source = payload.get("authorization_source")
    if not isinstance(user_authorization, str) or not isinstance(authorization_source, str):
        raise SystemExit("Literature selection authorization is invalid.")
    if "\x00" in user_authorization or len(user_authorization.encode("utf-8")) > MAX_USER_AUTHORIZATION_BYTES:
        raise SystemExit("Literature selection authorization is invalid or too large.")
    try:
        authorization, source = require_user_authorization(
            user_authorization=user_authorization,
            authorization_source=authorization_source,
        )
    except SystemExit as exc:
        raise SystemExit("Literature selection authorization is missing or invalid.") from exc
    raw_preferences = payload.get("preference_selection_ids", {})
    if not isinstance(raw_preferences, dict) or set(raw_preferences) - set(candidate_ids):
        raise SystemExit("Literature selection preference bindings are invalid.")
    preferences: dict[str, str] = {}
    for candidate_id, selection_id in raw_preferences.items():
        if (
            not isinstance(selection_id, str)
            or not selection_id
            or len(selection_id.encode("utf-8")) > MAX_PREFERENCE_SELECTION_ID_BYTES
            or SAFE_SELECTION_ID.fullmatch(selection_id) is None
        ):
            raise SystemExit("Literature selection preference binding is invalid.")
        preferences[str(candidate_id)] = selection_id

    display_binding = payload.get("display_binding")
    if not isinstance(display_binding, dict) or set(display_binding) != {
        "stage_byte_sha256",
        "candidate_bindings",
    }:
        raise SystemExit("Literature selection display binding is invalid.")
    displayed_stage_digest = display_binding.get("stage_byte_sha256")
    displayed_candidates = display_binding.get("candidate_bindings")
    if (
        not isinstance(displayed_stage_digest, str)
        or re.fullmatch(r"[0-9a-f]{64}", displayed_stage_digest) is None
        or not isinstance(displayed_candidates, list)
        or len(displayed_candidates) != len(candidate_ids)
    ):
        raise SystemExit("Literature selection display binding is invalid.")
    normalized_displayed: list[dict[str, str]] = []
    for index, raw_binding in enumerate(displayed_candidates):
        if not isinstance(raw_binding, dict) or set(raw_binding) != {
            "candidate_id",
            "identity_digest",
            "semantic_digest",
        }:
            raise SystemExit("Literature selection display candidate binding is invalid.")
        normalized = {key: str(raw_binding.get(key) or "") for key in raw_binding}
        if (
            normalized["candidate_id"] != candidate_ids[index]
            or re.fullmatch(r"[0-9a-f]{64}", normalized["identity_digest"]) is None
            or re.fullmatch(r"[0-9a-f]{64}", normalized["semantic_digest"]) is None
        ):
            raise SystemExit("Literature selection display candidate binding is invalid.")
        normalized_displayed.append(normalized)

    try:
        snapshot = literature_stage_snapshot(root, stage_id)
    except SystemExit as exc:
        raise SystemExit("Literature selection stage does not exist or is unsafe.") from exc
    stage = dict(snapshot["payload"])
    stage_digest = str(snapshot["byte_sha256"])
    if stage.get("entry_skill") != "literature-search" or stage.get("source_kind") != "paper":
        raise SystemExit("Literature selection stage is not owned by literature-search.")
    stop = stage.get("stop") if isinstance(stage.get("stop"), dict) else {}
    if str(stop.get("reason") or "") in {"", "in_progress", "blocked", "blocked_no_search_tool"}:
        raise SystemExit("Literature selection stage is not ready for a user choice.")

    candidates: list[dict[str, object]] = []
    already_materialized: dict[str, str] = {}
    stage_candidates = stage.get("candidates")
    if not isinstance(stage_candidates, list):
        raise SystemExit("Literature selection stage is invalid.")
    for index, candidate_id in enumerate(candidate_ids):
        matches = [
            dict(item)
            for item in stage_candidates
            if isinstance(item, dict) and item.get("candidate_id") == candidate_id
        ]
        if len(matches) != 1:
            raise SystemExit("Literature selection candidate does not exist in this stage.")
        candidate = matches[0]
        displayed = normalized_displayed[index]
        if (
            literature_candidate_identity_digest(candidate) != displayed["identity_digest"]
            or literature_candidate_semantic_digest(candidate) != displayed["semantic_digest"]
        ):
            raise SystemExit("Literature selection display candidate changed after it was shown.")
        if _candidate_screening_decision(candidate) not in {"include", "maybe"}:
            raise SystemExit("Literature selection candidate is not eligible for materialization.")
        status = str(candidate.get("status") or "")
        if status in {"materialized", "duplicate"}:
            record_id = _selection_receipt_record_id(
                root,
                stage_id=stage_id,
                candidate=candidate,
                user_authorization=authorization,
                preference_selection_id=str(preferences.get(candidate_id) or ""),
            )
            if not record_id:
                raise SystemExit("Literature selection candidate has an invalid materialization binding.")
            already_materialized[candidate_id] = record_id
        candidates.append(
            {
                "candidate_id": candidate_id,
                "identity_digest": literature_candidate_identity_digest(candidate),
                "semantic_digest": literature_candidate_semantic_digest(candidate),
            }
        )
    if stage_digest != displayed_stage_digest and len(already_materialized) != len(candidate_ids):
        raise SystemExit("Literature selection display changed after it was shown to the user.")
    authorization_digest = _canonical_digest(
        {"user_authorization": authorization, "authorization_source": source}
    )
    selection_binding = {
        "stage_id": stage_id,
        "initial_stage_digest": stage_digest,
        "candidate_bindings": candidates,
        "authorization_digest": authorization_digest,
        "preference_selection_ids": preferences,
    }
    selection_binding["selection_digest"] = _canonical_digest(selection_binding)
    return {
        "stage_id": stage_id,
        "candidate_ids": candidate_ids,
        "user_authorization": authorization,
        "authorization_source": source,
        "preference_selection_ids": preferences,
        "selection_binding": selection_binding,
        "already_materialized": already_materialized,
        "_initial_stage_snapshot": copy.deepcopy(stage),
    }


def _protocol_path_preflight(root: Path, requested: str) -> str:
    if not isinstance(requested, str) or SAFE_PROTOCOL_NAME.fullmatch(requested) is None:
        raise SystemExit("Literature selection protocol name is invalid.")
    cursor = root
    for component in ("kb", ".runtime", "literature-selection"):
        cursor = cursor / component
        try:
            metadata = cursor.lstat()
        except FileNotFoundError:
            break
        except OSError as exc:
            raise SystemExit("Literature selection protocol destination is unsafe.") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
            raise SystemExit("Literature selection protocol destination is unsafe.")
    path = root / "kb" / ".runtime" / "literature-selection" / requested
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return requested
    except OSError as exc:
        raise SystemExit("Literature selection protocol destination is unsafe.") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SystemExit("Literature selection protocol destination is unsafe.")
    raise SystemExit("Literature selection protocol name has already been used.")


def _open_protocol_directory(root: Path) -> int:
    flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(root, flags)
    except OSError as exc:
        raise SystemExit("Literature selection protocol workspace is unsafe.") from exc
    try:
        for component in ("kb", ".runtime", "literature-selection"):
            try:
                metadata = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
            except FileNotFoundError:
                os.mkdir(component, mode=0o700, dir_fd=descriptor)
                os.fsync(descriptor)
                metadata = os.stat(component, dir_fd=descriptor, follow_symlinks=False)
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise SystemExit("Literature selection protocol destination is unsafe.")
            child = os.open(component, flags, dir_fd=descriptor)
            if (os.fstat(child).st_dev, os.fstat(child).st_ino) != (metadata.st_dev, metadata.st_ino):
                os.close(child)
                raise SystemExit("Literature selection protocol destination changed.")
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _write_protocol_bytes_exclusive(root: Path, name: str, data: bytes) -> int:
    directory_fd = _open_protocol_directory(root)
    flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = -1
    try:
        try:
            descriptor = os.open(name, flags, 0o600, dir_fd=directory_fd)
        except FileExistsError as exc:
            raise SystemExit("Literature selection protocol name has already been used.") from exc
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short protocol write")
            view = view[written:]
        os.fsync(descriptor)
        os.fsync(directory_fd)
        claimed_descriptor = descriptor
        descriptor = -1
        return claimed_descriptor
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(directory_fd)


def _claim_selection_protocol(
    root: Path,
    name: str,
    *,
    selection_digest: str,
) -> tuple[str, bytes, int]:
    name = _protocol_path_preflight(root, name)
    claim_token = os.urandom(32).hex()
    claim = {
        "schema": "literature-selection-owner-adapter/v1",
        "status": "in_progress",
        "claim_token": claim_token,
        "selection_digest": selection_digest,
    }
    data = (json.dumps(claim, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    claim_fd = _write_protocol_bytes_exclusive(root, name, data)
    return claim_token, data, claim_fd


def _finalize_selection_protocol(
    root: Path,
    name: str,
    payload: Mapping[str, object],
    *,
    claim_token: str,
    claim_bytes: bytes,
    claim_fd: int,
) -> None:
    if not re.fullmatch(r"[0-9a-f]{64}", claim_token):
        raise SystemExit("Literature selection protocol claim is invalid.")
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )
    directory_fd = _open_protocol_directory(root)
    temporary = f".{name}.{os.getpid()}.{os.urandom(8).hex()}.tmp"
    read_flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    write_flags = (
        os.O_WRONLY
        | os.O_CREAT
        | os.O_EXCL
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    descriptor = -1
    try:
        claim_metadata = os.fstat(claim_fd)
        if (
            not stat.S_ISREG(claim_metadata.st_mode)
            or claim_metadata.st_size != len(claim_bytes)
        ):
            raise SystemExit("Literature selection protocol claim changed before completion.")
        descriptor = os.open(temporary, write_flags, 0o600, dir_fd=directory_fd)
        view = memoryview(data)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise OSError("short protocol write")
            view = view[written:]
        os.fsync(descriptor)
        # POSIX has no portable compare-and-swap rename.  Keep both inode
        # descriptors open and make the cooperative single-name contract
        # explicit: revalidate the visible claim immediately before rename,
        # then prove the published name is the fsynced temp inode immediately
        # afterwards.  A hostile writer with unlink permission can still race
        # inside that final syscall-sized window; detection remains fail-closed.
        visible_fd = -1
        try:
            visible_fd = os.open(name, read_flags, dir_fd=directory_fd)
            visible_metadata = os.fstat(visible_fd)
            visible_bytes = os.read(visible_fd, len(claim_bytes) + 1)
            current_claim_metadata = os.fstat(claim_fd)
            identity = lambda item: (
                item.st_dev,
                item.st_ino,
                item.st_mode,
                item.st_size,
                item.st_mtime_ns,
                item.st_ctime_ns,
            )
            if (
                identity(visible_metadata) != identity(claim_metadata)
                or identity(current_claim_metadata) != identity(claim_metadata)
                or visible_bytes != claim_bytes
            ):
                raise SystemExit("Literature selection protocol claim changed before completion.")
        except OSError as exc:
            raise SystemExit("Literature selection protocol claim changed before completion.") from exc
        finally:
            if visible_fd >= 0:
                os.close(visible_fd)
        os.replace(temporary, name, src_dir_fd=directory_fd, dst_dir_fd=directory_fd)
        published_fd = -1
        try:
            published_fd = os.open(name, read_flags, dir_fd=directory_fd)
            published_metadata = os.fstat(published_fd)
            temp_metadata = os.fstat(descriptor)
            if identity(published_metadata) != identity(temp_metadata):
                raise SystemExit("Literature selection protocol publication changed unexpectedly.")
        except OSError as exc:
            raise SystemExit("Literature selection protocol publication changed unexpectedly.") from exc
        finally:
            if published_fd >= 0:
                os.close(published_fd)
        os.fsync(directory_fd)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        try:
            os.unlink(temporary, dir_fd=directory_fd)
        except FileNotFoundError:
            pass
        os.close(directory_fd)


def _owner_stream_metadata(value: object) -> dict[str, object]:
    if isinstance(value, Mapping) and set(value) == {"bytes", "lines", "sha256"}:
        total = value.get("bytes")
        lines = value.get("lines")
        digest = value.get("sha256")
        if (
            isinstance(total, int)
            and total >= 0
            and isinstance(lines, int)
            and lines >= 0
            and isinstance(digest, str)
            and re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            return {"bytes": total, "lines": lines, "sha256": digest}
    if isinstance(value, bytes):
        data = value
    elif isinstance(value, str):
        data = value.encode("utf-8", errors="replace")
    else:
        data = b""
    return {
        "bytes": len(data),
        "lines": len(data.splitlines()),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _default_owner_runner(
    argv: Sequence[str],
    *,
    env: Mapping[str, str],
) -> subprocess.CompletedProcess[bytes]:
    process = subprocess.Popen(
        list(argv),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=dict(env),
        start_new_session=True,
    )
    streams = {
        process.stdout: {
            "bytes": 0,
            "lines": 0,
            "sha256": hashlib.sha256(),
            "last": b"",
        },
        process.stderr: {
            "bytes": 0,
            "lines": 0,
            "sha256": hashlib.sha256(),
            "last": b"",
        },
    }
    selector = selectors.DefaultSelector()
    for stream in streams:
        if stream is not None:
            selector.register(stream, selectors.EVENT_READ)
    deadline = time.monotonic() + OWNER_TIMEOUT_SECONDS
    timed_out = False
    try:
        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0 and not timed_out:
                timed_out = True
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except (OSError, ProcessLookupError):
                    process.kill()
            events = selector.select(0.25 if timed_out else min(0.25, max(remaining, 0.0)))
            for key, _mask in events:
                stream = key.fileobj
                chunk = os.read(stream.fileno(), 64 * 1024)
                if not chunk:
                    selector.unregister(stream)
                    stream.close()
                    continue
                state = streams[stream]
                state["bytes"] = int(state["bytes"]) + len(chunk)
                state["lines"] = int(state["lines"]) + chunk.count(b"\n")
                state["sha256"].update(chunk)
                state["last"] = chunk[-1:]
        returncode = process.wait()
    finally:
        selector.close()
        if process.poll() is None:
            process.kill()
            process.wait()

    def finalized(stream: object) -> dict[str, object]:
        state = streams[stream]
        line_count = int(state["lines"])
        if int(state["bytes"]) and state["last"] != b"\n":
            line_count += 1
        return {
            "bytes": int(state["bytes"]),
            "lines": line_count,
            "sha256": state["sha256"].hexdigest(),
        }

    return subprocess.CompletedProcess(
        list(argv),
        124 if timed_out else returncode,
        stdout=finalized(process.stdout),
        stderr=finalized(process.stderr),
    )


def _owner_argv(
    root: Path,
    *,
    stage_id: str,
    candidate_id: str,
    user_authorization: str,
    expected_stage_digest: str,
    preference_selection_id: str = "",
) -> tuple[str, ...]:
    argv = [
        sys.executable,
        os.fspath(INTAKE_SCRIPT),
        "--root",
        os.fspath(root),
        "add",
        "--kind",
        "paper",
        "--stage-id",
        stage_id,
        "--candidate-id",
        candidate_id,
        "--user-authorization",
        user_authorization,
        "--authorization-source",
        "user_message",
        "--expected-literature-stage-digest",
        expected_stage_digest,
    ]
    if preference_selection_id:
        argv.extend(["--preference-selection-id", preference_selection_id])
    return tuple(argv)


def materialize_selection(
    root: Path,
    payload: Mapping[str, object],
    *,
    protocol_name: str,
    owner_runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
) -> dict[str, object]:
    protocol_name = _protocol_path_preflight(root, protocol_name)
    bound = _validate_selection_payload(root, payload)
    claim_token, claim_bytes, claim_fd = _claim_selection_protocol(
        root,
        protocol_name,
        selection_digest=str(bound["selection_binding"]["selection_digest"]),
    )
    try:
        return _materialize_claimed_selection(
            root,
            bound,
            protocol_name=protocol_name,
            claim_token=claim_token,
            claim_bytes=claim_bytes,
            claim_fd=claim_fd,
            owner_runner=owner_runner,
        )
    finally:
        os.close(claim_fd)


def _materialize_claimed_selection(
    root: Path,
    bound: Mapping[str, object],
    *,
    protocol_name: str,
    claim_token: str,
    claim_bytes: bytes,
    claim_fd: int,
    owner_runner: Callable[..., subprocess.CompletedProcess[bytes]] | None = None,
) -> dict[str, object]:
    runner = owner_runner or _default_owner_runner
    stage_id = str(bound["stage_id"])
    authorization = str(bound["user_authorization"])
    preferences = dict(bound["preference_selection_ids"])
    candidate_bindings = {
        str(item["candidate_id"]): dict(item)
        for item in bound["selection_binding"]["candidate_bindings"]
    }
    counts = {
        "selected": len(bound["candidate_ids"]),
        "newly_materialized": 0,
        "duplicate": 0,
        "already_materialized": 0,
        "failed": 0,
    }
    owner_results: list[dict[str, object]] = []
    stop_remaining = False
    integrity_failure = False
    expected_stage_digest = str(bound["selection_binding"]["initial_stage_digest"])
    expected_stage_snapshot = copy.deepcopy(bound["_initial_stage_snapshot"])
    for candidate_id in bound["candidate_ids"]:
        candidate_id = str(candidate_id)
        existing_record_id = dict(bound["already_materialized"]).get(candidate_id, "")
        if stop_remaining:
            state = "not_attempted_after_binding_change"
            record_id = ""
            if existing_record_id:
                state = "already_materialized_before_binding_change"
                record_id = existing_record_id
                counts["already_materialized"] += 1
            else:
                counts["failed"] += 1
            owner_results.append(
                {
                    "candidate_id": candidate_id,
                    "state": state,
                    "record_id": record_id,
                    "returncode": 0 if existing_record_id else 1,
                    "stdout_bytes": 0,
                    "stdout_lines": 0,
                    "stdout_sha256": hashlib.sha256(b"").hexdigest(),
                    "stderr_bytes": 0,
                    "stderr_lines": 0,
                    "stderr_sha256": hashlib.sha256(b"").hexdigest(),
                    "before_stage_digest": "",
                    "after_stage_digest": "",
                }
            )
            continue
        try:
            current_snapshot = literature_stage_snapshot(root, stage_id)
            current_stage = dict(current_snapshot["payload"])
            before_stage_digest = str(current_snapshot["byte_sha256"])
            if (
                before_stage_digest != expected_stage_digest
                or current_stage != expected_stage_snapshot
            ):
                raise RuntimeError("whole stage binding changed")
            matches = [
                item
                for item in current_stage.get("candidates", [])
                if isinstance(item, dict) and item.get("candidate_id") == candidate_id
            ]
            if len(matches) != 1:
                raise RuntimeError("candidate identity is ambiguous")
            current_candidate = dict(matches[0])
            expected_binding = candidate_bindings[candidate_id]
            if (
                literature_candidate_identity_digest(current_candidate)
                != expected_binding["identity_digest"]
                or _candidate_semantic_digest(current_candidate) != expected_binding["semantic_digest"]
            ):
                raise RuntimeError("selection binding changed")
        except (OSError, RuntimeError, SystemExit, ValueError):
            state = "selection_binding_changed"
            record_id = ""
            if existing_record_id:
                state = "already_materialized_stage_binding_changed"
                record_id = existing_record_id
                counts["already_materialized"] += 1
            else:
                counts["failed"] += 1
            integrity_failure = True
            stop_remaining = True
            owner_results.append(
                {
                    "candidate_id": candidate_id,
                    "state": state,
                    "record_id": record_id,
                    "returncode": 0 if existing_record_id else 1,
                    "stdout_bytes": 0,
                    "stdout_lines": 0,
                    "stdout_sha256": hashlib.sha256(b"").hexdigest(),
                    "stderr_bytes": 0,
                    "stderr_lines": 0,
                    "stderr_sha256": hashlib.sha256(b"").hexdigest(),
                    "before_stage_digest": "",
                    "after_stage_digest": "",
                }
            )
            continue
        if existing_record_id:
            counts["already_materialized"] += 1
            owner_results.append(
                {
                    "candidate_id": candidate_id,
                    "state": "already_materialized",
                    "record_id": existing_record_id,
                    "returncode": 0,
                    "stdout_bytes": 0,
                    "stdout_lines": 0,
                    "stdout_sha256": hashlib.sha256(b"").hexdigest(),
                    "stderr_bytes": 0,
                    "stderr_lines": 0,
                    "stderr_sha256": hashlib.sha256(b"").hexdigest(),
                    "before_stage_digest": before_stage_digest,
                    "after_stage_digest": before_stage_digest,
                }
            )
            continue
        argv = _owner_argv(
            root,
            stage_id=stage_id,
            candidate_id=candidate_id,
            user_authorization=authorization,
            expected_stage_digest=before_stage_digest,
            preference_selection_id=str(preferences.get(candidate_id) or ""),
        )
        environment = dict(os.environ)
        environment.update(journal_subprocess_env(root))
        environment["RESEARCH_INGEST_CHAIN"] = "1"
        try:
            child = runner(argv, env=environment)
            returncode = int(child.returncode)
            stdout = _owner_stream_metadata(child.stdout)
            stderr = _owner_stream_metadata(child.stderr)
        except BaseException as exc:  # owner diagnostics remain private and value-free
            if isinstance(exc, (KeyboardInterrupt, GeneratorExit)):
                raise
            returncode = 1
            stdout = _owner_stream_metadata(b"")
            stderr = _owner_stream_metadata(exc.__class__.__name__)
        result = {
            "candidate_id": candidate_id,
            "state": "owner_failed",
            "record_id": "",
            "returncode": returncode,
            "stdout_bytes": stdout["bytes"],
            "stdout_lines": stdout["lines"],
            "stdout_sha256": stdout["sha256"],
            "stderr_bytes": stderr["bytes"],
            "stderr_lines": stderr["lines"],
            "stderr_sha256": stderr["sha256"],
            "before_stage_digest": before_stage_digest,
            "after_stage_digest": "",
        }
        try:
            after_snapshot = literature_stage_snapshot(root, stage_id)
            after_stage = dict(after_snapshot["payload"])
            after_stage_digest = str(after_snapshot["byte_sha256"])
            result["after_stage_digest"] = after_stage_digest
            matches = [
                item
                for item in after_stage.get("candidates", [])
                if isinstance(item, dict) and item.get("candidate_id") == candidate_id
            ]
            if len(matches) != 1:
                raise RuntimeError("owner candidate result is ambiguous")
            after_candidate = dict(matches[0])
            state = str(after_candidate.get("status") or "")
            record_id = _selection_receipt_record_id(
                root,
                stage_id=stage_id,
                candidate=after_candidate,
                user_authorization=authorization,
                preference_selection_id=str(preferences.get(candidate_id) or ""),
            )
            canonical_commit = (
                state in {"materialized", "duplicate"}
                and bool(record_id)
                and literature_candidate_identity_digest(after_candidate)
                == expected_binding["identity_digest"]
                and _candidate_semantic_digest(after_candidate)
                == expected_binding["semantic_digest"]
                and _valid_owner_stage_transition(
                    current_stage,
                    after_stage,
                    candidate_id=candidate_id,
                    status=state,
                    record_id=record_id,
                )
            )
            if canonical_commit:
                result["state"] = state
                result["record_id"] = record_id
                counts["newly_materialized" if state == "materialized" else "duplicate"] += 1
                expected_stage_digest = after_stage_digest
                expected_stage_snapshot = copy.deepcopy(after_stage)
            elif (
                state in {"materialized", "duplicate"}
                and bool(record_id)
                and literature_candidate_identity_digest(after_candidate)
                == expected_binding["identity_digest"]
                and _candidate_semantic_digest(after_candidate)
                == expected_binding["semantic_digest"]
            ):
                result["state"] = f"{state}_stage_binding_changed"
                result["record_id"] = record_id
                counts["newly_materialized" if state == "materialized" else "duplicate"] += 1
                integrity_failure = True
                stop_remaining = True
            elif after_stage_digest == before_stage_digest and after_stage == current_stage:
                counts["failed"] += 1
                result["state"] = "owner_failed" if returncode else "owner_result_invalid"
            else:
                counts["failed"] += 1
                result["state"] = "stage_binding_changed"
                integrity_failure = True
                stop_remaining = True
        except (OSError, RuntimeError, SystemExit, ValueError):
            counts["failed"] += 1
            result["state"] = "owner_result_invalid"
            integrity_failure = True
            stop_remaining = True
        owner_results.append(result)

    successful = (
        counts["newly_materialized"] + counts["duplicate"] + counts["already_materialized"]
    )
    exit_code = 0 if counts["failed"] == 0 and not integrity_failure else 1
    if exit_code == 0:
        public_message = (
            f"已按你的选择处理 {counts['selected']} 个文献候选：新入库 {counts['newly_materialized']} 个、"
            f"关联已有条目 {counts['duplicate']} 个、此前已完成 {counts['already_materialized']} 个。"
            "接下来可用 kb next 继续分析。"
        )
        status = "completed"
    elif integrity_failure:
        public_message = (
            f"本次共处理 {counts['selected']} 个文献候选：成功 {successful} 个，失败 {counts['failed']} 个。"
            "处理中检测到检索结果已发生变化；已完成的结果保持有效，其余项目请让 Agent 重新核对后继续。"
        )
        status = "partial_failure" if successful else "failed"
    else:
        public_message = (
            f"本次共处理 {counts['selected']} 个文献候选：成功 {successful} 个，失败 {counts['failed']} 个。"
            "已完成的结果保持有效；失败项可以安全重试，请让 Agent 查看私有结果后继续。"
        )
        status = "partial_failure" if successful else "failed"
    protocol = {
        "schema": "literature-selection-owner-adapter/v1",
        "status": status,
        "exit_code": exit_code,
        "integrity_failure": integrity_failure,
        "selection_binding": bound["selection_binding"],
        "counts": counts,
        "owner_results": owner_results,
        "next_route": {
            "owner": "paper-analyst",
            "action": "analyze-materialized-records",
            "record_ids": sorted(
                {
                    str(item.get("record_id") or "")
                    for item in owner_results
                    if str(item.get("record_id") or "")
                }
            ),
        },
    }
    try:
        _finalize_selection_protocol(
            root,
            protocol_name,
            protocol,
            claim_token=claim_token,
            claim_bytes=claim_bytes,
            claim_fd=claim_fd,
        )
    except SystemExit:
        raise
    except Exception as exc:
        raise SystemExit("Literature selection private result could not be saved safely.") from exc
    return {"exit_code": exit_code, "counts": counts, "public_message": public_message}


def stage_payload(root: Path, payload: dict[str, Any]) -> Path:
    if not isinstance(payload.get("request"), str):
        raise SystemExit("Literature search requires a textual original research question.")
    request = " ".join(payload["request"].split())
    if not request:
        raise SystemExit("Literature search requires an original research question.")
    note = payload.get("note", "")
    if not isinstance(note, str):
        raise SystemExit("Literature search note must be text.")
    candidates = payload.get("candidates", [])
    if not isinstance(candidates, list):
        raise SystemExit("Literature search candidates must be a list.")
    explicit_stage_id = payload.get("stage_id", "")
    if not isinstance(explicit_stage_id, str):
        raise SystemExit("Literature search stage_id must be text.")
    if explicit_stage_id and re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", explicit_stage_id
    ) is None:
        raise SystemExit("Literature search stage_id must be an ASCII-safe identifier.")
    run_id = payload.get("run_id", "")
    if not isinstance(run_id, str):
        raise SystemExit("Literature search run_id must be text.")
    mode = payload.get("mode", "exploratory")
    if not isinstance(mode, str):
        raise SystemExit("Literature search mode must be text.")
    scope = payload.get("scope", {})
    if not isinstance(scope, dict):
        raise SystemExit("Literature search scope must be a mapping.")
    current_stage_id = explicit_stage_id or build_literature_search_stage_id(
        request,
        mode=mode,
        scope=scope,
        run_id=run_id,
    )
    current_path = search_stage_path(root, current_stage_id)
    _validate_search_stage_target(root, current_path)
    existing = load_yaml(current_path, default={})
    if (
        explicit_stage_id
        and isinstance(existing, dict)
        and existing.get("id")
        and existing.get("entry_skill") != "literature-search"
    ):
        # A generic/provider-era stage lacks the provenance contract required by
        # literature-search.  Preserve it untouched and start a safe new run.
        current_stage_id = build_literature_search_stage_id(
            request,
            mode=mode,
            scope=scope,
            run_id=run_id,
        )
        current_path = search_stage_path(root, current_stage_id)
        _validate_search_stage_target(root, current_path)
        existing = load_yaml(current_path, default={})
    preferences = resolve_literature_search_preferences(
        root,
        payload,
        stage_id=current_stage_id,
        existing=existing,
    )
    search_state: dict[str, Any] = {
        "entry_skill": "literature-search",
        **{key: payload[key] for key in SEARCH_STATE_KEYS if key in payload},
        "preference_context": {
            "task_context_digest": preferences["task_context_digest"],
            "selection_binding": preferences["binding"],
            "hard_value_digests": preferences["hard_value_digests"],
        },
    }
    if (
        not isinstance(existing, dict)
        or not existing.get("id")
        or existing.get("entry_skill") != "literature-search"
    ):
        search_state["mode"] = mode or "exploratory"
        search_state["budget"] = {
            **DEFAULT_EXPLORATORY_BUDGET,
            **(search_state.get("budget") if isinstance(search_state.get("budget"), dict) else {}),
        }
        search_state["usage"] = {
            **EMPTY_USAGE,
            **(search_state.get("usage") if isinstance(search_state.get("usage"), dict) else {}),
        }
        search_state.setdefault("stop", {"reason": "in_progress"})
        search_state.setdefault("partial", True)
    else:
        existing_budget = existing.get("budget") if isinstance(existing.get("budget"), dict) else {}
        incoming_budget = search_state.get("budget") if isinstance(search_state.get("budget"), dict) else {}
        search_state["budget"] = {
            **DEFAULT_EXPLORATORY_BUDGET,
            **existing_budget,
            **incoming_budget,
        }
        existing_usage = existing.get("usage") if isinstance(existing.get("usage"), dict) else {}
        incoming_usage = search_state.get("usage") if isinstance(search_state.get("usage"), dict) else {}
        search_state["usage"] = {**EMPTY_USAGE, **existing_usage, **incoming_usage}
        if not existing.get("mode") and "mode" not in search_state:
            search_state["mode"] = "exploratory"
        if "stop" not in existing and "stop" not in search_state:
            search_state["stop"] = {"reason": "in_progress"}
        if "partial" not in existing and "partial" not in search_state:
            search_state["partial"] = True
    return stage_search_results(
        root,
        kind="paper",
        query=request,
        candidates=candidates,
        stage_id=current_stage_id,
        note=note,
        search_state=search_state,
    )


def build_parser() -> argparse.ArgumentParser:
    parser = PrivateArgumentParser(description="Manage a provider-neutral literature search stage.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)
    stage = subparsers.add_parser("stage", help="Validate and stage one Agent-authored search batch")
    stage.add_argument("--input", required=True)
    materialize = subparsers.add_parser(
        "materialize-selection",
        help="Privately delegate a current-user literature selection to source-intake",
    )
    materialize.add_argument("--input", required=True)
    materialize.add_argument("--agent-protocol", required=True)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    if args.command == "materialize-selection":
        payload = _load_selection_payload(Path(args.input))
        result = materialize_selection(
            root,
            payload,
            protocol_name=str(args.agent_protocol),
        )
        print(result["public_message"])
        return int(result["exit_code"])
    payload = _load_payload(Path(args.input))
    path = stage_payload(root, payload)
    persisted = load_yaml(path, default={})
    candidates = [item for item in persisted.get("candidates", []) if isinstance(item, dict)]
    stop = persisted.get("stop") if isinstance(persisted.get("stop"), dict) else {}
    if stop.get("reason") == "blocked_no_search_tool":
        print("当前没有可用的文献检索工具；已记录阻塞原因，没有把空结果当作成功。")
        return 0
    screening_counts = {"include": 0, "maybe": 0, "exclude": 0, "unassessed": 0}
    multi_reviewer = int((persisted.get("scope") or {}).get("screeners") or 1) > 1
    for candidate in candidates:
        screening_key = "effective_screening" if multi_reviewer else "screening"
        screening = candidate.get(screening_key) if isinstance(candidate.get(screening_key), dict) else {}
        decision = str(screening.get("decision") or "unassessed")
        if decision in screening_counts:
            screening_counts[decision] += 1
    print(
        f"已记录本轮文献检索结果；当前共有 {len(candidates)} 个候选，"
        f"其中初筛建议保留 {screening_counts['include']}、待定 {screening_counts['maybe']}、"
        f"排除 {screening_counts['exclude']}、尚未初筛 {screening_counts['unassessed']}。"
        "这些只是初筛；正式入库前，请先告诉我你要保留哪些候选。"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
