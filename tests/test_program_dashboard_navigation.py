from __future__ import annotations

import importlib.util
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest

from research.common import append_list_item, load_yaml, write_yaml_if_changed
from research.learnings import log_learning, review_learning
from research.core import iter_records, record_path, record_workflow_state


def _project_root() -> Path:
    return REPO_ROOT


def _load_script(skill: str, script_name: str, module_name: str):
    root = _project_root()
    script = root / ".agents" / "skills" / skill / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _make_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / ".agents" / "lib").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# Test\n", encoding="utf-8")
    return root


def test_navigator_current_state_renders_program_states() -> None:
    navigate = _load_script("research-navigator", "navigate.py", "navigator_script_for_u2")

    text = navigate.render_current(
        records=[],
        program_states=[
            {
                "program_id": "p-dashboard",
                "stage": "method-design",
                "goal": "Build the dashboard",
                "counts": {"open_questions": 2, "evidence_requests": 1},
                "updated_at": "2026-07-04T00:00:00+00:00",
            }
        ],
    )

    assert "`p-dashboard` · stage=method-design · OQ=2 · evidence=1 · Build the dashboard" in text
    assert "暂无 program state" not in text


def test_navigator_projects_survey_freshness_without_mutation(tmp_path: Path, monkeypatch) -> None:
    navigate = _load_script("research-navigator", "navigate.py", "navigator_script_for_survey_freshness")
    root = _make_workspace(tmp_path)
    survey_path = root / "kb" / "synthesis" / "robot-learning" / "survey.yaml"
    write_yaml_if_changed(survey_path, {"slug": "robot-learning", "consumer_binding": {}})
    before = survey_path.read_bytes()
    monkeypatch.setattr(
        navigate,
        "survey_staleness",
        lambda payload, project_root: {"stale": True, "reasons": ["changed unit"], "new_unit_ids": []},
    )

    freshness = navigate.load_survey_freshness(root)
    text = navigate.render_current([], survey_freshness=freshness)

    assert freshness == [{"id": "robot-learning", "stale": True, "reason_count": 1}]
    assert "可能过期" in text
    assert "需要重新核验" in text
    assert survey_path.read_bytes() == before


def test_navigator_skips_survey_below_symlinked_directory(tmp_path: Path, monkeypatch) -> None:
    navigate = _load_script("research-navigator", "navigate.py", "navigator_script_for_symlinked_survey")
    root = _make_workspace(tmp_path)
    outside = tmp_path / "outside-surveys"
    write_yaml_if_changed(outside / "survey.yaml", {"slug": "outside", "consumer_binding": {}})
    synthesis = root / "kb" / "synthesis"
    synthesis.mkdir(parents=True)
    (synthesis / "outside").symlink_to(outside, target_is_directory=True)
    monkeypatch.setattr(
        navigate,
        "survey_staleness",
        lambda payload, project_root: (_ for _ in ()).throw(AssertionError("unsafe survey must not be opened")),
    )

    assert navigate.load_survey_freshness(root) == []


def test_navigator_current_state_includes_recall_digest_without_writing(tmp_path: Path, monkeypatch, capsys) -> None:
    navigate = _load_script("research-navigator", "navigate.py", "navigator_script_for_recall")
    root = _make_workspace(tmp_path)
    pref, _ = log_learning(
        root,
        category="user-preference",
        text="Prefer compact Chinese status pages.",
        source="user",
    )
    gotcha, _ = log_learning(
        root,
        category="recurring-issue",
        text="Do not skip confirmation gates.",
        source="agent",
    )
    log_learning(
        root,
        category="skill-defect",
        text="Navigator omitted memory recall.",
        source="agent",
        skill="research-navigator",
    )
    review_learning(root, learning_id=pref["id"], status="confirmed")
    review_learning(root, learning_id=gotcha["id"], status="confirmed")
    monkeypatch.setattr(sys, "argv", ["navigate.py", "--root", str(root), "current-state"])

    assert navigate.main() == 0
    text = capsys.readouterr().out

    assert "## Recall Digest" in text
    assert "Prefer compact Chinese status pages." in text
    assert "Do not skip confirmation gates." in text
    assert "Pending skill defects: 1" in text
    assert not (root / "kb" / "user" / "current-state.md").exists()


def test_navigator_refresh_transactions_exact_pages_before_checkpoint(tmp_path: Path, monkeypatch) -> None:
    navigate = _load_script("research-navigator", "navigate.py", "navigator_script_for_refresh_transaction")
    root = _make_workspace(tmp_path)
    expected = [
        root / "kb" / "user" / "current-state.md",
        root / "kb" / "user" / "navigation.md",
        root / "kb" / "user" / "reading-lists" / "current-reading.md",
    ]
    events: list[str] = []

    @contextmanager
    def transaction(project_root: Path, op_type: str, target_paths: list[Path]):
        assert project_root == root
        assert op_type == "refresh_user_navigation"
        assert target_paths == expected
        events.append("transaction_begin")
        yield
        events.append("transaction_commit")

    def checkpoint(project_root: Path, **kwargs):
        assert project_root == root
        assert kwargs["target_paths"] == expected
        assert events[-1] == "transaction_commit"
        events.append("checkpoint")
        return {"committed": False}

    monkeypatch.setattr(navigate, "mutation_transaction", transaction)
    monkeypatch.setattr(navigate, "checkpoint_and_report", checkpoint)
    monkeypatch.setattr(sys, "argv", ["navigate.py", "--root", str(root), "refresh"])

    assert navigate.main() == 0

    assert events == ["transaction_begin", "transaction_commit", "checkpoint"]
    assert all(path.is_file() for path in expected)


def test_orchestrator_dashboard_prioritizes_blocking_evidence(tmp_path: Path) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_u2")
    root = _make_workspace(tmp_path)
    program_id = "p-next"
    orchestrate.ensure_program_files(root, program_id)
    write_yaml_if_changed(
        orchestrate.state_path(root, program_id),
        {
            "program_id": program_id,
            "stage": "literature-review",
            "goal": "Choose baseline",
            "active_unit_ids": [],
            "counts": {},
            "updated_at": "2026-07-04T00:00:00+00:00",
        },
    )
    append_list_item(
        orchestrate.evidence_requests_path(root, program_id),
        f"{program_id}-evidence-requests",
        "research-orchestrator",
        {
            "question": "Can repo-X reproduce baseline?",
            "needed": "Need baseline parity logs",
            "priority": "high",
            "blocking": True,
        },
        default_status="open",
    )

    items = orchestrate.program_dashboard_items(root)
    dashboard = orchestrate.format_dashboard(items)
    next_text = orchestrate.format_next(items)

    assert items[0]["program_id"] == program_id
    assert items[0]["blocking_evidence_count"] == 1
    assert "Resolve blocking evidence: Need baseline parity logs" in dashboard
    assert "研究计划「p-next」：Resolve blocking evidence: Need baseline parity logs" in next_text
    assert "--program-id p-next" in items[0]["recommended_command"]
    for rendered in (dashboard, next_text):
        for leaked_fragment in ("python3", ".py ", "--program-id", "${"):
            assert leaked_fragment not in rendered


def test_orchestrator_blocker_wins_over_pending_confirmation_governance(tmp_path: Path) -> None:
    orchestrate = _load_script(
        "research-orchestrator",
        "orchestrate.py",
        "orchestrator_script_for_blocker_pending_priority",
    )
    root = _make_workspace(tmp_path)
    program_id = "p-blocker-pending"
    unit_id = "p-pending-123456"
    orchestrate.ensure_program_files(root, program_id)
    write_yaml_if_changed(
        orchestrate.state_path(root, program_id),
        {
            "program_id": program_id,
            "stage": "literature-review",
            "goal": "Resolve blocker before review",
            "active_unit_ids": [unit_id],
            "counts": {},
        },
    )
    write_yaml_if_changed(
        record_path(root, "paper", unit_id),
        {
            "id": unit_id,
            "kind": "paper",
            "title": "Pending Paper",
            "status": "screened",
            "maturity": "lightweight",
            "confirmation_status": "pending_user_confirmation",
            "needs_human_confirmation": True,
            "information_types": ["fact"],
            "summary": "Pending summary",
            "tags": [],
            "topics": [],
            "candidate_pools": [],
            "source": {"original_uri": "", "file_hash": ""},
            "payload": {"state": {"full_note_status": "pending_user_confirmation"}},
        },
    )
    append_list_item(
        orchestrate.evidence_requests_path(root, program_id),
        f"{program_id}-evidence-requests",
        "research-orchestrator",
        {
            "question": "Can the baseline be reproduced?",
            "needed": "Baseline parity logs",
            "priority": "high",
            "blocking": True,
        },
        default_status="open",
    )

    item = orchestrate.program_dashboard_items(root)[0]
    rendered = orchestrate.format_next([item])

    assert item["pending_confirmation_count"] == 1
    assert item["blocking_evidence_count"] == 1
    assert item["next_action"] == "Resolve blocking evidence: Baseline parity logs"
    assert item["step_type"] == "program-work"
    assert item["action_kind"] == "program-work"
    assert item["record_id"] == ""
    assert "可以直接告诉 Agent 继续推进" in rendered
    assert "告诉我你的决定" not in rendered


def test_orchestrator_status_unknown_program_does_not_create_it(tmp_path: Path, monkeypatch) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_missing_status")
    root = _make_workspace(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["orchestrate.py", "--root", str(root), "status", "--program-id", "typo-program"],
    )

    with pytest.raises(SystemExit, match=r"program `typo-program` not found; existing: \(none\)"):
        orchestrate.main()

    assert not orchestrate.program_root(root, "typo-program").exists()


def test_orchestrator_status_existing_program_still_works(tmp_path: Path, monkeypatch) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_existing_status")
    root = _make_workspace(tmp_path)
    orchestrate.ensure_program_files(root, "p-existing")
    write_yaml_if_changed(orchestrate.state_path(root, "p-existing"), {"program_id": "p-existing", "stage": "init"})
    before = orchestrate.state_path(root, "p-existing").read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        ["orchestrate.py", "--root", str(root), "status", "--program-id", "p-existing"],
    )

    assert orchestrate.main() == 0
    assert orchestrate.state_path(root, "p-existing").exists()
    assert orchestrate.state_path(root, "p-existing").read_bytes() == before


def test_orchestrator_next_program_filter_requests_agent_planning_without_fixed_winner(tmp_path: Path, monkeypatch, capsys) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_filtered_next")
    root = _make_workspace(tmp_path)
    for program_id, action in (("p-one", "Advance one"), ("p-two", "Advance two")):
        orchestrate.ensure_program_files(root, program_id)
        payload = orchestrate.load_state(root, program_id)
        payload["next_actions"] = [action]
        orchestrate.write_state(root, program_id, payload)
    monkeypatch.setattr(
        sys,
        "argv",
        ["orchestrate.py", "--root", str(root), "next", "--program-id", "p-one"],
    )

    assert orchestrate.main() == 0
    output = capsys.readouterr().out
    assert "Agent 需要先比较当前 1 项可行行动" in output
    assert "Advance one" not in output
    assert "p-two" not in output


def test_orchestrator_next_unknown_program_errors(tmp_path: Path, monkeypatch) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_missing_next")
    root = _make_workspace(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["orchestrate.py", "--root", str(root), "next", "--program-id", "missing"],
    )

    with pytest.raises(SystemExit, match=r"program `missing` not found; existing: \(none\)"):
        orchestrate.main()

    assert not orchestrate.program_root(root, "missing").exists()


def test_orchestrator_pending_confirmation_command_uses_real_unit_id(tmp_path: Path) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_b2")
    root = _make_workspace(tmp_path)
    program_id = "p-confirm-next"
    orchestrate.ensure_program_files(root, program_id)
    write_yaml_if_changed(
        orchestrate.state_path(root, program_id),
        {
            "program_id": program_id,
            "stage": "literature-review",
            "goal": "Confirm unit",
            "active_unit_ids": ["p-pending-123456"],
            "counts": {},
        },
    )
    write_yaml_if_changed(
        record_path(root, "paper", "p-pending-123456"),
        {
            "id": "p-pending-123456",
            "kind": "paper",
            "title": "Pending Paper",
            "status": "screened",
            "maturity": "lightweight",
            "confirmation_status": "pending_user_confirmation",
            "needs_human_confirmation": True,
            "information_types": ["fact"],
            "summary": "Pending summary",
            "tags": [],
            "topics": [],
            "candidate_pools": [],
            "source": {"original_uri": "", "file_hash": ""},
            "payload": {"state": {"full_note_status": "pending_user_confirmation"}},
        },
    )

    items = orchestrate.program_dashboard_items(root)
    dashboard = orchestrate.format_dashboard(items)
    next_text = orchestrate.format_next(items)

    assert "--paper-id p-pending-123456" in items[0]["recommended_command"]
    assert "<id>" not in dashboard
    assert "<id>" not in next_text
    for rendered in (dashboard, next_text):
        for leaked_fragment in ("python3", ".py ", "--program-id", "--paper-id", "${"):
            assert leaked_fragment not in rendered


def test_safe_unit_step_routes_unfilled_paper_to_agent_before_user() -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_unfilled_step")
    record = {
        "id": "p-unfilled-123456",
        "kind": "paper",
        "title": "Unfilled Paper",
        "status": "screened",
        "maturity": "complete",
        "confirmation_status": "pending_user_confirmation",
        "payload": {"state": {"full_note_status": "awaiting_agent_fill"}},
    }

    step = orchestrate.safe_unit_step(record)

    assert step is not None
    assert step["kind"] == "agent-work"
    assert step["step_type"] == "agent-fill"
    assert "Agent 补全分析" in step["reason"]


def test_safe_unit_step_prepares_not_started_note_before_user_confirmation() -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_not_started_step")
    record = {
        "id": "p-not-started-123456",
        "kind": "paper",
        "title": "Not Started Paper",
        "status": "screened",
        "maturity": "complete",
        "confirmation_status": "pending_user_confirmation",
        "payload": {
            "quick_screen": {"judgement_reason": ["relevant"]},
            "state": {"full_note_status": "not_started"},
        },
    }

    step = orchestrate.safe_unit_step(record)

    assert step is not None
    assert step["kind"] == "paper"
    assert step["step_type"] == "generate-note"
    assert step["safe_execute"] is True


def test_safe_unit_step_routes_source_ready_blog_but_not_completed_blog() -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_blog_step")
    source_ready = {
        "id": "b-source-ready-123456",
        "kind": "blog",
        "title": "Source Ready Blog",
        "status": "active",
        "confirmation_status": "auto_confirmed",
        "payload": {},
    }

    step = orchestrate.safe_unit_step(source_ready)

    assert step is not None
    assert step["kind"] == "blog"
    assert step["step_type"] == "generate-note"
    assert step["safe_execute"] is True
    assert "有逐字证据支持的摘要" in step["reason"]
    assert "grounded" not in step["reason"]

    completed = {**source_ready, "status": "completed"}
    assert orchestrate.safe_unit_step(completed) is None


def test_program_dashboard_excludes_unfilled_shell_but_keeps_filled_confirmation(tmp_path: Path) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_fill_status_dashboard")
    root = _make_workspace(tmp_path)
    records = {
        "p-unfilled-123456": "awaiting_agent_fill",
        "p-filled-123456": "pending_user_confirmation",
    }
    for program_id, unit_id in (("program-unfilled", "p-unfilled-123456"), ("program-filled", "p-filled-123456")):
        orchestrate.ensure_program_files(root, program_id)
        write_yaml_if_changed(
            orchestrate.state_path(root, program_id),
            {
                "program_id": program_id,
                "stage": "literature-review",
                "goal": "Review paper",
                "active_unit_ids": [unit_id],
                "counts": {},
            },
        )
        write_yaml_if_changed(
            record_path(root, "paper", unit_id),
            {
                "id": unit_id,
                "kind": "paper",
                "title": unit_id,
                "status": "screened",
                "maturity": "complete",
                "confirmation_status": "pending_user_confirmation",
                "needs_human_confirmation": True,
                "information_types": ["fact"],
                "summary": "summary",
                "tags": [],
                "topics": [],
                "candidate_pools": [],
                "source": {"original_uri": "", "file_hash": ""},
                "payload": {"state": {"full_note_status": records[unit_id]}},
            },
        )

    items = {item["program_id"]: item for item in orchestrate.program_dashboard_items(root)}

    assert items["program-unfilled"]["pending_confirmation_count"] == 0
    assert "pending confirmation" not in items["program-unfilled"]["reasons"]
    assert items["program-filled"]["pending_confirmation_count"] == 1
    assert items["program-filled"]["step_type"] == "human-decision"
    assert items["program-filled"]["action_kind"] == "human-gate"
    assert items["program-filled"]["next_action"] == "Review pending confirmation: p-filled-123456"


def test_orchestrator_empty_kb_outputs_onboarding_command() -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_empty_kb")

    dashboard = orchestrate.format_dashboard([])
    next_text = orchestrate.format_next([])

    assert "KB 为空" in dashboard
    assert "KB 为空" in next_text
    assert "kb ingest" in dashboard
    assert "kb ingest" in next_text
    # empty-KB onboarding must NOT name the internal `intake add` verb (users only
    # have kb add / kb ingest) nor leak raw commands (SSOT principle 8).
    for rendered in (dashboard, next_text):
        assert "intake add" not in rendered
        for leaked_fragment in ("python3", ".py ", "--kind", "${"):
            assert leaked_fragment not in rendered


def test_orchestrator_next_distinguishes_existing_records_without_pending_work() -> None:
    orchestrate = _load_script(
        "research-orchestrator",
        "orchestrate.py",
        "orchestrator_script_for_existing_records_no_work",
    )

    text = orchestrate.format_next([], has_records=True)

    assert "知识库已有资料" in text
    assert "KB 为空" not in text
    assert "kb next" not in text


def test_orchestrator_blog_only_source_ready_is_a_real_next_item(tmp_path: Path) -> None:
    orchestrate = _load_script(
        "research-orchestrator",
        "orchestrate.py",
        "orchestrator_script_for_blog_only_next",
    )
    root = _make_workspace(tmp_path)
    write_yaml_if_changed(
        record_path(root, "blog", "b-blog-only-123456"),
        {
            "id": "b-blog-only-123456",
            "kind": "blog",
            "title": "Blog Only",
            "status": "active",
            "confirmation_status": "auto_confirmed",
            "information_types": ["fact"],
            "summary": "",
            "tags": [],
            "topics": [],
            "candidate_pools": [],
            "source": {"original_uri": "https://example.com/blog", "file_hash": ""},
            "payload": {},
        },
    )

    items = orchestrate.program_dashboard_items(root)
    text = orchestrate.format_next(items, has_records=True)

    assert len(items) == 1
    assert items[0]["record_id"] == "b-blog-only-123456"
    assert items[0]["step_type"] == "generate-note"
    assert "资料「Blog Only」（b-blog-only-123456）" in text
    assert "有逐字证据支持的摘要" in text
    assert "KB 为空" not in text
    assert "loose:" not in text
    assert "kb next" not in text


def test_confirmed_repo_does_not_reenter_next_for_optional_structure_scan(tmp_path: Path) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_done_repo_step")
    root = _make_workspace(tmp_path)
    write_yaml_if_changed(
        record_path(root, "repo", "r-confirmed-123456"),
        {
            "id": "r-confirmed-123456",
            "kind": "repo",
            "title": "Confirmed Repo",
            "status": "active",
            "maturity": "complete",
            "confirmation_status": "confirmed",
            "needs_human_confirmation": False,
            "information_types": ["fact"],
            "summary": "Confirmed metadata.",
            "tags": [],
            "topics": [],
            "candidate_pools": [],
            "source": {"original_uri": "https://example.com/repo", "file_hash": ""},
            "payload": {
                "structure": {"scan_status": "not_started", "scan_applicability": "applicable"},
                "state": {"capability_fill_status": "pending_user_confirmation"},
            },
        },
    )

    record = iter_records(root, kind="repo")[0]

    assert record_workflow_state(record) == "done"
    assert orchestrate.safe_unit_step(record) is None
    assert orchestrate.program_dashboard_items(root) == []


def test_persisted_program_next_action_outranks_loose_maintenance(tmp_path: Path) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_program_continuation")
    root = _make_workspace(tmp_path)
    orchestrate.ensure_program_files(root, "humanoid-survey")
    state = orchestrate.load_state(root, "humanoid-survey")
    state.update(
        {
            "program_id": "humanoid-survey",
            "stage": "literature-synthesis",
            "goal": "形成横向综述与技术路线图",
            "next_actions": ["生成横向综述与技术路线图"],
        }
    )
    write_yaml_if_changed(orchestrate.state_path(root, "humanoid-survey"), state)
    write_yaml_if_changed(
        record_path(root, "paper", "p-loose-654321"),
        {
            "id": "p-loose-654321",
            "kind": "paper",
            "title": "Loose Paper",
            "status": "active",
            "maturity": "lightweight",
            "confirmation_status": "auto_confirmed",
            "needs_human_confirmation": False,
            "information_types": ["fact"],
            "summary": "",
            "tags": [],
            "topics": [],
            "candidate_pools": [],
            "source": {"original_uri": "", "file_hash": ""},
            "payload": {"quick_screen": {}, "state": {"full_note_status": "not_started"}},
        },
    )

    items = orchestrate.program_dashboard_items(root)

    assert items[0]["program_id"] == "humanoid-survey"
    assert items[0]["next_action"] == "生成横向综述与技术路线图"
    assert items[0]["score"] >= 50
    assert any(item["stage"] == "loose-unit" for item in items[1:])


def test_next_action_owner_command_persists_and_resolves_durable_work(
    tmp_path: Path,
    monkeypatch,
) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_next_action_owner")
    root = _make_workspace(tmp_path)
    action = "生成横向综述与技术路线图"
    checkpoints: list[dict] = []

    def checkpoint(*args, **kwargs):
        checkpoints.append(kwargs)
        return {"committed": False}

    monkeypatch.setattr(orchestrate, "checkpoint_and_report", checkpoint)

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "orchestrate.py",
            "--root",
            str(root),
            "init-program",
            "--program-id",
            "humanoid-survey",
            "--question",
            "这批工作有哪些技术路线？",
            "--goal",
            "形成横向综述与技术路线图",
        ],
    )
    assert orchestrate.main() == 0
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "orchestrate.py",
            "--root",
            str(root),
            "add-next-action",
            "--program-id",
            "humanoid-survey",
            "--action",
            action,
        ],
    )
    assert orchestrate.main() == 0

    state = load_yaml(orchestrate.state_path(root, "humanoid-survey"))
    assert state["next_actions"] == [action]
    assert orchestrate.program_dashboard_items(root)[0]["next_action"] == action
    state_bytes = orchestrate.state_path(root, "humanoid-survey").read_bytes()
    event_bytes = orchestrate.reporting_events_path(root, "humanoid-survey").read_bytes()
    assert orchestrate.main() == 0
    assert orchestrate.state_path(root, "humanoid-survey").read_bytes() == state_bytes
    assert orchestrate.reporting_events_path(root, "humanoid-survey").read_bytes() == event_bytes
    assert len(checkpoints) == 2

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "orchestrate.py",
            "--root",
            str(root),
            "resolve-next-action",
            "--program-id",
            "humanoid-survey",
            "--action",
            action,
        ],
    )
    assert orchestrate.main() == 0
    assert load_yaml(orchestrate.state_path(root, "humanoid-survey"))["next_actions"] == []
    state_bytes = orchestrate.state_path(root, "humanoid-survey").read_bytes()
    event_bytes = orchestrate.reporting_events_path(root, "humanoid-survey").read_bytes()
    assert orchestrate.main() == 0
    assert orchestrate.state_path(root, "humanoid-survey").read_bytes() == state_bytes
    assert orchestrate.reporting_events_path(root, "humanoid-survey").read_bytes() == event_bytes
    assert len(checkpoints) == 3


def test_orchestrator_dashboard_detects_loose_unscreened_unit(tmp_path: Path) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_loose_unit")
    root = _make_workspace(tmp_path)
    write_yaml_if_changed(
        record_path(root, "paper", "p-loose-123456"),
        {
            "id": "p-loose-123456",
            "kind": "paper",
            "title": "Loose Paper",
            "status": "active",
            "maturity": "lightweight",
            "confirmation_status": "auto_confirmed",
            "needs_human_confirmation": False,
            "information_types": ["fact"],
            "summary": "Loose summary",
            "tags": [],
            "topics": [],
            "candidate_pools": [],
            "source": {"original_uri": "", "file_hash": ""},
            "payload": {"quick_screen": {}, "state": {"full_note_status": "not_started"}},
        },
    )

    items = orchestrate.program_dashboard_items(root)
    dashboard = orchestrate.format_dashboard(items)

    assert items[0]["program_id"] == "loose:p-loose-123456"
    assert "unscreened paper `p-loose-123456`" in dashboard
    assert "--paper-id p-loose-123456" in items[0]["recommended_command"]
    assert ".py " not in dashboard
    assert "--paper-id" not in dashboard


def test_orchestrator_routes_new_paper_directly_to_unified_deep_read(tmp_path: Path) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_direct_deep_read")
    root = _make_workspace(tmp_path)
    write_yaml_if_changed(
        record_path(root, "paper", "p-direct-123456"),
        {
            "id": "p-direct-123456",
            "kind": "paper",
            "title": "Direct Deep Read",
            "status": "source_ready",
            "maturity": "lightweight",
            "confirmation_status": "auto_confirmed",
            "needs_human_confirmation": False,
            "information_types": ["fact"],
            "summary": "",
            "tags": [],
            "topics": [],
            "candidate_pools": [],
            "source": {"original_uri": "", "file_hash": ""},
            "payload": {
                "deep_read": {"paper_type": ""},
                "state": {"full_note_status": "not_started"},
            },
        },
    )

    step = orchestrate.safe_unit_step(load_yaml(record_path(root, "paper", "p-direct-123456")))

    assert step is not None
    assert step["step_type"] == "generate-note"
    assert step["command_parts"][2] == "complete-note"
    assert "screen" not in step["command_parts"]


def test_orchestrator_auto_requires_agent_portfolio_decision_for_loose_unit(tmp_path: Path) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_auto_plan")
    root = _make_workspace(tmp_path)
    write_yaml_if_changed(
        record_path(root, "idea", "i-loose-123456"),
        {
            "id": "i-loose-123456",
            "kind": "idea",
            "title": "Loose Idea",
            "status": "draft",
            "maturity": "lightweight",
            "confirmation_status": "auto_confirmed",
            "needs_human_confirmation": False,
            "information_types": ["fact"],
            "summary": "Loose idea",
            "tags": [],
            "topics": [],
            "candidate_pools": [],
            "source": {"original_uri": "", "file_hash": ""},
            "payload": {"analysis": {}, "review": {"review_status": "not_started"}},
        },
    )

    plan = orchestrate.auto_plan(root)
    text = orchestrate.format_auto_plan(plan)

    assert "Agent must compare" in text
    assert plan["command_parts"] == []
    assert ".py " not in text
    assert "--idea-id" not in text
    assert "stop for human decision" in text
    assert plan["status"] == "planning_required"


def test_orchestrator_auto_stops_before_hollow_pending_confirmation(tmp_path: Path, capsys) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_auto_gate")
    root = _make_workspace(tmp_path)
    write_yaml_if_changed(
        record_path(root, "paper", "p-gated-123456"),
        {
            "id": "p-gated-123456",
            "kind": "paper",
            "title": "Gated Paper",
            "status": "screened",
            "maturity": "lightweight",
            "confirmation_status": "pending_user_confirmation",
            "needs_human_confirmation": True,
            "information_types": ["fact"],
            "summary": "Gated summary",
            "tags": [],
            "topics": [],
            "candidate_pools": [],
            "source": {"original_uri": "", "file_hash": ""},
            "payload": {
                "quick_screen": {"worth_deep_reading": "maybe"},
                "state": {"full_note_status": "pending_user_confirmation"},
            },
        },
    )

    plan = orchestrate.auto_plan(root)
    exit_code = orchestrate.execute_auto_plan(root, plan)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert plan["safe_execute"] is False
    assert "stop for human decision" in output
    assert "not executing" in output
    assert plan["step_type"] == "portfolio-planning"
    assert plan["kind"] == "agent-work"
    assert "recommended_command" not in plan
    for leaked_fragment in ("python3", ".py ", "--paper-id", "${"):
        assert leaked_fragment not in output


def test_orchestrator_auto_execute_passes_root_env_and_arg_to_child(tmp_path: Path, monkeypatch) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_auto_child_call")
    root = _make_workspace(tmp_path)
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return subprocess.CompletedProcess(command, 0, stdout="child ok\n", stderr="")

    monkeypatch.setattr(orchestrate.subprocess, "run", fake_run)
    plan = {
        "safe_execute": True,
        "step_type": "refresh",
        "reason": "root-aware child call",
        "command_parts": [
            orchestrate.COMMAND_PREFIX,
            ".agents/skills/idea-workbench/scripts/idea.py",
            "--root",
            "/wrong-root",
            "analyze",
            "--idea-id",
            "i-root-123456",
        ],
    }

    exit_code = orchestrate.execute_auto_plan(root, plan)

    assert exit_code == 0
    assert len(calls) == 1
    command, kwargs = calls[0]
    assert command == [
        sys.executable,
        ".agents/skills/idea-workbench/scripts/idea.py",
        "--root",
        str(root),
        "analyze",
        "--idea-id",
        "i-root-123456",
    ]
    assert kwargs["cwd"] == root
    assert kwargs["env"]["RESEARCH_PROJECT_ROOT"] == str(root)


@pytest.mark.parametrize("invalid_preferences", [ValueError("broken config"), {"autonomy": {"auto_execute_scope": "screen"}}])
def test_orchestrator_auto_execute_fails_closed_when_autonomy_preferences_are_invalid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    invalid_preferences: object,
) -> None:
    orchestrate = _load_script(
        "research-orchestrator",
        "orchestrate.py",
        "orchestrator_script_for_invalid_autonomy",
    )
    root = _make_workspace(tmp_path)

    if isinstance(invalid_preferences, Exception):
        def invalid_loader(_root: Path):
            raise invalid_preferences
        monkeypatch.setattr(orchestrate, "load_runtime_preferences", invalid_loader)
    else:
        monkeypatch.setattr(orchestrate, "load_runtime_preferences", lambda _root: invalid_preferences)
    monkeypatch.setattr(
        orchestrate.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("child must not execute")),
    )
    plan = {
        "safe_execute": True,
        "step_type": "screen",
        "reason": "bounded automatic screening",
        "command_parts": [orchestrate.COMMAND_PREFIX, "owner.py", "screen"],
    }

    assert orchestrate.execute_auto_plan(root, plan) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "could not be validated" in captured.err


def test_orchestrator_auto_execute_passes_root_to_child_under_symlinked_agents(tmp_path: Path) -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_auto_child_root")
    sandbox_root = tmp_path / "sandbox"
    symlink_target = tmp_path / "symlink-target"
    child_script = symlink_target / ".agents" / "skills" / "fake-skill" / "scripts" / "write_marker.py"
    child_script.parent.mkdir(parents=True)
    child_script.write_text(
        "\n".join(
                [
                    "from pathlib import Path",
                    "import sys",
                    "SCRIPT_PATH = Path(__file__).resolve()",
                    "for candidate in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents]:",
                    "    lib = candidate / '.agents' / 'lib'",
                    "    if lib.exists():",
                    "        sys.path.insert(0, str(lib))",
                    "        break",
                    "else:",
                    "    raise SystemExit('Could not locate .agents/lib')",
                    "from research.common import find_project_root",
                    "root = find_project_root(Path(__file__).resolve())",
                "(root / 'kb' / 'child-root.txt').parent.mkdir(parents=True, exist_ok=True)",
                "(root / 'kb' / 'child-root.txt').write_text(str(root), encoding='utf-8')",
                "print(root)",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    (symlink_target / ".agents" / "lib").symlink_to(_project_root() / ".agents" / "lib", target_is_directory=True)
    (symlink_target / "AGENTS.md").write_text("# target\n", encoding="utf-8")
    sandbox_root.mkdir()
    (sandbox_root / ".agents").symlink_to(symlink_target / ".agents", target_is_directory=True)
    (sandbox_root / "AGENTS.md").write_text("# sandbox\n", encoding="utf-8")

    plan = {
        "safe_execute": True,
        "step_type": "refresh",
        "reason": "fake safe write",
        "command_parts": [
            orchestrate.COMMAND_PREFIX,
            ".agents/skills/fake-skill/scripts/write_marker.py",
        ],
    }

    exit_code = orchestrate.execute_auto_plan(sandbox_root, plan)

    assert exit_code == 0
    assert (sandbox_root / "kb" / "child-root.txt").read_text(encoding="utf-8") == str(sandbox_root)
    assert not (symlink_target / "kb" / "child-root.txt").exists()


def test_is_user_confirmable_rejects_unverified_not_started_screening_paper() -> None:
    """R1: a screening judgement without canonical claims/verification is hollow."""
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_confirmable_not_started")
    not_started_screening = {
        "id": "p-scr-not-started-1",
        "kind": "paper",
        "status": "screened",
        "confirmation_status": "pending_user_confirmation",
        "payload": {"state": {"full_note_status": "not_started"},
                    "quick_screen": {"screening_mode": "deep", "judgement_reason": "worth reading"}},
    }
    unfilled_note = {
        "id": "p-shell-1",
        "kind": "paper",
        "status": "screened",
        "confirmation_status": "pending_user_confirmation",
        "payload": {"state": {"full_note_status": "awaiting_agent_fill"}},
    }
    assert orchestrate.is_user_confirmable(not_started_screening) is False
    assert orchestrate.is_user_confirmable(unfilled_note) is False
