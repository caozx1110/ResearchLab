from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path

import pytest

from research.preference_selection import eligible_preferences, record_effective_selection
from research.prefs import ensure_workspace


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_intake_module():
    root = _project_root()
    script = root / ".agents" / "skills" / "source-intake" / "scripts" / "intake.py"
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


def test_intake_confirm_command_contains_created_record_id() -> None:
    intake = _load_intake_module()

    command = intake.confirm_command({"kind": "repo", "id": "r-openvla-12345678"})

    assert ".agents/skills/repo-analyst/scripts/repo.py confirm --repo-id r-openvla-12345678" in command
    assert "<id>" not in command
    assert "${RESEARCH_CONFIRM_EVIDENCE:?set-human-evidence}" in command


def test_intake_confirm_command_uses_shared_helper_with_runtime_python() -> None:
    intake = _load_intake_module()
    record = {"kind": "repo", "id": "r-openvla-12345678"}

    assert intake.confirm_command(record) == (
        f"{intake.research_python()} .agents/skills/repo-analyst/scripts/repo.py confirm "
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
