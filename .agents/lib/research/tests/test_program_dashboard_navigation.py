from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

from research.common import append_list_item, write_yaml_if_changed
from research.learnings import log_learning, review_learning
from research.v2 import record_path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


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


def test_navigator_current_state_includes_recall_digest(tmp_path: Path, monkeypatch) -> None:
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
    text = (root / "kb" / "user" / "current-state.md").read_text(encoding="utf-8")

    assert "## Recall Digest" in text
    assert "Prefer compact Chinese status pages." in text
    assert "Do not skip confirmation gates." in text
    assert "Pending skill defects: 1" in text


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
    assert "`p-next`: Resolve blocking evidence: Need baseline parity logs" in next_text
    assert ".agents/skills/research-orchestrator/scripts/orchestrate.py status --program-id p-next" in dashboard
    assert ".agents/skills/research-orchestrator/scripts/orchestrate.py status --program-id p-next" in next_text


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
            "payload": {"state": {}},
        },
    )

    items = orchestrate.program_dashboard_items(root)
    dashboard = orchestrate.format_dashboard(items)
    next_text = orchestrate.format_next(items)

    assert ".agents/skills/paper-analyst/scripts/paper.py confirm --paper-id p-pending-123456" in dashboard
    assert ".agents/skills/paper-analyst/scripts/paper.py confirm --paper-id p-pending-123456" in next_text
    assert "<id>" not in dashboard
    assert "<id>" not in next_text


def test_orchestrator_empty_kb_outputs_onboarding_command() -> None:
    orchestrate = _load_script("research-orchestrator", "orchestrate.py", "orchestrator_script_for_empty_kb")

    dashboard = orchestrate.format_dashboard([])
    next_text = orchestrate.format_next([])

    assert "KB 为空，第一步：intake add 一篇论文" in dashboard
    assert ".agents/skills/source-intake/scripts/intake.py add --kind paper" in dashboard
    assert "KB 为空，第一步：intake add 一篇论文" in next_text


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
    assert ".agents/skills/paper-analyst/scripts/paper.py screen --paper-id p-loose-123456" in dashboard


def test_orchestrator_auto_dry_run_plans_exact_command_for_loose_unit(tmp_path: Path) -> None:
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

    text = orchestrate.format_auto_plan(orchestrate.auto_plan(root))

    assert "idea `i-loose-123456` needs analysis" in text
    assert ".agents/skills/idea-workbench/scripts/idea.py analyze --idea-id i-loose-123456" in text
    assert "safe refresh" in text


def test_orchestrator_auto_execute_stops_at_pending_confirmation(tmp_path: Path, capsys) -> None:
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
            "payload": {"quick_screen": {"worth_deep_reading": "maybe"}},
        },
    )

    plan = orchestrate.auto_plan(root)
    exit_code = orchestrate.execute_auto_plan(root, plan)
    output = capsys.readouterr().out

    assert exit_code == 0
    assert plan["safe_execute"] is False
    assert "stop for human decision" in output
    assert "not executing" in output
    assert ".agents/skills/knowledge-base-manager/scripts/kb.py confirm --id p-gated-123456" in output


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
