from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

import research.context_pack as context_pack_module
from research.common import write_yaml_if_changed
from research.confirm import apply_confirmation, write_record
from research.context_pack import build_context_pack, serialized_context_pack_size
from research.evidence import build_verification_receipt
from research.records import canonical_record_snapshot_for_record, normalize_record_snapshot
from repo_paths import initialize_test_workspace


def _claim(unit_id: str, number: int, quote: str, *, refs: int = 1) -> dict[str, Any]:
    return {
        "id": f"claim-{number:02d}",
        "text": f"Grounded conclusion {number}: {quote}",
        "claim_type": "evaluation",
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": [
            {
                "source_unit_id": unit_id,
                "artifact": "evidence.md",
                "locator": f"line={number}",
                "quote": quote,
            }
            for _ in range(refs)
        ],
    }


def _write_judgement(
    root: Path,
    unit_id: str,
    *,
    confirmed: bool,
    claim_count: int = 1,
    refs_per_claim: int = 1,
    quote_padding: int = 0,
    duplicate_claim_ids: bool = False,
) -> tuple[Path, dict[str, Any]]:
    initialize_test_workspace(root)
    unit_root = root / "units" / "papers" / unit_id
    unit_root.mkdir(parents=True, exist_ok=True)
    quotes = [f"evidence-{number}-" + ("证" * quote_padding) for number in range(1, claim_count + 1)]
    evidence_path = unit_root / "evidence.md"
    evidence_path.write_text("\n".join(quotes) + "\n", encoding="utf-8")
    claims = [
        _claim(unit_id, number, quote, refs=refs_per_claim)
        for number, quote in enumerate(quotes, start=1)
    ]
    if duplicate_claim_ids and len(claims) > 1:
        claims[1]["id"] = claims[0]["id"]
    record = {
        "id": unit_id,
        "kind": "paper",
        "title": f"Paper {unit_id}",
        "summary": f"Navigation summary for {unit_id}.",
        "status": "active",
        "maturity": "complete",
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "information_types": ["evaluation"],
        "source": {"original_uri": "", "file_hash": ""},
        "payload": {
            "core_content": {"research_problem": "A substantive grounded analysis."},
            "claims": claims,
        },
    }
    build_verification_receipt(record, unit_root, source_roots={unit_id: unit_root})
    record_path = unit_root / "record.yaml"
    write_yaml_if_changed(record_path, record)
    if not confirmed:
        return evidence_path, record

    expected = canonical_record_snapshot_for_record(root, record)
    normalized = normalize_record_snapshot(expected, root)
    assert normalized is not None
    apply_confirmation(
        normalized,
        confirmed_by="Human Reviewer",
        evidence=["Reviewed the grounded evidence."],
        user_authorization="I confirm these claims.",
        authorization_source="user_message",
        project_root=root,
        expected_record_snapshot=expected,
    )
    write_record(root, normalized, expected_record_snapshot=expected)
    return evidence_path, normalized


def _passage(unit_id: str, excerpt: str = "A lexical navigation excerpt.") -> dict[str, Any]:
    return {
        "unit_id": unit_id,
        "kind": "paper",
        "title": f"Paper {unit_id}",
        "excerpt": excerpt,
        "artifact": f"kb/units/papers/{unit_id}/source/document.md",
        "locator": f"kb/units/papers/{unit_id}/source/document.md#L10-L12",
        "heading": "Method",
        "line_start": 10,
        "line_end": 12,
        "_search_score": 99.0,
    }


def _forbidden_keys(value: Any) -> set[str]:
    forbidden = {"by", "at", "verified_at", "user_authorization", "authorization_source", "_search_score"}
    found: set[str] = set()
    if isinstance(value, dict):
        found.update(forbidden.intersection(value))
        for child in value.values():
            found.update(_forbidden_keys(child))
    elif isinstance(value, list):
        for child in value:
            found.update(_forbidden_keys(child))
    return found


def test_context_pack_separates_current_formal_claims_from_navigation(tmp_path: Path) -> None:
    unit_id = "p-context-current-123456"
    _write_judgement(tmp_path, unit_id, confirmed=True)

    pack = build_context_pack(
        tmp_path,
        query="grounded conclusion",
        matched_records=[{"id": unit_id, "_search_score": 100}],
        passages=[_passage(unit_id)],
    )

    assert pack["schema"] == "context-pack/v1"
    assert pack["limits"] == {
        "units": 5,
        "claims_per_unit": 3,
        "evidence_refs_per_claim": 2,
        "utf8_bytes": 6000,
    }
    assert len(pack["units"]) == 1
    unit = pack["units"][0]
    assert unit["formal"]["confirmation_bound"] is True
    assert unit["formal"]["claims"] == [
        {
            "confirmation_bound": True,
            "id": "claim-01",
            "text": "Grounded conclusion 1: evidence-1-",
            "claim_type": "evaluation",
            "evidence_refs": [
                {
                    "source_unit_id": unit_id,
                    "artifact": "evidence.md",
                    "locator": "line=1",
                    "quote": "evidence-1-",
                }
            ],
        }
    ]
    assert unit["navigation"]["confirmation_bound"] is False
    assert unit["navigation"]["summary"]["confirmation_bound"] is False
    assert unit["navigation"]["passages"][0]["confirmation_bound"] is False
    assert _forbidden_keys(pack) == set()
    assert str(tmp_path) not in json.dumps(pack, ensure_ascii=False)


def test_context_pack_excludes_pending_stale_and_forged_formal_content(tmp_path: Path) -> None:
    pending_id = "p-context-pending-123456"
    stale_id = "p-context-stale-123456"
    forged_id = "p-context-forged-123456"
    _write_judgement(tmp_path, pending_id, confirmed=False)
    stale_evidence, _ = _write_judgement(tmp_path, stale_id, confirmed=True)
    stale_evidence.write_text("changed after confirmation\n", encoding="utf-8")
    _write_judgement(tmp_path, forged_id, confirmed=False)
    forged_path = tmp_path / "units" / "papers" / forged_id / "record.yaml"
    forged = yaml.safe_load(forged_path.read_text(encoding="utf-8"))
    forged["confirmation_status"] = "confirmed"
    forged["needs_human_confirmation"] = False
    forged["confirmation"] = {"decision": "confirmed", "by": "Human Reviewer", "claim_ids": ["claim-01"]}
    write_yaml_if_changed(forged_path, forged)

    records = [{"id": unit_id} for unit_id in (pending_id, stale_id, forged_id)]
    pack = build_context_pack(
        tmp_path,
        query="navigation",
        matched_records=records,
        passages=[_passage(item["id"]) for item in records],
    )

    assert [unit["unit_id"] for unit in pack["units"]] == [pending_id, stale_id, forged_id]
    assert all(unit["formal"]["claims"] == [] for unit in pack["units"])
    assert all(unit["navigation"]["summary"]["confirmation_bound"] is False for unit in pack["units"])
    assert sum(pack["omissions"][key] for key in ("pending_confirmation_claim", "stale_confirmation_claim")) >= 3


def test_context_pack_duplicate_claim_ids_fail_closed(tmp_path: Path) -> None:
    unit_id = "p-context-duplicate-123456"
    _write_judgement(tmp_path, unit_id, confirmed=True, claim_count=2, duplicate_claim_ids=True)

    pack = build_context_pack(
        tmp_path,
        query="duplicate",
        matched_records=[{"id": unit_id}],
        passages=[],
    )

    assert pack["units"][0]["formal"]["claims"] == []
    assert pack["omissions"]["duplicate_claim_id"] == 2


def test_context_pack_duplicate_canonical_unit_ids_fail_closed(tmp_path: Path) -> None:
    unit_id = "p-context-collision-123456"
    _write_judgement(tmp_path, unit_id, confirmed=False)
    paper_path = tmp_path / "units" / "papers" / unit_id / "record.yaml"
    duplicate = yaml.safe_load(paper_path.read_text(encoding="utf-8"))
    duplicate["kind"] = "blog"
    write_yaml_if_changed(
        tmp_path / "units" / "blogs" / unit_id / "record.yaml",
        duplicate,
    )

    pack = build_context_pack(
        tmp_path,
        query="collision",
        matched_records=[{"id": unit_id}],
        passages=[],
    )

    assert pack["units"] == []
    assert pack["omissions"]["duplicate_canonical_unit_id"] == 1


def test_context_pack_aggregate_recheck_removes_claims_that_turn_stale(
    tmp_path: Path,
    monkeypatch,
) -> None:
    unit_id = "p-context-race-123456"
    _write_judgement(tmp_path, unit_id, confirmed=True)
    original = context_pack_module.judgement_confirmation_is_current
    calls = 0

    def current_once(*args, **kwargs):
        nonlocal calls
        calls += 1
        return original(*args, **kwargs) if calls == 1 else False

    monkeypatch.setattr(context_pack_module, "judgement_confirmation_is_current", current_once)
    pack = build_context_pack(
        tmp_path,
        query="race",
        matched_records=[{"id": unit_id}],
        passages=[],
    )

    assert pack["units"][0]["formal"]["claims"] == []
    assert pack["omissions"]["aggregate_recheck"] == 1


def test_context_pack_confirmation_reader_failure_fails_closed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    unit_id = "p-context-reader-failure-123456"
    _write_judgement(tmp_path, unit_id, confirmed=True)

    def fail_closed(*args, **kwargs):
        raise SystemExit("private malformed receipt detail")

    monkeypatch.setattr(context_pack_module, "judgement_confirmation_is_current", fail_closed)
    pack = build_context_pack(
        tmp_path,
        query="reader failure",
        matched_records=[{"id": unit_id}],
        passages=[],
    )

    assert pack["units"][0]["formal"]["claims"] == []
    assert pack["omissions"]["stale_confirmation_claim"] == 1


def test_context_pack_bounds_are_deterministic_and_never_cut_a_claim(tmp_path: Path) -> None:
    unit_id = "p-context-budget-123456"
    _write_judgement(
        tmp_path,
        unit_id,
        confirmed=True,
        claim_count=5,
        refs_per_claim=3,
        quote_padding=100,
    )
    kwargs = {
        "query": "bounded context",
        "matched_records": [{"id": unit_id}],
        "passages": [_passage(unit_id, excerpt="导" * 500)],
        "max_utf8_bytes": 2600,
    }

    first = build_context_pack(tmp_path, **kwargs)
    second = build_context_pack(tmp_path, **kwargs)

    assert first == second
    assert serialized_context_pack_size(first) <= 2600
    claims = first["units"][0]["formal"]["claims"] if first["units"] else []
    assert len(claims) <= 3
    assert all(len(claim["evidence_refs"]) <= 2 for claim in claims)
    assert all(ref["quote"].endswith("证" * 100) for claim in claims for ref in claim["evidence_refs"])
    assert first["omissions"]["claim_limit"] == 2
    assert first["omissions"]["evidence_ref_limit"] == 5
    assert first["omissions"]["byte_budget"] > 0


def test_context_pack_is_read_only_for_canonical_workspace(tmp_path: Path) -> None:
    unit_id = "p-context-readonly-123456"
    _write_judgement(tmp_path, unit_id, confirmed=True)
    canonical_root = tmp_path / "kb"

    def snapshot() -> dict[str, tuple[bytes, int]]:
        return {
            path.relative_to(canonical_root).as_posix(): (path.read_bytes(), path.stat().st_mtime_ns)
            for path in sorted(canonical_root.rglob("*"))
            if path.is_file()
        }

    before = snapshot()
    build_context_pack(
        tmp_path,
        query="read only",
        matched_records=[{"id": unit_id}],
        passages=[_passage(unit_id)],
    )
    after = snapshot()

    assert after == before
