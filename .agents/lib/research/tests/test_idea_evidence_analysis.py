from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.core import default_record, ensure_workspace, record_path
from research.evidence import verification_receipt_violations


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


def test_success_receipt_current_and_consumed_fill_starts_second_round(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    unit = record_path(tmp_path, "idea", idea_id).parent
    fill_path = unit / "analyze-fill.yaml"
    write_yaml_if_changed(fill_path, _fill(fill_path, source_id, "The baseline loses accuracy under unseen camera viewpoints."))
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify") == 0
    record = load_yaml(unit / "record.yaml", default={})
    assert verification_receipt_violations(
        record,
        unit,
        source_roots={source_id: record_path(tmp_path, "repo", source_id).parent},
    ) == []
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    refreshed = load_yaml(fill_path, default={})
    assert refreshed["reviewer"] == ""
    assert all(claim["text"] == "" for claim in refreshed["claims"])


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
    sidecar = load_yaml(unit / "discussion-judgements.yaml", default={})
    assert len(sidecar["items"]) == 2


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


def test_coherent_corpus_and_fill_view_tamper_cannot_replace_orientation_commitment(
    tmp_path: Path, monkeypatch
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
    fill_path = unit / "analyze-fill.yaml"
    fill = _fill(fill_path, source_id, "Late evidence was not frozen by the owner.")
    for claim in fill["claims"]:
        claim["evidence_refs"][0]["artifact"] = "late.txt"
    forged_context = dict(fill["preference_consumer"]["task_context"])
    forged_context["evidence_corpus_identity_digest"] = corpus["identity_digest"]
    forged_context["evidence_corpus_bytes_digest"] = corpus["bytes_digest"]
    fill["preference_consumer"] = idea._preference_consumer_view("analyze", forged_context)
    write_yaml_if_changed(fill_path, fill)
    record_before = (unit / "record.yaml").read_bytes()
    with pytest.raises(SystemExit):
        _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify")
    assert (unit / "record.yaml").read_bytes() == record_before
    assert not (unit / "analyze.yaml").exists()


def test_post_write_failure_rolls_back_and_same_fill_can_retry(
    tmp_path: Path, monkeypatch
) -> None:
    idea = _load_idea_module()
    idea_id, source_id = _setup(tmp_path, idea)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "prepare") == 0
    unit = record_path(tmp_path, "idea", idea_id).parent
    fill_path = unit / "analyze-fill.yaml"
    write_yaml_if_changed(fill_path, _fill(fill_path, source_id, "The baseline loses accuracy under unseen camera viewpoints."))
    original_build_index = idea.build_index
    monkeypatch.setattr(idea, "build_index", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("forced post-write failure")))
    with pytest.raises(RuntimeError, match="forced post-write failure"):
        _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify")
    assert not (unit / "analyze.yaml").exists()
    monkeypatch.setattr(idea, "build_index", original_build_index)
    assert _run(idea, monkeypatch, "analyze", "--idea-id", idea_id, "--phase", "verify") == 0


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
