from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

import pytest


PLAN_BYTE_SHA256_PLACEHOLDER = "COMPUTE_AFTER_REVIEW"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _environment(tmp_path: Path) -> dict[str, str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    return {
        **os.environ,
        "HOME": str(home),
        "RESEARCH_PYTHON": sys.executable,
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "NO_COLOR": "1",
    }


def _plan(workspace: Path, plan_path: Path, env: dict[str, str], *, action: str = "install") -> dict[str, object]:
    argv = ["bash", str(_project_root() / "install.sh")]
    if action != "install":
        argv.append(action)
    argv.extend(["--agent-plan-json", str(plan_path), "--project", str(workspace), "--yes"])
    if action == "install":
        argv.append("--codex")
    result = subprocess.run(
        argv,
        cwd=_project_root(),
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return json.loads(plan_path.read_text(encoding="utf-8"))


def _apply(plan: dict[str, object], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    contract = plan["apply_contract"]
    assert isinstance(contract, dict)
    argv = list(contract["argv"])
    plan_path = Path(str(contract["plan_path"]))
    byte_index = argv.index("--expected-plan-byte-sha256")
    assert argv[byte_index + 1] == PLAN_BYTE_SHA256_PLACEHOLDER
    argv[byte_index + 1] = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    return subprocess.run(
        [str(contract["executable"]), *argv],
        cwd=_project_root(),
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def _race_python_wrapper(tmp_path: Path, env: dict[str, str], *, mode: str, manifest: Path) -> dict[str, str]:
    bin_dir = tmp_path / f"python-wrapper-{mode}"
    bin_dir.mkdir()
    wrapper = bin_dir / "python3"
    wrapper.write_text(
        """#!/bin/sh
case "${1:-}" in
  */install-lib/ws_sync.py)
    if [ ! -e "$RACE_DONE" ]; then
      "$REAL_PYTHON" - "$RACE_MODE" "$RACE_MANIFEST" "$RACE_DONE" <<'PY'
import json
import os
import sys
from pathlib import Path

mode, manifest_text, done_text = sys.argv[1:]
manifest = Path(manifest_text)
done = Path(done_text)
manifest.parent.mkdir(parents=True, exist_ok=True)
if mode == "create-valid":
    payload = {
        "schema": 1,
        "install_name": "workspace-oss",
        "install_mode": "copy-project",
        "files": {},
        "marker": "concurrent-writer",
    }
    manifest.write_text(json.dumps(payload, sort_keys=True) + "\\n", encoding="utf-8")
elif mode == "replace-same":
    replacement = manifest.with_name(".concurrent-manifest-replacement")
    replacement.write_bytes(manifest.read_bytes())
    os.replace(replacement, manifest)
else:
    raise SystemExit(f"unknown race mode: {mode}")
done.write_text("done\\n", encoding="utf-8")
PY
    fi
    ;;
esac
exec "$REAL_PYTHON" "$@"
""",
        encoding="utf-8",
    )
    wrapper.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    raced = dict(env)
    raced.update(
        {
            "PATH": f"{bin_dir}{os.pathsep}{env.get('PATH', '')}",
            "REAL_PYTHON": sys.executable,
            "RACE_MODE": mode,
            "RACE_MANIFEST": str(manifest),
            "RACE_DONE": str(tmp_path / f"race-{mode}.done"),
        }
    )
    return raced


def test_agent_plan_expected_absent_survives_verify_to_ws_sync_race(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = _environment(tmp_path)
    plan = _plan(workspace, tmp_path / "fresh-plan.json", env)
    assert plan["workspace_manifest_precondition"] == {"type": "absent"}
    manifest = workspace / ".agents" / ".install-manifest.json"

    applied = _apply(
        plan,
        _race_python_wrapper(tmp_path, env, mode="create-valid", manifest=manifest),
    )

    assert applied.returncode == 1
    concurrent = json.loads(manifest.read_text(encoding="utf-8"))
    assert concurrent["marker"] == "concurrent-writer"
    assert sorted(path.relative_to(workspace).as_posix() for path in workspace.rglob("*") if path.is_file()) == [
        ".agents/.install-manifest.json"
    ]


def test_agent_plan_same_bytes_new_manifest_inode_is_stale_at_ws_sync_boundary(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = _environment(tmp_path)
    installed = subprocess.run(
        ["bash", str(_project_root() / "install.sh"), "--codex", "--project", str(workspace), "--yes"],
        cwd=_project_root(),
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    manifest = workspace / ".agents" / ".install-manifest.json"
    before = manifest.read_bytes()
    inode_before = manifest.stat().st_ino
    version = workspace / ".agents" / "VERSION"
    version_before = version.read_bytes()
    plan = _plan(workspace, tmp_path / "update-plan.json", env, action="update")
    planned_state = plan["workspace_manifest_precondition"]
    assert isinstance(planned_state, dict)
    assert planned_state["type"] == "regular"
    assert planned_state["inode"] == inode_before

    applied = _apply(
        plan,
        _race_python_wrapper(tmp_path, env, mode="replace-same", manifest=manifest),
    )

    assert applied.returncode == 1
    assert manifest.read_bytes() == before
    assert manifest.stat().st_ino != inode_before
    assert version.read_bytes() == version_before


@pytest.mark.parametrize("unsafe_kind", ["ancestor-symlink", "leaf-fifo"])
def test_manifest_plan_precondition_rejects_unsafe_path_without_following(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    install_lib = str(_project_root() / "install-lib")
    if install_lib not in sys.path:
        sys.path.insert(0, install_lib)
    import agent_plan

    workspace = tmp_path / "unsafe-workspace"
    workspace.mkdir()
    victim = tmp_path / "victim-agents"
    victim.mkdir()
    victim_manifest = victim / ".install-manifest.json"
    victim_manifest.write_text('{"victim": true}\n', encoding="utf-8")
    if unsafe_kind == "ancestor-symlink":
        (workspace / ".agents").symlink_to(victim, target_is_directory=True)
    else:
        (workspace / ".agents").mkdir()
        os.mkfifo(workspace / ".agents" / ".install-manifest.json")

    with pytest.raises(ValueError):
        agent_plan.workspace_manifest_precondition(workspace)

    assert victim_manifest.read_text(encoding="utf-8") == '{"victim": true}\n'


def test_plan_generation_uses_sync_snapshot_and_rejects_later_rebind(tmp_path: Path) -> None:
    install_lib = str(_project_root() / "install-lib")
    if install_lib not in sys.path:
        sys.path.insert(0, install_lib)
    import agent_plan

    workspace = tmp_path / "workspace-plan-cas"
    manifest = workspace / ".agents" / ".install-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text('{"schema":1,"files":{}}\n', encoding="utf-8")
    planned = agent_plan.workspace_manifest_precondition(workspace)
    original_inode = manifest.stat().st_ino
    replacement = manifest.with_name(".replacement")
    replacement.write_bytes(manifest.read_bytes())
    os.replace(replacement, manifest)
    assert manifest.stat().st_ino != original_inode

    output = tmp_path / "stale-plan.json"
    args = agent_plan.build_parser().parse_args(
        [
            "--output",
            str(output),
            "--action",
            "uninstall",
            "--scope",
            "project",
            "--workspace",
            str(workspace),
            "--home",
            str(tmp_path / "home"),
            "--source-strategy",
            "local-checkout",
            "--source-checkout",
            str(_project_root()),
            "--source-origin",
            "local",
            "--source-commit",
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=_project_root(), text=True).strip(),
            "--distributable-root",
            str(_project_root()),
            "--operation-time",
            "2026-07-25T00:00:00Z",
            "--manifest-precondition-json",
            json.dumps(planned, sort_keys=True, separators=(",", ":")),
        ]
    )

    with pytest.raises(ValueError, match="changed after sync planning"):
        agent_plan.generate_plan(args)

    assert not output.exists()


def test_plan_generation_records_exact_supplied_sync_snapshot(tmp_path: Path) -> None:
    install_lib = str(_project_root() / "install-lib")
    if install_lib not in sys.path:
        sys.path.insert(0, install_lib)
    import agent_plan

    workspace = tmp_path / "workspace-plan-exact"
    workspace.mkdir()
    planned = {"type": "absent"}
    output = tmp_path / "exact-plan.json"
    args = agent_plan.build_parser().parse_args(
        [
            "--output",
            str(output),
            "--action",
            "install",
            "--scope",
            "project",
            "--workspace",
            str(workspace),
            "--home",
            str(tmp_path / "home"),
            "--source-strategy",
            "local-checkout",
            "--source-checkout",
            str(_project_root()),
            "--source-origin",
            "local",
            "--source-commit",
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=_project_root(), text=True).strip(),
            "--distributable-root",
            str(_project_root()),
            "--operation-time",
            "2026-07-25T00:00:00Z",
            "--manifest-precondition-json",
            json.dumps(planned),
        ]
    )

    assert agent_plan.generate_plan(args) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["workspace_manifest_precondition"] == planned
