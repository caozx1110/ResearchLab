"""Lightweight learnings memory for research workflows."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .core import kb_root, load_runtime_preferences, runtime_preferences_path, write_runtime_preferences
from .journal import mutation_transaction
from .yaml_io import load_yaml, write_yaml_if_changed

CATEGORIES = {"skill-defect", "user-preference", "recurring-issue"}
SOURCES = {"agent", "user"}
STATUSES = {"pending", "confirmed", "dismissed"}
REVIEW_STATUSES = {"confirmed", "dismissed"}
RECALL_KINDS = {"prefs", "gotchas", "defects", "all"}


def learnings_path(project_root: Path) -> Path:
    return kb_root(project_root) / "memory" / "learnings.yaml"


def load_learnings(project_root: Path) -> list[dict[str, Any]]:
    payload = load_yaml(learnings_path(project_root), default=[])
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def write_learnings(project_root: Path, entries: list[dict[str, Any]]) -> Path:
    path = learnings_path(project_root)
    with mutation_transaction(project_root, "write-learnings", [path]):
        write_yaml_if_changed(path, entries)
    return path


def _now(now: datetime | None = None) -> datetime:
    value = now or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _normalize_text(value: str) -> str:
    chars = [ch.lower() if ch.isalnum() else " " for ch in value]
    return " ".join("".join(chars).split())


def _text_similarity(left: str, right: str) -> float:
    left_norm = _normalize_text(left)
    right_norm = _normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    sequence = SequenceMatcher(None, left_norm, right_norm).ratio()
    left_tokens = set(left_norm.split())
    right_tokens = set(right_norm.split())
    overlap = len(left_tokens & right_tokens) / max(1, len(left_tokens | right_tokens))
    return max(sequence, overlap)


def _next_learning_id(entries: list[dict[str, Any]], now: datetime) -> str:
    date = now.strftime("%Y%m%d")
    pattern = re.compile(rf"^lrn-{date}-(\d{{3}})$")
    existing = []
    for entry in entries:
        match = pattern.match(str(entry.get("id") or ""))
        if match:
            existing.append(int(match.group(1)))
    return f"lrn-{date}-{max(existing, default=0) + 1:03d}"


def _validate_enum(value: str, allowed: set[str], field: str) -> str:
    normalized = str(value or "").strip()
    if normalized not in allowed:
        raise ValueError(f"{field} must be one of: {', '.join(sorted(allowed))}")
    return normalized


def _entry_occurrences(entry: dict[str, Any]) -> int:
    try:
        return max(1, int(entry.get("occurrences") or 1))
    except (TypeError, ValueError):
        return 1


def log_learning(
    project_root: Path,
    *,
    category: str,
    text: str,
    source: str = "agent",
    skill: str = "",
    context: str = "",
    now: datetime | None = None,
) -> tuple[dict[str, Any], bool]:
    category = _validate_enum(category, CATEGORIES, "category")
    source = _validate_enum(source, SOURCES, "source")
    text = str(text or "").strip()
    if not text:
        raise ValueError("text must not be empty")

    timestamp = _now(now)
    timestamp_text = timestamp.isoformat()
    path = learnings_path(project_root)
    with mutation_transaction(project_root, "log-learning", [path]):
        entries = load_learnings(project_root)
        best_match: dict[str, Any] | None = None
        best_score = 0.0
        for entry in entries:
            if str(entry.get("category") or "") != category:
                continue
            score = _text_similarity(text, str(entry.get("text") or ""))
            if score > best_score and score >= 0.86:
                best_match = entry
                best_score = score

        if best_match is not None:
            best_match["occurrences"] = _entry_occurrences(best_match) + 1
            best_match["last_seen_at"] = timestamp_text
            write_learnings(project_root, entries)
            return best_match, False

        entry = {
            "id": _next_learning_id(entries, timestamp),
            "created_at": timestamp_text,
            "category": category,
            "text": text,
            "source": source,
            "skill": str(skill or "").strip(),
            "context": str(context or "").strip(),
            "status": "pending",
            "occurrences": 1,
            "last_seen_at": timestamp_text,
        }
        entries.append(entry)
        write_learnings(project_root, entries)
        return entry, True


def find_learning(project_root: Path, learning_id: str) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    entries = load_learnings(project_root)
    for entry in entries:
        if str(entry.get("id") or "") == learning_id:
            return entries, entry
    raise ValueError(f"learning not found: {learning_id}")


def review_learning(project_root: Path, *, learning_id: str, status: str) -> dict[str, Any]:
    status = _validate_enum(status, REVIEW_STATUSES, "status")
    path = learnings_path(project_root)
    with mutation_transaction(project_root, "review-learning", [path]):
        entries, entry = find_learning(project_root, learning_id)
        entry["status"] = status
        write_learnings(project_root, entries)
        return entry


def _learned_preference_item(entry: dict[str, Any]) -> dict[str, str]:
    return {
        "id": str(entry.get("id") or ""),
        "text": str(entry.get("text") or ""),
        "source": str(entry.get("source") or ""),
        "skill": str(entry.get("skill") or ""),
        "context": str(entry.get("context") or ""),
    }


def promote_learning(project_root: Path, *, learning_id: str) -> tuple[dict[str, Any], Path]:
    memory_path = learnings_path(project_root)
    preferences_path = runtime_preferences_path(project_root)
    with mutation_transaction(
        project_root,
        "promote-learning",
        [memory_path, preferences_path],
    ):
        entries, entry = find_learning(project_root, learning_id)
        if str(entry.get("category") or "") != "user-preference":
            raise ValueError("only user-preference learnings can be promoted")
        if str(entry.get("status") or "") == "dismissed":
            raise ValueError("dismissed learnings cannot be promoted")

        preferences = load_runtime_preferences(project_root)
        learned_preferences = preferences.get("learned_preferences", {})
        if not isinstance(learned_preferences, dict):
            learned_preferences = {}
        items = learned_preferences.get("items", [])
        if not isinstance(items, list):
            items = []
        item = _learned_preference_item(entry)
        replaced = False
        for index, existing in enumerate(items):
            if isinstance(existing, dict) and str(existing.get("id") or "") == item["id"]:
                items[index] = item
                replaced = True
                break
        if not replaced:
            items.append(item)
        learned_preferences["items"] = items

        entry["status"] = "confirmed"
        write_learnings(project_root, entries)
        write_runtime_preferences(project_root, {"learned_preferences": learned_preferences})
        return entry, preferences_path


def _confirmed_entries(entries: list[dict[str, Any]], category: str, limit: int) -> list[dict[str, Any]]:
    selected = [
        entry
        for entry in entries
        if str(entry.get("category") or "") == category and str(entry.get("status") or "") == "confirmed"
    ]
    return _sort_entries(selected)[:limit]


def _pending_defects(entries: list[dict[str, Any]], limit: int | None = None) -> list[dict[str, Any]]:
    selected = [
        entry
        for entry in entries
        if str(entry.get("category") or "") == "skill-defect" and str(entry.get("status") or "") == "pending"
    ]
    sorted_entries = _sort_entries(selected)
    return sorted_entries if limit is None else sorted_entries[:limit]


def _sort_entries(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        entries,
        key=lambda entry: (_entry_occurrences(entry), str(entry.get("last_seen_at") or "")),
        reverse=True,
    )


def _format_entry(entry: dict[str, Any]) -> str:
    occurrences = _entry_occurrences(entry)
    suffix = f" (x{occurrences})" if occurrences > 1 else ""
    skill = str(entry.get("skill") or "").strip()
    skill_suffix = f" [skill: {skill}]" if skill else ""
    return f"- `{entry.get('id')}` {entry.get('text', '')}{suffix}{skill_suffix}"


def _append_entry_section(lines: list[str], title: str, entries: list[dict[str, Any]]) -> None:
    lines.extend([title, ""])
    if not entries:
        lines.append("- none")
    else:
        lines.extend(_format_entry(entry) for entry in entries)


def render_recall_digest(entries: list[dict[str, Any]], *, kind: str = "all", limit: int = 5) -> str:
    kind = _validate_enum(kind, RECALL_KINDS, "kind")
    limit = max(1, int(limit or 5))
    lines = ["## Recall Digest", ""]

    if kind in {"prefs", "all"}:
        _append_entry_section(lines, "Known habits", _confirmed_entries(entries, "user-preference", limit))
        lines.append("")
    if kind in {"gotchas", "all"}:
        _append_entry_section(lines, "Known gotchas", _confirmed_entries(entries, "recurring-issue", limit))
        lines.append("")
    if kind == "defects":
        _append_entry_section(lines, "Pending skill defects", _pending_defects(entries, limit))
    elif kind == "all":
        lines.append(f"Pending skill defects: {len(_pending_defects(entries))}")

    return "\n".join(lines).strip() + "\n"
