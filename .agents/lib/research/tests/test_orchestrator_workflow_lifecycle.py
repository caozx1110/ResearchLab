from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from research.common import append_list_item, load_list_document


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_orchestrator_module():
    root = _project_root()
    script = root / ".agents" / "skills" / "research-orchestrator" / "scripts" / "orchestrate.py"
    spec = importlib.util.spec_from_file_location("research_orchestrator_lifecycle_script", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    (root / ".agents" / "lib").mkdir(parents=True)
    (root / "AGENTS.md").write_text("# Test\n", encoding="utf-8")
    return root


def test_refresh_state_counts_only_counts_open_workflow_items(tmp_path: Path) -> None:
    module = _load_orchestrator_module()
    root = _make_workspace(tmp_path)
    program_id = "p-counts"
    module.ensure_program_files(root, program_id)

    for status in ("open", "answered", "dropped"):
        append_list_item(
            module.open_questions_path(root, program_id),
            f"{program_id}-open-questions",
            "research-orchestrator",
            {"question": f"question {status}"},
            default_status=status,
        )
    for status in ("open", "fulfilled", "dropped"):
        append_list_item(
            module.evidence_requests_path(root, program_id),
            f"{program_id}-evidence-requests",
            "research-orchestrator",
            {"question": f"evidence {status}", "needed": "proof"},
            default_status=status,
        )

    state = module.refresh_state_counts(root, program_id, {"program_id": program_id})

    assert state["counts"]["open_questions"] == 1
    assert state["counts"]["evidence_requests"] == 1


def test_workflow_lifecycle_updates_items_state_and_events(tmp_path: Path) -> None:
    module = _load_orchestrator_module()
    root = _make_workspace(tmp_path)
    program_id = "p-lifecycle"
    module.ensure_program_files(root, program_id)

    append_list_item(
        module.open_questions_path(root, program_id),
        f"{program_id}-open-questions",
        "research-orchestrator",
        {"id": "oq-1", "question": "What is missing?"},
        default_status="open",
    )
    append_list_item(
        module.evidence_requests_path(root, program_id),
        f"{program_id}-evidence-requests",
        "research-orchestrator",
        {"id": "ev-1", "question": "Need evidence", "needed": "logs"},
        default_status="open",
    )

    module.update_list_item_status(
        module.open_questions_path(root, program_id),
        f"{program_id}-open-questions",
        "research-orchestrator",
        "oq-1",
        status="answered",
        note_key="answer",
        note="Enough evidence collected.",
    )
    evidence_path, evidence_item = module.update_list_item_status(
        module.evidence_requests_path(root, program_id),
        f"{program_id}-evidence-requests",
        "research-orchestrator",
        "ev-1",
        status="fulfilled",
        note_key="result",
        note="Baseline log attached.",
    )
    module.append_program_reporting_event(
        root,
        program_id,
        {
            "source_skill": "research-orchestrator",
            "event_type": "evidence-fulfilled",
            "title": evidence_item["question"],
            "summary": evidence_item["result"],
            "tags": ["evidence-request", "fulfilled"],
        },
        generated_by="research-orchestrator",
    )
    module.write_state(root, program_id, module.load_state(root, program_id))

    open_questions = load_list_document(
        module.open_questions_path(root, program_id),
        f"{program_id}-open-questions",
        "research-orchestrator",
    )["items"]
    evidence_requests = load_list_document(evidence_path, f"{program_id}-evidence-requests", "research-orchestrator")["items"]
    events = load_list_document(
        module.reporting_events_path(root, program_id),
        f"{program_id}-reporting-events",
        "research-orchestrator",
    )["items"]
    state = module.load_state(root, program_id)

    assert open_questions[0]["status"] == "answered"
    assert open_questions[0]["answer"] == "Enough evidence collected."
    assert evidence_requests[0]["status"] == "fulfilled"
    assert evidence_requests[0]["result"] == "Baseline log attached."
    assert state["counts"]["open_questions"] == 0
    assert state["counts"]["evidence_requests"] == 0
    assert events[-1]["event_type"] == "evidence-fulfilled"
