from __future__ import annotations

from contextlib import contextmanager
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

from repo_paths import REPO_ROOT
import sys

import pytest

import research.confirm as confirm
import research.evidence as evidence
import research.git_ops as git_ops
import research.journal as journal
import research.records as records
from research.yaml_io import load_yaml, write_yaml_if_changed


def _project_root() -> Path:
    return REPO_ROOT


def _load_script(skill: str, script_name: str, module_name: str):
    script = _project_root() / ".agents" / "skills" / skill / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(module_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_cross_track_compatibility_shims_are_absent() -> None:
    root = _project_root()
    banned = {
        root / ".agents" / "lib" / "research" / "records.py": (
            "tempfile",
            "_atomic_restore_bytes",
            "journaled_op",
        ),
        root / ".agents" / "lib" / "research" / "confirm.py": (
            "exclusive_file_lock",
            "operation_lock_path",
            "journaled_op",
        ),
        root / ".agents" / "skills" / "research-orchestrator" / "scripts" / "orchestrate.py": (
            "program_file_lock",
            ".program.lock",
            "journaled_op",
        ),
        root / ".agents" / "skills" / "knowledge-base-manager" / "scripts" / "kb.py": (
            "import inspect",
            "inspect.signature",
            "_confirm_unit_compat",
            "REVIEW_BLOCKED_STATES",
            "review_workflow_states",
            "except ImportError",
            "def mutation_transaction",
        ),
        root / ".agents" / "skills" / "research-navigator" / "scripts" / "navigate.py": (
            "getattr(",
            "journaled_op",
            "navigation_transaction",
            "research_journal",
        ),
    }

    for path, forbidden_fragments in banned.items():
        source = path.read_text(encoding="utf-8")
        for fragment in forbidden_fragments:
            assert fragment not in source, f"temporary compatibility shim returned in {path}: {fragment}"


def test_scripts_import_the_canonical_transaction_and_workflow_classifier() -> None:
    manager = _load_script("knowledge-base-manager", "kb.py", "r1_convergence_manager")
    orchestrator = _load_script("research-orchestrator", "orchestrate.py", "r1_convergence_orchestrator")
    navigator = _load_script("research-navigator", "navigate.py", "r1_convergence_navigator")

    assert manager.mutation_transaction is journal.mutation_transaction
    assert orchestrator.mutation_transaction is journal.mutation_transaction
    assert navigator.mutation_transaction is journal.mutation_transaction
    assert manager.dirty_kb_paths is git_ops.dirty_kb_paths
    assert manager.record_workflow_state is records.record_workflow_state
    assert manager.is_ready_for_human_review is records.is_ready_for_human_review


def test_canonical_classifier_keeps_only_fact_metadata_review_ready() -> None:
    fact_metadata = {
        "id": "p-fact-metadata",
        "kind": "paper",
        "status": "active",
        "confirmation_status": "pending_user_confirmation",
        "information_types": ["fact"],
        "payload": {},
    }
    hollow_records = [
        {**fact_metadata, "id": "p-user-opinion", "information_types": ["user_opinion"]},
        {**fact_metadata, "id": "p-unverified-info", "information_types": ["unverified"]},
        {
            **fact_metadata,
            "id": "p-not-started-judgement",
            "status": "screened",
            "information_types": [],
            "payload": {
                "quick_screen": {"judgement_reason": ["promising result"]},
                "state": {"full_note_status": "not_started"},
            },
        },
        {
            **fact_metadata,
            "id": "p-unverified-claim",
            "payload": {
                "claims": [
                    {
                        "claim_id": "claim-unverified",
                        "claim_type": "unverified",
                        "statement": "Needs verification",
                        "evidence_refs": [],
                    }
                ]
            },
        },
    ]

    assert records.record_workflow_state(fact_metadata) == "ready_for_review"
    assert records.is_ready_for_human_review(fact_metadata) is True
    for record in hollow_records:
        assert records.record_workflow_state(record) != "ready_for_review"
        assert records.is_ready_for_human_review(record) is False


def _verified_judgement_record(kind: str, claim_type: str = "evaluation") -> dict:
    prefix = {"paper": "p", "blog": "b", "repo": "r"}[kind]
    unit_id = f"{prefix}-verified-{kind}-12345678"
    claim = {
        "id": f"claim-{kind}",
        "text": f"Verified {kind} judgement",
        "claim_type": claim_type,
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": [
            {
                "source_unit_id": unit_id,
                "artifact": "raw/source.txt",
                "locator": "line:1",
                "quote": "verbatim source quote",
            }
        ],
    }
    state_key = "capability_fill_status" if kind == "repo" else "full_note_status"
    substance = {
        "paper": {"core_content": {"method": "A real method explanation."}},
        "blog": {"content": {"key_points": ["A grounded key point."]}},
        "repo": {"capability": {"core_capabilities": ["training"]}},
    }[kind]
    return {
        "id": unit_id,
        "kind": kind,
        "title": f"Verified {kind}",
        "status": "active",
        "confirmation_status": "pending_user_confirmation",
        "information_types": ["inference", "evaluation", "unverified"],
        "payload": {
            **substance,
            "claims": [claim],
            "verification": {
                "verified_at": "2026-07-19T00:00:00+00:00",
                "claims_digest": evidence.claims_digest([claim]),
                "evidence_digest": "a" * 64,
                "artifacts": [{"artifact": "raw/source.txt", "sha256": "b" * 64}],
            },
            "state": {state_key: "pending_user_confirmation"},
        },
    }


@pytest.mark.parametrize(
    ("kind", "claim_type"),
    [("paper", "evaluation"), ("blog", "user_opinion"), ("repo", "inference")],
)
def test_verified_judgements_with_record_unverified_are_review_ready(
    kind: str,
    claim_type: str,
) -> None:
    verified = _verified_judgement_record(kind, claim_type)
    assert records.record_workflow_state(verified) == "ready_for_review"
    assert records.is_ready_for_human_review(verified) is True

    hollow = deepcopy(verified)
    hollow["payload"].pop({"paper": "core_content", "blog": "content", "repo": "capability"}[kind])
    assert records.record_workflow_state(hollow) != "ready_for_review"

    missing_receipt = deepcopy(verified)
    missing_receipt["payload"].pop("verification")
    assert records.record_workflow_state(missing_receipt) != "ready_for_review"

    stale_receipt = deepcopy(verified)
    stale_receipt["payload"]["verification"]["invalidation"] = {"reason": "verification_stale"}
    assert records.record_workflow_state(stale_receipt) != "ready_for_review"

    unverified_claim = deepcopy(verified)
    unverified_claim["payload"]["claims"][0]["claim_type"] = "unverified"
    unverified_claim["payload"]["verification"]["claims_digest"] = evidence.claims_digest(
        unverified_claim["payload"]["claims"]
    )
    assert records.record_workflow_state(unverified_claim) != "ready_for_review"


def test_raw_confirmed_judgement_cannot_hide_stale_claim_digest() -> None:
    current = _verified_judgement_record("paper")
    current["confirmation_status"] = "confirmed"
    assert records.record_workflow_state(current) == "done"

    stale = deepcopy(current)
    stale["payload"]["claims"][0]["text"] = "Changed after verification"
    assert records.record_workflow_state(stale) == "ready_to_verify"

    hollow_stale = deepcopy(stale)
    hollow_stale["payload"].pop("core_content")
    assert records.record_workflow_state(hollow_stale) == "awaiting_agent_fill"

    fact = {
        "id": "p-confirmed-fact-12345678",
        "kind": "paper",
        "status": "active",
        "confirmation_status": "confirmed",
        "information_types": ["fact"],
        "payload": {},
    }
    assert records.record_workflow_state(fact) == "done"

    rejected_stale = {**stale, "confirmation_status": "rejected"}
    archived_stale = {**stale, "status": "archived"}
    assert records.record_workflow_state(rejected_stale) == "done"
    assert records.record_workflow_state(archived_stale) == "done"

    archived_failure = deepcopy(archived_stale)
    archived_failure["payload"]["workflow_status"] = "failed_retryable"
    assert records.record_workflow_state(archived_failure) == "failed_retryable"
    archived_failure["confirmation_status"] = "rejected"
    assert records.record_workflow_state(archived_failure) == "done"


def test_attached_stale_unit_is_visible_and_prioritized_between_blocker_and_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    orchestrator = _load_script(
        "research-orchestrator",
        "orchestrate.py",
        "r1_stale_attached_orchestrator",
    )
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# Test workspace\n", encoding="utf-8")

    stale = _verified_judgement_record("paper")
    stale["program_ids"] = ["program-stale"]
    stale["payload"]["claims"][0]["text"] = "Changed after verification"
    write_yaml_if_changed(records.record_path(tmp_path, "paper", stale["id"]), stale)

    pending = {
        "id": "p-pending-fact-12345678",
        "kind": "paper",
        "title": "Pending factual metadata",
        "status": "active",
        "confirmation_status": "pending_user_confirmation",
        "information_types": ["fact"],
        "program_ids": ["program-pending"],
        "payload": {},
    }
    write_yaml_if_changed(records.record_path(tmp_path, "paper", pending["id"]), pending)

    for program_id, unit_ids in (
        ("program-blocked", []),
        ("program-stale", [stale["id"]]),
        ("program-question", []),
        ("program-pending", [pending["id"]]),
    ):
        orchestrator.ensure_program_files(tmp_path, program_id)
        write_yaml_if_changed(
            orchestrator.state_path(tmp_path, program_id),
            {
                "program_id": program_id,
                "stage": "literature-review",
                "active_unit_ids": unit_ids,
            },
        )
    orchestrator.append_list_item(
        orchestrator.evidence_requests_path(tmp_path, "program-blocked"),
        "program-blocked-evidence-requests",
        "research-orchestrator",
        {
            "question": "Is the baseline reproducible?",
            "needed": "Baseline parity logs",
            "priority": "high",
            "blocking": True,
        },
        default_status="open",
    )
    for program_id in ("program-stale", "program-question"):
        orchestrator.append_list_item(
            orchestrator.open_questions_path(tmp_path, program_id),
            f"{program_id}-open-questions",
            "research-orchestrator",
            {
                "question": "Which hypothesis should be tested first?",
                "priority": "high",
            },
            default_status="open",
        )

    items = orchestrator.program_dashboard_items(tmp_path)
    by_program = {item["program_id"]: item for item in items}
    stale_item = by_program["program-stale"]

    assert [item["program_id"] for item in items[:4]] == [
        "program-blocked",
        "program-stale",
        "program-question",
        "program-pending",
    ]
    assert stale_item["record_id"] == stale["id"]
    assert stale_item["step_type"] == "agent-verify"
    assert stale_item["action_kind"] == "agent-work"
    assert stale_item["recommended_command"] == ""
    assert stale_item["pending_confirmation_count"] == 0
    rendered = orchestrator.format_next([stale_item])
    assert "需要 Agent 核验逐字证据" in rendered
    for internal in ("ready_to_verify", "stage=", ".agents/", "--", "${"):
        assert internal not in rendered

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "orchestrate.py",
            "--root",
            str(tmp_path),
            "next",
            "--program-id",
            "program-stale",
            "--json",
        ],
    )
    assert orchestrator.main() == 0
    owner_payload = json.loads(capsys.readouterr().out)
    assert owner_payload["planning_required"] is True
    assert owner_payload["items"] == []
    stale_candidates = [
        item
        for item in owner_payload["candidate_snapshot"]["candidates"]
        if item["subject"]["id"] == stale["id"]
    ]
    assert len(stale_candidates) == 1
    assert stale_candidates[0]["action_type"] == "agent-verify"
    assert stale_candidates[0]["recommended_command"] == ""


def test_orchestrator_transaction_uses_complete_checkpoint_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = _load_script("research-orchestrator", "orchestrate.py", "r1_convergence_scope")
    attached_record = tmp_path / "kb" / "units" / "papers" / "p-attached" / "record.yaml"
    observed: dict[str, object] = {}

    @contextmanager
    def capture_transaction(root: Path, op_type: str, target_paths: list[Path]):
        observed.update(root=root, op_type=op_type, target_paths=target_paths)
        yield "captured-op"

    monkeypatch.setattr(orchestrator, "mutation_transaction", capture_transaction)

    with orchestrator.program_mutation(tmp_path, "program-one", "attach-unit", attached_record):
        pass

    expected = orchestrator.program_checkpoint_paths(tmp_path, "program-one", attached_record)
    assert observed == {
        "root": tmp_path,
        "op_type": "research-orchestrator:attach-unit",
        "target_paths": expected,
    }
    assert attached_record in expected


def test_orchestrator_checkpoints_after_transaction_with_identical_query_scope(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    orchestrator = _load_script("research-orchestrator", "orchestrate.py", "r1_convergence_checkpoint")
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# Test workspace\n", encoding="utf-8")
    events: list[tuple[str, list[Path]]] = []

    @contextmanager
    def capture_transaction(_root: Path, _op_type: str, target_paths: list[Path]):
        events.append(("transaction_begin", list(target_paths)))
        yield "captured-op"
        events.append(("transaction_commit", list(target_paths)))

    def capture_checkpoint(_root: Path, **kwargs):
        assert events[-1][0] == "transaction_commit"
        events.append(("checkpoint", list(kwargs["target_paths"])))
        return {"committed": False}

    monkeypatch.setattr(orchestrator, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(orchestrator, "mutation_transaction", capture_transaction)
    monkeypatch.setattr(orchestrator, "checkpoint_and_report", capture_checkpoint)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "orchestrate.py",
            "--root",
            str(tmp_path),
            "query-program",
            "--program-id",
            "program-one",
            "--question",
            "Which evidence is missing?",
        ],
    )

    assert orchestrator.main() == 0
    assert [event for event, _ in events] == ["transaction_begin", "transaction_commit", "checkpoint"]
    assert events[0][1] == events[1][1] == events[2][1]
    assert any(path.parent.name == "queries" for path in events[0][1])


def test_write_record_canonical_transaction_preserves_cas_and_rolls_back(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = records.default_record("paper", title="Canonical CAS", maturity="lightweight")
    record["id"] = "p-canonical-cas"
    path = confirm.write_record(tmp_path, record)
    stale = deepcopy(load_yaml(path))

    current = deepcopy(stale)
    current["title"] = "Committed revision two"
    confirm.write_record(tmp_path, current)
    assert load_yaml(path)["revision"] == 2

    stale["title"] = "Stale replacement"
    with pytest.raises(SystemExit, match="revision conflict"):
        confirm.write_record(tmp_path, stale)
    assert load_yaml(path)["title"] == "Committed revision two"

    real_write = confirm.write_yaml_if_changed

    def fail_after_record_write(target: Path, payload: dict) -> None:
        real_write(target, payload)
        if target == path:
            raise RuntimeError("simulated post-write failure")

    monkeypatch.setattr(confirm, "write_yaml_if_changed", fail_after_record_write)
    failing = deepcopy(load_yaml(path))
    failing["title"] = "Must roll back"

    with pytest.raises(RuntimeError, match="simulated post-write failure"):
        confirm.write_record(tmp_path, failing)

    restored = load_yaml(path)
    assert restored["title"] == "Committed revision two"
    assert restored["revision"] == 2
    write_ops = [
        load_yaml(entry)
        for entry in (tmp_path / "kb" / ".journal").glob("*.yaml")
        if load_yaml(entry).get("op_type") == "write_record"
    ]
    assert any(entry.get("state") == "abort" for entry in write_ops)


def test_nested_write_record_is_a_transaction_descendant(tmp_path: Path) -> None:
    record = records.default_record("blog", title="Nested canonical write", maturity="lightweight")
    record["id"] = "b-nested-canonical"
    path = tmp_path / "kb" / "units" / "blogs" / record["id"] / "record.yaml"

    with journal.mutation_transaction(tmp_path, "outer-command", [path]) as outer_op_id:
        confirm.write_record(tmp_path, record)

    entries = [load_yaml(entry) for entry in (tmp_path / "kb" / ".journal").glob("*.yaml")]
    inner = next(entry for entry in entries if entry.get("op_type") == "write_record")
    outer = next(entry for entry in entries if entry.get("op_id") == outer_op_id)
    assert outer["state"] == "commit"
    assert inner["state"] == "commit"
    assert inner["parent_op_id"] == outer_op_id
    assert inner["root_op_id"] == outer_op_id
    assert inner["undoable"] is False


def test_navigator_current_state_is_strictly_read_only(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    navigator = _load_script("research-navigator", "navigate.py", "r1_convergence_read_only")
    (tmp_path / ".agents" / "lib").mkdir(parents=True)
    (tmp_path / "AGENTS.md").write_text("# Test workspace\n", encoding="utf-8")
    state = tmp_path / "kb" / "programs" / "program-one" / "state.yaml"
    state.parent.mkdir(parents=True)
    state.write_text("program_id: program-one\nstage: analysis\n", encoding="utf-8")
    before = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }

    @contextmanager
    def forbidden_transaction(*_args, **_kwargs):
        raise AssertionError("current-state must not open a mutation transaction")
        yield

    monkeypatch.setattr(navigator, "mutation_transaction", forbidden_transaction)
    monkeypatch.setattr(sys, "argv", ["navigate.py", "--root", str(tmp_path), "current-state"])

    assert navigator.main() == 0

    after = {
        path.relative_to(tmp_path).as_posix(): path.read_bytes()
        for path in tmp_path.rglob("*")
        if path.is_file()
    }
    assert after == before
    assert "program-one" in capsys.readouterr().out
    assert not (tmp_path / "kb" / "user" / "current-state.md").exists()
