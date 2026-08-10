from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

from repo_paths import REPO_ROOT, initialize_test_workspace

import pytest
import yaml

from research.common import load_yaml, write_yaml_if_changed
from research.confirm import apply_confirmation, confirm_unit
from research.core import default_record, record_path, write_record
from research.evidence import (
    attach_claims,
    build_verification_receipt,
    record_external_source_contract,
)
from research.judgements import discover_stale_confirmed_surveys
from research.records import (
    canonical_record_snapshot_for_record,
    kind_payload_skeleton,
    normalize_record_snapshot,
)
import research.surveys as surveys_module


ROOT = REPO_ROOT
SCRIPT = ROOT / "skills" / "literature-synthesizer" / "scripts" / "synthesize.py"


def load_synthesizer():
    spec = importlib.util.spec_from_file_location("literature_synthesizer_script", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_confirmed_unit(module, root: Path, record: dict, evidence_text: str = "") -> Path:
    initialize_test_workspace(root)
    unit_dir = module.unit_root(root, record["kind"], record["id"])
    unit_dir.mkdir(parents=True, exist_ok=True)
    if evidence_text:
        (unit_dir / "note.md").write_text(evidence_text, encoding="utf-8")
    canonical = {
        **record,
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["fact"],
        "payload": record.get("payload") or {},
    }
    apply_confirmation(
        canonical,
        confirmed_by="Alice Researcher",
        evidence=["Reviewed source unit"],
        project_root=root,
    )
    (unit_dir / "record.yaml").write_text(
        yaml.safe_dump(canonical, allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return unit_dir


def write_confirmed_external_repo_unit(root: Path) -> tuple[dict, Path]:
    initialize_test_workspace(root)
    repo_root = root / "mini-repo"
    repo_root.mkdir()
    source_path = repo_root / "README.md"
    source_path.write_text(
        "# MiniSurveyRepo\n"
        "This repository exposes a reusable survey integration entrypoint.\n",
        encoding="utf-8",
    )
    unit_id = "r-survey-external"
    payload = kind_payload_skeleton("repo", "MiniSurveyRepo")
    payload["structure"]["repo_root"] = repo_root.resolve().as_posix()
    payload["capability"]["core_capabilities"] = [
        "Provides a reusable survey integration entrypoint."
    ]
    claims = [
        {
            "id": "claim-repo-survey-entrypoint",
            "text": "The repository exposes a reusable survey integration entrypoint.",
            "claim_type": "evaluation",
            "confirmation_status": "pending_user_confirmation",
            "evidence_refs": [
                {
                    "source_unit_id": unit_id,
                    "artifact": "README.md",
                    "locator": "line=2",
                    "quote": "This repository exposes a reusable survey integration entrypoint.",
                    "external_source": {"kind": "repo"},
                }
            ],
        }
    ]
    attach_claims(payload, claims)
    record = default_record(
        "repo",
        title="MiniSurveyRepo",
        maturity="complete",
        source={"original_uri": repo_root.resolve().as_posix()},
    )
    record.update(
        {
            "id": unit_id,
            "status": "screened",
            "confirmation_status": "pending_user_confirmation",
            "needs_human_confirmation": True,
            "information_types": ["evaluation"],
            "summary": "robot learning survey integration",
            "payload": payload,
        }
    )
    build_verification_receipt(
        record,
        record_path(root, "repo", unit_id).parent,
        external_source=record_external_source_contract(record),
    )
    canonical_path = write_record(root, record)
    assert load_yaml(canonical_path) == record
    snapshot = canonical_record_snapshot_for_record(root, record)
    persisted = normalize_record_snapshot(snapshot, root)
    assert persisted is not None
    confirmed = confirm_unit(
        persisted,
        "repo",
        confirmed_by="Alice Researcher",
        evidence=["Reviewed external repository evidence"],
        user_authorization="I confirm this repository analysis.",
        authorization_source="user_message",
        project_root=root,
        expected_record_snapshot=snapshot,
    )
    write_yaml_if_changed(canonical_path, confirmed)
    return confirmed, source_path


def build_filled_survey(tmp_path: Path):
    module = load_synthesizer()
    records = [
        {"id": "p-alpha", "kind": "paper", "title": "Alpha Method"},
        {"id": "r-beta", "kind": "repo", "title": "Beta System"},
    ]
    quotes = {
        "p-alpha": "Alpha uses a hierarchical controller for long-horizon tasks.",
        "r-beta": "Beta reports benchmark metrics for recovery tasks.",
    }
    for record in records:
        write_confirmed_unit(
            module,
            tmp_path,
            {**record, "summary": "robot learning", "payload": {}},
            f"# Evidence\n\n{quotes[record['id']]}\n",
        )
    scaffold = module.build_survey_scaffold(
        records,
        root=tmp_path,
        query="robot learning",
        kind="",
        topic="",
        tag="",
        pool="",
        mode="survey",
        as_of="2026-07-17T00:00:00Z",
    )
    _, entries = module.survey_claim_entries(scaffold)
    for _, cell, _ in entries:
        cell["content"] = f"Agent-authored content for {cell['id']}."
        cell["evidence_refs"] = [
            {
                "source_unit_id": "p-alpha",
                "artifact": "note.md",
                "locator": "section=evidence",
                "quote": quotes["p-alpha"],
            }
        ]
    taxonomy = next(section for section in scaffold["sections"] if section["id"] == "taxonomy")
    taxonomy["cells"][0]["row_label"] = "Alpha Method"
    taxonomy["cells"][0]["column_label"] = "Hierarchical control"
    taxonomy["cells"][0]["evidence_refs"].append(
        {
            "source_unit_id": "r-beta",
            "artifact": "note.md",
            "locator": "section=evidence",
            "quote": quotes["r-beta"],
        }
    )
    trends = next(section for section in scaffold["sections"] if section["id"] == "trends")
    trends["items"][0]["trajectory"] = "flat control -> hierarchical control -> recovery-aware control"
    gaps = next(section for section in scaffold["sections"] if section["id"] == "gaps_challenges")
    gaps["items"][0]["gap_type"] = "benchmark coverage"
    scaffold["comparison_matrix"]["dimensions"][0]["label"] = "Control hierarchy"
    scaffold["comparison_matrix"]["methods"][0]["label"] = "Alpha Method"
    scaffold["comparison_matrix"]["methods"][0]["source_unit_ids"] = ["p-alpha"]
    return module, scaffold


def test_prepare_emits_seven_section_evidence_first_scaffold(tmp_path: Path) -> None:
    module = load_synthesizer()
    unit_dir = write_confirmed_unit(
        module,
        tmp_path,
        {"id": "p-alpha", "kind": "paper", "title": "Alpha", "payload": {}},
        "# Alpha\n\nGrounded evidence.\n",
    )
    scaffold = module.build_survey_scaffold(
        [{"id": "p-alpha", "kind": "paper", "title": "Alpha"}],
        root=tmp_path,
        query="robot learning",
        kind="",
        topic="",
        tag="",
        pool="",
        mode="survey",
        as_of="2026-07-17T00:00:00Z",
    )

    assert [section["id"] for section in scaffold["sections"]] == [
        "scope_positioning",
        "background_terms",
        "taxonomy",
        "cross_cutting",
        "trends",
        "gaps_challenges",
        "conclusion",
    ]
    assert scaffold["kb_anchor"]["unit_ids"] == ["p-alpha"]
    binding = scaffold["kb_anchor"]["units"][0]
    assert len(binding["record_content_digest"]) == 64
    assert binding["evidence_artifacts"] == [
        {"artifact": "note.md", "byte_sha256": module.file_sha256(unit_dir / "note.md")}
    ]
    assert scaffold["comparison_matrix"]["cells"]
    _, entries = module.survey_claim_entries(scaffold)
    assert entries
    assert all(cell["content"] == "" and cell["evidence_refs"] == [] for _, cell, _ in entries)
    serialized = yaml.safe_dump(scaffold, allow_unicode=True)
    assert "confidence: 0.68" not in serialized
    assert "当前结果仍偏索引级综合" not in serialized


def test_unit_binding_passes_tree_record_snapshot_into_confirmation_check(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_synthesizer()
    unit_dir = write_confirmed_unit(
        module,
        tmp_path,
        {"id": "p-alpha", "kind": "paper", "title": "Alpha", "payload": {}},
        "stable evidence\n",
    )
    canonical = yaml.safe_load((unit_dir / "record.yaml").read_text(encoding="utf-8"))
    expected_snapshots = []
    original_roots = surveys_module.trusted_claim_source_roots

    def checking_roots(*args, expected_record_snapshot=None, **kwargs):
        expected_snapshots.append(expected_record_snapshot)
        return original_roots(
            *args,
            expected_record_snapshot=expected_record_snapshot,
            **kwargs,
        )

    monkeypatch.setattr(surveys_module, "trusted_claim_source_roots", checking_roots)

    binding = surveys_module.build_unit_binding(tmp_path, canonical)

    assert binding["title"] == "Alpha"
    assert expected_snapshots
    assert all(snapshot is not None for snapshot in expected_snapshots)
    assert all(snapshot.raw_bytes == (unit_dir / "record.yaml").read_bytes() for snapshot in expected_snapshots)


def test_external_repo_evidence_is_survey_eligible_and_contract_bound(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_synthesizer()
    record, source_path = write_confirmed_external_repo_unit(tmp_path)

    eligible, excluded = surveys_module.select_current_confirmed_survey_records(
        tmp_path,
        [record],
        query="robot learning",
    )
    assert [item["id"] for item in eligible] == [record["id"]]
    assert excluded == []
    scaffold = module.build_survey_scaffold(
        [record],
        root=tmp_path,
        query="robot learning",
        kind="",
        topic="",
        tag="",
        pool="",
        mode="survey",
        as_of="2026-07-25T00:00:00Z",
    )
    assert scaffold["kb_anchor"]["unit_ids"] == [record["id"]]

    source_path.write_text("# MiniSurveyRepo\nTampered external bytes.\n", encoding="utf-8")
    eligible, excluded = surveys_module.select_current_confirmed_survey_records(
        tmp_path,
        [record],
        query="robot learning",
    )
    assert eligible == []
    assert excluded[0]["reasons"]
    with pytest.raises(SystemExit, match="not currently confirmed"):
        surveys_module.build_unit_binding(tmp_path, record)

    source_path.write_text(
        "# MiniSurveyRepo\n"
        "This repository exposes a reusable survey integration entrypoint.\n",
        encoding="utf-8",
    )
    forged_root = tmp_path / "forged-repo"
    forged_root.mkdir()
    (forged_root / "README.md").write_text("forged bytes\n", encoding="utf-8")
    for contract in (
        None,
        {"kind": "repo", "base_root": forged_root.resolve().as_posix()},
    ):
        monkeypatch.setattr(
            surveys_module,
            "record_external_source_contract",
            lambda _record, current_contract=contract: current_contract,
        )
        eligible, excluded = surveys_module.select_current_confirmed_survey_records(
            tmp_path,
            [record],
            query="robot learning",
        )
        assert eligible == []
        assert excluded[0]["reasons"]
        with pytest.raises(SystemExit, match="not currently confirmed"):
            surveys_module.build_unit_binding(tmp_path, record)


def test_unit_binding_rejects_ambiguous_canonical_unit_id(tmp_path: Path) -> None:
    module = load_synthesizer()
    paper_dir = write_confirmed_unit(
        module,
        tmp_path,
        {"id": "shared-unit-id", "kind": "paper", "title": "Paper", "payload": {}},
    )
    isolated = tmp_path.parent / f"{tmp_path.name}-repo-fixture"
    write_confirmed_unit(
        module,
        isolated,
        {"id": "shared-unit-id", "kind": "repo", "title": "Repo", "payload": {}},
    )
    shutil.copytree(
        isolated / "units" / "repos" / "shared-unit-id",
        tmp_path / "units" / "repos" / "shared-unit-id",
    )
    canonical = yaml.safe_load((paper_dir / "record.yaml").read_text(encoding="utf-8"))

    with pytest.raises(SystemExit, match="missing, ambiguous, or unsafe"):
        surveys_module.build_unit_binding(tmp_path, canonical)


def test_verify_accepts_verbatim_cross_unit_evidence(tmp_path: Path) -> None:
    module, scaffold = build_filled_survey(tmp_path)

    violations, verified = module.verify_survey_fill(scaffold, tmp_path)

    assert violations == []
    assert verified["status"] == "pending_user_confirmation"
    assert verified["evidence_verification_status"] == "verified"
    assert verified["governance_status"] == "ready_for_review"
    assert verified["payload"]["claims"]
    assert verified["payload"]["verification"]["verified_at"]
    _, entries = module.survey_claim_entries(verified)
    statuses = {cell["epistemic_status"] for _, cell, _ in entries}
    assert statuses == {"verified_pending_confirmation"}
    summary = module.render_verified_summary(verified)
    assert "## Comparison Matrix" in summary
    assert "| Alpha Method |" in summary


def test_verify_rejects_fabricated_quote(tmp_path: Path) -> None:
    module, scaffold = build_filled_survey(tmp_path)
    scaffold["sections"][0]["claims"][0]["evidence_refs"][0]["quote"] = "Fabricated result at 99 percent."

    violations, verified = module.verify_survey_fill(scaffold, tmp_path)

    assert verified["status"] == "awaiting_agent_fill"
    assert any("not verbatim" in violation for violation in violations)


def test_verify_cli_persists_only_verified_survey(tmp_path: Path, monkeypatch) -> None:
    module, scaffold = build_filled_survey(tmp_path)
    fill_path = tmp_path / "synthesis" / "robot-learning" / "agent-filled.yaml"
    fill_path.parent.mkdir(parents=True, exist_ok=True)
    fill_path.write_text(yaml.safe_dump(scaffold, allow_unicode=True, sort_keys=False), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [str(SCRIPT), "--root", str(tmp_path), "survey", "verify", "--input", str(fill_path)],
    )

    assert module.main() == 0

    survey_path = tmp_path / "synthesis" / "robot-learning" / "survey.yaml"
    summary_path = tmp_path / "synthesis" / "robot-learning" / "summary.md"
    assert survey_path.exists()
    assert summary_path.exists()
    persisted = yaml.safe_load(survey_path.read_text(encoding="utf-8"))
    assert persisted["status"] == "pending_user_confirmation"
    assert persisted["evidence_verification_status"] == "verified"
    assert persisted["consumer_binding"]["selection_filters"]["query"] == "robot learning"
    assert persisted["consumer_binding"]["unit_ids"] == ["p-alpha", "r-beta"]
    assert "Pending / Unverified judgement" in (survey_path.parent / "summary.md").read_text(encoding="utf-8")
    assert "## Comparison Matrix" in summary_path.read_text(encoding="utf-8")


def test_prepare_rejects_unit_with_symlink_artifact(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    module = load_synthesizer()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside evidence", encoding="utf-8")
    unit_dir = write_confirmed_unit(
        module,
        tmp_path,
        {"id": "p-alpha", "kind": "paper", "title": "Alpha", "payload": {}},
    )
    (unit_dir / "linked.txt").symlink_to(outside)

    with pytest.raises(SystemExit, match="missing, ambiguous, or unsafe"):
        module.build_survey_scaffold(
            [{"id": "p-alpha", "kind": "paper", "title": "Alpha"}],
            root=tmp_path,
            query="alpha",
            kind="",
            topic="",
            tag="",
            pool="",
            mode="survey",
            as_of="2026-07-17T00:00:00Z",
        )

    assert outside.read_text(encoding="utf-8") == "outside evidence"


def test_build_unit_binding_rejects_source_ancestor_replaced_after_tree_capture(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = load_synthesizer()
    unit_dir = write_confirmed_unit(
        module,
        tmp_path,
        {"id": "p-alpha", "kind": "paper", "title": "Alpha", "payload": {}},
        "stable canonical evidence\n",
    )
    canonical = yaml.safe_load((unit_dir / "record.yaml").read_text(encoding="utf-8"))
    outside_dir = tmp_path / "outside-canonical-units"
    shutil.copytree(unit_dir, outside_dir)
    (outside_dir / "outside-only.md").write_text(
        "OUTSIDE-ONLY-SURVEY-SENTINEL\n",
        encoding="utf-8",
    )
    parked_dir = tmp_path / "parked-canonical-unit"
    captured_artifacts: list[str] = []
    original_capture = surveys_module.snapshot_unique_canonical_unit_tree

    def capture_then_replace(*args, **kwargs):
        snapshot = original_capture(*args, **kwargs)
        assert snapshot is not None
        captured_artifacts.extend(item.artifact for item in snapshot.artifacts)
        unit_dir.rename(parked_dir)
        outside_dir.rename(unit_dir)
        return snapshot

    monkeypatch.setattr(
        surveys_module,
        "snapshot_unique_canonical_unit_tree",
        capture_then_replace,
    )

    with pytest.raises(SystemExit, match="not currently confirmed|changed while anchoring"):
        surveys_module.build_unit_binding(tmp_path, canonical)
    assert "outside-only.md" not in captured_artifacts
    assert "note.md" in captured_artifacts


def test_verify_rejects_changed_bound_record_or_evidence(tmp_path: Path) -> None:
    module, scaffold = build_filled_survey(tmp_path)
    paper_dir = module.unit_root(tmp_path, "paper", "p-alpha")
    (paper_dir / "note.md").write_text("# Evidence\n\nChanged bytes.\n", encoding="utf-8")

    violations, _ = module.verify_survey_fill(scaffold, tmp_path)

    assert any("canonical unit content, confirmation, or evidence changed" in item for item in violations)


def test_survey_staleness_detects_changed_deleted_and_new_matching_units(tmp_path: Path) -> None:
    module, scaffold = build_filled_survey(tmp_path)
    violations, verified = module.verify_survey_fill(scaffold, tmp_path)
    assert violations == []
    assert module.survey_staleness(verified, tmp_path) == {
        "stale": False,
        "reasons": [],
        "new_unit_ids": [],
    }

    paper_dir = module.unit_root(tmp_path, "paper", "p-alpha")
    (paper_dir / "note.md").write_text("# Evidence\n\nChanged bytes.\n", encoding="utf-8")
    repo_dir = module.unit_root(tmp_path, "repo", "r-beta")
    (repo_dir / "record.yaml").unlink()
    write_confirmed_unit(
        module,
        tmp_path,
        {"id": "p-gamma", "kind": "paper", "title": "Gamma", "summary": "robot learning", "payload": {}},
    )

    stale = module.survey_staleness(verified, tmp_path)

    assert stale["stale"] is True
    assert stale["new_unit_ids"] == ["p-gamma"]
    assert "changed unit: p-alpha" in stale["reasons"]
    assert "deleted or unreadable unit: r-beta" in stale["reasons"]
    assert "new matching unit: p-gamma" in stale["reasons"]


def test_confirmed_stale_survey_is_discovered_without_mutating_old_judgement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module, scaffold = build_filled_survey(tmp_path)
    violations, verified = module.verify_survey_fill(scaffold, tmp_path)
    assert violations == []
    survey_path = tmp_path / "synthesis" / "robot-learning" / "survey.yaml"
    survey_path.parent.mkdir(parents=True, exist_ok=True)
    source_roots = {
        item["id"]: module.unit_root(tmp_path, item["kind"], item["id"])
        for item in verified["consumer_binding"]["units"]
    }
    module.apply_confirmation(
        verified,
        confirmed_by="Alice Researcher",
        evidence=["Reviewed the verified survey."],
        user_authorization="I confirm this survey.",
        authorization_source="user_message",
        project_root=tmp_path,
        verification_root=survey_path.parent,
        trusted_source_roots=source_roots,
    )
    write_yaml_if_changed(survey_path, verified)
    before = survey_path.read_bytes()
    write_confirmed_unit(
        module,
        tmp_path,
        {
            "id": "p-gamma",
            "kind": "paper",
            "title": "Gamma Method",
            "summary": "robot learning",
            "payload": {},
        },
        "# Evidence\n\nGamma adds a new matching result.\n",
    )

    stale = discover_stale_confirmed_surveys(tmp_path)

    assert len(stale) == 1
    assert stale[0]["subject"]["id"] == verified["id"]
    assert stale[0]["slug"] == "robot-learning"
    assert stale[0]["new_unit_ids"] == ["p-gamma"]
    assert "new matching unit: p-gamma" in stale[0]["stale_reasons"]
    assert survey_path.read_bytes() == before

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
            "2026-07-27T00:00:00Z",
        ],
    )
    assert module.main() == 0
    fill_path = survey_path.parent / "survey-fill.yaml"
    fill = yaml.safe_load(fill_path.read_text(encoding="utf-8"))
    assert fill["status"] == "awaiting_agent_fill"
    assert fill["kb_anchor"]["unit_ids"] == ["p-alpha", "p-gamma", "r-beta"]
    assert "confirmation_receipt" not in fill
    assert survey_path.read_bytes() == before


def test_stale_survey_discovery_ignores_malformed_symlink_and_noncanonical_duplicate(
    tmp_path: Path,
) -> None:
    module, scaffold = build_filled_survey(tmp_path)
    violations, verified = module.verify_survey_fill(scaffold, tmp_path)
    assert violations == []
    survey_path = tmp_path / "synthesis" / "robot-learning" / "survey.yaml"
    survey_path.parent.mkdir(parents=True, exist_ok=True)
    source_roots = {
        item["id"]: module.unit_root(tmp_path, item["kind"], item["id"])
        for item in verified["consumer_binding"]["units"]
    }
    module.apply_confirmation(
        verified,
        confirmed_by="Alice Researcher",
        evidence=["Reviewed the verified survey."],
        user_authorization="I confirm this survey.",
        authorization_source="user_message",
        project_root=tmp_path,
        verification_root=survey_path.parent,
        trusted_source_roots=source_roots,
    )
    write_yaml_if_changed(survey_path, verified)
    write_confirmed_unit(
        module,
        tmp_path,
        {
            "id": "p-gamma",
            "kind": "paper",
            "title": "Gamma Method",
            "summary": "robot learning",
            "payload": {},
        },
        "# Evidence\n\nGamma adds a new matching result.\n",
    )

    malformed = tmp_path / "synthesis" / "malformed" / "survey.yaml"
    malformed.parent.mkdir(parents=True)
    malformed.write_text("kind: survey_judgement\nid: [unterminated\n", encoding="utf-8")
    duplicate = tmp_path / "synthesis" / "duplicate" / "survey.yaml"
    duplicate.parent.mkdir(parents=True)
    duplicate.write_bytes(survey_path.read_bytes())
    linked = tmp_path / "synthesis" / "linked"
    linked.symlink_to(survey_path.parent, target_is_directory=True)

    stale = discover_stale_confirmed_surveys(tmp_path)

    assert len(stale) == 1
    assert stale[0]["subject"]["path"] == "kb/synthesis/robot-learning/survey.yaml"
    assert stale[0]["new_unit_ids"] == ["p-gamma"]
