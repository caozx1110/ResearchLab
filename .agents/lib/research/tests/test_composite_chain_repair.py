from __future__ import annotations

import copy
from pathlib import Path

import pytest

import research.surveys as surveys


def _binding(stage_id: str, *, refs: list[dict], facts: dict) -> dict:
    return {
        "schema_version": 1,
        "kind": surveys.COMPOSITE_BINDING_KIND,
        "stage_id": stage_id,
        "refs": refs,
        "artifacts": [
            {
                "role": "test",
                "path": "kb/test.yaml",
                "artifact_kind": "test",
                "artifact_id": stage_id,
                "content_sha256": "a" * 64,
            }
        ],
        "facts": facts,
        "binding_digest": "b" * 64,
    }


def _completed_state() -> dict:
    bindings = {
        "search": _binding(
            "search",
            refs=[{"kind": "literature-search-stage", "stage_id": "search-1"}],
            facts={},
        ),
        "selection": _binding(
            "selection",
            refs=[
                {
                    "kind": "literature-search-selection",
                    "stage_id": "search-1",
                    "candidate_ids": ["candidate-1"],
                    "user_authorization": "Keep candidate-1.",
                    "authorization_source": "user_message",
                }
            ],
            facts={
                "selected_candidates": [{"candidate_id": "candidate-1"}],
                "authorization_digest": "auth-1",
            },
        ),
        "source_intake": _binding(
            "source_intake",
            refs=[
                {
                    "kind": "materialized-units",
                    "stage_id": "search-1",
                    "units": [{"kind": "paper", "id": "paper-1"}],
                }
            ],
            facts={
                "units": [
                    {
                        "kind": "paper",
                        "id": "paper-1",
                        "candidate_id": "candidate-1",
                        "authorization_digest": "auth-1",
                    }
                ]
            },
        ),
        "unit_analysis": _binding(
            "unit_analysis",
            refs=[
                {
                    "kind": "confirmed-units",
                    "stage_id": "search-1",
                    "units": [{"kind": "paper", "id": "paper-1"}],
                }
            ],
            facts={},
        ),
        "synthesis": _binding(
            "synthesis",
            refs=[{"kind": "verified-survey", "slug": "survey-1", "mode": "survey"}],
            facts={"unit_ids": ["paper-1"]},
        ),
        "review_confirmation": _binding(
            "review_confirmation",
            refs=[{"kind": "confirmed-survey", "slug": "survey-1", "mode": "survey"}],
            facts={},
        ),
        "report_consumption": _binding(
            "report_consumption",
            refs=[
                {
                    "kind": "not-applicable-report-consumption",
                    "reason": "no_linked_programs",
                    "survey_slug": "survey-1",
                    "survey_mode": "survey",
                }
            ],
            facts={},
        ),
    }
    return {
        "stages": [
            {"id": stage_id, "status": "completed", "outputs": [bindings[stage_id]]}
            for stage_id in surveys.COMPOSITE_SURVEY_STAGES
        ]
    }


@pytest.mark.parametrize(
    ("expected_stage", "mutate"),
    [
        (
            "selection",
            lambda state: state["stages"][1]["outputs"][0]["refs"][0].update(
                stage_id="other-search"
            ),
        ),
        (
            "source_intake",
            lambda state: state["stages"][2]["outputs"][0]["facts"]["units"][0].update(
                authorization_digest="other-auth"
            ),
        ),
        (
            "unit_analysis",
            lambda state: state["stages"][3]["outputs"][0]["refs"][0]["units"][0].update(
                id="paper-2"
            ),
        ),
        (
            "synthesis",
            lambda state: state["stages"][4]["outputs"][0]["facts"].update(
                unit_ids=["paper-2"]
            ),
        ),
        (
            "review_confirmation",
            lambda state: state["stages"][5]["outputs"][0]["refs"][0].update(
                slug="survey-2"
            ),
        ),
        (
            "report_consumption",
            lambda state: state["stages"][6]["outputs"][0]["refs"][0].update(
                survey_slug="survey-2"
            ),
        ),
    ],
)
def test_chain_repair_starts_at_the_affected_downstream_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expected_stage: str,
    mutate,
) -> None:
    state = copy.deepcopy(_completed_state())
    mutate(state)
    monkeypatch.setattr(surveys, "_completed_binding_violations", lambda _root, _stage: [])

    assert surveys._first_invalid_completed_stage(tmp_path, state) == expected_stage
    projected = surveys.composite_survey_repair_projection(tmp_path, state)
    assert projected["current_stage"] == expected_stage
    expected_index = surveys.COMPOSITE_SURVEY_STAGES.index(expected_stage)
    assert all(
        stage["status"] == "completed" for stage in projected["stages"][:expected_index]
    )
    assert projected["stages"][expected_index]["status"] == "blocked"
