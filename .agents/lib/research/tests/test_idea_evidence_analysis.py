from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.core import default_record, ensure_workspace, record_path
from research.evidence import EvidenceSourceSnapshot, verification_receipt_violations
from research.git_ops import undo_last_operation
from research.records import canonical_record_snapshot_for_record


def _load_idea_module():
    root = Path(__file__).resolve().parents[4]
    script = root / ".agents" / "skills" / "idea-workbench" / "scripts" / "idea.py"
    spec = importlib.util.spec_from_file_location("idea_workbench_script_for_analysis", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _setup(tmp_path: Path, idea) -> tuple[str, str]:
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    ensure_workspace(tmp_path)
    idea_record = default_record("idea", title="Evidence Idea", maturity="lightweight", source={"original_uri": "discussion"})
    idea_record["id"] = "i-evidence-123456"
    idea_record["payload"]["problem"]["problem_definition"] = "Improve transfer."
    idea_record["payload"]["hypothesis"]["core_hypothesis"] = "A structured bottleneck improves transfer."
    write_yaml_if_changed(record_path(tmp_path, "idea", idea_record["id"]), idea_record)

    repo_record = default_record("repo", title="Prior System", maturity="complete", source={"original_uri": "fixture"})
    repo_record["id"] = "r-prior-123456"
    repo_path = record_path(tmp_path, "repo", repo_record["id"])
    write_yaml_if_changed(repo_path, repo_record)
    (repo_path.parent / "evidence.txt").write_text(
        "The baseline loses accuracy under unseen camera viewpoints.\n",
        encoding="utf-8",
    )
    idea.PROJECT_ROOT = tmp_path
    idea.checkpoint_and_report = lambda *args, **kwargs: {}
    return idea_record["id"], repo_record["id"]


def _run(idea, monkeypatch, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["idea.py", *argv])
    return idea.main()


def _fill(path: Path, source_id: str, quote: str, *, selection_rank: int | None = None) -> dict:
    payload = load_yaml(path, default={})
    payload["reviewer"] = "runtime-agent"
    if selection_rank is not None:
        payload["selection_rank"] = selection_rank
    texts = {
        "novelty": "The idea differs by testing a structured bottleneck under viewpoint shift.",
        "feasibility": "A focused viewpoint-shift evaluation is feasible in the cited repo.",
        "recommendation": "Promising only if the bottleneck beats the cited baseline failure.",
        "killer-question": "Does the gain survive unseen camera viewpoints?",
    }
    for claim in payload["claims"]:
        claim["text"] = texts[claim["role"]]
        claim["evidence_refs"] = [
            {
                "source_unit_id": source_id,
                "artifact": "evidence.txt",
                "locator": "section:fixture",
                "quote": quote,
                "summary": "Grounds the comparison and test target.",
            }
        ]
    return payload


def _cross_unit_claim(source_id: str, quote: str) -> dict:
    return {
        "id": "cross-unit-evaluation",
        "text": "The cited baseline motivates a bounded viewpoint-shift test.",
        "claim_type": "evaluation",
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": [
            {
                "source_unit_id": source_id,
                "artifact": "evidence.txt",
                "locator": "section:fixture",
                "quote": quote,
                "summary": "Grounds the bounded evaluation.",
            }
        ],
    }


def _multi_setup(root: Path, idea, *, count: int = 3) -> tuple[list[str], str, Path]:
    root.mkdir()
    (root / ".agents").mkdir()
    (root / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    ensure_workspace(root)
    source_id = "r-concurrency-source"
    source = default_record("repo", title="Concurrency Source", maturity="complete", source={"original_uri": "fixture"})
    source["id"] = source_id
    source_path = record_path(root, "repo", source_id)
    write_yaml_if_changed(source_path, source)
    evidence_path = source_path.parent / "evidence.txt"
    evidence_path.write_text("Frozen evidence supports the bounded claim.\n", encoding="utf-8")
    idea_ids: list[str] = []
    for index in range(count):
        idea_id = f"i-concurrency-{index}"
        record = default_record("idea", title=f"Concurrent Idea {index}", maturity="lightweight", source={"original_uri": "discussion"})
        record["id"] = idea_id
        record["payload"]["problem"]["problem_definition"] = f"Problem {index}"
        record["payload"]["hypothesis"]["core_hypothesis"] = f"Hypothesis {index}"
        write_yaml_if_changed(record_path(root, "idea", idea_id), record)
        idea_ids.append(idea_id)
    idea.PROJECT_ROOT = root
    idea.checkpoint_and_report = lambda *args, **kwargs: {}
    return idea_ids, source_id, evidence_path


def _path_snapshot(paths: list[Path]) -> dict[Path, tuple[bytes, tuple[int, int, int]]]:
    return {
        path: (
            path.read_bytes(),
            (path.lstat().st_dev, path.lstat().st_ino, path.lstat().st_mode),
        )
        for path in paths
    }


def _optional_path_snapshot(
    paths: list[Path],
) -> dict[Path, tuple[bytes, tuple[int, int, int]] | None]:
    return {
        path: (
            _path_snapshot([path])[path]
            if path.exists() or path.is_symlink()
            else None
        )
        for path in paths
    }


def _symlink_snapshot(path: Path) -> tuple[str, tuple[int, int, int]]:
    metadata = path.lstat()
    return os.readlink(path), (metadata.st_dev, metadata.st_ino, metadata.st_mode)


def _journal_entry_snapshot(root: Path) -> dict[str, bytes]:
    journal = root / "kb/.journal"
    if not journal.exists():
        return {}
    return {
        path.relative_to(journal).as_posix(): path.read_bytes()
        for path in journal.glob("*.yaml")
    }


def _rewrite_corpus_as_v1(idea, corpus_path: Path) -> None:
    corpus = load_yaml(corpus_path, default={})
    corpus["schema"] = "idea-evidence-corpus/v1"
    for entry in corpus["entries"]:
        entry.pop("size")
    corpus["identity_digest"] = idea.canonical_digest([
        {"path": item["path"], "identity_digest": item["identity_digest"]}
        for item in corpus["entries"]
    ])
    corpus["bytes_digest"] = idea.canonical_digest([
        {"path": item["path"], "bytes_digest": item["bytes_digest"]}
        for item in corpus["entries"]
    ])
    write_yaml_if_changed(corpus_path, corpus)


def _discussion_fill(path: Path, source_id: str) -> dict:
    payload = load_yaml(path, default={})
    payload["reviewer"] = "runtime-agent"
    payload["conclusion"] = "The frozen evidence supports a guarded next experiment."
    for claim in payload["claims"]:
        claim["text"] = (
            payload["conclusion"]
            if claim["role"] == "conclusion"
            else f"Evidence-grounded {claim['role']} for this idea."
        )
        claim["evidence_refs"] = [{
            "source_unit_id": source_id,
            "artifact": "evidence.txt",
            "locator": "section:fixture",
            "quote": "The baseline loses accuracy under unseen camera viewpoints.",
            "summary": "Grounds this discussion judgement.",
        }]
    return payload


def test_analyze_prepare_is_fillable_and_has_no_verdict(tmp_path: Path, monkeypatch) -> None:
    idea = _load_idea_module()
    idea_id, _ = _setup(tmp_path, idea)

    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0

    fill = load_yaml(record_path(tmp_path, "idea", idea_id).parent / "analyze-fill.yaml", default={})
    assert all(claim["text"] == "" and claim["evidence_refs"] == [] for claim in fill["claims"])
    assert "score_breakdown" not in fill
    assert fill["descriptive_counts"]["note"].endswith("not scores or verdicts.")


def test_review_verify_persists_agent_judgements_without_heuristic_score(tmp_path: Path, monkeypatch) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "review", "--idea-id", idea_id, "--phase", "prepare") == 0
    fill_path = record_path(tmp_path, "idea", idea_id).parent / "review-fill.yaml"
    write_yaml_if_changed(
        fill_path,
        _fill(fill_path, source_id, "The baseline loses accuracy under unseen camera viewpoints.", selection_rank=1),
    )

    assert _run(idea, monkeypatch, "review", "--idea-id", idea_id, "--phase", "verify") == 0

    updated = load_yaml(record_path(tmp_path, "idea", idea_id), default={})
    assert updated["payload"]["analysis"]["novelty"].startswith("The idea differs")
    assert updated["payload"]["review"]["recommendation"].startswith("Promising only")
    assert updated["payload"]["review"]["selection_rank"] == 1
    assert updated["payload"]["review"]["score_breakdown"] == {}
    assert len(updated["payload"]["review"]["claims"]) == 4


def test_analyze_verify_rejects_fabricated_evidence(tmp_path: Path, monkeypatch) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    fill_path = record_path(tmp_path, "idea", idea_id).parent / "analyze-fill.yaml"
    write_yaml_if_changed(fill_path, _fill(fill_path, source_id, "Fabricated evidence."))

    with pytest.raises(SystemExit) as exc:
        _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify")

    assert exc.value.code == 1
    updated = load_yaml(record_path(tmp_path, "idea", idea_id), default={})
    assert updated["payload"]["analysis"]["novelty"] == ""


def test_three_ideas_prepare_fill_verify_twice_without_global_staleness(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    for round_index in range(2):
        root = tmp_path / f"round-{round_index}"
        idea_ids, source_id, _evidence_path = _multi_setup(root, idea)
        for idea_id in idea_ids:
            assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
        for idea_id in idea_ids:
            unit = record_path(root, "idea", idea_id).parent
            corpus = load_yaml(unit / "analyze-evidence-corpus.yaml", default={})
            assert corpus["schema"] == "idea-evidence-corpus/v2"
            assert not any(
                entry["path"].endswith(("-fill.yaml", "-orientation.yaml", "-evidence-corpus.yaml"))
                for entry in corpus["entries"]
            )
            fill_path = unit / "analyze-fill.yaml"
            write_yaml_if_changed(
                fill_path,
                _fill(fill_path, source_id, "Frozen evidence supports the bounded claim."),
            )
        for idea_id in idea_ids:
            assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify") == 0


@pytest.mark.parametrize("replacement", ["mutate", "replace", "symlink"])
def test_cited_frozen_artifact_change_rejects_without_result_write(
    tmp_path: Path, monkeypatch, replacement: str
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    unit = record_path(tmp_path, "idea", idea_id).parent
    fill_path = unit / "analyze-fill.yaml"
    write_yaml_if_changed(
        fill_path,
        _fill(fill_path, source_id, "The baseline loses accuracy under unseen camera viewpoints."),
    )
    evidence_path = record_path(tmp_path, "repo", source_id).parent / "evidence.txt"
    if replacement == "mutate":
        evidence_path.write_text("The baseline now has different bytes.\n", encoding="utf-8")
    else:
        evidence_path.unlink()
        if replacement == "replace":
            evidence_path.write_text("The baseline loses accuracy under unseen camera viewpoints.\n", encoding="utf-8")
        else:
            target = tmp_path / "outside.txt"
            target.write_text("The baseline loses accuracy under unseen camera viewpoints.\n", encoding="utf-8")
            evidence_path.symlink_to(target)
    record_before = record_path(tmp_path, "idea", idea_id).read_bytes()
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify")
    assert record_path(tmp_path, "idea", idea_id).read_bytes() == record_before
    assert not (unit / "analyze.yaml").exists()


def test_unfrozen_new_artifact_rejects_but_unreferenced_changes_do_not(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    source_unit = record_path(tmp_path, "repo", source_id).parent
    (source_unit / "unreferenced.txt").write_text("Unreferenced mutable text.\n", encoding="utf-8")
    fill_path = record_path(tmp_path, "idea", idea_id).parent / "analyze-fill.yaml"
    fresh = _fill(fill_path, source_id, "Unreferenced mutable text.")
    for claim in fresh["claims"]:
        claim["evidence_refs"][0]["artifact"] = "unreferenced.txt"
    write_yaml_if_changed(fill_path, fresh)
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify")

    original = _fill(fill_path, source_id, "The baseline loses accuracy under unseen camera viewpoints.")
    write_yaml_if_changed(fill_path, original)
    (source_unit / "unreferenced.txt").write_text("Changed but still unreferenced.\n", encoding="utf-8")
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify") == 0


@pytest.mark.parametrize("operation", ["analyze", "discuss"])
def test_nonempty_prepare_retry_preserves_bytes_and_inodes(
    tmp_path: Path, monkeypatch, operation: str
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, operation, "--idea-id", idea_id, "--phase", "prepare") == 0
    unit = record_path(tmp_path, "idea", idea_id).parent
    fill_name = "discussion-fill.yaml" if operation == "discuss" else "analyze-fill.yaml"
    prefix = "discuss" if operation == "discuss" else "analyze"
    fill_path = unit / fill_name
    write_yaml_if_changed(
        fill_path,
        _discussion_fill(fill_path, source_id)
        if operation == "discuss"
        else _fill(fill_path, source_id, "The baseline loses accuracy under unseen camera viewpoints."),
    )
    watched = [
        unit / "record.yaml",
        fill_path,
        unit / f"{prefix}-orientation.yaml",
        unit / f"{prefix}-evidence-corpus.yaml",
    ]
    before = _path_snapshot(watched)
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, operation, "--idea-id", idea_id, "--phase", "prepare")
    assert _path_snapshot(watched) == before


def test_empty_prepare_retry_is_exact_no_churn(tmp_path: Path, monkeypatch) -> None:
    idea = _load_idea_module()
    idea_id, _source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    unit = record_path(tmp_path, "idea", idea_id).parent
    watched = [
        unit / "record.yaml",
        unit / "analyze-fill.yaml",
        unit / "analyze-orientation.yaml",
        unit / "analyze-evidence-corpus.yaml",
    ]
    before = _path_snapshot(watched)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    assert _path_snapshot(watched) == before


def test_bad_evidence_preflight_then_fix_same_fill_can_verify(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    unit = record_path(tmp_path, "idea", idea_id).parent
    fill_path = unit / "analyze-fill.yaml"
    write_yaml_if_changed(fill_path, _fill(fill_path, source_id, "fabricated"))
    watched = [unit / "record.yaml", fill_path, unit / "analyze-orientation.yaml", unit / "analyze-evidence-corpus.yaml"]
    before = _path_snapshot(watched)
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify")
    assert _path_snapshot(watched) == before
    write_yaml_if_changed(
        fill_path,
        _fill(fill_path, source_id, "The baseline loses accuracy under unseen camera viewpoints."),
    )
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify") == 0


@pytest.mark.parametrize(
    "mutation",
    ["claim_type", "confirmation_status", "claim_id", "extra_key"],
)
def test_verify_rejects_immutable_scaffold_mutation(
    tmp_path: Path, monkeypatch, mutation: str
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "review", "--idea-id", idea_id, "--phase", "prepare") == 0
    fill_path = record_path(tmp_path, "idea", idea_id).parent / "review-fill.yaml"
    fill = _fill(fill_path, source_id, "The baseline loses accuracy under unseen camera viewpoints.", selection_rank=1)
    if mutation == "extra_key":
        fill["unexpected"] = True
    elif mutation == "claim_id":
        fill["claims"][0]["id"] = "changed"
    else:
        fill["claims"][0][mutation] = "fact" if mutation == "claim_type" else "confirmed"
    write_yaml_if_changed(fill_path, fill)
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, "review", "--idea-id", idea_id, "--phase", "verify")


@pytest.mark.parametrize("mode", ["analyze", "review"])
def test_success_receipt_consumes_anchor_and_starts_second_round(
    tmp_path: Path, monkeypatch, mode: str
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, mode, "--idea-id", idea_id, "--phase", "prepare") == 0
    unit = record_path(tmp_path, "idea", idea_id).parent
    fill_path = unit / f"{mode}-fill.yaml"
    write_yaml_if_changed(
        fill_path,
        _fill(
            fill_path,
            source_id,
            "The baseline loses accuracy under unseen camera viewpoints.",
            selection_rank=1 if mode == "review" else None,
        ),
    )
    assert _run(idea, monkeypatch, mode, "--idea-id", idea_id, "--phase", "verify") == 0
    record = load_yaml(unit / "record.yaml", default={})
    assert mode not in record["payload"].get("idea_authoring_contracts", {})
    result = load_yaml(unit / f"{mode}.yaml", default={})
    assert result["authoring_provenance"]["mode"] == "owner-anchored/v1"
    assert len(result["authoring_provenance"]["authoring_contract_digest"]) == 64
    assert verification_receipt_violations(
        record,
        unit,
        source_roots={source_id: record_path(tmp_path, "repo", source_id).parent},
    ) == []
    assert _run(idea, monkeypatch, mode, "--idea-id", idea_id, "--phase", "prepare") == 0
    refreshed = load_yaml(fill_path, default={})
    assert refreshed["reviewer"] == ""
    assert all(claim["text"] == "" for claim in refreshed["claims"])
    refreshed_record = load_yaml(unit / "record.yaml", default={})
    assert refreshed_record["payload"]["idea_authoring_contracts"][mode]["operation"] == mode


def test_discussion_consumed_fill_allows_second_conclusion(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    unit = record_path(tmp_path, "idea", idea_id).parent
    for _round in range(2):
        assert _run(idea, monkeypatch, "discuss", "--idea-id", idea_id, "--phase", "prepare") == 0
        fill_path = unit / "discussion-fill.yaml"
        write_yaml_if_changed(fill_path, _discussion_fill(fill_path, source_id))
        assert _run(idea, monkeypatch, "discuss", "--idea-id", idea_id, "--phase", "verify") == 0
        record = load_yaml(unit / "record.yaml", default={})
        assert "discuss" not in record["payload"].get("idea_authoring_contracts", {})
    sidecar = load_yaml(unit / "discussion-judgements.yaml", default={})
    assert len(sidecar["items"]) == 2
    assert all(
        item["authoring_provenance"]["mode"] == "owner-anchored/v1"
        for item in sidecar["items"]
    )


def test_one_active_semantic_operation_blocks_another_until_consumed(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    unit = record_path(tmp_path, "idea", idea_id).parent
    assert _run(
        idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare"
    ) == 0
    analyze_paths = [
        unit / "record.yaml",
        unit / "analyze-fill.yaml",
        unit / "analyze-orientation.yaml",
        unit / "analyze-evidence-corpus.yaml",
    ]
    before = _path_snapshot(analyze_paths)
    with pytest.raises(SystemExit):
        _run(
            idea, monkeypatch, "review", "--idea-id", idea_id, "--phase", "prepare"
        )
    assert _path_snapshot(analyze_paths) == before
    assert not (unit / "review-fill.yaml").exists()
    assert not (unit / "review-orientation.yaml").exists()
    assert not (unit / "review-evidence-corpus.yaml").exists()

    fill_path = unit / "analyze-fill.yaml"
    write_yaml_if_changed(
        fill_path,
        _fill(
            fill_path,
            source_id,
            "The baseline loses accuracy under unseen camera viewpoints.",
        ),
    )
    assert _run(
        idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify"
    ) == 0
    assert _run(
        idea, monkeypatch, "review", "--idea-id", idea_id, "--phase", "prepare"
    ) == 0
    record = load_yaml(unit / "record.yaml", default={})
    assert set(record["payload"]["idea_authoring_contracts"]) == {"review"}


@pytest.mark.parametrize("command", ["analyze", "review", "discuss"])
@pytest.mark.parametrize("corpus_state", ["v1", "missing"])
def test_semantic_prepare_rejects_hybrid_owner_before_journal(
    tmp_path: Path, monkeypatch, command: str, corpus_state: str
) -> None:
    idea = _load_idea_module()
    idea_id, _source_id = _setup(tmp_path, idea)
    unit = record_path(tmp_path, "idea", idea_id).parent
    assert _run(
        idea, monkeypatch, command, "--idea-id", idea_id, "--phase", "prepare"
    ) == 0
    operation = "discuss" if command == "discuss" else command
    fill_path = (
        unit / "discussion-fill.yaml"
        if operation == "discuss"
        else unit / f"{operation}-fill.yaml"
    )
    orientation_path = unit / f"{operation}-orientation.yaml"
    corpus_path = unit / f"{operation}-evidence-corpus.yaml"
    if corpus_state == "v1":
        _rewrite_corpus_as_v1(idea, corpus_path)
    else:
        corpus_path.unlink()
    protected = [unit / "record.yaml", fill_path, orientation_path, corpus_path]
    before = _optional_path_snapshot(protected)

    with pytest.raises(SystemExit):
        _run(
            idea, monkeypatch, command, "--idea-id", idea_id, "--phase", "prepare"
        )
    assert _optional_path_snapshot(protected) == before


@pytest.mark.parametrize("command", ["analyze", "review", "discuss"])
@pytest.mark.parametrize(
    "tuple_state",
    [
        "v1_with_v2_orientation",
        "v1_without_orientation",
        "v1_with_malformed_orientation",
        "orientation_without_corpus",
    ],
)
def test_semantic_ownerless_mixed_tuple_is_rejected_before_journal(
    tmp_path: Path, monkeypatch, command: str, tuple_state: str
) -> None:
    idea = _load_idea_module()
    idea_id, _source_id = _setup(tmp_path, idea)
    unit = record_path(tmp_path, "idea", idea_id).parent
    assert _run(
        idea, monkeypatch, command, "--idea-id", idea_id, "--phase", "prepare"
    ) == 0
    operation = "discuss" if command == "discuss" else command
    fill_path = (
        unit / "discussion-fill.yaml"
        if operation == "discuss"
        else unit / f"{operation}-fill.yaml"
    )
    orientation_path = unit / f"{operation}-orientation.yaml"
    corpus_path = unit / f"{operation}-evidence-corpus.yaml"
    record_file = unit / "record.yaml"
    record = load_yaml(record_file, default={})
    record["payload"].pop("idea_authoring_contracts", None)
    write_yaml_if_changed(record_file, record)
    if tuple_state.startswith("v1_"):
        _rewrite_corpus_as_v1(idea, corpus_path)
    if tuple_state == "v1_without_orientation":
        orientation_path.unlink()
    elif tuple_state == "v1_with_malformed_orientation":
        write_yaml_if_changed(orientation_path, {"schema": "malformed"})
    elif tuple_state == "orientation_without_corpus":
        corpus_path.unlink()
    protected = [record_file, fill_path, orientation_path, corpus_path]
    before = _optional_path_snapshot(protected)

    with pytest.raises(SystemExit):
        _run(
            idea, monkeypatch, command, "--idea-id", idea_id, "--phase", "prepare"
        )
    assert _optional_path_snapshot(protected) == before


@pytest.mark.parametrize("tamper", ["duplicate", "unsafe", "bad_digest", "extra_key"])
def test_frozen_manifest_malformed_entries_fail_closed(
    tmp_path: Path, monkeypatch, tamper: str
) -> None:
    idea = _load_idea_module()
    idea_id, _source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    corpus_path = record_path(tmp_path, "idea", idea_id).parent / "analyze-evidence-corpus.yaml"
    corpus = load_yaml(corpus_path, default={})
    if tamper == "duplicate":
        corpus["entries"].append(dict(corpus["entries"][0]))
    elif tamper == "unsafe":
        corpus["entries"][0]["path"] = "kb/units/repos/../escape.txt"
    elif tamper == "bad_digest":
        corpus["entries"][0]["bytes_digest"] = "0" * 63
    else:
        corpus["entries"][0]["unexpected"] = True
    write_yaml_if_changed(corpus_path, corpus)
    with pytest.raises(ValueError):
        idea._validated_frozen_corpus(tmp_path, corpus_path)


def test_binary_artifacts_are_not_frozen_and_oversized_fill_fails_before_record_write(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    source_unit = record_path(tmp_path, "repo", source_id).parent
    (source_unit / "weights.bin").write_bytes(b"\x00\xff" * 1024)
    (source_unit / "paper.pdf").write_bytes(b"%PDF-binary")
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    unit = record_path(tmp_path, "idea", idea_id).parent
    corpus = load_yaml(unit / "analyze-evidence-corpus.yaml", default={})
    paths = {entry["path"] for entry in corpus["entries"]}
    assert not any(path.endswith(("weights.bin", "paper.pdf")) for path in paths)
    fill_path = unit / "analyze-fill.yaml"
    fill_path.write_bytes(b"x" * (idea.MAX_CORPUS_FILE_BYTES + 1))
    original_binding = idea.regular_file_binding

    def reject_if_oversized_was_hashed(path, **kwargs):
        if Path(path) == fill_path:
            raise AssertionError("oversized fill reached the hashing layer")
        return original_binding(path, **kwargs)

    monkeypatch.setattr(idea, "regular_file_binding", reject_if_oversized_was_hashed)
    record_before = _path_snapshot([unit / "record.yaml"])
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify")
    assert _path_snapshot([unit / "record.yaml"]) == record_before


def test_legacy_v1_nonempty_fill_remains_verifiable(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    unit = record_path(tmp_path, "idea", idea_id).parent
    corpus_path = unit / "analyze-evidence-corpus.yaml"
    orientation_path = unit / "analyze-orientation.yaml"
    corpus = load_yaml(corpus_path, default={})
    corpus["schema"] = "idea-evidence-corpus/v1"
    for entry in corpus["entries"]:
        entry.pop("size")
    corpus["identity_digest"] = idea.canonical_digest([
        {"path": item["path"], "identity_digest": item["identity_digest"]}
        for item in corpus["entries"]
    ])
    corpus["bytes_digest"] = idea.canonical_digest([
        {"path": item["path"], "bytes_digest": item["bytes_digest"]}
        for item in corpus["entries"]
    ])
    write_yaml_if_changed(corpus_path, corpus)
    write_yaml_if_changed(
        orientation_path,
        idea.idea_preference_orientation(
            "analyze",
            canonical_id=idea_id,
            corpus_commitment={},
            schema_version=1,
        ),
    )
    record_file = unit / "record.yaml"
    record = load_yaml(record_file, default={})
    del record["payload"]["idea_authoring_contracts"]["analyze"]
    record["payload"].pop("idea_authoring_contracts", None)
    write_yaml_if_changed(record_file, record)
    context = idea.idea_preference_context(
        tmp_path,
        operation="analyze",
        canonical_id=idea_id,
        orientation_path=orientation_path,
        corpus_path=corpus_path,
        excluded_paths=idea._corpus_exclusions(unit, "analyze"),
        record_path_value=unit / "record.yaml",
    )
    fill_path = unit / "analyze-fill.yaml"
    fill = _fill(fill_path, source_id, "The baseline loses accuracy under unseen camera viewpoints.")
    fill["preference_consumer"] = idea._preference_consumer_view("analyze", context)
    write_yaml_if_changed(fill_path, fill)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify") == 0
    result = load_yaml(unit / "analyze.yaml", default={})
    assert result["authoring_provenance"] == {"mode": "legacy-unanchored/v1"}
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify")
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    refreshed_record = load_yaml(record_file, default={})
    assert refreshed_record["payload"]["idea_authoring_contracts"]["analyze"]["schema"] == "idea-authoring-anchor/v1"
    assert load_yaml(corpus_path, default={})["schema"] == "idea-evidence-corpus/v2"


def test_receipt_time_evidence_mutation_is_rejected_before_first_write(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "review", "--idea-id", idea_id, "--phase", "prepare") == 0
    unit = record_path(tmp_path, "idea", idea_id).parent
    fill_path = unit / "review-fill.yaml"
    write_yaml_if_changed(fill_path, _fill(fill_path, source_id, "The baseline loses accuracy under unseen camera viewpoints.", selection_rank=1))
    evidence_path = record_path(tmp_path, "repo", source_id).parent / "evidence.txt"
    original_receipt = idea.build_verification_receipt

    def mutate_after_receipt(*args, **kwargs):
        result = original_receipt(*args, **kwargs)
        evidence_path.write_text("Changed during receipt construction.\n", encoding="utf-8")
        return result

    monkeypatch.setattr(idea, "build_verification_receipt", mutate_after_receipt)
    record_before = (unit / "record.yaml").read_bytes()
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, "review", "--idea-id", idea_id, "--phase", "verify")
    assert (unit / "record.yaml").read_bytes() == record_before
    assert not (unit / "review.yaml").exists()
    assert not (unit / "idea-card.md").exists()


def test_stable_cross_unit_snapshot_supports_validation_and_confirmation(
    tmp_path: Path,
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    quote = "The baseline loses accuracy under unseen camera viewpoints."
    claims = [_cross_unit_claim(source_id, quote)]
    source_roots = idea._trusted_claim_source_roots(
        tmp_path,
        claims,
        consumer_id=idea_id,
    )

    assert isinstance(source_roots[source_id], EvidenceSourceSnapshot)
    assert idea._verify_cross_unit_claims(
        tmp_path,
        claims,
        source_roots=source_roots,
    ) == []

    idea_path = record_path(tmp_path, "idea", idea_id)
    record = load_yaml(idea_path, default={})
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    record["information_types"] = ["evaluation", "unverified"]
    record["payload"]["claims"] = claims
    idea.build_verification_receipt(
        record,
        idea_path.parent,
        source_roots=source_roots,
    )
    idea.write_record(tmp_path, record, expected_revision=0)
    expected_record_snapshot = canonical_record_snapshot_for_record(tmp_path, record)

    idea.apply_confirmation(
        record,
        confirmed_by="Human Reviewer",
        evidence=["review conversation"],
        user_authorization="I confirm this evidence-grounded evaluation.",
        authorization_source="user_message",
        project_root=tmp_path,
        verification_root=idea_path.parent,
        trusted_source_roots=source_roots,
        expected_record_snapshot=expected_record_snapshot,
    )
    assert record["confirmation_status"] == "confirmed"


def test_replaced_source_ancestor_cannot_ground_outside_bytes_or_confirm(
    tmp_path: Path,
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    original_quote = "The baseline loses accuracy under unseen camera viewpoints."
    outside_sentinel = "OUTSIDE-ONLY-SENTINEL must never become canonical evidence."
    claims = [_cross_unit_claim(source_id, original_quote)]
    source_roots = idea._trusted_claim_source_roots(
        tmp_path,
        claims,
        consumer_id=idea_id,
    )
    source_snapshot = source_roots[source_id]
    assert isinstance(source_snapshot, EvidenceSourceSnapshot)

    idea_path = record_path(tmp_path, "idea", idea_id)
    record = load_yaml(idea_path, default={})
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    record["information_types"] = ["evaluation", "unverified"]
    record["payload"]["claims"] = claims
    idea.build_verification_receipt(
        record,
        idea_path.parent,
        source_roots=source_roots,
    )
    idea.write_record(tmp_path, record, expected_revision=0)
    expected_record_snapshot = canonical_record_snapshot_for_record(tmp_path, record)

    source_dir = record_path(tmp_path, "repo", source_id).parent
    parked_dir = tmp_path / "parked-source-unit"
    outside_dir = tmp_path / "outside-canonical-units"
    source_dir.rename(parked_dir)
    outside_dir.mkdir()
    (outside_dir / "record.yaml").write_bytes((parked_dir / "record.yaml").read_bytes())
    (outside_dir / "evidence.txt").write_text(outside_sentinel + "\n", encoding="utf-8")
    source_dir.symlink_to(outside_dir, target_is_directory=True)

    assert not source_snapshot.is_current()
    assert outside_sentinel.encode("utf-8") not in source_snapshot.artifacts[0].raw_bytes
    sentinel_claims = [_cross_unit_claim(source_id, outside_sentinel)]
    violations = idea._verify_cross_unit_claims(
        tmp_path,
        sentinel_claims,
        source_roots=source_roots,
    )
    assert violations
    assert any("no longer current" in violation for violation in violations)

    with pytest.raises(
        SystemExit,
        match="Confirmation evidence source is not a canonical safe unit or program",
    ):
        idea.apply_confirmation(
            record,
            confirmed_by="Human Reviewer",
            evidence=["review conversation"],
            user_authorization="I confirm this evidence-grounded evaluation.",
            authorization_source="user_message",
            project_root=tmp_path,
            verification_root=idea_path.parent,
            trusted_source_roots=source_roots,
            expected_record_snapshot=expected_record_snapshot,
        )
    assert record["confirmation_status"] == "pending_user_confirmation"


def test_hard_preference_change_is_rejected_at_final_boundary(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    unit = record_path(tmp_path, "idea", idea_id).parent
    fill_path = unit / "analyze-fill.yaml"
    write_yaml_if_changed(fill_path, _fill(fill_path, source_id, "The baseline loses accuracy under unseen camera viewpoints."))
    original_resolve = idea.resolve_idea_preferences
    calls = {"count": 0}

    def changing_hard_values(*args, **kwargs):
        result = dict(original_resolve(*args, **kwargs))
        calls["count"] += 1
        if calls["count"] >= 3:
            result["hard_value_digests"] = {"changed": "0" * 64}
        return result

    monkeypatch.setattr(idea, "resolve_idea_preferences", changing_hard_values)
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify")
    assert not (unit / "analyze.yaml").exists()


@pytest.mark.parametrize("round_index", [1, 2])
def test_coherent_corpus_and_fill_view_tamper_cannot_replace_orientation_commitment(
    tmp_path: Path, monkeypatch, round_index: int
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    unit = record_path(tmp_path, "idea", idea_id).parent
    source_unit = record_path(tmp_path, "repo", source_id).parent
    new_path = source_unit / "late.txt"
    new_path.write_text("Late evidence was not frozen by the owner.\n", encoding="utf-8")
    relative = new_path.relative_to(tmp_path).as_posix()
    binding = idea.regular_file_binding(new_path, logical_identity=relative, trusted_root=tmp_path)
    corpus_path = unit / "analyze-evidence-corpus.yaml"
    corpus = load_yaml(corpus_path, default={})
    corpus["entries"].append({"path": relative, **binding, "size": new_path.stat().st_size})
    corpus["entries"].sort(key=lambda item: item["path"])
    corpus["identity_digest"] = idea.canonical_digest([
        {"path": item["path"], "identity_digest": item["identity_digest"], "size": item["size"]}
        for item in corpus["entries"]
    ])
    corpus["bytes_digest"] = idea.canonical_digest([
        {"path": item["path"], "bytes_digest": item["bytes_digest"], "size": item["size"]}
        for item in corpus["entries"]
    ])
    write_yaml_if_changed(corpus_path, corpus)
    corpus_binding = idea.regular_file_binding(
        corpus_path,
        logical_identity=corpus_path.relative_to(tmp_path).as_posix(),
        trusted_root=tmp_path,
    )
    orientation_path = unit / "analyze-orientation.yaml"
    write_yaml_if_changed(
        orientation_path,
        idea.idea_preference_orientation(
            "analyze",
            canonical_id=idea_id,
            corpus_commitment=idea._corpus_commitment(corpus, corpus_binding),
        ),
    )
    fill_path = unit / "analyze-fill.yaml"
    fill = _fill(fill_path, source_id, "Late evidence was not frozen by the owner.")
    for claim in fill["claims"]:
        claim["evidence_refs"][0]["artifact"] = "late.txt"
    forged_context = dict(fill["preference_consumer"]["task_context"])
    forged_context["evidence_corpus_identity_digest"] = corpus["identity_digest"]
    forged_context["evidence_corpus_bytes_digest"] = corpus["bytes_digest"]
    orientation_binding = idea.regular_file_binding(
        orientation_path,
        logical_identity=orientation_path.name,
        trusted_root=tmp_path,
    )
    forged_context["immutable_orientation_identity_digest"] = orientation_binding["identity_digest"]
    forged_context["immutable_orientation_bytes_digest"] = orientation_binding["bytes_digest"]
    fill["preference_consumer"] = idea._preference_consumer_view("analyze", forged_context)
    write_yaml_if_changed(fill_path, fill)
    record_before = (unit / "record.yaml").read_bytes()
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify")
    assert (unit / "record.yaml").read_bytes() == record_before
    assert not (unit / "analyze.yaml").exists()


@pytest.mark.parametrize("round_index", [1, 2])
def test_generation_coherent_three_file_rewrite_cannot_materialize(
    tmp_path: Path, monkeypatch, round_index: int
) -> None:
    idea = _load_idea_module()
    root = tmp_path / "workspace"
    _idea_ids, source_id, _evidence_path = _multi_setup(root, idea, count=1)
    common = (
        "generate", "--title", "Anchored generation", "--count", "1",
        "--bundle-id", "idea-bundle-anchor",
    )
    assert _run(idea, monkeypatch, *common, "--phase", "prepare") == 0
    working = root / "kb/synthesis/idea-pools/idea-bundle-anchor"
    index_path = working / "index.yaml"
    prepared_before = index_path.read_bytes() if index_path.exists() else b""
    source_unit = record_path(root, "repo", source_id).parent
    late_path = source_unit / "generation-late.txt"
    late_path.write_text("Late generation evidence.\n", encoding="utf-8")
    relative = late_path.relative_to(root).as_posix()
    binding = idea.regular_file_binding(late_path, logical_identity=relative, trusted_root=root)
    corpus_path = working / "generation-evidence-corpus.yaml"
    corpus = load_yaml(corpus_path, default={})
    corpus["entries"].append({"path": relative, **binding, "size": late_path.stat().st_size})
    corpus["entries"].sort(key=lambda item: item["path"])
    corpus["identity_digest"] = idea.canonical_digest([
        {"path": item["path"], "identity_digest": item["identity_digest"], "size": item["size"]}
        for item in corpus["entries"]
    ])
    corpus["bytes_digest"] = idea.canonical_digest([
        {"path": item["path"], "bytes_digest": item["bytes_digest"], "size": item["size"]}
        for item in corpus["entries"]
    ])
    write_yaml_if_changed(corpus_path, corpus)
    corpus_binding = idea.regular_file_binding(
        corpus_path,
        logical_identity=corpus_path.relative_to(root).as_posix(),
        trusted_root=root,
    )
    fill_path = working / "generation-fill.yaml"
    fill = load_yaml(fill_path, default={})
    request_context = dict(fill["request_context"])
    orientation_path = working / "generation-orientation.yaml"
    write_yaml_if_changed(
        orientation_path,
        idea.idea_preference_orientation(
            "generate",
            canonical_id="idea-bundle-anchor",
            corpus_commitment=idea._corpus_commitment(corpus, corpus_binding),
            request_context=request_context,
        ),
    )
    forged_context = dict(fill["preference_consumer"]["task_context"])
    forged_context["evidence_corpus_identity_digest"] = corpus["identity_digest"]
    forged_context["evidence_corpus_bytes_digest"] = corpus["bytes_digest"]
    orientation_binding = idea.regular_file_binding(
        orientation_path,
        logical_identity=orientation_path.name,
        trusted_root=root,
    )
    forged_context["immutable_orientation_identity_digest"] = orientation_binding["identity_digest"]
    forged_context["immutable_orientation_bytes_digest"] = orientation_binding["bytes_digest"]
    fill["preference_consumer"] = idea._preference_consumer_view("generate", forged_context)
    fill["candidates"][0].update({
        "title": f"Forged late candidate {round_index}",
        "strategy": "Use post-prepare material",
        "problem": "The frozen boundary was bypassed.",
        "hypothesis": "A forged context would be accepted without an owner anchor.",
        "next_actions": ["Reject the coherent rewrite"],
    })
    write_yaml_if_changed(fill_path, fill)
    before_ids = {path.parent.name for path in (root / "kb/units/ideas").glob("*/record.yaml")}
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, *common, "--phase", "verify")
    after_ids = {path.parent.name for path in (root / "kb/units/ideas").glob("*/record.yaml")}
    assert after_ids == before_ids
    assert index_path.read_bytes() == prepared_before


@pytest.mark.parametrize("mutation", ["remove", "digest", "extra_key"])
def test_semantic_owner_anchor_mutation_fails_closed(
    tmp_path: Path, monkeypatch, mutation: str
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "review", "--idea-id", idea_id, "--phase", "prepare") == 0
    unit = record_path(tmp_path, "idea", idea_id).parent
    fill_path = unit / "review-fill.yaml"
    write_yaml_if_changed(
        fill_path,
        _fill(
            fill_path,
            source_id,
            "The baseline loses accuracy under unseen camera viewpoints.",
            selection_rank=1,
        ),
    )
    record_file = unit / "record.yaml"
    record = load_yaml(record_file, default={})
    anchor = record["payload"]["idea_authoring_contracts"]["review"]
    if mutation == "remove":
        del record["payload"]["idea_authoring_contracts"]["review"]
    elif mutation == "digest":
        anchor["request_context_digest"] = "0" * 64
    else:
        anchor["unexpected"] = True
    write_yaml_if_changed(record_file, record)
    mutated = record_file.read_bytes()
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, "review", "--idea-id", idea_id, "--phase", "verify")
    assert record_file.read_bytes() == mutated
    assert not (unit / "review.yaml").exists()
    assert not (unit / "idea-card.md").exists()


@pytest.mark.parametrize("round_index", [1, 2])
def test_generation_prepared_index_drift_is_not_overwritten(
    tmp_path: Path, monkeypatch, round_index: int
) -> None:
    idea = _load_idea_module()
    root = tmp_path / "workspace"
    _multi_setup(root, idea, count=1)
    common = (
        "generate", "--title", "Prepared sentinel", "--count", "1",
        "--bundle-id", "idea-bundle-sentinel",
    )
    assert _run(idea, monkeypatch, *common, "--phase", "prepare") == 0
    working = root / "kb/synthesis/idea-pools/idea-bundle-sentinel"
    fill_path = working / "generation-fill.yaml"
    fill = load_yaml(fill_path, default={})
    fill["candidates"][0].update({
        "title": f"Sentinel candidate {round_index}",
        "strategy": "Respect prepared state",
        "problem": "Verify must not overwrite drifted owner state.",
        "hypothesis": "Exact prepared CAS rejects the drift.",
        "next_actions": ["Keep the sentinel intact"],
    })
    write_yaml_if_changed(fill_path, fill)
    index_path = working / "index.yaml"
    prepared = load_yaml(index_path, default={})
    prepared["sentinel"] = f"do-not-overwrite-{round_index}"
    write_yaml_if_changed(index_path, prepared)
    sentinel_bytes = index_path.read_bytes()
    before_ids = {path.parent.name for path in (root / "kb/units/ideas").glob("*/record.yaml")}
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, *common, "--phase", "verify")
    assert index_path.read_bytes() == sentinel_bytes
    assert {path.parent.name for path in (root / "kb/units/ideas").glob("*/record.yaml")} == before_ids


def test_generation_prepared_binding_rejects_same_bytes_atomic_replacement(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    root = tmp_path / "workspace"
    _multi_setup(root, idea, count=1)
    common = (
        "generate", "--title", "Prepared CAS", "--count", "1",
        "--bundle-id", "idea-bundle-cas",
    )
    assert _run(idea, monkeypatch, *common, "--phase", "prepare") == 0
    working = root / "kb/synthesis/idea-pools/idea-bundle-cas"
    fill_path = working / "generation-fill.yaml"
    fill = load_yaml(fill_path, default={})
    fill["candidates"][0].update({
        "title": "CAS candidate",
        "strategy": "Bind the prepared inode transiently",
        "problem": "Same bytes can still replace the owner file.",
        "hypothesis": "Transient identity comparison detects replacement.",
        "next_actions": ["Reject before candidate write"],
    })
    write_yaml_if_changed(fill_path, fill)
    index_path = working / "index.yaml"
    original_preflight = idea._idea_transaction_preflight
    swapped = {"done": False}

    def replace_before_locked_preflight(args, project_root):
        if not swapped["done"] and args.command == "generate" and args.phase == "verify":
            replacement = index_path.with_name("index-replacement.yaml")
            replacement.write_bytes(index_path.read_bytes())
            replacement.replace(index_path)
            swapped["done"] = True
        return original_preflight(args, project_root)

    monkeypatch.setattr(idea, "_idea_transaction_preflight", replace_before_locked_preflight)
    before_ids = {path.parent.name for path in (root / "kb/units/ideas").glob("*/record.yaml")}
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, *common, "--phase", "verify")
    assert {path.parent.name for path in (root / "kb/units/ideas").glob("*/record.yaml")} == before_ids


def test_generation_prepared_state_retries_then_materializes_and_becomes_terminal(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    root = tmp_path / "workspace"
    _multi_setup(root, idea, count=1)
    common = (
        "generate", "--title", "Prepared lifecycle", "--count", "1",
        "--bundle-id", "idea-bundle-lifecycle",
    )
    assert _run(idea, monkeypatch, *common, "--phase", "prepare") == 0
    working = root / "kb/synthesis/idea-pools/idea-bundle-lifecycle"
    index_path = working / "index.yaml"
    prepared_snapshot = _path_snapshot([index_path])
    assert load_yaml(index_path, default={})["status"] == "prepared"
    assert _run(idea, monkeypatch, *common, "--phase", "prepare") == 0
    assert _path_snapshot([index_path]) == prepared_snapshot
    fill_path = working / "generation-fill.yaml"
    fill = load_yaml(fill_path, default={})
    fill["candidates"][0].update({
        "title": "Lifecycle candidate",
        "strategy": "Resume the anchored prepared task",
        "problem": "Prepared state must not be terminal.",
        "hypothesis": "Exact CAS permits one materialization.",
        "next_actions": ["Materialize once"],
    })
    write_yaml_if_changed(fill_path, fill)
    assert _run(idea, monkeypatch, *common, "--phase", "verify") == 0
    materialized = index_path.read_bytes()
    active = load_yaml(index_path, default={})
    assert active["status"] == "active"
    assert active["authoring_provenance"]["mode"] == "owner-anchored/v1"
    assert len(active["authoring_provenance"]["authoring_contract_digest"]) == 64
    assert "authoring_contract" not in active
    assert idea._is_prepared_generation_bundle(active) is False
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, *common, "--phase", "prepare")
    assert index_path.read_bytes() == materialized


def test_generation_prepare_rebuilds_missing_fill_and_checkpoints_exact_target(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    root = tmp_path / "workspace"
    _multi_setup(root, idea, count=1)
    bundle_id = "idea-bundle-rebuild-fill"
    common = (
        "generate", "--title", "Rebuild fill", "--count", "1",
        "--bundle-id", bundle_id,
    )
    assert _run(idea, monkeypatch, *common, "--phase", "prepare") == 0
    working = root / "kb/synthesis/idea-pools" / bundle_id
    index_path = working / "index.yaml"
    fill_path = working / "generation-fill.yaml"
    prepared_bytes = index_path.read_bytes()
    expected_fill_bytes = fill_path.read_bytes()
    fill_path.unlink()
    checkpoints: list[dict[str, object]] = []

    def capture_checkpoint(project_root: Path, **kwargs) -> dict[str, object]:
        checkpoints.append({"root": project_root, **kwargs})
        return {"committed": False}

    monkeypatch.setattr(idea, "checkpoint_and_report", capture_checkpoint)
    assert _run(idea, monkeypatch, *common, "--phase", "prepare") == 0
    assert fill_path.read_bytes() == expected_fill_bytes
    assert index_path.read_bytes() == prepared_bytes
    assert len(checkpoints) == 1
    assert checkpoints[0]["root"] == root
    assert checkpoints[0]["trigger"] == "milestone"
    assert checkpoints[0]["target_paths"] == [fill_path]


@pytest.mark.parametrize(
    "tuple_state",
    [
        "v1_with_v2_orientation",
        "v1_without_orientation",
        "v1_with_malformed_orientation",
        "v1_with_wrong_request_orientation",
        "orientation_without_corpus",
    ],
)
def test_generation_ownerless_mixed_tuple_is_rejected_before_journal(
    tmp_path: Path, monkeypatch, tuple_state: str
) -> None:
    idea = _load_idea_module()
    root = tmp_path / "workspace"
    _multi_setup(root, idea, count=1)
    bundle_id = "idea-bundle-ownerless-mixed"
    common = (
        "generate", "--title", "Ownerless mixed", "--count", "1",
        "--bundle-id", bundle_id,
    )
    assert _run(idea, monkeypatch, *common, "--phase", "prepare") == 0
    working = root / "kb/synthesis/idea-pools" / bundle_id
    index_path = working / "index.yaml"
    fill_path = working / "generation-fill.yaml"
    orientation_path = working / "generation-orientation.yaml"
    corpus_path = working / "generation-evidence-corpus.yaml"
    request_context = dict(load_yaml(fill_path, default={})["request_context"])
    index_path.unlink()
    if tuple_state.startswith("v1_"):
        _rewrite_corpus_as_v1(idea, corpus_path)
    if tuple_state == "v1_without_orientation":
        orientation_path.unlink()
    elif tuple_state == "v1_with_malformed_orientation":
        write_yaml_if_changed(orientation_path, {"schema": "malformed"})
    elif tuple_state == "v1_with_wrong_request_orientation":
        wrong_request = {**request_context, "title": "Different request"}
        write_yaml_if_changed(
            orientation_path,
            idea.idea_preference_orientation(
                "generate",
                canonical_id=bundle_id,
                corpus_commitment={},
                request_context=wrong_request,
                schema_version=1,
            ),
        )
    elif tuple_state == "orientation_without_corpus":
        corpus_path.unlink()
    protected = [index_path, fill_path, orientation_path, corpus_path]
    before = _optional_path_snapshot(protected)

    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, *common, "--phase", "prepare")
    assert _optional_path_snapshot(protected) == before


def test_generation_exact_legacy_tuple_can_refresh_to_new_owner(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    root = tmp_path / "workspace"
    _multi_setup(root, idea, count=1)
    bundle_id = "idea-bundle-legacy-refresh"
    common = (
        "generate", "--title", "Legacy refresh", "--count", "1",
        "--bundle-id", bundle_id,
    )
    assert _run(idea, monkeypatch, *common, "--phase", "prepare") == 0
    working = root / "kb/synthesis/idea-pools" / bundle_id
    index_path = working / "index.yaml"
    fill_path = working / "generation-fill.yaml"
    orientation_path = working / "generation-orientation.yaml"
    corpus_path = working / "generation-evidence-corpus.yaml"
    request_context = dict(load_yaml(fill_path, default={})["request_context"])
    index_path.unlink()
    fill_path.unlink()
    _rewrite_corpus_as_v1(idea, corpus_path)
    write_yaml_if_changed(
        orientation_path,
        idea.idea_preference_orientation(
            "generate",
            canonical_id=bundle_id,
            corpus_commitment={},
            request_context=request_context,
            schema_version=1,
        ),
    )

    assert _run(idea, monkeypatch, *common, "--phase", "prepare") == 0
    prepared = load_yaml(index_path, default={})
    assert prepared["status"] == "prepared"
    assert prepared["authoring_contract"]["operation"] == "generate"
    assert load_yaml(corpus_path, default={})["schema"] == "idea-evidence-corpus/v2"
    assert load_yaml(orientation_path, default={})["schema"] == "idea-preference-orientation/v2"
    assert fill_path.exists()


@pytest.mark.parametrize("drift_schema_and_status", [False, True])
def test_prepared_generation_bundle_rejects_generic_bundle_entrypoints(
    tmp_path: Path, monkeypatch, drift_schema_and_status: bool
) -> None:
    idea = _load_idea_module()
    root = tmp_path / "workspace"
    _multi_setup(root, idea, count=1)
    bundle_id = "idea-bundle-prepared-routing"
    common = (
        "generate", "--title", "Prepared routing", "--count", "1",
        "--bundle-id", bundle_id,
    )
    assert _run(idea, monkeypatch, *common, "--phase", "prepare") == 0
    index_path = root / "kb/synthesis/idea-pools" / bundle_id / "index.yaml"
    if drift_schema_and_status:
        drifted = load_yaml(index_path, default={})
        drifted["schema"] = "drifted-away-from-prepared-schema"
        drifted["status"] = "drifted-away-from-prepared-status"
        write_yaml_if_changed(index_path, drifted)
        assert "authoring_contract" in drifted
        assert "request_context_digest" in drifted
    before = _path_snapshot([index_path])

    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, "review-assist", "--bundle-id", bundle_id)
    assert _path_snapshot([index_path]) == before
    with pytest.raises(SystemExit):
        _run(
            idea,
            monkeypatch,
            "select-best",
            "--bundle-id",
            bundle_id,
            "--evidence",
            "fixture",
        )
    assert _path_snapshot([index_path]) == before
    with pytest.raises(ValueError):
        idea.ensure_bundle(
            root, bundle_id, title="x", source="", pool="", strategy="review"
        )
    with pytest.raises(ValueError):
        idea.update_bundle(root, bundle_id, idea_ids=[])
    assert _path_snapshot([index_path]) == before


@pytest.mark.parametrize("attack", ["index_symlink", "bundle_ancestor_symlink"])
def test_generic_bundle_symlink_paths_fail_before_journal_without_touching_victim(
    tmp_path: Path, monkeypatch, attack: str
) -> None:
    idea = _load_idea_module()
    root = tmp_path / "workspace"
    _multi_setup(root, idea, count=1)
    pool = "unsafe-pool"
    bundle_id = "unsafe-pool"
    pools_root = root / "kb/synthesis/idea-pools"
    pools_root.mkdir(parents=True, exist_ok=True)
    bundle = pools_root / bundle_id
    victim = root / "victim-bundle"
    victim.mkdir()
    victim_index = victim / "index.yaml"
    write_yaml_if_changed(victim_index, {"id": "victim", "sentinel": "preserve"})
    victim_marker = victim / "marker.txt"
    victim_marker.write_text("do not touch\n", encoding="utf-8")
    if attack == "index_symlink":
        bundle.mkdir()
        link_path = bundle / "index.yaml"
        link_path.symlink_to(victim_index)
    else:
        link_path = bundle
        link_path.symlink_to(victim, target_is_directory=True)
    victim_before = _path_snapshot([victim_index, victim_marker])
    link_before = _symlink_snapshot(link_path)
    journal_before = _journal_entry_snapshot(root)

    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, "review-assist", "--pool", pool)
    assert _path_snapshot([victim_index, victim_marker]) == victim_before
    assert _symlink_snapshot(link_path) == link_before
    assert not (victim / "review-assist.md").exists()
    assert _journal_entry_snapshot(root) == journal_before

    with pytest.raises(SystemExit):
        _run(
            idea,
            monkeypatch,
            "select-best",
            "--pool",
            pool,
            "--evidence",
            "fixture",
        )
    with pytest.raises(ValueError):
        idea.ensure_bundle(
            root, bundle_id, title="unsafe", source="", pool=pool, strategy="review"
        )
    with pytest.raises(ValueError):
        idea.update_bundle(root, bundle_id, idea_ids=[])
    assert _path_snapshot([victim_index, victim_marker]) == victim_before
    assert _symlink_snapshot(link_path) == link_before
    assert _journal_entry_snapshot(root) == journal_before


def test_generic_bundle_locked_preflight_rejects_index_symlink_swap(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    root = tmp_path / "workspace"
    _multi_setup(root, idea, count=1)
    pool = "locked-swap-pool"
    bundle_id = "locked-swap-pool"
    idea.ensure_bundle(
        root, bundle_id, title="safe before swap", source="", pool=pool, strategy="review"
    )
    bundle = root / "kb/synthesis/idea-pools" / bundle_id
    index_path = bundle / "index.yaml"
    victim = root / "locked-swap-victim.yaml"
    write_yaml_if_changed(victim, {"sentinel": "preserve"})
    victim_before = _path_snapshot([victim])
    journal_before = _journal_entry_snapshot(root)
    original_preflight = idea._idea_transaction_preflight
    swapped: dict[str, object] = {}

    def swap_under_lock(args, project_root):
        if not swapped:
            index_path.unlink()
            index_path.symlink_to(victim)
            swapped["link"] = _symlink_snapshot(index_path)
        return original_preflight(args, project_root)

    monkeypatch.setattr(idea, "_idea_transaction_preflight", swap_under_lock)
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, "review-assist", "--pool", pool)
    assert _symlink_snapshot(index_path) == swapped["link"]
    assert _path_snapshot([victim]) == victim_before
    assert not (bundle / "review-assist.md").exists()
    assert _journal_entry_snapshot(root) == journal_before


def test_generic_bundle_regular_path_still_supports_review_assist(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    root = tmp_path / "workspace"
    idea_ids, _source_id, _evidence = _multi_setup(root, idea, count=1)
    assert _run(
        idea, monkeypatch, "review-assist", "--idea-id", idea_ids[0]
    ) == 0
    bundles = [path for path in (root / "kb/synthesis/idea-pools").iterdir() if path.is_dir()]
    assert len(bundles) == 1
    assert (bundles[0] / "index.yaml").is_file()
    assert not (bundles[0] / "index.yaml").is_symlink()
    assert (bundles[0] / "review-assist.md").is_file()


def test_legacy_v1_generation_is_one_time_and_records_value_free_provenance(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    root = tmp_path / "workspace"
    _multi_setup(root, idea, count=1)
    bundle_id = "idea-bundle-legacy"
    common = (
        "generate", "--title", "Legacy generation", "--count", "1",
        "--bundle-id", bundle_id,
    )
    assert _run(idea, monkeypatch, *common, "--phase", "prepare") == 0
    working = root / "kb/synthesis/idea-pools" / bundle_id
    corpus_path = working / "generation-evidence-corpus.yaml"
    corpus = load_yaml(corpus_path, default={})
    corpus["schema"] = "idea-evidence-corpus/v1"
    for entry in corpus["entries"]:
        entry.pop("size")
    corpus["identity_digest"] = idea.canonical_digest([
        {"path": item["path"], "identity_digest": item["identity_digest"]}
        for item in corpus["entries"]
    ])
    corpus["bytes_digest"] = idea.canonical_digest([
        {"path": item["path"], "bytes_digest": item["bytes_digest"]}
        for item in corpus["entries"]
    ])
    write_yaml_if_changed(corpus_path, corpus)
    fill_path = working / "generation-fill.yaml"
    fill = load_yaml(fill_path, default={})
    request_context = dict(fill["request_context"])
    orientation_path = working / "generation-orientation.yaml"
    write_yaml_if_changed(
        orientation_path,
        idea.idea_preference_orientation(
            "generate",
            canonical_id=bundle_id,
            corpus_commitment={},
            request_context=request_context,
            schema_version=1,
        ),
    )
    index_path = working / "index.yaml"
    index_path.unlink()
    context = idea.idea_preference_context(
        root,
        operation="generate",
        canonical_id=bundle_id,
        orientation_path=orientation_path,
        corpus_path=corpus_path,
        excluded_paths=set(),
        request_context=request_context,
    )
    fill["preference_consumer"] = idea._preference_consumer_view("generate", context)
    fill["candidates"][0].update({
        "title": "Legacy candidate",
        "strategy": "Consume the legacy task once",
        "problem": "Legacy tasks have no persisted owner anchor.",
        "hypothesis": "A one-time compatibility path preserves old authored work.",
        "next_actions": ["Record value-free provenance"],
    })
    write_yaml_if_changed(fill_path, fill)

    assert _run(idea, monkeypatch, *common, "--phase", "verify") == 0
    active = load_yaml(index_path, default={})
    assert active["status"] == "active"
    assert active["authoring_provenance"] == {"mode": "legacy-unanchored/v1"}
    assert "authoring_contract" not in active
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, *common, "--phase", "verify")


def test_generation_post_write_failure_restores_prepared_owner_and_retries(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    root = tmp_path / "workspace"
    _multi_setup(root, idea, count=1)
    bundle_id = "idea-bundle-rollback"
    common = (
        "generate", "--title", "Rollback generation", "--count", "1",
        "--bundle-id", bundle_id,
    )
    assert _run(idea, monkeypatch, *common, "--phase", "prepare") == 0
    working = root / "kb/synthesis/idea-pools" / bundle_id
    index_path = working / "index.yaml"
    fill_path = working / "generation-fill.yaml"
    fill = load_yaml(fill_path, default={})
    fill["candidates"][0].update({
        "title": "Rollback candidate",
        "strategy": "Retry the exact anchored task",
        "problem": "A failure may occur after candidate writes.",
        "hypothesis": "The transaction restores the prepared owner state exactly.",
        "next_actions": ["Retry after rollback"],
    })
    write_yaml_if_changed(fill_path, fill)
    prepared_bytes = index_path.read_bytes()
    before_ids = {
        path.parent.name
        for path in (root / "kb/units/ideas").glob("*/record.yaml")
    }
    original_build_index = idea.build_index
    monkeypatch.setattr(
        idea,
        "build_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("forced generation post-write failure")
        ),
    )
    with pytest.raises(RuntimeError, match="forced generation post-write failure"):
        _run(idea, monkeypatch, *common, "--phase", "verify")
    assert index_path.read_bytes() == prepared_bytes
    assert {
        path.parent.name
        for path in (root / "kb/units/ideas").glob("*/record.yaml")
    } == before_ids
    monkeypatch.setattr(idea, "build_index", original_build_index)
    assert _run(idea, monkeypatch, *common, "--phase", "verify") == 0
    assert load_yaml(index_path, default={})["status"] == "active"


def test_undo_semantic_verify_restores_active_anchor_and_allows_same_verify(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    unit = record_path(tmp_path, "idea", idea_id).parent
    assert _run(
        idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare"
    ) == 0
    fill_path = unit / "analyze-fill.yaml"
    write_yaml_if_changed(
        fill_path,
        _fill(
            fill_path,
            source_id,
            "The baseline loses accuracy under unseen camera viewpoints.",
        ),
    )
    prepared_record_bytes = (unit / "record.yaml").read_bytes()
    assert _run(
        idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify"
    ) == 0
    completed = load_yaml(unit / "record.yaml", default={})
    assert "analyze" not in completed["payload"].get("idea_authoring_contracts", {})

    undone = undo_last_operation(tmp_path)
    assert undone["restored_paths"]
    assert (unit / "record.yaml").read_bytes() == prepared_record_bytes
    assert not (unit / "analyze.yaml").exists()
    restored = load_yaml(unit / "record.yaml", default={})
    assert restored["payload"]["idea_authoring_contracts"]["analyze"]["operation"] == "analyze"
    assert _run(
        idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify"
    ) == 0


def test_undo_generation_materialization_restores_prepared_bundle_and_retries(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    root = tmp_path / "workspace"
    _multi_setup(root, idea, count=1)
    bundle_id = "idea-bundle-undo"
    common = (
        "generate", "--title", "Undo generation", "--count", "1",
        "--bundle-id", bundle_id,
    )
    assert _run(idea, monkeypatch, *common, "--phase", "prepare") == 0
    working = root / "kb/synthesis/idea-pools" / bundle_id
    index_path = working / "index.yaml"
    fill_path = working / "generation-fill.yaml"
    fill = load_yaml(fill_path, default={})
    fill["candidates"][0].update({
        "title": "Undo candidate",
        "strategy": "Restore prepared ownership",
        "problem": "Materialization may need to be undone.",
        "hypothesis": "Undo restores the exact prepared bytes and removes candidates.",
        "next_actions": ["Verify again from the same fill"],
    })
    write_yaml_if_changed(fill_path, fill)
    prepared_bytes = index_path.read_bytes()
    assert _run(idea, monkeypatch, *common, "--phase", "verify") == 0
    active = load_yaml(index_path, default={})
    candidate_path = record_path(root, "idea", active["idea_ids"][0])
    assert candidate_path.exists()

    undone = undo_last_operation(root)
    assert undone["restored_paths"]
    assert index_path.read_bytes() == prepared_bytes
    assert load_yaml(index_path, default={})["status"] == "prepared"
    assert not candidate_path.exists()
    assert _run(idea, monkeypatch, *common, "--phase", "verify") == 0
    assert load_yaml(index_path, default={})["status"] == "active"


def test_post_write_failure_rolls_back_and_same_fill_can_retry(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    unit = record_path(tmp_path, "idea", idea_id).parent
    fill_path = unit / "analyze-fill.yaml"
    write_yaml_if_changed(fill_path, _fill(fill_path, source_id, "The baseline loses accuracy under unseen camera viewpoints."))
    prepared_record_bytes = (unit / "record.yaml").read_bytes()
    original_build_index = idea.build_index
    monkeypatch.setattr(idea, "build_index", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("forced post-write failure")))
    with pytest.raises(RuntimeError, match="forced post-write failure"):
        _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify")
    assert not (unit / "analyze.yaml").exists()
    assert (unit / "record.yaml").read_bytes() == prepared_record_bytes
    restored = load_yaml(unit / "record.yaml", default={})
    assert restored["payload"]["idea_authoring_contracts"]["analyze"]["operation"] == "analyze"
    monkeypatch.setattr(idea, "build_index", original_build_index)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify") == 0
    completed = load_yaml(unit / "record.yaml", default={})
    assert "analyze" not in completed["payload"].get("idea_authoring_contracts", {})


def test_locked_preflight_rejects_fuzzy_resolution_switch_without_writes(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    idea_ids, _source_id, _evidence_path = _multi_setup(tmp_path / "workspace", idea, count=2)
    original_locate = idea.locate_record
    resolved = [original_locate(idea.PROJECT_ROOT, idea_id, kind="idea") for idea_id in idea_ids]
    calls = {"count": 0}

    def switching_locate(root, requested, *args, **kwargs):
        if requested != "moving-alias":
            return original_locate(root, requested, *args, **kwargs)
        index = min(calls["count"], 1)
        calls["count"] += 1
        return resolved[index]

    monkeypatch.setattr(idea, "locate_record", switching_locate)
    before = _path_snapshot([path for _record, path in resolved])
    with pytest.raises(SystemExit, match="resolution changed"):
        _run(idea, monkeypatch, "analyze", "--idea-id", "moving-alias", "--phase", "prepare")
    assert _path_snapshot([path for _record, path in resolved]) == before
    assert not any((path.parent / "analyze-fill.yaml").exists() for _record, path in resolved)
