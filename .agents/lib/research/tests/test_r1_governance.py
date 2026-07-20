from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from research.confirm import apply_confirmation, is_ai_signer
from research.evidence import build_verification_receipt, verify_claim_evidence
from research import journal
from research.paths import record_path, unit_root
from research.records import normalize_record_schema
from research.core import default_record, locate_record, write_record
from research.common import load_yaml, write_yaml_if_changed


def _load_skill_script(skill: str, script_name: str):
    project = Path(__file__).resolve().parents[4]
    path = project / ".agents" / "skills" / skill / "scripts" / script_name
    module_name = f"r1_{skill.replace('-', '_')}_{script_name.replace('.py', '')}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def _tree_bytes(root: Path) -> dict[str, bytes]:
    if not root.exists():
        return {}
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _claim(artifact: str, *, external: bool = False) -> dict:
    ref = {
        "source_unit_id": "p-r1-123456",
        "artifact": artifact,
        "locator": "section:test",
        "quote": "grounded words",
    }
    if external:
        ref["external_source"] = {"kind": "repo"}
    return {
        "id": "claim-r1",
        "text": "A grounded judgement.",
        "claim_type": "evaluation",
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": [ref],
    }


def test_r1_evidence_containment_rejects_absolute_parent_and_symlink_escape(tmp_path: Path) -> None:
    unit_root = tmp_path / "unit"
    unit_root.mkdir()
    (unit_root / "inside.md").write_text("grounded words", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text("grounded words", encoding="utf-8")
    (unit_root / "escape.md").symlink_to(outside)

    assert verify_claim_evidence(_claim("inside.md"), unit_root) == []
    assert "absolute path" in verify_claim_evidence(_claim(outside.as_posix()), unit_root)[0]
    assert "must not contain '..'" in verify_claim_evidence(_claim("../outside.md"), unit_root)[0]
    assert "escapes allowed unit root" in verify_claim_evidence(_claim("escape.md"), unit_root)[0]


def test_r1_repo_external_source_requires_trusted_matching_base_root(tmp_path: Path) -> None:
    unit_root = tmp_path / "unit"
    repo_root = tmp_path / "repo"
    unit_root.mkdir()
    repo_root.mkdir()
    (repo_root / "README.md").write_text("grounded words", encoding="utf-8")
    claim = _claim("README.md", external=True)

    assert "trusted base-root contract" in verify_claim_evidence(claim, unit_root)[0]
    assert verify_claim_evidence(
        claim,
        unit_root,
        external_source={"kind": "repo", "base_root": repo_root.as_posix()},
    ) == []

    escaped = _claim("../unit/inside.md", external=True)
    assert "must not contain '..'" in verify_claim_evidence(
        escaped,
        unit_root,
        external_source={"kind": "repo", "base_root": repo_root.as_posix()},
    )[0]


def _verified_paper(project_root: Path) -> dict:
    record = {
        "id": "p-r1-123456",
        "kind": "paper",
        "information_types": ["fact", "inference", "evaluation"],
        "confirmation_status": "pending_user_confirmation",
        "needs_human_confirmation": True,
        "payload": {
            "core_content": {"method": "A grounded method."},
            "claims": [_claim("parse-cache.yaml")],
        },
    }
    root = unit_root(project_root, "paper", record["id"])
    root.mkdir(parents=True, exist_ok=True)
    (root / "parse-cache.yaml").write_text("source with grounded words", encoding="utf-8")
    build_verification_receipt(record, root, verified_at="2026-07-18T00:00:00+00:00")
    return record


def test_r1_judgement_confirmation_requires_current_verification_and_user_message(tmp_path: Path) -> None:
    record = _verified_paper(tmp_path)
    verification = record["payload"].pop("verification")
    with pytest.raises(SystemExit, match="user_authorization"):
        apply_confirmation(record, confirmed_by="Human Reviewer", evidence=["decision-log.md"], project_root=tmp_path)
    with pytest.raises(SystemExit, match="missing payload.verification"):
        apply_confirmation(
            record,
            confirmed_by="Human Reviewer",
            evidence=["decision-log.md"],
            user_authorization="I confirm this analysis.",
            authorization_source="user_message",
            project_root=tmp_path,
        )

    record["payload"]["verification"] = verification
    with pytest.raises(SystemExit, match="authorization_source=user_message"):
        apply_confirmation(
            record,
            confirmed_by="Human Reviewer",
            evidence=["decision-log.md"],
            user_authorization="I confirm this analysis.",
            authorization_source="",
            project_root=tmp_path,
        )

    confirmed = apply_confirmation(
        record,
        confirmed_by="Human Reviewer",
        evidence=["decision-log.md"],
        user_authorization="I confirm this analysis.",
        authorization_source="user_message",
        project_root=tmp_path,
    )
    receipt = confirmed["confirmation"]
    assert receipt["claim_ids"] == ["claim-r1"]
    assert receipt["verified_at"] == "2026-07-18T00:00:00+00:00"
    assert receipt["user_authorization"] == "I confirm this analysis."
    assert receipt["authorization_source"] == "user_message"


def test_r1_artifact_byte_change_invalidates_confirmation(tmp_path: Path) -> None:
    record = _verified_paper(tmp_path)
    confirmed = apply_confirmation(
        record,
        confirmed_by="Human Reviewer",
        evidence=["decision-log.md"],
        user_authorization="Confirmed.",
        authorization_source="user_message",
        project_root=tmp_path,
    )
    artifact = unit_root(tmp_path, "paper", record["id"]) / "parse-cache.yaml"
    artifact.write_text("source with grounded words and changed bytes", encoding="utf-8")

    normalized = normalize_record_schema(confirmed, project_root=tmp_path)

    assert normalized["confirmation_status"] == "pending_user_confirmation"
    assert normalized["payload"]["verification"]["invalidation"]["reason"] == "verification_stale"


@pytest.mark.parametrize(
    "actor",
    ["Codex Agent", "OpenAI Codex", "assistant-1", "GPT-5.6", "Claude Code"],
)
def test_r1_compound_ai_actor_is_rejected(actor: str) -> None:
    assert is_ai_signer(actor) is True


def test_r1_common_human_name_is_not_rejected() -> None:
    assert is_ai_signer("Claude Martin") is False


def test_r1_orchestrator_status_is_byte_identical_read(tmp_path: Path, monkeypatch, capsys) -> None:
    orchestrate = _load_skill_script("research-orchestrator", "orchestrate.py")
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    program_id = "legacy-status"
    program = tmp_path / "kb" / "programs" / program_id
    workflow = program / "workflow"
    workflow.mkdir(parents=True)
    write_yaml_if_changed(program / "state.yaml", {"program_id": program_id, "stage": "review"})
    (workflow / "decision-log.md").write_text(
        "# Decision Log\n\n## 2026-07-01T00:00:00+00:00 · Legacy choice\n\n"
        "- Confirmation: `confirmed`\n",
        encoding="utf-8",
    )
    before = _tree_bytes(tmp_path / "kb")
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["orchestrate.py", "--root", str(tmp_path), "status", "--program-id", program_id],
    )

    assert orchestrate.main() == 0
    assert _tree_bytes(tmp_path / "kb") == before
    assert "'decisions': 1" in capsys.readouterr().out


def test_r1_program_mutation_abort_journals_extra_target(tmp_path: Path) -> None:
    orchestrate = _load_skill_script("research-orchestrator", "orchestrate.py")
    (tmp_path / "kb").mkdir()
    program_id = "fault-scope"
    query_path = orchestrate.program_root(tmp_path, program_id) / "queries" / "fault.md"

    with pytest.raises(RuntimeError, match="injected"):
        with orchestrate.program_mutation(tmp_path, program_id, "fault-test", query_path):
            orchestrate.ensure_program_files(tmp_path, program_id)
            query_path.parent.mkdir(parents=True, exist_ok=True)
            query_path.write_text("partial\n", encoding="utf-8")
            raise RuntimeError("injected")

    entries = [load_yaml(path) for path in (tmp_path / "kb" / ".journal").glob("*.yaml")]
    aborted = [entry for entry in entries if entry.get("op_type") == "research-orchestrator:fault-test"]
    assert len(aborted) == 1 and aborted[0]["state"] == "abort"
    assert query_path.relative_to(tmp_path / "kb").as_posix() in aborted[0]["target_paths"]
    assert orchestrate.decisions_path(tmp_path, program_id).relative_to(tmp_path / "kb").as_posix() in aborted[0]["target_paths"]
    assert not query_path.exists()
    assert not orchestrate.decisions_path(tmp_path, program_id).exists()


def test_r1_legacy_decision_migrates_pending_and_reports_unverified(tmp_path: Path) -> None:
    orchestrate = _load_skill_script("research-orchestrator", "orchestrate.py")
    report = _load_skill_script("report-author", "report.py")
    program_id = "legacy-decision"
    workflow = orchestrate.workflow_root(tmp_path, program_id)
    workflow.mkdir(parents=True)
    (workflow / "decision-log.md").write_text(
        "# Decision Log\n\n"
        "## 2026-07-01T00:00:00+00:00 · Use legacy baseline\n\n"
        "- Stage: `review`\n"
        "- Rationale: Old rationale.\n"
        "- Confirmation: `confirmed`\n",
        encoding="utf-8",
    )

    orchestrate.ensure_program_files(tmp_path, program_id)
    payload = load_yaml(orchestrate.decisions_path(tmp_path, program_id))
    item = payload["items"][0]
    assert item["confirmation_status"] == "pending_user_confirmation"
    assert item["legacy_import"]["original_confirmation_status"] == "confirmed"
    assert item["legacy_import"]["trust"] == "pending_unverified"
    assert orchestrate.refresh_state_counts(tmp_path, program_id, {})["counts"]["decisions"] == 1

    rendered = "\n".join(report.render_decisions(report.load_decisions(tmp_path, program_id)))
    assert "pending/unverified legacy decision" in rendered
    assert "- Confirmation: confirmed" not in rendered


def test_r1_write_record_default_cas_rejects_stale_second_writer(tmp_path: Path) -> None:
    record = default_record("paper", title="CAS", maturity="lightweight")
    path = write_record(tmp_path, record)
    first_reader, _ = locate_record(tmp_path, record["id"], kind="paper")
    stale_reader, _ = locate_record(tmp_path, record["id"], kind="paper")

    first_reader["summary"] = "first writer wins"
    write_record(tmp_path, first_reader)
    first_writer_bytes = path.read_bytes()
    stale_reader["summary"] = "stale overwrite"

    with pytest.raises(SystemExit, match="revision conflict"):
        write_record(tmp_path, stale_reader)
    assert path.read_bytes() == first_writer_bytes


def test_r1_program_decision_requires_two_stage_confirmation(tmp_path: Path, monkeypatch) -> None:
    orchestrate = _load_skill_script("research-orchestrator", "orchestrate.py")
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    program_id = "decision-gate"
    program = tmp_path / "kb" / "programs" / program_id
    workflow = program / "workflow"
    workflow.mkdir(parents=True)
    evidence_path = workflow / "decision-evidence.md"
    evidence_path.write_text("benchmark evidence supports the choice", encoding="utf-8")
    claims_path = workflow / "decision-claims.yaml"
    write_yaml_if_changed(
        claims_path,
        {
            "claims": [
                {
                    "id": "claim-program-choice",
                    "text": "Choose baseline A.",
                    "claim_type": "evaluation",
                    "confirmation_status": "pending_user_confirmation",
                    "evidence_refs": [
                        {
                            "source_unit_id": f"program:{program_id}",
                            "artifact": "workflow/decision-evidence.md",
                            "locator": "decision-evidence",
                            "quote": "benchmark evidence supports the choice",
                        }
                    ],
                }
            ]
        },
    )
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(orchestrate, "checkpoint_and_report", lambda *args, **kwargs: {})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "orchestrate.py", "--root", str(tmp_path), "log-decision", "--program-id", program_id,
            "--decision", "Choose baseline A", "--confirmation-status", "confirmed",
        ],
    )
    with pytest.raises(SystemExit, match="cannot be created confirmed"):
        orchestrate.main()

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "orchestrate.py", "--root", str(tmp_path), "log-decision", "--program-id", program_id,
            "--decision", "Choose baseline A", "--rationale", "Grounded benchmark choice.",
            "--claims-file", str(claims_path),
        ],
    )
    assert orchestrate.main() == 0
    decisions = load_yaml(orchestrate.decisions_path(tmp_path, program_id))["items"]
    assert len(decisions) == 1
    decision_id = decisions[0]["id"]
    assert decisions[0]["confirmation_status"] == "pending_user_confirmation"
    assert decisions[0]["payload"]["verification"]["artifacts"]

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "orchestrate.py", "--root", str(tmp_path), "confirm-decision", "--program-id", program_id,
            "--decision-id", decision_id, "--confirmed-by", "Human Reviewer", "--evidence",
            evidence_path.relative_to(tmp_path).as_posix(), "--user-authorization",
            "I confirm baseline A.", "--authorization-source", "user_message",
        ],
    )
    assert orchestrate.main() == 0
    confirmed = load_yaml(orchestrate.decisions_path(tmp_path, program_id))["items"][0]
    assert confirmed["confirmation_status"] == "confirmed"
    assert confirmed["information_types"] == ["inference", "evaluation", "unverified"]
    assert confirmed["confirmation"]["claim_ids"] == ["claim-program-choice"]
    assert confirmed["confirmation"]["user_authorization"] == "I confirm baseline A."


@pytest.mark.parametrize("skill", ["paper", "blog", "repo"])
def test_r1_analyzer_command_failure_rolls_back_record_and_artifacts(
    tmp_path: Path, monkeypatch, skill: str
) -> None:
    module = _load_skill_script(f"{skill}-analyst", f"{skill}.py")
    record = default_record(skill, title=f"{skill} rollback", maturity="lightweight")
    if skill == "repo":
        source_repo = tmp_path / "source-repo"
        source_repo.mkdir()
        (source_repo / "README.md").write_text("# repo\n", encoding="utf-8")
        record["source"]["original_uri"] = source_repo.as_posix()
    path = write_record(tmp_path, record)
    loaded, _ = locate_record(tmp_path, record["id"], kind=skill)
    before = path.read_bytes()
    checkpoint_calls: list[object] = []
    monkeypatch.setattr(module, "checkpoint_and_report", lambda *args, **kwargs: checkpoint_calls.append(kwargs))
    monkeypatch.setattr(module, "build_index", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("injected")))

    if skill == "paper":
        cache = path.parent / "parse-cache.yaml"
        write_yaml_if_changed(cache, {"paper_id": record["id"], "chunks": [{"label": "page-1", "text": "source"}]})
        args = SimpleNamespace(phase="prepare", mode="scaffold", input="", paper_id=record["id"])
        call = lambda: module._run_complete_note(args, tmp_path, loaded, path.parent, cache, [{"label": "page-1", "text": "source"}], {}, False)
        artifact = path.parent / "note-fill.yaml"
    elif skill == "blog":
        write_yaml_if_changed(path.parent / "parse-cache.yaml", {"blog_id": record["id"], "chunks": [{"label": "section:intro", "text": "source"}]})
        args = SimpleNamespace(phase="prepare", input="", blog_id=record["id"])
        call = lambda: module._run_complete_note(args, tmp_path, loaded, path.parent, False)
        artifact = path.parent / "blog-fill.yaml"
    else:
        args = SimpleNamespace(repo_id=record["id"])
        call = lambda: module._run_scan_structure(args, tmp_path, loaded, path.parent, False)
        artifact = path.parent / "structure-scan.yaml"

    with pytest.raises(RuntimeError, match="injected"):
        call()
    assert path.read_bytes() == before
    assert not artifact.exists()
    assert checkpoint_calls == []


def test_r1_paper_figure_tree_rolls_back_as_one_command_scope(
    tmp_path: Path, monkeypatch
) -> None:
    paper = _load_skill_script("paper-analyst", "paper.py")
    record = default_record("paper", title="figure rollback", maturity="lightweight")
    path = write_record(tmp_path, record)
    loaded, located_path = locate_record(tmp_path, record["id"], kind="paper")
    unit = located_path.parent
    figures = unit / "figures"
    figures.mkdir()
    old_asset = figures / "old.png"
    old_asset.write_bytes(b"old-asset")
    before_record = path.read_bytes()
    checkpoint_calls: list[object] = []

    def fake_extract(_root: Path, _record: dict, unit_root: Path):
        new_asset = unit_root / "figures" / "new.png"
        new_asset.parent.mkdir(parents=True, exist_ok=True)
        new_asset.write_bytes(b"partial-new-asset")
        return (
            [{"id": "figure-1", "kind": "figure", "path": new_asset.as_posix()}],
            [],
            {"mode": "test", "captions_detected": 1},
        )

    monkeypatch.setattr(paper, "_extract_pdf_images", fake_extract)
    monkeypatch.setattr(paper, "checkpoint_and_report", lambda *args, **kwargs: checkpoint_calls.append(kwargs))
    monkeypatch.setattr(
        paper,
        "build_index",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("injected")),
    )

    with pytest.raises(RuntimeError, match="injected"):
        paper._run_extract_figures(
            tmp_path,
            loaded,
            unit,
            [{"label": "page-1", "text": "Figure 1 shows the result."}],
            defer_post_actions=False,
        )

    assert path.read_bytes() == before_record
    assert old_asset.read_bytes() == b"old-asset"
    assert not (figures / "new.png").exists()
    assert not (unit / "figures.yaml").exists()
    assert checkpoint_calls == []


def test_r1_paper_parse_cache_force_never_overwrites_derived_evidence(tmp_path: Path) -> None:
    paper = _load_skill_script("paper-analyst", "paper.py")
    record = default_record("paper", title="immutable cache", maturity="lightweight")
    path = write_record(tmp_path, record)
    loaded, located_path = locate_record(tmp_path, record["id"], kind="paper")
    unit = located_path.parent
    cache = unit / "parse-cache.yaml"
    cache.write_bytes(b"immutable-cache-bytes\n")

    with pytest.raises(SystemExit, match="immutable derived evidence"):
        paper._load_or_refresh_cache(tmp_path, loaded, unit, force=True)

    assert cache.read_bytes() == b"immutable-cache-bytes\n"
    assert path.exists()


@pytest.mark.parametrize("skill", ["idea", "experiment"])
def test_r1_workbench_command_failure_rolls_back_before_checkpoint(
    tmp_path: Path, monkeypatch, skill: str
) -> None:
    module = _load_skill_script(f"{skill}-workbench", f"{skill}.py")
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    checkpoint_calls: list[object] = []
    if hasattr(module, "checkpoint_and_report"):
        monkeypatch.setattr(module, "checkpoint_and_report", lambda *args, **kwargs: checkpoint_calls.append(kwargs))
    monkeypatch.setattr(module, "build_index", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("injected")))
    if skill == "idea":
        title = "rollback idea"
        argv = ["idea.py", "--root", str(tmp_path), "capture", "--title", title]
        unit_id = module.build_unit_id("idea", title, "discussion")
    else:
        title = "rollback experiment"
        argv = ["experiment.py", "--root", str(tmp_path), "plan", "--title", title, "--program-id", "p-test"]
        unit_id = module.build_unit_id("experiment", title, "program:p-test")
    monkeypatch.setattr(module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(RuntimeError, match="injected"):
        module.main()
    assert not record_path(tmp_path, skill, unit_id).exists()
    assert checkpoint_calls == []


def test_r1_report_failure_restores_output_and_skips_checkpoint(tmp_path: Path, monkeypatch) -> None:
    report = _load_skill_script("report-author", "report.py")
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    program_id = "report-rollback"
    output = tmp_path / "kb" / "programs" / program_id / "reports" / "weekly.md"
    output.parent.mkdir(parents=True)
    output.write_text("before\n", encoding="utf-8")
    checkpoint_calls: list[object] = []
    original_write = report.write_text_if_changed

    def fail_after_write(path: Path, text: str) -> None:
        original_write(path, text)
        raise RuntimeError("injected")

    monkeypatch.setattr(report, "write_text_if_changed", fail_after_write)
    monkeypatch.setattr(report, "checkpoint_and_report", lambda *args, **kwargs: checkpoint_calls.append(kwargs))
    monkeypatch.setattr(report, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        ["report.py", "--root", str(tmp_path), "weekly", "--program-id", program_id],
    )
    with pytest.raises(RuntimeError, match="injected"):
        report.main()
    assert output.read_bytes() == b"before\n"
    assert checkpoint_calls == []


def test_r1_program_commit_failure_rolls_back_and_skips_checkpoint(tmp_path: Path, monkeypatch) -> None:
    orchestrate = _load_skill_script("research-orchestrator", "orchestrate.py")
    (tmp_path / ".agents").mkdir()
    (tmp_path / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    checkpoint_calls: list[object] = []

    def fail_commit(*_args, **_kwargs):
        raise RuntimeError("commit failure")

    monkeypatch.setattr(journal, "commit_op", fail_commit)
    monkeypatch.setattr(orchestrate, "checkpoint_and_report", lambda *args, **kwargs: checkpoint_calls.append(kwargs))
    monkeypatch.setattr(orchestrate, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "orchestrate.py", "--root", str(tmp_path), "init-program", "--program-id", "rollback-program",
            "--question", "Q", "--goal", "G",
        ],
    )
    with pytest.raises(RuntimeError, match="commit failure"):
        orchestrate.main()
    assert not orchestrate.state_path(tmp_path, "rollback-program").exists()
    assert checkpoint_calls == []
