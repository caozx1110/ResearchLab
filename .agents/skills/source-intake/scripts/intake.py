#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
for candidate in [SCRIPT_PATH.parent, *SCRIPT_PATH.parents]:
    lib = candidate / ".agents" / "lib"
    if lib.exists():
        sys.path.insert(0, str(lib))
        PROJECT_ROOT = candidate
        break
else:
    raise SystemExit("Could not locate .agents/lib")

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.common import add_project_root_argument, confirm_command as shared_confirm_command, extract_pdf_record, load_yaml, parse_arxiv_id, print_resolved_project_roots, skill_script_for_command
from research.confirm import require_user_authorization
from research.journal import journal_subprocess_env, mutation_transaction
from research.intake_cli import add_intake_add_arguments
from research.preference_selection import operation_contract, resolve_operation_preferences
from research.core import (
    apply_record_governance,
    append_history,
    backup_source,
    build_index,
    candidate_pools_path,
    default_record,
    detect_duplicate,
    ensure_workspace,
    load_search_stage,
    locate_record,
    mark_search_candidate,
    checkpoint_and_report,
    kb_root,
    normalize_storage_reference,
    project_root,
    resolve_local_reference,
    resolve_search_candidate,
    search_stage_path,
    rebase_source_backup_paths,
    source_backup_error,
    source_record_fields,
    stage_search_results,
    unit_root,
    topic_taxonomy_path,
    UnsafeLocalSourceError,
    validate_local_source,
    write_parse_cache,
    write_record,
)
from research.surveys import literature_candidate_identity_digest


def infer_title(source: str) -> str:
    if source.startswith("http"):
        return source.rstrip("/").split("/")[-1] or source
    return Path(source).stem.replace("_", " ")


def research_python() -> str:
    return os.environ.get("RESEARCH_PYTHON") or sys.executable or "python3"


def confirm_command(record: dict) -> str:
    python = research_python()
    return shared_confirm_command(record, command_prefix=python, direct_kinds=("paper", "repo", "dataset", "blog"))


def infer_paper_metadata(root: Path, source: str) -> dict:
    if source.startswith("http"):
        return {}
    path = resolve_local_reference(root, source) or Path(source).expanduser()
    if not path.exists() or path.suffix.lower() != ".pdf":
        return {}
    try:
        return extract_pdf_record(path)
    except Exception:  # noqa: BLE001
        return {}


def canonical_paper_source_url(source: str, metadata: dict) -> str:
    arxiv_id = str(metadata.get("arxiv_id") or parse_arxiv_id(source) or "").strip()
    arxiv_id = arxiv_id.split("v", 1)[0] if arxiv_id else ""
    if arxiv_id:
        return f"https://arxiv.org/abs/{arxiv_id}"
    return source if source.startswith("http") else ""


def run_paper_command(root: Path, *args: str) -> list[str]:
    cmd = [
        research_python(),
        skill_script_for_command(".agents/skills/paper-analyst/scripts/paper.py", cwd=root),
        "--root",
        str(root),
        *args,
    ]
    result = subprocess.run(
        cmd,
        cwd=root,
        env=journal_subprocess_env(root),
        text=True,
        capture_output=True,
        check=False,
    )
    output = [
        line.strip()
        for line in (result.stdout.splitlines() + result.stderr.splitlines())
        if line.strip()
    ]
    if result.returncode != 0:
        raise SystemExit("\n".join(output) or f"paper command failed: {' '.join(cmd)}")
    return output


def guidance_hints(kind: str, preferences: dict, *, has_pdf: bool, note_created: bool) -> list[str]:
    if kind == "paper":
        next_step = "已入库并备好初筛，下一步：运行 kb next，或让 AI 用逐字证据完成类型与深读判断。"
    elif kind == "repo":
        next_step = "已入库，下一步：运行 kb next，或让 AI 扫描结构并判断复用价值。"
    elif kind == "blog":
        next_step = "已入库，下一步：运行 kb next，或让 AI 总结要点并标出可信度。"
    else:
        next_step = "已入库，下一步：运行 kb next 查看主线推进建议。"
    hints = [next_step]
    if kind != "paper":
        return hints
    if not bool(preferences.get("prompt_for_preference_updates", True)):
        return hints
    optional_hints = [
        "可选：如需查看当前文献入库默认模式，可直接询问 AI。",
    ]
    if not bool(preferences.get("auto_complete_note")):
        optional_hints.append(
            "可选：如需让值得读的论文默认自动生成完整笔记，可告诉 AI 调整该偏好。"
        )
    if note_created and str(preferences.get("complete_note_mode") or "scaffold") != "draft":
        optional_hints.append(
            "可选：如需默认直接生成更饱满的 draft，可告诉 AI 调整完整笔记模式。"
        )
    if has_pdf and not bool(preferences.get("auto_extract_figures_after_note")):
        optional_hints.append(
            "可选：如需完整笔记后自动提取 Figure / Table，可告诉 AI 开启该偏好。"
        )
    hints.extend(optional_hints[:2])
    return hints


# kind -> (analyzer skill script, prepare verb, id flag). Used only to build the
# machine-readable NEXT FOR AGENT navigation line (SSOT §7); no judgement here.
ANALYZER_PREPARE: dict[str, tuple[str, str, str]] = {
    "paper": (".agents/skills/paper-analyst/scripts/paper.py", "screen", "--paper-id"),
    "repo": (".agents/skills/repo-analyst/scripts/repo.py", "map-capability", "--repo-id"),
    "dataset": (".agents/skills/dataset-analyst/scripts/dataset.py", "profile", "--dataset-id"),
    "blog": (".agents/skills/blog-analyst/scripts/blog.py", "complete-note", "--blog-id"),
}


def ingest_chain_active() -> bool:
    """Whether kb ingest owns the analyzer ordering for this intake."""
    return bool(str(os.environ.get("RESEARCH_INGEST_CHAIN") or "").strip())


def next_for_agent_intake(root: Path, kind: str, record_id: str) -> str:
    """One machine-readable navigation line after intake add (SSOT §7).

    Inside a `kb ingest` chain (RESEARCH_INGEST_CHAIN set) the chain auto-runs prepare
    next, so we say so and point at prepare's own NEXT line. Standalone, it names the
    exact analyzer prepare command the session agent should run to produce the fillable
    skeleton. Pure navigation — it authors no judgement.
    """
    if kind not in ANALYZER_PREPARE:
        return f"NEXT FOR AGENT: unit {record_id} landed; run the matching analyzer prepare, then fill + verify."
    if ingest_chain_active():
        return (
            f"NEXT FOR AGENT: intake done for {record_id}; kb ingest auto-continues to {kind} prepare "
            f"— read that prepare's NEXT FOR AGENT line to fill elements + verify."
        )
    script, verb, id_flag = ANALYZER_PREPARE[kind]
    resolved = skill_script_for_command(script, cwd=root)
    prepare_cmd = f"{research_python()} {resolved} --root {root} {verb} {id_flag} {record_id} --phase prepare"
    return f"NEXT FOR AGENT: run {kind} prepare (fillable skeleton) then fill + verify: {prepare_cmd}"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest a source into the knowledge base.")
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    add = subparsers.add_parser("add", help="Add a paper, repo, dataset, or blog source")
    add_intake_add_arguments(add, include_stage_options=True)
    add.add_argument("--user-authorization", default="")
    add.add_argument("--authorization-source", default="")
    add.add_argument("--preference-selection-id", default="")
    add.add_argument("--prepared-intake-token", default="")

    prepare = subparsers.add_parser(
        "prepare-add",
        help="Privately freeze one intake snapshot before Agent preference selection",
    )
    add_intake_add_arguments(prepare, include_stage_options=True)
    prepare.add_argument("--user-authorization", default="")
    prepare.add_argument("--authorization-source", default="")

    for search_name in ("search", "stage-search"):
        stage = subparsers.add_parser(search_name, help="Record search candidates before canonical intake")
        stage.add_argument("--kind", required=True, choices=["repo", "dataset", "blog"])
        stage.add_argument("--query", required=True)
        stage.add_argument("--stage-id", default="")
        stage.add_argument("--candidate-url", action="append", default=[])
        stage.add_argument("--candidate-title", action="append", default=[])
        stage.add_argument("--note", default="")

    show = subparsers.add_parser("show-stage", help="Inspect a recorded search stage")
    show.add_argument("--stage-id", required=True)
    return parser


def _canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def intake_preference_context(
    args: argparse.Namespace,
    *,
    source: str,
    title: str,
    canonical_pools: list[str] | None = None,
    source_content_digest: str = "",
    source_input_digest: str = "",
    candidate_binding_digest: str = "",
    prepared_record_digest: str = "",
) -> dict[str, object]:
    """Canonical source-intake inputs used to bind an effective selection."""
    return {
        "kind": str(args.kind),
        "source": str(source),
        "title": str(title),
        "maturity": str(args.maturity),
        "stage_id": str(args.stage_id or ""),
        "candidate_id": str(args.candidate_id or ""),
        "canonical_pools": sorted(
            {str(item).strip() for item in canonical_pools or [] if str(item).strip()}
        ),
        "source_content_digest": str(source_content_digest),
        "source_input_digest": str(source_input_digest),
        "candidate_binding_digest": str(candidate_binding_digest),
        "prepared_record_digest": str(prepared_record_digest),
        # Authorization text can contain sensitive user wording.  Bind its
        # canonical value without ever copying it into a preference receipt.
        "authorization_digest": _canonical_digest(
            {
                "user_authorization": str(
                    getattr(args, "user_authorization", "") or ""
                ).strip(),
                "authorization_source": str(
                    getattr(args, "authorization_source", "") or ""
                ).strip(),
            }
        ),
    }


def resolve_intake_preferences(
    root: Path,
    args: argparse.Namespace,
    *,
    source: str,
    title: str,
    canonical_pools: list[str] | None = None,
    canonical_inputs: dict[str, object] | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    """Return selected runtime.paper values plus value-free task preference state."""
    selection_id = str(getattr(args, "preference_selection_id", "") or "")
    context = canonical_inputs or intake_preference_context(
        args,
        source=source,
        title=title,
        canonical_pools=canonical_pools,
    )
    effective = resolve_operation_preferences(
        root,
        selection_id=selection_id,
        skill="source-intake",
        operation="add",
        canonical_inputs=context,
    )
    selected = dict(effective.get("values_by_path") or {})
    raw = selected.get("runtime.paper")
    state = {
        "task_context_digest": str(effective.get("task_context_digest") or ""),
        "selection_binding": dict(effective.get("binding") or {}),
        "hard_value_digests": dict(effective.get("hard_value_digests") or {}),
    }
    return (dict(raw) if str(args.kind) == "paper" and isinstance(raw, dict) else {}), state


def stage_candidates(args: argparse.Namespace) -> list[dict]:
    titles = list(args.candidate_title)
    candidates = []
    for index, url in enumerate(args.candidate_url):
        title = titles[index] if index < len(titles) else ""
        candidates.append({"title": title, "url": url})
    return candidates


PREPARED_INTAKE_SCHEMA = 1
PREPARED_TOKEN_PATTERN = re.compile(r"[0-9a-f]{32}")
PREPARED_INTAKE_TTL_SECONDS = 60 * 60
PREPARED_MAX_ENTRIES = 100_000
PREPARED_MAX_TOTAL_BYTES = 8 * 1024 * 1024 * 1024
PREPARED_MAX_DEPTH = 64


def _stream_regular_file(descriptor: int) -> tuple[dict[str, object], str]:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("prepared intake contains a non-regular file")
    digest = hashlib.sha256()
    with os.fdopen(os.dup(descriptor), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    after = os.fstat(descriptor)
    stable_fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_uid",
        "st_gid",
        "st_size",
        "st_mtime_ns",
    )
    if any(getattr(before, name) != getattr(after, name) for name in stable_fields):
        raise ValueError("prepared intake source changed while it was read")
    return (
        {
            "device": before.st_dev,
            "inode": before.st_ino,
            "mode": stat.S_IMODE(before.st_mode),
            "uid": before.st_uid,
            "gid": before.st_gid,
            "size": before.st_size,
            "mtime_ns": before.st_mtime_ns,
        },
        digest.hexdigest(),
    )


def _directory_snapshot(
    descriptor: int,
    relative: Path,
    rows: list[dict[str, object]],
    budget: dict[str, int],
) -> None:
    try:
        entries = sorted(os.scandir(descriptor), key=lambda item: item.name)
    except OSError as exc:
        raise ValueError("prepared intake source tree is unreadable") from exc
    for entry in entries:
        child_relative = relative / entry.name
        if len(child_relative.parts) > PREPARED_MAX_DEPTH:
            raise ValueError("prepared intake source tree exceeds the depth budget")
        budget["entries"] += 1
        if budget["entries"] > PREPARED_MAX_ENTRIES:
            raise ValueError("prepared intake source tree exceeds the entry budget")
        if entry.is_symlink():
            raise ValueError("prepared intake source tree contains a symlink")
        try:
            child_stat = os.stat(entry.name, dir_fd=descriptor, follow_symlinks=False)
        except OSError as exc:
            raise ValueError("prepared intake source tree changed while it was read") from exc
        if stat.S_ISDIR(child_stat.st_mode):
            flags = (
                os.O_RDONLY
                | getattr(os, "O_CLOEXEC", 0)
                | getattr(os, "O_DIRECTORY", 0)
                | getattr(os, "O_NOFOLLOW", 0)
            )
            try:
                child_descriptor = os.open(entry.name, flags, dir_fd=descriptor)
            except OSError as exc:
                raise ValueError("prepared intake source tree changed while it was read") from exc
            try:
                opened = os.fstat(child_descriptor)
                if (opened.st_dev, opened.st_ino) != (child_stat.st_dev, child_stat.st_ino):
                    raise ValueError("prepared intake source tree changed while it was read")
                rows.append(
                    {
                        "relative": child_relative.as_posix(),
                        "type": "directory",
                        "device": opened.st_dev,
                        "inode": opened.st_ino,
                        "mode": stat.S_IMODE(opened.st_mode),
                        "uid": opened.st_uid,
                        "gid": opened.st_gid,
                    }
                )
                _directory_snapshot(child_descriptor, child_relative, rows, budget)
            finally:
                os.close(child_descriptor)
            continue
        if not stat.S_ISREG(child_stat.st_mode):
            raise ValueError("prepared intake source tree contains a special file")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            child_descriptor = os.open(entry.name, flags, dir_fd=descriptor)
        except OSError as exc:
            raise ValueError("prepared intake source tree changed while it was read") from exc
        try:
            metadata, byte_digest = _stream_regular_file(child_descriptor)
            budget["bytes"] += int(metadata["size"])
            if budget["bytes"] > PREPARED_MAX_TOTAL_BYTES:
                raise ValueError("prepared intake source tree exceeds the byte budget")
            if (metadata["device"], metadata["inode"]) != (child_stat.st_dev, child_stat.st_ino):
                raise ValueError("prepared intake source tree changed while it was read")
            rows.append(
                {
                    "relative": child_relative.as_posix(),
                    "type": "file",
                    **metadata,
                    "sha256": byte_digest,
                }
            )
        finally:
            os.close(child_descriptor)


def _path_snapshot_digest(path: Path) -> str:
    """Stream a no-follow identity+byte digest for one file or closed tree."""
    try:
        root_stat = path.lstat()
    except OSError as exc:
        raise ValueError("prepared intake source is unavailable") from exc
    if stat.S_ISLNK(root_stat.st_mode):
        raise ValueError("prepared intake source is a symlink")
    if stat.S_ISREG(root_stat.st_mode):
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ValueError("prepared intake source changed before it was read") from exc
        try:
            metadata, byte_digest = _stream_regular_file(descriptor)
        finally:
            os.close(descriptor)
        if int(metadata["size"]) > PREPARED_MAX_TOTAL_BYTES:
            raise ValueError("prepared intake source exceeds the byte budget")
        return _canonical_digest(
            [{"relative": ".", "type": "file", **metadata, "sha256": byte_digest}]
        )
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError("prepared intake source has an unsupported type")
    flags = (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise ValueError("prepared intake source changed before it was read") from exc
    try:
        opened = os.fstat(descriptor)
        rows: list[dict[str, object]] = [
            {
                "relative": ".",
                "type": "directory",
                "device": opened.st_dev,
                "inode": opened.st_ino,
                "mode": stat.S_IMODE(opened.st_mode),
                "uid": opened.st_uid,
                "gid": opened.st_gid,
            }
        ]
        _directory_snapshot(descriptor, Path(), rows, {"entries": 0, "bytes": 0})
    finally:
        os.close(descriptor)
    return _canonical_digest(rows)


def _source_input_digest(root: Path, source: str) -> str:
    if source.startswith("http"):
        return _canonical_digest({"type": "remote", "source": source})
    local = validate_local_source(root, source)
    if local is None:
        return _canonical_digest({"type": "locator", "source": source})
    return _path_snapshot_digest(local)


def _candidate_binding_digest(
    *,
    stage: dict | None,
    candidate: dict | None,
) -> str:
    if stage is None or candidate is None:
        return _canonical_digest({"state": "not_applicable"})
    return _canonical_digest(
        {
            "stage": {
                key: stage.get(key)
                for key in (
                    "id",
                    "entry_skill",
                    "source_kind",
                    "query",
                    "mode",
                    "scope",
                    "protocol_digest",
                )
            },
            "candidate": candidate,
        }
    )


def _prepared_scope(root: Path) -> str:
    return hashlib.sha256(root.resolve(strict=False).as_posix().encode("utf-8")).hexdigest()[:12]


def _prepared_dir(root: Path, token: str) -> Path:
    if not PREPARED_TOKEN_PATTERN.fullmatch(str(token or "")):
        raise SystemExit("Prepared intake token is invalid.")
    return root.resolve(strict=False).parent / f".research-intake-{_prepared_scope(root)}-{token}"


def _new_prepared_dir(root: Path) -> tuple[str, Path]:
    token = uuid.uuid4().hex
    expected = _prepared_dir(root, token)
    created = Path(
        tempfile.mkdtemp(
            prefix=f".research-intake-{_prepared_scope(root)}-{token}-creating-",
            dir=root.resolve(strict=False).parent,
        )
    )
    os.chmod(created, 0o700)
    os.replace(created, expected)
    return token, expected


def _assert_owned_private_directory(path: Path) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise SystemExit("Prepared intake snapshot is unavailable.") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise SystemExit("Prepared intake snapshot storage is unsafe.")
    if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o700:
        raise SystemExit("Prepared intake snapshot storage has unsafe ownership or permissions.")
    return metadata


def _harden_prepared_tree(path: Path) -> None:
    """Make the private staged snapshot owner-only after source conversion."""
    if path.is_symlink() or not path.is_dir():
        raise SystemExit("Prepared intake stage is unsafe.")
    for current, directories, files in os.walk(path, topdown=True, followlinks=False):
        current_path = Path(current)
        os.chmod(current_path, 0o700, follow_symlinks=False)
        for name in directories:
            child = current_path / name
            if child.is_symlink():
                raise SystemExit("Prepared intake stage contains a symlink.")
            metadata = child.lstat()
            if metadata.st_uid != os.getuid() or not stat.S_ISDIR(metadata.st_mode):
                raise SystemExit("Prepared intake stage has unsafe ownership or types.")
        for name in files:
            child = current_path / name
            metadata = child.lstat()
            if (
                metadata.st_uid != os.getuid()
                or stat.S_ISLNK(metadata.st_mode)
                or not stat.S_ISREG(metadata.st_mode)
            ):
                raise SystemExit("Prepared intake stage has unsafe ownership or types.")
            os.chmod(child, 0o600, follow_symlinks=False)


def _claim_prepared_intake(root: Path, token: str) -> None:
    prepared = _prepared_dir(root, token)
    _assert_owned_private_directory(prepared)
    directory_descriptor = os.open(
        prepared,
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_CLOEXEC", 0)
            | getattr(os, "O_NOFOLLOW", 0)
        )
        try:
            descriptor = os.open("claimed", flags, 0o600, dir_fd=directory_descriptor)
        except FileExistsError as exc:
            raise SystemExit("Prepared intake snapshot is already being consumed.") from exc
        try:
            os.write(descriptor, f"pid={os.getpid()} time={int(time.time())}\n".encode("ascii"))
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)


def _safe_remove_prepared(root: Path, token: str) -> None:
    prepared = _prepared_dir(root, token)
    try:
        prepared.lstat()
    except FileNotFoundError:
        return
    _assert_owned_private_directory(prepared)
    shutil.rmtree(prepared)


def _write_prepared_manifest(path: Path, payload: dict[str, object]) -> None:
    encoded = (json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str) + "\n").encode("utf-8")
    temporary = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_CLOEXEC", 0)
    descriptor = os.open(temporary, flags, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(encoded)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory_descriptor = os.open(
            path.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
    finally:
        os.close(descriptor)
        if temporary.exists():
            temporary.unlink()


def _read_prepared_manifest(path: Path) -> dict[str, object]:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags)
    except OSError as exc:
        raise SystemExit("Prepared intake snapshot is unavailable or unsafe.") from exc
    try:
        metadata = os.fstat(descriptor)
        if not stat.S_ISREG(metadata.st_mode):
            raise SystemExit("Prepared intake manifest is not a regular file.")
        if metadata.st_uid != os.getuid() or stat.S_IMODE(metadata.st_mode) != 0o600:
            raise SystemExit("Prepared intake manifest has unsafe ownership or permissions.")
        with os.fdopen(os.dup(descriptor), "rb") as handle:
            data = handle.read(16 * 1024 * 1024 + 1)
        if len(data) > 16 * 1024 * 1024:
            raise SystemExit("Prepared intake manifest is too large.")
    finally:
        os.close(descriptor)
    try:
        payload = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SystemExit("Prepared intake manifest is invalid.") from exc
    if not isinstance(payload, dict):
        raise SystemExit("Prepared intake manifest is invalid.")
    return payload


def _resolve_intake_request(
    root: Path,
    args: argparse.Namespace,
) -> tuple[str, str, dict, dict | None, dict | None]:
    source = str(getattr(args, "source", "") or "")
    staged_candidate: dict | None = None
    staged_search: dict | None = None
    if str(getattr(args, "stage_id", "") or "") and str(
        getattr(args, "candidate_id", "") or ""
    ):
        staged_candidate = resolve_search_candidate(root, args.stage_id, args.candidate_id)
        staged_search = load_search_stage(root, args.stage_id)
        if args.kind != str(staged_search.get("source_kind") or ""):
            raise SystemExit("A staged candidate must be materialized with its recorded source kind.")
        if staged_search.get("entry_skill") == "literature-search":
            if source:
                raise SystemExit(
                    "A selected literature candidate must be materialized from its staged source."
                )
            require_user_authorization(
                user_authorization=args.user_authorization,
                authorization_source=args.authorization_source,
            )
        source = source or str(staged_candidate.get("url") or "")
    if not source:
        raise SystemExit("Provide a source or a selected staged candidate.")
    if not source.startswith("http"):
        try:
            validate_local_source(root, source)
        except UnsafeLocalSourceError as exc:
            raise SystemExit(str(exc)) from exc
        source = normalize_storage_reference(root, source)
    paper_metadata = infer_paper_metadata(root, source) if args.kind == "paper" else {}
    title = (
        str(getattr(args, "title", "") or "")
        or (str(staged_candidate.get("title") or "") if staged_candidate else "")
        or str(paper_metadata.get("title") or "").strip()
        or infer_title(source)
    )
    return source, title, paper_metadata, staged_candidate, staged_search


def _request_binding_digest(
    args: argparse.Namespace,
    *,
    source: str,
    initial_title: str,
    source_input_digest: str,
    candidate_binding_digest: str,
) -> str:
    return _canonical_digest(
        {
            "kind": str(args.kind),
            "source": str(source),
            "initial_title": str(initial_title),
            "requested_title": str(getattr(args, "title", "") or ""),
            "maturity": str(args.maturity),
            "stage_id": str(getattr(args, "stage_id", "") or ""),
            "candidate_id": str(getattr(args, "candidate_id", "") or ""),
            "requested_pools": sorted(
                {str(item).strip() for item in getattr(args, "pool", []) if str(item).strip()}
            ),
            "authorization_digest": _canonical_digest(
                {
                    "user_authorization": str(
                        getattr(args, "user_authorization", "") or ""
                    ).strip(),
                    "authorization_source": str(
                        getattr(args, "authorization_source", "") or ""
                    ).strip(),
                }
            ),
            "source_input_digest": source_input_digest,
            "candidate_binding_digest": candidate_binding_digest,
        }
    )


def _finish_prepared_record(
    root: Path,
    args: argparse.Namespace,
    *,
    source: str,
    initial_title: str,
    paper_metadata: dict,
    staged_candidate: dict | None,
    staged_search: dict | None,
    source_info: dict,
    stage_dir: Path,
    prepared_root: Path,
) -> tuple[dict, dict, str]:
    parse_metadata = source_info.get("parse_metadata") or {}
    title = initial_title
    if args.kind == "paper" and not paper_metadata and parse_metadata:
        better_title = str(parse_metadata.get("title") or "").strip()
        paper_metadata = {
            "title": better_title,
            "abstract": str(parse_metadata.get("abstract") or ""),
            "year": parse_metadata.get("year"),
            "arxiv_id": str(parse_metadata.get("arxiv_id") or ""),
            "authors": [],
            "topics": [],
            "tags": [],
            "doi": "",
        }
        if better_title and not args.title and not (staged_candidate and staged_candidate.get("title")):
            title = better_title
    elif parse_metadata:
        better_title = str(parse_metadata.get("title") or "").strip()
        if better_title and not args.title and not (staged_candidate and staged_candidate.get("title")):
            title = better_title

    record = default_record(
        args.kind,
        title=initial_title,
        maturity=args.maturity,
        source={"original_uri": source},
    )
    if title != initial_title:
        record["title"] = title
    canonical_dir = unit_root(root, args.kind, str(record["id"]))
    mirrored_canonical_dir = prepared_root / canonical_dir.relative_to(root)
    canonical_source_info = rebase_source_backup_paths(
        prepared_root,
        source_info,
        from_unit_dir=stage_dir,
        to_unit_dir=mirrored_canonical_dir,
    )
    record["source"] = source_record_fields(canonical_source_info)
    record["status"] = "active"
    record["summary"] = ""
    explicit_topics = list(staged_candidate.get("topics", []) if staged_candidate else [])
    explicit_tags = list(staged_candidate.get("tags", []) if staged_candidate else [])
    if args.kind == "paper":
        explicit_topics.extend(
            str(item) for item in paper_metadata.get("topics", []) if str(item).strip()
        )
        explicit_tags.extend(
            str(item) for item in paper_metadata.get("tags", []) if str(item).strip()
        )
    record = apply_record_governance(
        root,
        record,
        explicit_topics=explicit_topics,
        explicit_tags=explicit_tags,
        explicit_pools=args.pool + (staged_candidate.get("pool_hints", []) if staged_candidate else []),
        infer_missing=True,
        source_label="source-intake",
    )
    if staged_candidate and staged_search:
        _attach_source_search_selection(
            record,
            stage=staged_search,
            candidate=staged_candidate,
            stage_id=args.stage_id,
            candidate_id=args.candidate_id,
            user_authorization=args.user_authorization,
            authorization_source=args.authorization_source,
        )

    if args.kind == "paper":
        canonical_arxiv_id = str(
            paper_metadata.get("arxiv_id") or parse_arxiv_id(source) or ""
        ).split("v", 1)[0]
        record["payload"]["basic_info"]["title"] = title
        record["payload"]["basic_info"]["authors"] = list(paper_metadata.get("authors", []))
        record["payload"]["basic_info"]["year"] = str(paper_metadata.get("year") or "")
        record["payload"]["basic_info"]["source_url"] = canonical_paper_source_url(
            source, paper_metadata
        )
        record["payload"]["basic_info"]["abstract"] = str(paper_metadata.get("abstract") or "")
        record["payload"]["basic_info"]["arxiv_id"] = canonical_arxiv_id
        record["payload"]["basic_info"]["doi"] = str(paper_metadata.get("doi") or "")
    elif args.kind == "repo":
        record["payload"]["basic_info"]["name"] = title
        record["payload"]["basic_info"]["url"] = source if source.startswith("http") else ""
        structure = record["payload"].setdefault("structure", {})
        if str(canonical_source_info.get("backup_kind") or "") == "directory":
            structure["scan_applicability"] = "applicable"
            structure["scan_reason"] = "local_source_tree"
        else:
            structure["scan_applicability"] = "unavailable"
            structure["scan_reason"] = "source_tree_not_archived"
    elif args.kind == "dataset":
        record["payload"]["basic_info"]["name"] = title
        record["payload"]["basic_info"]["url"] = source if source.startswith("http") else ""
        if "huggingface.co/datasets/" in source.lower():
            record["payload"]["basic_info"]["platform"] = "huggingface"
    else:
        record["payload"]["basic_info"]["title"] = title
        record["payload"]["basic_info"]["url"] = source if source.startswith("http") else ""
    return record, canonical_source_info, title


def _prepare_intake_snapshot(root: Path, args: argparse.Namespace) -> dict[str, object]:
    source, initial_title, paper_metadata, staged_candidate, staged_search = _resolve_intake_request(
        root, args
    )
    candidate_digest = _candidate_binding_digest(
        stage=staged_search,
        candidate=staged_candidate,
    )
    source_input_digest = _source_input_digest(root, source)
    token, prepared_root = _new_prepared_dir(root)
    try:
        preliminary_record = default_record(
            args.kind,
            title=initial_title,
            maturity=args.maturity,
            source={"original_uri": source},
        )
        stage_dir = prepared_root / "kb" / "intake-staging" / str(preliminary_record["id"])
        source_info = backup_source(
            prepared_root,
            args.kind,
            str(preliminary_record["id"]),
            source,
            unit_dir=stage_dir,
        )
        write_parse_cache(stage_dir, str(preliminary_record["id"]), source_info)
        readiness_error = source_backup_error(prepared_root, args.kind, source_info)
        if readiness_error:
            raise RuntimeError(readiness_error)
        if _source_input_digest(root, source) != source_input_digest:
            raise RuntimeError("The intake source changed while its snapshot was prepared.")
        if staged_candidate is not None and staged_search is not None:
            current_stage = load_search_stage(root, args.stage_id)
            current_candidate = resolve_search_candidate(root, args.stage_id, args.candidate_id)
            if _candidate_binding_digest(stage=current_stage, candidate=current_candidate) != candidate_digest:
                raise RuntimeError("The selected staged candidate changed while intake was prepared.")
        record, canonical_source_info, title = _finish_prepared_record(
            root,
            args,
            source=source,
            initial_title=initial_title,
            paper_metadata=paper_metadata,
            staged_candidate=staged_candidate,
            staged_search=staged_search,
            source_info=source_info,
            stage_dir=stage_dir,
            prepared_root=prepared_root,
        )
        _harden_prepared_tree(stage_dir)
        source_content_digest = _path_snapshot_digest(stage_dir)
        prepared_record_digest = _canonical_digest(record)
        context = intake_preference_context(
            args,
            source=source,
            title=title,
            canonical_pools=list(record.get("candidate_pools") or []),
            source_content_digest=source_content_digest,
            source_input_digest=source_input_digest,
            candidate_binding_digest=candidate_digest,
            prepared_record_digest=prepared_record_digest,
        )
        payload: dict[str, object] = {
            "schema": PREPARED_INTAKE_SCHEMA,
            "token": token,
            "created_at_epoch": int(time.time()),
            "workspace_digest": _canonical_digest(root.resolve(strict=False).as_posix()),
            "request_binding_digest": _request_binding_digest(
                args,
                source=source,
                initial_title=initial_title,
                source_input_digest=source_input_digest,
                candidate_binding_digest=candidate_digest,
            ),
            "stage_relative": stage_dir.relative_to(prepared_root).as_posix(),
            "source": source,
            "title": title,
            "source_input_digest": source_input_digest,
            "candidate_binding_digest": candidate_digest,
            "source_content_digest": source_content_digest,
            "prepared_record_digest": prepared_record_digest,
            "canonical_inputs": context,
            "record": record,
            "source_info": canonical_source_info,
        }
        payload["manifest_digest"] = _canonical_digest(payload)
        _write_prepared_manifest(prepared_root / "prepared.json", payload)
        return payload
    except BaseException:
        _safe_remove_prepared(root, token)
        raise


def _load_prepared_intake(
    root: Path,
    args: argparse.Namespace,
    token: str,
) -> tuple[dict[str, object], Path]:
    prepared_root = _prepared_dir(root, token)
    _assert_owned_private_directory(prepared_root)
    payload = _read_prepared_manifest(prepared_root / "prepared.json")
    required = {
        "schema",
        "token",
        "created_at_epoch",
        "workspace_digest",
        "request_binding_digest",
        "stage_relative",
        "source",
        "title",
        "source_input_digest",
        "candidate_binding_digest",
        "source_content_digest",
        "prepared_record_digest",
        "canonical_inputs",
        "record",
        "source_info",
        "manifest_digest",
    }
    if set(payload) != required:
        raise SystemExit("Prepared intake manifest has an invalid schema.")
    if payload.get("schema") != PREPARED_INTAKE_SCHEMA or payload.get("token") != token:
        raise SystemExit("Prepared intake manifest identity is invalid.")
    try:
        created_at_epoch = int(payload.get("created_at_epoch"))
    except (TypeError, ValueError) as exc:
        raise SystemExit("Prepared intake snapshot has an invalid creation time.") from exc
    age = int(time.time()) - created_at_epoch
    if age < -60 or age > PREPARED_INTAKE_TTL_SECONDS:
        raise SystemExit("Prepared intake snapshot has expired.")
    if payload.get("workspace_digest") != _canonical_digest(root.resolve(strict=False).as_posix()):
        raise SystemExit("Prepared intake snapshot belongs to another workspace.")
    manifest_digest = str(payload.pop("manifest_digest") or "")
    if manifest_digest != _canonical_digest(payload):
        raise SystemExit("Prepared intake manifest changed after preparation.")
    payload["manifest_digest"] = manifest_digest
    stage_relative = Path(str(payload.get("stage_relative") or ""))
    if stage_relative.is_absolute() or ".." in stage_relative.parts:
        raise SystemExit("Prepared intake stage escaped its controlled directory.")
    stage_dir = prepared_root / stage_relative

    source, initial_title, _metadata, candidate, stage = _resolve_intake_request(root, args)
    candidate_digest = _candidate_binding_digest(stage=stage, candidate=candidate)
    source_input_digest = _source_input_digest(root, source)
    if payload.get("request_binding_digest") != _request_binding_digest(
        args,
        source=source,
        initial_title=initial_title,
        source_input_digest=source_input_digest,
        candidate_binding_digest=candidate_digest,
    ):
        raise SystemExit("Prepared intake inputs changed after preparation.")
    if source != payload.get("source"):
        raise SystemExit("Prepared intake source changed after preparation.")
    if source_input_digest != payload.get("source_input_digest"):
        raise SystemExit("Prepared intake source bytes changed after preparation.")
    if candidate_digest != payload.get("candidate_binding_digest"):
        raise SystemExit("Prepared intake candidate changed after preparation.")
    if _path_snapshot_digest(stage_dir) != payload.get("source_content_digest"):
        raise SystemExit("Prepared intake archived bytes changed after preparation.")
    record = payload.get("record")
    source_info = payload.get("source_info")
    context = payload.get("canonical_inputs")
    if not isinstance(record, dict) or not isinstance(source_info, dict) or not isinstance(context, dict):
        raise SystemExit("Prepared intake manifest content is invalid.")
    if _canonical_digest(record) != payload.get("prepared_record_digest"):
        raise SystemExit("Prepared intake record changed after preparation.")
    recomputed_context = intake_preference_context(
        args,
        source=source,
        title=str(payload.get("title") or ""),
        canonical_pools=list(record.get("candidate_pools") or []),
        source_content_digest=str(payload.get("source_content_digest") or ""),
        source_input_digest=source_input_digest,
        candidate_binding_digest=candidate_digest,
        prepared_record_digest=str(payload.get("prepared_record_digest") or ""),
    )
    if recomputed_context != context:
        raise SystemExit("Prepared intake task context changed after preparation.")
    return payload, stage_dir


def _workspace_seed_paths(root: Path) -> list[Path]:
    return [
        kb_root(root) / ".gitignore",
        kb_root(root) / "config" / "research-settings.md",
        kb_root(root) / "config" / "runtime-preferences.yaml",
        kb_root(root) / "user" / "navigation.md",
        kb_root(root) / "user" / "current-state.md",
        topic_taxonomy_path(root),
        candidate_pools_path(root),
    ]


def _index_target_paths(root: Path) -> list[Path]:
    return [
        topic_taxonomy_path(root),
        candidate_pools_path(root),
        kb_root(root) / "index.yaml",
        kb_root(root) / "index.md",
    ]


def _materialize_staged_source(
    root: Path,
    *,
    kind: str,
    source: str,
    title: str,
    record: dict,
    source_info: dict,
    stage_dir: Path,
) -> tuple[Path | None, dict | None, dict]:
    """Atomically move staged evidence into a canonical unit and write its record."""
    canonical_dir = unit_root(root, kind, str(record["id"]))
    canonical_source_info = dict(source_info)
    record["source"] = source_record_fields(canonical_source_info)
    quarantine_root = (
        kb_root(root)
        / ".runtime"
        / "intake-staging"
        / "legacy-failed-units"
        / str(record["id"])
    )
    rollback_targets = [canonical_dir, quarantine_root]
    with mutation_transaction(root, "source-intake-materialize", rollback_targets):
        duplicate = detect_duplicate(
            root,
            kind,
            source,
            title=title,
            candidate_file_hash=str(canonical_source_info.get("file_hash") or ""),
        )
        if duplicate:
            shutil.rmtree(stage_dir)
            return None, duplicate, canonical_source_info

        quarantine_dir: Path | None = None
        if canonical_dir.exists():
            quarantine_dir = quarantine_root / uuid.uuid4().hex
        if quarantine_dir is not None:
            quarantine_dir.parent.mkdir(parents=True, exist_ok=True)
            os.replace(canonical_dir, quarantine_dir)
        canonical_dir.parent.mkdir(parents=True, exist_ok=True)
        os.replace(stage_dir, canonical_dir)
        path = write_record(root, record)
    return path, None, canonical_source_info


def _build_index_transaction(root: Path) -> tuple[Path, Path]:
    targets = _index_target_paths(root)
    with mutation_transaction(root, "source-intake-build-index", targets):
        return build_index(root)


def _intake_transaction_targets(
    root: Path,
    *,
    unit_dir: Path,
    unit_id: str,
    stage_id: str = "",
) -> list[Path]:
    targets = [
        unit_dir,
        *_index_target_paths(root),
        # A rejected legacy unit may be quarantined during materialization.  The
        # command-level snapshot must remove/restore that KB-local move as one op.
        kb_root(root) / ".runtime" / "intake-staging" / "legacy-failed-units" / unit_id,
    ]
    if stage_id:
        targets.append(search_stage_path(root, stage_id))
    return list(dict.fromkeys(targets))


def _attach_source_search_selection(
    record: dict,
    *,
    stage: dict,
    candidate: dict,
    stage_id: str,
    candidate_id: str,
    user_authorization: str,
    authorization_source: str,
) -> bool:
    """Attach exact intake provenance without changing analysis or confirmation substance."""
    source_search = record.setdefault("payload", {}).setdefault("source_search", {})
    before = repr(source_search)
    source_search["stage_ids"] = sorted(set(source_search.get("stage_ids", [])) | {stage_id})
    source_search["candidate_ids"] = sorted(
        set(source_search.get("candidate_ids", [])) | {candidate_id}
    )
    source_search["queries"] = sorted(
        set(source_search.get("queries", [])) | {str(stage.get("query") or "")}
    )
    if stage.get("entry_skill") == "literature-search":
        require_user_authorization(
            user_authorization=user_authorization,
            authorization_source=authorization_source,
        )
        receipt = {
            "stage_id": stage_id,
            "candidate_id": candidate_id,
            "candidate_identity_digest": literature_candidate_identity_digest(candidate),
            "user_authorization": user_authorization.strip(),
            "authorization_source": "user_message",
        }
        selections = [
            item for item in source_search.get("selections", []) if isinstance(item, dict)
        ]
        prior = [
            item
            for item in selections
            if item.get("stage_id") == stage_id and item.get("candidate_id") == candidate_id
        ]
        if prior and (len(prior) != 1 or prior[0] != receipt):
            raise SystemExit("A staged candidate selection cannot be rebound after intake.")
        if not prior:
            selections.append(receipt)
        source_search["selections"] = sorted(
            selections,
            key=lambda item: (str(item.get("stage_id") or ""), str(item.get("candidate_id") or "")),
        )
        source_search["user_selection"] = {
            "user_authorization": receipt["user_authorization"],
            "authorization_source": receipt["authorization_source"],
        }
    return repr(source_search) != before


def _attach_duplicate_selection_and_mark(
    root: Path,
    *,
    args: argparse.Namespace,
    duplicate: dict,
) -> Path | None:
    if not args.stage_id or not args.candidate_id:
        return None
    stage_path = search_stage_path(root, args.stage_id)
    current, record_path = locate_record(
        root,
        str(duplicate.get("id") or ""),
        kind=str(duplicate.get("kind") or args.kind),
        fuzzy=False,
    )
    with mutation_transaction(
        root,
        "source-intake-attach-duplicate-selection",
        [record_path, stage_path],
    ):
        current, _ = locate_record(
            root,
            str(duplicate.get("id") or ""),
            kind=str(duplicate.get("kind") or args.kind),
            fuzzy=False,
        )
        stage = load_search_stage(root, args.stage_id)
        candidate = resolve_search_candidate(root, args.stage_id, args.candidate_id)
        changed = _attach_source_search_selection(
            current,
            stage=stage,
            candidate=candidate,
            stage_id=args.stage_id,
            candidate_id=args.candidate_id,
            user_authorization=args.user_authorization,
            authorization_source=args.authorization_source,
        )
        if changed:
            append_history(
                current,
                action="source-search-duplicate-attached",
                summary="Attached a selected staged source to this existing canonical unit.",
                information_types=["fact"],
            )
            write_record(root, current)
        return mark_search_candidate(
            root,
            args.stage_id,
            args.candidate_id,
            status="duplicate",
            record_id=str(current.get("id") or ""),
        )


def _execute_intake_transaction(
    root: Path,
    *,
    args: argparse.Namespace,
    source: str,
    title: str,
    record: dict,
    source_info: dict,
    stage_dir: Path,
    unit_dir: Path,
    paper_preferences: dict,
) -> tuple[Path | None, dict | None, dict, list[str], bool, Path | None]:
    """Materialize and derive one intake as one undoable command transaction."""
    targets = _intake_transaction_targets(
        root,
        unit_dir=unit_dir,
        unit_id=str(record["id"]),
        stage_id=str(args.stage_id or ""),
    )
    auto_outputs: list[str] = []
    note_created = False
    updated_stage_path: Path | None = None
    with mutation_transaction(root, "source-intake-add", targets):
        path, concurrent_duplicate, canonical_source_info = _materialize_staged_source(
            root,
            kind=args.kind,
            source=source,
            title=title,
            record=record,
            source_info=source_info,
            stage_dir=stage_dir,
        )
        if concurrent_duplicate:
            updated_stage_path = _attach_duplicate_selection_and_mark(
                root,
                args=args,
                duplicate=concurrent_duplicate,
            )
            return (
                None,
                concurrent_duplicate,
                canonical_source_info,
                auto_outputs,
                note_created,
                updated_stage_path,
            )
        if path is None:
            raise RuntimeError("Source materialization completed without a canonical record path.")

        # Standalone add keeps its preference-driven preparation.  kb ingest owns
        # the stricter paper order (screen verify before type-specific note prepare),
        # so intake must not create competing analyzer scaffolds inside that chain.
        if args.kind == "paper" and not ingest_chain_active():
            if bool(paper_preferences.get("parse_cache_prewarm_on_intake", True)) and not bool(
                paper_preferences.get("auto_screen_on_intake", True)
            ):
                auto_outputs.extend(
                    run_paper_command(root, "prewarm-cache", "--paper-id", record["id"], "--defer-post-actions")
                )
            should_screen = bool(paper_preferences.get("auto_screen_on_intake", True)) or args.maturity == "complete"
            if should_screen:
                auto_outputs.extend(
                    run_paper_command(root, "screen", "--paper-id", record["id"], "--mode", "auto", "--defer-post-actions")
                )
            # Complete-note preparation is deliberately deferred until the runtime
            # agent fills and verifies screening.paper_type.  No preference or
            # maturity shortcut may create a method-shaped scaffold before that.

        _build_index_transaction(root)
        if args.stage_id and args.candidate_id:
            updated_stage_path = mark_search_candidate(
                root,
                args.stage_id,
                args.candidate_id,
                status="materialized",
                record_id=str(record["id"]),
            )
    return path, None, canonical_source_info, auto_outputs, note_created, updated_stage_path


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)

    if args.command in {"search", "stage-search"}:
        ensure_workspace(root)
        candidates = stage_candidates(args)
        path = stage_search_results(
            root,
            kind=args.kind,
            query=args.query,
            candidates=candidates,
            stage_id=args.stage_id,
            note=args.note,
        )
        print(f"[ok] wrote {path.relative_to(root)}")
        return 0

    if args.command == "show-stage":
        payload = load_search_stage(root, args.stage_id)
        print(f"id: {payload['id']}")
        print(f"source_kind: {payload.get('source_kind')}")
        print(f"query: {payload.get('query')}")
        for candidate in payload.get("candidates", []):
            print(
                f"- {candidate.get('candidate_id')} | {candidate.get('status')} | "
                f"{candidate.get('title') or '-'} | {candidate.get('url')}"
            )
        return 0

    if args.command == "prepare-add":
        try:
            prepared = _prepare_intake_snapshot(root, args)
        except (Exception, SystemExit) as exc:
            error = str(exc).strip() or exc.__class__.__name__
            raise SystemExit(f"Source intake failed; retry is safe: {error}") from exc
        print(
            json.dumps(
                {
                    "prepared_intake_token": prepared["token"],
                    "skill": "source-intake",
                    "operation": "add",
                    "canonical_inputs": prepared["canonical_inputs"],
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 0

    missing_seed_paths = [path for path in _workspace_seed_paths(root) if not path.exists()]
    token = str(getattr(args, "prepared_intake_token", "") or "")
    created_here = not bool(token)
    if not token:
        try:
            token = str(_prepare_intake_snapshot(root, args)["token"])
        except (Exception, SystemExit) as exc:
            error = str(exc).strip() or exc.__class__.__name__
            raise SystemExit(f"Source intake failed; retry is safe: {error}") from exc
    claimed = False
    try:
        _claim_prepared_intake(root, token)
        claimed = True
        prepared, stage_dir = _load_prepared_intake(root, args, token)
        record = prepared["record"]
        source_info = prepared["source_info"]
        canonical_inputs = prepared["canonical_inputs"]
        if not isinstance(record, dict) or not isinstance(source_info, dict) or not isinstance(
            canonical_inputs, dict
        ):
            raise SystemExit("Prepared intake snapshot is incomplete.")
        source = str(prepared.get("source") or "")
        title = str(prepared.get("title") or "")
        unit_dir = unit_root(root, args.kind, str(record["id"]))
        paper_preferences, preference_state = resolve_intake_preferences(
            root,
            args,
            source=source,
            title=title,
            canonical_pools=list(record.get("candidate_pools") or []),
            canonical_inputs=canonical_inputs,
        )
        # Re-open every external and canonical input after receipt validation so
        # a same-path mutation cannot be promoted with the old receipt.
        _load_prepared_intake(root, args, token)

        record["payload"]["preference_contract"] = operation_contract(
            skill="source-intake", operation="add"
        )
        record["payload"]["preference_context"] = preference_state
        selection = dict(preference_state.get("selection_binding") or {})
        if selection:
            record["payload"]["preference_binding"] = selection
        else:
            record["payload"].pop("preference_binding", None)

        duplicate = detect_duplicate(
            root,
            args.kind,
            source,
            title=title,
            candidate_file_hash=str(source_info.get("file_hash") or ""),
        )
        if duplicate:
            _attach_duplicate_selection_and_mark(root, args=args, duplicate=duplicate)
            print(f"[ok] duplicate detected: {duplicate['id']}")
            return 0

        ensure_workspace(root)
        created_seed_paths = [path for path in missing_seed_paths if path.exists()]
        backup_warning = str(source_info.get("backup_warning") or "").strip()
        parse_cache_path = (
            unit_dir / "parse-cache.yaml" if source_info.get("parse_chunks") else None
        )
        path, concurrent_duplicate, source_info, auto_outputs, note_created, updated_stage_path = (
            _execute_intake_transaction(
                root,
                args=args,
                source=source,
                title=title,
                record=record,
                source_info=source_info,
                stage_dir=stage_dir,
                unit_dir=unit_dir,
                paper_preferences=paper_preferences,
            )
        )
        if concurrent_duplicate:
            print(f"[ok] duplicate detected: {concurrent_duplicate['id']}")
            return 0
        if path is None:
            raise RuntimeError("Source materialization completed without a canonical record path.")
        has_pdf = str(source_info.get("source_type") or "") == "pdf" or source.lower().endswith(
            ".pdf"
        )
        print(f"[ok] created {path.relative_to(root)}")
        backup_status = str(source_info.get("backup_status") or "").strip()
        if backup_status:
            print(
                f"[source] backup_status={backup_status} "
                f"source_type={source_info.get('source_type') or '-'} "
                f"locator_kind={source_info.get('locator_kind') or '-'}"
            )
        if parse_cache_path is not None:
            print(
                f"[source] parse-cache: {parse_cache_path.relative_to(root)} "
                f"({len(source_info.get('parse_chunks') or [])} chunks)"
            )
        if backup_warning:
            print(f"[warn] source archive: {backup_warning}")
        print(f"待内容补全并校验后，再请你确认条目 {record['id']}。")
        for line in auto_outputs:
            print(f"[auto] {line}")
        checkpoint_targets = [unit_dir, *_index_target_paths(root), *created_seed_paths]
        if updated_stage_path is not None:
            checkpoint_targets.append(updated_stage_path)
        checkpoint_and_report(
            root,
            trigger="milestone",
            message=f"milestone: intake {args.kind} {record['id']}",
            target_paths=list(dict.fromkeys(checkpoint_targets)),
        )
        for hint in guidance_hints(
            args.kind,
            paper_preferences,
            has_pdf=has_pdf,
            note_created=note_created,
        ):
            print(f"[hint] {hint}")
        print(next_for_agent_intake(root, args.kind, record["id"]))
        return 0
    finally:
        if claimed or created_here:
            _safe_remove_prepared(root, token)


if __name__ == "__main__":
    raise SystemExit(main())
