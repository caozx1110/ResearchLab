"""KB git repository management, checkpoints, and versioning state."""
from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import (
    ensure_dir,
    load_yaml,
    parse_iso_datetime,
    utc_now_iso,
    write_yaml_if_changed,
)
from .paths import (
    ensure_kb_gitignore,
    kb_gitignore_path,
    kb_root,
    kb_runtime_root,
    versioning_state_path,
)
from .prefs import (
    ensure_workspace,
    load_runtime_preferences,
)

def load_versioning_state(project_root: Path) -> dict[str, Any]:
    payload = load_yaml(versioning_state_path(project_root), default={})
    if not isinstance(payload, dict) or not payload:
        payload = {
            "last_auto_commit_at": "",
            "last_trigger": "",
            "last_commit": "",
            "history": [],
        }
    payload.setdefault("history", [])
    return payload


def write_versioning_state(project_root: Path, payload: dict[str, Any]) -> Path:
    ensure_dir(kb_runtime_root(project_root))
    write_yaml_if_changed(versioning_state_path(project_root), payload)
    return versioning_state_path(project_root)


def kb_repo_path(project_root: Path) -> Path:
    return kb_root(project_root)


def kb_repo_exists(project_root: Path) -> bool:
    return (kb_repo_path(project_root) / ".git").exists()


def _run_git(project_root: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(kb_repo_path(project_root)), *args],
        check=check,
        capture_output=True,
        text=True,
    )


def _git_head_exists(project_root: Path) -> bool:
    result = _run_git(project_root, "rev-parse", "--verify", "HEAD", check=False)
    return result.returncode == 0


def ensure_kb_git_repo(project_root: Path, *, create_initial_commit: bool = True, initial_message: str = "chore: initialize kb repo") -> dict[str, Any]:
    ensure_workspace(project_root)
    created = False
    if not kb_repo_exists(project_root):
        subprocess.run(["git", "init", str(kb_repo_path(project_root))], check=True, capture_output=True, text=True)
        created = True
    ensure_kb_gitignore(project_root)
    result = {
        "created": created,
        "repo_path": kb_repo_path(project_root).as_posix(),
        "gitignore_path": kb_gitignore_path(project_root).as_posix(),
        "initial_commit": False,
        "head_exists": _git_head_exists(project_root),
    }
    if create_initial_commit and not result["head_exists"]:
        checkpoint = git_checkpoint(project_root, initial_message, trigger="manual", auto_init=False)
        result["initial_commit"] = checkpoint.get("committed", False)
        result["head_exists"] = _git_head_exists(project_root)
        result["checkpoint"] = checkpoint
    return result


def kb_git_status(project_root: Path) -> dict[str, Any]:
    if not kb_repo_exists(project_root):
        return {"repo_exists": False, "text": "kb git repo is not initialized"}
    status = _run_git(project_root, "status", "--short", "--branch", check=False)
    return {"repo_exists": True, "text": status.stdout.strip(), "code": status.returncode}


def kb_git_log(project_root: Path, *, limit: int = 10) -> dict[str, Any]:
    if not kb_repo_exists(project_root):
        return {"repo_exists": False, "text": "kb git repo is not initialized"}
    if not _git_head_exists(project_root):
        return {"repo_exists": True, "text": "kb git repo has no commits yet"}
    log = _run_git(project_root, "log", f"--max-count={max(1, int(limit))}", "--oneline", "--decorate", check=False)
    return {"repo_exists": True, "text": log.stdout.strip(), "code": log.returncode}


def git_checkpoint(
    project_root: Path,
    message: str,
    *,
    trigger: str = "manual",
    auto_init: bool = True,
) -> dict[str, Any]:
    ensure_workspace(project_root)
    if not kb_repo_exists(project_root):
        if auto_init:
            ensure_kb_git_repo(project_root, create_initial_commit=False)
        else:
            return {"committed": False, "status": "missing-repo", "message": "kb git repo is not initialized"}
    ensure_kb_gitignore(project_root)
    _run_git(project_root, "add", "-A", ".", check=True)
    staged = _run_git(project_root, "diff", "--cached", "--name-only", check=False)
    staged_files = [line.strip() for line in staged.stdout.splitlines() if line.strip()]
    if not staged_files:
        return {"committed": False, "status": "no-changes", "message": "no kb changes to commit"}
    commit = _run_git(project_root, "commit", "-m", message, check=False)
    if commit.returncode != 0:
        stderr = commit.stderr.strip() or commit.stdout.strip() or "git commit failed"
        raise SystemExit(stderr)
    head = _run_git(project_root, "rev-parse", "--short", "HEAD", check=False)
    return {
        "committed": True,
        "status": "committed",
        "trigger": trigger,
        "message": message,
        "commit": head.stdout.strip(),
        "files": staged_files,
    }


def maybe_auto_checkpoint(project_root: Path, *, trigger: str, message: str) -> dict[str, Any]:
    prefs = load_runtime_preferences(project_root)
    versioning = prefs.get("versioning", {})
    if not isinstance(versioning, dict) or not versioning.get("enabled", True):
        return {"committed": False, "status": "disabled"}
    mode = str(versioning.get("auto_commit_mode") or "milestone")
    commit_on_browser_save = bool(versioning.get("commit_on_browser_save"))
    should_commit = False
    if trigger == "manual":
        should_commit = True
    elif trigger == "milestone":
        should_commit = mode in {"milestone", "aggressive"}
    elif trigger == "browser-save":
        should_commit = mode == "aggressive" or commit_on_browser_save
    if not should_commit:
        return {"committed": False, "status": "skipped", "reason": f"trigger `{trigger}` disabled for mode `{mode}`"}

    if not kb_repo_exists(project_root):
        if versioning.get("auto_init_repo", True):
            ensure_kb_git_repo(project_root, create_initial_commit=False)
        else:
            return {"committed": False, "status": "missing-repo", "reason": "kb git repo is not initialized"}

    if trigger == "browser-save":
        state = load_versioning_state(project_root)
        last_commit_at = parse_iso_datetime(state.get("last_auto_commit_at"))
        debounce_seconds = int(versioning.get("debounce_seconds") or 0)
        if last_commit_at is not None and debounce_seconds > 0:
            elapsed = (datetime.now(timezone.utc) - last_commit_at.astimezone(timezone.utc)).total_seconds()
            if elapsed < debounce_seconds:
                return {
                    "committed": False,
                    "status": "debounced",
                    "reason": f"last browser-save commit was {elapsed:.1f}s ago",
                }

    result = git_checkpoint(project_root, message, trigger=trigger, auto_init=False)
    if result.get("committed"):
        state = load_versioning_state(project_root)
        state["last_auto_commit_at"] = utc_now_iso()
        state["last_trigger"] = trigger
        state["last_commit"] = result.get("commit", "")
        history = [item for item in state.get("history", []) if isinstance(item, dict)]
        history.append(
            {
                "timestamp": state["last_auto_commit_at"],
                "trigger": trigger,
                "commit": result.get("commit", ""),
                "message": message,
            }
        )
        state["history"] = history[-50:]
        write_versioning_state(project_root, state)
    return result


def checkpoint_and_report(project_root: Path, *, trigger: str, message: str) -> dict[str, Any]:
    checkpoint = maybe_auto_checkpoint(project_root, trigger=trigger, message=message)
    if checkpoint.get("committed"):
        print(f"[ok] git checkpoint: {checkpoint.get('commit')}")
    return checkpoint


__all__ = [
    "load_versioning_state",
    "write_versioning_state",
    "kb_repo_path",
    "kb_repo_exists",
    "_run_git",
    "_git_head_exists",
    "ensure_kb_git_repo",
    "kb_git_status",
    "kb_git_log",
    "git_checkpoint",
    "maybe_auto_checkpoint",
    "checkpoint_and_report",
]
