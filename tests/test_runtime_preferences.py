from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from repo_paths import REPO_ROOT

from research.common import load_yaml, write_yaml_if_changed
from research.core import ensure_workspace, load_runtime_preferences, write_runtime_preferences
from research.paths import runtime_preferences_path
from research.prefs import effective_review_policy


def _project_root() -> Path:
    return REPO_ROOT


def test_pdf_figure_extraction_mode_surfaces_in_runtime_preferences_and_config_guide(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    preferences = load_runtime_preferences(root)

    assert preferences["pdf"]["figure_extraction_mode"] == "caption-region"

    script = _project_root() / "skills" / "research-config-manager" / "scripts" / "config.py"
    result = subprocess.run(
        [sys.executable, str(script), "--root", str(root), "guide", "--focus", "paper-intake"],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(_project_root() / "runtime" / "lib")},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "- PDF Figure 模式: caption-region" in result.stdout
    assert "- PDF Figure 模式: None" not in result.stdout
    assert "快速筛选" not in result.stdout
    assert "完整笔记触发条件" not in result.stdout


def test_new_workspace_is_explicit_personal_but_pre_profile_workspace_stays_strict(tmp_path: Path) -> None:
    new_root = tmp_path / "new"
    ensure_workspace(new_root)
    stored = load_yaml(runtime_preferences_path(new_root))
    assert stored["governance_profile"] == "personal"
    assert stored["autonomy"]["auto_execute_scope"] == ["ingest", "build-index", "refresh", "generate-note"]
    assert load_runtime_preferences(new_root)["governance_profile"] == "personal"

    legacy_root = tmp_path / "legacy"
    path = runtime_preferences_path(legacy_root)
    write_yaml_if_changed(path, {"identity": {"default_confirmed_by": "Human"}})
    assert load_runtime_preferences(legacy_root)["governance_profile"] == "strict"

    write_yaml_if_changed(path, {"governance_profile": "unexpected"})
    assert load_runtime_preferences(legacy_root)["governance_profile"] == "strict"

    write_yaml_if_changed(path, {})
    assert load_runtime_preferences(legacy_root)["governance_profile"] == "strict"


def test_retired_screening_preferences_are_not_loaded_or_rewritten(tmp_path: Path) -> None:
    root = tmp_path / "legacy"
    write_yaml_if_changed(
        runtime_preferences_path(root),
        {
            "governance_profile": "strict",
            "autonomy": {"auto_execute_scope": ["screen", "refresh"]},
            "paper": {
                "auto_screen_on_intake": True,
                "auto_complete_note_condition": "after_screen",
                "screening_mode": "legacy",
                "screening_context_pages": 6,
                "screening_max_chars": 12000,
            },
        },
    )

    loaded = load_runtime_preferences(root)
    assert loaded["autonomy"]["auto_execute_scope"] == ["refresh"]
    assert not {
        "auto_screen_on_intake",
        "auto_complete_note_condition",
        "screening_mode",
        "screening_context_pages",
        "screening_max_chars",
    } & set(loaded["paper"])

    write_runtime_preferences(root, {})
    stored = load_yaml(runtime_preferences_path(root))
    assert stored["autonomy"]["auto_execute_scope"] == ["refresh"]
    assert "auto_screen_on_intake" not in stored["paper"]


def test_effective_review_policy_preserves_strict_and_bounds_personal_configuration(tmp_path: Path) -> None:
    strict_root = tmp_path / "strict"
    write_yaml_if_changed(
        runtime_preferences_path(strict_root),
        {
            "governance_profile": "strict",
            "review": {"batch_item_limit": 19, "card_ttl_hours": 168},
        },
    )
    assert effective_review_policy(strict_root) == {
        "governance_profile": "strict",
        "item_limit": 3,
        "card_ttl_hours": 24,
        "ttl_seconds": 86400,
        "absolute_max_items": 20,
    }

    personal_root = tmp_path / "personal"
    write_yaml_if_changed(
        runtime_preferences_path(personal_root),
        {
            "governance_profile": "personal",
            "review": {"batch_item_limit": 99, "card_ttl_hours": 999},
        },
    )
    assert effective_review_policy(personal_root) == {
        "governance_profile": "personal",
        "item_limit": 20,
        "card_ttl_hours": 168,
        "ttl_seconds": 604800,
        "absolute_max_items": 20,
    }


def test_config_owner_sets_governance_profile_and_review_policy(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    root.mkdir()
    script = _project_root() / "skills" / "research-config-manager" / "scripts" / "config.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--root",
            str(root),
            "set-governance",
            "--profile",
            "personal",
            "--review-item-limit",
            "12",
            "--card-ttl-hours",
            "72",
        ],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(_project_root() / "runtime" / "lib")},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert effective_review_policy(root)["item_limit"] == 12
    assert effective_review_policy(root)["card_ttl_hours"] == 72

    guide = subprocess.run(
        [sys.executable, str(script), "--root", str(root), "guide", "--focus", "governance"],
        cwd=root,
        env={**os.environ, "PYTHONPATH": str(_project_root() / "runtime" / "lib")},
        text=True,
        capture_output=True,
        check=False,
    )
    assert guide.returncode == 0, guide.stderr
    assert "- 治理档位: personal" in guide.stdout
    assert "- 每批待确认上限: 12" in guide.stdout
    assert "- 待确认卡片有效期: 72 小时" in guide.stdout
