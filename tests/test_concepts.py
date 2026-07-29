from __future__ import annotations

from pathlib import Path

import yaml

from research.common import load_yaml
from research.concepts import (
    build_concept_scaffold,
    concept_lifecycle_violations,
    verify_concept_fill,
)
from research.confirm import confirm_unit, write_record
from research.index import build_index, search_passages
from research.judgements import discover_pending_judgements, judgement_confirmation_is_current
from research.obsidian import update_obsidian_projection
from research.paths import record_path, unit_root
from research.records import canonical_record_snapshot_for_identity, default_record, normalize_record_snapshot
from research.common import write_yaml_if_changed
from research.confirm import apply_confirmation


SOURCE_ROWS = (
    ("paper", "p-alpha-method-12345678", "Alpha Method", "Embodied policies use action chunks for temporal consistency."),
    ("blog", "b-beta-guide-23456789", "Beta Guide", "Action chunking reduces the frequency of policy queries."),
    ("idea", "i-gamma-plan-34567890", "Gamma Plan", "A variable chunk horizon may improve recovery behavior."),
)


def _write_confirmed_sources(root: Path) -> list[dict]:
    records = []
    for kind, unit_id, title, quote in SOURCE_ROWS:
        directory = unit_root(root, kind, unit_id)
        directory.mkdir(parents=True, exist_ok=True)
        (directory / "note.md").write_text(f"# Evidence\n\n{quote}\n", encoding="utf-8")
        record = default_record(
            kind,
            title=title,
            maturity="complete",
            source={"kind": "local"},
        )
        record.update(
            {
                "id": unit_id,
                "status": "active",
                "confirmation_status": "pending_user_confirmation",
                "needs_human_confirmation": True,
                "information_types": ["fact"],
                "summary": f"Source about {title}",
            }
        )
        apply_confirmation(
            record,
            confirmed_by="Alice Researcher",
            evidence=["Reviewed source metadata"],
            user_authorization="I confirm these source records.",
            authorization_source="user_message",
            project_root=root,
        )
        write_yaml_if_changed(directory / "record.yaml", record)
        records.append(record)
    return records


def _filled_concept(root: Path) -> tuple[dict, dict]:
    records = _write_confirmed_sources(root)
    fill = build_concept_scaffold(
        root,
        canonical_name="Action Chunking",
        records=records,
        as_of="2026-07-27T00:00:00Z",
    )
    fill["concept"]["aliases"] = ["temporal action chunking"]
    fill["concept"]["definition"].update(
        {
            "content": "Action chunking predicts temporally consistent blocks of actions.",
            "claim_type": "evaluation",
            "evidence_refs": [
                {
                    "source_unit_id": SOURCE_ROWS[0][1],
                    "artifact": "note.md",
                    "locator": "line=3",
                    "quote": SOURCE_ROWS[0][3],
                }
            ],
        }
    )
    source_by_id = {source[1]: source for source in SOURCE_ROWS}
    for association in fill["associations"]:
        source = source_by_id[association["target_id"]]
        association["role"].update(
            {
                "content": f"{source[2]} contributes evidence about action chunking.",
                "claim_type": "evaluation",
                "evidence_refs": [
                    {
                        "source_unit_id": source[1],
                        "artifact": "note.md",
                        "locator": "line=3",
                        "quote": source[3],
                    }
                ],
            }
        )
    violations, record = verify_concept_fill(root, fill)
    assert violations == []
    assert record is not None
    return fill, record


def test_prepare_is_empty_agent_fill_and_requires_three_confirmed_units(tmp_path: Path) -> None:
    records = _write_confirmed_sources(tmp_path)
    fill = build_concept_scaffold(
        tmp_path,
        canonical_name="Action Chunking",
        records=records,
        as_of="2026-07-27T00:00:00Z",
    )

    assert fill["concept_id"].startswith("c-action-chunking-")
    assert fill["concept"]["definition"]["content"] == ""
    assert all(item["role"]["content"] == "" for item in fill["associations"])
    violations, record = verify_concept_fill(tmp_path, fill)
    assert record is None
    assert any("runtime Agent content is required" in item for item in violations)

    try:
        build_concept_scaffold(
            tmp_path,
            canonical_name="Too Small",
            records=records[:2],
            as_of="2026-07-27T00:00:00Z",
        )
    except ValueError as exc:
        assert "at least 3" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("two units must not produce a concept scaffold")


def test_verify_writes_pending_concept_discoverable_by_generic_review(tmp_path: Path) -> None:
    _fill, record = _filled_concept(tmp_path)
    path = write_record(tmp_path, record, expected_revision=0)

    persisted = load_yaml(path)
    assert persisted["kind"] == "concept"
    assert persisted["confirmation_status"] == "pending_user_confirmation"
    assert persisted["payload"]["concept"]["definition"].startswith("Action chunking")
    assert len(persisted["payload"]["associations"]) == 3
    assert len(persisted["links"]) == 3
    cards = discover_pending_judgements(tmp_path)
    concept_cards = [card for card in cards if card["subject"]["kind"] == "concept"]
    assert len(concept_cards) == 1
    assert concept_cards[0]["subject"]["owner"] == "literature-synthesizer"


def test_concept_confirm_index_find_and_obsidian_page(tmp_path: Path) -> None:
    _fill, record = _filled_concept(tmp_path)
    path = write_record(tmp_path, record, expected_revision=0)
    snapshot = canonical_record_snapshot_for_identity(tmp_path, "concept", record["id"])
    assert snapshot is not None
    persisted = normalize_record_snapshot(snapshot, tmp_path)
    assert persisted is not None
    confirmed = confirm_unit(
        persisted,
        "concept",
        confirmed_by="Alice Researcher",
        evidence=["Reviewed the concept definition and all three associations"],
        user_authorization="I confirm this concept page.",
        authorization_source="user_message",
        project_root=tmp_path,
        expected_record_snapshot=snapshot,
    )
    write_record(tmp_path, confirmed, expected_record_snapshot=snapshot)
    current = canonical_record_snapshot_for_identity(tmp_path, "concept", record["id"])
    assert current is not None
    current_record = normalize_record_snapshot(current, tmp_path)
    assert current_record is not None
    assert judgement_confirmation_is_current(
        tmp_path,
        current_record,
        current.path,
        record_snapshot=current,
    )

    build_index(tmp_path)
    results = search_passages(tmp_path, "Action Chunking", limit=10)["results"]
    assert any(item["unit_id"] == record["id"] for item in results)
    update_obsidian_projection(tmp_path)
    page = tmp_path / "kb" / "obsidian" / "managed" / "units" / f"{record['id']}.md"
    text = page.read_text(encoding="utf-8")
    assert "## Definition" in text
    assert "Action chunking predicts temporally consistent blocks of actions." in text
    assert "## Associations" in text
    assert "Analysis · Evidence-backed analysis available" in text
    assert "Confirmation: Confirmed" in text
    assert "Awaiting human confirmation" not in text
    for _kind, unit_id, title, _quote in SOURCE_ROWS:
        assert unit_id in text or title in text


def test_concept_rejects_forged_quote_and_association_source(tmp_path: Path) -> None:
    fill, _record = _filled_concept(tmp_path)
    fill["concept"]["definition"]["evidence_refs"][0]["quote"] = "not present"
    association = fill["associations"][0]
    wrong_source = next(source[1] for source in SOURCE_ROWS if source[1] != association["target_id"])
    association["role"]["evidence_refs"][0]["source_unit_id"] = wrong_source

    violations, record = verify_concept_fill(tmp_path, fill)

    assert record is None
    assert any("evidence must come from its target unit" in item for item in violations)
    assert any("not verbatim" in item for item in violations)


def test_upstream_record_change_invalidates_confirmed_concept_anchor(tmp_path: Path) -> None:
    _fill, record = _filled_concept(tmp_path)
    path = write_record(tmp_path, record, expected_revision=0)
    snapshot = canonical_record_snapshot_for_identity(tmp_path, "concept", record["id"])
    assert snapshot is not None
    persisted = normalize_record_snapshot(snapshot, tmp_path)
    assert persisted is not None
    confirmed = confirm_unit(
        persisted,
        "concept",
        confirmed_by="Alice Researcher",
        evidence=["Reviewed concept"],
        user_authorization="I confirm this concept page.",
        authorization_source="user_message",
        project_root=tmp_path,
        expected_record_snapshot=snapshot,
    )
    write_record(tmp_path, confirmed, expected_record_snapshot=snapshot)

    upstream_path = record_path(tmp_path, SOURCE_ROWS[0][0], SOURCE_ROWS[0][1])
    upstream = load_yaml(upstream_path)
    upstream["summary"] = "Changed navigation-only summary"
    upstream_path.write_text(yaml.safe_dump(upstream, allow_unicode=True, sort_keys=False), encoding="utf-8")

    current = canonical_record_snapshot_for_identity(tmp_path, "concept", record["id"])
    assert current is not None
    current_record = normalize_record_snapshot(current, tmp_path)
    assert current_record is not None
    assert current_record["confirmation_status"] == "pending_user_confirmation"
    assert concept_lifecycle_violations(tmp_path, current_record)
    assert not judgement_confirmation_is_current(
        tmp_path,
        current_record,
        current.path,
        record_snapshot=current,
    )


def test_concept_anchor_mutation_invalidates_confirmation_receipt(tmp_path: Path) -> None:
    _fill, record = _filled_concept(tmp_path)
    path = write_record(tmp_path, record, expected_revision=0)
    snapshot = canonical_record_snapshot_for_identity(tmp_path, "concept", record["id"])
    assert snapshot is not None
    persisted = normalize_record_snapshot(snapshot, tmp_path)
    assert persisted is not None
    confirmed = confirm_unit(
        persisted,
        "concept",
        confirmed_by="Alice Researcher",
        evidence=["Reviewed the frozen concept anchor"],
        user_authorization="I confirm this concept page.",
        authorization_source="user_message",
        project_root=tmp_path,
        expected_record_snapshot=snapshot,
    )
    write_record(tmp_path, confirmed, expected_record_snapshot=snapshot)

    tampered = load_yaml(path)
    tampered["payload"]["anchor"]["as_of"] = "2026-07-28T00:00:00Z"
    path.write_text(yaml.safe_dump(tampered, allow_unicode=True, sort_keys=False), encoding="utf-8")

    current = canonical_record_snapshot_for_identity(tmp_path, "concept", record["id"])
    assert current is not None
    current_record = normalize_record_snapshot(current, tmp_path)
    assert current_record is not None
    assert current_record["confirmation_status"] == "pending_user_confirmation"
    assert not judgement_confirmation_is_current(
        tmp_path,
        current_record,
        current.path,
        record_snapshot=current,
    )
