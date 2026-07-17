"""Paper-analyst machinery tests (SSOT Principle 1 / §3.2).

We cannot headless-test "an agent filled *good* understanding" (that needs a real
agent). So these test the MACHINERY the script owns:

  * screen --phase prepare emits a fillable structure with NO keyword-driven grading;
  * complete-note --phase prepare emits the 5-element fillable skeleton;
  * feeding synthetic filled content with legit verbatim evidence -> validates,
    clears the substance gate, and persists (core_content non-empty, note.md written);
  * feeding fabricated evidence -> rejected, with the offending element named;
  * feeding empty/template fill -> the substance gate blocks confirm.

The evidence quotes are copied verbatim from a synthetic parse-cache so verification
is deterministic and offline.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.confirm import confirm_unit, has_substantive_content
from research.core import ensure_workspace, record_path, write_record
from research.evidence import attach_claims, build_verification_receipt
from research.records import kind_payload_skeleton


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_paper_module():
    script = _project_root() / ".agents" / "skills" / "paper-analyst" / "scripts" / "paper.py"
    spec = importlib.util.spec_from_file_location("paper_analyst_script_under_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# Synthetic parse-cache: known verbatim text on two labelled PDF pages.
PAGE1 = (
    "We study vision language action policies for robot manipulation. "
    "Existing imitation policies fail to generalize to unseen objects."
)
PAGE2 = (
    "Our method predicts short action chunks with a flow matching head. "
    "On the real robot benchmark we report a higher success rate than the baseline. "
    "A key limitation is brittle behaviour under heavy occlusion."
)

JUDGEMENT_INFO_TYPES = ["evaluation", "fact", "inference", "unverified", "user_opinion"]


def _write_parse_cache(unit_dir: Path, paper_id: str) -> Path:
    cache = unit_dir / "parse-cache.yaml"
    write_yaml_if_changed(
        cache,
        {
            "paper_id": paper_id,
            "source_type": "pdf",
            "locator_kind": "page",
            "chunks": [
                {"label": "source.pdf:page-1", "text": PAGE1, "page": 1},
                {"label": "source.pdf:page-2", "text": PAGE2, "page": 2},
            ],
        },
    )
    return cache


def _paper_record(paper_id: str, *, info_types=None, core_content=None) -> dict:
    record = {
        "id": paper_id,
        "kind": "paper",
        "title": "Synthetic VLA Paper",
        "status": "screened",
        "maturity": "lightweight",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": list(info_types or JUDGEMENT_INFO_TYPES),
        "topics": ["vision-language-action"],
        "tags": ["manipulation"],
        "source": {"original_uri": "", "file_hash": ""},
        "payload": kind_payload_skeleton("paper", "Synthetic VLA Paper"),
    }
    if core_content:
        record["payload"]["core_content"].update(core_content)
    return record


def _legit_note_fill() -> dict:
    """A synthetic 5-element fill whose every quote is verbatim from the cache."""
    return {
        "elements": [
            {
                "element": "motivation",
                "claim_type": "inference",
                "content": "Imitation policies do not generalize to novel objects, motivating a new approach.",
                "evidence_refs": [
                    {"source_unit_id": "p-x", "artifact": "parse-cache.yaml", "locator": "page=1",
                     "quote": "fail to generalize to unseen objects", "summary": "generalization gap"}
                ],
            },
            {
                "element": "method",
                "claim_type": "inference",
                "content": "It predicts short action chunks via a flow-matching head.",
                "evidence_refs": [
                    {"source_unit_id": "p-x", "artifact": "parse-cache.yaml", "locator": "page=2",
                     "quote": "predicts short action chunks with a flow matching head", "summary": "method core"}
                ],
            },
            {
                "element": "experiment",
                "claim_type": "evaluation",
                "content": "On a real-robot benchmark it beats the baseline success rate.",
                "evidence_refs": [
                    {"source_unit_id": "p-x", "artifact": "parse-cache.yaml", "locator": "page=2",
                     "quote": "higher success rate than the baseline", "summary": "headline result"}
                ],
            },
            {
                "element": "limitation",
                "claim_type": "evaluation",
                "content": "Behaviour is brittle under heavy occlusion.",
                "evidence_refs": [
                    {"source_unit_id": "p-x", "artifact": "parse-cache.yaml", "locator": "page=2",
                     "quote": "brittle behaviour under heavy occlusion", "summary": "failure mode"}
                ],
            },
            {
                "element": "insight",
                "claim_type": "inference",
                "content": "Chunked action prediction plausibly helps because it smooths short horizons.",
                "evidence_refs": [
                    {"source_unit_id": "p-x", "artifact": "parse-cache.yaml", "locator": "page=2",
                     "quote": "predicts short action chunks", "summary": "why it might work"}
                ],
            },
        ]
    }


def _typed_note_fill(paper, paper_type: str) -> dict:
    quote_by_element = {
        "motivation": "fail to generalize to unseen objects",
        "task_design": "real robot benchmark",
        "metrics": "higher success rate than the baseline",
        "coverage_limitation": "brittle behaviour under heavy occlusion",
        "scope": "vision language action policies for robot manipulation",
        "taxonomy": "predicts short action chunks with a flow matching head",
        "trends": "higher success rate than the baseline",
        "gaps": "brittle behaviour under heavy occlusion",
        "insight": "flow matching head",
    }
    return {
        "elements": [
            {
                "element": name,
                "claim_type": paper.ELEMENT_CLAIM_TYPE[name],
                "content": f"Agent-authored {name.replace('_', ' ')} synthesis.",
                "evidence_refs": [
                    {
                        "source_unit_id": "p-x",
                        "artifact": "parse-cache.yaml",
                        "locator": "page=1" if name in {"motivation", "scope"} else "page=2",
                        "quote": quote_by_element[name],
                        "summary": name,
                    }
                ],
            }
            for name in paper.ELEMENT_SETS[paper_type]
        ]
    }


# --------------------------------------------------------------------------- #
# 1. screen --phase prepare produces a fillable structure with NO grading.
# --------------------------------------------------------------------------- #
def test_screen_scaffold_has_no_count_driven_grading(tmp_path: Path) -> None:
    paper = _load_paper_module()
    record = _paper_record("p-screen-000001")
    chunks = [{"label": "source.pdf:page-1", "text": PAGE1, "page": 1}]

    scaffold = paper.build_screening_scaffold(record, chunks, "page", digest_chunks=6, digest_chars=800)

    # Judgement fields exist but are left BLANK for the agent — the script does not grade.
    assert scaffold["worth_deep_reading"] == ""
    assert scaffold["paper_type"] == ""
    assert scaffold["judgement_reason"] == []
    assert scaffold["relevance_to_current_research"] == ""
    assert scaffold["claims"] == []
    # No count->grade rating fields leak in (novelty/result_strength/experiment_signal...).
    for banned in ("novelty_signal", "result_strength", "experiment_signal", "reliability_signal",
                   "relevance_signal", "novelty", "experiment_quality"):
        assert banned not in scaffold
    # keyword mentions are kept only as an explicitly-non-judgemental hint.
    assert "keyword_mentions" in scaffold["agent_hints"]
    assert "NOT" in scaffold["agent_hints"]["note"]
    # evidence digest carries a citable locator, not a judgement.
    assert scaffold["evidence_digest"]
    assert scaffold["evidence_digest"][0]["locator"] == "page=1"
    assert scaffold["evidence_digest"][0]["artifact"] == "parse-cache.yaml"


def test_paper_source_has_no_count_grading_symbols() -> None:
    """Anti-pattern guard: no `_grade` / `len(...hits)` count->judgement logic remains."""
    import re

    src = (_project_root() / ".agents" / "skills" / "paper-analyst" / "scripts" / "paper.py").read_text("utf-8")
    assert "_grade" not in src
    assert not re.search(r"len\([^)]*hits[^)]*\)", src)


# --------------------------------------------------------------------------- #
# 2. complete-note --phase prepare produces the 5-element fillable skeleton.
# --------------------------------------------------------------------------- #
def test_note_scaffold_has_five_blank_elements(tmp_path: Path) -> None:
    paper = _load_paper_module()
    record = _paper_record("p-note-000001")
    chunks = [{"label": "source.pdf:page-1", "text": PAGE1, "page": 1}]

    scaffold = paper.build_note_scaffold(record, chunks, "page", digest_chunks=8, digest_chars=800)

    names = [el["element"] for el in scaffold["elements"]]
    assert names == ["motivation", "method", "experiment", "limitation", "insight"]
    for el in scaffold["elements"]:
        assert el["content"] == ""          # script authors nothing
        assert el["evidence_refs"] == []     # agent must attach evidence
    assert scaffold["fill_contract"]["required_elements"] == names
    assert "evidence_ref_format" in scaffold["fill_contract"]


@pytest.mark.parametrize(
    ("paper_type", "expected"),
    [
        ("benchmark", ["motivation", "task_design", "metrics", "coverage_limitation", "insight"]),
        ("survey", ["scope", "taxonomy", "trends", "gaps", "insight"]),
    ],
)
def test_note_scaffold_and_verify_follow_paper_type(
    tmp_path: Path, paper_type: str, expected: list[str]
) -> None:
    paper = _load_paper_module()
    unit_dir = tmp_path / paper_type
    unit_dir.mkdir()
    _write_parse_cache(unit_dir, "p-x")
    record = _paper_record(f"p-{paper_type}")
    record["payload"]["quick_screen"]["paper_type"] = paper_type

    scaffold = paper.build_note_scaffold(record, [], "page", digest_chunks=1, digest_chars=10)
    assert scaffold["paper_type"] == paper_type
    assert scaffold["fill_contract"]["required_elements"] == expected
    assert [element["element"] for element in scaffold["elements"]] == expected

    violations, claims = paper.verify_note_fill(_typed_note_fill(paper, paper_type), unit_dir, record)
    assert violations == [], violations
    paper._apply_note_fill_to_payload(record, claims)
    assert has_substantive_content(record, "paper") is True
    note_md = paper.render_note_md(record, claims)
    for name in expected:
        assert f"## {paper.ELEMENT_HEADING[name]}" in note_md

    method_fill = _legit_note_fill()
    violations, _ = paper.verify_note_fill(method_fill, unit_dir, record)
    assert violations
    assert any("unexpected for selected paper type" in violation for violation in violations)
    assert any("missing" in violation for violation in violations)


def test_missing_paper_type_keeps_method_system_contract(tmp_path: Path) -> None:
    paper = _load_paper_module()
    record = _paper_record("p-default")
    assert paper.elements_for(record) == paper.NOTE_ELEMENTS
    scaffold = paper.build_note_scaffold(record, [], "page", digest_chunks=1, digest_chars=10)
    assert [element["element"] for element in scaffold["elements"]] == list(paper.NOTE_ELEMENTS)


# --------------------------------------------------------------------------- #
# 3. Legit filled content + verbatim evidence -> validates, fills, persists.
# --------------------------------------------------------------------------- #
def test_note_fill_legit_evidence_validates_and_clears_substance_gate(tmp_path: Path) -> None:
    paper = _load_paper_module()
    record = _paper_record("p-fill-legit-1")
    unit_dir = record_path(tmp_path, "paper", record["id"]).parent
    unit_dir.mkdir(parents=True)
    _write_parse_cache(unit_dir, "p-x")

    violations, claims = paper.verify_note_fill(_legit_note_fill(), unit_dir)
    assert violations == [], violations
    assert len(claims) == 5
    for claim in claims:
        for ref in claim["evidence_refs"]:
            ref["source_unit_id"] = record["id"]

    assert has_substantive_content(record, "paper") is False  # empty before fill
    paper._apply_note_fill_to_payload(record, claims)
    attach_claims(record["payload"], claims)
    build_verification_receipt(record, unit_dir)

    cc = record["payload"]["core_content"]
    assert cc["motivation"] and cc["method"] and cc["why_it_might_work"]
    assert cc["changes_and_effects"]  # experiment -> list field
    assert record["payload"]["critique"]["weak_spots"]  # limitation -> critique
    assert has_substantive_content(record, "paper") is True

    # note.md renders every element + its evidence citation.
    note_md = paper.render_note_md(record, claims)
    assert "## Motivation" in note_md and "## Insight" in note_md
    assert "higher success rate than the baseline" in note_md

    # Substance gate now passes: a real human can confirm the judgement-track paper.
    confirmed = confirm_unit(
        record, "paper", confirmed_by="czx", evidence=["kb/programs/p/decision-log.md"],
        user_authorization="I confirm this paper analysis.", authorization_source="user_message",
        project_root=tmp_path,
    )
    assert confirmed["confirmation_status"] == "confirmed"


# --------------------------------------------------------------------------- #
# 4. Fabricated evidence -> rejected, offending element named.
# --------------------------------------------------------------------------- #
def test_note_fill_fabricated_evidence_is_rejected_by_element(tmp_path: Path) -> None:
    paper = _load_paper_module()
    unit_dir = tmp_path / "unit"
    unit_dir.mkdir()
    _write_parse_cache(unit_dir, "p-x")

    fill = _legit_note_fill()
    # Corrupt the method element's quote so it is not verbatim in the artifact.
    fill["elements"][1]["evidence_refs"][0]["quote"] = "a diffusion transformer we never mentioned"

    violations, _claims = paper.verify_note_fill(fill, unit_dir)
    assert violations
    assert any("element 'method'" in v and "not verbatim" in v for v in violations), violations
    # Untouched elements are not falsely blamed.
    assert not any("element 'motivation'" in v for v in violations)


def test_note_fill_wrong_page_locator_is_rejected(tmp_path: Path) -> None:
    paper = _load_paper_module()
    unit_dir = tmp_path / "unit"
    unit_dir.mkdir()
    _write_parse_cache(unit_dir, "p-x")

    fill = _legit_note_fill()
    # motivation quote is verbatim but on page 1; cite page 2 -> locator mismatch.
    fill["elements"][0]["evidence_refs"][0]["locator"] = "page=2"

    violations, _claims = paper.verify_note_fill(fill, unit_dir)
    assert any("element 'motivation'" in v for v in violations), violations


# --------------------------------------------------------------------------- #
# 5. Empty / template fill -> rejected, and the substance gate blocks confirm.
# --------------------------------------------------------------------------- #
def test_empty_note_fill_is_rejected_and_hollow_confirm_is_blocked(tmp_path: Path) -> None:
    paper = _load_paper_module()
    unit_dir = tmp_path / "unit"
    unit_dir.mkdir()
    _write_parse_cache(unit_dir, "p-x")

    # A scaffold-shaped fill with blank content (what the agent produced nothing for).
    empty_fill = paper.build_note_scaffold(_paper_record("p-x"), [], "page", digest_chunks=1, digest_chars=10)
    violations, _claims = paper.verify_note_fill(empty_fill, unit_dir)
    assert violations
    assert any("empty content" in v for v in violations)
    assert any("no evidence_refs" in v for v in violations)

    # And the confirmation substance gate independently refuses a hollow paper.
    hollow = _paper_record("p-hollow-000001")  # core_content untouched == empty
    assert has_substantive_content(hollow, "paper") is False
    with pytest.raises(SystemExit, match="hollow"):
        confirm_unit(hollow, "paper", confirmed_by="czx", evidence=["kb/programs/p/log.md"])


def test_screen_fill_requires_evidence_backed_judgement(tmp_path: Path) -> None:
    paper = _load_paper_module()
    unit_dir = tmp_path / "unit"
    unit_dir.mkdir()
    _write_parse_cache(unit_dir, "p-x")

    # worth=yes but no backing claim -> rejected.
    payload = {"worth_deep_reading": "yes", "judgement_reason": ["looks relevant"], "claims": []}
    violations = paper.verify_screening_fill(payload, unit_dir)
    assert any("no evidence-backed claims" in v for v in violations)

    # worth=yes with a verbatim-grounded claim -> clean.
    payload_ok = {
        "worth_deep_reading": "yes",
        "judgement_reason": ["directly on VLA manipulation"],
        "claims": [
            {
                "id": "claim-screen-1",
                "text": "It targets VLA manipulation.",
                "claim_type": "evaluation",
                "confirmation_status": "pending_user_confirmation",
                "evidence_refs": [
                    {"source_unit_id": "p-x", "artifact": "parse-cache.yaml", "locator": "page=1",
                     "quote": "vision language action policies for robot manipulation", "summary": "scope"}
                ],
            }
        ],
    }
    assert paper.verify_screening_fill(payload_ok, unit_dir) == []

    # blank worth (agent did not judge) -> rejected.
    assert paper.verify_screening_fill({"worth_deep_reading": "", "claims": []}, unit_dir)


def test_screen_fill_validates_paper_type_enum(tmp_path: Path) -> None:
    paper = _load_paper_module()
    unit_dir = tmp_path / "unit"
    unit_dir.mkdir()
    _write_parse_cache(unit_dir, "p-x")

    payload = {
        "paper_type": "benchmark",
        "worth_deep_reading": "no",
        "judgement_reason": ["not relevant"],
        "claims": [
            {
                "id": "claim-paper-type",
                "text": "This paper defines a real-robot benchmark.",
                "claim_type": "inference",
                "confirmation_status": "pending_user_confirmation",
                "evidence_refs": [
                    {
                        "source_unit_id": "p-x",
                        "artifact": "parse-cache.yaml",
                        "locator": "page=2",
                        "quote": "real robot benchmark",
                        "summary": "paper type",
                    }
                ],
            }
        ],
    }
    assert paper.verify_screening_fill(payload, unit_dir) == []

    payload["paper_type"] = "position_paper"
    violations = paper.verify_screening_fill(payload, unit_dir)
    assert any("paper_type" in violation and "position_paper" in violation for violation in violations)

    payload["paper_type"] = ""
    assert paper.verify_screening_fill(payload, unit_dir) == []

    payload["paper_type"] = "survey"
    payload["claims"] = []
    assert any("paper_type is an agent judgement" in violation for violation in paper.verify_screening_fill(payload, unit_dir))


# --------------------------------------------------------------------------- #
# 6. End-to-end through the real CLI (main): prepare -> fill -> verify -> confirm.
# --------------------------------------------------------------------------- #
def _run_cli(paper, monkeypatch, root: Path, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["paper.py", "--root", str(root), *argv])
    return paper.main()


def test_cli_end_to_end_prepare_fill_verify_persist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    paper = _load_paper_module()
    ensure_workspace(tmp_path)
    paper_id = "p-e2e-000001"
    record = _paper_record(paper_id)
    write_record(tmp_path, record)
    unit_dir = record_path(tmp_path, "paper", paper_id).parent
    _write_parse_cache(unit_dir, paper_id)

    # prepare screen -> fillable screening.yaml, no grading, record stays hollow.
    assert _run_cli(paper, monkeypatch, tmp_path, "screen", "--phase", "prepare",
                    "--paper-id", paper_id, "--defer-post-actions") == 0
    screening = load_yaml(unit_dir / "screening.yaml")
    assert screening["worth_deep_reading"] == "" and screening["evidence_digest"]

    screening["paper_type"] = "method_system"
    screening["worth_deep_reading"] = "yes"
    screening["judgement_reason"] = ["method/system paper is in scope"]
    screening["claims"] = [
        {
            "id": "claim-screen-type",
            "text": "The paper proposes an action prediction method.",
            "claim_type": "inference",
            "confirmation_status": "pending_user_confirmation",
            "evidence_refs": [
                {
                    "source_unit_id": paper_id,
                    "artifact": "parse-cache.yaml",
                    "locator": "page=2",
                    "quote": "Our method predicts short action chunks",
                    "summary": "method/system classification",
                }
            ],
        }
    ]
    write_yaml_if_changed(unit_dir / "screening.yaml", screening)
    assert _run_cli(paper, monkeypatch, tmp_path, "screen", "--phase", "verify",
                    "--paper-id", paper_id, "--defer-post-actions") == 0
    screened = load_yaml(record_path(tmp_path, "paper", paper_id))
    assert screened["payload"]["quick_screen"]["paper_type"] == "method_system"

    # prepare note -> 5-element skeleton; record marked complete but still hollow.
    assert _run_cli(paper, monkeypatch, tmp_path, "complete-note", "--phase", "prepare",
                    "--paper-id", paper_id, "--defer-post-actions") == 0
    fill_path = unit_dir / "note-fill.yaml"
    assert [el["element"] for el in load_yaml(fill_path)["elements"]] == list(paper.NOTE_ELEMENTS)
    reloaded = load_yaml(record_path(tmp_path, "paper", paper_id))
    assert has_substantive_content(reloaded, "paper") is False  # scaffold is not content

    # Agent fills the scaffold; verify persists note.md + core_content.
    write_yaml_if_changed(fill_path, _legit_note_fill())
    assert _run_cli(paper, monkeypatch, tmp_path, "complete-note", "--phase", "verify",
                    "--paper-id", paper_id, "--defer-post-actions") == 0
    assert (unit_dir / "note.md").exists()
    filled = load_yaml(record_path(tmp_path, "paper", paper_id))
    assert has_substantive_content(filled, "paper") is True
    assert filled["payload"]["claims"] == load_yaml(unit_dir / "note-claims.yaml")["claims"]
    assert filled["payload"]["verification"]["artifacts"]
    assert len(filled["payload"]["verification"]["claims_digest"]) == 64

    # Fabricated fill through the CLI is rejected (non-zero exit).
    bad = _legit_note_fill()
    bad["elements"][0]["evidence_refs"][0]["quote"] = "fabricated claim not in source"
    write_yaml_if_changed(fill_path, bad)
    with pytest.raises(SystemExit):
        _run_cli(paper, monkeypatch, tmp_path, "complete-note", "--phase", "verify",
                 "--paper-id", paper_id, "--defer-post-actions")
