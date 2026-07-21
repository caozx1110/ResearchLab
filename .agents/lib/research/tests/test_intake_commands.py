from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


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


def test_kb_ingest_chain_owns_paper_analyzer_order(monkeypatch) -> None:
    intake = _load_intake_module()

    monkeypatch.delenv("RESEARCH_INGEST_CHAIN", raising=False)
    assert intake.ingest_chain_active() is False

    monkeypatch.setenv("RESEARCH_INGEST_CHAIN", "1")
    assert intake.ingest_chain_active() is True
