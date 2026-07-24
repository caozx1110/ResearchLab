#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
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

from research.common import add_project_root_argument, confirm_command as shared_confirm_command, extract_pdf_record, load_yaml, parse_arxiv_id, print_resolved_project_roots, skill_script_for_command, utc_now_iso, write_yaml_if_changed
from research.confirm import require_user_authorization
from research.journal import journal_subprocess_env, mutation_transaction
from research.intake_cli import add_intake_add_arguments
from research.preference_selection import operation_contract, resolve_task_preferences, selection_binding
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
        # Authorization text can contain sensitive user wording.  Bind its
        # canonical value without ever copying it into a preference receipt.
        "authorization_digest": _canonical_digest(
            {
                "user_authorization": str(args.user_authorization or "").strip(),
                "authorization_source": str(args.authorization_source or "").strip(),
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
) -> tuple[dict[str, object], dict[str, object]]:
    """Return selected runtime.paper values plus a value-free persistence binding."""
    selection_id = str(getattr(args, "preference_selection_id", "") or "")
    if str(args.kind) != "paper" or not selection_id:
        return {}, {}
    effective = resolve_task_preferences(
        root,
        selection_id=selection_id,
        skill="source-intake",
        operation="add",
        canonical_inputs=intake_preference_context(
            args,
            source=source,
            title=title,
            canonical_pools=canonical_pools,
        ),
    )
    selected = {
        str(item.get("path") or ""): item.get("value")
        for item in effective.get("effective_items", [])
        if isinstance(item, dict)
    }
    raw = selected.get("runtime.paper")
    return (dict(raw) if isinstance(raw, dict) else {}), selection_binding(effective)


def stage_candidates(args: argparse.Namespace) -> list[dict]:
    titles = list(args.candidate_title)
    candidates = []
    for index, url in enumerate(args.candidate_url):
        title = titles[index] if index < len(titles) else ""
        candidates.append({"title": title, "url": url})
    return candidates


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


def _new_intake_stage_dir(root: Path, unit_id: str) -> Path:
    return kb_root(root) / ".runtime" / "intake-staging" / unit_id / uuid.uuid4().hex


def _record_staging_failure(
    stage_dir: Path,
    *,
    kind: str,
    unit_id: str,
    source: str,
    error: str,
    source_info: dict | None = None,
) -> Path:
    path = stage_dir / "failure.yaml"
    write_yaml_if_changed(
        path,
        {
            "status": "failed_retryable",
            "kind": kind,
            "unit_id": unit_id,
            "source": source,
            "error": error,
            "failed_at": utc_now_iso(),
            "backup_status": str((source_info or {}).get("backup_status") or ""),
            "backup_warning": str((source_info or {}).get("backup_warning") or ""),
        },
    )
    return path


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
    canonical_source_info = rebase_source_backup_paths(
        root,
        source_info,
        from_unit_dir=stage_dir,
        to_unit_dir=canonical_dir,
    )
    record["source"] = source_record_fields(canonical_source_info)
    quarantine_root = (
        kb_root(root)
        / ".runtime"
        / "intake-staging"
        / "legacy-failed-units"
        / str(record["id"])
    )
    rollback_targets = [canonical_dir, stage_dir, quarantine_root]
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
    intake_stage_dir: Path,
    stage_id: str = "",
) -> list[Path]:
    targets = [
        unit_dir,
        intake_stage_dir,
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
        intake_stage_dir=stage_dir,
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
    missing_seed_paths = [path for path in _workspace_seed_paths(root) if not path.exists()]
    ensure_workspace(root)
    created_seed_paths = [path for path in missing_seed_paths if path.exists()]

    if args.command in {"search", "stage-search"}:
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

    source = args.source
    staged_candidate = None
    if args.stage_id and args.candidate_id:
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
        raise SystemExit("Provide --source or use --stage-id + --candidate-id.")
    if not source.startswith("http"):
        try:
            validate_local_source(root, source)
        except UnsafeLocalSourceError as exc:
            raise SystemExit(str(exc)) from exc
    source = normalize_storage_reference(root, source) if not source.startswith("http") else source
    paper_metadata = infer_paper_metadata(root, source) if args.kind == "paper" else {}
    title = (
        args.title
        or (str(staged_candidate.get("title") or "") if staged_candidate else "")
        or str(paper_metadata.get("title") or "").strip()
        or infer_title(source)
    )

    duplicate = detect_duplicate(root, args.kind, source, title=title)
    if duplicate:
        _attach_duplicate_selection_and_mark(root, args=args, duplicate=duplicate)
        print(f"[ok] duplicate detected: {duplicate['id']}")
        return 0

    record = default_record(args.kind, title=title, maturity=args.maturity, source={"original_uri": source})
    unit_dir = unit_root(root, args.kind, record["id"])
    stage_dir = _new_intake_stage_dir(root, record["id"])
    source_info: dict = {}
    staged_parse_cache: Path | None = None
    try:
        source_info = backup_source(root, args.kind, record["id"], source, unit_dir=stage_dir)
        staged_parse_cache = write_parse_cache(stage_dir, record["id"], source_info)
        readiness_error = source_backup_error(root, args.kind, source_info)
        if readiness_error:
            raise RuntimeError(readiness_error)
    except (Exception, SystemExit) as exc:
        error = str(exc).strip() or exc.__class__.__name__
        _record_staging_failure(
            stage_dir,
            kind=args.kind,
            unit_id=str(record["id"]),
            source=source,
            error=error,
            source_info=source_info,
        )
        raise SystemExit(f"Source intake failed; retry is safe: {error}") from exc

    canonical_source_info = rebase_source_backup_paths(
        root,
        source_info,
        from_unit_dir=stage_dir,
        to_unit_dir=unit_dir,
    )
    # Only the on-disk source contract keys go into record.source; backup status /
    # warnings stay in retryable staging and public diagnostics.
    record["source"] = source_record_fields(canonical_source_info)
    backup_warning = str(source_info.get("backup_warning") or "").strip()
    parse_cache_path = unit_dir / "parse-cache.yaml" if staged_parse_cache is not None else None
    # For URL papers (arxiv/PDF) the lightweight download path yields metadata the
    # legacy local PyPDF path could not; fold it in when we have nothing better.
    parse_metadata = source_info.get("parse_metadata") or {}
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
            record["title"] = better_title
    elif parse_metadata:
        better_title = str(parse_metadata.get("title") or "").strip()
        if better_title and not args.title and not (staged_candidate and staged_candidate.get("title")):
            title = better_title
            record["title"] = better_title
    record["status"] = "active"
    # Intake archives and indexes the source; it does not understand the
    # material.  Leave the summary empty until a runtime agent writes grounded
    # analysis instead of persisting a generic scaffold sentence as knowledge.
    record["summary"] = ""
    explicit_topics = list(staged_candidate.get("topics", []) if staged_candidate else [])
    explicit_tags = list(staged_candidate.get("tags", []) if staged_candidate else [])
    if args.kind == "paper":
        explicit_topics.extend(str(item) for item in paper_metadata.get("topics", []) if str(item).strip())
        explicit_tags.extend(str(item) for item in paper_metadata.get("tags", []) if str(item).strip())
    record = apply_record_governance(
        root,
        record,
        explicit_topics=explicit_topics,
        explicit_tags=explicit_tags,
        explicit_pools=args.pool + (staged_candidate.get("pool_hints", []) if staged_candidate else []),
        infer_missing=True,
        source_label="source-intake",
    )
    if staged_candidate:
        stage_payload = load_search_stage(root, args.stage_id)
        _attach_source_search_selection(
            record,
            stage=stage_payload,
            candidate=staged_candidate,
            stage_id=args.stage_id,
            candidate_id=args.candidate_id,
            user_authorization=args.user_authorization,
            authorization_source=args.authorization_source,
        )

    if args.kind == "paper":
        canonical_arxiv_id = str(paper_metadata.get("arxiv_id") or parse_arxiv_id(source) or "").split("v", 1)[0]
        record["payload"]["basic_info"]["title"] = title
        record["payload"]["basic_info"]["authors"] = list(paper_metadata.get("authors", []))
        record["payload"]["basic_info"]["year"] = str(paper_metadata.get("year") or "")
        record["payload"]["basic_info"]["source_url"] = canonical_paper_source_url(source, paper_metadata)
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
    paper_preferences, preference_binding = resolve_intake_preferences(
        root,
        args,
        source=source,
        title=title,
        canonical_pools=list(record.get("candidate_pools") or []),
    )
    record["payload"]["preference_contract"] = operation_contract(
        skill="source-intake", operation="add"
    )
    if preference_binding:
        record["payload"]["preference_binding"] = preference_binding
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
    has_pdf = str(source_info.get("source_type") or "") == "pdf" or source.lower().endswith(".pdf")
    print(f"[ok] created {path.relative_to(root)}")
    backup_status = str(source_info.get("backup_status") or "").strip()
    if backup_status:
        print(f"[source] backup_status={backup_status} source_type={source_info.get('source_type') or '-'} locator_kind={source_info.get('locator_kind') or '-'}")
    if parse_cache_path is not None:
        print(f"[source] parse-cache: {parse_cache_path.relative_to(root)} ({len(source_info.get('parse_chunks') or [])} chunks)")
    if backup_warning:
        print(f"[warn] source archive: {backup_warning}")
    print(f"待内容补全并校验后，再请你确认条目 {record['id']}。")
    for line in auto_outputs:
        print(f"[auto] {line}")
    checkpoint_targets = [unit_dir, *_index_target_paths(root), *created_seed_paths]
    if updated_stage_path is not None:
        checkpoint_targets.append(updated_stage_path)
    checkpoint = checkpoint_and_report(
        root,
        trigger="milestone",
        message=f"milestone: intake {args.kind} {record['id']}",
        target_paths=list(dict.fromkeys(checkpoint_targets)),
    )
    for hint in guidance_hints(args.kind, paper_preferences, has_pdf=has_pdf, note_created=note_created):
        print(f"[hint] {hint}")
    print(next_for_agent_intake(root, args.kind, record["id"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
