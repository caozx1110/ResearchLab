from __future__ import annotations

import copy
import hashlib
import importlib.machinery
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

from research.common import load_yaml, write_yaml_if_changed
from research.confirm import apply_confirmation
from research.judgements import discover_pending_judgements, judgement_confirmation_is_current
from research.paths import config_root, runtime_preferences_path
from research.prefs import default_runtime_preferences
from research.surveys import (
    COMPOSITE_SURVEY_STAGES,
    build_composite_stage_binding,
    composite_survey_current_violations,
    composite_survey_repair_projection,
    composite_survey_state_path,
    composite_survey_state_violations,
    new_composite_survey_state,
    literature_candidate_identity_digest,
    pending_composite_survey_states,
    select_current_confirmed_survey_records,
    survey_lifecycle_violations,
    update_composite_survey_stage,
)
from research.sources import mark_search_candidate, stage_search_results


ROOT = Path(__file__).resolve().parents[4]
SCRIPT = ROOT / ".agents" / "skills" / "literature-synthesizer" / "scripts" / "synthesize.py"
INTAKE_SCRIPT = ROOT / ".agents" / "skills" / "source-intake" / "scripts" / "intake.py"
QUOTE = "Alpha uses a hierarchical controller for long-horizon tasks."


def load_synthesizer():
    spec = importlib.util.spec_from_file_location("survey_lifecycle_synthesizer", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_intake():
    spec = importlib.util.spec_from_file_location("survey_lifecycle_intake", INTAKE_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_kb_cli():
    script = ROOT / ".agents" / "skills" / "kb-cli" / "scripts" / "kb"
    loader = importlib.machinery.SourceFileLoader("survey_lifecycle_kb_cli", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def load_orchestrator():
    script = ROOT / ".agents" / "skills" / "research-orchestrator" / "scripts" / "orchestrate.py"
    spec = importlib.util.spec_from_file_location("survey_lifecycle_orchestrator", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def write_confirmed_source(module, root: Path, *, unit_id: str = "p-alpha", confirmed: bool = True) -> dict:
    unit_dir = module.unit_root(root, "paper", unit_id)
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / "note.md").write_text(f"# Evidence\n\n{QUOTE}\n", encoding="utf-8")
    record = {
        "id": unit_id,
        "kind": "paper",
        "title": "Alpha Method",
        "summary": "robot learning",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["fact"],
        "payload": {},
    }
    if confirmed:
        apply_confirmation(
            record,
            confirmed_by="Alice Researcher",
            evidence=["Reviewed source unit"],
            project_root=root,
        )
    write_yaml_if_changed(unit_dir / "record.yaml", record)
    return record


def write_terminal_search(root: Path, *, candidate_id: str = "paper-a") -> Path:
    queried_at = "2026-07-24T00:00:00+00:00"
    state = {
        "entry_skill": "literature-search",
        "mode": "exploratory",
        "scope": {},
        "budget": {
            "max_queries": 8,
            "max_candidates": 50,
            "max_full_reads": 8,
            "max_citation_hops": 6,
        },
        "usage": {
            "queries": 1,
            "candidates_seen": 1,
            "full_reads": 0,
            "citation_hops": 0,
            "retryable_failures": 0,
        },
        "queries": [
            {
                "query_id": "q1",
                "text": "robot learning",
                "intent": "seed",
                "facet": "seed",
                "channel": "web-search",
                "tool": "test-search",
                "selection_reason": "bounded fixture query",
                "searched_at": queried_at,
                "result_count": 1,
                "result_depth": "top-10",
                "outcome": "success",
                "reproducible": False,
            }
        ],
        "coverage": {
            "round": 1,
            "covered_facets": ["seed"],
            "uncovered_facets": [],
            "new_candidates": 1,
            "deduplicated": 0,
            "new_relevant": 1,
            "notes": "fixture coverage",
        },
        "frontier": [],
        "stop": {"reason": "target_met", "rationale": "Fixture target reached."},
        "partial": True,
    }
    candidate = {
        "candidate_id": candidate_id,
        "title": "Alpha Method",
        "url": "https://example.test/alpha",
        "status": "staged",
        "note": "",
        "topics": [],
        "tags": [],
        "pool_hints": [],
        "discovered_by": [
            {
                "query_id": "q1",
                "edge_type": "direct",
                "channel": "web-search",
                "tool": "test-search",
                "discovered_at": queried_at,
            }
        ],
        "fetch": {"status": "discovered", "attempts": 0, "updated_at": queried_at},
        "evidence_level": "title",
        "screening": {"decision": "unassessed"},
    }
    return stage_search_results(
        root,
        kind="paper",
        query="robot learning",
        candidates=[candidate],
        stage_id="literature-search-alpha",
        search_state=state,
    )


def bind_materialized_candidate(module, root: Path, stage_path: Path) -> dict:
    record = write_confirmed_source(module, root)
    record_path = root / "kb/units/papers/p-alpha/record.yaml"
    current = load_yaml(record_path)
    current["status"] = "active"
    current["source"] = {"original_uri": "https://example.test/alpha"}
    candidate = next(
        item for item in load_yaml(stage_path)["candidates"] if item["candidate_id"] == "paper-a"
    )
    current.setdefault("payload", {})["source_search"] = {
        "stage_ids": [stage_path.stem],
        "candidate_ids": ["paper-a"],
        "queries": ["robot learning"],
        "user_selection": {
            "user_authorization": "Keep paper-a for this survey.",
            "authorization_source": "user_message",
        },
        "selections": [
            {
                "stage_id": stage_path.stem,
                "candidate_id": "paper-a",
                "candidate_identity_digest": literature_candidate_identity_digest(candidate),
                "user_authorization": "Keep paper-a for this survey.",
                "authorization_source": "user_message",
            }
        ],
    }
    write_yaml_if_changed(record_path, current)
    mark_search_candidate(
        root,
        stage_path.stem,
        "paper-a",
        status="materialized",
        record_id="p-alpha",
    )
    return load_yaml(record_path)


def build_verified_survey(root: Path, *, program_id: str = "", source: dict | None = None):
    module = load_synthesizer()
    source = source or write_confirmed_source(module, root)
    if program_id:
        (root / "kb" / "programs" / program_id).mkdir(parents=True, exist_ok=True)
    scaffold = module.build_survey_scaffold(
        [source],
        root=root,
        query="robot learning",
        kind="",
        topic="",
        tag="",
        pool="",
        mode="survey",
        as_of="2026-07-24T00:00:00Z",
        program_ids=[program_id] if program_id else [],
    )
    _, entries = module.survey_claim_entries(scaffold)
    for _, cell, _ in entries:
        cell["content"] = f"Agent-authored judgement for {cell['id']}."
        cell["evidence_refs"] = [
            {
                "source_unit_id": "p-alpha",
                "artifact": "note.md",
                "locator": "section=evidence",
                "quote": QUOTE,
            }
        ]
    taxonomy = next(section for section in scaffold["sections"] if section["id"] == "taxonomy")
    taxonomy["cells"][0]["row_label"] = "Alpha Method"
    taxonomy["cells"][0]["column_label"] = "Hierarchical control"
    trends = next(section for section in scaffold["sections"] if section["id"] == "trends")
    trends["items"][0]["trajectory"] = "flat -> hierarchical"
    gaps = next(section for section in scaffold["sections"] if section["id"] == "gaps_challenges")
    gaps["items"][0]["gap_type"] = "benchmark coverage"
    scaffold["comparison_matrix"]["dimensions"][0]["label"] = "Control hierarchy"
    scaffold["comparison_matrix"]["methods"][0]["label"] = "Alpha Method"
    scaffold["comparison_matrix"]["methods"][0]["source_unit_ids"] = ["p-alpha"]
    violations, verified = module.verify_survey_fill(scaffold, root)
    assert violations == [], violations
    survey_path = root / "kb/synthesis/robot-learning/survey.yaml"
    survey_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml_if_changed(survey_path, verified)
    (survey_path.parent / "summary.md").write_text(module.render_verified_summary(verified), encoding="utf-8")
    return module, survey_path, verified


def test_prepare_zero_current_inputs_returns_structured_gap_without_scaffold(tmp_path: Path, monkeypatch, capsys) -> None:
    module = load_synthesizer()
    write_confirmed_source(module, tmp_path, confirmed=False)

    eligible, excluded = select_current_confirmed_survey_records(
        tmp_path,
        list(module.iter_records(tmp_path)),
        query="robot learning",
        kind="",
        topic="",
        tag="",
        pool="",
    )
    assert eligible == []
    assert excluded[0]["reasons"] == ["unit is not confirmed"]

    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--root", str(tmp_path), "survey", "prepare", "--query", "robot learning", "--as-of", "2026-07-24"],
    )
    assert module.main() == 2
    output = capsys.readouterr().out.strip().splitlines()
    handoff = json.loads(output[-1])
    assert handoff["status"] == "evidence_gap"
    assert handoff["composite_handoff"]["ordered_stages"] == list(COMPOSITE_SURVEY_STAGES)
    binding = handoff["composite_handoff"]["state_binding"]
    state_path = tmp_path / binding["state_path"]
    state = load_yaml(state_path)
    assert state["status"] == "blocked"
    assert state["current_stage"] == "search"
    assert state["revision"] == binding["revision"] == 2
    assert composite_survey_state_violations(state) == []
    assert not (tmp_path / "kb/synthesis/robot-learning/survey-fill.yaml").exists()

    orchestrator = load_orchestrator()
    snapshot = orchestrator.portfolio_candidate_snapshot(tmp_path)
    resumable = [
        item
        for item in snapshot["candidates"]
        if item["action_type"] == "resume-composite-survey"
    ]
    assert len(resumable) == 1
    assert resumable[0]["subject"] == {
        "kind": "composite-survey-state",
        "id": binding["composite_id"],
    }
    assert resumable[0]["owner_skill"] == "literature-search"
    assert resumable[0]["stage"] == "search"
    assert resumable[0]["dependencies"][0]["revision"] == binding["revision"]

    # Simulate a fresh process that only has the installed public entrypoint,
    # rather than retaining the prepare handoff in chat context.
    kb = load_kb_cli()
    capsys.readouterr()
    assert kb.main(
        [
            "--root",
            str(tmp_path),
            "--agent-protocol",
            "next-after-restart.json",
            "next",
        ]
    ) == 0
    public = capsys.readouterr().out
    assert "Agent 需要比较当前" in public
    assert "知识库还是空的" not in public
    protocol = json.loads(
        (tmp_path / "kb/.runtime/next-after-restart.json").read_text(encoding="utf-8")
    )
    assert protocol["status"] == "agent_action_required"
    assert protocol["details"]["candidate_count"] >= 1
    assert any(
        item["action_type"] == "resume-composite-survey"
        for item in protocol["next_actions"][0]["candidate_snapshot"]["candidates"]
    )


def test_systematic_prepare_with_matching_unit_still_starts_frozen_search_composite(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = load_synthesizer()
    source = write_confirmed_source(module, tmp_path)
    selected, _excluded = select_current_confirmed_survey_records(
        tmp_path,
        [source],
        query="robot learning",
        kind="",
        topic="",
        tag="",
        pool="",
    )
    assert [item["id"] for item in selected] == ["p-alpha"]
    protocol_path = tmp_path / "systematic-protocol.json"
    protocol_path.write_text(
        json.dumps(
            {
                "mode": "systematic",
                "scope": {
                    "inclusion": ["robot learning"],
                    "exclusion": [],
                    "languages": ["en"],
                    "source_types": ["paper"],
                    "channels": ["runtime-search"],
                    "date_range": "through 2026-07-24",
                    "result_depth": "all bounded results",
                    "screening": "title_abstract_then_fulltext",
                    "screeners": 1,
                },
                "budget": {"max_queries": 8, "max_candidates": 50},
                "review_protocol": {},
                "reviewers": [],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "survey",
            "prepare",
            "--query",
            "robot learning",
            "--as-of",
            "2026-07-24",
            "--discovery-mode",
            "systematic",
            "--search-protocol-input",
            str(protocol_path),
        ],
    )
    assert module.main() == 2
    handoff = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert handoff["reason"] == "external_discovery_required"
    binding = handoff["composite_handoff"]["state_binding"]
    state = load_yaml(tmp_path / binding["state_path"])
    assert state["current_stage"] == "search"
    assert state["stages"][0]["blocker"] == {"code": "external_discovery_required"}
    assert state["selection_filters"]["discovery_mode"] == "systematic"
    frozen = json.loads(state["selection_filters"]["search_protocol"])
    assert frozen["scope"]["inclusion"] == ["robot learning"]
    assert not (tmp_path / "kb/synthesis/robot-learning/survey-fill.yaml").exists()


def test_composite_cli_updates_with_revision_cas_and_is_resumable(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = load_synthesizer()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "survey",
            "prepare",
            "--query",
            "robot learning",
            "--as-of",
            "2026-07-24",
        ],
    )
    assert module.main() == 2
    handoff = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    binding = handoff["composite_handoff"]["state_binding"]
    search_path = write_terminal_search(tmp_path)
    update_path = tmp_path / "search-complete.json"
    update_path.write_text(
        json.dumps(
            {
                "stage_id": "search",
                "status": "completed",
                "outputs": [
                    {"kind": "literature-search-stage", "stage_id": search_path.stem}
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "composite",
            "update",
            "--slug",
            "robot-learning",
            "--composite-id",
            binding["composite_id"],
            "--expected-revision",
            str(binding["revision"]),
            "--input",
            str(update_path),
        ],
    )
    assert module.main() == 0
    updated = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert updated["current_stage"] == "selection"
    assert updated["revision"] == binding["revision"] + 1

    with pytest.raises(SystemExit, match="changed after"):
        module.main()
    assert load_yaml(tmp_path / binding["state_path"])["revision"] == updated["revision"]


def test_composite_all_seven_stages_bind_current_canonical_artifacts(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = load_synthesizer()
    search_path = write_terminal_search(tmp_path)
    state = new_composite_survey_state(
        composite_id="survey-run-binding",
        request_digest=hashlib.sha256(b"canonical binding flow").hexdigest(),
        mode="discovery",
        filters={"query": "robot learning", "program_ids": ""},
    )

    stage_refs: dict[str, list[dict]] = {
        "search": [
            {"kind": "literature-search-stage", "stage_id": search_path.stem}
        ]
    }
    with pytest.raises(ValueError, match="missing or unsafe"):
        update_composite_survey_stage(
            state,
            "search",
            status="completed",
            outputs=[{"kind": "literature-search-stage", "stage_id": "fake-stage"}],
            root=tmp_path,
        )
    state = update_composite_survey_stage(
        state,
        "search",
        status="completed",
        outputs=stage_refs["search"],
        root=tmp_path,
    )
    assert composite_survey_current_violations(tmp_path, state) == []

    stage_refs["selection"] = [
        {
            "kind": "literature-search-selection",
            "stage_id": search_path.stem,
            "candidate_ids": ["paper-a"],
            "user_authorization": "Keep paper-a for this survey.",
            "authorization_source": "user_message",
        }
    ]
    with pytest.raises(ValueError, match="missing from literature stage"):
        update_composite_survey_stage(
            state,
            "selection",
            status="completed",
            outputs=[
                {
                    "kind": "literature-search-selection",
                    "stage_id": search_path.stem,
                    "candidate_ids": ["fake-candidate"],
                    "user_authorization": "Keep fake-candidate.",
                    "authorization_source": "user_message",
                }
            ],
            root=tmp_path,
        )
    state = update_composite_survey_stage(
        state,
        "selection",
        status="completed",
        outputs=stage_refs["selection"],
        root=tmp_path,
    )
    assert not list((tmp_path / "kb/units").rglob("record.yaml"))

    unit_refs = [{"kind": "paper", "id": "p-alpha"}]
    stage_refs["source_intake"] = [
        {"kind": "materialized-units", "stage_id": search_path.stem, "units": unit_refs}
    ]
    with pytest.raises(ValueError, match="missing or unsafe"):
        update_composite_survey_stage(
            state,
            "source_intake",
            status="completed",
            outputs=[
                {
                    "kind": "materialized-units",
                    "stage_id": search_path.stem,
                    "units": [{"kind": "paper", "id": "fake-unit"}],
                }
            ],
            root=tmp_path,
        )
    source = bind_materialized_candidate(module, tmp_path, search_path)
    assert composite_survey_current_violations(tmp_path, state) == []
    state = update_composite_survey_stage(
        state,
        "source_intake",
        status="completed",
        outputs=stage_refs["source_intake"],
        root=tmp_path,
    )

    stage_refs["unit_analysis"] = [
        {"kind": "confirmed-units", "stage_id": search_path.stem, "units": unit_refs}
    ]
    with pytest.raises((SystemExit, ValueError), match="fake-unit|Record not found"):
        update_composite_survey_stage(
            state,
            "unit_analysis",
            status="completed",
            outputs=[
                {
                    "kind": "confirmed-units",
                    "stage_id": search_path.stem,
                    "units": [{"kind": "paper", "id": "fake-unit"}],
                }
            ],
            root=tmp_path,
        )
    state = update_composite_survey_stage(
        state,
        "unit_analysis",
        status="completed",
        outputs=stage_refs["unit_analysis"],
        root=tmp_path,
    )

    module, survey_path, _verified = build_verified_survey(
        tmp_path,
        source=source,
    )
    stage_refs["synthesis"] = [
        {"kind": "verified-survey", "slug": "robot-learning", "mode": "survey"}
    ]
    with pytest.raises(ValueError, match="missing or unsafe"):
        update_composite_survey_stage(
            state,
            "synthesis",
            status="completed",
            outputs=[{"kind": "verified-survey", "slug": "fake-survey", "mode": "survey"}],
            root=tmp_path,
        )
    state = update_composite_survey_stage(
        state,
        "synthesis",
        status="completed",
        outputs=stage_refs["synthesis"],
        root=tmp_path,
    )

    with pytest.raises(ValueError, match="confirmation is missing or stale"):
        update_composite_survey_stage(
            state,
            "review_confirmation",
            status="completed",
            outputs=[{"kind": "confirmed-survey", "slug": "robot-learning", "mode": "survey"}],
            root=tmp_path,
        )
    card = discover_pending_judgements(tmp_path)[0]
    module.apply_review_batch_decision(
        tmp_path,
        card,
        "confirm",
        actor="Alice Researcher",
        evidence=["Reviewed the survey for report consumption."],
        user_authorization="Confirm this displayed survey.",
        authorization_source="user_message",
        rejection_reason="",
    )
    stage_refs["review_confirmation"] = [
        {"kind": "confirmed-survey", "slug": "robot-learning", "mode": "survey"}
    ]
    state = update_composite_survey_stage(
        state,
        "review_confirmation",
        status="completed",
        outputs=stage_refs["review_confirmation"],
        root=tmp_path,
    )

    stage_refs["report_consumption"] = [
        {
            "kind": "not-applicable-report-consumption",
            "reason": "no_linked_programs",
            "survey_slug": "robot-learning",
            "survey_mode": "survey",
        }
    ]
    with pytest.raises(ValueError, match="cover every linked"):
        update_composite_survey_stage(
            state,
            "report_consumption",
            status="completed",
            outputs=[
                {
                    "kind": "program-reporting-events",
                    "program_ids": ["program-survey"],
                    "survey_slug": "robot-learning",
                    "survey_mode": "survey",
                }
            ],
            root=tmp_path,
        )
    state = update_composite_survey_stage(
        state,
        "report_consumption",
        status="completed",
        outputs=stage_refs["report_consumption"],
        root=tmp_path,
    )
    assert state["status"] == "completed"
    assert composite_survey_current_violations(tmp_path, state) == []
    for stage in state["stages"]:
        persisted = stage["outputs"][0]
        assert persisted == build_composite_stage_binding(
            tmp_path,
            stage["id"],
            refs=persisted["refs"],
        )

    state_path = composite_survey_state_path(
        tmp_path,
        slug="robot-learning",
        composite_id="survey-run-binding",
    )
    state_path.parent.mkdir(parents=True, exist_ok=True)
    write_yaml_if_changed(state_path, state)
    record_path = tmp_path / "kb/units/papers/p-alpha/record.yaml"
    changed = load_yaml(record_path)
    changed["payload"]["source_search"]["selections"][0]["user_authorization"] = (
        "Changed authorization bytes."
    )
    write_yaml_if_changed(record_path, changed)
    before_state = state_path.read_bytes()
    journal = tmp_path / "kb/.journal"
    before_journal = {
        item.name: item.read_bytes() for item in journal.glob("*.yaml")
    }

    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "composite",
            "status",
            "--slug",
            "robot-learning",
            "--composite-id",
            "survey-run-binding",
        ],
    )
    assert module.main() == 0
    projected = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert projected["status"] == "blocked"
    assert projected["current_stage"] == "source_intake"
    assert projected["stages"][2]["blocker"] == {
        "code": "stale_composite_stage_binding"
    }
    pending = pending_composite_survey_states(tmp_path)
    repaired_route = next(item for item in pending if item["state"]["id"] == "survey-run-binding")
    assert repaired_route["state"]["current_stage"] == "source_intake"
    assert state_path.read_bytes() == before_state
    assert {item.name: item.read_bytes() for item in journal.glob("*.yaml")} == before_journal


def test_composite_fake_ref_and_stale_cas_fail_before_business_write(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = load_synthesizer()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "survey",
            "prepare",
            "--query",
            "robot learning",
            "--as-of",
            "2026-07-24",
        ],
    )
    assert module.main() == 2
    handoff = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    binding = handoff["composite_handoff"]["state_binding"]
    state_path = tmp_path / binding["state_path"]
    before = state_path.read_bytes()
    update_path = tmp_path / "fake-complete.json"
    update_path.write_text(
        json.dumps(
            {
                "stage_id": "search",
                "status": "completed",
                "outputs": [
                    {"kind": "literature-search-stage", "stage_id": "fake-stage"}
                ],
            }
        ),
        encoding="utf-8",
    )
    base_argv = [
        str(SCRIPT),
        "--root",
        str(tmp_path),
        "composite",
        "update",
        "--slug",
        "robot-learning",
        "--composite-id",
        binding["composite_id"],
        "--input",
        str(update_path),
    ]
    monkeypatch.setattr(
        sys,
        "argv",
        [*base_argv, "--expected-revision", str(binding["revision"])],
    )
    with pytest.raises(SystemExit, match="missing or unsafe"):
        module.main()
    assert state_path.read_bytes() == before

    write_terminal_search(tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [*base_argv, "--expected-revision", str(binding["revision"] - 1)],
    )
    with pytest.raises(SystemExit, match="changed after"):
        module.main()
    assert state_path.read_bytes() == before


def test_duplicate_candidate_attaches_exact_selection_before_composite_intake(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    module = load_synthesizer()
    search_path = write_terminal_search(tmp_path)
    unit_dir = module.unit_root(tmp_path, "paper", "p-alpha")
    unit_dir.mkdir(parents=True, exist_ok=True)
    (unit_dir / "note.md").write_text(f"# Evidence\n\n{QUOTE}\n", encoding="utf-8")
    existing = {
        "id": "p-alpha",
        "kind": "paper",
        "title": "Alpha Method",
        "status": "active",
        "summary": "robot learning",
        "source": {
            "original_uri": "https://example.test/alpha",
            "backup_kind": "file",
            "backup_paths": ["kb/units/papers/p-alpha/note.md"],
            "file_hash": hashlib.sha256(
                (unit_dir / "note.md").read_bytes()
            ).hexdigest(),
        },
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["fact"],
        "payload": {},
    }
    apply_confirmation(
        existing,
        confirmed_by="Alice Researcher",
        evidence=["Reviewed existing source unit"],
        project_root=tmp_path,
    )
    write_yaml_if_changed(unit_dir / "record.yaml", existing)
    confirmation_before = copy.deepcopy(existing["confirmation"])

    state = new_composite_survey_state(
        composite_id="survey-duplicate",
        request_digest=hashlib.sha256(b"duplicate selection").hexdigest(),
        mode="discovery",
        filters={"query": "robot learning"},
    )
    state = update_composite_survey_stage(
        state,
        "search",
        status="completed",
        outputs=[{"kind": "literature-search-stage", "stage_id": search_path.stem}],
        root=tmp_path,
    )
    selection_ref = {
        "kind": "literature-search-selection",
        "stage_id": search_path.stem,
        "candidate_ids": ["paper-a"],
        "user_authorization": "Keep paper-a for this survey.",
        "authorization_source": "user_message",
    }
    state = update_composite_survey_stage(
        state,
        "selection",
        status="completed",
        outputs=[selection_ref],
        root=tmp_path,
    )

    intake = load_intake()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(INTAKE_SCRIPT),
            "--root",
            str(tmp_path),
            "add",
            "--kind",
            "paper",
            "--stage-id",
            search_path.stem,
            "--candidate-id",
            "paper-a",
            "--user-authorization",
            "Keep paper-a for this survey.",
            "--authorization-source",
            "user_message",
        ],
    )
    assert intake.main() == 0
    assert "duplicate detected" in capsys.readouterr().out
    candidate = next(
        item for item in load_yaml(search_path)["candidates"] if item["candidate_id"] == "paper-a"
    )
    assert candidate["status"] == "duplicate"
    assert candidate["record_id"] == "p-alpha"
    current = load_yaml(unit_dir / "record.yaml")
    assert current["confirmation"] == confirmation_before
    receipt = current["payload"]["source_search"]["selections"][0]
    assert receipt["candidate_identity_digest"] == literature_candidate_identity_digest(candidate)

    state = update_composite_survey_stage(
        state,
        "source_intake",
        status="completed",
        outputs=[
            {
                "kind": "materialized-units",
                "stage_id": search_path.stem,
                "units": [{"kind": "paper", "id": "p-alpha"}],
            }
        ],
        root=tmp_path,
    )
    assert state["current_stage"] == "unit_analysis"
    assert composite_survey_current_violations(tmp_path, state) == []

def test_verified_survey_is_discovered_and_batch_confirmed_with_receipt(tmp_path: Path) -> None:
    module, survey_path, verified = build_verified_survey(tmp_path)

    cards = discover_pending_judgements(tmp_path)
    assert [card["subject"] for card in cards] == [
        {
            "kind": "survey_judgement",
            "id": "survey:survey:robot-learning",
            "owner": "literature-synthesizer",
            "path": "kb/synthesis/robot-learning/survey.yaml",
        }
    ]
    card = cards[0]
    assert card["substance"]["sections"]
    assert card["confirm_route"]["action"] == "confirm"
    assert card["reject_route"]["action"] == "reject"

    plan = module.prepare_review_batch_decision(
        tmp_path,
        card,
        "confirm",
        actor="Alice Researcher",
        evidence=["Reviewed all displayed survey claims"],
        user_authorization="I confirm the displayed survey.",
        authorization_source="user_message",
        rejection_reason="",
    )
    assert plan["target_paths"] == [survey_path, survey_path.parent / "summary.md"]
    module.apply_review_batch_decision(
        tmp_path,
        card,
        "confirm",
        actor="Alice Researcher",
        evidence=["Reviewed all displayed survey claims"],
        user_authorization="I confirm the displayed survey.",
        authorization_source="user_message",
        rejection_reason="",
    )
    confirmed = load_yaml(survey_path)
    assert confirmed["confirmation_status"] == "confirmed"
    assert confirmed["confirmation"]["authorization_source"] == "user_message"
    assert confirmed["confirmation"]["claim_ids"]
    assert judgement_confirmation_is_current(tmp_path, confirmed, survey_path)
    assert discover_pending_judgements(tmp_path) == []
    assert "Confirmed judgement" in (survey_path.parent / "summary.md").read_text(encoding="utf-8")

    with pytest.raises(ValueError, match="no longer pending"):
        module.apply_review_batch_decision(
            tmp_path,
            card,
            "confirm",
            actor="Alice Researcher",
            evidence=["Reviewed all displayed survey claims"],
            user_authorization="I confirm the displayed survey.",
            authorization_source="user_message",
            rejection_reason="",
        )


def test_survey_confirmation_rejects_hard_preference_change_without_writes(tmp_path: Path) -> None:
    module, survey_path, before = build_verified_survey(tmp_path)
    card = discover_pending_judgements(tmp_path)[0]
    before_bytes = survey_path.read_bytes()
    write_yaml_if_changed(
        config_root(tmp_path) / "user-profile.yaml",
        {"constraints": ["new offline-only boundary"]},
    )

    with pytest.raises(ValueError, match="preferences changed"):
        module.prepare_review_batch_decision(
            tmp_path,
            card,
            "confirm",
            actor="Alice Researcher",
            evidence=["Reviewed all displayed survey claims"],
            user_authorization="I confirm the displayed survey.",
            authorization_source="user_message",
            rejection_reason="",
        )

    assert survey_path.read_bytes() == before_bytes
    assert load_yaml(survey_path)["confirmation_status"] == before["confirmation_status"]


def test_public_dialogue_batch_routes_survey_to_its_owner(tmp_path: Path, capsys) -> None:
    _module, survey_path, _verified = build_verified_survey(tmp_path)
    (tmp_path / ".agents").mkdir(exist_ok=True)
    (tmp_path / "AGENTS.md").write_text("# isolated survey review\n", encoding="utf-8")
    preferences = default_runtime_preferences()
    preferences["identity"]["default_confirmed_by"] = "Human Reviewer"
    write_yaml_if_changed(runtime_preferences_path(tmp_path), preferences)
    kb = load_kb_cli()

    assert kb.main(
        ["--root", str(tmp_path), "--agent-protocol", "survey-review.json", "review"]
    ) == 0
    capsys.readouterr()
    protocol = json.loads(
        (tmp_path / "kb/.runtime/survey-review.json").read_text(encoding="utf-8")
    )
    item = next(
        row
        for row in protocol["next_actions"][0]["review_items"]
        if row["subject"]["kind"] == "survey_judgement"
    )
    reference = f"survey_judgement:{item['subject']['id']}"

    assert kb.main(
        [
            "--root",
            str(tmp_path),
            "review",
            "--apply-snapshot",
            "survey-review.json",
            "--confirm-ref",
            reference,
            "--decision-evidence",
            "I reviewed every displayed survey claim.",
            "--user-authorization",
            "Confirm this displayed survey judgement.",
        ]
    ) == 0
    public = capsys.readouterr().out

    assert "已应用 1 条拍板结果" in public
    assert load_yaml(survey_path)["confirmation_status"] == "confirmed"


def test_confirmed_program_survey_emits_a_current_reportable_event(tmp_path: Path) -> None:
    module, survey_path, _verified = build_verified_survey(tmp_path, program_id="program-survey")
    card = discover_pending_judgements(tmp_path)[0]
    assert card["program_ids"] == ["program-survey"]
    snapshot = load_orchestrator().portfolio_candidate_snapshot(
        tmp_path,
        selected_program_id="program-survey",
    )
    candidate = next(
        item for item in snapshot["candidates"] if item["subject"]["kind"] == "survey_judgement"
    )
    assert candidate["owner_skill"] == "literature-synthesizer"
    assert candidate["governance_gate"] == "human-decision"

    plan = module.prepare_review_batch_decision(
        tmp_path,
        card,
        "confirm",
        actor="Alice Researcher",
        evidence=["Reviewed the survey for the program report."],
        user_authorization="Confirm this displayed survey.",
        authorization_source="user_message",
        rejection_reason="",
    )
    events_path = tmp_path / "kb/programs/program-survey/workflow/reporting-events.yaml"
    assert events_path in plan["target_paths"]
    module.apply_review_batch_decision(
        tmp_path,
        card,
        "confirm",
        actor="Alice Researcher",
        evidence=["Reviewed the survey for the program report."],
        user_authorization="Confirm this displayed survey.",
        authorization_source="user_message",
        rejection_reason="",
    )
    event = load_yaml(events_path)["items"][0]

    assert event["event_type"] == "survey-confirmed"
    assert event["confirmation_binding"]["subject"]["path"] == survey_path.relative_to(tmp_path).as_posix()
    assert event["confirmation_status"] == "confirmed"
    composite_binding = build_composite_stage_binding(
        tmp_path,
        "report_consumption",
        refs=[
            {
                "kind": "program-reporting-events",
                "program_ids": ["program-survey"],
                "survey_slug": "robot-learning",
                "survey_mode": "survey",
            }
        ],
    )
    assert composite_binding["facts"]["events"][0]["program_id"] == "program-survey"


def test_reject_is_terminal_without_fabricating_confirmation(tmp_path: Path) -> None:
    module, survey_path, _verified = build_verified_survey(tmp_path)
    card = discover_pending_judgements(tmp_path)[0]

    module.apply_review_batch_decision(
        tmp_path,
        card,
        "reject",
        actor="Alice Researcher",
        evidence=[],
        user_authorization="",
        authorization_source="",
        rejection_reason="Taxonomy needs revision.",
    )
    rejected = load_yaml(survey_path)
    assert rejected["confirmation_status"] == "rejected"
    assert "confirmation" not in rejected
    assert rejected["rejection"]["reason"] == "Taxonomy needs revision."
    assert discover_pending_judgements(tmp_path) == []


@pytest.mark.parametrize(
    ("actor", "evidence", "authorization", "source", "message"),
    [
        ("Codex Agent", ["reviewed"], "I confirm it.", "user_message", "Self-signing"),
        ("Alice Researcher", [], "I confirm it.", "user_message", "at least one --evidence"),
        ("Alice Researcher", ["reviewed"], "", "user_message", "user_authorization"),
        ("Alice Researcher", ["reviewed"], "I confirm it.", "", "authorization_source"),
    ],
)
def test_confirm_requires_human_current_message_provenance(
    tmp_path: Path,
    actor: str,
    evidence: list[str],
    authorization: str,
    source: str,
    message: str,
) -> None:
    module, survey_path, _verified = build_verified_survey(tmp_path)
    card = discover_pending_judgements(tmp_path)[0]
    before = survey_path.read_bytes()

    with pytest.raises(SystemExit, match=message):
        module.prepare_review_batch_decision(
            tmp_path,
            card,
            "confirm",
            actor=actor,
            evidence=evidence,
            user_authorization=authorization,
            authorization_source=source,
            rejection_reason="",
        )
    assert survey_path.read_bytes() == before


@pytest.mark.parametrize("mutation", ["content", "claim", "upstream_evidence", "upstream_confirmation"])
def test_confirmed_survey_stales_on_every_bound_change(tmp_path: Path, mutation: str) -> None:
    module, survey_path, _verified = build_verified_survey(tmp_path)
    card = discover_pending_judgements(tmp_path)[0]
    module.apply_review_batch_decision(
        tmp_path,
        card,
        "confirm",
        actor="Alice Researcher",
        evidence=["Reviewed survey"],
        user_authorization="I confirm it.",
        authorization_source="user_message",
        rejection_reason="",
    )
    record = load_yaml(survey_path)
    if mutation == "content":
        record["sections"][0]["claims"][0]["content"] += " Changed."
        write_yaml_if_changed(survey_path, record)
    elif mutation == "claim":
        record["payload"]["claims"][0]["text"] += " Changed."
        write_yaml_if_changed(survey_path, record)
    elif mutation == "upstream_evidence":
        (tmp_path / "kb/units/papers/p-alpha/note.md").write_text("changed evidence bytes", encoding="utf-8")
    else:
        source_path = tmp_path / "kb/units/papers/p-alpha/record.yaml"
        source = load_yaml(source_path)
        source["confirmation"]["evidence"].append("changed receipt bytes")
        write_yaml_if_changed(source_path, source)
    current = load_yaml(survey_path)
    assert not judgement_confirmation_is_current(tmp_path, current, survey_path)


def test_snapshot_cas_fails_before_any_write(tmp_path: Path) -> None:
    module, survey_path, _verified = build_verified_survey(tmp_path)
    card = discover_pending_judgements(tmp_path)[0]
    before = survey_path.read_bytes()
    tampered = copy.deepcopy(card)
    tampered["snapshot_binding"]["content_digest"] = "0" * 64

    with pytest.raises(ValueError, match="stale"):
        module.prepare_review_batch_decision(
            tmp_path,
            tampered,
            "confirm",
            actor="Alice Researcher",
            evidence=["Reviewed survey"],
            user_authorization="I confirm it.",
            authorization_source="user_message",
            rejection_reason="",
        )
    assert survey_path.read_bytes() == before


def test_confirm_cli_transaction_restores_survey_on_summary_failure(tmp_path: Path, monkeypatch) -> None:
    module, survey_path, _verified = build_verified_survey(tmp_path)
    card = discover_pending_judgements(tmp_path)[0]
    before_survey = survey_path.read_bytes()
    before_summary = (survey_path.parent / "summary.md").read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            str(SCRIPT),
            "--root",
            str(tmp_path),
            "survey",
            "confirm",
            "--expected-snapshot",
            json.dumps(card["snapshot_binding"], ensure_ascii=False),
            "--confirmed-by",
            "Alice Researcher",
            "--evidence",
            "Reviewed survey",
            "--user-authorization",
            "I confirm it.",
            "--authorization-source",
            "user_message",
        ],
    )

    def fail_summary(_path: Path, _text: str) -> None:
        raise RuntimeError("injected summary failure")

    monkeypatch.setattr(module, "write_text_if_changed", fail_summary)
    with pytest.raises(RuntimeError, match="injected summary failure"):
        module.main()
    assert survey_path.read_bytes() == before_survey
    assert (survey_path.parent / "summary.md").read_bytes() == before_summary


def test_legacy_needs_agent_repair_is_readable_but_not_reviewable(tmp_path: Path) -> None:
    legacy_path = tmp_path / "kb/synthesis/legacy/survey.yaml"
    legacy_path.parent.mkdir(parents=True)
    legacy = {
        "mode": "survey",
        "slug": "legacy",
        "status": "pending_user_confirmation",
        "confirmation_status": "pending_user_confirmation",
        "governance_status": "needs_agent_repair",
        "sections": [],
    }
    write_yaml_if_changed(legacy_path, legacy)

    assert load_yaml(legacy_path)["governance_status"] == "needs_agent_repair"
    assert survey_lifecycle_violations(legacy, tmp_path) == [
        "legacy survey requires agent repair and re-verification"
    ]
    assert discover_pending_judgements(tmp_path) == []


def test_composite_survey_state_is_ordered_and_resumable() -> None:
    assert COMPOSITE_SURVEY_STAGES == (
        "search",
        "selection",
        "source_intake",
        "unit_analysis",
        "synthesis",
        "review_confirmation",
        "report_consumption",
    )
    state = new_composite_survey_state(
        composite_id="survey-run-1",
        request_digest=hashlib.sha256(b"find papers then survey").hexdigest(),
        mode="discovery",
        filters={"query": "robot learning"},
    )
    assert composite_survey_state_violations(state) == []
    with pytest.raises(ValueError, match="workspace verifier"):
        update_composite_survey_stage(
            state,
            "search",
            status="completed",
            outputs=[{"kind": "candidate_stage", "id": "search-1"}],
        )
    state = update_composite_survey_stage(
        state,
        "search",
        status="blocked",
        blocker={"code": "awaiting_terminal_search"},
        resume_action="finish_literature_search",
    )
    assert state["status"] == "blocked"
    assert composite_survey_state_violations(state) == []
