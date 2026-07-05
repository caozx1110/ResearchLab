from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from research.learnings import (
    learnings_path,
    load_learnings,
    log_learning,
    promote_learning,
    render_recall_digest,
    review_learning,
)
from research.v2 import load_runtime_preferences


def _workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / ".agents" / "lib").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# Test\n", encoding="utf-8")
    return root


def _now(hour: int = 0) -> datetime:
    return datetime(2026, 7, 5, hour, 0, 0, tzinfo=timezone.utc)


def test_learning_log_creates_and_bumps_near_duplicate(tmp_path: Path) -> None:
    root = _workspace(tmp_path)

    entry, created = log_learning(
        root,
        category="recurring-issue",
        text="Always read the recall digest at session start.",
        source="agent",
        now=_now(),
    )
    bumped, bumped_created = log_learning(
        root,
        category="recurring-issue",
        text="Always read recall digest at session start",
        source="user",
        now=_now(1),
    )

    entries = load_learnings(root)
    assert created is True
    assert bumped_created is False
    assert entry["id"] == "lrn-20260705-001"
    assert bumped["id"] == entry["id"]
    assert bumped["occurrences"] == 2
    assert bumped["status"] == "pending"
    assert bumped["last_seen_at"] == "2026-07-05T01:00:00+00:00"
    assert len(entries) == 1
    assert learnings_path(root).relative_to(root).as_posix() == "kb/memory/learnings.yaml"


def test_recall_prints_confirmed_habits_gotchas_and_pending_defects(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    pref, _ = log_learning(
        root,
        category="user-preference",
        text="Prefer Chinese human-facing markdown.",
        source="user",
        now=_now(),
    )
    gotcha, _ = log_learning(
        root,
        category="recurring-issue",
        text="Do not treat AI evaluation as fact.",
        source="agent",
        now=_now(1),
    )
    defect, _ = log_learning(
        root,
        category="skill-defect",
        text="paper-analyst handoff omitted confirmation status.",
        source="agent",
        skill="paper-analyst",
        now=_now(2),
    )
    review_learning(root, learning_id=pref["id"], status="confirmed")
    review_learning(root, learning_id=gotcha["id"], status="confirmed")

    digest = render_recall_digest(load_learnings(root), kind="all", limit=5)
    defects = render_recall_digest(load_learnings(root), kind="defects", limit=5)

    assert "Known habits" in digest
    assert "Prefer Chinese human-facing markdown." in digest
    assert "Do not treat AI evaluation as fact." in digest
    assert "Pending skill defects: 1" in digest
    assert defect["id"] in defects
    assert "paper-analyst handoff omitted confirmation status." in defects


def test_promote_writes_runtime_preferences_and_confirms_learning(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    entry, _ = log_learning(
        root,
        category="user-preference",
        text="Prefer concise Chinese summaries.",
        source="user",
        skill="report-author",
        context="weekly report",
        now=_now(),
    )

    promoted, path = promote_learning(root, learning_id=entry["id"])
    preferences = load_runtime_preferences(root)

    assert path.relative_to(root).as_posix() == "kb/config/runtime-preferences.yaml"
    assert promoted["status"] == "confirmed"
    assert load_learnings(root)[0]["status"] == "confirmed"
    assert preferences["learned_preferences"]["items"] == [
        {
            "id": entry["id"],
            "text": "Prefer concise Chinese summaries.",
            "source": "user",
            "skill": "report-author",
            "context": "weekly report",
        }
    ]


def test_review_sets_confirmed_or_dismissed(tmp_path: Path) -> None:
    root = _workspace(tmp_path)
    entry, _ = log_learning(
        root,
        category="skill-defect",
        text="Navigator did not show memory recall.",
        source="agent",
        skill="research-navigator",
        now=_now(),
    )

    confirmed = review_learning(root, learning_id=entry["id"], status="confirmed")
    dismissed = review_learning(root, learning_id=entry["id"], status="dismissed")

    assert confirmed["status"] == "confirmed"
    assert dismissed["status"] == "dismissed"
    assert load_learnings(root)[0]["status"] == "dismissed"
