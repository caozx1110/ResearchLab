from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.core import default_record, record_path, write_record
from research.paths import config_root, runtime_preferences_path
from research.preference_selection import eligible_preferences, record_effective_selection
from research.prefs import default_runtime_preferences, ensure_workspace


def _project_root() -> Path:
    return REPO_ROOT


def _load_intake_module():
    root = _project_root()
    script = root / "skills" / "source-intake" / "scripts" / "intake.py"
    spec = importlib.util.spec_from_file_location("source_intake_script_for_commands", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _record_intake_selection(
    root: Path,
    intake,
    args: argparse.Namespace,
    *,
    source: str,
    title: str,
    canonical_pools: list[str],
    selection_id: str,
) -> Path:
    eligible = eligible_preferences(root, skill="source-intake", operation="add")
    selected = []
    excluded = []
    for item in eligible["items"]:
        row = {
            "preference_id": item["preference_id"],
            "reason": "bounded intake preference",
        }
        if item["strength"] == "hard":
            selected.append({**row, "application": "enforce during this intake only"})
        else:
            excluded.append({**row, "reason": "not relevant to this intake"})
    path, _receipt = record_effective_selection(
        root,
        {
            "selection_id": selection_id,
            "skill": "source-intake",
            "operation": "add",
            "catalog_digest": eligible["catalog_digest"],
            "task_context": intake.intake_preference_context(
                args,
                source=source,
                title=title,
                canonical_pools=canonical_pools,
            ),
            "selected": selected,
            "excluded": excluded,
        },
    )
    return path


def _workspace_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _prepared_args(root: Path, kind: str, source: Path) -> argparse.Namespace:
    return argparse.Namespace(
        command="prepare-add",
        kind=kind,
        source=str(source),
        maturity="lightweight",
        title=f"{kind.title()} Source",
        stage_id="",
        candidate_id="",
        pool=[],
        user_authorization="",
        authorization_source="",
    )


def _record_context_selection(
    root: Path,
    *,
    selection_id: str,
    context: dict[str, object],
) -> Path:
    eligible = eligible_preferences(root, skill="source-intake", operation="add")
    selected = []
    excluded = []
    for item in eligible["items"]:
        row = {"preference_id": item["preference_id"], "reason": "bounded intake test"}
        if item["strength"] == "hard":
            selected.append({**row, "application": "enforce this intake boundary"})
        else:
            excluded.append(row)
    path, _receipt = record_effective_selection(
        root,
        {
            "selection_id": selection_id,
            "skill": "source-intake",
            "operation": "add",
            "catalog_digest": eligible["catalog_digest"],
            "task_context": context,
            "selected": selected,
            "excluded": excluded,
        },
    )
    return path


def _add_argv(
    root: Path,
    args: argparse.Namespace,
    *,
    token: str = "",
    selection_id: str = "",
) -> list[str]:
    argv = [
        "intake.py",
        "--root",
        str(root),
        "add",
        "--kind",
        args.kind,
        "--source",
        args.source,
        "--maturity",
        args.maturity,
        "--title",
        args.title,
    ]
    if args.user_authorization:
        argv.extend(["--user-authorization", args.user_authorization])
    if args.authorization_source:
        argv.extend(["--authorization-source", args.authorization_source])
    if token:
        argv.extend(["--prepared-intake-token", token])
    if selection_id:
        argv.extend(["--preference-selection-id", selection_id])
    return argv


def test_intake_confirm_command_contains_created_record_id() -> None:
    intake = _load_intake_module()

    command = intake.confirm_command({"kind": "repo", "id": "r-openvla-12345678"})

    assert ".agents/skills/unit-analyst/scripts/repo.py confirm --repo-id r-openvla-12345678" in command
    assert "<id>" not in command
    assert "${RESEARCH_CONFIRM_EVIDENCE:?set-human-evidence}" in command


def test_intake_confirm_command_uses_shared_helper_with_runtime_python() -> None:
    intake = _load_intake_module()
    record = {"kind": "repo", "id": "r-openvla-12345678"}

    assert intake.confirm_command(record) == (
        f"{intake.research_python()} .agents/skills/unit-analyst/scripts/repo.py confirm "
        "--repo-id r-openvla-12345678 --confirmed-by "
        "${RESEARCH_CONFIRMED_BY:?set-human-identity} --evidence "
        "${RESEARCH_CONFIRM_EVIDENCE:?set-human-evidence}"
    )


def test_intake_user_guidance_hides_internal_config_commands() -> None:
    intake = _load_intake_module()

    hints = intake.guidance_hints(
        "paper",
        {
            "prompt_for_preference_updates": True,
            "auto_complete_note": False,
            "complete_note_mode": "scaffold",
            "auto_extract_figures_after_note": False,
        },
        has_pdf=True,
        note_created=True,
    )

    rendered = "\n".join(hints)
    assert "kb next" in rendered
    for leaked_fragment in ("python3", "config.py", ".py ", "--section", "${"):
        assert leaked_fragment not in rendered


@pytest.mark.parametrize(
    ("field", "mutate"),
    [
        ("kind", lambda args, values: setattr(args, "kind", "repo")),
        ("source", lambda _args, values: values.update(source="https://example.test/b")),
        ("title", lambda _args, values: values.update(title="Paper B")),
        ("maturity", lambda args, values: setattr(args, "maturity", "complete")),
        ("stage_id", lambda args, values: setattr(args, "stage_id", "source-search-b")),
        ("candidate_id", lambda args, values: setattr(args, "candidate_id", "candidate-b")),
        ("canonical_pools", lambda _args, values: values.update(canonical_pools=["baseline"])),
        ("user_authorization", lambda args, values: setattr(args, "user_authorization", "Keep candidate B.")),
        ("authorization_source", lambda args, values: setattr(args, "authorization_source", "other")),
    ],
)
def test_intake_preference_context_binds_every_consumed_scope_field(field, mutate) -> None:
    intake = _load_intake_module()
    args = argparse.Namespace(
        kind="paper",
        maturity="lightweight",
        stage_id="source-search-a",
        candidate_id="candidate-a",
        user_authorization="Keep candidate A.",
        authorization_source="user_message",
    )
    values = {
        "source": "https://example.test/a",
        "title": "Paper A",
        "canonical_pools": ["shortlist"],
    }
    before = intake.intake_preference_context(args, **values)
    mutate(args, values)
    after = intake.intake_preference_context(args, **values)

    assert after != before, field
    assert "user_authorization" not in after
    assert "authorization_source" not in after


@pytest.mark.parametrize(
    ("mutation", "canonical_pools"),
    [
        ("authorization", ["shortlist"]),
        ("pools", ["baseline"]),
    ],
)
def test_intake_old_preference_receipt_rejects_scope_replay_without_unit_write(
    tmp_path: Path,
    mutation: str,
    canonical_pools: list[str],
) -> None:
    intake = _load_intake_module()
    ensure_workspace(tmp_path)
    args = argparse.Namespace(
        kind="paper",
        maturity="lightweight",
        stage_id="source-search-a",
        candidate_id="candidate-a",
        user_authorization="Keep candidate A.",
        authorization_source="user_message",
        preference_selection_id="prefsel-intake-replay",
    )
    source = "https://example.test/private-source"
    receipt_path = _record_intake_selection(
        tmp_path,
        intake,
        args,
        source=source,
        title="Paper A",
        canonical_pools=["shortlist"],
        selection_id=args.preference_selection_id,
    )
    if mutation == "authorization":
        args.user_authorization = "Keep candidate B."
    units_root = tmp_path / "kb/units"
    before_units = {
        path.relative_to(units_root): path.read_bytes()
        for path in units_root.rglob("*")
        if path.is_file()
    }

    with pytest.raises(ValueError, match="another task"):
        intake.resolve_intake_preferences(
            tmp_path,
            args,
            source=source,
            title="Paper A",
            canonical_pools=canonical_pools,
        )

    assert {
        path.relative_to(units_root): path.read_bytes()
        for path in units_root.rglob("*")
        if path.is_file()
    } == before_units == {}
    persisted = receipt_path.read_text(encoding="utf-8")
    assert "Keep candidate A." not in persisted
    assert source not in persisted


def test_kb_ingest_chain_owns_paper_analyzer_order(monkeypatch) -> None:
    intake = _load_intake_module()

    monkeypatch.delenv("RESEARCH_INGEST_CHAIN", raising=False)
    assert intake.ingest_chain_active() is False

    monkeypatch.setenv("RESEARCH_INGEST_CHAIN", "1")
    assert intake.ingest_chain_active() is True


@pytest.mark.parametrize("kind", ["repo", "dataset", "blog", "paper"])
@pytest.mark.parametrize("receipt_fault", ["wrong-skill", "wrong-operation", "wrong-task"])
def test_all_intake_kinds_reject_wrong_receipts_without_workspace_writes(
    tmp_path: Path,
    monkeypatch,
    kind: str,
    receipt_fault: str,
) -> None:
    intake = _load_intake_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    write_yaml_if_changed(
        config_root(root) / "user-profile.yaml",
        {"constraints": ["no cloud upload"]},
    )
    if kind == "repo":
        source = root / "repo-source"
        source.mkdir()
        (source / "README.md").write_text("# Repo\n\nCode snapshot.\n", encoding="utf-8")
    else:
        source = root / f"{kind}-source.md"
        source.write_text(f"# {kind.title()}\n\nArchived evidence.\n", encoding="utf-8")
    args = _prepared_args(root, kind, source)
    prepared = intake._prepare_intake_snapshot(root, args)
    token = str(prepared["token"])
    context = dict(prepared["canonical_inputs"])
    if receipt_fault == "wrong-task":
        context["title"] = "A different prepared title"
    selection_id = f"prefsel-{kind}-{receipt_fault}"
    receipt_path = _record_context_selection(
        root,
        selection_id=selection_id,
        context=context,
    )
    if receipt_fault in {"wrong-skill", "wrong-operation"}:
        receipt = load_yaml(receipt_path)
        if receipt_fault == "wrong-skill":
            receipt["skill"] = "report-author"
        else:
            receipt["operation"] = "search"
        write_yaml_if_changed(receipt_path, receipt)
    before = _workspace_snapshot(root)
    monkeypatch.setattr(
        sys,
        "argv",
        _add_argv(root, args, token=token, selection_id=selection_id),
    )

    with pytest.raises((ValueError, SystemExit)):
        intake.main()

    assert _workspace_snapshot(root) == before
    assert not intake._prepared_dir(root, token).exists()
    assert not list((root / "kb").glob(".runtime/intake-staging/**/*"))


def test_no_receipt_uses_only_hard_fallback_and_persists_value_free_digests(
    tmp_path: Path,
    monkeypatch,
) -> None:
    intake = _load_intake_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    hard_text = "never upload private source material"
    write_yaml_if_changed(
        config_root(root) / "user-profile.yaml",
        {"constraints": [hard_text]},
    )
    write_yaml_if_changed(runtime_preferences_path(root), default_runtime_preferences())
    source = root / "paper.md"
    source.write_text("# Paper\n\nEvidence.\n", encoding="utf-8")
    args = _prepared_args(root, "paper", source)
    monkeypatch.setattr(intake, "checkpoint_and_report", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(sys, "argv", _add_argv(root, args))

    assert intake.main() == 0

    records = list((root / "kb/units/papers").glob("*/record.yaml"))
    assert len(records) == 1
    record = load_yaml(records[0])
    state = record["payload"]["preference_context"]
    assert state["selection_binding"] == {}
    assert set(state["hard_value_digests"]) == {"profile.constraints"}
    assert len(state["hard_value_digests"]["profile.constraints"]) == 64
    serialized = records[0].read_text(encoding="utf-8")
    assert hard_text not in serialized
    assert "auto_screen_on_intake" not in serialized
    basic = record["payload"]["basic_info"]
    assert basic["citation_key"] == intake.citation_key_for_unit_id(record["id"])
    assert basic["bibtex"]["entry_type"] == "misc"
    # Source intake is mechanical only; neither hard fallback nor a soft
    # preference may resurrect the retired quick-screen analyzer.


def test_archived_and_staged_paper_citation_metadata_merge_without_network() -> None:
    intake = _load_intake_module()
    merged = intake._merge_paper_citation_metadata(
        source="https://arxiv.org/abs/2603.12263v1",
        local_metadata={},
        parse_metadata={
            "title": "Archived Citation Metadata",
            "authors": ["Ada Example", "Bo Researcher"],
            "abstract": "Archived abstract.",
            "doi": "doi:10.1234/EXAMPLE",
            "venue": "Robotics Test Conference",
            "bibtex": {
                "entry_type": "inproceedings",
                "venue_field": "booktitle",
                "pages": "10--20",
            },
        },
        staged_candidate={
            "identities": {
                "doi": "https://doi.org/10.1234/example",
                "arxiv_id": "2603.12263",
            },
            "metadata": {"publication_year": 2026},
        },
    )

    assert merged["doi"] == "10.1234/example"
    assert merged["arxiv_id"] == "2603.12263"
    assert merged["authors"] == ["Ada Example", "Bo Researcher"]
    assert merged["year"] == 2026
    assert merged["bibtex"]["entry_type"] == "inproceedings"
    assert merged["bibtex"]["venue_field"] == "booktitle"


def test_conflicting_archived_and_staged_strong_citation_identity_fails_closed() -> None:
    intake = _load_intake_module()
    with pytest.raises(RuntimeError, match="conflicting DOI"):
        intake._merge_paper_citation_metadata(
            source="https://example.test/paper",
            local_metadata={"doi": "10.1234/one"},
            parse_metadata={},
            staged_candidate={"identities": {"doi": "10.1234/two"}},
        )


@pytest.mark.parametrize("mutation", ["input", "authorization", "source-bytes"])
def test_prepared_intake_mutation_rejects_old_receipt_before_promotion(
    tmp_path: Path,
    monkeypatch,
    mutation: str,
) -> None:
    intake = _load_intake_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    source = root / "blog.md"
    source.write_text("# Blog\n\nOriginal bytes.\n", encoding="utf-8")
    args = _prepared_args(root, "blog", source)
    args.user_authorization = "Archive the original snapshot."
    args.authorization_source = "user_message"
    prepared = intake._prepare_intake_snapshot(root, args)
    token = str(prepared["token"])
    selection_id = f"prefsel-mutation-{mutation}"
    _record_context_selection(
        root,
        selection_id=selection_id,
        context=dict(prepared["canonical_inputs"]),
    )
    if mutation == "input":
        args.maturity = "complete"
    elif mutation == "authorization":
        args.user_authorization = "Archive a different snapshot."
    else:
        source.write_text("# Blog\n\nChanged bytes.\n", encoding="utf-8")
    before = _workspace_snapshot(root)
    monkeypatch.setattr(
        sys,
        "argv",
        _add_argv(root, args, token=token, selection_id=selection_id),
    )

    with pytest.raises(SystemExit, match="changed after preparation"):
        intake.main()

    assert _workspace_snapshot(root) == before
    assert not intake._prepared_dir(root, token).exists()
    assert not list((root / "kb/units/blogs").glob("*/record.yaml"))


def test_ordinary_success_and_duplicate_keep_one_canonical_unit_and_cleanup(
    tmp_path: Path,
    monkeypatch,
) -> None:
    intake = _load_intake_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    source = root / "blog.md"
    source.write_text("# Blog\n\nStable duplicate bytes.\n", encoding="utf-8")
    args = _prepared_args(root, "blog", source)
    monkeypatch.setattr(intake, "checkpoint_and_report", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(sys, "argv", _add_argv(root, args))

    assert intake.main() == 0
    records = list((root / "kb/units/blogs").glob("*/record.yaml"))
    assert len(records) == 1
    record = load_yaml(records[0])
    assert record["source"]["file_hash"]
    assert record["source"]["backup_paths"]
    before_duplicate = _workspace_snapshot(root)
    monkeypatch.setattr(sys, "argv", _add_argv(root, args))

    assert intake.main() == 0

    assert len(list((root / "kb/units/blogs").glob("*/record.yaml"))) == 1
    assert _workspace_snapshot(root) == before_duplicate
    assert not list(root.parent.glob(f".research-intake-{intake._prepared_scope(root)}-*"))


def test_complete_local_paper_revision_archives_degraded_unconfirmed_unit_without_overwrite(
    tmp_path: Path,
    monkeypatch,
) -> None:
    intake = _load_intake_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    title = "Ordered Action Tokens for Robot Learning"
    old = default_record(
        "paper",
        title=title,
        maturity="lightweight",
        source={"original_uri": "https://arxiv.org/abs/2607.21670"},
    )
    old["id"] = "p-2607-21670-degraded"
    old["status"] = "active"
    old["confirmation_status"] = "pending_user_confirmation"
    old_source = record_path(root, "paper", old["id"]).parent / "source"
    old_source.mkdir(parents=True)
    old_document = old_source / "document.md"
    old_document.write_text("# Abstract only\n\nShort degraded abstract.\n", encoding="utf-8")
    old_original = old_source / "abstract.html"
    old_original.write_text("<html><body>Short degraded abstract.</body></html>\n", encoding="utf-8")
    old["source"].update(
        {
            "backup_kind": "file",
            "backup_paths": [old_original.relative_to(root).as_posix()],
            "file_hash": intake.hashlib.sha256(old_original.read_bytes()).hexdigest(),
            "backup_status": "degraded",
            "source_type": "arxiv-html",
            "markdown_path": old_document.relative_to(root).as_posix(),
            "materialization": {"status": "degraded"},
        }
    )
    old_path = write_record(root, old)
    old_record_bytes = old_path.read_bytes()
    old_source_bytes = {path.name: path.read_bytes() for path in old_source.iterdir()}

    fitz = pytest.importorskip("fitz")
    replacement = root / "ordered-action-tokens.pdf"
    document = fitz.open()
    document.set_metadata({"title": title, "author": "Cold fixture"})
    for heading in ("Method", "Experiments"):
        page = document.new_page()
        page.insert_textbox(
            fitz.Rect(72, 72, 520, 760),
            heading
            + "\n\n"
            + (
                "Complete grounded evidence explains robot policy learning, observations, "
                "action tokens, evaluation methods, controlled baselines, reproducible "
                "measurements, limitations, and analysis. "
                * 18
            ),
            fontsize=11,
        )
    document.save(replacement)
    document.close()
    args = argparse.Namespace(
        command="prepare-add",
        kind="paper",
        source=str(replacement),
        maturity="lightweight",
        title=title,
        stage_id="",
        candidate_id="",
        pool=[],
        user_authorization="",
        authorization_source="",
    )
    monkeypatch.setattr(intake, "checkpoint_and_report", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(sys, "argv", _add_argv(root, args))

    assert intake.main() == 0

    records = [load_yaml(path) for path in (root / "kb/units/papers").glob("*/record.yaml")]
    assert len(records) == 2
    archived = next(record for record in records if record["id"] == old["id"])
    current = next(record for record in records if record["id"] != old["id"])
    assert archived["status"] == "archived"
    assert current["status"] == "active"
    assert current["source"]["materialization"]["status"] == "complete"
    assert any(link["target_id"] == current["id"] and link["relation"] == "superseded_by" for link in archived["links"])
    assert any(link["target_id"] == archived["id"] and link["relation"] == "supersedes" for link in current["links"])
    assert old_path.read_bytes() != old_record_bytes
    assert {path.name: path.read_bytes() for path in old_source.iterdir()} == old_source_bytes
    assert intake.detect_duplicate(root, "paper", str(replacement), title=title)["id"] == current["id"]


def test_degraded_pdf_with_substantive_page_parse_is_safe_source_revision_material() -> None:
    intake = _load_intake_module()
    source_info = {
        "backup_status": "degraded",
        "source_type": "pdf",
        "locator_kind": "page",
        "file_hash": "a" * 64,
        "markdown_hash": "b" * 64,
        "backup_warning": (
            "PDF page 3 had low converted-text coverage; used native PDF text recovery "
            "Markdown contains 8 malformed pipe table(s)"
        ),
        "materialization": {
            "status": "degraded",
            "source_map_path": "kb/units/papers/p-new/source/source-map.yaml",
            "conversion_path": "kb/units/papers/p-new/source/conversion.yaml",
        },
        "parse_chunks": [
            {"page": 1, "text": "a" * 2_000},
            {"page": 2, "text": "b" * 2_000},
        ],
    }

    assert intake._source_upgrade_is_complete(source_info)
    assert source_info["backup_status"] == "degraded"
    assert source_info["materialization"]["status"] == "degraded"

    source_info["parse_chunks"] = [{"page": 1, "text": "a" * 8_000}]
    assert not intake._source_upgrade_is_complete(source_info)
    source_info["parse_chunks"] = [
        {"page": 1, "text": "a" * 1_900},
        {"page": 2, "text": "b" * 1_900},
    ]
    assert not intake._source_upgrade_is_complete(source_info)


def test_verified_degraded_paper_requires_decision_before_source_revision(
    tmp_path: Path,
    monkeypatch,
) -> None:
    intake = _load_intake_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    title = "Protected Degraded Paper"
    old = default_record(
        "paper",
        title=title,
        maturity="lightweight",
        source={"original_uri": "https://arxiv.org/abs/2607.99999"},
    )
    old["id"] = "p-protected-degraded"
    old["status"] = "active"
    old["confirmation_status"] = "pending_user_confirmation"
    old["payload"]["verification"] = {"verified_at": "2026-07-27T00:00:00Z"}
    old_source = record_path(root, "paper", old["id"]).parent / "source"
    old_source.mkdir(parents=True)
    original = old_source / "abstract.html"
    original.write_text("degraded abstract", encoding="utf-8")
    old["source"].update(
        {
            "backup_kind": "file",
            "backup_paths": [original.relative_to(root).as_posix()],
            "file_hash": intake.hashlib.sha256(original.read_bytes()).hexdigest(),
            "backup_status": "degraded",
            "source_type": "arxiv-html",
            "materialization": {"status": "degraded"},
        }
    )
    old_path = write_record(root, old)
    before = _workspace_snapshot(root)
    replacement = root / "2607.99999.html"
    replacement.write_text("<html><body><article>complete replacement</article></body></html>", encoding="utf-8")
    args = argparse.Namespace(
        command="prepare-add",
        kind="paper",
        source=str(replacement),
        maturity="lightweight",
        title=title,
        stage_id="",
        candidate_id="",
        pool=[],
        user_authorization="",
        authorization_source="",
    )

    with pytest.raises(RuntimeError, match="explicit user migration approval"):
        intake._prepare_intake_snapshot(root, args)

    assert _workspace_snapshot(root) == {**before, replacement.relative_to(root).as_posix(): replacement.read_bytes()}
    assert load_yaml(old_path)["status"] == "active"


def test_external_stage_is_cleaned_when_post_validation_execution_raises(
    tmp_path: Path,
    monkeypatch,
) -> None:
    intake = _load_intake_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    source = root / "dataset.md"
    source.write_text("# Dataset\n\nSchema.\n", encoding="utf-8")
    args = _prepared_args(root, "dataset", source)
    prepared = intake._prepare_intake_snapshot(root, args)
    token = str(prepared["token"])
    before = _workspace_snapshot(root)
    monkeypatch.setattr(
        intake,
        "_execute_intake_transaction",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("injected failure")),
    )
    monkeypatch.setattr(sys, "argv", _add_argv(root, args, token=token))

    with pytest.raises(RuntimeError, match="injected failure"):
        intake.main()

    assert _workspace_snapshot(root) == before
    assert not intake._prepared_dir(root, token).exists()


def test_prepared_token_concurrent_consumer_fails_closed_without_deleting_owner_stage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    intake = _load_intake_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    source = root / "blog.md"
    source.write_text("# Blog\n\nConcurrent snapshot.\n", encoding="utf-8")
    args = _prepared_args(root, "blog", source)
    prepared = intake._prepare_intake_snapshot(root, args)
    token = str(prepared["token"])
    intake._claim_prepared_intake(root, token)
    monkeypatch.setattr(sys, "argv", _add_argv(root, args, token=token))

    with pytest.raises(SystemExit, match="already being consumed"):
        intake.main()

    assert intake._prepared_dir(root, token).is_dir()
    intake._safe_remove_prepared(root, token)


@pytest.mark.parametrize(
    ("expected_stage", "fault_target"),
    [
        ("source-recognition", "resolve"),
        ("prepare-freeze", "backup"),
        ("materialization", "materialize"),
        ("canonical-transaction", "index"),
        ("checkpoint", "checkpoint"),
    ],
)
def test_safe_fixture_failure_matrix_reports_stable_intake_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    expected_stage: str,
    fault_target: str,
) -> None:
    intake = _load_intake_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
    source = root / "safe-fixture.md"
    source.write_text("# Safe fixture\n\nSynthetic public test bytes.\n", encoding="utf-8")
    args = _prepared_args(root, "blog", source)
    published: list[dict[str, object]] = []
    monkeypatch.setattr(
        intake,
        "publish_runtime_failure_stage",
        lambda _root, **payload: published.append(payload) or True,
    )

    token = ""
    if fault_target == "resolve":
        monkeypatch.setattr(
            intake,
            "_resolve_intake_request",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("injected source recognition failure")
            ),
        )
    elif fault_target == "backup":
        monkeypatch.setattr(
            intake,
            "backup_source",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(
                RuntimeError("injected prepare failure")
            ),
        )
    else:
        prepared = intake._prepare_intake_snapshot(root, args)
        token = str(prepared["token"])
        if fault_target == "materialize":
            monkeypatch.setattr(
                intake,
                "_materialize_staged_source",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("injected materialization failure")
                ),
            )
        elif fault_target == "index":
            monkeypatch.setattr(
                intake,
                "_build_index_transaction",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("injected canonical transaction failure")
                ),
            )
        else:
            monkeypatch.setattr(
                intake,
                "checkpoint_and_report",
                lambda *_args, **_kwargs: (_ for _ in ()).throw(
                    RuntimeError("injected checkpoint failure")
                ),
            )

    monkeypatch.setattr(sys, "argv", _add_argv(root, args, token=token))
    with pytest.raises((RuntimeError, SystemExit), match="injected"):
        intake.main()

    assert published == [
        {
            "skill": "source-intake",
            "operation": "add",
            "failure_stage": expected_stage,
        }
    ]
    records = list((root / "kb" / "units" / "blogs").glob("*/record.yaml"))
    if expected_stage == "checkpoint":
        # A post-commit checkpoint failure must be distinguishable because
        # retrying it as a failed canonical transaction would be unsafe.
        assert len(records) == 1
    else:
        assert records == []
    if token:
        assert not intake._prepared_dir(root, token).exists()
