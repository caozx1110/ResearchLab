from __future__ import annotations

import errno
import hashlib
import json
import os
import pty
import re
import select
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path


PLAN_BYTE_SHA256_PLACEHOLDER = "COMPUTE_AFTER_REVIEW"


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _workspace_snapshot(root: Path) -> dict[str, tuple[str, object, int]]:
    snapshot: dict[str, tuple[str, object, int]] = {}
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        metadata = path.lstat()
        mode = stat.S_IMODE(metadata.st_mode)
        if path.is_symlink():
            snapshot[relative] = ("symlink", os.readlink(path), mode)
        elif path.is_file():
            snapshot[relative] = ("file", path.read_bytes(), mode)
        elif path.is_dir():
            snapshot[relative] = ("directory", None, mode)
        else:
            snapshot[relative] = ("special", metadata.st_mode, mode)
    return snapshot


def _run_dry_install(tmp_path: Path, *, no_managed_venv: bool = False) -> subprocess.CompletedProcess[str]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    env = {**os.environ, "RESEARCH_PYTHON": "/bin/false", "NO_COLOR": "1"}
    if no_managed_venv:
        env["RESEARCH_NO_MANAGED_VENV"] = "1"
    return subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "--dry-run",
            "--codex",
            "--project",
            str(workspace),
            "--yes",
        ],
        cwd=_project_root(),
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_agent_plan_lists_exact_targets_and_writes_nothing(tmp_path: Path) -> None:
    workspace = tmp_path / "agent-workspace"
    workspace.mkdir()
    home = tmp_path / "agent-home"
    cache = tmp_path / "agent-pycache"
    scratch = tmp_path / "agent-tmp"
    for directory in (home, cache, scratch):
        directory.mkdir()
    plan_path = tmp_path / "install-plan.json"
    result = subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "--agent-plan-json",
            str(plan_path),
            "--all",
            "--kb-on-path",
            "--project",
            str(workspace),
            "--yes",
        ],
        cwd=_project_root(),
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
    assert "[dry-run]" not in result.stdout
    assert ".agents/skills/kb-cli/scripts/kb" not in result.stdout
    assert str(workspace) not in result.stdout + result.stderr
    assert str(plan_path) not in result.stdout + result.stderr
    assert len(result.stdout.splitlines()) <= 20
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert plan["mode"] == "agent-plan"
    assert plan["zero_write_scope"] == "workspace-home-and-runtime"
    assert plan["action"] == "install"
    assert plan["scope"] == "project"
    assert plan["tools"] == ["claude", "codex"]
    assert plan["workspace"] == str(workspace.resolve())
    assert plan["source"]["strategy"] == "local-checkout"
    assert plan["source"]["checkout"] == str(_project_root())
    assert plan["source"]["commit"] == _git_output(_project_root(), "rev-parse", "HEAD")
    assert plan["source"]["origin"] == _git_output(_project_root(), "remote", "get-url", "origin")
    targets = plan["targets"]
    kb_target = next(
        item
        for item in targets
        if item["operation"] == "write" and item["path"] == str(workspace / ".agents/skills/kb-cli/scripts/kb")
    )
    assert kb_target["precondition"] == {"type": "absent"}
    assert re.fullmatch(r"[0-9a-f]{64}", kb_target["source_content_sha256"])
    assert any(item["operation"] == "write-managed-block" and item["path"] == str(workspace / "CLAUDE.md") for item in targets)
    assert all(
        re.fullmatch(r"[0-9a-f]{64}", item["source_content_sha256"])
        for item in targets
        if item["operation"] in {"copy", "overwrite", "write", "write-manifest", "write-managed-block"}
    )
    runtime = plan["conditional_runtime_changes"]
    assert len(runtime) == 1
    assert runtime[0]["path"] == str(workspace / ".venv")
    assert runtime[0]["precondition"] == {"type": "absent"}
    assert "yaml, markdownify, bs4, or the pymupdf4llm PDF backend" in runtime[0]["condition"]
    assert "intentionally not enumerated" in runtime[0]["boundary"]
    assert "preserved" in runtime[0]["cleanup"]
    tree = plan["source"]["distributable_tree"]
    assert tree["entry_count"] == len(tree["entries"])
    assert re.fullmatch(r"[0-9a-f]{64}", tree["digest"])
    assert {item["type"] for item in tree["entries"]} <= {"regular", "symlink"}
    assert all(re.fullmatch(r"[0-7]{4}", item["mode"]) for item in tree["entries"])
    assert all(
        ("byte_sha256" in item) if item["type"] == "regular" else ("target" in item)
        for item in tree["entries"]
    )
    assert plan["conflicts"] == []
    assert plan["apply_contract"]["headless"] is True
    assert plan["apply_contract"]["requires_same_source_commit"] == plan["source"]["commit"]
    assert plan["apply_contract"]["requires_plan_digest"] == plan["plan_digest"]
    assert plan["apply_contract"]["requires_plan_byte_sha256"] == PLAN_BYTE_SHA256_PLACEHOLDER
    assert plan["apply_contract"]["requires_source_tree_digest"] == tree["digest"]
    assert plan["apply_contract"]["plan_path"] == str(plan_path)
    assert "--agent-plan-json" not in plan["apply_contract"]["argv"]
    byte_index = plan["apply_contract"]["argv"].index("--expected-plan-byte-sha256")
    assert plan["apply_contract"]["argv"][byte_index + 1] == PLAN_BYTE_SHA256_PLACEHOLDER
    expected_index = plan["apply_contract"]["argv"].index("--expected-source-commit")
    assert plan["apply_contract"]["argv"][expected_index + 1] == plan["source"]["commit"]
    summary = re.search(r"预计受管目标：(\d+) 项", result.stdout)
    assert summary is not None
    assert int(summary.group(1)) == plan["target_count"] == len(targets)
    assert not any(workspace.iterdir())
    assert not any(home.iterdir())
    assert not any(cache.iterdir())
    scratch_entries = {path.name for path in scratch.iterdir()}
    # macOS may let xcrun create its own TMPDIR cache while resolving the
    # developer-tool git binary.  That OS-owned cache is not an installer
    # mutation; no product-owned scratch artifact is allowed.
    if sys.platform == "darwin":
        assert scratch_entries <= {"xcrun_db"}
    else:
        assert not scratch_entries


def test_agent_plan_requires_explicit_json_result_path(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "--agent-plan",
            "--codex",
            "--project",
            str(workspace),
            "--yes",
        ],
        cwd=_project_root(),
        env={**os.environ, "HOME": str(tmp_path / "home"), "NO_COLOR": "1"},
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert "--agent-plan-json FILE" in result.stderr
    assert not any(workspace.iterdir())


def test_agent_plan_does_not_create_an_unplanned_output_parent(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    missing_parent = tmp_path / "missing-plan-parent"
    result = subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "--agent-plan-json",
            str(missing_parent / "plan.json"),
            "--codex",
            "--project",
            str(workspace),
            "--yes",
        ],
        cwd=_project_root(),
        env={**os.environ, "HOME": str(tmp_path / "home"), "NO_COLOR": "1"},
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 1
    assert not missing_parent.exists()
    assert not any(workspace.iterdir())


def test_agent_apply_contract_rejects_source_commit_drift_without_reading_stdin(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "--codex",
            "--project",
            str(workspace),
            "--expected-source-commit",
            "0" * 40,
            "--yes",
        ],
        cwd=_project_root(),
        env={**os.environ, "HOME": str(tmp_path / "home"), "NO_COLOR": "1"},
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 1
    assert "源码版本已不同于审阅过的 Agent 计划" in result.stderr
    assert not any(workspace.iterdir())


def test_agent_plan_apply_contract_installs_headlessly_with_bound_provenance(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    home = tmp_path / "home"
    workspace.mkdir()
    home.mkdir()
    plan_path = tmp_path / "plan.json"
    env = {
        **os.environ,
        "HOME": str(home),
        "RESEARCH_PYTHON": sys.executable,
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "NO_COLOR": "1",
    }
    planned = subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "--agent-plan-json",
            str(plan_path),
            "--codex",
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

    unreviewed = subprocess.run(
        [plan["apply_contract"]["executable"], *plan["apply_contract"]["argv"]],
        cwd=_project_root(),
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )
    assert unreviewed.returncode == 1
    assert not any(workspace.iterdir())
    assert not any(home.iterdir())

    applied = _apply_reviewed_plan(_project_root(), plan, env=env, timeout=30)

    assert applied.returncode == 0, applied.stdout + applied.stderr
    manifest = json.loads((workspace / ".agents/.install-manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_strategy"] == plan["source"]["strategy"]
    assert manifest["source_checkout"] == plan["source"]["checkout"]
    assert manifest["source_origin"] == plan["source"]["origin"]
    assert manifest["source_branch"] == plan["source"]["branch"]
    assert manifest["source_commit"] == plan["source"]["commit"]
    for target in plan["targets"]:
        if target["operation"] not in {"copy", "overwrite", "write", "write-manifest", "write-managed-block"}:
            continue
        content = Path(target["path"]).read_bytes()
        if target["operation"] == "write-managed-block":
            begin = content.index(b"# >>> workspace-oss managed >>>")
            end_marker = b"# <<< workspace-oss managed <<<"
            end = content.index(end_marker, begin) + len(end_marker)
            if content[end : end + 2] == b"\r\n":
                end += 2
            elif content[end : end + 1] == b"\n":
                end += 1
            content = content[begin:end]
        assert hashlib.sha256(content).hexdigest() == target["source_content_sha256"]


def _plan_from_source(
    source: Path,
    workspace: Path,
    plan_path: Path,
    *,
    env: dict[str, str],
) -> tuple[subprocess.CompletedProcess[str], dict[str, object]]:
    result = subprocess.run(
        [
            "bash",
            str(source / "install.sh"),
            "--agent-plan-json",
            str(plan_path),
            "--codex",
            "--project",
            str(workspace),
            "--yes",
        ],
        cwd=source,
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )
    payload = json.loads(plan_path.read_text(encoding="utf-8")) if result.returncode == 0 else {}
    return result, payload


def _apply_reviewed_plan(
    source: Path,
    plan: dict[str, object],
    *,
    env: dict[str, str],
    reviewed_byte_sha256: str | None = None,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    contract = plan["apply_contract"]
    assert isinstance(contract, dict)
    executable = contract["executable"]
    argv = contract["argv"]
    assert isinstance(executable, str) and isinstance(argv, list)
    argv = list(argv)
    plan_path = Path(str(contract["plan_path"]))
    if reviewed_byte_sha256 is None:
        reviewed_byte_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    byte_index = argv.index("--expected-plan-byte-sha256")
    assert argv[byte_index + 1] == PLAN_BYTE_SHA256_PLACEHOLDER
    argv[byte_index + 1] = reviewed_byte_sha256
    return subprocess.run(
        [executable, *argv],
        cwd=source,
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )


def test_agent_apply_rejects_uncommitted_distributable_drift_at_same_head_without_writes(tmp_path: Path) -> None:
    source = _make_linked_source(tmp_path)
    workspace = tmp_path / "source-drift-workspace"
    workspace.mkdir()
    home = tmp_path / "source-drift-home"
    home.mkdir()
    plan_path = tmp_path / "source-drift-plan.json"
    env = {
        **os.environ,
        "HOME": str(home),
        "RESEARCH_PYTHON": sys.executable,
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "NO_COLOR": "1",
    }
    planned, plan = _plan_from_source(source, workspace, plan_path, env=env)
    assert planned.returncode == 0, planned.stdout + planned.stderr
    original_head = _git_output(source, "rev-parse", "HEAD")
    source_agents = source / ".agents/AGENTS.md"
    source_agents.write_text(source_agents.read_text(encoding="utf-8") + "\nUncommitted drift.\n", encoding="utf-8")
    assert _git_output(source, "rev-parse", "HEAD") == original_head

    applied = _apply_reviewed_plan(source, plan, env=env)

    assert applied.returncode == 1
    assert "计划、源码或目标状态已变化" in applied.stderr
    assert not any(workspace.iterdir())
    assert not any(home.iterdir())


def test_agent_apply_rejects_source_origin_drift_without_writes(tmp_path: Path) -> None:
    source = _make_linked_source(tmp_path)
    workspace = tmp_path / "origin-drift-workspace"
    workspace.mkdir()
    home = tmp_path / "origin-drift-home"
    home.mkdir()
    plan_path = tmp_path / "origin-drift-plan.json"
    env = {
        **os.environ,
        "HOME": str(home),
        "RESEARCH_PYTHON": sys.executable,
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "NO_COLOR": "1",
    }
    planned, plan = _plan_from_source(source, workspace, plan_path, env=env)
    assert planned.returncode == 0, planned.stdout + planned.stderr
    original_head = _git_output(source, "rev-parse", "HEAD")
    _git_output(source, "remote", "set-url", "origin", "ssh://example.test/changed/workspace-oss.git")
    assert _git_output(source, "rev-parse", "HEAD") == original_head

    applied = _apply_reviewed_plan(source, plan, env=env)

    assert applied.returncode == 1
    assert "计划、源码或目标状态已变化" in applied.stderr
    assert not any(workspace.iterdir())
    assert not any(home.iterdir())


def test_agent_apply_rejects_same_commit_branch_drift_without_writes(tmp_path: Path) -> None:
    source = _make_linked_source(tmp_path)
    workspace = tmp_path / "branch-drift-workspace"
    workspace.mkdir()
    home = tmp_path / "branch-drift-home"
    home.mkdir()
    plan_path = tmp_path / "branch-drift-plan.json"
    env = {
        **os.environ,
        "HOME": str(home),
        "RESEARCH_PYTHON": sys.executable,
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "NO_COLOR": "1",
    }
    planned, plan = _plan_from_source(source, workspace, plan_path, env=env)
    assert planned.returncode == 0, planned.stdout + planned.stderr
    original_head = _git_output(source, "rev-parse", "HEAD")
    _git_output(source, "checkout", "-b", "same-commit-review-drift")
    assert _git_output(source, "rev-parse", "HEAD") == original_head

    applied = _apply_reviewed_plan(source, plan, env=env)

    assert applied.returncode == 1
    assert "计划、源码或目标状态已变化" in applied.stderr
    assert not any(workspace.iterdir())
    assert not any(home.iterdir())


def test_agent_apply_rejects_semantic_edit_even_with_recomputed_external_byte_sha(tmp_path: Path) -> None:
    source = _make_linked_source(tmp_path)
    workspace = tmp_path / "tampered-plan-workspace"
    workspace.mkdir()
    home = tmp_path / "tampered-plan-home"
    home.mkdir()
    plan_path = tmp_path / "tampered-plan.json"
    env = {
        **os.environ,
        "HOME": str(home),
        "RESEARCH_PYTHON": sys.executable,
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "NO_COLOR": "1",
    }
    planned, plan = _plan_from_source(source, workspace, plan_path, env=env)
    assert planned.returncode == 0, planned.stdout + planned.stderr
    reviewed_byte_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    tampered = json.loads(plan_path.read_text(encoding="utf-8"))
    tampered["conflicts"].append("tampered after review")
    plan_path.write_text(json.dumps(tampered, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    recomputed_byte_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()
    assert recomputed_byte_sha256 != reviewed_byte_sha256
    applied = _apply_reviewed_plan(source, plan, env=env, reviewed_byte_sha256=recomputed_byte_sha256)

    assert applied.returncode == 1
    assert "计划、源码或目标状态已变化" in applied.stderr
    assert not any(workspace.iterdir())
    assert not any(home.iterdir())


def test_agent_apply_binds_exact_reviewed_plan_bytes_before_any_write(tmp_path: Path) -> None:
    source = _project_root()
    mutations = ("append-newline", "reindent-and-reorder", "utf8-bom", "replacement-inode")

    for mutation in mutations:
        case_root = tmp_path / mutation
        case_root.mkdir()
        workspace = case_root / "workspace"
        home = case_root / "home"
        workspace.mkdir()
        home.mkdir()
        plan_path = case_root / "plan.json"
        outside_sentinel = case_root / "outside-sentinel.txt"
        outside_sentinel.write_text("unchanged\n", encoding="utf-8")
        env = {
            **os.environ,
            "HOME": str(home),
            "RESEARCH_PYTHON": sys.executable,
            "RESEARCH_NO_MANAGED_VENV": "1",
            "RESEARCH_NO_PDF_BACKEND": "1",
            "NO_COLOR": "1",
        }
        planned, plan = _plan_from_source(source, workspace, plan_path, env=env)
        assert planned.returncode == 0, planned.stdout + planned.stderr
        reviewed_bytes = plan_path.read_bytes()
        reviewed_byte_sha256 = hashlib.sha256(reviewed_bytes).hexdigest()

        if mutation == "append-newline":
            plan_path.write_bytes(reviewed_bytes + b"\n")
        elif mutation == "reindent-and-reorder":
            payload = json.loads(reviewed_bytes)
            reordered = dict(reversed(list(payload.items())))
            plan_path.write_text(
                json.dumps(reordered, ensure_ascii=False, indent=4, sort_keys=False) + "\n",
                encoding="utf-8",
            )
        elif mutation == "utf8-bom":
            plan_path.write_bytes(b"\xef\xbb\xbf" + reviewed_bytes)
        else:
            replacement = case_root / "replacement.json"
            replacement.write_bytes(reviewed_bytes + b"\n")
            os.replace(replacement, plan_path)

        applied = _apply_reviewed_plan(
            source,
            plan,
            env=env,
            reviewed_byte_sha256=reviewed_byte_sha256,
        )

        assert applied.returncode == 1
        assert "计划、源码或目标状态已变化" in applied.stderr
        assert not any(workspace.iterdir())
        assert not any(home.iterdir())
        assert outside_sentinel.read_text(encoding="utf-8") == "unchanged\n"


def test_agent_apply_rejects_leaf_and_ancestor_plan_symlinks_without_writes(tmp_path: Path) -> None:
    source = _project_root()

    for link_kind in ("leaf", "ancestor"):
        case_root = tmp_path / link_kind
        case_root.mkdir()
        workspace = case_root / "workspace"
        home = case_root / "home"
        plan_parent = case_root / "plan-parent"
        workspace.mkdir()
        home.mkdir()
        plan_parent.mkdir()
        plan_path = plan_parent / "plan.json"
        outside_sentinel = case_root / "outside-sentinel.txt"
        outside_sentinel.write_text("unchanged\n", encoding="utf-8")
        env = {
            **os.environ,
            "HOME": str(home),
            "RESEARCH_PYTHON": sys.executable,
            "RESEARCH_NO_MANAGED_VENV": "1",
            "RESEARCH_NO_PDF_BACKEND": "1",
            "NO_COLOR": "1",
        }
        planned, plan = _plan_from_source(source, workspace, plan_path, env=env)
        assert planned.returncode == 0, planned.stdout + planned.stderr
        reviewed_byte_sha256 = hashlib.sha256(plan_path.read_bytes()).hexdigest()

        if link_kind == "leaf":
            real_plan = case_root / "real-plan.json"
            plan_path.replace(real_plan)
            plan_path.symlink_to(real_plan)
        else:
            real_parent = case_root / "real-plan-parent"
            plan_parent.replace(real_parent)
            plan_parent.symlink_to(real_parent, target_is_directory=True)

        applied = _apply_reviewed_plan(
            source,
            plan,
            env=env,
            reviewed_byte_sha256=reviewed_byte_sha256,
        )

        assert applied.returncode == 1
        assert "计划、源码或目标状态已变化" in applied.stderr
        assert not any(workspace.iterdir())
        assert not any(home.iterdir())
        assert outside_sentinel.read_text(encoding="utf-8") == "unchanged\n"


def test_agent_apply_rejects_target_concurrency_without_writes(tmp_path: Path) -> None:
    source = _make_linked_source(tmp_path)
    workspace = tmp_path / "target-drift-workspace"
    workspace.mkdir()
    home = tmp_path / "target-drift-home"
    home.mkdir()
    plan_path = tmp_path / "target-drift-plan.json"
    env = {
        **os.environ,
        "HOME": str(home),
        "RESEARCH_PYTHON": sys.executable,
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "NO_COLOR": "1",
    }
    planned, plan = _plan_from_source(source, workspace, plan_path, env=env)
    assert planned.returncode == 0, planned.stdout + planned.stderr
    user_target = workspace / "AGENTS.md"
    user_target.write_text("concurrent user change\n", encoding="utf-8")

    applied = _apply_reviewed_plan(source, plan, env=env)

    assert applied.returncode == 1
    assert "计划、源码或目标状态已变化" in applied.stderr
    assert user_target.read_text(encoding="utf-8") == "concurrent user change\n"
    assert list(workspace.iterdir()) == [user_target]
    assert not any(home.iterdir())


def test_agent_plan_core_runtime_probe_catches_yaml_only_environment(tmp_path: Path) -> None:
    workspace = tmp_path / "partial-runtime-workspace"
    workspace.mkdir()
    home = tmp_path / "partial-runtime-home"
    home.mkdir()
    stubs = tmp_path / "partial-runtime-stubs"
    stubs.mkdir()
    (stubs / "yaml.py").write_text("# available\n", encoding="utf-8")
    (stubs / "markdownify.py").write_text("# available\n", encoding="utf-8")
    isolated_python = tmp_path / "partial-python"
    isolated_python.write_text(f"#!/bin/sh\nexec {sys.executable!s} -S \"$@\"\n", encoding="utf-8")
    isolated_python.chmod(0o755)
    plan_path = tmp_path / "partial-runtime-plan.json"
    env = {
        **os.environ,
        "HOME": str(home),
        "PYTHONPATH": str(stubs),
        "RESEARCH_PYTHON": str(isolated_python),
        "NO_COLOR": "1",
    }

    planned, plan = _plan_from_source(_project_root(), workspace, plan_path, env=env)

    assert planned.returncode == 0, planned.stdout + planned.stderr
    assert "首次使用时会自动准备" in planned.stderr
    runtime = plan["conditional_runtime_changes"]
    assert len(runtime) == 1
    assert runtime[0]["path"] == str(workspace / ".venv")
    assert "yaml, markdownify, bs4, or the pymupdf4llm PDF backend" in runtime[0]["condition"]


def test_agent_uninstall_plan_reports_managed_block_and_exact_count(tmp_path: Path) -> None:
    workspace = tmp_path / "agent-uninstall-workspace"
    installed = _run_copy_action(
        tmp_path,
        workspace,
        action="install",
        extra=("--claude",),
    )
    assert installed.returncode == 0, installed.stdout + installed.stderr
    plan_path = tmp_path / "uninstall-plan.json"
    before = _workspace_snapshot(workspace)
    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "RESEARCH_PYTHON": sys.executable,
        "RESEARCH_NO_MANAGED_VENV": "1",
        "NO_COLOR": "1",
    }

    result = subprocess.run(
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
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert any(item["operation"] == "remove-managed-block" and item["path"] == str(workspace / "CLAUDE.md") for item in plan["targets"])
    assert any(item["operation"] == "rmdir" and item["path"] == str(workspace / ".agents") for item in plan["targets"])
    summary = re.search(r"预计受管目标：(\d+) 项", result.stdout)
    assert summary is not None
    assert int(summary.group(1)) == plan["target_count"] == len(plan["targets"])
    assert "这个工作区现在不再由安装器管理" not in result.stdout
    assert "安装器管理的工作区文件已移除" not in result.stdout
    assert _workspace_snapshot(workspace) == before

    applied = _apply_reviewed_plan(_project_root(), plan, env=env, timeout=30)

    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert "这个工作区现在不再由安装器管理" in applied.stdout
    assert "安装器管理的工作区文件已移除" in applied.stdout
    assert not (workspace / ".agents/.install-manifest.json").exists()


def test_user_agents_managed_block_round_trip_is_byte_exact_across_two_lifecycles(
    tmp_path: Path,
) -> None:
    samples = {
        "no-newline": "用户规则".encode(),
        "one-newline": "用户规则\n".encode(),
        "multiple-newlines": "用户规则\n\n\n".encode(),
        "crlf": "用户规则\r\n第二行\r\n".encode(),
        "empty": b"",
    }
    for name, original in samples.items():
        workspace = tmp_path / f"agents-roundtrip-{name}"
        workspace.mkdir()
        target = workspace / "AGENTS.md"
        target.write_bytes(original)
        for _cycle in range(2):
            for action in ("install", "update", "reinstall"):
                result = _run_copy_action(tmp_path, workspace, action=action)
                assert result.returncode == 0, result.stdout + result.stderr
            manifest = json.loads(
                (workspace / ".agents/.install-manifest.json").read_text(encoding="utf-8")
            )
            assert manifest["agents_md_roundtrip"]["before_sha256"] == hashlib.sha256(
                original
            ).hexdigest()
            uninstalled = _run_copy_action(tmp_path, workspace, action="uninstall")
            assert uninstalled.returncode == 0, uninstalled.stdout + uninstalled.stderr
            assert target.is_file()
            assert target.read_bytes() == original


def test_user_agents_suffix_after_managed_block_survives_exact_uninstall(tmp_path: Path) -> None:
    workspace = tmp_path / "agents-roundtrip-suffix"
    workspace.mkdir()
    target = workspace / "AGENTS.md"
    original = "前置用户规则\r\n".encode()
    suffix = "后置用户规则\n".encode()
    target.write_bytes(original)
    installed = _run_copy_action(tmp_path, workspace, action="install")
    assert installed.returncode == 0, installed.stdout + installed.stderr
    target.write_bytes(target.read_bytes() + suffix)

    for action in ("update", "reinstall"):
        result = _run_copy_action(tmp_path, workspace, action=action)
        assert result.returncode == 0, result.stdout + result.stderr
    uninstalled = _run_copy_action(tmp_path, workspace, action="uninstall")

    assert uninstalled.returncode == 0, uninstalled.stdout + uninstalled.stderr
    assert target.read_bytes() == original + suffix


def test_legacy_manifests_remove_managed_agents_without_deleting_user_content(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "legacy-managed-block-workspace"
    workspace.mkdir()
    target = workspace / "AGENTS.md"
    original = b"legacy user rule\n"
    target.write_bytes(original)
    installed = _run_copy_action(tmp_path, workspace, action="install")
    assert installed.returncode == 0, installed.stdout + installed.stderr
    manifest_path = workspace / ".agents/.install-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop("agents_md_roundtrip")
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    uninstalled = _run_copy_action(tmp_path, workspace, action="uninstall")

    assert uninstalled.returncode == 0, uninstalled.stdout + uninstalled.stderr
    assert target.read_bytes().startswith(original)
    assert b"workspace-oss managed" not in target.read_bytes()

    legacy_workspace = tmp_path / "legacy-whole-file-workspace"
    installed = _run_copy_action(tmp_path, legacy_workspace, action="install")
    assert installed.returncode == 0, installed.stdout + installed.stderr
    legacy_target = legacy_workspace / "AGENTS.md"
    legacy_content = b"legacy installer owned file\n"
    legacy_target.write_bytes(legacy_content)
    manifest_path = legacy_workspace / ".agents/.install-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    legacy_digest = hashlib.sha256(legacy_content).hexdigest()
    manifest.pop("agents_md_roundtrip")
    manifest["agents_md"] = "managed"
    manifest["agents_md_sha"] = legacy_digest
    manifest["files"]["AGENTS.md"] = legacy_digest
    checksum = hashlib.sha256()
    for relative in sorted(manifest["files"]):
        checksum.update(relative.encode("utf-8"))
        checksum.update(b"\0")
        checksum.update(manifest["files"][relative].encode("ascii"))
        checksum.update(b"\0")
    manifest["tree_checksum"] = checksum.hexdigest()
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    uninstalled = _run_copy_action(tmp_path, legacy_workspace, action="uninstall")

    assert uninstalled.returncode == 0, uninstalled.stdout + uninstalled.stderr
    assert not legacy_target.exists()


def test_ready_managed_venv_suppresses_update_warning_and_conditional_target(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "ready-managed-venv"
    installed = _run_copy_action(tmp_path, workspace, action="install")
    assert installed.returncode == 0, installed.stdout + installed.stderr
    managed_bin = workspace / ".venv/bin"
    managed_bin.mkdir(parents=True)
    (managed_bin / "python").symlink_to(sys.executable)
    home = tmp_path / "ready-managed-home"
    home.mkdir()
    env = {
        **os.environ,
        "HOME": str(home),
        "NO_COLOR": "1",
        "PATH": "/usr/bin:/bin",
        "RESEARCH_PYTHON": "/bin/false",
        "RESEARCH_NO_PDF_BACKEND": "1",
    }
    doctor = subprocess.run(
        [str(workspace / ".agents/skills/kb-cli/scripts/kb"), "--root", str(workspace), "doctor"],
        cwd=workspace,
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert doctor.returncode == 0, doctor.stdout + doctor.stderr
    assert "受管项目运行环境可用" in doctor.stdout

    plan_path = tmp_path / "ready-managed-update.json"
    planned = subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "update",
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
        timeout=30,
        check=False,
    )
    assert planned.returncode == 0, planned.stdout + planned.stderr
    assert "Python 依赖尚未就绪" not in planned.stdout + planned.stderr
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    assert len(plan["conditional_runtime_changes"]) == 1
    assert plan["runtime_precondition"] is None
    venv_before = _workspace_snapshot(workspace / ".venv")

    applied = _apply_reviewed_plan(_project_root(), plan, env=env, timeout=30)

    assert applied.returncode == 0, applied.stdout + applied.stderr
    assert _workspace_snapshot(workspace / ".venv") == venv_before
    assert "Python 依赖尚未就绪" not in applied.stdout + applied.stderr
    assert "skills 已是最新版本" in applied.stdout


def test_unsafe_managed_venv_nodes_warn_without_execution_or_plan_writes(tmp_path: Path) -> None:
    for unsafe_kind in ("broken-leaf", "fifo-leaf", "venv-symlink", "bin-symlink", "slow-leaf"):
        case_root = tmp_path / unsafe_kind
        workspace = case_root / "workspace"
        home = case_root / "home"
        victim = case_root / "victim"
        marker = case_root / "unsafe-executed"
        workspace.mkdir(parents=True)
        home.mkdir()
        (victim / "bin").mkdir(parents=True)
        victim_python = victim / "bin/python"
        victim_python.write_text(f"#!/bin/sh\ntouch {marker!s}\nexit 0\n", encoding="utf-8")
        victim_python.chmod(0o755)
        managed_bin = workspace / ".venv/bin"
        if unsafe_kind == "venv-symlink":
            (workspace / ".venv").symlink_to(victim, target_is_directory=True)
        elif unsafe_kind == "bin-symlink":
            (workspace / ".venv").mkdir()
            managed_bin.symlink_to(victim / "bin", target_is_directory=True)
        else:
            managed_bin.mkdir(parents=True)
            managed_python = managed_bin / "python"
            if unsafe_kind == "broken-leaf":
                managed_python.symlink_to(case_root / "missing-python")
            elif unsafe_kind == "fifo-leaf":
                os.mkfifo(managed_python)
            else:
                slow_python = case_root / "slow-python"
                slow_python.write_text(
                    f"#!{sys.executable!s}\nimport time\ntime.sleep(30)\n",
                    encoding="utf-8",
                )
                slow_python.chmod(0o755)
                managed_python.symlink_to(slow_python)
        before = _workspace_snapshot(workspace)
        plan_path = case_root / "plan.json"
        started = time.monotonic()
        result = subprocess.run(
            [
                "bash",
                str(_project_root() / "install.sh"),
                "--agent-plan-json",
                str(plan_path),
                "--codex",
                "--project",
                str(workspace),
                "--yes",
            ],
            cwd=_project_root(),
            env={
                **os.environ,
                "HOME": str(home),
                "NO_COLOR": "1",
                "RESEARCH_PYTHON": "/bin/false",
                "RESEARCH_NO_PDF_BACKEND": "1",
            },
            stdin=subprocess.DEVNULL,
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        elapsed = time.monotonic() - started

        assert result.returncode == 0, result.stdout + result.stderr
        assert elapsed < 12
        assert "Python 依赖尚未就绪" in result.stdout + result.stderr
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        runtime = plan["conditional_runtime_changes"]
        assert len(runtime) == 1
        assert runtime[0]["path"] == str(workspace / ".venv")
        assert _workspace_snapshot(workspace) == before
        assert not marker.exists()


def test_managed_venv_regular_interpreter_cannot_attempt_an_ancestor_swap(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "swapped-venv-workspace"
    home = tmp_path / "swapped-venv-home"
    victim = tmp_path / "swapped-venv-victim"
    marker = tmp_path / "rebound-python-executed"
    managed_bin = workspace / ".venv/bin"
    managed_bin.mkdir(parents=True)
    home.mkdir()
    (victim / "bin").mkdir(parents=True)
    victim_python = victim / "bin/python"
    victim_python.write_text(f"#!/bin/sh\ntouch {marker!s}\nexit 0\n", encoding="utf-8")
    victim_python.chmod(0o755)
    managed_python = managed_bin / "python"
    managed_python.write_text(
        "#!/bin/sh\n"
        'mv "$PROBE_WORKSPACE/.venv" "$PROBE_WORKSPACE/.venv-original"\n'
        'ln -s "$PROBE_VICTIM" "$PROBE_WORKSPACE/.venv"\n'
        "exit 0\n",
        encoding="utf-8",
    )
    managed_python.chmod(0o755)
    plan_path = tmp_path / "swapped-venv-plan.json"

    result = subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "--agent-plan-json",
            str(plan_path),
            "--codex",
            "--project",
            str(workspace),
            "--yes",
        ],
        cwd=_project_root(),
        env={
            **os.environ,
            "HOME": str(home),
            "NO_COLOR": "1",
            "RESEARCH_PYTHON": "/bin/false",
            "RESEARCH_NO_PDF_BACKEND": "1",
            "PROBE_WORKSPACE": str(workspace),
            "PROBE_VICTIM": str(victim),
        },
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "Python 依赖尚未就绪" in result.stdout + result.stderr
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    runtime = plan["conditional_runtime_changes"]
    assert len(runtime) == 1
    assert runtime[0]["path"] == str(workspace / ".venv")
    assert (workspace / ".venv").is_dir()
    assert not (workspace / ".venv").is_symlink()
    assert not (workspace / ".venv-original").exists()
    assert managed_python.is_file()
    assert not marker.exists()


def test_installer_smoke_does_not_create_unplanned_bytecode(tmp_path: Path) -> None:
    workspace = tmp_path / "bytecode-workspace"
    workspace.mkdir()
    home = tmp_path / "bytecode-home"
    cache = tmp_path / "bytecode-cache"
    home.mkdir()
    cache.mkdir()
    result = subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "install",
            "--all",
            "--project",
            str(workspace),
            "--yes",
        ],
        cwd=_project_root(),
        env={
            **os.environ,
            "HOME": str(home),
            "PYTHONPYCACHEPREFIX": str(cache),
            "RESEARCH_PYTHON": sys.executable,
            "RESEARCH_NO_MANAGED_VENV": "1",
            "RESEARCH_NO_PDF_BACKEND": "1",
            "NO_COLOR": "1",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not list((workspace / ".agents").rglob("__pycache__"))
    assert not list((workspace / ".agents").rglob("*.pyc"))
    assert not any(cache.iterdir())


def test_project_install_rejects_symlinked_managed_parent(tmp_path: Path) -> None:
    workspace = tmp_path / "symlink-parent-workspace"
    outside = tmp_path / "outside-claude"
    workspace.mkdir()
    outside.mkdir()
    (workspace / ".claude").symlink_to(outside, target_is_directory=True)

    for plan_flag in (("--agent-plan-json", str(tmp_path / "rejected-plan.json")), ()):
        result = subprocess.run(
            [
                "bash",
                str(_project_root() / "install.sh"),
                "install",
                "--claude",
                "--project",
                str(workspace),
                "--yes",
                *plan_flag,
            ],
            cwd=_project_root(),
            env={**os.environ, "RESEARCH_PYTHON": sys.executable, "NO_COLOR": "1"},
            text=True,
            capture_output=True,
            check=False,
        )
        assert result.returncode == 1
        assert not any(outside.iterdir())
        assert not (workspace / ".agents").exists()
        assert not (workspace / "AGENTS.md").exists()


def test_system_agent_plan_lists_missing_parent_directories(tmp_path: Path) -> None:
    home = tmp_path / "system-plan-home"
    cache = tmp_path / "system-plan-cache"
    scratch = tmp_path / "system-plan-tmp"
    for directory in (home, cache, scratch):
        directory.mkdir()
    plan_path = tmp_path / "system-plan.json"
    result = subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "install",
            "--agent-plan-json",
            str(plan_path),
            "--all",
            "--system",
            "--kb-on-path",
            "--yes",
        ],
        cwd=_project_root(),
        env={
            **os.environ,
            "HOME": str(home),
            "PYTHONPYCACHEPREFIX": str(cache),
            "TMPDIR": str(scratch),
            "RESEARCH_PYTHON": sys.executable,
            "RESEARCH_NO_MANAGED_VENV": "1",
            "NO_COLOR": "1",
        },
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    targets = {(item["operation"], item["path"]) for item in plan["targets"]}
    for directory in (
        home / ".claude",
        home / ".claude/skills",
        home / ".codex",
        home / ".codex/workspace-oss",
        home / ".local",
        home / ".local/bin",
    ):
        assert ("mkdir", str(directory)) in targets
    summary = re.search(r"预计受管目标：(\d+) 项", result.stdout)
    assert summary is not None and int(summary.group(1)) == plan["target_count"] == len(plan["targets"])
    assert len(result.stdout.splitlines()) <= 20
    assert not any(home.iterdir())
    assert not any(cache.iterdir())
    scratch_entries = {path.name for path in scratch.iterdir()}
    if sys.platform == "darwin":
        assert scratch_entries <= {"xcrun_db"}
    else:
        assert not scratch_entries


def _run_pty_dialog(
    tmp_path: Path,
    *,
    args: list[str],
    exchanges: list[tuple[str, str]],
    env_overrides: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "HOME": str(home),
        "NO_COLOR": "1",
        "PATH": "/usr/bin:/bin",
        "RESEARCH_PYTHON": shutil.which("true") or "/usr/bin/true",
        "TERM": "dumb",
    }
    # A prior in-process bootstrap test may leave this readiness marker behind.
    # Each installer subprocess must prove its own configured runtime instead of
    # inheriting readiness from the pytest interpreter.
    env.pop("_RESEARCH_RUNTIME_READY", None)
    if env_overrides:
        env.update(env_overrides)
    command = ["bash", str(_project_root() / "install.sh"), *args]
    master_fd, slave_fd = pty.openpty()
    process = subprocess.Popen(
        command,
        cwd=_project_root(),
        env=env,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        close_fds=True,
    )
    os.close(slave_fd)
    output = bytearray()
    search_from = 0

    def read_once(timeout: float) -> bool:
        ready, _, _ = select.select([master_fd], [], [], timeout)
        if not ready:
            return False
        try:
            chunk = os.read(master_fd, 65536)
        except OSError as exc:
            if exc.errno == errno.EIO:
                return False
            raise
        if chunk:
            output.extend(chunk)
            return True
        return False

    try:
        for marker, response in exchanges:
            encoded = marker.encode("utf-8")
            deadline = time.monotonic() + 10
            while output.find(encoded, search_from) < 0 and time.monotonic() < deadline:
                read_once(0.1)
                if process.poll() is not None:
                    break
            position = output.find(encoded, search_from)
            if position < 0:
                rendered = output.decode("utf-8", errors="replace")
                raise AssertionError(f"PTY prompt not found: {marker!r}\n{rendered}")
            search_from = position + len(encoded)
            os.write(master_fd, response.encode("utf-8"))

        deadline = time.monotonic() + 15
        while process.poll() is None and time.monotonic() < deadline:
            read_once(0.1)
        if process.poll() is None:
            process.kill()
            raise AssertionError("installer PTY session timed out")
        while read_once(0):
            pass
        returncode = process.wait(timeout=2)
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=2)
        os.close(master_fd)

    return subprocess.CompletedProcess(
        command,
        returncode,
        output.decode("utf-8", errors="replace"),
        "",
    )


def _run_shortcut_install(
    tmp_path: Path,
    *,
    shortcut_on_path: bool,
) -> tuple[Path, subprocess.CompletedProcess[str]]:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    path_entries = ["/usr/bin", "/bin"]
    if shortcut_on_path:
        path_entries.insert(0, str(workspace / "bin"))
    result = _run_pty_dialog(
        tmp_path,
        args=[
            "install",
            "--codex",
            "--project",
            str(workspace),
            "--kb-on-path",
            "--yes",
        ],
        exchanges=[],
        env_overrides={
            "PATH": ":".join(path_entries),
            "RESEARCH_NO_MANAGED_VENV": "1",
            "RESEARCH_NO_PDF_BACKEND": "1",
            "RESEARCH_PYTHON": sys.executable,
        },
    )
    return workspace, result


def _run_copy_action(
    tmp_path: Path,
    workspace: Path,
    *,
    action: str,
    source: Path | None = None,
    extra: tuple[str, ...] = (),
) -> subprocess.CompletedProcess[str]:
    workspace.mkdir(exist_ok=True)
    source_root = source or _project_root()
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    env = {
        **os.environ,
        "HOME": str(home),
        "NO_COLOR": "1",
        "PATH": "/usr/bin:/bin",
        "RESEARCH_NO_MANAGED_VENV": "1",
        "RESEARCH_NO_PDF_BACKEND": "1",
        "RESEARCH_PYTHON": sys.executable,
    }
    # Bootstrap tests can set this marker directly in the pytest process.
    # A fresh installer subprocess must prove its own configured runtime.
    env.pop("_RESEARCH_RUNTIME_READY", None)
    command = ["bash", str(source_root / "install.sh"), action]
    if action == "install":
        command.append("--codex")
    command.extend(["--project", str(workspace), "--yes", *extra])
    return subprocess.run(
        command,
        cwd=source_root,
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )


def _install_copy(
    tmp_path: Path,
    workspace: Path,
    *,
    source: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return _run_copy_action(tmp_path, workspace, action="install", source=source)


def _assert_private_sync_output_hidden(
    result: subprocess.CompletedProcess[str],
    *private_paths: Path,
) -> None:
    output = result.stdout + result.stderr
    for token in (
        "copy-project",
        "clean-sync",
        "[dry-run]",
        "warn:",
        "error:",
        "MODIFIED",
        "expected=",
        "actual=",
        "reason=",
        ".agents/",
    ):
        assert token not in output
    for path in private_paths:
        assert str(path) not in output


def _git_output(checkout: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(checkout), *args],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _git_branch_or_empty(checkout: Path) -> str:
    result = subprocess.run(
        ["git", "-C", str(checkout), "symbolic-ref", "--quiet", "--short", "HEAD"],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 1:
        return ""
    result.check_returncode()
    return result.stdout.strip()


def _make_linked_source(tmp_path: Path) -> Path:
    primary = tmp_path / "source-primary"
    shutil.copytree(
        _project_root(),
        primary,
        ignore=shutil.ignore_patterns(".git", ".pytest_cache", "__pycache__", "*.pyc", "temp"),
    )
    subprocess.run(["git", "init", str(primary)], check=True, capture_output=True, text=True)
    _git_output(primary, "config", "user.name", "Installer Test")
    _git_output(primary, "config", "user.email", "installer@example.test")
    _git_output(primary, "checkout", "-b", "source-main")
    _git_output(primary, "add", ".")
    _git_output(primary, "commit", "-m", "source fixture")
    _git_output(primary, "remote", "add", "origin", "ssh://example.test/team/workspace-oss.git")
    linked = tmp_path / "source-linked"
    _git_output(primary, "worktree", "add", "-b", "linked-dev", str(linked), "source-main")
    return linked


def test_missing_system_yaml_continues_to_managed_runtime_fallback(tmp_path: Path) -> None:
    result = _run_dry_install(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "首次使用时会自动准备" in result.stderr
    assert "pip install" not in result.stderr


def test_missing_system_yaml_remains_fatal_when_managed_venv_disabled(tmp_path: Path) -> None:
    result = _run_dry_install(tmp_path, no_managed_venv=True)

    assert result.returncode == 1
    assert "已关闭自动运行环境" in result.stderr


def test_help_is_clear_and_colorless_for_first_time_users() -> None:
    result = subprocess.run(
        ["bash", str(_project_root() / "install.sh"), "--help"],
        cwd=_project_root(),
        env={**os.environ, "NO_COLOR": "1"},
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0
    assert "第一次使用" in result.stdout
    assert "直接运行 bash install.sh" in result.stdout
    assert "--project [DIR]" in result.stdout
    assert "\x1b[" not in result.stdout + result.stderr


def test_non_interactive_run_fails_fast_without_prompts() -> None:
    result = subprocess.run(
        ["bash", str(_project_root() / "install.sh")],
        cwd=_project_root(),
        env={**os.environ, "NO_COLOR": "1"},
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )

    assert result.returncode == 1
    assert "非交互运行时" in result.stderr
    assert "步骤 " not in result.stdout + result.stderr


def test_guided_dry_run_retries_invalid_choice_without_claiming_success(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = _run_pty_dialog(
        tmp_path,
        args=["--dry-run"],
        exchanges=[
            ("请选择 [1]：", "9\n"),
            ("请选择 [1]：", "1\n"),
            ("请选择 [3]：", "3\n"),
            ("请选择 [1]：", "1\n"),
            ("目录 [", f"{workspace}\n"),
            ("请选择 [1]：", "2\n"),
        ],
    )

    output = result.stdout
    assert result.returncode == 0, output
    assert "1) 首次安装" in output
    assert "2) 更新已安装的外部工作区" in output
    assert "3) 重装或修复已安装的外部工作区" in output
    assert "4) 卸载 skills 接入" in output
    assert "请输入 1、2、3 或 4" in output
    assert "预览完成" in output
    assert "没有写入任何文件" in output
    assert "安装完成" not in output
    assert "已为 Claude Code 和 Codex 完成配置" not in output
    assert "开始使用" not in output
    assert "[1/5]" not in output
    assert "预计文件变更：" in output
    assert ".agents/skills/kb-cli/scripts/kb" not in output
    assert "[dry-run]" not in output
    assert str(workspace) not in output
    assert ".claude/skills" not in output
    assert "\x1b[" not in output
    assert len(output.splitlines()) < 60
    assert not any(workspace.iterdir())


def test_guided_cancel_writes_nothing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = _run_pty_dialog(
        tmp_path,
        args=[],
        exchanges=[
            ("请选择 [1]：", "1\n"),
            ("请选择 [3]：", "2\n"),
            ("请选择 [1]：", "1\n"),
            ("目录 [", f"{workspace}\n"),
            ("请选择 [1]：", "1\n"),
            ("确认执行？[Y/n]：", "n\n"),
        ],
    )

    assert result.returncode == 0, result.stdout
    assert "已取消，没有写入任何文件" in result.stdout
    assert str(workspace) not in result.stdout
    assert not any(workspace.iterdir())


def test_guided_shortcut_choice_immediately_explains_terminal_usage(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = _run_pty_dialog(
        tmp_path,
        args=["install", "--dry-run", "--codex", "--project", str(workspace)],
        exchanges=[("请选择 [1]：", "2\n")],
    )

    output = result.stdout
    assert result.returncode == 0, output
    prompt_position = output.index("请选择 [1]：")
    help_position = output.index("kb help")
    init_position = output.index("kb init")
    preview_position = output.index("安装预览")
    assert prompt_position < help_position < init_position < preview_position
    assert not any(workspace.iterdir())


def test_shortcut_completion_reports_direct_terminal_usage_when_on_path(tmp_path: Path) -> None:
    workspace, result = _run_shortcut_install(tmp_path, shortcut_on_path=True)

    output = result.stdout
    assert result.returncode == 0, output
    completion = output.split("安装完成", 1)[1]
    terminal_guidance = completion.split("开始使用", 1)[0]
    assert "终端可直接运行" in terminal_guidance
    assert "kb help" in terminal_guidance
    assert "kb init" in terminal_guidance
    assert "不在 PATH" not in terminal_guidance
    assert (workspace / "bin" / "kb").is_symlink()
    for shell_config in (".zshrc", ".bashrc", ".profile"):
        assert not (tmp_path / "home" / shell_config).exists()


def test_shortcut_completion_explains_path_setup_when_not_on_path(tmp_path: Path) -> None:
    workspace, result = _run_shortcut_install(tmp_path, shortcut_on_path=False)

    output = result.stdout
    assert result.returncode == 0, output
    completion = output.split("安装完成", 1)[1]
    terminal_guidance = completion.split("开始使用", 1)[0]
    assert "不在 PATH" in terminal_guidance
    assert "加入 PATH" in terminal_guidance
    assert "重新打开终端" in terminal_guidance
    assert "kb help" in terminal_guidance
    assert "终端可直接运行" not in terminal_guidance
    assert str(workspace / "bin") not in output
    assert (workspace / "bin" / "kb").is_symlink()
    for shell_config in (".zshrc", ".bashrc", ".profile"):
        assert not (tmp_path / "home" / shell_config).exists()


def test_external_install_prints_completion_without_bash_variable_error(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    result = _run_pty_dialog(
        tmp_path,
        args=["install", "--codex", "--project", str(workspace), "--yes"],
        exchanges=[("请选择 [1]：", "1\n")],
        env_overrides={
            "NO_COLOR": "1",
            "RESEARCH_NO_MANAGED_VENV": "1",
            "RESEARCH_NO_PDF_BACKEND": "1",
            "RESEARCH_PYTHON": sys.executable,
        },
    )

    assert result.returncode == 0, result.stdout
    assert "安装完成" in result.stdout
    assert "工作区：独立工作区" in result.stdout
    assert str(workspace) not in result.stdout
    assert "unbound variable" not in result.stdout
    assert "copy-project" not in result.stdout
    assert "工作区文件已准备" in result.stdout
    terminal_guidance = result.stdout.split("安装完成", 1)[1].split("开始使用", 1)[0]
    assert "终端可直接运行" not in terminal_guidance
    assert "kb help" not in terminal_guidance
    manifest_path = workspace / ".agents" / ".install-manifest.json"
    installed_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert installed_manifest["source_strategy"] == "local-checkout"
    assert installed_manifest["source_checkout"] == str(_project_root())
    assert installed_manifest["source_origin"] == _git_output(_project_root(), "remote", "get-url", "origin")
    assert installed_manifest["source_branch"] == _git_branch_or_empty(_project_root())
    assert installed_manifest["source_commit"] == _git_output(_project_root(), "rev-parse", "HEAD")

    cancel = _run_pty_dialog(
        tmp_path,
        args=["uninstall", "--project", str(workspace)],
        exchanges=[("确认执行？[Y/n]：", "n\n")],
    )
    assert cancel.returncode == 0, cancel.stdout
    assert "已取消，没有写入任何文件" in cancel.stdout
    assert (workspace / ".agents" / ".install-manifest.json").is_file()

    update = _run_pty_dialog(
        tmp_path,
        args=[],
        exchanges=[
            ("请选择 [1]：", "2\n"),
            ("目录 [", f"{workspace}\n"),
            ("确认执行？[Y/n]：", "\n"),
        ],
    )
    assert update.returncode == 0, update.stdout
    assert "skills 已是最新版本，AI 工具配置已检查" in update.stdout
    assert "skills 和 AI 工具配置已更新" not in update.stdout
    assert "clean-sync" not in update.stdout
    updated_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert updated_manifest["source_strategy"] == installed_manifest["source_strategy"]
    assert updated_manifest["source_origin"] == installed_manifest["source_origin"]
    assert updated_manifest["source_checkout"] == installed_manifest["source_checkout"]
    assert updated_manifest["source_branch"] == installed_manifest["source_branch"]


def test_noninteractive_copy_lifecycle_hides_sync_engine_output_and_preserves_semantics(tmp_path: Path) -> None:
    dry_workspace = tmp_path / "dry-workspace"
    # Claude setup and the shortcut force this dry-run through ensure_dir,
    # link_force, and write_managed_block after ws_sync returns.
    dry_run = _run_copy_action(
        tmp_path,
        dry_workspace,
        action="install",
        extra=("--claude", "--kb-on-path", "--dry-run"),
    )

    assert dry_run.returncode == 0, dry_run.stdout + dry_run.stderr
    assert "预计文件变更：" in dry_run.stdout
    assert "预览完成" in dry_run.stdout
    assert "确认无误后再执行正式操作" in dry_run.stdout
    assert "再执行正式安装" not in dry_run.stdout
    _assert_private_sync_output_hidden(dry_run, _project_root(), dry_workspace / ".agents")
    assert not any(dry_workspace.iterdir())

    workspace = tmp_path / "workspace"
    install = _run_copy_action(tmp_path, workspace, action="install")

    assert install.returncode == 0, install.stdout + install.stderr
    assert "工作区文件已准备" in install.stdout
    assert "安装完成" in install.stdout
    _assert_private_sync_output_hidden(install, _project_root(), workspace / ".agents")
    manifest_path = workspace / ".agents" / ".install-manifest.json"
    version_path = workspace / ".agents" / "VERSION"
    assert manifest_path.is_file()
    original_version = version_path.read_bytes()

    update = _run_copy_action(tmp_path, workspace, action="update")

    assert update.returncode == 0, update.stdout + update.stderr
    assert "skills 已是最新版本，AI 工具配置已检查" in update.stdout
    _assert_private_sync_output_hidden(update, _project_root(), workspace / ".agents")

    manifest_before_failure = manifest_path.read_bytes()
    version_path.write_text("locally drifted\n", encoding="utf-8")
    failed_update = _run_copy_action(tmp_path, workspace, action="update")

    assert failed_update.returncode == 3
    assert "工作区文件操作失败。" in failed_update.stderr
    assert "受管文件已被本地修改" in failed_update.stderr
    assert "同步器输出" not in failed_update.stderr
    assert "Traceback" not in failed_update.stderr
    assert "\x1b[" not in failed_update.stderr
    assert not re.search(r"\b[0-9a-f]{40,64}\b", failed_update.stderr)
    assert "--force" not in failed_update.stderr
    assert str(_project_root()) not in failed_update.stderr
    assert str(workspace / ".agents") not in failed_update.stderr
    assert version_path.read_text(encoding="utf-8") == "locally drifted\n"
    assert manifest_path.read_bytes() == manifest_before_failure

    reinstall = _run_copy_action(tmp_path, workspace, action="reinstall")

    assert reinstall.returncode == 0, reinstall.stdout + reinstall.stderr
    assert "工作区文件已重新安装" in reinstall.stdout
    assert "重装完成" in reinstall.stdout
    _assert_private_sync_output_hidden(reinstall, _project_root(), workspace / ".agents")
    assert version_path.read_bytes() == original_version

    uninstall = _run_copy_action(tmp_path, workspace, action="uninstall")

    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert "安装器管理的工作区文件已移除" in uninstall.stdout
    assert "卸载完成" in uninstall.stdout
    _assert_private_sync_output_hidden(uninstall, _project_root(), workspace / ".agents")
    assert not manifest_path.exists()
    assert not version_path.exists()


def test_copy_lifecycle_preserves_claude_to_agents_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace-symlink"
    workspace.mkdir()
    claude = workspace / "CLAUDE.md"
    claude.symlink_to("AGENTS.md")

    install = _run_copy_action(
        tmp_path,
        workspace,
        action="install",
        extra=("--claude",),
    )
    assert install.returncode == 0, install.stdout + install.stderr
    assert claude.is_symlink() and os.readlink(claude) == "AGENTS.md"
    agents_after_install = (workspace / "AGENTS.md").read_bytes()
    assert b"@AGENTS.md" not in agents_after_install

    for action in ("update", "reinstall"):
        result = _run_copy_action(tmp_path, workspace, action=action)
        assert result.returncode == 0, result.stdout + result.stderr
        assert claude.is_symlink() and os.readlink(claude) == "AGENTS.md"
        assert (workspace / "AGENTS.md").read_bytes() == agents_after_install

    uninstall = _run_copy_action(tmp_path, workspace, action="uninstall")
    assert uninstall.returncode == 0, uninstall.stdout + uninstall.stderr
    assert claude.is_symlink() and os.readlink(claude) == "AGENTS.md"


def test_claude_project_install_rejects_unrelated_configuration_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace-unsafe-claude-link"
    workspace.mkdir()
    unrelated = tmp_path / "unrelated-claude.md"
    unrelated.write_text("user-owned\n", encoding="utf-8")
    claude = workspace / "CLAUDE.md"
    claude.symlink_to(unrelated)

    result = _run_copy_action(
        tmp_path,
        workspace,
        action="install",
        extra=("--claude",),
    )

    assert result.returncode != 0
    assert claude.is_symlink() and claude.resolve() == unrelated
    assert unrelated.read_text(encoding="utf-8") == "user-owned\n"
    assert not (workspace / ".agents").exists()


def test_codex_only_copy_lifecycle_ignores_unmanaged_claude_symlink(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace-codex-only"
    workspace.mkdir()
    unrelated = tmp_path / "unmanaged-claude.md"
    unrelated.write_text("user-owned\n", encoding="utf-8")
    claude = workspace / "CLAUDE.md"
    claude.symlink_to(unrelated)

    install = _run_copy_action(tmp_path, workspace, action="install")
    assert install.returncode == 0, install.stdout + install.stderr
    for action in ("update", "reinstall"):
        result = _run_copy_action(tmp_path, workspace, action=action)
        assert result.returncode == 0, result.stdout + result.stderr
        assert claude.is_symlink() and claude.resolve() == unrelated
        assert unrelated.read_text(encoding="utf-8") == "user-owned\n"


def test_noninteractive_smoke_failure_hides_child_diagnostics(tmp_path: Path) -> None:
    source = _make_linked_source(tmp_path)
    private_detail = tmp_path / "internal" / "smoke-traceback.log"
    smoke_script = source / ".agents" / "skills" / "kb-cli" / "scripts" / "kb"
    smoke_script.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s\\n' 'Traceback: smoke child secret at {private_detail}' >&2\n"
        "exit 23\n",
        encoding="utf-8",
    )
    workspace = tmp_path / "workspace"

    result = _run_copy_action(tmp_path, workspace, action="install", source=source)

    assert result.returncode != 0
    assert "kb 安装检查未通过，请让 Agent 检查后重试" in result.stderr
    assert "Traceback" not in result.stdout + result.stderr
    assert "smoke child secret" not in result.stdout + result.stderr
    assert str(private_detail) not in result.stdout + result.stderr
    _assert_private_sync_output_hidden(result, source, workspace / ".agents")
    assert (workspace / ".agents" / ".install-manifest.json").is_file()


def test_project_install_from_linked_worktree_preserves_linked_checkout(tmp_path: Path) -> None:
    source = _make_linked_source(tmp_path)
    assert (source / ".git").is_file()
    workspace = tmp_path / "linked-workspace"

    installed = _install_copy(tmp_path, workspace, source=source)

    assert installed.returncode == 0, installed.stdout + installed.stderr
    manifest = json.loads((workspace / ".agents" / ".install-manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_strategy"] == "local-checkout"
    assert manifest["source_checkout"] == str(source)
    assert manifest["source_origin"] == "ssh://example.test/team/workspace-oss.git"
    assert manifest["source_branch"] == "linked-dev"
    assert manifest["source_commit"] == _git_output(source, "rev-parse", "HEAD")


def test_project_install_from_detached_worktree_pins_commit_without_guessing_branch(tmp_path: Path) -> None:
    source = _make_linked_source(tmp_path)
    source_commit = _git_output(source, "rev-parse", "HEAD")
    _git_output(source, "checkout", "--detach", source_commit)
    workspace = tmp_path / "detached-workspace"

    installed = _install_copy(tmp_path, workspace, source=source)

    assert installed.returncode == 0, installed.stdout + installed.stderr
    assert "当前源码处于 detached 状态" in installed.stderr
    manifest = json.loads((workspace / ".agents" / ".install-manifest.json").read_text(encoding="utf-8"))
    assert manifest["source_strategy"] == "local-checkout"
    assert manifest["source_checkout"] == str(source)
    assert manifest["source_origin"] == "ssh://example.test/team/workspace-oss.git"
    assert manifest["source_branch"] == ""
    assert manifest["source_commit"] == source_commit


def test_ws_sync_rejects_unknown_source_strategy_before_writing(tmp_path: Path) -> None:
    workspace = tmp_path / "invalid-strategy-workspace"
    workspace.mkdir()

    result = subprocess.run(
        [
            sys.executable,
            str(_project_root() / "install-lib" / "ws_sync.py"),
            "install",
            "--repo",
            str(_project_root()),
            "--dir",
            str(workspace),
            "--source-strategy",
            "guess-from-origin",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "invalid choice" in result.stderr
    assert not (workspace / ".agents").exists()


def test_guided_reinstall_menu_runs_the_reinstall_action(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    installed = _install_copy(tmp_path, workspace)
    assert installed.returncode == 0, installed.stdout + installed.stderr

    result = _run_pty_dialog(
        tmp_path,
        args=[],
        exchanges=[
            ("请选择 [1]：", "3\n"),
            ("目录 [", f"{workspace}\n"),
            ("确认执行？[Y/n]：", "\n"),
        ],
        env_overrides={
            "RESEARCH_NO_MANAGED_VENV": "1",
            "RESEARCH_NO_PDF_BACKEND": "1",
            "RESEARCH_PYTHON": sys.executable,
        },
    )

    assert result.returncode == 0, result.stdout
    assert "操作：重装或修复" in result.stdout
    assert "AI 工具：Codex" in result.stdout
    assert "重装完成" in result.stdout


def test_interactive_duplicate_install_can_route_to_update_before_shortcut_prompt(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    installed = _install_copy(tmp_path, workspace)
    assert installed.returncode == 0, installed.stdout + installed.stderr

    result = _run_pty_dialog(
        tmp_path,
        args=["install", "--claude", "--project", str(workspace), "--yes"],
        exchanges=[("请选择 [1]：", "1\n")],
    )

    assert result.returncode == 0, result.stdout
    assert "这个工作区已经安装过" in result.stdout
    assert "操作：更新" in result.stdout
    assert "AI 工具：Codex" in result.stdout
    assert "更新完成" in result.stdout
    assert "是否创建终端快捷命令" not in result.stdout
    assert "终端快捷命令：" not in result.stdout


def test_interactive_duplicate_install_can_route_to_reinstall(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    installed = _install_copy(tmp_path, workspace)
    assert installed.returncode == 0, installed.stdout + installed.stderr

    result = _run_pty_dialog(
        tmp_path,
        args=["install", "--claude", "--project", str(workspace), "--yes"],
        exchanges=[("请选择 [1]：", "2\n")],
        env_overrides={
            "RESEARCH_NO_MANAGED_VENV": "1",
            "RESEARCH_NO_PDF_BACKEND": "1",
            "RESEARCH_PYTHON": sys.executable,
        },
    )

    assert result.returncode == 0, result.stdout
    assert "操作：重装或修复" in result.stdout
    assert "AI 工具：Codex" in result.stdout
    assert "重装完成" in result.stdout
    assert "是否创建终端快捷命令" not in result.stdout


def test_interactive_duplicate_install_can_be_cancelled_without_writes(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    installed = _install_copy(tmp_path, workspace)
    assert installed.returncode == 0, installed.stdout + installed.stderr
    manifest = workspace / ".agents" / ".install-manifest.json"
    manifest_before = manifest.read_bytes()

    result = _run_pty_dialog(
        tmp_path,
        args=["install", "--claude", "--project", str(workspace)],
        exchanges=[("请选择 [1]：", "3\n")],
    )

    assert result.returncode == 0, result.stdout
    assert "已取消，没有写入任何文件" in result.stdout
    assert "确认执行" not in result.stdout
    assert "是否创建终端快捷命令" not in result.stdout
    assert manifest.read_bytes() == manifest_before


def test_non_interactive_duplicate_install_still_fails_closed(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    installed = _install_copy(tmp_path, workspace)
    assert installed.returncode == 0, installed.stdout + installed.stderr

    result = _install_copy(tmp_path, workspace)

    assert result.returncode != 0
    assert "这个工作区已经安装过" in result.stderr
    assert "更新" in result.stderr
    assert "重装" in result.stderr


def test_system_uninstall_removes_matching_shortcut_without_kb_flag_and_preserves_foreign_link(
    tmp_path: Path,
) -> None:
    home = tmp_path / "home"
    shortcut = home / ".local" / "bin" / "kb"
    shortcut.parent.mkdir(parents=True)
    kb_script = _project_root() / ".agents" / "skills" / "kb-cli" / "scripts" / "kb"
    shortcut.symlink_to(kb_script)
    env = {**os.environ, "HOME": str(home), "NO_COLOR": "1", "PATH": "/usr/bin:/bin"}
    command = [
        "bash",
        str(_project_root() / "install.sh"),
        "--uninstall",
        "--system",
        "--codex",
        "--yes",
    ]

    removed = subprocess.run(
        command,
        cwd=_project_root(),
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )

    assert removed.returncode == 0, removed.stdout + removed.stderr
    assert not shortcut.is_symlink()

    shortcut.symlink_to("/usr/bin/true")
    preserved = subprocess.run(
        command,
        cwd=_project_root(),
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )

    assert preserved.returncode == 0, preserved.stdout + preserved.stderr
    assert shortcut.is_symlink()
    assert os.readlink(shortcut) == "/usr/bin/true"
    assert "链接目标与安装记录不一致，已保留" in preserved.stderr

    shortcut.unlink()
    shortcut.write_text("user-owned\n", encoding="utf-8")
    ordinary_file = subprocess.run(
        command,
        cwd=_project_root(),
        env=env,
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )

    assert ordinary_file.returncode == 0, ordinary_file.stdout + ordinary_file.stderr
    assert shortcut.read_text(encoding="utf-8") == "user-owned\n"
    assert "kb 快捷入口不是安装器创建的链接，已保留" in ordinary_file.stderr


def test_legacy_project_uninstall_removes_matching_shortcut_without_kb_flag(tmp_path: Path) -> None:
    workspace = tmp_path / "legacy-workspace"
    workspace.mkdir()
    (workspace / ".agents").symlink_to(_project_root() / ".agents", target_is_directory=True)
    shortcut = workspace / "bin" / "kb"
    shortcut.parent.mkdir()
    shortcut.symlink_to(_project_root() / ".agents" / "skills" / "kb-cli" / "scripts" / "kb")

    result = subprocess.run(
        [
            "bash",
            str(_project_root() / "install.sh"),
            "--uninstall",
            "--project",
            str(workspace),
            "--codex",
            "--yes",
        ],
        cwd=_project_root(),
        env={
            **os.environ,
            "HOME": str(tmp_path / "home"),
            "NO_COLOR": "1",
            "PATH": "/usr/bin:/bin",
        },
        stdin=subprocess.DEVNULL,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert not shortcut.is_symlink()
    assert not (workspace / ".agents").exists()


def test_guided_system_uninstall_can_be_cancelled(tmp_path: Path) -> None:
    result = _run_pty_dialog(
        tmp_path,
        args=[],
        exchanges=[
            ("请选择 [1]：", "4\n"),
            ("请选择 [3]：", "2\n"),
            ("请选择 [1]：", "2\n"),
            ("确认执行？[Y/n]：", "n\n"),
        ],
    )

    assert result.returncode == 0, result.stdout
    assert "操作：卸载" in result.stdout
    assert "使用范围：当前用户的所有工作区" in result.stdout
    assert "已取消，没有写入任何文件" in result.stdout


def test_single_agent_conflict_stops_before_next_steps(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    claude_dir = workspace / ".claude"
    claude_dir.mkdir(parents=True)
    (claude_dir / "skills").write_text("user-owned\n", encoding="utf-8")

    result = _run_pty_dialog(
        tmp_path,
        args=["install", "--claude", "--project", str(workspace), "--yes"],
        exchanges=[("请选择 [1]：", "1\n")],
        env_overrides={
            "NO_COLOR": "1",
            "RESEARCH_NO_MANAGED_VENV": "1",
            "RESEARCH_NO_PDF_BACKEND": "1",
            "RESEARCH_PYTHON": sys.executable,
        },
    )

    assert result.returncode == 0, result.stdout
    assert "配置因文件冲突被跳过" in result.stdout
    assert "请先处理上方文件冲突" in result.stdout
    assert "开始使用" not in result.stdout
    assert "kb init" not in result.stdout
