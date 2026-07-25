from __future__ import annotations

import importlib
import importlib.util
import inspect
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parents[4]
LIB_ROOT = REPO_ROOT / ".agents" / "lib"
SEARCH_SCRIPT = REPO_ROOT / ".agents" / "skills" / "literature-search" / "scripts" / "search.py"
MONITOR_SCRIPT = REPO_ROOT / ".agents" / "skills" / "research-monitor" / "scripts" / "monitor.py"
if str(LIB_ROOT) not in sys.path:
    sys.path.insert(0, str(LIB_ROOT))

from research.common import file_sha256, write_yaml_if_changed
from research.monitoring import (
    active_monitor_runs,
    create_due_run,
    create_subscription,
    due_subscriptions,
    finish_run,
    load_run,
    load_subscription,
    monitor_task_binding,
    monitor_subscription_preference_context,
    run_path,
    set_outcome_disposition,
    set_subscription_status,
    subscription_path,
    transition_run,
    unresolved_monitor_outcomes,
    value_digest,
)
from research.paths import config_root
from research.preference_selection import (
    OPERATION_CANONICAL_INPUTS,
    eligible_preferences,
    record_effective_selection,
    task_context_digest,
)
from research.skill_validator import validate_skill


@pytest.fixture(autouse=True)
def _existing_monitor_program(tmp_path: Path) -> None:
    (tmp_path / "kb" / "programs" / "program-vla").mkdir(parents=True, exist_ok=True)


def _load_monitor_script():
    spec = importlib.util.spec_from_file_location("research_monitor_script_r7", MONITOR_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _time(day: int, hour: int = 0) -> datetime:
    return datetime(2026, 7, day, hour, tzinfo=timezone.utc)


def _literature_subscription(
    *,
    subscription_id: str = "monitor-vla",
    anchor: str = "2026-07-01T00:00:00+00:00",
) -> dict:
    return {
        "subscription_id": subscription_id,
        "kind": "literature",
        "title": "VLA monitoring",
        "program_ids": ["program-vla"],
        "target": {"question": "What changed in vision-language-action learning?"},
        "scope": {"languages": ["en"], "facets": ["policy learning"]},
        "budget": {
            "max_queries": 8,
            "max_candidates": 50,
            "max_full_reads": 8,
            "max_citation_hops": 6,
        },
        "cadence": {
            "every_days": 14,
            "timezone": "Asia/Shanghai",
            "anchor_at": anchor,
        },
    }


def _monitor_selection(
    root: Path,
    payload: dict,
    *,
    selection_id: str = "prefsel-monitor01",
) -> str:
    context = monitor_subscription_preference_context(root, payload)
    eligible = eligible_preferences(
        root,
        skill="research-monitor",
        operation="create-subscription",
    )
    selected = []
    excluded = []
    for item in eligible["items"]:
        row = {
            "preference_id": item["preference_id"],
            "reason": "relevant to the bounded subscription request",
        }
        if item["strength"] == "hard" or item["path"] == "profile.personalization.research_focus":
            selected.append({**row, "application": "help the Agent author missing soft expression"})
        else:
            excluded.append(row)
    record_effective_selection(
        root,
        {
            "selection_id": selection_id,
            "skill": "research-monitor",
            "operation": "create-subscription",
            "catalog_digest": eligible["catalog_digest"],
            "task_context": context,
            "selected": selected,
            "excluded": excluded,
        },
    )
    return selection_id


def _survey_subscription(tmp_path: Path, *, subscription_id: str = "monitor-survey") -> dict:
    survey = tmp_path / "kb" / "synthesis" / "robot-learning" / "survey.yaml"
    survey.parent.mkdir(parents=True)
    survey.write_text("slug: robot-learning\nconsumer_binding: {}\n", encoding="utf-8")
    return {
        "subscription_id": subscription_id,
        "kind": "survey-freshness",
        "target": {
            "survey_path": survey.relative_to(tmp_path).as_posix(),
            "survey_sha256": file_sha256(survey),
        },
        "scope": {},
        "cadence": {
            "every_days": 30,
            "timezone": "UTC",
            "anchor_at": "2026-07-01T00:00:00Z",
        },
    }


def _write_literature_stage(tmp_path: Path, stage_id: str = "source-search-vla") -> Path:
    run_files = sorted((tmp_path / "kb/monitoring/runs").glob("*.yaml"))
    assert run_files
    binding = monitor_task_binding(load_run(tmp_path, run_files[-1].stem))
    spec = importlib.util.spec_from_file_location("monitor_literature_search_script", SEARCH_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.stage_payload(
        tmp_path,
        {
            "request": "What changed in vision-language-action learning?",
            "stage_id": stage_id,
            "monitor_binding": binding,
            "usage": {
                "queries": 1,
                "candidates_seen": 1,
                "full_reads": 0,
                "citation_hops": 0,
                "retryable_failures": 0,
            },
            "queries": [
                {
                    "query_id": "q-monitor",
                    "text": "new vision language action paper",
                    "intent": "seed",
                    "facet": "new work",
                    "channel": "web-search",
                    "tool": "runtime-search",
                    "selection_reason": "available broad web coverage",
                    "searched_at": "2026-07-15T00:00:00+00:00",
                    "result_depth": "first visible result",
                    "result_count": 1,
                    "outcome": "success",
                    "reproducible": False,
                }
            ],
            "candidates": [
                {
                    "candidate_id": "candidate-new",
                    "title": "New paper",
                    "url": "https://example.test/new-paper",
                    "discovered_by": [
                        {
                            "query_id": "q-monitor",
                            "edge_type": "direct",
                            "source_locator": "search result",
                            "channel": "web-search",
                            "tool": "runtime-search",
                            "discovered_at": "2026-07-15T00:00:00+00:00",
                        }
                    ],
                    "fetch": {"status": "fetched", "attempts": 1},
                    "evidence_level": "abstract",
                    "screening": {
                        "decision": "include",
                        "phase": "title_abstract",
                        "basis": "abstract",
                        "rationale": "The abstract matches the frozen monitor question.",
                        "evidence": [{"quote": "vision language action", "locator": "abstract"}],
                        "reviewer": "runtime-agent",
                    },
                }
            ],
            "coverage": {
                "round": 1,
                "covered_facets": ["new work"],
                "uncovered_facets": [],
                "new_candidates": 1,
                "deduplicated": 0,
                "new_relevant": 1,
            },
            "stop": {"reason": "target_met", "rationale": "Bounded search finished."},
            "partial": False,
        },
    )


def _start_run(tmp_path: Path, *, now: datetime = _time(15)) -> tuple[dict, dict]:
    create_subscription(tmp_path, _literature_subscription(), now=_time(1))
    create_due_run(
        tmp_path,
        "monitor-vla",
        expected_subscription_revision=1,
        now=now,
    )
    subscription = load_subscription(tmp_path, "monitor-vla")
    run = load_run(tmp_path, subscription["active_run_id"])
    transition_run(
        tmp_path,
        run["id"],
        expected_revision=run["revision"],
        state="running",
        now=now,
    )
    return load_subscription(tmp_path, "monitor-vla"), load_run(tmp_path, run["id"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("provider", "OpenAlex"),
        ("created_at", "not-a-time"),
        ("title", []),
        ("program_ids", ["program-vla", "program-vla"]),
        ("scope_snapshot", {"provider": "OpenAlex"}),
        ("history", [{"at": "2026-07-01T00:00:00+00:00", "action": "edited"}]),
    ],
)
def test_subscription_loader_rejects_noncanonical_or_unknown_schema_fields(
    tmp_path: Path, field: str, value: object
) -> None:
    create_subscription(tmp_path, _literature_subscription(), now=_time(1))
    path = subscription_path(tmp_path, "monitor-vla")
    tampered = yaml.safe_load(path.read_text(encoding="utf-8"))
    tampered[field] = value
    if field == "scope_snapshot":
        tampered["scope_digest"] = value_digest(value)
    path.write_text(yaml.safe_dump(tampered, sort_keys=False), encoding="utf-8")

    with pytest.raises(SystemExit):
        load_subscription(tmp_path, "monitor-vla")


@pytest.mark.parametrize(
    "mutation",
    [
        "top-level-provider",
        "frozen-provider",
        "nested-scope-provider",
        "invalid-created-at",
        "malformed-history",
    ],
)
def test_run_loader_rejects_unknown_fields_even_with_recomputed_digest(
    tmp_path: Path, mutation: str
) -> None:
    create_subscription(tmp_path, _literature_subscription(), now=_time(1))
    create_due_run(tmp_path, "monitor-vla", expected_subscription_revision=1, now=_time(15))
    subscription = load_subscription(tmp_path, "monitor-vla")
    path = run_path(tmp_path, subscription["active_run_id"])
    tampered = yaml.safe_load(path.read_text(encoding="utf-8"))
    if mutation == "top-level-provider":
        tampered["provider"] = "OpenAlex"
    elif mutation == "frozen-provider":
        tampered["frozen_subscription"]["provider"] = "OpenAlex"
    elif mutation == "nested-scope-provider":
        tampered["frozen_subscription"]["scope_snapshot"] = {"provider": "OpenAlex"}
        tampered["frozen_subscription"]["scope_digest"] = value_digest(
            tampered["frozen_subscription"]["scope_snapshot"]
        )
    elif mutation == "invalid-created-at":
        tampered["created_at"] = "not-a-time"
    else:
        tampered["history"] = [
            {"at": "2026-07-15T00:00:00+00:00", "action": "edited", "revision": 1}
        ]
    tampered["content_digest"] = value_digest(
        {key: value for key, value in tampered.items() if key != "content_digest"}
    )
    path.write_text(yaml.safe_dump(tampered, sort_keys=False), encoding="utf-8")

    with pytest.raises(SystemExit):
        load_run(tmp_path, subscription["active_run_id"])


def test_subscription_due_facts_are_read_only_and_anchored(tmp_path: Path) -> None:
    path = create_subscription(tmp_path, _literature_subscription(), now=_time(1))
    before = path.read_bytes()

    assert due_subscriptions(tmp_path, now="2026-06-30T23:59:59Z") == []
    due = due_subscriptions(tmp_path, now=_time(31))

    assert due == [
        {
            "subscription_id": "monitor-vla",
            "kind": "literature",
            "title": "VLA monitoring",
            "program_ids": ["program-vla"],
            "due_at": "2026-07-01T00:00:00+00:00",
            "overdue_windows": 2,
            "subscription_revision": 1,
            "scope_digest": load_subscription(tmp_path, "monitor-vla")["scope_digest"],
        }
    ]
    assert path.read_bytes() == before


def test_create_subscription_consumes_task_bound_preferences_and_due_run_inherits_binding(
    tmp_path: Path,
) -> None:
    write_yaml_if_changed(
        config_root(tmp_path) / "user-profile.yaml",
        {
            "preferences": {"language_preference": "zh-CN"},
            "personalization": {"research_focus": "embodied agents"},
            "constraints": ["local only"],
        },
    )
    payload = _literature_subscription(subscription_id="monitor-preference")
    selection_id = _monitor_selection(tmp_path, payload)

    result = _load_monitor_script()._apply(
        tmp_path,
        {
            "action": "create-subscription",
            "subscription": payload,
            "preference_selection_id": selection_id,
            "now": _time(1),
        },
    )
    subscription = load_subscription(tmp_path, "monitor-preference")

    assert result["subscription_id"] == "monitor-preference"
    assert subscription["preference_binding"]["selection_id"] == selection_id
    assert subscription["scope_snapshot"] == payload["scope"]
    assert subscription["budget"] == payload["budget"]
    create_due_run(
        tmp_path,
        "monitor-preference",
        expected_subscription_revision=1,
        now=_time(15),
    )
    current = load_subscription(tmp_path, "monitor-preference")
    run = load_run(tmp_path, current["active_run_id"])
    assert run["frozen_subscription"]["preference_binding"] == subscription["preference_binding"]
    assert run["frozen_subscription"]["subscription_content_digest"] == value_digest(subscription)
    assert monitor_task_binding(run)["task_digest"] == value_digest(
        {
            "run_id": run["id"],
            "subscription_id": "monitor-preference",
            "scheduled_for": run["scheduled_for"],
            "kind": run["frozen_subscription"]["kind"],
            "target": run["frozen_subscription"]["target"],
            "scope_digest": run["frozen_subscription"]["scope_digest"],
            "budget": run["frozen_subscription"]["budget"],
            "subscription_content_digest": run["frozen_subscription"]["subscription_content_digest"],
            "preference_binding": run["frozen_subscription"]["preference_binding"],
        }
    )


@pytest.mark.parametrize(
    ("field", "mutation"),
    [
        ("subscription_id", "monitor-mutated-id"),
        ("title", "Mutated title"),
        ("target", {"question": "A different explicit question"}),
        ("scope", {"languages": ["zh"], "facets": ["changed"]}),
        ("budget", {"max_queries": 1}),
        (
            "cadence",
            {"every_days": 30, "timezone": "UTC", "anchor_at": "2026-07-01T00:00:00Z"},
        ),
        ("program_ids", ["program-other"]),
    ],
)
def test_monitor_request_field_mutation_rejects_stale_receipt_with_zero_subscription_write(
    tmp_path: Path,
    field: str,
    mutation: object,
) -> None:
    (tmp_path / "kb/programs/program-other").mkdir(parents=True, exist_ok=True)
    write_yaml_if_changed(
        config_root(tmp_path) / "user-profile.yaml",
        {"personalization": {"research_focus": "robot learning"}},
    )
    payload = _literature_subscription(subscription_id="monitor-request-matrix")
    selection_id = _monitor_selection(
        tmp_path,
        payload,
        selection_id=f"prefsel-monitor-{field.replace('_', '-')}",
    )
    mutated = {**payload, field: mutation}

    with pytest.raises(SystemExit, match="preference receipt"):
        create_subscription(
            tmp_path,
            mutated,
            now=_time(1),
            preference_selection_id=selection_id,
        )

    assert list((tmp_path / "kb/monitoring/subscriptions").glob("*.yaml")) == []


def test_monitor_reference_and_canonical_preference_mutations_are_zero_write_stale_paths(
    tmp_path: Path,
) -> None:
    program_state = tmp_path / "kb/programs/program-vla/state.yaml"
    write_yaml_if_changed(program_state, {"program_id": "program-vla", "status": "active"})
    profile_path = config_root(tmp_path) / "user-profile.yaml"
    write_yaml_if_changed(
        profile_path,
        {"personalization": {"research_focus": "robot learning"}},
    )
    payload = _literature_subscription(subscription_id="monitor-reference-stale")
    selection_id = _monitor_selection(
        tmp_path,
        payload,
        selection_id="prefsel-monitor-reference",
    )
    write_yaml_if_changed(program_state, {"program_id": "program-vla", "status": "changed"})
    with pytest.raises(SystemExit, match="another task"):
        create_subscription(
            tmp_path,
            payload,
            now=_time(1),
            preference_selection_id=selection_id,
        )
    assert not subscription_path(tmp_path, "monitor-reference-stale").exists()

    write_yaml_if_changed(program_state, {"program_id": "program-vla", "status": "active"})
    second_payload = _literature_subscription(subscription_id="monitor-catalog-stale")
    second_id = _monitor_selection(
        tmp_path,
        second_payload,
        selection_id="prefsel-monitor-catalog",
    )
    write_yaml_if_changed(
        profile_path,
        {"personalization": {"research_focus": "changed after selection"}},
    )
    with pytest.raises(SystemExit, match="stale catalog"):
        create_subscription(
            tmp_path,
            second_payload,
            now=_time(1),
            preference_selection_id=second_id,
        )
    assert not subscription_path(tmp_path, "monitor-catalog-stale").exists()


def test_monitor_create_rejects_receipt_from_another_skill_before_write(tmp_path: Path) -> None:
    payload = _literature_subscription(subscription_id="monitor-wrong-skill")
    eligible = eligible_preferences(tmp_path, skill="report-author", operation="weekly")
    record_effective_selection(
        tmp_path,
        {
            "selection_id": "prefsel-monitor-wrong-skill",
            "skill": "report-author",
            "operation": "weekly",
            "catalog_digest": eligible["catalog_digest"],
            "task_context": {
                "program_id": "program-1",
                "operation": "weekly",
                "stage": "",
                "limit": 20,
                "presentation_contract": "report-presentation/v2",
                "input_snapshot": {
                    "digest": "0" * 64,
                    "accepted_event_count": 0,
                    "pending_judgement_event_count": 0,
                    "claim_source_count": 0,
                    "decision_count": 0,
                    "missing_unit_count": 0,
                },
            },
            "selected": [],
            "excluded": [],
        },
    )

    with pytest.raises(SystemExit, match="another skill"):
        create_subscription(
            tmp_path,
            payload,
            now=_time(1),
            preference_selection_id="prefsel-monitor-wrong-skill",
        )

    assert not subscription_path(tmp_path, "monitor-wrong-skill").exists()


def test_monitor_consumed_input_registry_mutation_matrix() -> None:
    fields = OPERATION_CANONICAL_INPUTS[("research-monitor", "create-subscription")]
    context: dict[str, object] = {field: f"value-{field}" for field in fields}
    baseline = task_context_digest(
        skill="research-monitor",
        operation="create-subscription",
        canonical_inputs=context,
    )
    for field in fields:
        mutated = dict(context)
        mutated[field] = f"changed-{field}"
        assert task_context_digest(
            skill="research-monitor",
            operation="create-subscription",
            canonical_inputs=mutated,
        ) != baseline


@pytest.mark.parametrize("state", ["planned", "running", "blocked", "failed_retryable"])
def test_active_monitor_runs_projects_every_resumable_state(tmp_path: Path, state: str) -> None:
    create_subscription(tmp_path, _literature_subscription(), now=_time(1))
    create_due_run(tmp_path, "monitor-vla", expected_subscription_revision=1, now=_time(15))
    subscription = load_subscription(tmp_path, "monitor-vla")
    run = load_run(tmp_path, subscription["active_run_id"])
    if state != "planned":
        transition_run(
            tmp_path,
            run["id"],
            expected_revision=run["revision"],
            state="running",
            now=_time(15, 1),
        )
        run = load_run(tmp_path, run["id"])
    if state in {"blocked", "failed_retryable"}:
        transition_run(
            tmp_path,
            run["id"],
            expected_revision=run["revision"],
            state=state,
            stop={"reason": state, "rationale": f"The run is {state}."},
            now=_time(15, 2),
        )
        run = load_run(tmp_path, run["id"])

    subscription_bytes = subscription_path(tmp_path, "monitor-vla").read_bytes()
    run_bytes = run_path(tmp_path, run["id"]).read_bytes()
    projection = active_monitor_runs(tmp_path)

    assert len(projection) == 1
    assert projection[0]["run_state"] == state
    assert projection[0]["run_revision"] == run["revision"]
    assert projection[0]["run_content_digest"] == run["content_digest"]
    assert projection[0]["subscription_revision"] == subscription["revision"]
    assert projection[0]["program_ids"] == ["program-vla"]
    assert subscription_path(tmp_path, "monitor-vla").read_bytes() == subscription_bytes
    assert run_path(tmp_path, run["id"]).read_bytes() == run_bytes


def test_pre_r11_active_run_remains_discoverable_with_legacy_task_digest(tmp_path: Path) -> None:
    create_subscription(tmp_path, _literature_subscription(), now=_time(1))
    create_due_run(tmp_path, "monitor-vla", expected_subscription_revision=1, now=_time(15))
    subscription = load_subscription(tmp_path, "monitor-vla")
    run = load_run(tmp_path, subscription["active_run_id"])

    subscription_file = subscription_path(tmp_path, "monitor-vla")
    legacy_subscription = yaml.safe_load(subscription_file.read_text(encoding="utf-8"))
    legacy_subscription.pop("preference_binding")
    subscription_file.write_text(
        yaml.safe_dump(legacy_subscription, sort_keys=False),
        encoding="utf-8",
    )
    run_file = run_path(tmp_path, run["id"])
    legacy_run = yaml.safe_load(run_file.read_text(encoding="utf-8"))
    legacy_run["frozen_subscription"].pop("preference_binding")
    legacy_run["frozen_subscription"].pop("subscription_content_digest")
    legacy_run["content_digest"] = value_digest(
        {key: value for key, value in legacy_run.items() if key != "content_digest"}
    )
    run_file.write_text(yaml.safe_dump(legacy_run, sort_keys=False), encoding="utf-8")

    loaded = load_run(tmp_path, run["id"])
    expected_legacy_task = value_digest(
        {
            "run_id": run["id"],
            "subscription_id": "monitor-vla",
            "scheduled_for": run["scheduled_for"],
            "kind": run["frozen_subscription"]["kind"],
            "target": run["frozen_subscription"]["target"],
            "scope_digest": run["frozen_subscription"]["scope_digest"],
            "budget": run["frozen_subscription"]["budget"],
        }
    )

    assert monitor_task_binding(loaded)["task_digest"] == expected_legacy_task
    assert active_monitor_runs(tmp_path)[0]["run_id"] == run["id"]


def test_subscription_rejects_a_nonexistent_program_binding(tmp_path: Path) -> None:
    payload = _literature_subscription(subscription_id="monitor-missing-program")
    payload["program_ids"] = ["missing-program"]
    with pytest.raises(SystemExit, match="program does not exist"):
        create_subscription(tmp_path, payload, now=_time(1))
    assert not subscription_path(tmp_path, "monitor-missing-program").exists()


def test_due_run_freezes_subscription_and_coalesces_missed_windows(tmp_path: Path) -> None:
    create_subscription(tmp_path, _literature_subscription(), now=_time(1))
    run_file = create_due_run(
        tmp_path,
        "monitor-vla",
        expected_subscription_revision=1,
        now=_time(31),
    )
    subscription = load_subscription(tmp_path, "monitor-vla")
    run = load_run(tmp_path, run_file.stem)

    assert run["scheduled_for"] == "2026-07-01T00:00:00+00:00"
    assert run["frozen_subscription"]["subscription_revision"] == 1
    assert run["frozen_subscription"]["scope_snapshot"] == {
        "languages": ["en"],
        "facets": ["policy learning"],
    }
    assert subscription["active_run_id"] == run["id"]
    assert subscription["revision"] == 2
    assert due_subscriptions(tmp_path, now=_time(31)) == []
    assert len(list((tmp_path / "kb/monitoring/runs").glob("*.yaml"))) == 1


def test_completed_run_advances_from_anchor_not_completion_time(tmp_path: Path) -> None:
    subscription, run = _start_run(tmp_path, now=_time(31))
    stage = _write_literature_stage(tmp_path)

    finish_run(
        tmp_path,
        run["id"],
        expected_run_revision=run["revision"],
        expected_subscription_revision=subscription["revision"],
        state="completed",
        stop={"reason": "completed", "rationale": "Agent completed the bounded review."},
        outputs={"literature_stage_ids": [stage.stem]},
        review_outcomes=[
            {
                "outcome_id": "outcome-new-paper",
                "classification": "new",
                "subject_ref": "candidate-new",
                "rationale": "Agent marked this candidate for user review.",
                "references": [
                    {
                        "kind": "literature-candidate",
                        "stage_id": stage.stem,
                        "candidate_id": "candidate-new",
                    }
                ],
            }
        ],
        now=_time(31, 12),
    )

    completed = load_run(tmp_path, run["id"])
    updated = load_subscription(tmp_path, "monitor-vla")
    assert completed["state"] == "completed"
    assert completed["review_outcomes"][0]["classification"] == "new"
    assert updated["active_run_id"] == ""
    assert updated["last_completed_run_id"] == run["id"]
    assert updated["next_due_at"] == "2026-08-12T00:00:00+00:00"
    assert due_subscriptions(tmp_path, now=_time(31, 13)) == []
    events = yaml.safe_load(
        (tmp_path / "kb/programs/program-vla/workflow/reporting-events.yaml").read_text(
            encoding="utf-8"
        )
    )["items"]
    assert len(events) == 1
    assert events[0]["event_type"] == "monitor-run-completed"
    assert events[0]["epistemic_type"] == "operational"
    assert events[0]["monitor_run_id"] == run["id"]
    assert events[0]["monitor_run_completion_revision"] == completed["revision"]
    assert "classification" not in events[0]


def test_completed_outcome_stays_visible_until_a_bound_disposition(tmp_path: Path) -> None:
    subscription, run = _start_run(tmp_path)
    stage = _write_literature_stage(tmp_path)
    finish_run(
        tmp_path,
        run["id"],
        expected_run_revision=run["revision"],
        expected_subscription_revision=subscription["revision"],
        state="completed",
        stop={"reason": "completed", "rationale": "Agent completed the bounded review."},
        outputs={"literature_stage_ids": [stage.stem]},
        review_outcomes=[
            {
                "outcome_id": "outcome-new-paper",
                "classification": "new",
                "subject_ref": "candidate-new",
                "rationale": "Agent marked this candidate for user review.",
                "references": [
                    {
                        "kind": "literature-candidate",
                        "stage_id": stage.stem,
                        "candidate_id": "candidate-new",
                    }
                ],
            }
        ],
        now=_time(15, 1),
    )
    completed = load_run(tmp_path, run["id"])
    receipt = run_path(tmp_path, run["id"])
    before = receipt.read_bytes()

    unresolved = unresolved_monitor_outcomes(tmp_path)

    assert receipt.read_bytes() == before
    assert len(unresolved) == 1
    assert unresolved[0]["outcome_id"] == "outcome-new-paper"
    assert unresolved[0]["program_ids"] == ["program-vla"]
    assert unresolved[0]["run_content_digest"] == completed["content_digest"]
    assert completed["review_outcomes"][0]["disposition"] == {
        "state": "unresolved",
        "actor": "",
        "at": "",
        "reason": "",
        "target_ref": "",
        "user_authorization": "",
        "authorization_source": "",
    }

    unit_record = tmp_path / "kb/units/papers/p-materialized/record.yaml"
    unit_record.parent.mkdir(parents=True)
    unit_record.write_text("id: p-materialized\nkind: paper\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="current user authorization"):
        set_outcome_disposition(
            tmp_path,
            run["id"],
            "outcome-new-paper",
            expected_run_revision=completed["revision"],
            expected_run_content_digest=completed["content_digest"],
            state="materialized",
            actor="runtime-agent",
            reason="The user selected the candidate.",
            target_ref="p-materialized",
        )
    assert receipt.read_bytes() == before

    result = _load_monitor_script()._apply(
        tmp_path,
        {
            "action": "set-outcome-disposition",
            "run_id": run["id"],
            "outcome_id": "outcome-new-paper",
            "expected_run_revision": completed["revision"],
            "expected_run_content_digest": completed["content_digest"],
            "state": "materialized",
            "actor": "runtime-agent",
            "reason": "The user selected the displayed candidate.",
            "target_ref": "p-materialized",
            "user_authorization": "Add this displayed paper to the knowledge base.",
            "authorization_source": "user_message",
            "now": _time(15, 2),
        },
    )
    resolved = load_run(tmp_path, run["id"])

    assert result["action"] == "set-outcome-disposition"
    assert result["disposition"]["state"] == "materialized"
    assert unresolved_monitor_outcomes(tmp_path) == []
    assert resolved["revision"] == completed["revision"] + 1
    assert resolved["review_outcomes"][0]["disposition"]["state"] == "materialized"
    assert resolved["review_outcomes"][0]["disposition"]["target_ref"] == "p-materialized"


def test_legacy_completed_outcome_is_read_as_unresolved_without_rewrite(tmp_path: Path) -> None:
    subscription, run = _start_run(tmp_path)
    stage = _write_literature_stage(tmp_path)
    finish_run(
        tmp_path,
        run["id"],
        expected_run_revision=run["revision"],
        expected_subscription_revision=subscription["revision"],
        state="completed",
        stop={"reason": "completed", "rationale": "Done."},
        outputs={"literature_stage_ids": [stage.stem]},
        review_outcomes=[
            {
                "outcome_id": "legacy-outcome",
                "classification": "new",
                "subject_ref": "candidate-new",
                "rationale": "This receipt predates explicit dispositions.",
                "references": [
                    {
                        "kind": "literature-candidate",
                        "stage_id": stage.stem,
                        "candidate_id": "candidate-new",
                    }
                ],
            }
        ],
        now=_time(15, 1),
    )
    receipt = run_path(tmp_path, run["id"])
    legacy = yaml.safe_load(receipt.read_text(encoding="utf-8"))
    legacy["review_outcomes"][0].pop("disposition")
    legacy["content_digest"] = value_digest(
        {key: value for key, value in legacy.items() if key != "content_digest"}
    )
    receipt.write_text(yaml.safe_dump(legacy, sort_keys=False), encoding="utf-8")
    before = receipt.read_bytes()

    assert load_run(tmp_path, run["id"])["review_outcomes"][0].get("disposition") is None
    unresolved = unresolved_monitor_outcomes(tmp_path)
    assert len(unresolved) == 1
    assert unresolved[0]["outcome_id"] == "legacy-outcome"
    assert receipt.read_bytes() == before


def test_outcome_disposition_rejects_stale_run_binding_without_writes(tmp_path: Path) -> None:
    subscription, run = _start_run(tmp_path)
    stage = _write_literature_stage(tmp_path)
    finish_run(
        tmp_path,
        run["id"],
        expected_run_revision=run["revision"],
        expected_subscription_revision=subscription["revision"],
        state="completed",
        stop={"reason": "completed", "rationale": "Done."},
        outputs={"literature_stage_ids": [stage.stem]},
        review_outcomes=[
            {
                "outcome_id": "outcome-duplicate",
                "classification": "duplicate",
                "subject_ref": "candidate-new",
                "rationale": "Agent found this result duplicates a known candidate.",
                "references": [
                    {
                        "kind": "literature-candidate",
                        "stage_id": stage.stem,
                        "candidate_id": "candidate-new",
                    }
                ],
            }
        ],
        now=_time(15, 1),
    )
    completed = load_run(tmp_path, run["id"])
    receipt = run_path(tmp_path, run["id"])
    before = receipt.read_bytes()

    with pytest.raises(SystemExit, match="changed after"):
        set_outcome_disposition(
            tmp_path,
            run["id"],
            "outcome-duplicate",
            expected_run_revision=completed["revision"],
            expected_run_content_digest="0" * 64,
            state="acknowledged",
            actor="runtime-agent",
            reason="Duplicate result accounted for.",
        )

    assert receipt.read_bytes() == before


def test_calendar_cadence_preserves_local_wall_time_across_dst(tmp_path: Path) -> None:
    payload = _literature_subscription(
        anchor="2026-03-07T09:00:00-05:00",
    )
    payload["cadence"]["every_days"] = 1
    payload["cadence"]["timezone"] = "America/New_York"
    create_subscription(tmp_path, payload, now="2026-03-07T14:00:00Z")
    create_due_run(
        tmp_path,
        "monitor-vla",
        expected_subscription_revision=1,
        now="2026-03-07T14:00:00Z",
    )
    subscription = load_subscription(tmp_path, "monitor-vla")
    run = load_run(tmp_path, subscription["active_run_id"])
    transition_run(
        tmp_path,
        run["id"],
        expected_revision=run["revision"],
        state="running",
        now="2026-03-07T14:05:00Z",
    )
    run = load_run(tmp_path, run["id"])
    finish_run(
        tmp_path,
        run["id"],
        expected_run_revision=run["revision"],
        expected_subscription_revision=subscription["revision"],
        state="completed",
        stop={"reason": "user_stop", "rationale": "The user ended this review."},
        now="2026-03-07T15:00:00Z",
    )

    assert load_subscription(tmp_path, "monitor-vla")["next_due_at"] == "2026-03-08T13:00:00+00:00"


def test_pause_resume_and_subscription_terminal_state_are_monotonic(tmp_path: Path) -> None:
    create_subscription(tmp_path, _literature_subscription(), now=_time(1))
    set_subscription_status(
        tmp_path,
        "monitor-vla",
        expected_revision=1,
        status="paused",
        now=_time(2),
    )
    assert due_subscriptions(tmp_path, now=_time(31)) == []
    set_subscription_status(
        tmp_path,
        "monitor-vla",
        expected_revision=2,
        status="active",
        now=_time(31),
    )
    assert due_subscriptions(tmp_path, now=_time(31))[0]["subscription_revision"] == 3
    set_subscription_status(
        tmp_path,
        "monitor-vla",
        expected_revision=3,
        status="completed",
        now=_time(31),
    )
    with pytest.raises(SystemExit, match="cannot be reopened"):
        set_subscription_status(
            tmp_path,
            "monitor-vla",
            expected_revision=4,
            status="active",
            now=_time(31),
        )


def test_blocked_retry_state_is_resumable_but_terminal_run_is_not(tmp_path: Path) -> None:
    subscription, run = _start_run(tmp_path)
    transition_run(
        tmp_path,
        run["id"],
        expected_revision=run["revision"],
        state="blocked",
        stop={"reason": "blocked_no_search_tool", "rationale": "No search tool is available."},
        now=_time(15, 1),
    )
    blocked = load_run(tmp_path, run["id"])
    transition_run(
        tmp_path,
        run["id"],
        expected_revision=blocked["revision"],
        state="running",
        now=_time(15, 2),
    )
    running = load_run(tmp_path, run["id"])
    finish_run(
        tmp_path,
        run["id"],
        expected_run_revision=running["revision"],
        expected_subscription_revision=subscription["revision"],
        state="completed",
        stop={"reason": "user_stop", "rationale": "The user stopped this run."},
        now=_time(15, 3),
    )
    terminal = load_run(tmp_path, run["id"])
    with pytest.raises(SystemExit, match="cannot transition from completed"):
        transition_run(
            tmp_path,
            run["id"],
            expected_revision=terminal["revision"],
            state="running",
            now=_time(15, 4),
        )


def test_stale_subscription_and_run_revisions_fail_closed(tmp_path: Path) -> None:
    subscription, run = _start_run(tmp_path)
    with pytest.raises(SystemExit, match="revision conflict"):
        set_subscription_status(
            tmp_path,
            "monitor-vla",
            expected_revision=1,
            status="paused",
            now=_time(15),
        )
    with pytest.raises(SystemExit, match="revision conflict"):
        transition_run(
            tmp_path,
            run["id"],
            expected_revision=1,
            state="blocked",
            stop={"reason": "blocked", "rationale": "Blocked."},
            now=_time(15),
        )
    assert load_subscription(tmp_path, "monitor-vla") == subscription
    assert load_run(tmp_path, run["id"]) == run


def test_two_concurrent_due_creators_produce_one_frozen_run(tmp_path: Path) -> None:
    create_subscription(tmp_path, _literature_subscription(), now=_time(1))

    def create() -> str:
        return create_due_run(
            tmp_path,
            "monitor-vla",
            expected_subscription_revision=1,
            now=_time(15),
        ).name

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = [future for future in (pool.submit(create), pool.submit(create))]
    outcomes: list[str] = []
    for future in results:
        try:
            outcomes.append(future.result())
        except SystemExit as exc:
            outcomes.append(str(exc))

    assert sum(item.endswith(".yaml") for item in outcomes) == 1
    assert len(list((tmp_path / "kb/monitoring/runs").glob("*.yaml"))) == 1
    assert load_subscription(tmp_path, "monitor-vla")["revision"] == 2


def test_literature_and_candidate_references_fail_closed(tmp_path: Path) -> None:
    subscription, run = _start_run(tmp_path)
    stage = _write_literature_stage(tmp_path)
    bad_outcome = [
        {
            "outcome_id": "bad-candidate",
            "classification": "worth_reviewing",
            "subject_ref": "ghost",
            "rationale": "Agent supplied a missing candidate.",
            "references": [
                {
                    "kind": "literature-candidate",
                    "stage_id": stage.stem,
                    "candidate_id": "candidate-missing",
                }
            ],
        }
    ]

    with pytest.raises(SystemExit, match="unknown literature candidate"):
        finish_run(
            tmp_path,
            run["id"],
            expected_run_revision=run["revision"],
            expected_subscription_revision=subscription["revision"],
            state="completed",
            stop={"reason": "completed", "rationale": "Done."},
            outputs={"literature_stage_ids": [stage.stem]},
            review_outcomes=bad_outcome,
            now=_time(16),
        )
    assert load_run(tmp_path, run["id"])["state"] == "running"


def test_completion_rejects_incomplete_or_unlinked_literature_stage(tmp_path: Path) -> None:
    subscription, run = _start_run(tmp_path)
    stage = _write_literature_stage(tmp_path)
    stage_doc = yaml.safe_load(stage.read_text(encoding="utf-8"))
    stage_doc["stop"] = {"reason": "in_progress"}
    stage.write_text(yaml.safe_dump(stage_doc, sort_keys=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="not complete"):
        finish_run(
            tmp_path,
            run["id"],
            expected_run_revision=run["revision"],
            expected_subscription_revision=subscription["revision"],
            state="completed",
            stop={"reason": "completed", "rationale": "Done."},
            outputs={"literature_stage_ids": [stage.stem]},
            now=_time(16),
        )

    stage = _write_literature_stage(tmp_path)
    with pytest.raises(SystemExit, match="not linked by this run"):
        finish_run(
            tmp_path,
            run["id"],
            expected_run_revision=run["revision"],
            expected_subscription_revision=subscription["revision"],
            state="completed",
            stop={"reason": "completed", "rationale": "Done."},
            outputs={"literature_stage_ids": []},
            review_outcomes=[
                {
                    "outcome_id": "unlinked-stage",
                    "classification": "new",
                    "subject_ref": "candidate-new",
                    "rationale": "Agent referred to an unlinked run.",
                    "references": [
                        {
                            "kind": "literature-candidate",
                            "stage_id": stage.stem,
                            "candidate_id": "candidate-new",
                        }
                    ],
                }
            ],
            now=_time(16),
        )


def test_contradiction_requires_both_evidence_sides(tmp_path: Path) -> None:
    subscription, run = _start_run(tmp_path)
    stage = _write_literature_stage(tmp_path)
    with pytest.raises(SystemExit, match="both sides"):
        finish_run(
            tmp_path,
            run["id"],
            expected_run_revision=run["revision"],
            expected_subscription_revision=subscription["revision"],
            state="completed",
            stop={"reason": "completed", "rationale": "Done."},
            outputs={"literature_stage_ids": [stage.stem]},
            review_outcomes=[
                {
                    "outcome_id": "possible-conflict",
                    "classification": "contradiction_candidate",
                    "subject_ref": "candidate-new",
                    "rationale": "Agent identified a possible contradiction.",
                    "references": [
                        {
                            "kind": "literature-candidate",
                            "stage_id": stage.stem,
                            "candidate_id": "candidate-new",
                        }
                    ],
                }
            ],
            now=_time(16),
        )

    duplicate = {
        "kind": "literature-candidate",
        "stage_id": stage.stem,
        "candidate_id": "candidate-new",
    }
    with pytest.raises(SystemExit, match="both sides"):
        finish_run(
            tmp_path,
            run["id"],
            expected_run_revision=run["revision"],
            expected_subscription_revision=subscription["revision"],
            state="completed",
            stop={"reason": "completed", "rationale": "Done."},
            outputs={"literature_stage_ids": [stage.stem]},
            review_outcomes=[
                {
                    "outcome_id": "duplicate-conflict",
                    "classification": "contradiction_candidate",
                    "subject_ref": "candidate-new",
                    "rationale": "The same reference cannot represent both sides.",
                    "references": [duplicate, duplicate],
                }
            ],
            now=_time(16),
        )


def test_artifact_reference_requires_digest_and_verbatim_quote(tmp_path: Path) -> None:
    subscription, run = _start_run(tmp_path)
    stage = _write_literature_stage(tmp_path)
    artifact = tmp_path / "kb/units/papers/p-old/note.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("The older result reports lower success.\n", encoding="utf-8")
    common = {
        "outcome_id": "possible-conflict",
        "classification": "contradiction_candidate",
        "subject_ref": "candidate-new",
        "rationale": "Agent identified a possible contradiction.",
        "references": [
            {
                "kind": "literature-candidate",
                "stage_id": stage.stem,
                "candidate_id": "candidate-new",
            },
            {
                "kind": "artifact",
                "path": artifact.relative_to(tmp_path).as_posix(),
                "byte_sha256": file_sha256(artifact),
                "locator": "sentence 1",
                "quote": "not present",
            },
        ],
    }
    with pytest.raises(SystemExit, match="not verbatim"):
        finish_run(
            tmp_path,
            run["id"],
            expected_run_revision=run["revision"],
            expected_subscription_revision=subscription["revision"],
            state="completed",
            stop={"reason": "completed", "rationale": "Done."},
            outputs={"literature_stage_ids": [stage.stem]},
            review_outcomes=[common],
            now=_time(16),
        )


def test_survey_binding_is_byte_bound_and_required_for_survey_run(tmp_path: Path) -> None:
    payload = _survey_subscription(tmp_path)
    create_subscription(tmp_path, payload, now=_time(1))
    create_due_run(
        tmp_path,
        "monitor-survey",
        expected_subscription_revision=1,
        now=_time(31),
    )
    subscription = load_subscription(tmp_path, "monitor-survey")
    run = load_run(tmp_path, subscription["active_run_id"])
    transition_run(
        tmp_path,
        run["id"],
        expected_revision=run["revision"],
        state="running",
        now=_time(31),
    )
    run = load_run(tmp_path, run["id"])
    survey = tmp_path / payload["target"]["survey_path"]
    survey.write_text("slug: changed\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="digest is stale"):
        finish_run(
            tmp_path,
            run["id"],
            expected_run_revision=run["revision"],
            expected_subscription_revision=subscription["revision"],
            state="completed",
            stop={"reason": "completed", "rationale": "Freshness checked."},
            outputs={
                "survey_bindings": [
                    {
                        "path": survey.relative_to(tmp_path).as_posix(),
                        "byte_sha256": payload["target"]["survey_sha256"],
                    }
                ]
            },
            now=_time(31, 1),
        )


def test_survey_subscription_requires_current_canonical_binding(tmp_path: Path) -> None:
    payload = _survey_subscription(tmp_path)
    payload["target"]["survey_sha256"] = "0" * 64
    with pytest.raises(SystemExit, match="digest is stale"):
        create_subscription(tmp_path, payload, now=_time(1))


def test_completed_outputs_are_bound_to_frozen_monitor_target_and_bytes(tmp_path: Path) -> None:
    subscription, run = _start_run(tmp_path)
    stage = _write_literature_stage(tmp_path)
    stage_doc = yaml.safe_load(stage.read_text(encoding="utf-8"))
    stage_doc["monitor_binding"]["task_digest"] = "0" * 64
    stage.write_text(yaml.safe_dump(stage_doc, sort_keys=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="another frozen run"):
        finish_run(
            tmp_path,
            run["id"],
            expected_run_revision=run["revision"],
            expected_subscription_revision=subscription["revision"],
            state="completed",
            stop={"reason": "completed", "rationale": "Done."},
            outputs={"literature_stage_ids": [stage.stem]},
            now=_time(16),
        )

    stage_doc["monitor_binding"] = monitor_task_binding(run)
    stage.write_text(yaml.safe_dump(stage_doc, sort_keys=False), encoding="utf-8")
    finish_run(
        tmp_path,
        run["id"],
        expected_run_revision=run["revision"],
        expected_subscription_revision=subscription["revision"],
        state="completed",
        stop={"reason": "completed", "rationale": "Done."},
        outputs={"literature_stage_ids": [stage.stem]},
        now=_time(16),
    )
    stage.write_text(stage.read_text(encoding="utf-8") + "tampered: true\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="byte binding"):
        load_run(tmp_path, run["id"])


def test_terminal_run_receipt_and_unit_coverage_fail_closed(tmp_path: Path) -> None:
    unit_id = "p-monitor-unit-000001"
    unit = tmp_path / f"kb/units/papers/{unit_id}/record.yaml"
    unit.parent.mkdir(parents=True)
    unit.write_text(yaml.safe_dump({"id": unit_id, "kind": "paper"}), encoding="utf-8")
    create_subscription(
        tmp_path,
        {
            "subscription_id": "monitor-unit",
            "kind": "unit-recheck",
            "target": {"unit_ids": [unit_id]},
            "scope": {},
            "cadence": {"every_days": 1, "timezone": "UTC", "anchor_at": "2026-07-01T00:00:00Z"},
        },
        now=_time(1),
    )
    create_due_run(tmp_path, "monitor-unit", expected_subscription_revision=1, now=_time(2))
    subscription = load_subscription(tmp_path, "monitor-unit")
    run = load_run(tmp_path, subscription["active_run_id"])
    transition_run(tmp_path, run["id"], expected_revision=run["revision"], state="running", now=_time(2))
    run = load_run(tmp_path, run["id"])
    with pytest.raises(SystemExit, match="cover every frozen target unit"):
        finish_run(
            tmp_path,
            run["id"],
            expected_run_revision=run["revision"],
            expected_subscription_revision=subscription["revision"],
            state="completed",
            stop={"reason": "completed", "rationale": "Checked."},
            outputs={},
            now=_time(2),
        )
    finish_run(
        tmp_path,
        run["id"],
        expected_run_revision=run["revision"],
        expected_subscription_revision=subscription["revision"],
        state="completed",
        stop={"reason": "completed", "rationale": "Checked."},
        outputs={"unit_ids": [unit_id]},
        now=_time(2),
    )
    receipt = run_path(tmp_path, run["id"])
    tampered = yaml.safe_load(receipt.read_text(encoding="utf-8"))
    tampered["outputs"] = {"raw_provider_payload": "secret"}
    receipt.write_text(yaml.safe_dump(tampered, sort_keys=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="content digest|unsupported"):
        load_run(tmp_path, run["id"])


def test_finish_rejects_due_window_tamper_without_revision_change(tmp_path: Path) -> None:
    subscription, run = _start_run(tmp_path)
    stage = _write_literature_stage(tmp_path)
    path = subscription_path(tmp_path, "monitor-vla")
    tampered = yaml.safe_load(path.read_text(encoding="utf-8"))
    tampered["next_due_at"] = "2026-07-29T00:00:00+00:00"
    path.write_text(yaml.safe_dump(tampered, sort_keys=False), encoding="utf-8")

    with pytest.raises(SystemExit, match="due window changed"):
        finish_run(
            tmp_path,
            run["id"],
            expected_run_revision=run["revision"],
            expected_subscription_revision=subscription["revision"],
            state="completed",
            stop={"reason": "completed", "rationale": "Done."},
            outputs={"literature_stage_ids": [stage.stem]},
            now=_time(16),
        )


def test_symlinked_subscription_and_reference_paths_are_rejected(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    subscriptions = tmp_path / "kb/monitoring/subscriptions"
    subscriptions.parent.mkdir(parents=True)
    subscriptions.symlink_to(outside, target_is_directory=True)
    with pytest.raises(SystemExit, match="symlink|outside kb"):
        create_subscription(tmp_path, _literature_subscription(), now=_time(1))

    safe_root = tmp_path / "safe"
    safe_root.mkdir()
    survey_payload = _survey_subscription(safe_root)
    survey = safe_root / survey_payload["target"]["survey_path"]
    create_subscription(safe_root, survey_payload, now=_time(1))
    real = safe_root / "outside-survey.yaml"
    real.write_text(survey.read_text(encoding="utf-8"), encoding="utf-8")
    survey.unlink()
    survey.symlink_to(real)
    create_due_run(
        safe_root,
        "monitor-survey",
        expected_subscription_revision=1,
        now=_time(31),
    )
    subscription = load_subscription(safe_root, "monitor-survey")
    run = load_run(safe_root, subscription["active_run_id"])
    transition_run(
        safe_root,
        run["id"],
        expected_revision=run["revision"],
        state="running",
        now=_time(31),
    )
    run = load_run(safe_root, run["id"])
    with pytest.raises(SystemExit, match="symlink|escapes"):
        finish_run(
            safe_root,
            run["id"],
            expected_run_revision=run["revision"],
            expected_subscription_revision=subscription["revision"],
            state="completed",
            stop={"reason": "completed", "rationale": "Freshness checked."},
            outputs={
                "survey_bindings": [
                    {
                        "path": survey.relative_to(safe_root).as_posix(),
                        "byte_sha256": file_sha256(real),
                    }
                ]
            },
            now=_time(31, 1),
        )


def test_failed_completion_event_write_rolls_back_run_subscription_and_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monitoring = importlib.import_module("research.monitoring")
    subscription, run = _start_run(tmp_path)
    stage = _write_literature_stage(tmp_path)
    before_run = run_path(tmp_path, run["id"]).read_bytes()
    before_subscription = subscription_path(tmp_path, "monitor-vla").read_bytes()
    event_path = tmp_path / "kb/programs/program-vla/workflow/reporting-events.yaml"
    assert not event_path.exists()
    original_write = monitoring.write_yaml_if_changed

    def fail_event(path: Path, value: object) -> None:
        if path == event_path:
            raise RuntimeError("injected reporting-event failure")
        original_write(path, value)

    monkeypatch.setattr(monitoring, "write_yaml_if_changed", fail_event)
    with pytest.raises(RuntimeError, match="injected"):
        monitoring.finish_run(
            tmp_path,
            run["id"],
            expected_run_revision=run["revision"],
            expected_subscription_revision=subscription["revision"],
            state="completed",
            stop={"reason": "completed", "rationale": "Done."},
            outputs={"literature_stage_ids": [stage.stem]},
            now=_time(16),
        )
    assert run_path(tmp_path, run["id"]).read_bytes() == before_run
    assert subscription_path(tmp_path, "monitor-vla").read_bytes() == before_subscription
    assert not event_path.exists()


def test_module_has_no_network_client_or_content_judgement_heuristic() -> None:
    import research.monitoring as monitoring

    source = inspect.getsource(monitoring)
    for forbidden in (
        "urllib",
        "requests",
        "httpx",
        "socket",
        "urlopen",
        "citation_count",
        "semantic_score",
        "novelty_score",
    ):
        assert forbidden not in source


def test_research_monitor_skill_metadata_is_valid() -> None:
    skill = REPO_ROOT / ".agents" / "skills" / "research-monitor"
    assert validate_skill(skill) == []
