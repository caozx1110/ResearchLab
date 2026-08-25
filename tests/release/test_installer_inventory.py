from __future__ import annotations

from pathlib import Path

from repo_paths import REPO_ROOT
from support import load_ws_sync, tree_snapshot


EXPECTED_SKILLS = {
    "research-analysis",
    "research-capture",
    "research-review",
    "research-vault",
    "research-workbench",
}
EXPECTED_RUNTIME = {
    "__init__.py",
    "legacy_detector.py",
    "updater.py",
    "v2_bootstrap.py",
}


def _sync_args(action: str, workspace: Path, *extra: str) -> list[str]:
    return [
        action,
        "--repo",
        str(REPO_ROOT),
        "--dir",
        str(workspace),
        "--agents",
        "codex",
        "--operation-time",
        "2026-08-25T00:00:00Z",
        *extra,
    ]


def test_installer_dry_run_is_zero_write_and_reports_a_plan(tmp_path: Path, capsys) -> None:
    sync = load_ws_sync()
    before = tree_snapshot(tmp_path)

    assert sync.main(_sync_args("install", tmp_path, "--dry-run", "--plan-jsonl")) == 0

    output = capsys.readouterr().out
    assert '"operation": "write-manifest"' in output
    assert tree_snapshot(tmp_path) == before


def test_clean_copy_contains_only_five_skills_and_four_runtime_files(tmp_path: Path) -> None:
    sync = load_ws_sync()
    assert sync.main(_sync_args("install", tmp_path)) == 0

    skill_root = tmp_path / ".agents" / "skills"
    runtime_root = tmp_path / ".agents" / "lib" / "research"
    assert {path.name for path in skill_root.iterdir() if path.is_dir()} == EXPECTED_SKILLS
    assert (skill_root / "metadata.yaml").is_file()
    assert {path.name for path in runtime_root.iterdir() if path.is_file()} == EXPECTED_RUNTIME
    assert not (runtime_root / "skill_validator.py").exists()
    assert not (runtime_root / "SCHEMAS.md").exists()

    manifest = (tmp_path / ".agents" / ".install-manifest.json").read_text(encoding="utf-8")
    assert ".agents/lib/research/v2_bootstrap.py" in manifest
    assert "runtime/lib/research/common.py" not in manifest
