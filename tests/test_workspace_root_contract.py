from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

from repo_paths import REPO_ROOT
from research.common import print_resolved_project_roots, research_root
from research.git_ops import kb_repo_path
from research.path_contract import (
    DataLayout,
    PathContractError,
    RootRoles,
    TargetClass,
    assert_no_follow_target,
    classify_data_relative_path,
    logical_ref_to_physical_path,
    physical_path_to_logical_ref,
    validate_logical_artifact_ref,
)
from research.paths import units_root
from research.prefs import ensure_workspace


def _roots(tmp_path: Path, layout: DataLayout) -> RootRoles:
    workspace = tmp_path / f"workspace-{layout.value}"
    bundle = tmp_path / "product-bundle"
    workspace.mkdir(parents=True)
    bundle.mkdir(parents=True, exist_ok=True)
    roots = RootRoles.for_layout(workspace, bundle, layout)
    roots.data_root.mkdir(exist_ok=True)
    return roots


def test_path_contract_is_independent_of_high_level_core_facade() -> None:
    source = (REPO_ROOT / "runtime/lib/research/path_contract.py").read_text(
        encoding="utf-8"
    )

    assert "from .core" not in source
    assert "from research.core" not in source


@pytest.mark.parametrize(
    ("layout", "data_suffix"),
    [
        (DataLayout.LEGACY_KB_DIRECTORY, "kb"),
        (DataLayout.WORKSPACE_ROOT, "."),
    ],
)
def test_root_roles_keep_workspace_data_and_bundle_explicit(
    tmp_path: Path,
    layout: DataLayout,
    data_suffix: str,
) -> None:
    roots = _roots(tmp_path, layout)

    expected = (
        roots.workspace_root
        if data_suffix == "."
        else roots.workspace_root / data_suffix
    )
    assert roots.data_root == expected
    assert roots.product_bundle_root == tmp_path / "product-bundle"

    with pytest.raises(PathContractError, match="does not match"):
        RootRoles(
            workspace_root=roots.workspace_root,
            data_root=roots.workspace_root / "wrong",
            product_bundle_root=roots.product_bundle_root,
            layout=layout,
        )


@pytest.mark.parametrize(
    "logical_ref",
    [
        "kb/units/papers/p-test/record.yaml",
        "kb/programs/program-a/state.yaml",
        "kb/raw/source.pdf",
        "kb/index.yaml",
        "kb/.runtime/search/passages.sqlite3",
        "kb/.journal/op-0001.yaml",
    ],
)
def test_logical_refs_round_trip_byte_identically_across_layouts(
    tmp_path: Path,
    logical_ref: str,
) -> None:
    original = logical_ref.encode("utf-8")
    for layout in DataLayout:
        roots = _roots(tmp_path / layout.value, layout)
        physical = logical_ref_to_physical_path(roots, logical_ref)
        restored = physical_path_to_logical_ref(roots, physical)

        assert restored.encode("utf-8") == original
        expected_relative = Path(*logical_ref.split("/")[1:])
        assert physical == roots.data_root / expected_relative


@pytest.mark.parametrize(
    "logical_ref",
    [
        "",
        "kb",
        "/kb/units/papers/p/record.yaml",
        " kb/units/papers/p/record.yaml",
        "kb/units/papers/p/record.yaml ",
        "kb//units/papers/p/record.yaml",
        "kb/units/./p/record.yaml",
        "kb/units/../programs/p/state.yaml",
        "kb\\units\\papers\\p\\record.yaml",
        "units/papers/p/record.yaml",
        "kb/.agents/lib/research/core.py",
        "kb/.Git/config",
        "kb/.venv/bin/python",
        "kb/AGENTS.md",
        "kb/CLAUDE.md",
        "kb/bin/kb",
        "kb/index.yaml/child",
        "kb/unknown-top-level/file.yaml",
    ],
)
def test_logical_ref_validation_fails_closed(logical_ref: str) -> None:
    with pytest.raises(PathContractError):
        validate_logical_artifact_ref(logical_ref)


@pytest.mark.parametrize(
    ("relative", "expected"),
    [
        ("units/papers/p/record.yaml", TargetClass.CANONICAL_ARTIFACT),
        ("raw/source.pdf", TargetClass.CANONICAL_ARTIFACT),
        (".runtime/cache.sqlite3", TargetClass.OPERATIONAL_STATE),
        (".journal/op.yaml", TargetClass.OPERATIONAL_STATE),
        (".agents/lib/research/core.py", TargetClass.RESERVED),
        (".GIT/config", TargetClass.RESERVED),
        ("AGENTS.md", TargetClass.RESERVED),
        ("other/data.yaml", TargetClass.UNKNOWN),
    ],
)
def test_top_level_target_classification(relative: str, expected: TargetClass) -> None:
    assert classify_data_relative_path(relative) is expected


@pytest.mark.parametrize("layout", list(DataLayout))
def test_physical_conversion_rejects_escape_reserved_and_unknown(
    tmp_path: Path,
    layout: DataLayout,
) -> None:
    roots = _roots(tmp_path, layout)

    with pytest.raises(PathContractError, match="escaped"):
        physical_path_to_logical_ref(roots, roots.data_root.parent / "outside.yaml")
    with pytest.raises(PathContractError, match="reserved"):
        physical_path_to_logical_ref(roots, roots.data_root / ".agents" / "owned.yaml")
    with pytest.raises(PathContractError, match="unknown"):
        physical_path_to_logical_ref(roots, roots.data_root / "other" / "owned.yaml")


def test_no_follow_target_accepts_regular_or_missing_canonical_paths(tmp_path: Path) -> None:
    roots = _roots(tmp_path, DataLayout.WORKSPACE_ROOT)
    units = roots.data_root / "units"
    units.mkdir()
    record = units / "papers" / "p-test" / "record.yaml"

    missing = assert_no_follow_target(roots, record)
    assert not record.exists()
    assert missing.logical_ref == "kb/units/papers/p-test/record.yaml"
    assert missing.target_class is TargetClass.CANONICAL_ARTIFACT

    record.parent.mkdir(parents=True)
    record.write_text("id: p-test\n", encoding="utf-8")
    existing = assert_no_follow_target(roots, record)
    assert existing.physical_path == record


def test_no_follow_target_requires_explicit_operational_state_opt_in(tmp_path: Path) -> None:
    roots = _roots(tmp_path, DataLayout.WORKSPACE_ROOT)
    journal = roots.data_root / ".journal" / "op.yaml"

    with pytest.raises(PathContractError, match="not allowed"):
        assert_no_follow_target(roots, journal)

    assessed = assert_no_follow_target(
        roots,
        journal,
        allowed_classes=(TargetClass.OPERATIONAL_STATE,),
    )
    assert assessed.logical_ref == "kb/.journal/op.yaml"


def test_no_follow_target_rejects_symlink_ancestor_and_leaf(tmp_path: Path) -> None:
    roots = _roots(tmp_path, DataLayout.WORKSPACE_ROOT)
    outside = tmp_path / "outside"
    outside.mkdir()

    (roots.data_root / "units").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PathContractError, match="symlink"):
        assert_no_follow_target(roots, roots.data_root / "units" / "record.yaml")

    (roots.data_root / "units").unlink()
    (roots.data_root / "units").mkdir()
    leaf = roots.data_root / "units" / "linked-record.yaml"
    leaf.symlink_to(outside / "record.yaml")
    with pytest.raises(PathContractError, match="symlink"):
        assert_no_follow_target(roots, leaf)


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO fixture requires POSIX")
def test_no_follow_target_rejects_special_leaf(tmp_path: Path) -> None:
    roots = _roots(tmp_path, DataLayout.WORKSPACE_ROOT)
    units = roots.data_root / "units"
    units.mkdir()
    fifo = units / "special-node"
    os.mkfifo(fifo)

    with pytest.raises(PathContractError, match="special"):
        assert_no_follow_target(roots, fifo)


def test_no_follow_target_rejects_symlinked_data_root(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    outside = tmp_path / "outside-kb"
    outside.mkdir()
    (workspace / "kb").symlink_to(outside, target_is_directory=True)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    roots = RootRoles.for_layout(workspace, bundle, DataLayout.LEGACY_KB_DIRECTORY)

    with pytest.raises(PathContractError, match="symlink"):
        assert_no_follow_target(roots, roots.data_root / "units" / "record.yaml")


def test_wave_one_does_not_activate_workspace_root_behavior(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    workspace = tmp_path / "legacy-workspace"
    workspace.mkdir()

    assert research_root(workspace) == workspace / "kb"
    assert units_root(workspace) == workspace / "kb" / "units"
    assert kb_repo_path(workspace) == workspace / "kb"

    print_resolved_project_roots(workspace)
    ensure_workspace(workspace)
    assert capsys.readouterr().out == ""
    assert (workspace / "kb" / "units").is_dir()
    assert (workspace / "kb" / ".gitignore").is_file()
    assert not (workspace / "units").exists()


def test_wave_one_installer_plan_still_owns_no_kb_target(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    cache = tmp_path / "pycache"
    scratch = tmp_path / "scratch"
    plan_path = tmp_path / "install-plan.json"
    for directory in (workspace, home, cache, scratch):
        directory.mkdir()

    result = subprocess.run(
        [
            "bash",
            str(REPO_ROOT / "install.sh"),
            "--agent-plan-json",
            str(plan_path),
            "--codex",
            "--project",
            str(workspace),
            "--yes",
        ],
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "HOME": str(home),
            "PYTHONPYCACHEPREFIX": str(cache),
            "TMPDIR": str(scratch),
            "RESEARCH_PYTHON": "/bin/false",
            "NO_COLOR": "1",
        },
        text=True,
        capture_output=True,
        stdin=subprocess.DEVNULL,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    kb_prefix = f"{workspace / 'kb'}/"
    assert all(
        item["path"] != str(workspace / "kb")
        and not str(item["path"]).startswith(kb_prefix)
        for item in plan["targets"]
    )
    assert not (workspace / "kb").exists()
