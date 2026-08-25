from __future__ import annotations

import os
from pathlib import Path

import pytest

from repo_paths import REPO_ROOT
from support import load_runtime_module, load_ws_sync, tree_snapshot


@pytest.mark.parametrize(
    "marker",
    ("kb", "record.yaml", "config/workspace-layout.yaml", "obsidian/managed"),
)
def test_legacy_markers_fail_closed_and_remain_untouched(tmp_path: Path, marker: str) -> None:
    detector = load_runtime_module("legacy_detector")
    sync = load_ws_sync()
    marker_path = tmp_path / marker
    if marker_path.suffix or marker_path.name == "record.yaml":
        marker_path.parent.mkdir(parents=True, exist_ok=True)
        marker_path.write_bytes(b"legacy sentinel\n")
    else:
        marker_path.mkdir(parents=True)
        (marker_path / "sentinel").write_bytes(b"legacy sentinel\n")
    before = tree_snapshot(tmp_path)

    detection = detector.detect_legacy_layout(tmp_path)
    result = sync.main(
        [
            "install",
            "--repo",
            str(REPO_ROOT),
            "--dir",
            str(tmp_path),
            "--agents",
            "codex",
        ]
    )

    assert detection.state is detector.LegacyLayoutState.LEGACY
    assert detection.marker == marker
    assert result != 0
    assert tree_snapshot(tmp_path) == before


def test_workspace_rules_pointer_and_installed_rules_are_stable(tmp_path: Path) -> None:
    sync = load_ws_sync()
    runtime_agents = (REPO_ROOT / "runtime" / "AGENTS.md").read_text(encoding="utf-8")
    expected_rules = (REPO_ROOT / "runtime" / "WORKSPACE_RULES.md").read_bytes()

    assert runtime_agents.strip() == (
        "Before any Research Vault operation, load `.agents/WORKSPACE_RULES.md`. "
        "If it is missing or unreadable, do not write to the workspace; explain that "
        "the installation must be repaired."
    )
    assert sync.main(
        [
            "install",
            "--repo",
            str(REPO_ROOT),
            "--dir",
            str(tmp_path),
            "--agents",
            "codex",
        ]
    ) == 0
    assert (tmp_path / ".agents" / "WORKSPACE_RULES.md").read_bytes() == expected_rules
    assert ".agents/WORKSPACE_RULES.md" in (tmp_path / "AGENTS.md").read_text(encoding="utf-8")


def test_bootstrap_accepts_a_ready_core_runtime_without_provisioning(monkeypatch, tmp_path: Path) -> None:
    bootstrap = load_runtime_module("v2_bootstrap")
    monkeypatch.delenv(bootstrap.READY_FLAG, raising=False)
    monkeypatch.setattr(bootstrap, "_has_core_runtime", lambda: True)

    bootstrap.ensure_managed_runtime(tmp_path)

    assert os.environ[bootstrap.READY_FLAG] == "1"


def test_updater_keeps_minimal_version_and_semver_contract(tmp_path: Path) -> None:
    updater = load_runtime_module("updater")
    version = tmp_path / ".agents" / "VERSION"
    version.parent.mkdir(parents=True)
    version.write_text("0.2.0-rc.8\n", encoding="utf-8")

    assert updater.read_local_version(tmp_path) == "0.2.0-rc.8"
    assert updater.compare_versions("0.2.0-rc.8", "0.2.0") < 0
    assert updater.compare_versions("0.2.0", "0.2.0") == 0
    assert updater.compare_versions("0.3.0", "0.2.9") > 0
