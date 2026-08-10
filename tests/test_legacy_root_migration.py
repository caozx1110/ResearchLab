from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from repo_paths import REPO_ROOT

from research.legacy_migration import (
    LEGACY_MIGRATION_GUIDANCE,
    LegacyLayoutState,
    LegacyMigrationError,
    apply_legacy_migration,
    detect_legacy_layout,
    plan_legacy_migration,
    rollback_legacy_migration,
)
from research.workspace_layout import WORKSPACE_LAYOUT_MARKER_BYTES
from research.prefs import ensure_workspace


KB_CLI = REPO_ROOT / "skills/kb-cli/scripts/kb"
SYNC = REPO_ROOT / "install-lib/ws_sync.py"
INSTALLER = REPO_ROOT / "install.sh"
AUTHORIZATION = "我已检查备份与拒绝条件，现在明确授权迁移这个隔离工作区。"
ROLLBACK_AUTHORIZATION = "我已复核当前迁移收据，现在明确授权回滚这个隔离工作区。"


def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _legacy_workspace(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    workspace = tmp_path / "workspace"
    legacy = workspace / "kb"
    (workspace / ".agents").mkdir(parents=True)
    (workspace / ".agents/WORKSPACE_RULES.md").write_text(
        "# WORKSPACE_RULES — fixture\n",
        encoding="utf-8",
    )
    (workspace / ".agents/.install-manifest.json").write_text(
        json.dumps({"fixture": True}, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    bundle_version_bytes = b"0.2.0-legacy-fixture\n"
    (workspace / ".agents/VERSION").write_bytes(bundle_version_bytes)
    agents_bytes = b"# user-owned root rules\n\nKeep this exact.\n"
    root_ignore_bytes = b"# user root ignore\n/local-only/\n"
    (workspace / "AGENTS.md").write_bytes(agents_bytes)
    (workspace / ".gitignore").write_bytes(root_ignore_bytes)
    (workspace / ".gitignore").chmod(0o600)

    (legacy / "units/papers/p-migration/source").mkdir(parents=True)
    (legacy / "config").mkdir()
    (legacy / ".runtime/cache").mkdir(parents=True)
    (legacy / ".journal/locks").mkdir(parents=True)
    legacy_ignore_bytes = (
        b"# legacy user rule\n*.scratch\n.runtime/\n.journal/\nraw/\noutput/\n"
    )
    (legacy / ".gitignore").write_bytes(legacy_ignore_bytes)
    record_bytes = (
        b"id: p-migration\nkind: paper\n"
        b"artifact: kb/units/papers/p-migration/record.yaml\n"
        b"evidence: kb/units/papers/p-migration/source/paper.pdf\n"
    )
    (legacy / "units/papers/p-migration/record.yaml").write_bytes(record_bytes)
    (legacy / "units/papers/p-migration/source/paper.pdf").write_bytes(
        b"%PDF-1.4\nimmutable fixture bytes\n"
    )
    (legacy / "config/runtime-preferences.yaml").write_text(
        "schema_version: 1\ngovernance_profile: strict\n",
        encoding="utf-8",
    )
    (legacy / ".runtime/cache/local.bin").write_bytes(b"runtime-state\x00")
    (legacy / ".journal/committed.yaml").write_text(
        "op_id: committed\nstate: commit\n",
        encoding="utf-8",
    )

    _git(legacy, "init", "-b", "main")
    _git(legacy, "config", "user.name", "Migration Fixture")
    _git(legacy, "config", "user.email", "migration@example.invalid")
    _git(legacy, "add", "--", ".gitignore", "config", "units")
    _git(legacy, "commit", "-m", "initial knowledge history")
    first_head = _git(legacy, "rev-parse", "HEAD").stdout.strip()
    (legacy / "units/papers/p-migration/notes.md").write_text(
        "# Notes\n\nEvidence remains at `kb/units/papers/p-migration/source/paper.pdf`.\n",
        encoding="utf-8",
    )
    _git(legacy, "add", "--", "units/papers/p-migration/notes.md")
    _git(legacy, "commit", "-m", "add evidence-bound note")
    old_head = _git(legacy, "rev-parse", "HEAD").stdout.strip()
    _git(legacy, "branch", "preserved-history", first_head)
    _git(legacy, "tag", "legacy-v1", first_head)
    assert _git(legacy, "status", "--porcelain", "--untracked-files=all").stdout == ""
    return workspace, {
        "agents": agents_bytes,
        "root_ignore": root_ignore_bytes,
        "legacy_ignore": legacy_ignore_bytes,
        "bundle_version": bundle_version_bytes,
        "record": record_bytes,
        "first_head": first_head,
        "old_head": old_head,
    }


def _tree_bytes(root: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts or path.is_dir() or path.is_symlink():
            continue
        result[path.relative_to(root).as_posix()] = path.read_bytes()
    return result


def _receipt(recovery: Path) -> dict[str, object]:
    return json.loads((recovery / "receipt.json").read_text(encoding="utf-8"))


def _installer_environment() -> dict[str, str]:
    return {
        **os.environ,
        "NO_COLOR": "1",
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "RESEARCH_PYTHON": os.sys.executable,
    }


def _run_public_installer(
    workspace: Path,
    action: str,
    *extra: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            "bash",
            os.fspath(INSTALLER),
            action,
            "--project",
            os.fspath(workspace),
            "--yes",
            *extra,
        ],
        cwd=REPO_ROOT,
        env=_installer_environment(),
        text=True,
        capture_output=True,
        check=False,
    )


def _reseal_plan(payload: dict[str, object]) -> dict[str, object]:
    unsigned = {key: value for key, value in payload.items() if key != "plan_sha256"}
    payload["plan_sha256"] = hashlib.sha256(
        json.dumps(
            unsigned,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    return payload


def test_detector_distinguishes_root_no_layout_partial_outer_symlink_and_special(
    tmp_path: Path,
) -> None:
    empty = tmp_path / "empty"
    empty.mkdir()
    assert detect_legacy_layout(empty).state is LegacyLayoutState.NO_LAYOUT

    active = tmp_path / "active"
    (active / "config").mkdir(parents=True)
    (active / "config/workspace-layout.yaml").write_bytes(WORKSPACE_LAYOUT_MARKER_BYTES)
    assert detect_legacy_layout(active).state is LegacyLayoutState.ACTIVE_ROOT
    (active / "legacy-target").mkdir()
    (active / "kb").symlink_to(active / "legacy-target", target_is_directory=True)
    assert detect_legacy_layout(active).state is LegacyLayoutState.SYMLINK

    partial = tmp_path / "partial"
    (partial / "kb").mkdir(parents=True)
    assert detect_legacy_layout(partial).state is LegacyLayoutState.PARTIAL_AMBIGUOUS

    outer, _ = _legacy_workspace(tmp_path / "outer-fixture")
    _git(outer, "init", "-b", "outer")
    assert detect_legacy_layout(outer).state is LegacyLayoutState.OUTER_GIT

    symlinked = tmp_path / "symlinked"
    symlinked.mkdir()
    (symlinked / "target").mkdir()
    (symlinked / "kb").symlink_to(symlinked / "target", target_is_directory=True)
    assert detect_legacy_layout(symlinked).state is LegacyLayoutState.SYMLINK

    special = tmp_path / "special"
    special.mkdir()
    os.mkfifo(special / "kb")
    assert detect_legacy_layout(special).state is LegacyLayoutState.SPECIAL_NODE

    real_parent = tmp_path / "real-parent"
    linked_parent = tmp_path / "linked-parent"
    (real_parent / "workspace").mkdir(parents=True)
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    assert (
        detect_legacy_layout(linked_parent / "workspace").state
        is LegacyLayoutState.SYMLINK
    )


def test_detector_distinguishes_eligible_dirty_journal_and_collision(tmp_path: Path) -> None:
    eligible, _ = _legacy_workspace(tmp_path / "eligible")
    before = _tree_bytes(eligible)
    detection = detect_legacy_layout(eligible)
    assert detection.state is LegacyLayoutState.ELIGIBLE_LEGACY
    assert detection.git is not None
    assert _tree_bytes(eligible) == before

    dirty, _ = _legacy_workspace(tmp_path / "dirty")
    (dirty / "kb/units/papers/p-migration/notes.md").write_text(
        "dirty tracked bytes\n",
        encoding="utf-8",
    )
    assert detect_legacy_layout(dirty).state is LegacyLayoutState.DIRTY

    journal, _ = _legacy_workspace(tmp_path / "journal")
    (journal / "kb/.journal/live.yaml").write_text(
        "op_id: live\nstate: begin\n",
        encoding="utf-8",
    )
    assert detect_legacy_layout(journal).state is LegacyLayoutState.INCOMPLETE_JOURNAL

    collision, _ = _legacy_workspace(tmp_path / "collision")
    (collision / "units").mkdir()
    assert detect_legacy_layout(collision).state is LegacyLayoutState.COLLISION

    linked_leaf, _ = _legacy_workspace(tmp_path / "linked-leaf")
    (linked_leaf / "kb/.runtime/cache-link").symlink_to(
        linked_leaf / "kb/.runtime/cache",
        target_is_directory=True,
    )
    assert detect_legacy_layout(linked_leaf).state is LegacyLayoutState.SYMLINK

    special_leaf, _ = _legacy_workspace(tmp_path / "special-leaf")
    os.mkfifo(special_leaf / "kb/.runtime/live.pipe")
    assert detect_legacy_layout(special_leaf).state is LegacyLayoutState.SPECIAL_NODE


def test_plan_is_read_only_and_apply_preserves_bytes_history_refs_and_root_rules(
    tmp_path: Path,
) -> None:
    workspace, expected = _legacy_workspace(tmp_path)
    before = _tree_bytes(workspace)
    plan = plan_legacy_migration(workspace)
    assert _tree_bytes(workspace) == before
    assert not (workspace.parent / plan.recovery_name).exists()

    result = apply_legacy_migration(
        plan,
        user_authorization=AUTHORIZATION,
        authorization_source="user_message",
    )
    recovery = Path(result["recovery_material"])
    assert result["state"] == "migrated"
    assert not (workspace / "kb").exists()
    assert (workspace / ".git").is_dir()
    assert (workspace / "config/workspace-layout.yaml").read_bytes() == WORKSPACE_LAYOUT_MARKER_BYTES
    assert (workspace / "units/papers/p-migration/record.yaml").read_bytes() == expected["record"]
    assert b"kb/units/papers/p-migration" in (
        workspace / "units/papers/p-migration/record.yaml"
    ).read_bytes()
    assert (workspace / "AGENTS.md").read_bytes() == expected["agents"]
    assert (workspace / ".agents/VERSION").read_bytes() == expected["bundle_version"]
    merged_ignore = (workspace / ".gitignore").read_bytes()
    assert merged_ignore.startswith(expected["root_ignore"])
    assert expected["legacy_ignore"] in merged_ignore
    assert b"/.agents/" in merged_ignore
    assert stat_mode(workspace / ".gitignore") == 0o600
    assert _git(workspace, "rev-parse", "HEAD^").stdout.strip() == expected["old_head"]
    assert _git(workspace, "merge-base", "--is-ancestor", str(expected["first_head"]), "HEAD").returncode == 0
    assert _git(workspace, "show-ref", "--verify", "refs/heads/preserved-history").stdout.startswith(
        str(expected["first_head"])
    )
    assert _git(workspace, "show-ref", "--verify", "refs/tags/legacy-v1").stdout.startswith(
        str(expected["first_head"])
    )
    assert recovery.parent == workspace.parent
    assert stat_mode(recovery) == 0o700
    assert _receipt(recovery)["state"] == "migrated"


def test_resealed_plan_cannot_widen_the_frozen_move_inventory(tmp_path: Path) -> None:
    workspace, _ = _legacy_workspace(tmp_path)
    plan = plan_legacy_migration(workspace)
    payload = plan.to_dict()
    payload["movable_entries"] = [*payload["movable_entries"], "../outside"]
    with pytest.raises(LegacyMigrationError, match="movable inventory"):
        type(plan).from_dict(_reseal_plan(payload))


def stat_mode(path: Path) -> int:
    return path.stat().st_mode & 0o777


@pytest.mark.parametrize(
    "stage",
    [
        "recovery-prepared",
        "git-moved",
        "entries-moved",
        "ignore-merged",
        "marker-written",
        "commit-created",
    ],
)
def test_fault_after_each_apply_stage_restores_exact_legacy_state(
    tmp_path: Path,
    stage: str,
) -> None:
    workspace, expected = _legacy_workspace(tmp_path)
    before = _tree_bytes(workspace)
    plan = plan_legacy_migration(workspace)
    with pytest.raises(LegacyMigrationError, match="injected migration failure"):
        apply_legacy_migration(
            plan,
            user_authorization=AUTHORIZATION,
            authorization_source="user_message",
            _fault_after=stage,
        )
    assert detect_legacy_layout(workspace).state is LegacyLayoutState.ELIGIBLE_LEGACY
    assert _git(workspace / "kb", "rev-parse", "HEAD").stdout.strip() == expected["old_head"]
    assert _tree_bytes(workspace) == before
    recovery = workspace.parent / plan.recovery_name
    assert recovery.is_dir()
    assert _receipt(recovery)["state"] == "rolled-back-after-failure"


def test_stale_plan_and_missing_current_message_authorization_are_zero_write(
    tmp_path: Path,
) -> None:
    workspace, _ = _legacy_workspace(tmp_path)
    plan = plan_legacy_migration(workspace)
    before = _tree_bytes(workspace)
    with pytest.raises(LegacyMigrationError, match="current user message"):
        apply_legacy_migration(
            plan,
            user_authorization="",
            authorization_source="agent",
        )
    assert _tree_bytes(workspace) == before
    assert not (workspace.parent / plan.recovery_name).exists()

    (workspace / "kb/units/papers/p-migration/notes.md").write_text(
        "stale plan\n",
        encoding="utf-8",
    )
    with pytest.raises(LegacyMigrationError, match="stale"):
        apply_legacy_migration(
            plan,
            user_authorization=AUTHORIZATION,
            authorization_source="user_message",
        )
    assert not (workspace.parent / plan.recovery_name).exists()
    assert (workspace / "kb/.git").is_dir()
    assert not (workspace / ".git").exists()


def test_successful_rollback_adds_reverse_commit_and_restores_legacy_layout(
    tmp_path: Path,
) -> None:
    workspace, expected = _legacy_workspace(tmp_path)
    original_bytes = _tree_bytes(workspace)
    plan = plan_legacy_migration(workspace)
    applied = apply_legacy_migration(
        plan,
        user_authorization=AUTHORIZATION,
        authorization_source="user_message",
    )
    recovery = Path(applied["recovery_material"])
    result = rollback_legacy_migration(
        workspace,
        recovery,
        user_authorization=ROLLBACK_AUTHORIZATION,
        authorization_source="user_message",
        expected_receipt_sha256=str(_receipt(recovery)["receipt_sha256"]),
    )
    assert result["state"] == "rolled-back"
    assert (workspace / "kb/.git").is_dir()
    assert not (workspace / ".git").exists()
    assert not (workspace / "config").exists()
    assert (workspace / ".gitignore").read_bytes() == expected["root_ignore"]
    assert (workspace / "kb/.gitignore").read_bytes() == expected["legacy_ignore"]
    assert (workspace / "AGENTS.md").read_bytes() == expected["agents"]
    assert _tree_bytes(workspace) == original_bytes
    rollback_head = _git(workspace / "kb", "rev-parse", "HEAD").stdout.strip()
    assert rollback_head == result["rollback_head"]
    assert _git(workspace / "kb", "rev-parse", "HEAD^").stdout.strip() == applied["migration_head"]
    assert _git(workspace / "kb", "merge-base", "--is-ancestor", str(expected["old_head"]), "HEAD").returncode == 0
    assert _receipt(recovery)["state"] == "rolled-back"
    completed_receipt = (recovery / "receipt.json").read_bytes()
    with pytest.raises(LegacyMigrationError, match="not eligible"):
        rollback_legacy_migration(
            workspace,
            recovery,
            user_authorization="我明确授权再次检查回滚状态。",
            authorization_source="user_message",
            expected_receipt_sha256=str(_receipt(recovery)["receipt_sha256"]),
        )
    assert (recovery / "receipt.json").read_bytes() == completed_receipt


def test_rollback_requires_current_receipt_and_rejects_linked_recovery(
    tmp_path: Path,
) -> None:
    workspace, _ = _legacy_workspace(tmp_path)
    applied = apply_legacy_migration(
        plan_legacy_migration(workspace),
        user_authorization=AUTHORIZATION,
        authorization_source="user_message",
    )
    recovery = Path(applied["recovery_material"])
    head = _git(workspace, "rev-parse", "HEAD").stdout.strip()
    with pytest.raises(LegacyMigrationError, match="stale"):
        rollback_legacy_migration(
            workspace,
            recovery,
            user_authorization=ROLLBACK_AUTHORIZATION,
            authorization_source="user_message",
            expected_receipt_sha256="0" * 64,
        )
    assert _git(workspace, "rev-parse", "HEAD").stdout.strip() == head

    expected = str(_receipt(recovery)["receipt_sha256"])
    real_recovery = recovery.with_name(f"{recovery.name}-real")
    recovery.rename(real_recovery)
    recovery.symlink_to(real_recovery, target_is_directory=True)
    with pytest.raises(LegacyMigrationError, match="recovery directory is unsafe"):
        rollback_legacy_migration(
            workspace,
            recovery,
            user_authorization=ROLLBACK_AUTHORIZATION,
            authorization_source="user_message",
            expected_receipt_sha256=expected,
        )
    assert _git(workspace, "rev-parse", "HEAD").stdout.strip() == head


def test_rollback_detects_canonical_drift_before_git_or_layout_mutation(
    tmp_path: Path,
) -> None:
    workspace, _ = _legacy_workspace(tmp_path)
    applied = apply_legacy_migration(
        plan_legacy_migration(workspace),
        user_authorization=AUTHORIZATION,
        authorization_source="user_message",
    )
    recovery = Path(applied["recovery_material"])
    (workspace / "units/papers/p-migration/new-untracked.md").write_text(
        "drift\n",
        encoding="utf-8",
    )
    migration_head = _git(workspace, "rev-parse", "HEAD").stdout.strip()
    with pytest.raises(LegacyMigrationError, match="canonical bytes changed"):
        rollback_legacy_migration(
            workspace,
            recovery,
            user_authorization=ROLLBACK_AUTHORIZATION,
            authorization_source="user_message",
            expected_receipt_sha256=str(_receipt(recovery)["receipt_sha256"]),
        )
    assert _git(workspace, "rev-parse", "HEAD").stdout.strip() == migration_head
    assert (workspace / ".git").is_dir()
    assert not (workspace / "kb").exists()


@pytest.mark.parametrize(
    "fault_stage",
    ["rollback-commit-created", "rollback-entries-moved"],
)
def test_incomplete_success_rollback_preserves_unique_recovery_material(
    tmp_path: Path,
    fault_stage: str,
) -> None:
    workspace, _ = _legacy_workspace(tmp_path)
    plan = plan_legacy_migration(workspace)
    applied = apply_legacy_migration(
        plan,
        user_authorization=AUTHORIZATION,
        authorization_source="user_message",
    )
    recovery = Path(applied["recovery_material"])
    receipt_sha256 = str(_receipt(recovery)["receipt_sha256"])
    with pytest.raises(LegacyMigrationError, match="injected migration failure"):
        rollback_legacy_migration(
            workspace,
            recovery,
            user_authorization=ROLLBACK_AUTHORIZATION,
            authorization_source="user_message",
            expected_receipt_sha256=receipt_sha256,
            _fault_after=fault_stage,
        )
    assert recovery.is_dir()
    receipt = _receipt(recovery)
    assert receipt["state"] == "rollback-incomplete"
    assert receipt["rollback_head"]
    assert len(list(workspace.parent.glob(f"{recovery.name}*"))) == 1


def test_apply_refuses_a_contended_workspace_lock_before_recovery(tmp_path: Path) -> None:
    workspace, _ = _legacy_workspace(tmp_path)
    plan = plan_legacy_migration(workspace)
    holder = subprocess.Popen(
        [
            os.sys.executable,
            "-c",
            (
                "import fcntl, os, sys, time; "
                "fd=os.open(sys.argv[1], os.O_RDONLY); "
                "fcntl.flock(fd, fcntl.LOCK_EX); "
                "print('locked', flush=True); time.sleep(10)"
            ),
            os.fspath(workspace),
        ],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert holder.stdout is not None
        assert holder.stdout.readline().strip() == "locked"
        with pytest.raises(LegacyMigrationError, match="active lifecycle operation"):
            apply_legacy_migration(
                plan,
                user_authorization=AUTHORIZATION,
                authorization_source="user_message",
            )
    finally:
        holder.terminate()
        holder.wait(timeout=5)
    assert not (workspace.parent / plan.recovery_name).exists()
    assert detect_legacy_layout(workspace).state is LegacyLayoutState.ELIGIBLE_LEGACY


@pytest.mark.parametrize("action", ["install", "update", "reinstall"])
def test_installer_lifecycle_detects_legacy_before_any_write(
    tmp_path: Path,
    action: str,
) -> None:
    workspace, _ = _legacy_workspace(tmp_path)
    before = _tree_bytes(workspace)
    result = subprocess.run(
        [
            os.fspath(Path(os.sys.executable)),
            os.fspath(SYNC),
            action,
            "--repo",
            os.fspath(REPO_ROOT),
            "--dir",
            os.fspath(workspace),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert LEGACY_MIGRATION_GUIDANCE in result.stderr
    assert "不会自动迁移" in result.stderr
    assert _tree_bytes(workspace) == before


def test_installer_rejects_a_linked_workspace_identity_before_write(tmp_path: Path) -> None:
    real = tmp_path / "real-workspace"
    linked = tmp_path / "linked-workspace"
    real.mkdir()
    linked.symlink_to(real, target_is_directory=True)
    result = subprocess.run(
        [
            os.fspath(Path(os.sys.executable)),
            os.fspath(SYNC),
            "install",
            "--repo",
            os.fspath(REPO_ROOT),
            "--dir",
            os.fspath(linked),
        ],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert not any(real.iterdir())


def test_public_installer_routes_legacy_layout_without_private_leakage(tmp_path: Path) -> None:
    workspace, _ = _legacy_workspace(tmp_path)
    before = _tree_bytes(workspace)
    result = _run_public_installer(workspace, "install", "--codex")
    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode != 0
    assert "旧版知识库布局" in output
    assert "不会自动搬运研究数据" in output
    for private_token in ("Traceback", "receipt_sha256", "--authorization", ".workspace-oss-migration-"):
        assert private_token not in output
    assert _tree_bytes(workspace) == before


def test_migrated_workspace_passes_root_runtime_and_product_lifecycle(tmp_path: Path) -> None:
    workspace = tmp_path / "installed-workspace"
    workspace.mkdir()
    user_agents = b"# User rules\n\nKeep these bytes.\n"
    (workspace / "AGENTS.md").write_bytes(user_agents)
    (workspace / ".gitignore").write_bytes(b"# user ignore\n/local-only/\n")
    installed = _run_public_installer(workspace, "install", "--codex")
    assert installed.returncode == 0, installed.stdout + installed.stderr

    template, expected = _legacy_workspace(tmp_path / "legacy-template")
    shutil.copytree(template / "kb", workspace / "kb")
    assert detect_legacy_layout(workspace).state is LegacyLayoutState.ELIGIBLE_LEGACY
    applied = apply_legacy_migration(
        plan_legacy_migration(workspace),
        user_authorization=AUTHORIZATION,
        authorization_source="user_message",
    )
    assert applied["state"] == "migrated"
    assert (workspace / "units/papers/p-migration/record.yaml").read_bytes() == expected["record"]
    assert b"kb/units/papers/p-migration" in expected["record"]

    ensure_workspace(workspace)
    status = subprocess.run(
        [os.fspath(KB_CLI), "--root", os.fspath(workspace), "status"],
        cwd=REPO_ROOT,
        env=_installer_environment(),
        text=True,
        capture_output=True,
        check=False,
    )
    assert status.returncode == 0, status.stdout + status.stderr

    for action in ("update", "reinstall"):
        result = _run_public_installer(workspace, action)
        assert result.returncode == 0, result.stdout + result.stderr
        assert (workspace / "units/papers/p-migration/record.yaml").read_bytes() == expected["record"]
        assert "Keep these bytes." in (workspace / "AGENTS.md").read_text(encoding="utf-8")

    removed = _run_public_installer(workspace, "uninstall")
    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert (workspace / "AGENTS.md").read_bytes() == user_agents
    assert (workspace / "units/papers/p-migration/record.yaml").read_bytes() == expected["record"]
    assert (workspace / ".git").is_dir()


def test_public_runtime_keeps_help_doctor_rescue_and_blocks_other_legacy_verbs(
    tmp_path: Path,
) -> None:
    workspace, _ = _legacy_workspace(tmp_path)
    before = _tree_bytes(workspace)
    for verb in ("help", "doctor"):
        result = subprocess.run(
            [os.fspath(KB_CLI), "--root", os.fspath(workspace), verb],
            cwd=REPO_ROOT,
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode in {0, 1}
        assert LEGACY_MIGRATION_GUIDANCE not in result.stdout
        assert LEGACY_MIGRATION_GUIDANCE not in result.stderr
    blocked = subprocess.run(
        [os.fspath(KB_CLI), "--root", os.fspath(workspace), "status"],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert blocked.returncode != 0
    assert LEGACY_MIGRATION_GUIDANCE in f"{blocked.stdout}\n{blocked.stderr}"
    assert _tree_bytes(workspace) == before
