#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import time
import uuid
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
skills_dir = SCRIPT_PATH.parents[2]
if skills_dir.name != "skills":
    raise SystemExit("Could not locate the managed research runtime.")
if skills_dir.parent.name == ".agents":
    PROJECT_ROOT = skills_dir.parent.parent
    lib = PROJECT_ROOT / ".agents" / "lib"
else:
    PROJECT_ROOT = skills_dir.parent
    lib = PROJECT_ROOT / "runtime" / "lib"
if not (skills_dir / "metadata.yaml").is_file() or not (lib / "research" / "__init__.py").is_file() or not (lib / "research" / "bootstrap.py").is_file():
    raise SystemExit("Could not locate the managed research runtime.")
sys.path.insert(0, str(lib))

from research.bootstrap import ensure_managed_runtime

if __name__ == "__main__":
    ensure_managed_runtime(PROJECT_ROOT)

from research.bibliography import citation_key_for_unit_id, normalize_arxiv_id, normalize_doi
from research.analyzer_registry import UNIT_ANALYZER_PREPARE_BY_KIND
from research.common import add_project_root_argument, confirm_command as shared_confirm_command, extract_pdf_record, load_yaml, parse_arxiv_id, print_resolved_project_roots, skill_script_for_command
from research.confirm import require_user_authorization
from research.diagnostics import publish_runtime_failure_stage
from research.journal import mutation_transaction
from research.intake_cli import add_intake_add_arguments
from research.ids import canonical_unit_id_with_hash
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
from research.paths import passage_search_cache_path
from research.records import snapshot_project_file
from research.sources import literature_stage_snapshot
from research.slugs import normalize_title


HUMAN_NOTE_AREAS = frozenset({"inbox", "annotations"})
HUMAN_NOTE_MAX_BYTES = 1024 * 1024
HUMAN_NOTE_ORIGIN = "human-note"
HUMAN_NOTE_REVIEW_SCHEMA = "kb-obsidian-review-sheet/v1"
HUMAN_NOTE_REVIEW_MARKER = re.compile(r"<!--\s*kb-review-batch:[0-9a-f]{64}\s*-->", re.IGNORECASE)
_INTAKE_FAILURE_STAGE_ATTRIBUTE = "_research_intake_failure_stage"


def _tag_intake_failure(exc: BaseException, stage: str) -> None:
    """Attach only a stable internal stage token; never attach exception text."""

    if not getattr(exc, _INTAKE_FAILURE_STAGE_ATTRIBUTE, ""):
        setattr(exc, _INTAKE_FAILURE_STAGE_ATTRIBUTE, stage)


def _intake_failure_stage(exc: BaseException, *, default: str) -> str:
    return str(getattr(exc, _INTAKE_FAILURE_STAGE_ATTRIBUTE, "") or default)


def _call_at_intake_stage(stage: str, callback, *args, **kwargs):
    try:
        return callback(*args, **kwargs)
    except (Exception, SystemExit) as exc:
        _tag_intake_failure(exc, stage)
        raise


def _publish_intake_failure_stage(root: Path, operation: str, exc: BaseException) -> None:
    publish_runtime_failure_stage(
        root,
        skill="source-intake",
        operation=operation,
        failure_stage=_intake_failure_stage(exc, default="unknown"),
    )


def infer_title(source: str) -> str:
    if source.startswith("http"):
        return source.rstrip("/").split("/")[-1] or source
    return Path(source).stem.replace("_", " ")


def _source_material_is_degraded(record: dict) -> bool:
    if str(record.get("status") or "").strip().lower() in {"archived", "rejected", "failed"}:
        return False
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    materialization = source.get("materialization") if isinstance(source.get("materialization"), dict) else {}
    return (
        str(source.get("backup_status") or "").strip().lower() == "degraded"
        or str(materialization.get("status") or "").strip().lower() == "degraded"
    )


def _degraded_unconfirmed_source(record: dict) -> bool:
    if str(record.get("kind") or "") != "paper" or not _source_material_is_degraded(record):
        return False
    if str(record.get("confirmation_status") or "").strip().lower() in {"confirmed", "rejected"}:
        return False
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    return not payload.get("claims") and not payload.get("verification")


def _source_upgrade_candidate_identity_matches(record: dict, source: str, title: str) -> bool:
    if str(record.get("kind") or "") != "paper" or source.startswith(("http://", "https://")):
        return False
    source_path = Path(source)
    if source_path.suffix.lower() not in {".pdf", ".html", ".htm"}:
        return False
    record_source = record.get("source") if isinstance(record.get("source"), dict) else {}
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    basic = payload.get("basic_info") if isinstance(payload.get("basic_info"), dict) else {}
    old_arxiv = parse_arxiv_id(
        "\n".join(
            (
                str(record_source.get("original_uri") or ""),
                str(basic.get("source_url") or ""),
                str(basic.get("arxiv_id") or ""),
                str(record.get("title") or ""),
            )
        )
    )
    new_arxiv = parse_arxiv_id("\n".join((source_path.name, title)))
    if old_arxiv and new_arxiv:
        return old_arxiv.split("v", 1)[0] == new_arxiv.split("v", 1)[0]
    return bool(title and normalize_title(title) == normalize_title(str(record.get("title") or "")))


def _source_upgrade_identity_matches(record: dict, source: str, title: str) -> bool:
    return _degraded_unconfirmed_source(record) and _source_upgrade_candidate_identity_matches(
        record, source, title
    )


def _source_upgrade_is_complete(source_info: dict) -> bool:
    materialization = source_info.get("materialization")
    if not isinstance(materialization, dict):
        return False
    backup_status = str(source_info.get("backup_status") or "").strip().lower()
    materialization_status = str(materialization.get("status") or "").strip().lower()
    source_type = str(source_info.get("source_type") or "").strip().lower()
    if (
        backup_status == "ok"
        and materialization_status == "complete"
        and source_type in {"pdf", "html"}
    ):
        return True
    # Converter warnings are not proof that the raw PDF is an abstract shell.
    # Preserve the degraded label and warnings, but accept a byte-bound,
    # page-located, substantive multi-page parse as a complete replacement
    # source.  This does not relax ordinary backup quality reporting.
    if backup_status != "degraded" or materialization_status != "degraded" or source_type != "pdf":
        return False
    if (
        str(source_info.get("locator_kind") or "") != "page"
        or not str(source_info.get("file_hash") or "")
        or not str(source_info.get("markdown_hash") or "")
        or not str(materialization.get("source_map_path") or "")
        or not str(materialization.get("conversion_path") or "")
    ):
        return False
    pages: set[int] = set()
    parsed_characters = 0
    for chunk in source_info.get("parse_chunks") or []:
        if not isinstance(chunk, dict):
            continue
        try:
            page = int(chunk.get("page"))
        except (TypeError, ValueError):
            continue
        text = str(chunk.get("text") or "").strip()
        if page < 1 or not text:
            continue
        pages.add(page)
        parsed_characters += len(text)
    return bool(
        len(pages) >= 2
        and pages == set(range(1, max(pages) + 1))
        and parsed_characters >= 4_000
    )


def _ensure_source_revision_link(record: dict, target_id: str, relation: str) -> None:
    links = record.setdefault("links", [])
    if any(
        isinstance(item, dict)
        and str(item.get("target_id") or "") == target_id
        and str(item.get("relation") or "") == relation
        for item in links
    ):
        return
    links.append(
        {
            "target_id": target_id,
            "relation": relation,
            "note": "Source revision lineage; canonical evidence bytes remain immutable.",
        }
    )


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


def guidance_hints(kind: str, preferences: dict, *, has_pdf: bool, note_created: bool) -> list[str]:
    if kind == "paper":
        next_step = "已轻量入库；可运行 kb ingest 继续深读，或运行 kb next 查看主线建议。"
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


# kind -> (unit-analyst script, prepare verb, id flag). Used only to build the
# private NEXT FOR AGENT navigation line (`docs/DESIGN.md`, "对话层与 Agent 协议"); no judgement here.
ANALYZER_PREPARE: dict[str, tuple[str, str, str]] = dict(UNIT_ANALYZER_PREPARE_BY_KIND)


def ingest_chain_active() -> bool:
    """Whether kb ingest owns the analyzer ordering for this intake."""
    return bool(str(os.environ.get("RESEARCH_INGEST_CHAIN") or "").strip())


def next_for_agent_intake(root: Path, kind: str, record_id: str) -> str:
    """One private navigation line after intake add, per the Agent protocol in `docs/DESIGN.md`.

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
    add.add_argument("--expected-literature-stage-digest", default="", help=argparse.SUPPRESS)

    batch_add = subparsers.add_parser(
        "batch-add",
        help="Privately preflight and atomically materialize one intake batch",
    )
    batch_add.add_argument("--item", action="append", required=True)

    subparsers.add_parser(
        "garden-prepared",
        help="Privately remove only provably safe expired intake snapshots",
    )

    prepare = subparsers.add_parser(
        "prepare-add",
        help="Privately freeze one intake snapshot before Agent preference selection",
    )
    add_intake_add_arguments(prepare, include_stage_options=True)
    prepare.add_argument("--user-authorization", default="")
    prepare.add_argument("--authorization-source", default="")
    prepare.add_argument("--expected-literature-stage-digest", default="", help=argparse.SUPPRESS)

    human_note = subparsers.add_parser(
        "human-note",
        help="Privately freeze one selected human-authored Obsidian note",
    )
    human_note.add_argument("--area", required=True, choices=sorted(HUMAN_NOTE_AREAS))
    human_note.add_argument("--filename", required=True)

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


def _human_note_relative_path(area: str, filename: str) -> str:
    """Return the only accepted human-note source shape: one named Markdown leaf."""
    if area not in HUMAN_NOTE_AREAS:
        raise SystemExit("Human-note intake accepts only inbox or annotations.")
    if (
        not filename
        or filename in {".", ".."}
        or Path(filename).name != filename
        or "/" in filename
        or "\\" in filename
        or Path(filename).suffix.lower() != ".md"
    ):
        raise SystemExit("Human-note intake requires one Markdown filename without directories.")
    if filename.casefold().startswith("pending review "):
        raise SystemExit("Obsidian review sheets cannot be ingested as human notes.")
    return f"kb/obsidian/{area}/{filename}"


def _snapshot_human_note(root: Path, area: str, filename: str):
    relative = _human_note_relative_path(area, filename)
    snapshot = snapshot_project_file(root, relative, max_bytes=HUMAN_NOTE_MAX_BYTES)
    if snapshot is None:
        raise SystemExit("The selected human note is unavailable or unsafe.")
    try:
        text = snapshot.raw_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SystemExit("Human-note intake accepts only strict UTF-8 Markdown.") from exc
    frontmatter = ""
    if text.startswith("---\n") or text.startswith("---\r\n"):
        match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, flags=re.DOTALL)
        if match:
            frontmatter = match.group(1)
    if re.search(
        rf"(?mi)^\s*schema\s*:\s*['\"]?{re.escape(HUMAN_NOTE_REVIEW_SCHEMA)}['\"]?\s*$",
        frontmatter,
    ) or HUMAN_NOTE_REVIEW_MARKER.search(text):
        raise SystemExit("Obsidian review sheets cannot be ingested as human notes.")
    return snapshot


def _normalize_human_note_args(root: Path, args: argparse.Namespace) -> argparse.Namespace:
    snapshot = _snapshot_human_note(root, str(args.area), str(args.filename))
    return argparse.Namespace(
        command="add",
        kind="blog",
        source=snapshot.relative_path,
        maturity="lightweight",
        title="",
        stage_id="",
        candidate_id="",
        pool=[],
        user_authorization="",
        authorization_source="",
        preference_selection_id="",
        prepared_intake_token="",
        expected_literature_stage_digest="",
        human_note_area=str(args.area),
        human_note_filename=str(args.filename),
        source_origin=HUMAN_NOTE_ORIGIN,
    )


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
BATCH_INTAKE_MAX_ITEMS = 20
PREPARED_MAX_FILE_BYTES = 64 * 1024 * 1024
PREPARED_MAX_ENTRIES = 20_000
PREPARED_MAX_TOTAL_BYTES = 512 * 1024 * 1024
PREPARED_MAX_DEPTH = 64


def _stream_regular_file(
    descriptor: int,
    *,
    max_bytes: int = PREPARED_MAX_FILE_BYTES,
) -> tuple[dict[str, object], str]:
    before = os.fstat(descriptor)
    if not stat.S_ISREG(before.st_mode):
        raise ValueError("prepared intake contains a non-regular file")
    if before.st_size > max_bytes:
        raise ValueError("prepared intake source exceeds the byte budget")
    digest = hashlib.sha256()
    byte_count = 0
    with os.fdopen(os.dup(descriptor), "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            byte_count += len(chunk)
            if byte_count > max_bytes:
                raise ValueError("prepared intake source exceeds the byte budget")
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
    if byte_count != after.st_size:
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
    directory_before = os.fstat(descriptor)
    remaining_entries = PREPARED_MAX_ENTRIES - budget["entries"]
    entries: list[os.DirEntry[str]] = []
    try:
        with os.scandir(descriptor) as iterator:
            for entry in iterator:
                entries.append(entry)
                if len(entries) > remaining_entries:
                    raise ValueError("prepared intake source tree exceeds the entry budget")
        entries.sort(key=lambda item: item.name)
    except ValueError:
        raise
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
            remaining_bytes = PREPARED_MAX_TOTAL_BYTES - budget["bytes"]
            metadata, byte_digest = _stream_regular_file(
                child_descriptor,
                max_bytes=min(PREPARED_MAX_FILE_BYTES, max(remaining_bytes, 0)),
            )
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
    directory_after = os.fstat(descriptor)
    stable_directory_fields = (
        "st_dev",
        "st_ino",
        "st_mode",
        "st_uid",
        "st_gid",
        "st_size",
        "st_mtime_ns",
        "st_ctime_ns",
    )
    if any(
        getattr(directory_before, name) != getattr(directory_after, name)
        for name in stable_directory_fields
    ):
        raise ValueError("prepared intake source tree changed while it was read")


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
            metadata, byte_digest = _stream_regular_file(
                descriptor,
                max_bytes=PREPARED_MAX_FILE_BYTES,
            )
        finally:
            os.close(descriptor)
        if (int(metadata["device"]), int(metadata["inode"])) != (
            root_stat.st_dev,
            root_stat.st_ino,
        ):
            raise ValueError("prepared intake source changed before it was read")
        try:
            visible_after = path.lstat()
        except OSError as exc:
            raise ValueError("prepared intake source changed while it was read") from exc
        if (
            visible_after.st_dev,
            visible_after.st_ino,
            visible_after.st_mode,
            visible_after.st_size,
            visible_after.st_mtime_ns,
        ) != (
            int(metadata["device"]),
            int(metadata["inode"]),
            root_stat.st_mode,
            int(metadata["size"]),
            int(metadata["mtime_ns"]),
        ):
            raise ValueError("prepared intake source changed while it was read")
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
        if (opened.st_dev, opened.st_ino) != (root_stat.st_dev, root_stat.st_ino):
            raise ValueError("prepared intake source tree changed before it was read")
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
    try:
        visible_after = path.lstat()
    except OSError as exc:
        raise ValueError("prepared intake source tree changed while it was read") from exc
    if (visible_after.st_dev, visible_after.st_ino) != (opened.st_dev, opened.st_ino):
        raise ValueError("prepared intake source tree changed while it was read")
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


def _strict_literature_stage_candidate(
    root: Path,
    args: argparse.Namespace,
) -> tuple[dict, dict, str]:
    expected = str(getattr(args, "expected_literature_stage_digest", "") or "")
    if re.fullmatch(r"[0-9a-f]{64}", expected) is None:
        raise SystemExit("Expected literature stage digest is invalid.")
    stage_id = str(getattr(args, "stage_id", "") or "")
    candidate_id = str(getattr(args, "candidate_id", "") or "")
    if not stage_id or not candidate_id:
        raise SystemExit("Expected literature stage digest requires an exact staged candidate.")
    snapshot = literature_stage_snapshot(root, stage_id)
    stage = dict(snapshot["payload"])
    if stage.get("entry_skill") != "literature-search" or stage.get("source_kind") != "paper":
        raise SystemExit("Expected literature stage digest requires a literature-search paper stage.")
    if str(snapshot["byte_sha256"]) != expected:
        raise SystemExit("Selected literature stage changed before canonical intake.")
    matches = [
        dict(item)
        for item in stage.get("candidates", [])
        if isinstance(item, dict) and item.get("candidate_id") == candidate_id
    ]
    if len(matches) != 1:
        raise SystemExit("Selected literature candidate is missing or ambiguous.")
    return stage, matches[0], str(snapshot["byte_sha256"])


def _assert_expected_literature_stage_digest(root: Path, args: argparse.Namespace) -> None:
    expected = str(getattr(args, "expected_literature_stage_digest", "") or "")
    if expected:
        _strict_literature_stage_candidate(root, args)


def _prepared_record_binding_digest(
    record: dict,
    *,
    duplicate_record_binding_digest: str = "",
    superseded_record_binding_digest: str = "",
) -> str:
    return _canonical_digest(
        {
            "record": record,
            "duplicate_record_binding_digest": str(duplicate_record_binding_digest or ""),
            "superseded_record_binding_digest": str(superseded_record_binding_digest or ""),
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


def _prepared_gc_candidate(
    root: Path,
    path: Path,
    token: str,
    *,
    now_epoch: int,
) -> tuple[str, str]:
    """Classify one prepared tree without following links or guessing intent."""
    try:
        _assert_owned_private_directory(path)
    except SystemExit:
        return "retained", "unsafe-root"

    entry_count = 0
    try:
        for current, directories, files in os.walk(path, topdown=True, followlinks=False):
            current_path = Path(current)
            current_stat = current_path.lstat()
            if (
                current_stat.st_uid != os.getuid()
                or stat.S_ISLNK(current_stat.st_mode)
                or not stat.S_ISDIR(current_stat.st_mode)
            ):
                return "retained", "unsafe-tree"
            for name in [*directories, *files]:
                entry_count += 1
                if entry_count > PREPARED_MAX_ENTRIES * 2 + 32:
                    return "retained", "unbounded-tree"
                child = current_path / name
                metadata = child.lstat()
                if metadata.st_uid != os.getuid() or stat.S_ISLNK(metadata.st_mode):
                    return "retained", "unsafe-tree"
                if name in directories:
                    if not stat.S_ISDIR(metadata.st_mode):
                        return "retained", "unsafe-tree"
                elif not stat.S_ISREG(metadata.st_mode):
                    return "retained", "unsafe-tree"
    except OSError:
        return "retained", "unreadable-tree"

    claimed = path / "claimed"
    try:
        claimed_stat = claimed.lstat()
    except FileNotFoundError:
        claimed_stat = None
    except OSError:
        return "retained", "unknown-claim-state"
    if claimed_stat is not None:
        if (
            claimed_stat.st_uid == os.getuid()
            and stat.S_ISREG(claimed_stat.st_mode)
            and stat.S_IMODE(claimed_stat.st_mode) == 0o600
        ):
            return "active", "claimed"
        return "retained", "unsafe-claim-state"

    try:
        payload = _read_prepared_manifest(path / "prepared.json")
    except SystemExit:
        return "retained", "invalid-manifest"
    required = {
        "schema",
        "token",
        "created_at_epoch",
        "workspace_digest",
        "manifest_digest",
    }
    if not required <= set(payload):
        return "retained", "invalid-manifest"
    manifest_digest = str(payload.get("manifest_digest") or "")
    digest_payload = dict(payload)
    digest_payload.pop("manifest_digest", None)
    if manifest_digest != _canonical_digest(digest_payload):
        return "retained", "invalid-manifest"
    if (
        payload.get("schema") != PREPARED_INTAKE_SCHEMA
        or payload.get("token") != token
        or payload.get("workspace_digest")
        != _canonical_digest(root.resolve(strict=False).as_posix())
    ):
        return "retained", "foreign-or-invalid-manifest"
    try:
        created_at_epoch = int(payload.get("created_at_epoch"))
    except (TypeError, ValueError):
        return "retained", "invalid-manifest"
    age = now_epoch - created_at_epoch
    if age < -60:
        return "retained", "future-timestamp"
    if age <= PREPARED_INTAKE_TTL_SECONDS:
        return "active", "within-ttl"
    return "expired", "ttl-elapsed"


def _garden_prepared_intakes(
    root: Path,
    *,
    now_epoch: int | None = None,
) -> dict[str, object]:
    """Remove only expired private trees whose complete safety proof succeeds."""
    root = root.resolve(strict=False)
    parent = root.parent
    prefix = f".research-intake-{_prepared_scope(root)}-"
    pattern = re.compile(rf"{re.escape(prefix)}(?P<token>[0-9a-f]{{32}})\Z")
    removed: list[str] = []
    active: list[str] = []
    retained: list[dict[str, str]] = []
    now = int(time.time()) if now_epoch is None else int(now_epoch)
    try:
        with os.scandir(parent) as iterator:
            entry_names = sorted(entry.name for entry in iterator)
    except OSError:
        return {
            "removed_count": 0,
            "active_count": 0,
            "retained_count": 1,
            "removed_tokens": [],
            "active_tokens": [],
            "retained": [{"name": prefix + "*", "reason": "unreadable-parent"}],
        }
    for entry_name in entry_names:
        if not entry_name.startswith(prefix):
            continue
        match = pattern.fullmatch(entry_name)
        if match is None:
            retained.append({"name": entry_name, "reason": "unknown-name"})
            continue
        token = str(match.group("token") or "")
        path = parent / entry_name
        state, reason = _prepared_gc_candidate(root, path, token, now_epoch=now)
        if state == "active":
            active.append(token)
            continue
        if state != "expired":
            retained.append({"name": entry_name, "reason": reason})
            continue
        if not bool(getattr(shutil.rmtree, "avoids_symlink_attacks", False)):
            retained.append({"name": entry_name, "reason": "unsafe-platform-delete"})
            continue
        try:
            before = path.lstat()
            _assert_owned_private_directory(path)
            current = path.lstat()
            if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
                retained.append({"name": entry_name, "reason": "root-changed"})
                continue
            shutil.rmtree(path)
        except (OSError, SystemExit):
            retained.append({"name": entry_name, "reason": "delete-race-or-error"})
            continue
        removed.append(token)
    return {
        "removed_count": len(removed),
        "active_count": len(active),
        "retained_count": len(retained),
        "removed_tokens": removed,
        "active_tokens": active,
        "retained": retained,
    }


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
        if str(getattr(args, "expected_literature_stage_digest", "") or ""):
            staged_search, staged_candidate, _digest = _strict_literature_stage_candidate(
                root, args
            )
        else:
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
    source_origin = str(getattr(args, "source_origin", "") or "")
    if source_origin == HUMAN_NOTE_ORIGIN:
        snapshot = _snapshot_human_note(
            root,
            str(getattr(args, "human_note_area", "") or ""),
            str(getattr(args, "human_note_filename", "") or ""),
        )
        if source != snapshot.relative_path:
            raise SystemExit("Human-note intake source does not match the selected note.")
        source = snapshot.path.as_posix()
    elif source_origin:
        raise SystemExit("Unsupported source origin.")
    elif not source.startswith("http"):
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
            "expected_literature_stage_digest": str(
                getattr(args, "expected_literature_stage_digest", "") or ""
            ),
            "source_origin": str(getattr(args, "source_origin", "") or ""),
        }
    )


def _paper_metadata_values(*values):
    for value in values:
        if value not in (None, "", [], {}):
            return value
    return ""


def _merge_paper_citation_metadata(
    *,
    source: str,
    local_metadata: dict,
    parse_metadata: dict,
    staged_candidate: dict | None,
) -> dict:
    """Merge already-archived factual metadata without querying or guessing."""
    local = local_metadata if isinstance(local_metadata, dict) else {}
    parsed = parse_metadata if isinstance(parse_metadata, dict) else {}
    candidate = staged_candidate if isinstance(staged_candidate, dict) else {}
    candidate_metadata = candidate.get("metadata")
    candidate_metadata = candidate_metadata if isinstance(candidate_metadata, dict) else {}
    identities = candidate.get("identities")
    identities = identities if isinstance(identities, dict) else {}

    doi_inputs = [local.get("doi"), parsed.get("doi"), identities.get("doi")]
    dois = {normalize_doi(value) for value in doi_inputs if normalize_doi(value)}
    if len(dois) > 1:
        raise RuntimeError("Paper citation metadata contains conflicting DOI identities.")
    arxiv_inputs = [
        local.get("arxiv_id"),
        parsed.get("arxiv_id"),
        identities.get("arxiv_id"),
        parse_arxiv_id(source),
    ]
    arxiv_ids = {
        normalize_arxiv_id(value) for value in arxiv_inputs if normalize_arxiv_id(value)
    }
    if len(arxiv_ids) > 1:
        raise RuntimeError("Paper citation metadata contains conflicting arXiv identities.")

    bibtex = {
        "entry_type": "misc",
        "venue_field": "",
        "volume": "",
        "number": "",
        "pages": "",
        "publisher": "",
        "primary_class": "",
    }
    for metadata in (local, parsed):
        supplement = metadata.get("bibtex")
        if not isinstance(supplement, dict):
            continue
        for key in tuple(bibtex):
            value = str(supplement.get(key) or "").strip()
            if not value:
                continue
            current = str(bibtex.get(key) or "").strip()
            if key == "entry_type" and current == "misc" and value != "misc":
                bibtex[key] = value
            elif current in {"", value}:
                bibtex[key] = value
            elif value != "misc":
                raise RuntimeError(f"Paper citation metadata conflicts for BibTeX field {key}.")

    authors = _paper_metadata_values(
        local.get("authors"),
        parsed.get("authors"),
        candidate_metadata.get("authors"),
    )
    return {
        "title": str(_paper_metadata_values(local.get("title"), parsed.get("title")) or ""),
        "abstract": str(_paper_metadata_values(local.get("abstract"), parsed.get("abstract")) or ""),
        "year": _paper_metadata_values(
            local.get("year"),
            parsed.get("year"),
            candidate_metadata.get("publication_year"),
        ),
        "arxiv_id": next(iter(arxiv_ids), ""),
        "authors": [str(item).strip() for item in authors] if isinstance(authors, list) else [],
        "topics": list(local.get("topics", [])) if isinstance(local.get("topics"), list) else [],
        "tags": list(local.get("tags", [])) if isinstance(local.get("tags"), list) else [],
        "doi": next(iter(dois), ""),
        "venue": str(
            _paper_metadata_values(
                local.get("venue"), parsed.get("venue"), candidate_metadata.get("venue")
            )
            or ""
        ),
        "bibtex": bibtex,
    }


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
    prepared_record_id: str = "",
) -> tuple[dict, dict, str]:
    parse_metadata = source_info.get("parse_metadata") or {}
    title = initial_title
    if args.kind == "paper":
        paper_metadata = _merge_paper_citation_metadata(
            source=source,
            local_metadata=paper_metadata,
            parse_metadata=parse_metadata,
            staged_candidate=staged_candidate,
        )
        better_title = str(paper_metadata.get("title") or "").strip()
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
    if prepared_record_id:
        record["id"] = prepared_record_id
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
        record["payload"]["basic_info"]["doi"] = normalize_doi(paper_metadata.get("doi"))
        record["payload"]["basic_info"]["venue"] = str(paper_metadata.get("venue") or "")
        record["payload"]["basic_info"]["citation_key"] = citation_key_for_unit_id(record["id"])
        record["payload"]["basic_info"]["bibtex"] = dict(paper_metadata.get("bibtex") or {})
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
    source, initial_title, paper_metadata, staged_candidate, staged_search = _call_at_intake_stage(
        "source-recognition",
        _resolve_intake_request,
        root,
        args,
    )
    _call_at_intake_stage(
        "source-recognition", _assert_expected_literature_stage_digest, root, args
    )
    candidate_digest = _candidate_binding_digest(
        stage=staged_search,
        candidate=staged_candidate,
    )
    source_input_digest = _call_at_intake_stage(
        "source-recognition", _source_input_digest, root, source
    )
    token, prepared_root = _call_at_intake_stage("prepare-freeze", _new_prepared_dir, root)
    try:
        if staged_candidate is not None and staged_search is not None:
            if str(getattr(args, "expected_literature_stage_digest", "") or ""):
                current_stage, current_candidate, _digest = _strict_literature_stage_candidate(
                    root, args
                )
            else:
                current_stage = load_search_stage(root, args.stage_id)
                current_candidate = resolve_search_candidate(root, args.stage_id, args.candidate_id)
            if _candidate_binding_digest(stage=current_stage, candidate=current_candidate) != candidate_digest:
                raise RuntimeError("The selected staged candidate changed while intake was prepared.")
        preliminary_record = default_record(
            args.kind,
            title=initial_title,
            maturity=args.maturity,
            source={"original_uri": source},
        )
        source_origin = str(getattr(args, "source_origin", "") or "")
        if source_origin == HUMAN_NOTE_ORIGIN:
            human_snapshot = _snapshot_human_note(
                root,
                str(getattr(args, "human_note_area", "") or ""),
                str(getattr(args, "human_note_filename", "") or ""),
            )
            preliminary_record["id"] = canonical_unit_id_with_hash(
                "blog",
                title=initial_title,
                source=source,
                hash_value=human_snapshot.byte_sha256,
            )
        stage_dir = prepared_root / "kb" / "intake-staging" / str(preliminary_record["id"])
        duplicate_record_relative = ""
        duplicate_record_binding_digest = ""
        superseded_record_relative = ""
        superseded_record_binding_digest = ""
        duplicate = detect_duplicate(
            root,
            args.kind,
            source,
            title=initial_title,
            source_origin=source_origin,
        )
        if (
            duplicate is not None
            and _source_material_is_degraded(duplicate)
            and _source_upgrade_candidate_identity_matches(duplicate, source, initial_title)
            and not _degraded_unconfirmed_source(duplicate)
        ):
            raise RuntimeError(
                "The degraded unit already has verified or confirmed judgement; explicit user migration approval is required."
            )
        if duplicate is not None and _source_upgrade_identity_matches(
            duplicate, source, initial_title
        ):
            _old_record, old_path = locate_record(
                root,
                str(duplicate.get("id") or ""),
                kind=str(duplicate.get("kind") or args.kind),
                fuzzy=False,
            )
            superseded_record_relative = old_path.relative_to(root).as_posix()
            superseded_record_binding_digest = _path_snapshot_digest(old_path)
            duplicate = None
        if duplicate is not None:
            record, duplicate_record_path = locate_record(
                root,
                str(duplicate.get("id") or ""),
                kind=str(duplicate.get("kind") or args.kind),
                fuzzy=False,
            )
            duplicate_record_relative = duplicate_record_path.relative_to(root).as_posix()
            duplicate_record_binding_digest = _path_snapshot_digest(duplicate_record_path)
            stage_dir.mkdir(parents=True, exist_ok=False)
            canonical_source_info = {
                "backup_status": "duplicate-existing",
                "file_hash": str(record.get("source", {}).get("file_hash") or ""),
            }
            title = str(record.get("title") or initial_title)
        else:
            source_info = backup_source(
                prepared_root,
                args.kind,
                str(preliminary_record["id"]),
                source,
                unit_dir=stage_dir,
            )
            if source_origin == HUMAN_NOTE_ORIGIN:
                source_info["original_uri"] = _human_note_relative_path(
                    str(getattr(args, "human_note_area", "") or ""),
                    str(getattr(args, "human_note_filename", "") or ""),
                )
                source_info["source_origin"] = HUMAN_NOTE_ORIGIN
            write_parse_cache(stage_dir, str(preliminary_record["id"]), source_info)
            readiness_error = source_backup_error(prepared_root, args.kind, source_info)
            if readiness_error:
                raise RuntimeError(readiness_error)
            parse_metadata = source_info.get("parse_metadata")
            parsed_title = (
                str(parse_metadata.get("title") or "").strip()
                if isinstance(parse_metadata, dict)
                else ""
            )
            duplicate_title = parsed_title or initial_title
            byte_duplicate = detect_duplicate(
                root,
                args.kind,
                source,
                title=duplicate_title,
                candidate_file_hash=str(source_info.get("file_hash") or ""),
                source_origin=source_origin,
            )
            if (
                byte_duplicate is not None
                and _source_material_is_degraded(byte_duplicate)
                and _source_upgrade_candidate_identity_matches(
                    byte_duplicate, source, duplicate_title
                )
                and not _degraded_unconfirmed_source(byte_duplicate)
            ):
                raise RuntimeError(
                    "The degraded unit already has verified or confirmed judgement; explicit user migration approval is required."
                )
            if byte_duplicate is not None and _source_upgrade_identity_matches(
                byte_duplicate, source, duplicate_title
            ):
                if not _source_upgrade_is_complete(source_info):
                    raise RuntimeError(
                        "The replacement source did not pass the complete-material gate; the degraded unit was preserved."
                    )
                _old_record, old_path = locate_record(
                    root,
                    str(byte_duplicate.get("id") or ""),
                    kind=str(byte_duplicate.get("kind") or args.kind),
                    fuzzy=False,
                )
                current_relative = old_path.relative_to(root).as_posix()
                current_digest = _path_snapshot_digest(old_path)
                if superseded_record_relative and (
                    current_relative != superseded_record_relative
                    or current_digest != superseded_record_binding_digest
                ):
                    raise RuntimeError("The source upgrade matched more than one canonical unit.")
                superseded_record_relative = current_relative
                superseded_record_binding_digest = current_digest
                byte_duplicate = None
            if byte_duplicate is not None:
                record, duplicate_record_path = locate_record(
                    root,
                    str(byte_duplicate.get("id") or ""),
                    kind=str(byte_duplicate.get("kind") or args.kind),
                    fuzzy=False,
                )
                duplicate_record_relative = duplicate_record_path.relative_to(root).as_posix()
                duplicate_record_binding_digest = _path_snapshot_digest(
                    duplicate_record_path
                )
                canonical_source_info = source_info
                title = str(record.get("title") or initial_title)
            else:
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
                    prepared_record_id=str(preliminary_record["id"]),
                )
                if superseded_record_relative:
                    if not _source_upgrade_is_complete(source_info):
                        raise RuntimeError(
                            "The replacement source did not pass the complete-material gate; the degraded unit was preserved."
                        )
                    old_id = Path(superseded_record_relative).parent.name
                    if str(record.get("id") or "") == old_id:
                        raise RuntimeError("A source upgrade must create a new canonical unit revision.")
        if _source_input_digest(root, source) != source_input_digest:
            raise RuntimeError("The intake source changed while its snapshot was prepared.")
        _assert_expected_literature_stage_digest(root, args)
        _harden_prepared_tree(stage_dir)
        source_content_digest = _path_snapshot_digest(stage_dir)
        prepared_record_digest = _prepared_record_binding_digest(
            record,
            duplicate_record_binding_digest=duplicate_record_binding_digest,
            superseded_record_binding_digest=superseded_record_binding_digest,
        )
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
            "duplicate_record_relative": duplicate_record_relative,
            "duplicate_record_binding_digest": duplicate_record_binding_digest,
            "superseded_record_relative": superseded_record_relative,
            "superseded_record_binding_digest": superseded_record_binding_digest,
            "canonical_inputs": context,
            "record": record,
            "source_info": canonical_source_info,
        }
        payload["manifest_digest"] = _canonical_digest(payload)
        _write_prepared_manifest(prepared_root / "prepared.json", payload)
        return payload
    except BaseException as exc:
        if isinstance(exc, (Exception, SystemExit)):
            _tag_intake_failure(exc, "prepare-freeze")
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
        "duplicate_record_relative",
        "duplicate_record_binding_digest",
        "superseded_record_relative",
        "superseded_record_binding_digest",
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
    _assert_expected_literature_stage_digest(root, args)
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
    duplicate_record_relative = str(payload.get("duplicate_record_relative") or "")
    duplicate_record_binding_digest = str(
        payload.get("duplicate_record_binding_digest") or ""
    )
    if bool(duplicate_record_relative) != bool(duplicate_record_binding_digest):
        raise SystemExit("Prepared intake duplicate binding is incomplete.")
    if duplicate_record_relative:
        duplicate_relative = Path(duplicate_record_relative)
        if duplicate_relative.is_absolute() or ".." in duplicate_relative.parts:
            raise SystemExit("Prepared intake duplicate record escaped the workspace.")
        current_duplicate, current_duplicate_path = locate_record(
            root,
            str(record.get("id") or ""),
            kind=str(record.get("kind") or args.kind),
            fuzzy=False,
        )
        if current_duplicate_path.relative_to(root).as_posix() != duplicate_record_relative:
            raise SystemExit("Prepared intake duplicate record identity changed.")
        if _path_snapshot_digest(current_duplicate_path) != duplicate_record_binding_digest:
            raise SystemExit("Prepared intake duplicate record changed after preparation.")
        if current_duplicate != record:
            raise SystemExit("Prepared intake duplicate record content changed after preparation.")
    superseded_record_relative = str(payload.get("superseded_record_relative") or "")
    superseded_record_binding_digest = str(
        payload.get("superseded_record_binding_digest") or ""
    )
    if bool(superseded_record_relative) != bool(superseded_record_binding_digest):
        raise SystemExit("Prepared intake source-upgrade binding is incomplete.")
    if superseded_record_relative:
        superseded_relative = Path(superseded_record_relative)
        if superseded_relative.is_absolute() or ".." in superseded_relative.parts:
            raise SystemExit("Prepared intake source-upgrade record escaped the workspace.")
        superseded_id = superseded_relative.parent.name
        current_superseded, current_superseded_path = locate_record(
            root,
            superseded_id,
            kind="paper",
            fuzzy=False,
        )
        if current_superseded_path.relative_to(root).as_posix() != superseded_record_relative:
            raise SystemExit("Prepared intake source-upgrade identity changed.")
        if _path_snapshot_digest(current_superseded_path) != superseded_record_binding_digest:
            raise SystemExit("Prepared intake source-upgrade record changed after preparation.")
        if not _source_upgrade_identity_matches(
            current_superseded, source, str(payload.get("title") or "")
        ) or not _source_upgrade_is_complete(source_info):
            raise SystemExit("Prepared intake source-upgrade eligibility changed after preparation.")
    if _prepared_record_binding_digest(
        record,
        duplicate_record_binding_digest=duplicate_record_binding_digest,
        superseded_record_binding_digest=superseded_record_binding_digest,
    ) != payload.get("prepared_record_digest"):
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


def _index_transaction_target_paths(root: Path) -> list[Path]:
    """Canonical indexes plus the disposable cache written by build_index()."""
    return [*_index_target_paths(root), passage_search_cache_path(root)]


def _batch_item_args(raw: str) -> argparse.Namespace:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise SystemExit("Batch intake item is not valid JSON.") from exc
    if not isinstance(payload, dict) or set(payload) - {
        "kind",
        "source",
        "title",
        "maturity",
        "pool",
        "preference_selection_id",
    }:
        raise SystemExit("Batch intake item has unsupported fields.")
    kind = str(payload.get("kind") or "")
    source = str(payload.get("source") or "")
    maturity = str(payload.get("maturity") or "lightweight")
    pools = payload.get("pool", [])
    if kind not in {"paper", "repo", "dataset", "blog"}:
        raise SystemExit("Batch intake item has an unsupported source kind.")
    if not source.strip():
        raise SystemExit("Batch intake item requires a source.")
    if maturity not in {"lightweight", "complete"}:
        raise SystemExit("Batch intake item has an unsupported maturity.")
    if not isinstance(pools, list) or any(not isinstance(item, str) for item in pools):
        raise SystemExit("Batch intake item pools must be a list of strings.")
    return argparse.Namespace(
        command="batch-add",
        kind=kind,
        source=source,
        maturity=maturity,
        title=str(payload.get("title") or ""),
        stage_id="",
        candidate_id="",
        pool=list(pools),
        user_authorization="",
        authorization_source="",
        preference_selection_id=str(payload.get("preference_selection_id") or ""),
        prepared_intake_token="",
        expected_literature_stage_digest="",
    )


def _batch_commit_guard(root: Path, prepared_items: list[dict[str, object]]) -> None:
    """Revalidate every external source at the final publication boundary."""
    for item in prepared_items:
        source = str(item.get("source") or "")
        if _source_input_digest(root, source) != str(item.get("source_input_digest") or ""):
            raise RuntimeError("A batch intake source changed before commit.")


def _single_commit_guard(
    root: Path,
    args: argparse.Namespace,
    prepared: dict[str, object],
) -> None:
    """Revalidate the selected source at the final single-intake publication boundary."""
    source = str(prepared.get("source") or "")
    if str(getattr(args, "source_origin", "") or "") == HUMAN_NOTE_ORIGIN:
        snapshot = _snapshot_human_note(
            root,
            str(getattr(args, "human_note_area", "") or ""),
            str(getattr(args, "human_note_filename", "") or ""),
        )
        if snapshot.path.as_posix() != source:
            raise RuntimeError("The selected human note changed before commit.")
    if _source_input_digest(root, source) != str(prepared.get("source_input_digest") or ""):
        raise RuntimeError("The intake source bytes changed before commit.")


def _batch_dedup_key(
    item_args: argparse.Namespace,
    prepared: dict[str, object],
) -> tuple[str, str]:
    source_info = prepared.get("source_info")
    file_hash = (
        str(source_info.get("file_hash") or "")
        if isinstance(source_info, dict)
        else ""
    )
    identity = file_hash or str(prepared.get("source_input_digest") or "")
    return str(item_args.kind), identity


def _run_batch_add(root: Path, raw_items: list[str]) -> dict[str, object]:
    failure_stage = "source-recognition"
    if not 1 <= len(raw_items) <= BATCH_INTAKE_MAX_ITEMS:
        exc = SystemExit(f"Batch intake requires 1..{BATCH_INTAKE_MAX_ITEMS} items.")
        _tag_intake_failure(exc, failure_stage)
        raise exc
    args_items = [
        _call_at_intake_stage("source-recognition", _batch_item_args, raw)
        for raw in raw_items
    ]
    prepared_rows: list[tuple[argparse.Namespace, dict[str, object], str]] = []
    prepared_tokens: list[str] = []
    try:
        # Finish all external snapshot/parse work before the first canonical write.
        failure_stage = "prepare-freeze"
        for item_args in args_items:
            prepared = _prepare_intake_snapshot(root, item_args)
            token = str(prepared["token"])
            prepared_tokens.append(token)
            prepared_rows.append((item_args, prepared, token))

        unique_rows: list[tuple[argparse.Namespace, dict[str, object], str]] = []
        request_keys: list[tuple[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for item_args, prepared, token in prepared_rows:
            key = _batch_dedup_key(item_args, prepared)
            request_keys.append(key)
            if key in seen:
                continue
            seen.add(key)
            unique_rows.append((item_args, prepared, token))

        ready: list[dict[str, object]] = []
        outcomes: dict[tuple[str, str], dict[str, object]] = {}
        for item_args, _prepared, token in unique_rows:
            _call_at_intake_stage("prepare-freeze", _claim_prepared_intake, root, token)
            prepared, stage_dir = _call_at_intake_stage(
                "prepare-freeze", _load_prepared_intake, root, item_args, token
            )
            if str(prepared.get("superseded_record_relative") or ""):
                raise SystemExit("Source upgrades must be applied as a single-item intake.")
            record = prepared.get("record")
            source_info = prepared.get("source_info")
            canonical_inputs = prepared.get("canonical_inputs")
            if not isinstance(record, dict) or not isinstance(source_info, dict) or not isinstance(
                canonical_inputs, dict
            ):
                raise SystemExit("Prepared batch intake snapshot is incomplete.")
            source = str(prepared.get("source") or "")
            title = str(prepared.get("title") or "")
            _paper_preferences, preference_state = resolve_intake_preferences(
                root,
                item_args,
                source=source,
                title=title,
                canonical_pools=list(record.get("candidate_pools") or []),
                canonical_inputs=canonical_inputs,
            )
            _call_at_intake_stage(
                "prepare-freeze", _load_prepared_intake, root, item_args, token
            )
            record["payload"]["preference_contract"] = operation_contract(
                skill="source-intake", operation="add"
            )
            record["payload"]["preference_context"] = preference_state
            selection = dict(preference_state.get("selection_binding") or {})
            if selection:
                record["payload"]["preference_binding"] = selection
            else:
                record["payload"].pop("preference_binding", None)
            key = _batch_dedup_key(item_args, prepared)
            duplicate = detect_duplicate(
                root,
                item_args.kind,
                source,
                title=title,
                candidate_file_hash=str(source_info.get("file_hash") or ""),
            )
            if duplicate is not None:
                if not str(prepared.get("duplicate_record_binding_digest") or ""):
                    raise SystemExit(
                        "A duplicate appeared after batch preparation; retry with fresh snapshots."
                    )
                outcomes[key] = {
                    "status": "duplicate",
                    "kind": str(duplicate.get("kind") or item_args.kind),
                    "unit_id": str(duplicate.get("id") or ""),
                }
                continue
            ready.append(
                {
                    "args": item_args,
                    "prepared": prepared,
                    "stage_dir": stage_dir,
                    "record": record,
                    "source_info": source_info,
                    "key": key,
                }
            )

        if ready:
            failure_stage = "canonical-transaction"
            seed_targets = [path for path in _workspace_seed_paths(root) if not path.exists()]
            checkpoint_targets = [*seed_targets, *_index_target_paths(root)]
            for item in ready:
                item_args = item["args"]
                record = item["record"]
                assert isinstance(item_args, argparse.Namespace) and isinstance(record, dict)
                checkpoint_targets.extend(
                    [
                        unit_root(root, item_args.kind, str(record["id"])),
                        kb_root(root)
                        / ".runtime"
                        / "intake-staging"
                        / "legacy-failed-units"
                        / str(record["id"]),
                    ]
                )
            checkpoint_targets = list(dict.fromkeys(checkpoint_targets))
            transaction_targets = list(
                dict.fromkeys([*checkpoint_targets, passage_search_cache_path(root)])
            )
            prepared_for_guard = [
                dict(item["prepared"])
                for item in ready
                if isinstance(item.get("prepared"), dict)
            ]
            with mutation_transaction(
                root,
                "source-intake-batch-add",
                transaction_targets,
                commit_guard=lambda: _batch_commit_guard(root, prepared_for_guard),
            ):
                ensure_workspace(root)
                for item in ready:
                    item_args = item["args"]
                    prepared = item["prepared"]
                    record = item["record"]
                    source_info = item["source_info"]
                    stage_dir = item["stage_dir"]
                    assert isinstance(item_args, argparse.Namespace)
                    assert isinstance(prepared, dict) and isinstance(record, dict)
                    assert isinstance(source_info, dict) and isinstance(stage_dir, Path)
                    _call_at_intake_stage(
                        "prepare-freeze",
                        _load_prepared_intake,
                        root,
                        item_args,
                        str(prepared["token"]),
                    )
                    path, duplicate, _canonical_source_info = _call_at_intake_stage(
                        "materialization",
                        _materialize_staged_source,
                        root,
                        kind=item_args.kind,
                        source=str(prepared.get("source") or ""),
                        title=str(prepared.get("title") or ""),
                        record=record,
                        source_info=source_info,
                        stage_dir=stage_dir,
                    )
                    if duplicate is not None or path is None:
                        raise SystemExit(
                            "A duplicate appeared during batch publication; the batch was rolled back."
                        )
                    outcomes[item["key"]] = {
                        "status": "created",
                        "kind": item_args.kind,
                        "unit_id": str(record["id"]),
                    }
                _build_index_transaction(root)
            failure_stage = "checkpoint"
            _call_at_intake_stage(
                "checkpoint",
                checkpoint_and_report,
                root,
                trigger="milestone",
                message=f"milestone: intake batch ({len(ready)})",
                target_paths=checkpoint_targets,
            )
            failure_stage = "unknown"

        results: list[dict[str, object]] = []
        emitted: set[tuple[str, str]] = set()
        for key in request_keys:
            outcome = dict(outcomes[key])
            if key in emitted:
                outcome["status"] = "merged"
            emitted.add(key)
            results.append(outcome)
        return {
            "item_count": len(raw_items),
            "created_count": sum(1 for item in outcomes.values() if item["status"] == "created"),
            "duplicate_count": sum(1 for item in results if item["status"] != "created"),
            "results": results,
        }
    except (Exception, SystemExit) as exc:
        _tag_intake_failure(exc, failure_stage)
        raise
    finally:
        for token in prepared_tokens:
            _safe_remove_prepared(root, token)


def _materialize_staged_source(
    root: Path,
    *,
    kind: str,
    source: str,
    title: str,
    record: dict,
    source_info: dict,
    stage_dir: Path,
    source_origin: str = "",
    superseded_record_id: str = "",
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
            source_origin=source_origin,
        )
        if duplicate and str(duplicate.get("id") or "") != superseded_record_id:
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
    targets = _index_transaction_target_paths(root)
    with mutation_transaction(root, "source-intake-build-index", targets):
        return build_index(root)


def _intake_transaction_targets(
    root: Path,
    *,
    unit_dir: Path,
    unit_id: str,
    stage_id: str = "",
    superseded_record_path: Path | None = None,
) -> list[Path]:
    targets = [
        unit_dir,
        *_index_transaction_target_paths(root),
        # A rejected legacy unit may be quarantined during materialization.  The
        # command-level snapshot must remove/restore that KB-local move as one op.
        kb_root(root) / ".runtime" / "intake-staging" / "legacy-failed-units" / unit_id,
    ]
    if stage_id:
        targets.append(search_stage_path(root, stage_id))
    if superseded_record_path is not None:
        targets.append(superseded_record_path)
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
    preference_state: dict[str, object] | None = None,
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
        if preference_state:
            preference_receipt = {
                "stage_id": stage_id,
                "candidate_id": candidate_id,
                "task_context_digest": str(
                    preference_state.get("task_context_digest") or ""
                ),
                "selection_binding": dict(
                    preference_state.get("selection_binding") or {}
                ),
                "hard_value_digests": dict(
                    preference_state.get("hard_value_digests") or {}
                ),
            }
            preference_bindings = [
                item
                for item in source_search.get("preference_bindings", [])
                if isinstance(item, dict)
            ]
            prior_bindings = [
                item
                for item in preference_bindings
                if item.get("stage_id") == stage_id
                and item.get("candidate_id") == candidate_id
            ]
            if prior_bindings and (
                len(prior_bindings) != 1 or prior_bindings[0] != preference_receipt
            ):
                raise SystemExit(
                    "A staged candidate preference binding cannot be rebound after intake."
                )
            if not prior_bindings:
                preference_bindings.append(preference_receipt)
            source_search["preference_bindings"] = sorted(
                preference_bindings,
                key=lambda item: (
                    str(item.get("stage_id") or ""),
                    str(item.get("candidate_id") or ""),
                ),
            )
    return repr(source_search) != before


def _attach_duplicate_selection_and_mark(
    root: Path,
    *,
    args: argparse.Namespace,
    duplicate: dict,
    expected_record_binding_digest: str = "",
    expected_prepared_record_digest: str = "",
    expected_candidate_binding_digest: str = "",
    preference_state: dict[str, object] | None = None,
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
        if str(getattr(args, "expected_literature_stage_digest", "") or ""):
            stage, candidate, _digest = _strict_literature_stage_candidate(root, args)
        else:
            stage = load_search_stage(root, args.stage_id)
            candidate = resolve_search_candidate(root, args.stage_id, args.candidate_id)
        current, _ = locate_record(
            root,
            str(duplicate.get("id") or ""),
            kind=str(duplicate.get("kind") or args.kind),
            fuzzy=False,
        )
        current_binding_digest = _path_snapshot_digest(record_path)
        if (
            not expected_record_binding_digest
            or current_binding_digest != expected_record_binding_digest
        ):
            raise SystemExit("The duplicate record changed after intake preparation.")
        if _prepared_record_binding_digest(
            current,
            duplicate_record_binding_digest=current_binding_digest,
        ) != expected_prepared_record_digest:
            raise SystemExit("The duplicate record content changed after intake preparation.")
        if _candidate_binding_digest(stage=stage, candidate=candidate) != str(
            expected_candidate_binding_digest or ""
        ):
            raise SystemExit("The selected candidate changed after intake preparation.")
        changed = _attach_source_search_selection(
            current,
            stage=stage,
            candidate=candidate,
            stage_id=args.stage_id,
            candidate_id=args.candidate_id,
            user_authorization=args.user_authorization,
            authorization_source=args.authorization_source,
            preference_state=preference_state,
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
    prepared: dict[str, object],
) -> tuple[Path | None, dict | None, dict, list[str], bool, Path | None]:
    """Materialize and derive one intake as one undoable command transaction."""
    superseded_relative = str(prepared.get("superseded_record_relative") or "")
    superseded_digest = str(prepared.get("superseded_record_binding_digest") or "")
    superseded_path = root / superseded_relative if superseded_relative else None
    superseded_id = Path(superseded_relative).parent.name if superseded_relative else ""
    targets = _intake_transaction_targets(
        root,
        unit_dir=unit_dir,
        unit_id=str(record["id"]),
        stage_id=str(args.stage_id or ""),
        superseded_record_path=superseded_path,
    )
    auto_outputs: list[str] = []
    note_created = False
    updated_stage_path: Path | None = None
    try:
        with mutation_transaction(
            root,
            "source-intake-add",
            targets,
            commit_guard=lambda: _single_commit_guard(root, args, prepared),
        ):
            _assert_expected_literature_stage_digest(root, args)
            superseded_record: dict | None = None
            if superseded_path is not None:
                superseded_record, current_path = locate_record(
                    root,
                    superseded_id,
                    kind="paper",
                    fuzzy=False,
                )
                if (
                    current_path != superseded_path
                    or _path_snapshot_digest(current_path) != superseded_digest
                    or not _source_upgrade_identity_matches(superseded_record, source, title)
                    or not _source_upgrade_is_complete(source_info)
                ):
                    raise SystemExit("The source-upgrade binding changed before publication.")
                _ensure_source_revision_link(record, superseded_id, "supersedes")
            path, concurrent_duplicate, canonical_source_info = _call_at_intake_stage(
                "materialization",
                _materialize_staged_source,
                root,
                kind=args.kind,
                source=source,
                title=title,
                record=record,
                source_info=source_info,
                stage_dir=stage_dir,
                source_origin=str(getattr(args, "source_origin", "") or ""),
                superseded_record_id=superseded_id,
            )
            if concurrent_duplicate:
                raise SystemExit(
                    "A duplicate appeared after intake preparation; retry with a fresh snapshot."
                )
            if path is None:
                raise RuntimeError("Source materialization completed without a canonical record path.")

            if superseded_record is not None:
                superseded_record["status"] = "archived"
                _ensure_source_revision_link(
                    superseded_record,
                    str(record.get("id") or ""),
                    "superseded_by",
                )
                append_history(
                    superseded_record,
                    action="source-revision-superseded",
                    summary="Archived after a complete replacement source was materialized as a new unit.",
                    information_types=["fact"],
                )
                write_record(root, superseded_record)

            # Source intake never authors or prepares research understanding.  The
            # public wrapper consumes link_autodrive and, when requested, starts the
            # analyzer's unified deep-read prepare after this transaction commits.

            _build_index_transaction(root)
            if args.stage_id and args.candidate_id:
                updated_stage_path = mark_search_candidate(
                    root,
                    args.stage_id,
                    args.candidate_id,
                    status="materialized",
                    record_id=str(record["id"]),
                )
    except (Exception, SystemExit) as exc:
        _tag_intake_failure(exc, "canonical-transaction")
        raise
    return path, None, canonical_source_info, auto_outputs, note_created, updated_stage_path


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)

    if args.command == "human-note":
        try:
            args = _call_at_intake_stage(
                "source-recognition", _normalize_human_note_args, root, args
            )
        except (Exception, SystemExit) as exc:
            _publish_intake_failure_stage(root, "add", exc)
            raise

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

    if args.command == "batch-add":
        try:
            payload = _run_batch_add(root, list(args.item or []))
        except (Exception, SystemExit) as exc:
            # The dispatcher exposes both single and batch intake as `kb add`.
            _publish_intake_failure_stage(root, "add", exc)
            error = str(exc).strip() or exc.__class__.__name__
            raise SystemExit(f"Batch source intake failed; retry is safe: {error}") from exc
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "garden-prepared":
        print(json.dumps(_garden_prepared_intakes(root), ensure_ascii=False, sort_keys=True))
        return 0

    if args.command == "prepare-add":
        try:
            prepared = _prepare_intake_snapshot(root, args)
        except (Exception, SystemExit) as exc:
            _publish_intake_failure_stage(root, "add", exc)
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
            _publish_intake_failure_stage(root, "add", exc)
            error = str(exc).strip() or exc.__class__.__name__
            raise SystemExit(f"Source intake failed; retry is safe: {error}") from exc
    claimed = False
    failure_stage = "prepare-freeze"
    try:
        _call_at_intake_stage("prepare-freeze", _claim_prepared_intake, root, token)
        claimed = True
        prepared, stage_dir = _call_at_intake_stage(
            "prepare-freeze", _load_prepared_intake, root, args, token
        )
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
        _call_at_intake_stage("prepare-freeze", _load_prepared_intake, root, args, token)

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
            source_origin=str(getattr(args, "source_origin", "") or ""),
        )
        superseded_relative = str(prepared.get("superseded_record_relative") or "")
        superseded_id = Path(superseded_relative).parent.name if superseded_relative else ""
        if duplicate and str(duplicate.get("id") or "") == superseded_id:
            duplicate = None
        if duplicate:
            duplicate_record_binding_digest = str(
                prepared.get("duplicate_record_binding_digest") or ""
            )
            if not duplicate_record_binding_digest:
                raise SystemExit(
                    "A duplicate appeared after intake preparation; retry with a fresh snapshot."
                )
            _call_at_intake_stage(
                "canonical-transaction",
                _attach_duplicate_selection_and_mark,
                root,
                args=args,
                duplicate=duplicate,
                expected_record_binding_digest=duplicate_record_binding_digest,
                expected_prepared_record_digest=str(
                    prepared.get("prepared_record_digest") or ""
                ),
                expected_candidate_binding_digest=str(
                    prepared.get("candidate_binding_digest") or ""
                ),
                preference_state=preference_state,
            )
            print(f"[ok] duplicate detected: {duplicate['id']}")
            return 0

        failure_stage = "canonical-transaction"
        _call_at_intake_stage("canonical-transaction", ensure_workspace, root)
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
                prepared=prepared,
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
        if superseded_relative:
            checkpoint_targets.append(root / superseded_relative)
        if updated_stage_path is not None:
            checkpoint_targets.append(updated_stage_path)
        failure_stage = "checkpoint"
        _call_at_intake_stage(
            "checkpoint",
            checkpoint_and_report,
            root,
            trigger="milestone",
            message=f"milestone: intake {args.kind} {record['id']}",
            target_paths=list(dict.fromkeys(checkpoint_targets)),
        )
        failure_stage = "unknown"
        for hint in guidance_hints(
            args.kind,
            paper_preferences,
            has_pdf=has_pdf,
            note_created=note_created,
        ):
            print(f"[hint] {hint}")
        if superseded_id:
            print(f"[source] upgraded_from={superseded_id}")
        print(next_for_agent_intake(root, args.kind, record["id"]))
        return 0
    except (Exception, SystemExit) as exc:
        _tag_intake_failure(exc, failure_stage)
        _publish_intake_failure_stage(root, "add", exc)
        raise
    finally:
        if claimed or created_here:
            _safe_remove_prepared(root, token)


if __name__ == "__main__":
    raise SystemExit(main())
