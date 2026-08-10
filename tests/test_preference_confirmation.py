from __future__ import annotations

from repo_paths import initialize_test_workspace

import importlib.machinery
import importlib.util
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from repo_paths import REPO_ROOT
from research.common import load_yaml, write_yaml_if_changed
from research.core import default_runtime_preferences, ensure_workspace
from research.learnings import (
    discover_pending_preference_review_cards,
    learnings_path,
    load_learnings,
    log_learning,
    promote_learning,
    render_recall_digest,
    review_learning,
)
from research.paths import runtime_preferences_path
from research.preference_selection import eligible_preferences


def _load_kb_cli():
    script = REPO_ROOT / "skills" / "kb-cli" / "scripts" / "kb"
    module_name = f"kb_cli_preference_confirmation_{id(script)}_{len(sys.modules)}"
    loader = importlib.machinery.SourceFileLoader(module_name, str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def _workspace(tmp_path: Path, *, signer: str = "Human Reviewer") -> Path:
    root = tmp_path / "workspace"
    (root / ".agents").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# isolated preference fixture\n", encoding="utf-8")
    initialize_test_workspace(root)
    runtime = default_runtime_preferences()
    runtime["identity"]["default_confirmed_by"] = signer
    write_yaml_if_changed(runtime_preferences_path(root), runtime)
    return root


def _log_preference(root: Path, index: int, *, operation: str = "weekly") -> dict:
    texts = {
        1: "Prefer concise Chinese summaries.",
        2: "Put the conclusion before supporting detail.",
        3: "Keep established technical terms in English.",
    }
    observations = {
        1: "请用中文，并把结论写得更简洁。",
        2: "先给结论，再补充支撑细节。",
        3: "已经约定的技术术语保留英文。",
    }
    entry, created = log_learning(
        root,
        category="user-preference",
        text=texts[index],
        observation=observations[index],
        source="user",
        skill="report-author",
        operation=operation,
        context="weekly report",
        now=datetime(2026, 7, 27, index, 0, tzinfo=timezone.utc),
    )
    assert created is True
    return entry


def _snapshot_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _display(root: Path, kb, name: str = "review.json") -> tuple[dict, list[dict]]:
    assert kb.main(["--root", str(root), "--agent-protocol", name, "review"]) == 0
    protocol = json.loads((root / ".runtime" / name).read_text(encoding="utf-8"))
    action = next(item for item in protocol["next_actions"] if item["action"] == "present_review_items")
    return protocol, action["review_items"]


def _apply(
    root: Path,
    kb,
    *,
    snapshot: str,
    ref: str,
    decision: str,
    result: str = "apply.json",
) -> int:
    decision_args = [
        "--confirm-ref",
        ref,
        "--decision-evidence",
        "I reviewed the displayed verbatim correction.",
        "--user-authorization",
        "请记住并在以后同类任务中使用这条偏好。",
    ]
    if decision == "reject":
        decision_args = [
            "--reject-ref",
            ref,
            "--rejection-reason",
            "这不是稳定偏好。",
            "--user-authorization",
            "不要记住这条偏好。",
        ]
    return kb.main(
        [
            "--root",
            str(root),
            "--agent-protocol",
            result,
            "review",
            "--apply-snapshot",
            snapshot,
            *decision_args,
        ]
    )


def test_preference_requires_grounded_scope_and_direct_bypasses_are_zero_write(
    tmp_path: Path,
) -> None:
    root = _workspace(tmp_path)
    with pytest.raises(ValueError, match="skill, operation, and verbatim observation"):
        log_learning(
            root,
            category="user-preference",
            text="Prefer concise answers.",
            source="user",
        )
    with pytest.raises(ValueError, match="observation or scope is invalid"):
        log_learning(
            root,
            category="user-preference",
            text="Prefer concise answers.",
            observation="Please be concise.",
            source="user",
            skill="report-author",
            operation="../weekly",
        )
    entry = _log_preference(root, 1)
    before = _snapshot_bytes(root)

    with pytest.raises(ValueError, match="unified kb review snapshot"):
        review_learning(root, learning_id=entry["id"], status="confirmed")
    with pytest.raises(ValueError, match="unified kb review snapshot"):
        promote_learning(root, learning_id=entry["id"])

    assert _snapshot_bytes(root) == before


def test_preference_review_confirms_once_and_only_exact_consumer_can_see_it(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _workspace(tmp_path)
    kb = _load_kb_cli()
    entry = _log_preference(root, 1)

    protocol, items = _display(root, kb)
    public = capsys.readouterr().out
    assert protocol["status"] == "needs_user_authorization"
    assert "表达偏好" in public
    assert entry["text"] in public
    assert entry["observation"] in public
    assert len(items) == 1
    item = items[0]
    assert item["subject"] == {
        "kind": "user_preference",
        "id": entry["id"],
        "owner": "skill-evolution-advisor",
        "path": "kb/memory/learnings.yaml",
    }
    assert item["confirm_route"]["action"] == "confirm-preference"
    assert item["reject_route"]["action"] == "dismiss-preference"

    ref = f"user_preference:{entry['id']}"
    assert _apply(root, kb, snapshot="review.json", ref=ref, decision="confirm") == 0
    capsys.readouterr()
    stored = load_learnings(root)[0]
    assert stored["status"] == "confirmed"
    assert stored["confirmation"]["subject"] == {"kind": "user_preference", "id": entry["id"]}
    assert stored["confirmation"]["authorization_source"] == "user_message"

    weekly = eligible_preferences(root, skill="report-author", operation="weekly")
    ppt = eligible_preferences(root, skill="report-author", operation="ppt-materials")
    experiment = eligible_preferences(root, skill="experiment-workbench", operation="plan")
    learned_path = f"learned.{entry['id']}"
    assert learned_path in {item["path"] for item in weekly["items"]}
    assert learned_path not in {item["path"] for item in ppt["items"]}
    assert learned_path not in {item["path"] for item in experiment["items"]}
    assert entry["text"] in render_recall_digest(load_learnings(root), kind="prefs")

    log_learning(
        root,
        category="recurring-issue",
        text="An unrelated learning was appended later.",
        source="agent",
    )
    still_current = eligible_preferences(root, skill="report-author", operation="weekly")
    assert learned_path in {item["path"] for item in still_current["items"]}

    repeated, created = log_learning(
        root,
        category="user-preference",
        text=entry["text"],
        observation="再次纠正：同类周报仍请保持简洁中文。",
        source="user",
        skill="report-author",
        operation="weekly",
    )
    assert created is True
    assert repeated["id"] != entry["id"]


def test_only_two_pending_preferences_are_surfaced_and_stale_content_cannot_apply(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _workspace(tmp_path)
    kb = _load_kb_cli()
    entries = [_log_preference(root, index) for index in (1, 2, 3)]

    cards = discover_pending_preference_review_cards(root)
    assert [card["subject"]["id"] for card in cards] == [entry["id"] for entry in entries[:2]]
    _protocol, items = _display(root, kb, "stale.json")
    capsys.readouterr()
    assert len([item for item in items if item["subject"]["kind"] == "user_preference"]) == 2

    payload = load_yaml(learnings_path(root))
    payload[0]["observation"] = "用户后来修改了这条原话。"
    write_yaml_if_changed(learnings_path(root), payload)
    first_ref = f"user_preference:{entries[0]['id']}"
    before_runtime = runtime_preferences_path(root).read_bytes()

    assert _apply(root, kb, snapshot="stale.json", ref=first_ref, decision="confirm") == 2
    assert "内容已经更新" in capsys.readouterr().err
    assert runtime_preferences_path(root).read_bytes() == before_runtime
    assert load_learnings(root)[0]["status"] == "pending"


def test_sibling_learning_change_invalidates_displayed_preference_snapshot(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _workspace(tmp_path)
    kb = _load_kb_cli()
    entry = _log_preference(root, 1)
    _display(root, kb, "sibling-stale.json")
    capsys.readouterr()
    log_learning(
        root,
        category="recurring-issue",
        text="A separate learning changed the canonical container.",
        source="agent",
    )
    before_runtime = runtime_preferences_path(root).read_bytes()

    assert _apply(
        root,
        kb,
        snapshot="sibling-stale.json",
        ref=f"user_preference:{entry['id']}",
        decision="confirm",
    ) == 2
    assert "内容已经更新" in capsys.readouterr().err
    assert runtime_preferences_path(root).read_bytes() == before_runtime
    assert next(item for item in load_learnings(root) if item["id"] == entry["id"])["status"] == "pending"


def test_tampered_or_placeholder_receipt_is_excluded_without_deleting_history(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _workspace(tmp_path)
    kb = _load_kb_cli()
    entry = _log_preference(root, 1)
    _display(root, kb)
    capsys.readouterr()
    ref = f"user_preference:{entry['id']}"
    assert _apply(root, kb, snapshot="review.json", ref=ref, decision="confirm") == 0
    capsys.readouterr()

    payload = load_yaml(learnings_path(root))
    payload[0]["confirmation"]["by"] = "我"
    write_yaml_if_changed(learnings_path(root), payload)
    runtime_before = runtime_preferences_path(root).read_bytes()

    visible = eligible_preferences(root, skill="report-author", operation="weekly")
    assert f"learned.{entry['id']}" not in {item["path"] for item in visible["items"]}
    assert entry["text"] not in render_recall_digest(load_learnings(root), kind="prefs")
    assert runtime_preferences_path(root).read_bytes() == runtime_before
    assert any(item["id"] == entry["id"] for item in load_yaml(runtime_preferences_path(root))["learned_preferences"]["items"])


def test_placeholder_signer_cannot_confirm_preference(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _workspace(tmp_path, signer="我")
    kb = _load_kb_cli()
    entry = _log_preference(root, 1)
    protocol, _items = _display(root, kb)
    capsys.readouterr()
    assert protocol["details"]["confirmation_identity_required"] is True

    ref = f"user_preference:{entry['id']}"
    assert _apply(root, kb, snapshot="review.json", ref=ref, decision="confirm") == 2
    assert "真实署名" in capsys.readouterr().err
    assert load_learnings(root)[0]["status"] == "pending"
    assert load_yaml(runtime_preferences_path(root))["learned_preferences"]["items"] == []


def test_multi_preference_owner_failure_rolls_back_canonical_files_and_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _workspace(tmp_path)
    kb = _load_kb_cli()
    entries = [_log_preference(root, index) for index in (1, 2)]
    protocol, items = _display(root, kb, "rollback.json")
    capsys.readouterr()
    token = protocol["next_actions"][0]["apply"]["snapshot_token"]
    owner = kb._review_owner_module(root, "skill-evolution-advisor")
    original_apply = owner.apply_review_batch_decision
    calls = {"count": 0}

    def fail_second(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 2:
            raise RuntimeError("injected second preference failure")
        return original_apply(*args, **kwargs)

    monkeypatch.setattr(owner, "apply_review_batch_decision", fail_second)
    before_learning = learnings_path(root).read_bytes()
    before_runtime = runtime_preferences_path(root).read_bytes()
    refs = [f"user_preference:{entry['id']}" for entry in entries]

    assert kb.main(
        [
            "--root",
            str(root),
            "--agent-protocol",
            "rollback-result.json",
            "review",
            "--apply-snapshot",
            "rollback.json",
            "--confirm-ref",
            refs[0],
            "--decision-evidence",
            "I reviewed both displayed corrections.",
            "--reject-ref",
            refs[1],
            "--rejection-reason",
            "The second correction is temporary.",
            "--user-authorization",
            "记住第一条，不要记住第二条。",
        ]
    ) == 2
    capsys.readouterr()
    assert calls["count"] == 2
    assert learnings_path(root).read_bytes() == before_learning
    assert runtime_preferences_path(root).read_bytes() == before_runtime
    tombstone = json.loads(
            (root / f".runtime/review-snapshots/{token}.json").read_text(encoding="utf-8")
    )
    assert tombstone["status"] == "unused"
    assert len(items) == 2


def test_mixed_preference_decisions_commit_atomically_with_exact_targets(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _workspace(tmp_path)
    kb = _load_kb_cli()
    entries = [_log_preference(root, index) for index in (1, 2)]
    protocol, _items = _display(root, kb, "mixed.json")
    capsys.readouterr()
    token = protocol["next_actions"][0]["apply"]["snapshot_token"]
    refs = [f"user_preference:{entry['id']}" for entry in entries]

    assert kb.main(
        [
            "--root",
            str(root),
            "--agent-protocol",
            "mixed-result.json",
            "review",
            "--apply-snapshot",
            "mixed.json",
            "--confirm-ref",
            refs[0],
            "--decision-evidence",
            "I reviewed both displayed corrections.",
            "--reject-ref",
            refs[1],
            "--rejection-reason",
            "The second correction is temporary.",
            "--user-authorization",
            "记住第一条，不要记住第二条。",
        ]
    ) == 0
    capsys.readouterr()
    stored = {entry["id"]: entry for entry in load_learnings(root)}
    assert stored[entries[0]["id"]]["status"] == "confirmed"
    assert stored[entries[1]["id"]]["status"] == "dismissed"
    runtime_items = load_yaml(runtime_preferences_path(root))["learned_preferences"]["items"]
    assert [item["id"] for item in runtime_items] == [entries[0]["id"]]
    journal_entries = [
        load_yaml(path)
        for path in (root / ".journal").glob("*.yaml")
        if load_yaml(path).get("op_type") == "kb-cli:dialogue-review-batch"
    ]
    assert len(journal_entries) == 1
    assert set(journal_entries[0]["target_paths"]) == {
        "memory/learnings.yaml",
        "config/runtime-preferences.yaml",
        f".runtime/review-snapshots/{token}.json",
    }
    assert journal_entries[0]["state"] == "commit"


def test_dismiss_preserves_unverified_legacy_runtime_history(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = _workspace(tmp_path)
    kb = _load_kb_cli()
    entry = _log_preference(root, 1)
    runtime = load_yaml(runtime_preferences_path(root))
    runtime["learned_preferences"]["items"] = [
        {
            "id": entry["id"],
            "text": "legacy bytes stay historical",
            "source": "user",
            "skill": "report-author",
            "operations": ["weekly"],
        }
    ]
    write_yaml_if_changed(runtime_preferences_path(root), runtime)
    runtime_before = runtime_preferences_path(root).read_bytes()
    _display(root, kb, "dismiss.json")
    capsys.readouterr()

    assert _apply(
        root,
        kb,
        snapshot="dismiss.json",
        ref=f"user_preference:{entry['id']}",
        decision="reject",
    ) == 0
    capsys.readouterr()
    assert runtime_preferences_path(root).read_bytes() == runtime_before
    assert load_learnings(root)[0]["status"] == "dismissed"


@pytest.mark.parametrize("unsafe_kind", ["duplicate-key", "non-utf8", "oversize", "symlink", "fifo"])
def test_unsafe_learning_container_never_produces_preference_cards(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    root = _workspace(tmp_path)
    path = learnings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    if unsafe_kind == "duplicate-key":
        path.write_text(
            "- id: lrn-20260727-001\n  category: user-preference\n  category: user-preference\n",
            encoding="utf-8",
        )
    elif unsafe_kind == "non-utf8":
        path.write_bytes(b"\xff\xfe\x00")
    elif unsafe_kind == "oversize":
        path.write_bytes(b"x" * (8 * 1024 * 1024 + 1))
    elif unsafe_kind == "symlink":
        outside = tmp_path / "outside.yaml"
        outside.write_text("- id: outside\n", encoding="utf-8")
        path.symlink_to(outside)
    else:
        os.mkfifo(path)

    before = path.lstat()
    assert discover_pending_preference_review_cards(root) == []
    after = path.lstat()
    assert (after.st_mode, after.st_ino, after.st_size) == (before.st_mode, before.st_ino, before.st_size)
