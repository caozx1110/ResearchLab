from __future__ import annotations

import hashlib
import importlib.util
import json
import multiprocessing
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path
from types import ModuleType
from types import SimpleNamespace

import pytest


BEGIN_MARKER = "# >>> workspace-oss managed >>>"
END_MARKER = "# <<< workspace-oss managed <<<"
PUBLIC_PRESERVATION_WARNING = "检测到用户修改并按安全策略保留，请让 Agent 检查。"
PLAN_BYTE_SHA256_PLACEHOLDER = "COMPUTE_AFTER_REVIEW"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _installer_env() -> dict[str, str]:
    env = {
        **os.environ,
        "NO_COLOR": "1",
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "RESEARCH_PYTHON": sys.executable,
    }
    env.pop("_RESEARCH_RUNTIME_READY", None)
    return env


def test_installer_subprocess_env_never_inherits_bootstrap_ready_sentinel(monkeypatch) -> None:
    monkeypatch.setenv("_RESEARCH_RUNTIME_READY", "1")

    assert "_RESEARCH_RUNTIME_READY" not in _installer_env()


def _run_installer(workspace: Path, action: str, *extra: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(_project_root() / "install.sh"), action, "--project", str(workspace), "--yes", *extra],
        cwd=_project_root(),
        env=_installer_env(),
        text=True,
        capture_output=True,
        check=False,
    )


def _assert_public_preservation_warning(result: subprocess.CompletedProcess[str]) -> None:
    assert PUBLIC_PRESERVATION_WARNING in result.stderr
    assert result.stderr.count(PUBLIC_PRESERVATION_WARNING) == 1
    for token in ("preserving ", "reason=", "warn:", ".agents/", "expected=", "actual="):
        assert token not in result.stdout + result.stderr


def _load_ws_sync() -> ModuleType:
    path = _project_root() / "install-lib" / "ws_sync.py"
    spec = importlib.util.spec_from_file_location("bundle_lifecycle_ws_sync", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_updater(project: str) -> ModuleType:
    library = str(Path(project) / ".agents" / "lib")
    if library not in sys.path:
        sys.path.insert(0, library)
    from research import updater as updater_module

    return updater_module


def test_ws_plan_manifest_expectation_is_exact_loaded_snapshot(capsys, tmp_path: Path) -> None:
    ws_sync = _load_ws_sync()
    workspace = tmp_path / "workspace-plan-snapshot"
    manifest = workspace / ".agents" / ".install-manifest.json"
    manifest.parent.mkdir(parents=True)
    content = b'{"schema":1,"install_name":"workspace-oss","install_mode":"copy-project","files":{}}\n'
    manifest.write_bytes(content)
    manifest.chmod(0o640)
    snapshot = ws_sync.load_manifest_snapshot(workspace)
    assert snapshot is not None
    ws_sync.PLAN_JSONL = True

    ws_sync.emit_plan_manifest_expectation(snapshot, dry_run=True)

    record = json.loads(capsys.readouterr().out)
    assert record == {
        "operation": "manifest-expectation",
        "state": {
            "type": "regular",
            "mode": "0640",
            "byte_sha256": hashlib.sha256(content).hexdigest(),
            "device": manifest.stat().st_dev,
            "inode": manifest.stat().st_ino,
        },
    }


def _rebind_worker(
    project: str,
    workspace: str,
    expected_digest: str,
    pause_ready: object | None,
    pause_release: object | None,
    lock_attempted: object | None,
    result_queue: object,
) -> None:
    updater_module = _load_updater(project)
    if lock_attempted is not None:
        real_flock = updater_module.fcntl.flock

        def observed_flock(descriptor: int, operation: int) -> None:
            if operation == updater_module.fcntl.LOCK_EX:
                lock_attempted.set()
            real_flock(descriptor, operation)

        updater_module.fcntl.flock = observed_flock
    if pause_ready is not None and pause_release is not None:
        real_read = updater_module._read_manifest_at
        reads = 0

        def paused_read(agents_fd: int):
            nonlocal reads
            result = real_read(agents_fd)
            reads += 1
            if reads == 1:
                pause_ready.set()
                if not pause_release.wait(10):
                    raise RuntimeError("rebind test barrier timed out")
            return result

        updater_module._read_manifest_at = paused_read
    try:
        result = updater_module.rebind_source(
            Path(workspace),
            expected_manifest_digest=expected_digest,
            source_origin="ssh://example.test/team/rebound.git",
            source_branch="release/r17",
            source_strategy="remote-branch",
        )
        result_queue.put(("ok", result))
    except updater_module.SourceRebindError as exc:
        result_queue.put(("error", exc.code))
    except BaseException as exc:
        result_queue.put(("exception", repr(exc)))


def _installer_transaction_worker(
    project: str,
    workspace: str,
    planned: object,
    start_write: object,
    lock_attempted: object | None,
    pause_after_validation: object | None,
    validation_release: object | None,
    result_queue: object,
) -> None:
    del project
    ws_sync = _load_ws_sync()
    root = Path(workspace)
    try:
        snapshot = ws_sync.load_manifest_snapshot(root)
        assert snapshot is not None
        replacement = dict(snapshot.payload)
        replacement["marker"] = "installer-won"
        replacement["files"] = {".agents/VERSION": hashlib.sha256(b"0.3.0\n").hexdigest()}
        planned.set()
        if not start_write.wait(10):
            raise RuntimeError("installer start barrier timed out")
        if lock_attempted is not None:
            real_flock = ws_sync.fcntl.flock

            def observed_flock(descriptor: int, operation: int) -> None:
                if operation == ws_sync.fcntl.LOCK_EX:
                    lock_attempted.set()
                real_flock(descriptor, operation)

            ws_sync.fcntl.flock = observed_flock
        if pause_after_validation is not None and validation_release is not None:
            real_validate = ws_sync._validate_expected_manifest_at

            def paused_validate(root_fd: int, expected: object) -> None:
                real_validate(root_fd, expected)
                pause_after_validation.set()
                if not validation_release.wait(10):
                    raise RuntimeError("installer validation barrier timed out")

            ws_sync._validate_expected_manifest_at = paused_validate
        ws_sync.transactional_apply(
            root,
            {".agents/VERSION": (b"0.3.0\n", 0o644)},
            [],
            replacement,
            dry_run=False,
            expected_manifest=snapshot,
        )
        result_queue.put(("ok", "installer"))
    except ws_sync.SyncError as exc:
        result_queue.put(("error", str(exc)))
    except BaseException as exc:
        result_queue.put(("exception", repr(exc)))


def _fresh_transaction_worker(
    workspace: str,
    marker: str,
    planned: object,
    start_write: object,
    lock_attempted: object | None,
    pause_after_validation: object | None,
    validation_release: object | None,
    result_queue: object,
) -> None:
    ws_sync = _load_ws_sync()
    root = Path(workspace)
    try:
        snapshot = ws_sync.load_manifest_snapshot(root, required=False)
        assert snapshot is None
        planned.set()
        if not start_write.wait(10):
            raise RuntimeError("fresh installer start barrier timed out")
        if lock_attempted is not None:
            real_flock = ws_sync.fcntl.flock

            def observed_flock(descriptor: int, operation: int) -> None:
                if operation == ws_sync.fcntl.LOCK_EX:
                    lock_attempted.set()
                real_flock(descriptor, operation)

            ws_sync.fcntl.flock = observed_flock
        if pause_after_validation is not None and validation_release is not None:
            real_validate = ws_sync._validate_expected_manifest_at

            def paused_validate(root_fd: int, expected: object) -> None:
                real_validate(root_fd, expected)
                pause_after_validation.set()
                if not validation_release.wait(10):
                    raise RuntimeError("fresh installer validation barrier timed out")

            ws_sync._validate_expected_manifest_at = paused_validate
        content = f"{marker}\n".encode("utf-8")
        manifest = {
            "schema": 1,
            "install_name": "workspace-oss",
            "install_mode": "copy-project",
            "files": {".agents/VERSION": hashlib.sha256(content).hexdigest()},
            "marker": marker,
        }
        ws_sync.transactional_apply(
            root,
            {".agents/VERSION": (content, 0o644)},
            [],
            manifest,
            dry_run=False,
            expected_manifest=None,
        )
        result_queue.put(("ok", marker))
    except ws_sync.SyncError as exc:
        result_queue.put(("error", str(exc)))
    except BaseException as exc:
        result_queue.put(("exception", repr(exc)))


def _uninstall_worker(
    project: str,
    workspace: str,
    lock_attempted: object,
    pause_after_snapshot: object | None,
    snapshot_release: object | None,
    result_queue: object,
) -> None:
    ws_sync = _load_ws_sync()
    real_flock = ws_sync.fcntl.flock

    def observed_flock(descriptor: int, operation: int) -> None:
        if operation == ws_sync.fcntl.LOCK_EX:
            lock_attempted.set()
        real_flock(descriptor, operation)

    ws_sync.fcntl.flock = observed_flock
    if pause_after_snapshot is not None and snapshot_release is not None:
        real_validate = ws_sync._validate_planned_snapshot

        def paused_validate(current: object, planned: object):
            result = real_validate(current, planned)
            pause_after_snapshot.set()
            if not snapshot_release.wait(10):
                raise RuntimeError("uninstall snapshot barrier timed out")
            return result

        ws_sync._validate_planned_snapshot = paused_validate
    try:
        result = ws_sync.uninstall(
            SimpleNamespace(repo=project, dir=workspace, dry_run=False, expected_manifest_state="")
        )
        result_queue.put(("ok", result))
    except BaseException as exc:
        result_queue.put(("exception", repr(exc)))


def test_clean_install_ships_only_runtime_allowlist(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = _run_installer(workspace, "install", "--codex")

    assert result.returncode == 0, result.stdout + result.stderr
    manifest_path = workspace / ".agents" / ".install-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    installed = set(manifest["files"])
    assert (workspace / ".agents" / "VERSION").is_file()
    assert (workspace / ".agents" / "LICENSE").is_file()
    assert (workspace / ".agents" / "skills" / "kb-cli" / "SKILL.md").is_file()
    assert (workspace / ".agents" / "skills" / "research-monitor" / "SKILL.md").is_file()
    assert (workspace / ".agents" / "lib" / "research" / "common.py").is_file()
    assert not (workspace / ".agents" / "lib" / "research" / "tests").exists()
    assert not (workspace / ".agents" / "skills" / "skill-evolution-advisor" / "scripts" / "eval_research_value.py").exists()
    assert not any("/tests/" in rel for rel in installed)
    assert not any("eval_research_value.py" in rel for rel in installed)
    assert not any(Path(rel).is_absolute() for rel in installed)
    assert manifest["source_strategy"] == "local-checkout"
    assert manifest["source_checkout"] == str(_project_root())

    duplicate = _run_installer(workspace, "install", "--codex")
    assert duplicate.returncode == 1
    assert "更新”或“重装" in duplicate.stderr


def test_fresh_install_rejects_unverified_existing_managed_block(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace-unverified-block"
    workspace.mkdir()
    agents = workspace / "AGENTS.md"
    original = (
        "# User rules\n\n"
        f"{BEGIN_MARKER}\n"
        "unverified prior bundle content\n"
        f"{END_MARKER}\n"
    )
    agents.write_text(original, encoding="utf-8")

    for extra in (
        ("--codex", "--agent-plan", "--agent-plan-json", str(tmp_path / "unverified-plan.json")),
        ("--codex",),
    ):
        result = _run_installer(workspace, "install", *extra)
        assert result.returncode == 1
        assert agents.read_text(encoding="utf-8") == original
        assert not (workspace / ".agents/.install-manifest.json").exists()


def test_reinstall_rejects_managed_block_drift_unless_forced(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace-reinstall-drift"
    workspace.mkdir()
    agents = workspace / "AGENTS.md"
    agents.write_text("# User rules\n\nKeep this prose.\n", encoding="utf-8")
    installed = _run_installer(workspace, "install", "--codex")
    assert installed.returncode == 0, installed.stdout + installed.stderr
    drifted = agents.read_text(encoding="utf-8").replace(
        "<!-- Managed by workspace-oss. Content outside this block is user-owned. -->",
        "<!-- Locally edited managed block. -->",
        1,
    )
    agents.write_text(drifted, encoding="utf-8")

    for extra in (
        ("--agent-plan", "--agent-plan-json", str(tmp_path / "drift-plan.json")),
        (),
    ):
        rejected = _run_installer(workspace, "reinstall", *extra)
        assert rejected.returncode == 3
        assert agents.read_text(encoding="utf-8") == drifted

    forced = _run_installer(workspace, "reinstall", "--force")
    assert forced.returncode == 0, forced.stdout + forced.stderr
    repaired = agents.read_text(encoding="utf-8")
    assert "Keep this prose." in repaired
    assert "Locally edited managed block" not in repaired


def test_merge_update_reinstall_uninstall_preserve_user_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    user_skill = workspace / ".agents" / "skills" / "user-owned" / "SKILL.md"
    user_skill.parent.mkdir(parents=True)
    user_skill.write_text("# User skill\n", encoding="utf-8")
    (workspace / "AGENTS.md").write_text("# User rules\n\nKeep this prose.\n", encoding="utf-8")
    (workspace / "kb").mkdir()
    (workspace / "kb" / "notes.md").write_text("research data\n", encoding="utf-8")
    (workspace / ".venv").mkdir()
    (workspace / ".venv" / "sentinel").write_text("runtime\n", encoding="utf-8")

    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr
    merged = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert "Keep this prose." in merged
    assert merged.count(BEGIN_MARKER) == 1
    assert merged.count(END_MARKER) == 1
    assert user_skill.read_text(encoding="utf-8") == "# User skill\n"

    update = _run_installer(workspace, "update")
    assert update.returncode == 0, update.stdout + update.stderr
    assert "Keep this prose." in (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert user_skill.is_file()

    managed_file = workspace / ".agents" / "VERSION"
    managed_file.write_text("locally damaged\n", encoding="utf-8")
    reinstall = _run_installer(workspace, "reinstall")
    assert reinstall.returncode == 0, reinstall.stdout + reinstall.stderr
    assert managed_file.read_text(encoding="utf-8") != "locally damaged\n"
    assert "Keep this prose." in (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert user_skill.is_file()
    assert (workspace / "kb" / "notes.md").is_file()
    assert (workspace / ".venv" / "sentinel").is_file()

    uninstall = _run_installer(workspace, "uninstall")
    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert not (workspace / ".agents" / ".install-manifest.json").exists()
    assert not (workspace / ".agents" / "VERSION").exists()
    assert user_skill.read_text(encoding="utf-8") == "# User skill\n"
    agents_text = (workspace / "AGENTS.md").read_text(encoding="utf-8")
    assert "Keep this prose." in agents_text
    assert BEGIN_MARKER not in agents_text
    assert END_MARKER not in agents_text
    assert (workspace / "kb" / "notes.md").read_text(encoding="utf-8") == "research data\n"
    assert (workspace / ".venv" / "sentinel").read_text(encoding="utf-8") == "runtime\n"


def test_reviewed_uninstall_plan_preserves_runtime_and_kb_lifecycle(tmp_path: Path) -> None:
    workspace = tmp_path / "reviewed-uninstall-workspace"
    workspace.mkdir()
    home = tmp_path / "reviewed-uninstall-home"
    home.mkdir()
    env = {**_installer_env(), "HOME": str(home)}
    installed = subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "install",
            "--project",
            str(workspace),
            "--codex",
            "--yes",
        ],
        cwd=_project_root(),
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    (workspace / "kb").mkdir()
    (workspace / "kb/user.md").write_text("research data\n", encoding="utf-8")
    (workspace / ".venv").mkdir()
    (workspace / ".venv/sentinel").write_text("runtime\n", encoding="utf-8")
    plan_path = tmp_path / "reviewed-uninstall.json"
    planned = subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "uninstall",
            "--agent-plan-json",
            str(plan_path),
            "--project",
            str(workspace),
            "--yes",
        ],
        cwd=_project_root(),
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )
    assert planned.returncode == 0, planned.stdout + planned.stderr
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["conditional_runtime_changes"] == []

    contract = plan["apply_contract"]
    argv = list(contract["argv"])
    byte_index = argv.index("--expected-plan-byte-sha256")
    assert argv[byte_index + 1] == PLAN_BYTE_SHA256_PLACEHOLDER
    argv[byte_index + 1] = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    applied = subprocess.run(
        [contract["executable"], *argv],
        cwd=_project_root(),
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )

    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert not (workspace / ".agents/.install-manifest.json").exists()
    assert (workspace / "kb/user.md").read_text(encoding="utf-8") == "research data\n"
    assert (workspace / ".venv/sentinel").read_text(encoding="utf-8") == "runtime\n"
    assert not any(home.iterdir())


def test_clean_uninstall_removes_all_managed_files(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr
    manifest = json.loads((workspace / ".agents" / ".install-manifest.json").read_text(encoding="utf-8"))
    cache_dir = workspace / ".agents" / "lib" / "research" / "__pycache__"
    cache_dir.mkdir(exist_ok=True)
    core_source = workspace / ".agents" / "lib" / "research" / "core.py"
    core_cache = cache_dir / Path(importlib.util.cache_from_source(str(core_source))).name
    core_cache.write_bytes(b"generated bytecode\n")

    uninstall = _run_installer(workspace, "uninstall")

    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert all(not (workspace / rel).exists() for rel in manifest["files"] if rel != "AGENTS.md")
    assert not (workspace / ".agents" / ".install-manifest.json").exists()
    assert not (workspace / ".agents").exists()
    assert not (workspace / "AGENTS.md").exists()


def test_uninstall_preserves_drifted_and_retyped_managed_paths(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr

    drifted = workspace / ".agents" / "VERSION"
    drifted.write_text("user-owned after local edit\n", encoding="utf-8")

    retyped = workspace / ".agents" / "LICENSE"
    retyped.unlink()
    retyped.mkdir()
    (retyped / "nested-empty-directory").mkdir()

    external = tmp_path / "external-agents.md"
    external.write_text("external target\n", encoding="utf-8")
    linked = workspace / ".agents" / "AGENTS.md"
    linked.unlink()
    linked.symlink_to(external)

    cache_dir = workspace / ".agents" / "lib" / "research" / "__pycache__"
    cache_dir.mkdir(exist_ok=True)
    core_source = workspace / ".agents" / "lib" / "research" / "core.py"
    managed_cache = cache_dir / Path(importlib.util.cache_from_source(str(core_source))).name
    managed_cache.write_bytes(b"generated bytecode\n")
    user_cache = cache_dir / "user_extension.cpython-test.pyc"
    user_cache.write_bytes(b"user-owned cache\n")

    uninstall = _run_installer(workspace, "uninstall")

    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert drifted.read_text(encoding="utf-8") == "user-owned after local edit\n"
    assert retyped.is_dir()
    assert (retyped / "nested-empty-directory").is_dir()
    assert linked.is_symlink()
    assert linked.readlink() == external
    assert external.read_text(encoding="utf-8") == "external target\n"
    assert not managed_cache.exists()
    assert user_cache.read_bytes() == b"user-owned cache\n"
    assert not (workspace / ".agents" / ".install-manifest.json").exists()
    assert not (workspace / ".agents" / "skills" / "kb-cli" / "SKILL.md").exists()
    _assert_public_preservation_warning(uninstall)


def test_direct_uninstall_rejects_linked_agents_root_without_touching_target(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr

    external_agents = tmp_path / "external-agents"
    shutil.move(str(workspace / ".agents"), external_agents)
    (workspace / ".agents").symlink_to(external_agents, target_is_directory=True)
    external_manifest = external_agents / ".install-manifest.json"
    external_version = external_agents / "VERSION"
    manifest_before = external_manifest.read_bytes()
    version_before = external_version.read_bytes()

    result = subprocess.run(
        [
            sys.executable,
            str(_project_root() / "install-lib" / "ws_sync.py"),
            "uninstall",
            "--repo",
            str(_project_root()),
            "--dir",
            str(workspace),
        ],
        cwd=_project_root(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "managed .agents root is not a real directory" in result.stderr
    assert (workspace / ".agents").is_symlink()
    assert external_manifest.read_bytes() == manifest_before
    assert external_version.read_bytes() == version_before


def test_direct_uninstall_rejects_linked_manifest_without_touching_target(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr

    manifest = workspace / ".agents" / ".install-manifest.json"
    external_manifest = tmp_path / "external-manifest.json"
    shutil.move(str(manifest), external_manifest)
    manifest.symlink_to(external_manifest)
    manifest_before = external_manifest.read_bytes()
    version = workspace / ".agents" / "VERSION"
    version_before = version.read_bytes()

    result = subprocess.run(
        [
            sys.executable,
            str(_project_root() / "install-lib" / "ws_sync.py"),
            "uninstall",
            "--repo",
            str(_project_root()),
            "--dir",
            str(workspace),
        ],
        cwd=_project_root(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "manifest is not a regular file" in result.stderr
    assert manifest.is_symlink()
    assert external_manifest.read_bytes() == manifest_before
    assert version.read_bytes() == version_before


def test_uninstall_preserves_nonstandard_same_prefix_bytecode_name(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr

    core_source = workspace / ".agents" / "lib" / "research" / "core.py"
    cache_dir = core_source.parent / "__pycache__"
    cache_dir.mkdir(exist_ok=True)
    standard_cache = cache_dir / Path(importlib.util.cache_from_source(str(core_source))).name
    standard_cache.write_bytes(b"generated bytecode\n")
    user_cache = standard_cache.parent / "core.user-owned.pyc"
    user_cache.write_bytes(b"user-owned cache-shaped file\n")

    uninstall = _run_installer(workspace, "uninstall")

    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert not standard_cache.exists()
    assert user_cache.read_bytes() == b"user-owned cache-shaped file\n"
    assert not (workspace / ".agents" / ".install-manifest.json").exists()


def test_uninstall_removes_cross_abi_cpython_caches_but_preserves_changed_types(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr

    core_source = workspace / ".agents" / "lib" / "research" / "core.py"
    cache_dir = core_source.parent / "__pycache__"
    cache_dir.mkdir(exist_ok=True)
    other_abi = cache_dir / "core.cpython-999.pyc"
    other_abi.write_bytes(b"other abi\n")
    other_abi_optimized = cache_dir / "core.cpython-999.opt-1.pyc"
    other_abi_optimized.write_bytes(b"other abi optimized\n")
    user_cache = cache_dir / "core.user-owned.pyc"
    user_cache.write_bytes(b"user cache\n")
    external = tmp_path / "external-cache"
    external.write_bytes(b"external\n")
    linked_cache = cache_dir / "core.cpython-998.pyc"
    linked_cache.symlink_to(external)
    retyped_cache = cache_dir / "core.cpython-997.opt-2.pyc"
    retyped_cache.mkdir()

    uninstall = _run_installer(workspace, "uninstall")

    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert not other_abi.exists()
    assert not other_abi_optimized.exists()
    assert user_cache.read_bytes() == b"user cache\n"
    assert linked_cache.is_symlink()
    assert linked_cache.readlink() == external
    assert external.read_bytes() == b"external\n"
    assert retyped_cache.is_dir()
    _assert_public_preservation_warning(uninstall)


def test_uninstall_preserves_whole_agents_file_when_managed_block_drifts(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agents_path = workspace / "AGENTS.md"
    agents_path.write_text("# User rules\n\nKeep this prose.\n", encoding="utf-8")
    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr
    manifest = json.loads((workspace / ".agents" / ".install-manifest.json").read_text(encoding="utf-8"))

    installed = agents_path.read_text(encoding="utf-8")
    drifted = installed.replace(
        "<!-- Managed by workspace-oss. Content outside this block is user-owned. -->",
        "<!-- Locally edited managed block. -->",
        1,
    )
    assert drifted != installed
    agents_path.write_text(drifted, encoding="utf-8")

    uninstall = _run_installer(workspace, "uninstall")

    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert agents_path.read_text(encoding="utf-8") == drifted
    assert BEGIN_MARKER in drifted
    assert END_MARKER in drifted
    _assert_public_preservation_warning(uninstall)
    assert not (workspace / ".agents" / ".install-manifest.json").exists()
    assert all(not (workspace / rel).exists() for rel in manifest["files"] if rel != "AGENTS.md")


def test_uninstall_preserves_whole_agents_file_when_managed_marker_changes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agents_path = workspace / "AGENTS.md"
    agents_path.write_text("# User rules\n", encoding="utf-8")
    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr

    installed = agents_path.read_text(encoding="utf-8")
    drifted = installed.replace(END_MARKER, "# <<< locally edited marker <<<", 1)
    assert drifted != installed
    agents_path.write_text(drifted, encoding="utf-8")

    uninstall = _run_installer(workspace, "uninstall")

    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert agents_path.read_text(encoding="utf-8") == drifted
    _assert_public_preservation_warning(uninstall)
    assert not (workspace / ".agents" / ".install-manifest.json").exists()


def test_uninstall_preserves_whole_agents_file_when_it_is_not_utf8(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    agents_path = workspace / "AGENTS.md"
    install = _run_installer(workspace, "install", "--codex")
    assert install.returncode == 0, install.stdout + install.stderr

    installed = agents_path.read_bytes()
    drifted = installed.replace(BEGIN_MARKER.encode(), BEGIN_MARKER.encode() + b"\xff", 1)
    assert drifted != installed
    agents_path.write_bytes(drifted)

    uninstall = _run_installer(workspace, "uninstall")

    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert agents_path.read_bytes() == drifted
    _assert_public_preservation_warning(uninstall)
    assert not (workspace / ".agents" / ".install-manifest.json").exists()


def test_ambiguous_cwd_refuses_without_writing(tmp_path: Path) -> None:
    repo_manifest = _project_root() / ".agents" / ".install-manifest.json"
    assert not repo_manifest.exists()

    result = subprocess.run(
        ["bash", str(_project_root() / "install.sh"), "update", "--yes"],
        cwd=tmp_path,
        env=_installer_env(),
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "当前目录不是可识别的已安装工作区" in result.stderr
    assert not any(tmp_path.iterdir())
    assert not repo_manifest.exists()


def test_fresh_transaction_rolls_back_all_managed_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    ws_sync = _load_ws_sync()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    writes = {
        ".agents/first.txt": (b"first\n", 0o644),
        ".agents/second.txt": (b"second\n", 0o644),
        "AGENTS.md": (b"managed\n", 0o644),
    }
    manifest = {
        "schema": 1,
        "install_name": "workspace-oss",
        "install_mode": "copy-project",
        "files": {rel: "0" * 64 for rel in writes},
    }
    real_replace = ws_sync.os.replace

    def fail_mid_commit(source: Path, destination: Path) -> None:
        if Path(destination).name == "second.txt":
            raise OSError("injected commit failure")
        real_replace(source, destination)

    monkeypatch.setattr(ws_sync.os, "replace", fail_mid_commit)
    with pytest.raises(OSError, match="injected commit failure"):
        ws_sync.transactional_apply(workspace, writes, [], manifest, dry_run=False)

    assert not (workspace / ".agents").exists()
    assert not (workspace / "AGENTS.md").exists()


@pytest.mark.parametrize("replacement_kind", ["atomic-replace", "in-place"])
def test_transaction_rejects_manifest_changed_after_planning_without_managed_writes(
    tmp_path: Path,
    replacement_kind: str,
) -> None:
    ws_sync = _load_ws_sync()
    workspace = tmp_path / "workspace"
    managed = workspace / ".agents" / "managed.txt"
    managed.parent.mkdir(parents=True)
    managed.write_bytes(b"before\n")
    manifest_path = workspace / ".agents" / ".install-manifest.json"
    payload = {
        "schema": 1,
        "install_name": "workspace-oss",
        "install_mode": "copy-project",
        "files": {".agents/managed.txt": hashlib.sha256(b"before\n").hexdigest()},
        "marker": "planned",
    }
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    snapshot = ws_sync.load_manifest_snapshot(workspace)
    assert snapshot is not None

    payload["marker"] = "concurrent-writer"
    replacement = (json.dumps(payload) + "\n").encode("utf-8")
    if replacement_kind == "atomic-replace":
        temporary = manifest_path.with_suffix(".replacement")
        temporary.write_bytes(replacement)
        os.replace(temporary, manifest_path)
    else:
        manifest_path.write_bytes(replacement)
    concurrent_manifest = manifest_path.read_bytes()

    with pytest.raises(ws_sync.SyncError, match="changed after planning"):
        ws_sync.transactional_apply(
            workspace,
            {".agents/managed.txt": (b"after\n", 0o644)},
            [],
            {**payload, "files": {".agents/managed.txt": hashlib.sha256(b"after\n").hexdigest()}},
            dry_run=False,
            expected_manifest=snapshot,
        )

    assert managed.read_bytes() == b"before\n"
    assert manifest_path.read_bytes() == concurrent_manifest
    assert not list((workspace / ".agents").glob(".workspace-oss-stage-*"))


def test_noop_update_revalidates_manifest_under_lease_before_reporting_clean(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace-noop-race"
    workspace.mkdir()
    installed = _run_installer(workspace, "install", "--codex")
    assert installed.returncode == 0, installed.stdout + installed.stderr
    ws_sync = _load_ws_sync()
    manifest_path = workspace / ".agents" / ".install-manifest.json"
    before = manifest_path.read_bytes()
    inode_before = manifest_path.stat().st_ino
    payload = json.loads(before)
    version = workspace / ".agents" / "VERSION"
    version_before = version.read_bytes()
    real_source_items = ws_sync.source_items

    def raced_source_items(repo: Path, source: Path | None, *, allow_snapshot: bool = False):
        items = real_source_items(repo, source, allow_snapshot=allow_snapshot)
        replacement = manifest_path.with_name(".same-manifest-new-inode")
        replacement.write_bytes(before)
        os.replace(replacement, manifest_path)
        return items

    monkeypatch.setattr(ws_sync, "source_items", raced_source_items)
    args = SimpleNamespace(
        repo=str(_project_root()),
        dir=str(workspace),
        source="",
        source_commit=str(payload.get("source_commit") or ""),
        source_origin=str(payload.get("source_origin") or ""),
        source_checkout=str(payload.get("source_checkout") or ""),
        source_branch=str(payload.get("source_branch") or ""),
        source_strategy=str(payload.get("source_strategy") or ""),
        operation_time="",
        force=False,
        dry_run=False,
        allow_snapshot_source=False,
        expected_manifest_state="",
    )

    with pytest.raises(ws_sync.SyncError, match="changed after planning"):
        ws_sync.update(args)

    assert manifest_path.read_bytes() == before
    assert manifest_path.stat().st_ino != inode_before
    assert version.read_bytes() == version_before


@pytest.mark.parametrize("leaf_kind", ["fifo", "symlink"])
def test_update_plan_rejects_nonregular_manifest_without_following_or_blocking(
    tmp_path: Path,
    leaf_kind: str,
) -> None:
    workspace = tmp_path / "workspace"
    manifest = workspace / ".agents" / ".install-manifest.json"
    manifest.parent.mkdir(parents=True)
    victim = tmp_path / "victim.json"
    victim.write_text('{"keep": true}\n', encoding="utf-8")
    if leaf_kind == "fifo":
        os.mkfifo(manifest)
    else:
        manifest.symlink_to(victim)

    result = subprocess.run(
        [
            sys.executable,
            str(_project_root() / "install-lib" / "ws_sync.py"),
            "update",
            "--repo",
            str(_project_root()),
            "--dir",
            str(workspace),
        ],
        cwd=_project_root(),
        text=True,
        capture_output=True,
        timeout=3,
        check=False,
    )

    assert result.returncode == 1
    assert "manifest is not a regular file" in result.stderr
    if leaf_kind == "fifo":
        assert stat.S_ISFIFO(manifest.lstat().st_mode)
    else:
        assert manifest.is_symlink()
        assert victim.read_text(encoding="utf-8") == '{"keep": true}\n'


def _write_concurrency_workspace(tmp_path: Path) -> tuple[Path, Path, bytes]:
    workspace = tmp_path / "concurrent-workspace"
    version = workspace / ".agents" / "VERSION"
    version.parent.mkdir(parents=True)
    version.write_bytes(b"0.2.0\n")
    manifest = workspace / ".agents" / ".install-manifest.json"
    payload = {
        "schema": 1,
        "install_name": "workspace-oss",
        "install_mode": "copy-project",
        "source_origin": "ssh://example.test/team/original.git",
        "source_checkout": "",
        "source_repo": "",
        "source_branch": "release/original",
        "source_strategy": "remote-branch",
        "source_commit": "old",
        "files": {".agents/VERSION": hashlib.sha256(version.read_bytes()).hexdigest()},
        "marker": "before",
    }
    content = (json.dumps(payload, sort_keys=True) + "\n").encode("utf-8")
    manifest.write_bytes(content)
    return workspace, manifest, content


def test_rebind_lease_serializes_installer_and_stale_plan_cannot_overwrite(tmp_path: Path) -> None:
    workspace, manifest, initial = _write_concurrency_workspace(tmp_path)
    project = str(_project_root())
    context = multiprocessing.get_context("fork")
    planned = context.Event()
    start_installer = context.Event()
    installer_attempted = context.Event()
    rebind_paused = context.Event()
    release_rebind = context.Event()
    installer_queue = context.Queue()
    rebind_queue = context.Queue()
    installer_process = context.Process(
        target=_installer_transaction_worker,
        args=(
            project,
            str(workspace),
            planned,
            start_installer,
            installer_attempted,
            None,
            None,
            installer_queue,
        ),
    )
    installer_process.start()
    assert planned.wait(5)
    rebind_process = context.Process(
        target=_rebind_worker,
        args=(
            project,
            str(workspace),
            hashlib.sha256(initial).hexdigest(),
            rebind_paused,
            release_rebind,
            None,
            rebind_queue,
        ),
    )
    rebind_process.start()
    assert rebind_paused.wait(5)
    start_installer.set()
    assert installer_attempted.wait(5)
    release_rebind.set()
    rebind_process.join(10)
    installer_process.join(10)

    assert rebind_process.exitcode == 0
    assert installer_process.exitcode == 0
    assert rebind_queue.get(timeout=1)[0] == "ok"
    installer_result = installer_queue.get(timeout=1)
    assert installer_result[0] == "error"
    assert "changed after planning" in installer_result[1]
    final = json.loads(manifest.read_text(encoding="utf-8"))
    assert final["source_origin"] == "ssh://example.test/team/rebound.git"
    assert final["source_branch"] == "release/r17"
    assert final["marker"] == "before"
    assert (workspace / ".agents" / "VERSION").read_bytes() == b"0.2.0\n"


def test_installer_lease_serializes_rebind_and_stale_rebind_cannot_overwrite(tmp_path: Path) -> None:
    workspace, manifest, initial = _write_concurrency_workspace(tmp_path)
    project = str(_project_root())
    context = multiprocessing.get_context("fork")
    planned = context.Event()
    start_installer = context.Event()
    installer_validated = context.Event()
    release_installer = context.Event()
    rebind_attempted = context.Event()
    installer_queue = context.Queue()
    rebind_queue = context.Queue()
    installer_process = context.Process(
        target=_installer_transaction_worker,
        args=(
            project,
            str(workspace),
            planned,
            start_installer,
            None,
            installer_validated,
            release_installer,
            installer_queue,
        ),
    )
    installer_process.start()
    assert planned.wait(5)
    start_installer.set()
    assert installer_validated.wait(5)
    rebind_process = context.Process(
        target=_rebind_worker,
        args=(
            project,
            str(workspace),
            hashlib.sha256(initial).hexdigest(),
            None,
            None,
            rebind_attempted,
            rebind_queue,
        ),
    )
    rebind_process.start()
    assert rebind_attempted.wait(5)
    release_installer.set()
    installer_process.join(10)
    rebind_process.join(10)

    assert installer_process.exitcode == 0
    assert rebind_process.exitcode == 0
    assert installer_queue.get(timeout=1) == ("ok", "installer")
    assert rebind_queue.get(timeout=1) == ("error", "stale-manifest")
    final = json.loads(manifest.read_text(encoding="utf-8"))
    assert final["marker"] == "installer-won"
    assert final["source_origin"] == "ssh://example.test/team/original.git"
    assert (workspace / ".agents" / "VERSION").read_bytes() == b"0.3.0\n"


def test_rebind_and_uninstall_share_root_lease_without_manifest_resurrection(tmp_path: Path) -> None:
    workspace, manifest, initial = _write_concurrency_workspace(tmp_path)
    project = str(_project_root())
    context = multiprocessing.get_context("fork")
    rebind_paused = context.Event()
    release_rebind = context.Event()
    uninstall_attempted = context.Event()
    rebind_queue = context.Queue()
    uninstall_queue = context.Queue()
    rebind_process = context.Process(
        target=_rebind_worker,
        args=(
            project,
            str(workspace),
            hashlib.sha256(initial).hexdigest(),
            rebind_paused,
            release_rebind,
            None,
            rebind_queue,
        ),
    )
    rebind_process.start()
    assert rebind_paused.wait(5)
    uninstall_process = context.Process(
        target=_uninstall_worker,
        args=(project, str(workspace), uninstall_attempted, None, None, uninstall_queue),
    )
    uninstall_process.start()
    assert uninstall_attempted.wait(5)
    release_rebind.set()
    rebind_process.join(10)
    uninstall_process.join(10)

    assert rebind_process.exitcode == 0
    assert uninstall_process.exitcode == 0
    assert rebind_queue.get(timeout=1)[0] == "ok"
    assert uninstall_queue.get(timeout=1) == ("ok", 0)
    assert not manifest.exists()
    assert not (workspace / ".agents" / "VERSION").exists()


def test_uninstall_lease_finishes_before_waiting_rebind_without_manifest_resurrection(tmp_path: Path) -> None:
    workspace, manifest, initial = _write_concurrency_workspace(tmp_path)
    project = str(_project_root())
    context = multiprocessing.get_context("fork")
    uninstall_attempted = context.Event()
    uninstall_paused = context.Event()
    release_uninstall = context.Event()
    rebind_attempted = context.Event()
    uninstall_queue = context.Queue()
    rebind_queue = context.Queue()
    uninstall_process = context.Process(
        target=_uninstall_worker,
        args=(
            project,
            str(workspace),
            uninstall_attempted,
            uninstall_paused,
            release_uninstall,
            uninstall_queue,
        ),
    )
    uninstall_process.start()
    assert uninstall_attempted.wait(5)
    assert uninstall_paused.wait(5)
    rebind_process = context.Process(
        target=_rebind_worker,
        args=(
            project,
            str(workspace),
            hashlib.sha256(initial).hexdigest(),
            None,
            None,
            rebind_attempted,
            rebind_queue,
        ),
    )
    rebind_process.start()
    assert rebind_attempted.wait(5)
    release_uninstall.set()
    uninstall_process.join(10)
    rebind_process.join(10)

    assert uninstall_process.exitcode == 0
    assert rebind_process.exitcode == 0
    assert uninstall_queue.get(timeout=1) == ("ok", 0)
    rebind_result = rebind_queue.get(timeout=1)
    assert rebind_result[0] == "error"
    assert rebind_result[1] in {"unsafe-manifest-path", "unsafe-manifest-ancestor", "unsafe-manifest-leaf"}
    assert not manifest.exists()
    assert not (workspace / ".agents").exists()


def test_two_fresh_installs_and_symlink_alias_share_one_expected_absent_boundary(tmp_path: Path) -> None:
    workspace = tmp_path / "fresh-workspace"
    workspace.mkdir()
    alias = tmp_path / "fresh-workspace-alias"
    alias.symlink_to(workspace, target_is_directory=True)
    context = multiprocessing.get_context("fork")
    first_planned = context.Event()
    second_planned = context.Event()
    start_first = context.Event()
    start_second = context.Event()
    first_validated = context.Event()
    release_first = context.Event()
    second_attempted = context.Event()
    first_queue = context.Queue()
    second_queue = context.Queue()
    first = context.Process(
        target=_fresh_transaction_worker,
        args=(
            str(workspace),
            "first",
            first_planned,
            start_first,
            None,
            first_validated,
            release_first,
            first_queue,
        ),
    )
    second = context.Process(
        target=_fresh_transaction_worker,
        args=(
            str(alias),
            "second",
            second_planned,
            start_second,
            second_attempted,
            None,
            None,
            second_queue,
        ),
    )
    first.start()
    second.start()
    assert first_planned.wait(5)
    assert second_planned.wait(5)
    start_first.set()
    assert first_validated.wait(5)
    start_second.set()
    assert second_attempted.wait(5)
    release_first.set()
    first.join(10)
    second.join(10)

    assert first.exitcode == 0
    assert second.exitcode == 0
    assert first_queue.get(timeout=1) == ("ok", "first")
    second_result = second_queue.get(timeout=1)
    assert second_result[0] == "error"
    assert "changed after planning" in second_result[1]
    manifest = json.loads((workspace / ".agents" / ".install-manifest.json").read_text(encoding="utf-8"))
    assert manifest["marker"] == "first"
    assert (workspace / ".agents" / "VERSION").read_bytes() == b"first\n"


@pytest.mark.parametrize(
    "fault",
    [
        "staged-payload-fsync",
        "staged-manifest-fsync",
        "payload-replace",
        "payload-parent-fsync",
        "manifest-replace",
        "manifest-parent-fsync",
    ],
)
def test_transaction_fault_matrix_rolls_back_and_releases_lease(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fault: str,
) -> None:
    ws_sync = _load_ws_sync()
    workspace, manifest_path, manifest_before = _write_concurrency_workspace(tmp_path)
    version = workspace / ".agents" / "VERSION"
    snapshot = ws_sync.load_manifest_snapshot(workspace)
    assert snapshot is not None
    replacement = dict(snapshot.payload)
    replacement["marker"] = "after"
    replacement["files"] = {".agents/VERSION": hashlib.sha256(b"0.3.0\n").hexdigest()}

    if fault.startswith("staged-"):
        real_fsync = ws_sync.os.fsync
        calls = 0
        failure_call = 1 if fault == "staged-payload-fsync" else 3

        def failed_fsync(descriptor: int) -> None:
            nonlocal calls
            calls += 1
            if calls == failure_call:
                raise OSError(f"injected {fault}")
            real_fsync(descriptor)

        monkeypatch.setattr(ws_sync.os, "fsync", failed_fsync)
    elif fault.endswith("replace"):
        real_replace = ws_sync.os.replace
        replace_failed = False

        def failed_replace(source: object, destination: object, *args: object, **kwargs: object) -> None:
            nonlocal replace_failed
            target = Path(destination)
            should_fail = (
                (fault == "payload-replace" and target == version)
                or (fault == "manifest-replace" and target == manifest_path)
            )
            if should_fail and not replace_failed:
                replace_failed = True
                raise OSError(f"injected {fault}")
            real_replace(source, destination, *args, **kwargs)

        monkeypatch.setattr(ws_sync.os, "replace", failed_replace)
    else:
        real_fsync_directory = ws_sync._fsync_directory
        agents_calls = 0
        failure_call = 1 if fault == "payload-parent-fsync" else 2

        def failed_directory(path: Path) -> None:
            nonlocal agents_calls
            if Path(path) == workspace / ".agents":
                agents_calls += 1
                if agents_calls == failure_call:
                    raise OSError(f"injected {fault}")
            real_fsync_directory(path)

        monkeypatch.setattr(ws_sync, "_fsync_directory", failed_directory)

    with pytest.raises(OSError, match=fault):
        ws_sync.transactional_apply(
            workspace,
            {".agents/VERSION": (b"0.3.0\n", 0o644)},
            [],
            replacement,
            dry_run=False,
            expected_manifest=snapshot,
        )

    assert version.read_bytes() == b"0.2.0\n"
    assert manifest_path.read_bytes() == manifest_before
    assert not list((workspace / ".agents").glob(".workspace-oss-stage-*"))
    retry_snapshot = ws_sync.load_manifest_snapshot(workspace)
    assert retry_snapshot is not None
    assert ws_sync.transactional_apply(
        workspace,
        {".agents/VERSION": (b"0.3.0\n", 0o644)},
        [],
        replacement,
        dry_run=False,
        expected_manifest=retry_snapshot,
    )
    assert version.read_bytes() == b"0.3.0\n"
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["marker"] == "after"


@pytest.mark.parametrize("fault", ["manifest-delete", "manifest-delete-fsync"])
def test_uninstall_manifest_fault_rolls_back_payload_before_releasing_lease(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    fault: str,
) -> None:
    ws_sync = _load_ws_sync()
    workspace, manifest_path, manifest_before = _write_concurrency_workspace(tmp_path)
    version = workspace / ".agents" / "VERSION"
    snapshot = ws_sync.load_manifest_snapshot(workspace)
    assert snapshot is not None
    if fault == "manifest-delete":
        real_unlink = ws_sync.Path.unlink
        failed = False

        def failed_unlink(path: Path, *args: object, **kwargs: object) -> None:
            nonlocal failed
            if path == manifest_path and not failed:
                failed = True
                raise OSError("injected manifest-delete")
            real_unlink(path, *args, **kwargs)

        monkeypatch.setattr(ws_sync.Path, "unlink", failed_unlink)
    else:
        real_fsync_directory = ws_sync._fsync_directory
        agents_calls = 0

        def failed_directory(path: Path) -> None:
            nonlocal agents_calls
            if Path(path) == workspace / ".agents":
                agents_calls += 1
                if agents_calls == 2:
                    raise OSError("injected manifest-delete-fsync")
            real_fsync_directory(path)

        monkeypatch.setattr(ws_sync, "_fsync_directory", failed_directory)

    with pytest.raises(OSError, match=fault):
        ws_sync.transactional_apply(
            workspace,
            {},
            [".agents/VERSION"],
            None,
            dry_run=False,
            delete_manifest=True,
            expected_manifest=snapshot,
        )

    assert version.read_bytes() == b"0.2.0\n"
    assert manifest_path.read_bytes() == manifest_before
    assert not list((workspace / ".agents").glob(".workspace-oss-stage-*"))
    retry_snapshot = ws_sync.load_manifest_snapshot(workspace)
    assert retry_snapshot is not None
    assert ws_sync.transactional_apply(
        workspace,
        {},
        [".agents/VERSION"],
        None,
        dry_run=False,
        delete_manifest=True,
        expected_manifest=retry_snapshot,
    )
    assert not version.exists()
    assert not manifest_path.exists()


def test_incomplete_rollback_preserves_stage_and_original_backup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ws_sync = _load_ws_sync()
    workspace, manifest_path, manifest_before = _write_concurrency_workspace(tmp_path)
    version = workspace / ".agents" / "VERSION"
    snapshot = ws_sync.load_manifest_snapshot(workspace)
    assert snapshot is not None
    replacement = dict(snapshot.payload)
    replacement["marker"] = "after"
    replacement["files"] = {".agents/VERSION": hashlib.sha256(b"0.3.0\n").hexdigest()}
    real_fsync_directory = ws_sync._fsync_directory
    agents_calls = 0

    def failed_manifest_fsync(path: Path) -> None:
        nonlocal agents_calls
        if Path(path) == workspace / ".agents":
            agents_calls += 1
            if agents_calls == 2:
                raise OSError("injected manifest-parent-fsync")
        real_fsync_directory(path)

    real_restore = ws_sync._restore_backup

    def failed_payload_restore(backup: Path, destination: Path) -> None:
        if destination == version:
            raise OSError("injected payload rollback failure")
        real_restore(backup, destination)

    monkeypatch.setattr(ws_sync, "_fsync_directory", failed_manifest_fsync)
    monkeypatch.setattr(ws_sync, "_restore_backup", failed_payload_restore)

    with pytest.raises(OSError, match="manifest-parent-fsync"):
        ws_sync.transactional_apply(
            workspace,
            {".agents/VERSION": (b"0.3.0\n", 0o644)},
            [],
            replacement,
            dry_run=False,
            expected_manifest=snapshot,
        )

    assert manifest_path.read_bytes() == manifest_before
    assert version.read_bytes() == b"0.3.0\n"
    stages = list(workspace.glob(".workspace-oss-stage-*"))
    assert len(stages) == 1
    backup_bytes = [path.read_bytes() for path in (stages[0] / "backups").iterdir() if path.is_file()]
    assert b"0.2.0\n" in backup_bytes


def test_uninstall_root_fsync_failure_releases_root_lease_after_manifest_last(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ws_sync = _load_ws_sync()
    workspace, manifest_path, manifest_before = _write_concurrency_workspace(tmp_path)
    version = workspace / ".agents" / "VERSION"
    version_before = version.read_bytes()
    root_status = workspace.stat()
    real_fsync = ws_sync.os.fsync
    failed = False

    def failed_root_fsync(descriptor: int) -> None:
        nonlocal failed
        current = os.fstat(descriptor)
        if not failed and current.st_dev == root_status.st_dev and current.st_ino == root_status.st_ino:
            failed = True
            raise OSError("injected root-fsync")
        real_fsync(descriptor)

    monkeypatch.setattr(ws_sync.os, "fsync", failed_root_fsync)
    args = SimpleNamespace(
        repo=str(_project_root()),
        dir=str(workspace),
        dry_run=False,
        expected_manifest_state="",
    )

    with pytest.raises(OSError, match="root-fsync"):
        ws_sync.uninstall(args)

    assert manifest_path.read_bytes() == manifest_before
    assert version.read_bytes() == version_before
    assert (workspace / ".agents").is_dir()
    with ws_sync.workspace_lease(workspace):
        pass

    assert ws_sync.uninstall(args) == 0
    assert not manifest_path.exists()
    assert not (workspace / ".agents").exists()


def test_stale_manifest_blocks_payload_and_project_claude_as_one_transaction(tmp_path: Path) -> None:
    ws_sync = _load_ws_sync()
    workspace, manifest_path, manifest_before = _write_concurrency_workspace(tmp_path)
    version = workspace / ".agents" / "VERSION"
    version_before = version.read_bytes()
    snapshot = ws_sync.load_manifest_snapshot(workspace)
    assert snapshot is not None
    replacement_path = manifest_path.with_name(".same-bytes-new-inode")
    replacement_path.write_bytes(manifest_before)
    os.replace(replacement_path, manifest_path)
    replacement_manifest = dict(snapshot.payload)
    replacement_manifest["marker"] = "must-not-commit"

    with pytest.raises(ws_sync.SyncError, match="changed after planning"):
        ws_sync.transactional_apply(
            workspace,
            {".agents/VERSION": (b"9.9.9\n", 0o644)},
            [],
            replacement_manifest,
            dry_run=False,
            expected_manifest=snapshot,
            project_claude=(True, False, _project_root() / ".agents" / "skills"),
        )

    assert manifest_path.read_bytes() == manifest_before
    assert version.read_bytes() == version_before
    assert not (workspace / "CLAUDE.md").exists()
    assert not (workspace / ".claude").exists()
    assert not list(workspace.glob(".workspace-oss-stage-*"))


def test_uninstall_root_fsync_failure_restores_project_claude_and_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    ws_sync = _load_ws_sync()
    workspace = tmp_path / "claude-root-fsync-workspace"
    workspace.mkdir()
    install_args = SimpleNamespace(
        repo=str(_project_root()),
        dir=str(workspace),
        source="",
        agents="claude",
        operation_time="2026-07-25T00:00:00Z",
        expected_manifest_state="",
        source_commit="test-commit",
        source_origin="local",
        source_checkout=str(_project_root()),
        source_branch="",
        source_strategy="local-checkout",
        force=False,
        dry_run=False,
        allow_snapshot_source=False,
    )
    assert ws_sync.install(install_args) == 0
    manifest = workspace / ".agents" / ".install-manifest.json"
    version = workspace / ".agents" / "VERSION"
    agents = workspace / "AGENTS.md"
    claude = workspace / "CLAUDE.md"
    skills = workspace / ".claude" / "skills"
    before = {
        manifest: manifest.read_bytes(),
        version: version.read_bytes(),
        agents: agents.read_bytes(),
        claude: claude.read_bytes(),
    }
    root_status = workspace.stat()
    real_fsync = ws_sync.os.fsync
    failed = False

    def failed_root_fsync(descriptor: int) -> None:
        nonlocal failed
        current = os.fstat(descriptor)
        if not failed and current.st_dev == root_status.st_dev and current.st_ino == root_status.st_ino:
            failed = True
            raise OSError("injected root-fsync-with-claude")
        real_fsync(descriptor)

    monkeypatch.setattr(ws_sync.os, "fsync", failed_root_fsync)
    uninstall_args = SimpleNamespace(
        repo=str(_project_root()),
        dir=str(workspace),
        dry_run=False,
        expected_manifest_state="",
    )

    with pytest.raises(OSError, match="root-fsync-with-claude"):
        ws_sync.uninstall(uninstall_args)

    for path, content in before.items():
        assert path.read_bytes() == content
    assert skills.is_symlink()
    assert os.readlink(skills) == "../.agents/skills"
    assert not list(workspace.glob(".workspace-oss-stage-*"))

    assert ws_sync.uninstall(uninstall_args) == 0
    assert not (workspace / ".agents").exists()
    assert not claude.exists()
    assert not skills.exists() and not skills.is_symlink()
