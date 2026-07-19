"""KB git repository management, checkpoints, and versioning state."""
from __future__ import annotations

import hashlib
import subprocess
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from .common import (
    ensure_dir,
    exclusive_file_lock,
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
from .journal import (
    JOURNAL_DIRNAME,
    journal_root,
    journaled_op,
    latest_committed_op,
    load_op,
    mark_op_undone,
    operation_lock_path,
    restore_before_snapshots,
    target_path,
    workspace_transaction_lock_path,
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
        checkpoint = git_checkpoint(
            project_root,
            initial_message,
            trigger="manual",
            auto_init=False,
            target_paths=dirty_kb_paths(project_root),
        )
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
    target_paths: Sequence[Path | str] | None = None,
) -> dict[str, Any]:
    scoped_paths = _normalize_git_paths(project_root, target_paths)
    ensure_workspace(project_root)
    if not kb_repo_exists(project_root):
        if auto_init:
            ensure_kb_git_repo(project_root, create_initial_commit=False)
        else:
            return {"committed": False, "status": "missing-repo", "message": "kb git repo is not initialized"}
    ensure_kb_gitignore(project_root)
    checkpointable_paths, addable_paths = _checkpointable_git_paths(project_root, scoped_paths)
    if not checkpointable_paths:
        return {"committed": False, "status": "no-changes", "message": "no checkpointable kb changes to commit"}
    pathspecs = [_literal_git_pathspec(path) for path in checkpointable_paths]
    if addable_paths:
        addable_pathspecs = [_literal_git_pathspec(path) for path in addable_paths]
        _run_git(project_root, "add", "--all", "--", *addable_pathspecs, check=True)
    staged = _run_git(project_root, "diff", "--cached", "--name-only", "--", *pathspecs, check=False)
    staged_files = [line.strip() for line in staged.stdout.splitlines() if line.strip()]
    if not staged_files:
        return {"committed": False, "status": "no-changes", "message": "no kb changes to commit"}
    commit_args = ["commit", "-m", message]
    commit_args.extend(["--only", "--", *pathspecs])
    commit = _run_git(project_root, *commit_args, check=False)
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


def maybe_auto_checkpoint(
    project_root: Path,
    *,
    trigger: str,
    message: str,
    target_paths: Sequence[Path | str] | None = None,
) -> dict[str, Any]:
    scoped_paths = _normalize_git_paths(project_root, target_paths)
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

    state_path = versioning_state_path(project_root)
    with exclusive_file_lock(workspace_transaction_lock_path(project_root)):
        with exclusive_file_lock(operation_lock_path(project_root, state_path)):
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

            result = git_checkpoint(
                project_root,
                message,
                trigger=trigger,
                auto_init=False,
                target_paths=scoped_paths,
            )
            if result.get("committed"):
                with journaled_op(
                    project_root,
                    "write_versioning_state",
                    [state_path],
                    undoable=False,
                    operation_role="bookkeeping",
                    coordination_scope="workspace-exclusive",
                ):
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


def checkpoint_and_report(
    project_root: Path,
    *,
    trigger: str,
    message: str,
    target_paths: Sequence[Path | str] | None = None,
) -> dict[str, Any]:
    scoped_paths = _normalize_git_paths(project_root, target_paths)
    checkpoint = maybe_auto_checkpoint(
        project_root,
        trigger=trigger,
        message=message,
        target_paths=scoped_paths,
    )
    if checkpoint.get("committed"):
        print(f"[ok] git checkpoint: {checkpoint.get('commit')}")
    return checkpoint


def _normalize_git_paths(
    project_root: Path,
    target_paths: Sequence[Path | str] | None,
) -> list[str]:
    if not target_paths:
        raise SystemExit("Checkpoint requires a non-empty explicit target_paths scope.")
    repo = kb_repo_path(project_root).resolve()
    normalized: set[str] = set()
    for raw_path in target_paths:
        if not str(raw_path).strip():
            raise SystemExit("Checkpoint target paths cannot contain empty values.")
        path = Path(raw_path)
        if not path.is_absolute():
            project_candidate = (project_root / path).resolve()
            repo_candidate = (repo / path).resolve()
            path = project_candidate if project_candidate.is_relative_to(repo) else repo_candidate
        else:
            path = path.resolve()
        try:
            relative_path = path.relative_to(repo).as_posix()
        except ValueError as exc:
            raise SystemExit(f"Checkpoint target must be inside kb/: {raw_path}") from exc
        if relative_path in {"", "."}:
            raise SystemExit("Checkpoint target cannot be the whole kb/ repository.")
        if relative_path == JOURNAL_DIRNAME or relative_path.startswith(f"{JOURNAL_DIRNAME}/"):
            raise SystemExit("Checkpoint targets cannot include the ignored operation journal.")
        if relative_path == ".git" or relative_path.startswith(".git/"):
            raise SystemExit("Checkpoint targets cannot include kb/.git metadata.")
        normalized.add(relative_path)
    if not normalized:
        raise SystemExit("Checkpoint requires a non-empty explicit target_paths scope.")
    return sorted(normalized)


def dirty_kb_paths(project_root: Path) -> list[Path]:
    """Return every dirty KB file as an explicit literal checkpoint target.

    This is intentionally separate from :func:`git_checkpoint`: callers such as
    the user-requested manual checkpoint verb may choose to checkpoint the whole
    dirty worktree, but the checkpoint primitive itself never broadens an absent
    scope into a repository-wide add.
    """
    if not kb_repo_exists(project_root):
        return []
    relative_paths: set[str] = set()
    commands = [
        ("diff", "--name-only", "-z"),
        ("diff", "--cached", "--name-only", "-z"),
        ("ls-files", "--others", "--exclude-standard", "-z"),
    ]
    for args in commands:
        result = _run_git(project_root, *args, check=False)
        if result.returncode != 0:
            detail = result.stderr.strip() or result.stdout.strip() or "git status query failed"
            raise SystemExit(detail)
        relative_paths.update(item for item in result.stdout.split("\0") if item)
    repo = kb_repo_path(project_root)
    return [repo / relative_path for relative_path in sorted(relative_paths)]


def _literal_git_pathspec(relative_path: str) -> str:
    return f":(top,literal){relative_path}"


def _git_query_has_paths(project_root: Path, *args: str) -> bool:
    result = _run_git(project_root, *args, check=False)
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or "git path query failed"
        raise SystemExit(detail)
    return bool(result.stdout)


def _git_path_has_index_or_untracked_entry(project_root: Path, relative_path: str) -> bool:
    """Whether a literal scope currently contains an index or unignored file."""
    return _git_query_has_paths(
        project_root,
        "ls-files",
        "--cached",
        "--others",
        "--exclude-standard",
        "--",
        _literal_git_pathspec(relative_path),
    )


def _git_path_has_staged_change(project_root: Path, relative_path: str) -> bool:
    """Include a deletion already removed from the index but tracked by HEAD."""
    return _git_query_has_paths(
        project_root,
        "diff",
        "--cached",
        "--name-only",
        "--",
        _literal_git_pathspec(relative_path),
    )


def _checkpointable_git_paths(
    project_root: Path,
    scoped_paths: Sequence[str],
) -> tuple[list[str], list[str]]:
    """Return the declared scope that Git can act on without broadening it.

    A transaction may conservatively declare outputs that it does not generate in
    every run. Git pathspec commands receive only scopes for which Git can enumerate
    an index entry, an unignored untracked entry, or a staged change. This keeps
    tracked deletions checkpointable while empty directories, ignored-only
    directories, and missing never-tracked outputs remain silent no-ops.

    The second result contains scopes that can safely be passed to ``git add``.
    A deletion already staged out of the index is checkpointable but not addable.
    """
    checkpointable: list[str] = []
    addable: list[str] = []
    for relative_path in scoped_paths:
        has_entry = _git_path_has_index_or_untracked_entry(project_root, relative_path)
        has_staged_change = _git_path_has_staged_change(project_root, relative_path)
        if not has_entry and not has_staged_change:
            continue
        checkpointable.append(relative_path)
        if has_entry:
            addable.append(relative_path)
    return checkpointable, addable


def _git_digest_at_revision(project_root: Path, revision: str, relative_path: str) -> str | None:
    result = _run_git(project_root, "show", f"{revision}:{relative_path}", check=False)
    if result.returncode != 0:
        return None
    return hashlib.sha256(result.stdout.encode("utf-8")).hexdigest()


def _find_revision_for_digests(project_root: Path, digests: dict[str, Any]) -> str:
    revisions = _run_git(project_root, "rev-list", "HEAD", check=False)
    for revision in [line.strip() for line in revisions.stdout.splitlines() if line.strip()]:
        if all(_git_digest_at_revision(project_root, revision, path) == digest for path, digest in digests.items()):
            return revision
    raise SystemExit("无法在知识库版本历史中找到该操作之前的状态。")


def _restore_paths_from_revision(
    project_root: Path,
    revision: str,
    before_digests: dict[str, Any],
) -> list[Path]:
    restored: list[Path] = []
    for relative_path, digest in before_digests.items():
        target = target_path(project_root, relative_path)
        if digest is None:
            if target.exists():
                target.unlink()
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            _run_git(project_root, "restore", f"--source={revision}", "--worktree", "--", relative_path, check=True)
        restored.append(target)
    return restored


def restore_operation(project_root: Path, op_id: str, *, recovery_type: str = "restore") -> dict[str, Any]:
    entry = load_op(project_root, op_id)
    before_digests = entry.get("before_digests", {})
    if not isinstance(before_digests, dict) or not before_digests:
        raise SystemExit(f"操作 {op_id} 没有可恢复的目标。")
    target_paths = [target_path(project_root, path) for path in before_digests]
    has_snapshots = isinstance(entry.get("before_snapshots"), dict) and bool(entry.get("before_snapshots"))
    with exclusive_file_lock(workspace_transaction_lock_path(project_root)):
        with ExitStack() as locks:
            for path in sorted(target_paths, key=lambda item: item.as_posix()):
                locks.enter_context(exclusive_file_lock(operation_lock_path(project_root, path)))
            with journaled_op(
                project_root,
                f"{recovery_type}:{op_id}",
                target_paths,
                undoable=False,
                operation_role="recovery",
                coordination_scope="workspace-exclusive",
                attach_to_active=False,
            ) as recovery_op_id:
                if has_snapshots:
                    restored = restore_before_snapshots(project_root, op_id)
                else:
                    if not kb_repo_exists(project_root) or not _git_head_exists(project_root):
                        raise SystemExit("知识库版本历史尚未初始化，且旧操作没有字节快照，无法恢复。")
                    revision = _find_revision_for_digests(project_root, before_digests)
                    restored = _restore_paths_from_revision(project_root, revision, before_digests)
            # Journal commit must succeed before Git advances.  If commit_op fails,
            # journaled_op restores the pre-recovery bytes and no checkpoint exists.
            checkpoint = git_checkpoint(
                project_root,
                f"recovery: {recovery_type} {op_id}",
                trigger="manual",
                auto_init=False,
                target_paths=restored,
            )
    if recovery_type == "undo":
        mark_op_undone(project_root, op_id, recovery_op_id)
    return {
        "op_id": op_id,
        "recovery_op_id": recovery_op_id,
        "restored_paths": [path.relative_to(kb_repo_path(project_root)).as_posix() for path in restored],
        "checkpoint": checkpoint,
    }


def undo_last_operation(project_root: Path) -> dict[str, Any]:
    with exclusive_file_lock(journal_root(project_root) / ".undo.lock"):
        entry = latest_committed_op(project_root)
        return restore_operation(project_root, str(entry["op_id"]), recovery_type="undo")


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
    "dirty_kb_paths",
    "git_checkpoint",
    "maybe_auto_checkpoint",
    "checkpoint_and_report",
    "restore_operation",
    "undo_last_operation",
]
