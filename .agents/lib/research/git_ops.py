"""KB git repository management, checkpoints, and versioning state."""
from __future__ import annotations

import subprocess
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Sequence

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
    passage_search_cache_path,
    versioning_state_path,
)
from .journal import (
    JOURNAL_DIRNAME,
    _assert_no_incomplete_root,
    _preflight_journal_envelopes,
    _recovery_journaled_op,
    _recovery_workspace_scope,
    _target_key,
    committed_ops,
    incomplete_ops,
    journal_runtime_lock,
    journaled_op,
    latest_committed_op,
    load_op,
    load_op_view,
    mark_op_undone,
    operation_lock,
    restore_before_snapshots,
    restorable_committed_ops,
    target_path,
    target_digest,
    terminalize_resumed_op,
    validated_recovery_target_keys,
    workspace_transaction_lock,
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
    _preflight_journal_envelopes(project_root)
    with workspace_transaction_lock(project_root):
        _assert_no_incomplete_root(project_root)
        return _ensure_kb_git_repo_locked(
            project_root,
            create_initial_commit=create_initial_commit,
            initial_message=initial_message,
        )


def _ensure_kb_git_repo_locked(
    project_root: Path,
    *,
    create_initial_commit: bool,
    initial_message: str,
) -> dict[str, Any]:
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
    _preflight_journal_envelopes(project_root)
    with workspace_transaction_lock(project_root):
        _assert_no_incomplete_root(project_root)
        return _git_checkpoint_locked(
            project_root,
            message,
            trigger=trigger,
            auto_init=auto_init,
            scoped_paths=scoped_paths,
        )


def _git_checkpoint_locked(
    project_root: Path,
    message: str,
    *,
    trigger: str,
    auto_init: bool,
    scoped_paths: Sequence[str],
) -> dict[str, Any]:
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

    _preflight_journal_envelopes(project_root)
    if not kb_repo_exists(project_root):
        if versioning.get("auto_init_repo", True):
            ensure_kb_git_repo(project_root, create_initial_commit=False)
        else:
            return {"committed": False, "status": "missing-repo", "reason": "kb git repo is not initialized"}

    state_path = versioning_state_path(project_root)
    with workspace_transaction_lock(project_root):
        _assert_no_incomplete_root(project_root)
        with operation_lock(project_root, state_path):
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
            path = (project_root / path) if path.parts[:1] == ("kb",) else (repo / path)
        try:
            relative_path = _target_key(project_root, path)
        except SystemExit as exc:
            raise SystemExit("Checkpoint target must be a safe lexical path inside kb/.") from exc
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


def restore_operation(project_root: Path, op_id: str, *, recovery_type: str = "restore") -> dict[str, Any]:
    if recovery_type in {"restore", "undo"}:
        return _restore_committed_range(project_root, op_id, recovery_type=recovery_type)
    with workspace_transaction_lock(project_root):
        # The source journal is mutable runtime state.  Load and validate its
        # authoritative bytes only after obtaining the workspace lease; every
        # target lock and the recovery journal derive from this one view.
        entry, source_digest = load_op_view(project_root, op_id)
        state = str(entry.get("state") or "")
        if state == "abort" and recovery_type == "resume" and entry.get("resumed_by"):
            return {
                "op_id": op_id,
                "recovery_op_id": str(entry.get("resumed_by") or ""),
                "restored_paths": [],
                "checkpoint": {"committed": False, "status": "already-resumed"},
                "status": "already-resumed",
            }
        if state != "commit" and not (state == "begin" and recovery_type == "resume"):
            raise SystemExit("只有已完成的操作可恢复；未完成操作只能通过 kb resume 自愈。")
        keys = validated_recovery_target_keys(
            project_root,
            entry,
            require_after=state == "commit",
        )
        target_paths = [target_path(project_root, key) for key in keys]
        incomplete_roots = incomplete_ops(project_root)
        newest_incomplete_id = (
            str(incomplete_roots[0].get("op_id") or "")
            if incomplete_roots
            else ""
        )
        if state == "begin" and op_id != newest_incomplete_id:
            raise SystemExit("未完成操作必须按从新到旧的顺序恢复；已停止恢复。")
        if state == "commit" and incomplete_roots:
            raise SystemExit("检测到未完成的知识库操作；请先使用 kb resume 完成恢复。")
        with ExitStack() as locks:
            for path in sorted(target_paths, key=lambda item: item.as_posix()):
                locks.enter_context(operation_lock(project_root, path))
            if state == "commit":
                after_digests = entry["after_digests"]
                changed_after_operation = [
                    key
                    for key in keys
                    if target_digest(project_root, key) != after_digests.get(key)
                ]
                if changed_after_operation:
                    raise SystemExit("目标在该操作完成后又被修改；为避免覆盖后续改动，已停止恢复。")
            _, locked_source_digest = load_op_view(project_root, op_id)
            if locked_source_digest != source_digest:
                raise SystemExit("恢复来源操作日志在执行前发生变化；已停止恢复。")
            with _recovery_journaled_op(
                project_root,
                f"{recovery_type}:{op_id}",
                target_paths,
            ) as recovery_op_id:
                restored = restore_before_snapshots(
                    project_root,
                    op_id,
                    source_entry=entry,
                )
            # Journal commit must succeed before Git advances.  If commit_op fails,
            # journaled_op restores the pre-recovery bytes and no checkpoint exists.
            with _recovery_workspace_scope():
                checkpoint = git_checkpoint(
                    project_root,
                    f"recovery: {recovery_type} {op_id}",
                    trigger="manual",
                    auto_init=False,
                    target_paths=restored,
                )
            if state == "begin":
                terminalize_resumed_op(
                    project_root,
                    op_id,
                    source_entry=entry,
                    source_digest=source_digest,
                    recovery_op_id=recovery_op_id,
                )
            if recovery_type == "undo":
                mark_op_undone(project_root, op_id, recovery_op_id)
    return {
        "op_id": op_id,
        "recovery_op_id": recovery_op_id,
        "restored_paths": [path.relative_to(kb_repo_path(project_root).resolve()).as_posix() for path in restored],
        "checkpoint": checkpoint,
    }


def _committed_root_ops(project_root: Path) -> list[dict[str, Any]]:
    """Return changed committed roots, including internal and recovery roots.

    Public recovery candidates intentionally exclude non-undoable bookkeeping,
    previously consumed business operations, and recovery journals.  Those roots
    still changed canonical targets, however, so a historical rewind must replay
    them to prove a continuous after->before digest chain.  Descendants stay out:
    their mutations are already covered by the authoritative root before-image.
    """
    roots: list[dict[str, Any]] = []
    for entry in committed_ops(project_root):
        op_id = str(entry.get("op_id") or "")
        parent_op_id = str(entry.get("parent_op_id") or "")
        root_op_id = str(entry.get("root_op_id") or op_id)
        if op_id and not parent_op_id and root_op_id == op_id:
            roots.append(entry)
    return roots


_UNKNOWN_RECOVERY_DIGEST = object()


def _target_keys_overlap(first: str, second: str) -> bool:
    """Return whether two canonical journal keys have an ancestor relation."""
    first_parts = PurePosixPath(first).parts
    second_parts = PurePosixPath(second).parts
    shorter = min(len(first_parts), len(second_parts))
    return first_parts[:shorter] == second_parts[:shorter]


def _recovery_envelope_keys(keys: set[str]) -> list[str]:
    """Collapse an overlapping union to the topmost non-overlapping envelopes."""
    envelopes: list[str] = []
    for key in sorted(keys, key=lambda item: (len(PurePosixPath(item).parts), item)):
        if any(_target_keys_overlap(envelope, key) for envelope in envelopes):
            continue
        envelopes.append(key)
    return envelopes


def _restore_committed_range(
    project_root: Path,
    op_id: str,
    *,
    recovery_type: str = "restore",
) -> dict[str, Any]:
    """Atomically rewind every committed root from a selectable operation onward."""
    with workspace_transaction_lock(project_root):
        if incomplete_ops(project_root):
            raise SystemExit("检测到未完成的知识库操作；请先使用 kb resume 完成恢复。")
        if recovery_type == "undo" and not op_id:
            # Re-select under the authoritative workspace lock.  The optimistic
            # read in undo_last_operation exists only to keep the no-candidate
            # path byte-identical and must not decide what a concurrent undo uses.
            op_id = str(latest_committed_op(project_root).get("op_id") or "")
        candidate_ids = [
            str(entry.get("op_id") or "")
            for entry in restorable_committed_ops(project_root)
        ]
        if op_id not in candidate_ids:
            raise SystemExit(f"Operation is not undoable: {op_id}")
        selected_candidate_ids = candidate_ids[candidate_ids.index(op_id) :]

        root_ids = [str(entry.get("op_id") or "") for entry in _committed_root_ops(project_root)]
        if op_id not in root_ids:
            raise SystemExit("指定操作缺少完整的根操作恢复记录；已停止恢复。")
        rewind_ids = root_ids[root_ids.index(op_id) :]
        source_views = [(source_id, *load_op_view(project_root, source_id)) for source_id in rewind_ids]
        keys_by_id: dict[str, list[str]] = {}
        union_keys: set[str] = set()
        disposable_recovery_keys = {
            _target_key(project_root, passage_search_cache_path(project_root))
        }
        for source_id, entry, _source_digest in source_views:
            if str(entry.get("state") or "") != "commit":
                raise SystemExit("只有已完成的根操作才能进入恢复链。")
            validated_keys = validated_recovery_target_keys(project_root, entry, require_after=True)
            keys = [key for key in validated_keys if key not in disposable_recovery_keys]
            keys_by_id[source_id] = keys
            union_keys.update(keys)
        target_paths = [target_path(project_root, key) for key in sorted(union_keys)]
        recovery_target_paths = [
            target_path(project_root, key) for key in _recovery_envelope_keys(union_keys)
        ]
        with ExitStack() as locks:
            for path in sorted(target_paths, key=lambda item: item.as_posix()):
                locks.enter_context(operation_lock(project_root, path))

            # Prove every exact-key segment before creating a recovery journal.
            # A directory digest cannot be derived by assigning the recorded
            # before digest of one descendant (and vice versa), so overlapping
            # scopes become unknown until the real reverse replay below.
            virtual: dict[str, str | None | object] = {
                key: target_digest(project_root, key) for key in union_keys
            }
            for source_id, entry, _source_digest in reversed(source_views):
                keys = keys_by_id[source_id]
                after_digests = entry["after_digests"]
                if any(
                    virtual[key] is not _UNKNOWN_RECOVERY_DIGEST
                    and virtual[key] != after_digests.get(key)
                    for key in keys
                ):
                    raise SystemExit(
                        "当前状态与已记录的恢复链不一致；可能存在未记账修改或日志损坏，"
                        "为避免覆盖现有内容，已停止恢复。"
                    )
                before_digests = entry["before_digests"]
                key_set = set(keys)
                for union_key in union_keys - key_set:
                    if any(_target_keys_overlap(union_key, key) for key in keys):
                        virtual[union_key] = _UNKNOWN_RECOVERY_DIGEST
                for key in keys:
                    virtual[key] = before_digests.get(key)

            for source_id, _entry, source_digest in source_views:
                _, locked_digest = load_op_view(project_root, source_id)
                if locked_digest != source_digest:
                    raise SystemExit("恢复来源操作日志在执行前发生变化；已停止恢复。")

            restored_by_key: dict[str, Path] = {}
            with _recovery_journaled_op(
                project_root,
                f"{recovery_type}:{op_id}",
                recovery_target_paths,
            ) as recovery_op_id:
                for source_id, entry, _source_digest in reversed(source_views):
                    keys = keys_by_id[source_id]
                    after_digests = entry["after_digests"]
                    if any(
                        target_digest(project_root, key) != after_digests.get(key)
                        for key in keys
                    ):
                        raise SystemExit(
                            "当前状态与已记录的恢复链不一致；可能存在未记账修改或日志损坏，"
                            "为避免覆盖现有内容，已停止恢复。"
                        )
                    for restored_path in restore_before_snapshots(
                        project_root,
                        source_id,
                        source_entry=entry,
                        target_keys=keys_by_id[source_id],
                    ):
                        restored_by_key[_target_key(project_root, restored_path)] = restored_path
            restored = [restored_by_key[key] for key in sorted(restored_by_key)]
            with _recovery_workspace_scope():
                checkpoint = git_checkpoint(
                    project_root,
                    f"recovery: {recovery_type} {op_id}",
                    trigger="manual",
                    auto_init=False,
                    target_paths=restored,
                )
            for source_id in selected_candidate_ids:
                mark_op_undone(project_root, source_id, recovery_op_id)
    canonical_repo = kb_repo_path(project_root).resolve()
    return {
        "op_id": op_id,
        "restored_op_ids": selected_candidate_ids,
        "rewound_op_ids": rewind_ids,
        "recovery_op_id": recovery_op_id,
        "restored_paths": [path.relative_to(canonical_repo).as_posix() for path in restored],
        "checkpoint": checkpoint,
    }


def undo_last_operation(project_root: Path) -> dict[str, Any]:
    # Keep the no-candidate path strictly read-only: acquiring the lock creates
    # its parent journal directory and the lock file itself.  This optimistic
    # read is only a zero-write preflight; the authoritative candidate must be
    # selected again while holding the lock so concurrent undo calls serialize
    # against the latest remaining business operation.
    latest_committed_op(project_root)
    with journal_runtime_lock(project_root, ".undo.lock"):
        return _restore_committed_range(project_root, "", recovery_type="undo")


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
