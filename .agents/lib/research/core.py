from __future__ import annotations

import copy
import hashlib
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .common import (
    ensure_dir,
    file_sha256,
    fetch_url,
    find_project_root,
    html_to_text,
    infer_topics_and_tags,
    is_url,
    load_yaml,
    normalize_ref_key,
    normalize_title,
    normalize_remote_url,
    parse_wikilinks,
    parse_arxiv_id,
    parse_iso_datetime,
    program_root as common_program_root,
    research_root,
    slugify,
    skills_root as common_skills_root,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
    yaml_duplicate_key_issues,
)
from .ids import (
    UNIT_KIND_PREFIXES,
    build_unit_id,
    canonical_unit_id,
    canonical_unit_id_with_hash,
    compact_unit_slug,
    is_canonical_unit_id,
)
from .retrieval import rank_records

from .paths import *
from .records import *
from .prefs import *


STATUS_VALUES = {
    "draft",
    "screened",
    "pending",
    "active",
    "selected",
    "rejected",
    "archived",
    "planned",
    "running",
    "completed",
    "failed",
}


CONFIRMATION_VALUES = {"auto_confirmed", "pending_user_confirmation", "confirmed", "rejected"}


WEB_SNAPSHOT_MAX_CHARS = 120_000


def load_topic_taxonomy(project_root: Path) -> dict[str, Any]:
    ensure_workspace(project_root)
    payload = load_yaml(topic_taxonomy_path(project_root), default={})
    if not isinstance(payload, dict):
        payload = {}
    normalized = _deep_fill_missing(payload, {**DEFAULT_TOPIC_TAXONOMY, "generated_at": utc_now_iso()})
    topics: dict[str, Any] = {}
    for key, item in normalized.get("topics", {}).items():
        topic = slugify(str(item.get("id") or key), max_words=12)
        if not topic:
            continue
        topics[topic] = {
            "id": topic,
            "aliases": _slug_list(item.get("aliases")),
            "tags": _slug_list(item.get("tags")),
            "pools": _slug_list(item.get("pools")),
            "member_ids": _text_list(item.get("member_ids")),
            "count": int(item.get("count") or 0),
            "note": str(item.get("note") or "").strip(),
            "status": str(item.get("status") or "active"),
        }
    tags: dict[str, Any] = {}
    for key, item in normalized.get("tags", {}).items():
        tag = slugify(str(item.get("id") or key), max_words=12)
        if not tag:
            continue
        tags[tag] = {
            "id": tag,
            "aliases": _slug_list(item.get("aliases")),
            "topic_hints": _slug_list(item.get("topic_hints")),
            "pools": _slug_list(item.get("pools")),
            "member_ids": _text_list(item.get("member_ids")),
            "count": int(item.get("count") or 0),
            "note": str(item.get("note") or "").strip(),
            "status": str(item.get("status") or "active"),
        }
    normalized["topics"] = {key: topics[key] for key in sorted(topics)}
    normalized["tags"] = {key: tags[key] for key in sorted(tags)}
    normalized["generated_at"] = utc_now_iso()
    return normalized


def write_topic_taxonomy(project_root: Path, payload: dict[str, Any]) -> Path:
    payload["generated_at"] = utc_now_iso()
    write_yaml_if_changed(topic_taxonomy_path(project_root), payload)
    return topic_taxonomy_path(project_root)


def load_candidate_pools(project_root: Path) -> dict[str, Any]:
    ensure_workspace(project_root)
    payload = load_yaml(candidate_pools_path(project_root), default={})
    if not isinstance(payload, dict):
        payload = {}
    normalized = _deep_fill_missing(payload, {**DEFAULT_CANDIDATE_POOLS, "generated_at": utc_now_iso()})
    pools: dict[str, Any] = {}
    for key, item in normalized.get("pools", {}).items():
        pool = slugify(str(item.get("id") or key), max_words=12)
        if not pool:
            continue
        pools[pool] = {
            "id": pool,
            "summary": str(item.get("summary") or "").strip(),
            "topic_hints": _slug_list(item.get("topic_hints")),
            "tags": _slug_list(item.get("tags")),
            "member_ids": _text_list(item.get("member_ids")),
            "kinds": _slug_list(item.get("kinds")),
            "status": str(item.get("status") or "active"),
        }
    normalized["pools"] = {key: pools[key] for key in sorted(pools)}
    normalized["generated_at"] = utc_now_iso()
    return normalized


def write_candidate_pools(project_root: Path, payload: dict[str, Any]) -> Path:
    payload["generated_at"] = utc_now_iso()
    write_yaml_if_changed(candidate_pools_path(project_root), payload)
    return candidate_pools_path(project_root)


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


def _move_tree_item(src: Path, dst: Path) -> list[tuple[Path, Path]]:
    moved: list[tuple[Path, Path]] = []
    if not src.exists():
        return moved
    if src.is_dir():
        ensure_dir(dst)
        for child in sorted(src.iterdir()):
            moved.extend(_move_tree_item(child, dst / child.name))
        if src.exists():
            try:
                src.rmdir()
            except OSError:
                pass
        return moved
    if dst.exists():
        return moved
    ensure_dir(dst.parent)
    shutil.move(str(src), str(dst))
    moved.append((src, dst))
    return moved


def _copy_into_raw(backup: Path, target: Path) -> bool:
    if target.exists():
        return True
    ensure_dir(target.parent)
    if backup.is_dir():
        shutil.copytree(backup, target)
        return True
    shutil.copy2(backup, target)
    return True


def prune_nested_repo_metadata(project_root: Path) -> list[str]:
    removed: list[str] = []
    repo_sources_root = units_root(project_root) / "repos"
    if not repo_sources_root.exists():
        return removed
    for path in repo_sources_root.glob("*/source/*/.git"):
        if not path.exists():
            continue
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        removed.append(rel(project_root, path))
    return removed


def _rewrite_storage_text(text: str, project_root: Path) -> str:
    old_abs_raw = (project_root / "raw").resolve().as_posix()
    new_abs_raw = raw_storage_root(project_root).resolve().as_posix()
    old_abs_output = (project_root / "output").resolve().as_posix()
    new_abs_output = output_storage_root(project_root).resolve().as_posix()
    updated = text.replace(old_abs_raw, new_abs_raw).replace(old_abs_output, new_abs_output)
    updated = re.sub(r"(?<!kb/)raw/", "kb/raw/", updated)
    updated = re.sub(r"(?<!kb/)output/", "kb/output/", updated)
    return updated


def sync_storage_layout(project_root: Path) -> dict[str, Any]:
    ensure_workspace(project_root)
    moved_paths: list[tuple[Path, Path]] = []
    for name, destination_root in (("raw", raw_storage_root(project_root)), ("output", output_storage_root(project_root))):
        source_root = project_root / name
        if not source_root.exists():
            continue
        ensure_dir(destination_root)
        for child in sorted(source_root.iterdir()):
            moved_paths.extend(_move_tree_item(child, destination_root / child.name))
        try:
            source_root.rmdir()
        except OSError:
            pass

    updated_records: list[str] = []
    hydrated_paths: list[str] = []
    for record in iter_records(project_root):
        source = record.get("source", {})
        if not isinstance(source, dict):
            continue
        original_uri = str(source.get("original_uri") or "").strip()
        if not original_uri or is_url(original_uri):
            continue
        old_path, remapped_path = _legacy_storage_map(project_root, original_uri)
        if remapped_path is None:
            continue
        backup_candidates = []
        for rel_backup in source.get("backup_paths", []):
            backup = project_root / str(rel_backup)
            if backup.exists():
                backup_candidates.append(backup)
        if not remapped_path.exists() and backup_candidates:
            _copy_into_raw(backup_candidates[0], remapped_path)
            hydrated_paths.append(rel(project_root, remapped_path))
        normalized_uri = remapped_path.resolve().as_posix() if remapped_path.exists() else remapped_path.as_posix()
        if normalized_uri != original_uri:
            source["original_uri"] = normalized_uri
            record["source"] = source
            write_record(project_root, record)
            updated_records.append(str(record.get("id") or ""))

    rewritten_files: list[str] = []
    for root in [kb_root(project_root), project_root / ".agents", project_root / "AGENTS.md"]:
        if isinstance(root, Path) and root.is_file():
            paths = [root]
        else:
            paths = list(root.rglob("*")) if isinstance(root, Path) and root.exists() else []
        for path in paths:
            if not path.is_file():
                continue
            if path.suffix.lower() not in TEXT_REWRITE_SUFFIXES and path.name not in {"AGENTS.md", "SKILL.md"}:
                continue
            if ".git" in path.parts or ("source" in path.parts and path.suffix.lower() not in {".md", ".markdown", ".txt"}):
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            updated = _rewrite_storage_text(text, project_root)
            if updated != text:
                write_text_if_changed(path, updated)
                rewritten_files.append(rel(project_root, path))

    removed_nested_git = prune_nested_repo_metadata(project_root)

    return {
        "moved_paths": [(src.as_posix(), dst.as_posix()) for src, dst in moved_paths],
        "updated_records": updated_records,
        "hydrated_paths": hydrated_paths,
        "rewritten_files": rewritten_files,
        "removed_nested_git": removed_nested_git,
    }


def apply_record_governance(
    project_root: Path,
    record: dict[str, Any],
    *,
    explicit_topics: list[str] | None = None,
    explicit_tags: list[str] | None = None,
    explicit_pools: list[str] | None = None,
    infer_missing: bool = True,
    source_label: str = "",
) -> dict[str, Any]:
    normalized = normalize_record_schema(record)
    signal_text = " ".join(
        [
            str(normalized.get("title") or ""),
            str(normalized.get("summary") or ""),
            str(normalized.get("source", {}).get("original_uri") or ""),
            str(normalized.get("payload", {}).get("basic_info", {}).get("title") or ""),
            str(normalized.get("payload", {}).get("basic_info", {}).get("name") or ""),
        ]
    ).strip()
    inferred_topics, inferred_tags = ([], [])
    if infer_missing and signal_text:
        inferred_topics, inferred_tags = infer_topics_and_tags(signal_text, project_root=project_root)
    topic_sources = list(normalized.get("taxonomy", {}).get("topic_sources", []))
    tag_sources = list(normalized.get("taxonomy", {}).get("tag_sources", []))
    pool_sources = list(normalized.get("taxonomy", {}).get("pool_sources", []))
    topics = set(normalized.get("topics", []))
    tags = set(normalized.get("tags", []))
    pools = set(normalized.get("candidate_pools", []))
    for item in explicit_topics or []:
        topic = slugify(str(item), max_words=12)
        if topic:
            topics.add(topic)
    for item in explicit_tags or []:
        tag = slugify(str(item), max_words=12)
        if tag:
            tags.add(tag)
    for item in explicit_pools or []:
        pool = slugify(str(item), max_words=12)
        if pool:
            pools.add(pool)
    for item in inferred_topics:
        topic = slugify(str(item), max_words=12)
        if topic:
            topics.add(topic)
    for item in inferred_tags:
        tag = slugify(str(item), max_words=12)
        if tag:
            tags.add(tag)
    if explicit_topics or inferred_topics:
        topic_sources.append(source_label or ("manual" if explicit_topics else "inferred"))
    if explicit_tags or inferred_tags:
        tag_sources.append(source_label or ("manual" if explicit_tags else "inferred"))
    if explicit_pools:
        pool_sources.append(source_label or "manual")
    normalized["topics"] = sorted(topics)
    normalized["tags"] = sorted(tags)
    normalized["candidate_pools"] = sorted(pools)
    taxonomy = normalized.get("taxonomy", {})
    primary_topic = normalized["topics"][0] if normalized["topics"] else ""
    taxonomy["primary_topic"] = primary_topic
    taxonomy["secondary_topics"] = [topic for topic in normalized["topics"] if topic != primary_topic]
    taxonomy["canonical_tags"] = list(normalized["tags"])
    taxonomy["topic_sources"] = sorted(set(_text_list(topic_sources)))
    taxonomy["tag_sources"] = sorted(set(_text_list(tag_sources)))
    taxonomy["pool_sources"] = sorted(set(_text_list(pool_sources)))
    normalized["taxonomy"] = taxonomy
    return normalized


GATED_CONFIRMATION_VALUES = {"pending_user_confirmation", "rejected"}


AI_SIGNER_NAMES = {"ai", "assistant", "codex", "chatgpt", "gpt", "openai"}


def is_ai_signer(actor: str) -> bool:
    return str(actor or "").strip().lower() in AI_SIGNER_NAMES


def default_confirmed_by(project_root: Path | None = None) -> str:
    if project_root is None:
        return ""
    preferences = load_runtime_preferences(project_root)
    identity = preferences.get("identity", {})
    if not isinstance(identity, dict):
        return ""
    return str(identity.get("default_confirmed_by") or "").strip()


def require_confirmation_provenance(
    *,
    confirmed_by: str,
    evidence: list[str] | str,
    project_root: Path | None = None,
) -> tuple[str, list[str]]:
    actor = str(confirmed_by or "").strip()
    if not actor:
        actor = default_confirmed_by(project_root)
    evidence_items = _text_list([evidence] if isinstance(evidence, str) else evidence)
    if not actor:
        raise SystemExit("Human confirmation requires --confirmed-by or identity.default_confirmed_by.")
    if not evidence_items:
        raise SystemExit("Human confirmation requires at least one --evidence.")
    return actor, evidence_items


def apply_confirmation(
    record: dict[str, Any],
    *,
    confirmed_by: str,
    evidence: list[str] | str,
    method: str = "cli",
    project_root: Path | None = None,
) -> dict[str, Any]:
    actor, evidence_items = require_confirmation_provenance(
        confirmed_by=confirmed_by,
        evidence=evidence,
        project_root=project_root,
    )
    now = utc_now_iso()
    record["confirmation_status"] = "confirmed"
    record["needs_human_confirmation"] = False
    record["last_human_confirmed_at"] = now
    record["confirmation"] = {
        "by": actor,
        "at": now,
        "evidence": evidence_items,
        "method": str(method or "cli").strip() or "cli",
    }
    return record


CONFIRM_UNIT_STATUS_BY_KIND = {
    "paper": "active",
    "repo": "active",
    "blog": "active",
}


CONFIRM_UNIT_SUMMARY_BY_KIND = {
    "paper": "Paper analysis confirmed by user.",
    "repo": "Repo analysis confirmed by user.",
    "blog": "Blog analysis confirmed by user.",
    "idea": "Idea content confirmed by user.",
    "experiment": "Experiment findings confirmed by user.",
}


def confirm_unit(
    record: dict[str, Any],
    kind: str | None = None,
    *,
    confirmed_by: str,
    evidence: list[str] | str,
    method: str = "cli",
    project_root: Path | None = None,
) -> dict[str, Any]:
    unit_kind = str(kind or record.get("kind") or "")
    if unit_kind not in UNIT_KIND_DIRS:
        raise SystemExit(f"Unsupported unit kind: {unit_kind}")
    record = apply_confirmation(
        record,
        confirmed_by=confirmed_by,
        evidence=evidence,
        method=method,
        project_root=project_root,
    )
    if unit_kind in CONFIRM_UNIT_STATUS_BY_KIND:
        record["status"] = CONFIRM_UNIT_STATUS_BY_KIND[unit_kind]
    elif unit_kind == "experiment" and str(record.get("status") or "") == "running":
        record["status"] = "completed"
    record["information_types"] = ["fact"]
    append_history(
        record,
        action=f"{unit_kind}-confirmed",
        summary=CONFIRM_UNIT_SUMMARY_BY_KIND.get(unit_kind, f"{unit_kind} record confirmed by user."),
        information_types=["fact"],
    )
    return record


def validate_write(record: dict[str, Any], *, strict: bool | None = None) -> list[str]:
    """Confirmation gate contract check (see lib/research/SCHEMAS.md#confirmation-gate).

    AI-derived records (information_types ∩ {inference, evaluation, user_opinion}
    or source.kind == "ai") must carry confirmation_status ∈
    {pending_user_confirmation, rejected} and needs_human_confirmation = true.

    Returns the list of contract violations (empty when clean). In strict mode
    raises SystemExit; otherwise emits a stderr warning. Default is non-strict;
    set RESEARCH_VALIDATE_STRICT=1 to opt into strict.
    """
    if strict is None:
        strict = os.getenv("RESEARCH_VALIDATE_STRICT") == "1"
    needs_gate, ai_info_types, source_is_ai = _record_needs_gate(record)
    if not needs_gate:
        return []
    violations: list[str] = []
    confirmation = str(record.get("confirmation_status") or "")
    if confirmation not in GATED_CONFIRMATION_VALUES:
        reason_parts = []
        if ai_info_types:
            reason_parts.append(f"information_types={sorted(ai_info_types)}")
        if source_is_ai:
            reason_parts.append("source.kind=ai")
        violations.append(
            f"record {record.get('id')!r}: confirmation_status={confirmation!r} "
            f"too strong for AI-derived record ({', '.join(reason_parts)}); "
            f"expected pending_user_confirmation or rejected."
        )
    if not record.get("needs_human_confirmation"):
        violations.append(
            f"record {record.get('id')!r}: needs_human_confirmation must be true "
            f"for AI-derived record."
        )
    if violations:
        msg = "validate_write contract violations:\n  - " + "\n  - ".join(violations)
        if strict:
            raise SystemExit(msg)
        sys.stderr.write(f"[research/core.validate_write] WARN: {msg}\n")
    return violations


def write_record(project_root: Path, record: dict[str, Any]) -> Path:
    normalized = normalize_record_schema(record)
    validate_write(normalized)
    root = unit_root(project_root, str(normalized["kind"]), str(normalized["id"]))
    ensure_dir(root)
    path = root / "record.yaml"
    normalized["updated_at"] = utc_now_iso()
    write_yaml_if_changed(path, normalized)
    return path


def _unit_id_slug_ref_key(unit_id: str) -> str:
    parts = unit_id.split("-")
    if len(parts) < 3 or parts[0] not in set(UNIT_KIND_PREFIXES.values()):
        return ""
    if not re.fullmatch(r"[0-9a-f]{6,40}", parts[-1]):
        return ""
    return normalize_ref_key("-".join(parts[1:-1]))


def _record_wikilink_ref_keys(record: dict[str, Any]) -> set[str]:
    keys: set[str] = set()
    unit_id = str(record.get("id") or "")
    for value in [unit_id, _unit_id_slug_ref_key(unit_id), str(record.get("title") or "")]:
        key = normalize_ref_key(value)
        if key:
            keys.add(key)
    for legacy_id in _unique_text_list(record.get("legacy_ids")):
        for value in [legacy_id, _unit_id_slug_ref_key(legacy_id)]:
            key = normalize_ref_key(value)
            if key:
                keys.add(key)
    return keys


def _unit_markdown_paths(project_root: Path, record: dict[str, Any]) -> list[Path]:
    kind = str(record.get("kind") or "")
    unit_id = str(record.get("id") or "")
    if kind not in UNIT_KIND_DIRS or not unit_id:
        return []
    root = unit_root(project_root, kind, unit_id)
    if not root.exists():
        return []
    paths = sorted({*root.rglob("*.md"), *root.rglob("*.markdown")})
    return [path for path in paths if "source" not in path.relative_to(root).parts]


def _wikilink_target_exists(project_root: Path, target: str, ref_keys: set[str]) -> bool:
    candidates = [target.strip(), normalize_ref_key(target)]
    for candidate in candidates:
        if not candidate:
            continue
        try:
            locate_record(project_root, candidate, fuzzy=False)
            return True
        except SystemExit:
            pass
    return normalize_ref_key(target) in ref_keys


def refresh_record_schemas(project_root: Path, *, unit_ids: list[str] | None = None, kind: str | None = None) -> list[Path]:
    ensure_workspace(project_root)
    paths: list[Path] = []
    if unit_ids:
        for unit_id in unit_ids:
            record, _ = locate_record(project_root, unit_id)
            paths.append(write_record(project_root, record))
        return paths
    for record in iter_records(project_root, kind=kind):
        paths.append(write_record(project_root, record))
    return paths


def _has_declared_members(item: dict[str, Any]) -> bool:
    return bool(_text_list(item.get("member_ids"))) or int(item.get("count") or 0) > 0


def _preserve_empty_governance_seeds(taxonomy: dict[str, Any], pools: dict[str, Any], existing_taxonomy: dict[str, Any], existing_pools: dict[str, Any]) -> None:
    for topic, item in existing_taxonomy.get("topics", {}).items():
        if topic in taxonomy["topics"] or _has_declared_members(item):
            continue
        taxonomy["topics"][topic] = {
            "id": topic,
            "aliases": _slug_list(item.get("aliases")),
            "tags": _slug_list(item.get("tags")),
            "pools": _slug_list(item.get("pools")),
            "member_ids": [],
            "count": 0,
            "note": str(item.get("note") or "").strip(),
            "status": str(item.get("status") or "active"),
        }
    for tag, item in existing_taxonomy.get("tags", {}).items():
        if tag in taxonomy["tags"] or _has_declared_members(item):
            continue
        taxonomy["tags"][tag] = {
            "id": tag,
            "aliases": _slug_list(item.get("aliases")),
            "topic_hints": _slug_list(item.get("topic_hints")),
            "pools": _slug_list(item.get("pools")),
            "member_ids": [],
            "count": 0,
            "note": str(item.get("note") or "").strip(),
            "status": str(item.get("status") or "active"),
        }
    for pool, item in existing_pools.get("pools", {}).items():
        if pool in pools["pools"] or _has_declared_members(item):
            continue
        pools["pools"][pool] = {
            "id": pool,
            "summary": str(item.get("summary") or "").strip(),
            "topic_hints": _slug_list(item.get("topic_hints")),
            "tags": _slug_list(item.get("tags")),
            "member_ids": [],
            "kinds": [],
            "status": str(item.get("status") or "active"),
        }


def rebuild_governance_catalogs(project_root: Path, *, records: list[dict[str, Any]] | None = None) -> tuple[Path, Path]:
    ensure_workspace(project_root)
    records = records if records is not None else iter_records(project_root)
    existing_taxonomy = load_topic_taxonomy(project_root)
    existing_pools = load_candidate_pools(project_root)
    taxonomy = {**existing_taxonomy, "topics": {}, "tags": {}}
    pools = {**existing_pools, "pools": {}}

    for record in records:
        unit_id = str(record.get("id") or "")
        record_tags = _slug_list(record.get("tags"))
        record_topics = _slug_list(record.get("topics"))
        record_pools = _slug_list(record.get("candidate_pools"))
        for topic in record_topics:
            base = existing_taxonomy.get("topics", {}).get(topic, {})
            item = taxonomy["topics"].setdefault(
                topic,
                {
                    "id": topic,
                    "aliases": _slug_list(base.get("aliases")),
                    "tags": [],
                    "pools": [],
                    "member_ids": [],
                    "count": 0,
                    "note": str(base.get("note") or "").strip(),
                    "status": str(base.get("status") or "active"),
                },
            )
            item["count"] += 1
            item["member_ids"] = sorted(set(item["member_ids"]) | {unit_id})
            item["tags"] = sorted(set(item["tags"]) | set(record_tags))
            item["pools"] = sorted(set(item["pools"]) | set(record_pools))
        for tag in record_tags:
            base = existing_taxonomy.get("tags", {}).get(tag, {})
            item = taxonomy["tags"].setdefault(
                tag,
                {
                    "id": tag,
                    "aliases": _slug_list(base.get("aliases")),
                    "topic_hints": [],
                    "pools": [],
                    "member_ids": [],
                    "count": 0,
                    "note": str(base.get("note") or "").strip(),
                    "status": str(base.get("status") or "active"),
                },
            )
            item["count"] += 1
            item["member_ids"] = sorted(set(item["member_ids"]) | {unit_id})
            item["topic_hints"] = sorted(set(item["topic_hints"]) | set(record_topics))
            item["pools"] = sorted(set(item["pools"]) | set(record_pools))
        for pool in record_pools:
            base = existing_pools.get("pools", {}).get(pool, {})
            item = pools["pools"].setdefault(
                pool,
                {
                    "id": pool,
                    "summary": str(base.get("summary") or "").strip(),
                    "topic_hints": [],
                    "tags": [],
                    "member_ids": [],
                    "kinds": [],
                    "status": str(base.get("status") or "active"),
                },
            )
            item["member_ids"] = sorted(set(item["member_ids"]) | {unit_id})
            item["topic_hints"] = sorted(set(item["topic_hints"]) | set(record_topics))
            item["tags"] = sorted(set(item["tags"]) | set(record_tags))
            item["kinds"] = sorted(set(item["kinds"]) | {str(record.get("kind") or "")})

    _preserve_empty_governance_seeds(taxonomy, pools, existing_taxonomy, existing_pools)
    taxonomy["topics"] = {key: taxonomy["topics"][key] for key in sorted(taxonomy["topics"])}
    taxonomy["tags"] = {key: taxonomy["tags"][key] for key in sorted(taxonomy["tags"])}
    pools["pools"] = {key: pools["pools"][key] for key in sorted(pools["pools"])}

    taxonomy_path = write_topic_taxonomy(project_root, taxonomy)
    pools_path = write_candidate_pools(project_root, pools)
    return taxonomy_path, pools_path


def build_index(project_root: Path) -> tuple[Path, Path]:
    ensure_workspace(project_root)
    records = iter_records(project_root)
    rebuild_governance_catalogs(project_root, records=records)
    items = []
    for record in sorted(records, key=lambda x: (str(x.get("kind")), str(x.get("title")))):
        items.append(
            {
                "id": record.get("id"),
                "kind": record.get("kind"),
                "title": record.get("title"),
                "status": record.get("status"),
                "maturity": record.get("maturity"),
                "confirmation_status": record.get("confirmation_status"),
                "tags": record.get("tags", []),
                "topics": record.get("topics", []),
                "candidate_pools": record.get("candidate_pools", []),
                "summary": record_summary(record),
                "path": rel(project_root, record_path(project_root, str(record.get("kind")), str(record.get("id")))),
            }
        )
    yaml_path = kb_root(project_root) / "index.yaml"
    md_path = kb_root(project_root) / "index.md"
    write_yaml_if_changed(
        yaml_path,
        {
            "id": "kb-index",
            "generated_at": utc_now_iso(),
            "items": items,
            "counts": {kind: len([item for item in items if item["kind"] == kind]) for kind in UNIT_KIND_DIRS},
        },
    )
    lines = ["# Research KB Index", ""]
    for kind in UNIT_KIND_DIRS:
        lines.extend([f"## {kind.title()}s", ""])
        kind_rows = [item for item in items if item["kind"] == kind]
        if not kind_rows:
            lines.append("- 暂无条目")
        for item in kind_rows:
            pools = ", ".join(item["candidate_pools"]) if item["candidate_pools"] else "-"
            lines.append(
                f"- `{item['id']}` · {item['title']} · status={item['status']} · maturity={item['maturity']} · confirm={item['confirmation_status']} · pools={pools}"
            )
        lines.append("")
    write_text_if_changed(md_path, "\n".join(lines).strip() + "\n")
    return yaml_path, md_path


def lint_workspace_integrity(project_root: Path) -> list[str]:
    issues: list[str] = []
    yaml_paths: list[Path] = []
    records = iter_records(project_root)

    for record in records:
        yaml_paths.append(record_path(project_root, str(record.get("kind") or ""), str(record.get("id") or "")))

    for base in [kb_root(project_root) / "programs", config_root(project_root), synthesis_root(project_root)]:
        if not base.exists():
            continue
        yaml_paths.extend(sorted(base.rglob("*.yaml")))
        yaml_paths.extend(sorted(base.rglob("*.yml")))

    seen_paths: set[Path] = set()
    for path in yaml_paths:
        if path in seen_paths or not path.exists():
            continue
        seen_paths.add(path)
        if "source" in path.parts or path.parts[-3:-1] == ("user", "kb"):
            continue
        for issue in yaml_duplicate_key_issues(path):
            prefix = f"{project_root.as_posix()}/"
            issues.append(issue.replace(prefix, ""))

    wikilink_ref_keys: set[str] = set()
    for record in records:
        wikilink_ref_keys.update(_record_wikilink_ref_keys(record))
    for record in records:
        for path in _unit_markdown_paths(project_root, record):
            try:
                markdown = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            for target in parse_wikilinks(markdown):
                if not _wikilink_target_exists(project_root, target, wikilink_ref_keys):
                    issues.append(f"{rel(project_root, path)}: broken wikilink `{target}`")

    programs_root = kb_root(project_root) / "programs"
    if not programs_root.exists():
        return issues

    for state_file in sorted(programs_root.glob("*/state.yaml")):
        program_id = state_file.parent.name
        state_payload = load_yaml(state_file, default={})
        if not isinstance(state_payload, dict):
            issues.append(f"{rel(project_root, state_file)}: invalid YAML payload")
            continue
        active_unit_ids = _text_list(state_payload.get("active_unit_ids"))
        for unit_id in active_unit_ids:
            try:
                record, _ = locate_record(project_root, unit_id, fuzzy=False)
            except SystemExit:
                issues.append(f"{rel(project_root, state_file)}: active_unit_id `{unit_id}` not found")
                continue
            if program_id not in _slug_list(record.get("program_ids")):
                issues.append(f"{rel(project_root, state_file)}: `{unit_id}` missing reverse program_ids link to `{program_id}`")

    for record in records:
        unit_id = str(record.get("id") or "")
        for program_id in _slug_list(record.get("program_ids")):
            state_file = common_program_root(project_root, program_id) / "state.yaml"
            if not state_file.exists():
                issues.append(f"{unit_id}: references missing program `{program_id}`")
                continue
            state_payload = load_yaml(state_file, default={})
            if not isinstance(state_payload, dict):
                issues.append(f"{unit_id}: referenced program `{program_id}` has invalid state payload")
                continue
            if unit_id not in _text_list(state_payload.get("active_unit_ids")):
                issues.append(f"{unit_id}: program `{program_id}` missing reverse active_unit_ids link")

    return issues


def lint_records(project_root: Path) -> tuple[str, list[str]]:
    ensure_workspace(project_root)
    issues: list[str] = []
    for raw_record in iter_records(project_root):
        try:
            record = normalize_record_schema(raw_record)
        except SystemExit as exc:
            issues.append(str(exc))
            continue
        unit_id = str(record.get("id") or "")
        kind = str(record.get("kind") or "")
        if not unit_id:
            issues.append("record without id")
        if kind not in UNIT_KIND_DIRS:
            issues.append(f"{unit_id}: invalid kind `{kind}`")
        if kind in UNIT_KIND_DIRS and not is_canonical_unit_id(kind, unit_id):
            issues.append(f"{unit_id}: non-canonical id, run `kb.py compact-ids --apply`")
        if str(record.get("status") or "") not in STATUS_VALUES:
            issues.append(f"{unit_id}: invalid status `{record.get('status')}`")
        if str(record.get("maturity") or "") not in MATURITY_LEVELS:
            issues.append(f"{unit_id}: invalid maturity `{record.get('maturity')}`")
        if str(record.get("confirmation_status") or "") not in CONFIRMATION_VALUES:
            issues.append(f"{unit_id}: invalid confirmation_status `{record.get('confirmation_status')}`")
        info_types = record.get("information_types", [])
        if not isinstance(info_types, list) or not set(info_types).issubset(INFORMATION_TYPES):
            issues.append(f"{unit_id}: invalid information_types")
        if not isinstance(record.get("payload"), dict) or not record.get("payload"):
            issues.append(f"{unit_id}: missing payload")
        if not isinstance(record.get("taxonomy"), dict):
            issues.append(f"{unit_id}: missing taxonomy block")
        if not isinstance(record.get("candidate_pools"), list):
            issues.append(f"{unit_id}: invalid candidate_pools")
        for violation in validate_write(record):
            issues.append(violation)
    issues.extend(lint_workspace_integrity(project_root))
    return ("PASS" if not issues else "FAIL"), issues


def search_records(
    project_root: Path,
    query: str,
    *,
    kind: str | None = None,
    pool: str | None = None,
    confirmation_status: str | None = None,
) -> list[dict[str, Any]]:
    normalized_pool = slugify(str(pool), max_words=12) if pool else ""
    filtered: list[dict[str, Any]] = []
    for record in iter_records(project_root, kind=kind):
        if normalized_pool and normalized_pool not in record.get("candidate_pools", []):
            continue
        if confirmation_status and str(record.get("confirmation_status") or "") != confirmation_status:
            continue
        filtered.append(record)
    return rank_records(filtered, query, markdown_paths_for=lambda record: _unit_markdown_paths(project_root, record))


def govern_records(
    project_root: Path,
    *,
    unit_ids: list[str] | None = None,
    kind: str | None = None,
    explicit_topics: list[str] | None = None,
    explicit_tags: list[str] | None = None,
    explicit_pools: list[str] | None = None,
    infer_missing: bool = True,
    source_label: str = "",
) -> list[Path]:
    ensure_workspace(project_root)
    written: list[Path] = []
    if unit_ids:
        for unit_id in unit_ids:
            record, _ = locate_record(project_root, unit_id)
            updated = apply_record_governance(
                project_root,
                record,
                explicit_topics=explicit_topics,
                explicit_tags=explicit_tags,
                explicit_pools=explicit_pools,
                infer_missing=infer_missing,
                source_label=source_label,
            )
            append_history(updated, action="governed", summary="Updated topics / tags / candidate pools.")
            written.append(write_record(project_root, updated))
        return written
    for record in iter_records(project_root, kind=kind):
        updated = apply_record_governance(
            project_root,
            record,
            explicit_topics=explicit_topics,
            explicit_tags=explicit_tags,
            explicit_pools=explicit_pools,
            infer_missing=infer_missing,
            source_label=source_label,
        )
        append_history(updated, action="governed", summary="Updated topics / tags / candidate pools.")
        written.append(write_record(project_root, updated))
    return written


def build_search_stage_id(kind: str, query: str) -> str:
    base = slugify(query, max_words=8) or kind
    short_hash = hashlib.sha1(f"{kind}:{query}".encode("utf-8")).hexdigest()[:8]
    return f"{kind}-search-{base}-{short_hash}"


def load_search_stage(project_root: Path, stage_id: str) -> dict[str, Any]:
    payload = load_yaml(search_stage_path(project_root, stage_id), default={})
    if not isinstance(payload, dict) or not payload.get("id"):
        raise SystemExit(f"Search stage not found: {stage_id}")
    return payload


def stage_search_results(
    project_root: Path,
    *,
    kind: str,
    query: str,
    candidates: list[dict[str, Any]],
    stage_id: str = "",
    note: str = "",
) -> Path:
    ensure_workspace(project_root)
    current_stage_id = stage_id or build_search_stage_id(kind, query)
    path = search_stage_path(project_root, current_stage_id)
    existing = load_yaml(path, default={})
    if not isinstance(existing, dict):
        existing = {}
    payload = _deep_fill_missing(
        existing,
        {
            "id": current_stage_id,
            "kind": "source-search-stage",
            "status": "staged",
            "source_kind": kind,
            "query": query,
            "note": note,
            "generated_by": "source-intake",
            "generated_at": utc_now_iso(),
            "candidates": [],
            "history": [],
        },
    )
    known_urls = {str(item.get("url") or "") for item in payload.get("candidates", []) if isinstance(item, dict)}
    query_topics, query_tags = infer_topics_and_tags(query, project_root=project_root)
    for index, candidate in enumerate(candidates, start=1):
        url = str(candidate.get("url") or "").strip()
        title = str(candidate.get("title") or "").strip()
        if not url or url in known_urls:
            continue
        candidate_id = str(candidate.get("candidate_id") or "").strip()
        if not candidate_id:
            seed = title or url or f"{current_stage_id}:{index}"
            candidate_id = f"{current_stage_id}-{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:6]}"
        payload["candidates"].append(
            {
                "candidate_id": candidate_id,
                "title": title,
                "url": url,
                "status": "staged",
                "note": str(candidate.get("note") or "").strip(),
                "topics": _slug_list(candidate.get("topics")) or _slug_list(query_topics),
                "tags": _slug_list(candidate.get("tags")) or _slug_list(query_tags),
                "pool_hints": _slug_list(candidate.get("pool_hints")),
            }
        )
        known_urls.add(url)
    payload["history"].append({"timestamp": utc_now_iso(), "action": "staged", "summary": f"Captured {len(candidates)} candidates."})
    payload["generated_at"] = utc_now_iso()
    write_yaml_if_changed(path, payload)
    return path


def resolve_search_candidate(project_root: Path, stage_id: str, candidate_id: str) -> dict[str, Any]:
    payload = load_search_stage(project_root, stage_id)
    for candidate in payload.get("candidates", []):
        if str(candidate.get("candidate_id") or "") == candidate_id:
            return dict(candidate)
    raise SystemExit(f"Candidate `{candidate_id}` not found in stage `{stage_id}`")


def mark_search_candidate(
    project_root: Path,
    stage_id: str,
    candidate_id: str,
    *,
    status: str,
    record_id: str = "",
) -> Path:
    payload = load_search_stage(project_root, stage_id)
    found = False
    for candidate in payload.get("candidates", []):
        if str(candidate.get("candidate_id") or "") != candidate_id:
            continue
        candidate["status"] = status
        if record_id:
            candidate["record_id"] = record_id
        found = True
        break
    if not found:
        raise SystemExit(f"Candidate `{candidate_id}` not found in stage `{stage_id}`")
    payload.setdefault("history", []).append(
        {
            "timestamp": utc_now_iso(),
            "action": "candidate-updated",
            "summary": f"{candidate_id} -> {status}",
        }
    )
    path = search_stage_path(project_root, stage_id)
    write_yaml_if_changed(path, payload)
    return path


def _copy_dir(src: Path, dst: Path) -> None:
    if dst.exists():
        return
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(".git", ".gitmodules"))


def _is_html_response(content_type: str, text: str) -> bool:
    normalized = content_type.lower().strip()
    if normalized in {"text/html", "application/xhtml+xml"} or normalized.endswith("+html"):
        return True
    prefix = text[:1000].lower()
    return "<html" in prefix or "<!doctype html" in prefix


def _truncate_snapshot_text(text: str) -> str:
    if len(text) <= WEB_SNAPSHOT_MAX_CHARS:
        return text
    trimmed = text[:WEB_SNAPSHOT_MAX_CHARS].rsplit(" ", 1)[0].rstrip()
    return (trimmed or text[:WEB_SNAPSHOT_MAX_CHARS]).rstrip() + "\n\n[truncated]\n"


def backup_source(project_root: Path, kind: str, unit_id: str, source: str) -> dict[str, Any]:
    root = unit_root(project_root, kind, unit_id) / "source"
    ensure_dir(root)
    if is_url(source):
        original_uri = normalize_remote_url(source)
        txt = root / "source-url.txt"
        write_text_if_changed(txt, source.strip() + "\n")
        backup_paths = [rel(project_root, txt)]
        file_hash = ""
        backup_warning = ""
        try:
            content, content_type = fetch_url(source, timeout=15)
            if isinstance(content, str) and _is_html_response(content_type, content):
                body = _truncate_snapshot_text(html_to_text(content))
                if body:
                    snapshot_text = f"# Source Snapshot\n\nSource: {original_uri}\n\n{body.rstrip()}\n"
                    snapshot = root / "snapshot.md"
                    write_text_if_changed(snapshot, snapshot_text)
                    backup_paths.append(rel(project_root, snapshot))
                    file_hash = hashlib.sha256(snapshot_text.encode("utf-8")).hexdigest()
                else:
                    backup_warning = "URL source produced an empty text snapshot."
            else:
                content_label = content_type or type(content).__name__
                backup_warning = f"URL source was not archived as a text snapshot: content_type={content_label}."
        except Exception as exc:  # noqa: BLE001
            backup_warning = f"URL source could not be archived as a text snapshot: {exc}"
        payload = {"original_uri": original_uri, "backup_paths": backup_paths, "backup_kind": "url", "file_hash": file_hash}
        if backup_warning:
            payload["backup_warning"] = backup_warning
            sys.stderr.write(f"[research/core.backup_source] WARN: {backup_warning} source={original_uri}\n")
        return payload

    normalized_source = normalize_storage_reference(project_root, source)
    resolved_source = resolve_local_reference(project_root, normalized_source)
    src = resolved_source or Path(normalized_source).expanduser().resolve()
    if not src.exists():
        raise SystemExit(f"Source not found: {source}")
    dst = root / src.name
    if src.is_dir():
        _copy_dir(src, dst)
        file_hash = ""
        backup_kind = "directory"
    else:
        if not dst.exists():
            shutil.copy2(src, dst)
        file_hash = file_sha256(src)
        backup_kind = "file"
    return {
        "original_uri": src.as_posix(),
        "backup_paths": [rel(project_root, dst)],
        "backup_kind": backup_kind,
        "file_hash": file_hash,
    }


def detect_duplicate(project_root: Path, kind: str, source: str, *, title: str = "") -> dict[str, Any] | None:
    normalized = normalize_remote_url(source) if is_url(source) else normalize_storage_reference(project_root, source)
    file_hash = ""
    candidate_arxiv_id = parse_arxiv_id(source)
    candidate_title = normalize_title(title) if title else ""
    if not is_url(source):
        path = resolve_local_reference(project_root, normalized) or Path(normalized).expanduser().resolve()
        if path.exists() and path.is_file():
            file_hash = file_sha256(path)
            normalized = path.as_posix()
            if not candidate_arxiv_id:
                candidate_arxiv_id = parse_arxiv_id(path.name)
        elif path.exists():
            normalized = path.as_posix()
    for record in iter_records(project_root, kind=kind):
        record_source = record.get("source", {})
        record_original_uri = str(record_source.get("original_uri") or "")
        record_normalized = normalize_remote_url(record_original_uri) if is_url(record_original_uri) else record_original_uri
        if normalized and normalized == record_normalized:
            return record
        if file_hash and file_hash == str(record_source.get("file_hash") or ""):
            return record
        if kind == "paper":
            record_arxiv_id = parse_arxiv_id(
                "\n".join(
                    [
                        record_original_uri,
                        str(record.get("title") or ""),
                        str(record.get("payload", {}).get("basic_info", {}).get("source_url") or ""),
                    ]
                )
            )
            if candidate_arxiv_id and record_arxiv_id and candidate_arxiv_id == record_arxiv_id:
                return record
            if candidate_title and candidate_title == normalize_title(str(record.get("title") or "")):
                return record
    return None


def _sorted_id_pairs(mapping: dict[str, str]) -> list[tuple[str, str]]:
    return sorted(mapping.items(), key=lambda item: len(item[0]), reverse=True)


def _replace_ids_in_text(text: str, mapping: dict[str, str]) -> str:
    updated = text
    for old_id, new_id in _sorted_id_pairs(mapping):
        updated = updated.replace(old_id, new_id)
    return updated


def _replace_ids_in_object(value: Any, mapping: dict[str, str]) -> Any:
    if isinstance(value, dict):
        return {key: _replace_ids_in_object(item, mapping) for key, item in value.items()}
    if isinstance(value, list):
        return [_replace_ids_in_object(item, mapping) for item in value]
    if isinstance(value, str):
        return _replace_ids_in_text(value, mapping)
    return value


def _text_rewrite_allowed(project_root: Path, path: Path) -> bool:
    if path.name == "record.yaml":
        return False
    if path.suffix.lower() not in TEXT_REWRITE_SUFFIXES:
        return False
    try:
        rel_path = path.resolve().relative_to(kb_root(project_root).resolve())
    except ValueError:
        return False
    if rel_path.parts[:2] == ("user", "kb"):
        return False
    if "source" in rel_path.parts:
        return False
    return True


def _rename_paths_with_ids(project_root: Path, mapping: dict[str, str]) -> list[tuple[Path, Path]]:
    if not mapping:
        return []
    root = kb_root(project_root)
    renamed: list[tuple[Path, Path]] = []
    paths = sorted(root.rglob("*"), key=lambda item: (len(item.parts), len(item.as_posix())), reverse=True)
    for path in paths:
        if not path.exists():
            continue
        try:
            rel_path = path.resolve().relative_to(root.resolve())
        except ValueError:
            continue
        if rel_path.parts[:2] == ("user", "kb"):
            continue
        if "source" in rel_path.parts:
            continue
        updated_name = _replace_ids_in_text(path.name, mapping)
        if updated_name == path.name:
            continue
        destination = path.with_name(updated_name)
        if destination.exists():
            continue
        path.rename(destination)
        renamed.append((path, destination))
    return renamed


def compact_unit_ids(project_root: Path, *, kind: str | None = None, apply: bool = False) -> dict[str, Any]:
    ensure_workspace(project_root)
    records = iter_records(project_root, kind=kind)
    occupied_ids = {str(record.get("id") or "") for record in records if str(record.get("id") or "")}
    reserved_new_ids: set[str] = set()
    changes: list[dict[str, Any]] = []
    mapping: dict[str, str] = {}

    for record in records:
        item_kind = str(record.get("kind") or "")
        old_id = str(record.get("id") or "")
        title = str(record.get("title") or "")
        source_uri = str(record.get("source", {}).get("original_uri") or "")
        if not old_id or item_kind not in UNIT_KIND_DIRS:
            continue
        old_hash = _extract_unit_id_hash(old_id)
        new_id = canonical_unit_id_with_hash(item_kind, title=title, source=source_uri, hash_value=old_hash)
        if new_id != old_id and (new_id in reserved_new_ids or new_id in occupied_ids):
            for hash_size in (10, 12, 16):
                candidate = canonical_unit_id(item_kind, title=title, source=source_uri, hash_size=hash_size)
                if candidate == old_id or (candidate not in reserved_new_ids and (candidate not in occupied_ids or candidate == old_id)):
                    new_id = candidate
                    break
        reserved_new_ids.add(new_id)
        if new_id == old_id:
            continue
        mapping[old_id] = new_id
        changes.append(
            {
                "kind": item_kind,
                "title": title,
                "old_id": old_id,
                "new_id": new_id,
            }
        )

    summary = {
        "changed": len(changes),
        "mapping": mapping,
        "items": changes,
        "renamed_paths": [],
    }
    if not apply or not changes:
        return summary

    for item in changes:
        old_root = unit_root(project_root, item["kind"], item["old_id"])
        new_root = unit_root(project_root, item["kind"], item["new_id"])
        if new_root.exists() and new_root != old_root:
            raise SystemExit(f"Target unit path already exists: {rel(project_root, new_root)}")

    for item in changes:
        old_root = unit_root(project_root, item["kind"], item["old_id"])
        new_root = unit_root(project_root, item["kind"], item["new_id"])
        ensure_dir(new_root.parent)
        if old_root.exists() and old_root != new_root:
            old_root.rename(new_root)

    for record in records:
        original_id = str(record.get("id") or "")
        updated = _replace_ids_in_object(copy.deepcopy(record), mapping)
        current_id = mapping.get(original_id, original_id)
        updated["id"] = current_id
        legacy_ids = _unique_text_list(updated.get("legacy_ids"))
        if original_id in mapping:
            legacy_ids.append(original_id)
        updated["legacy_ids"] = [item for item in _unique_text_list(legacy_ids) if item and item != current_id]
        write_record(project_root, updated)

    renamed_paths = _rename_paths_with_ids(project_root, mapping)
    for path in kb_root(project_root).rglob("*"):
        if not path.is_file() or not _text_rewrite_allowed(project_root, path):
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        updated_content = _replace_ids_in_text(content, mapping)
        if updated_content != content:
            write_text_if_changed(path, updated_content)

    rebuild_governance_catalogs(project_root)
    build_index(project_root)

    summary["renamed_paths"] = [
        {"old": rel(project_root, old_path), "new": rel(project_root, new_path)}
        for old_path, new_path in renamed_paths
    ]
    return summary


def link_records(project_root: Path, from_id: str, to_id: str, relation: str, note: str = "") -> None:
    from_record, _ = locate_record(project_root, from_id)
    to_record, _ = locate_record(project_root, to_id)
    link = {"target_id": to_id, "relation": relation, "note": note}
    back_link = {"target_id": from_id, "relation": f"reverse:{relation}", "note": note}
    if link not in from_record.setdefault("links", []):
        from_record["links"].append(link)
        append_history(from_record, action="linked", summary=f"Linked to {to_id} as {relation}.", artifacts=[])
        write_record(project_root, from_record)
    if back_link not in to_record.setdefault("links", []):
        to_record["links"].append(back_link)
        append_history(to_record, action="linked", summary=f"Linked to {from_id} as reverse:{relation}.", artifacts=[])
        write_record(project_root, to_record)


def promote_record(
    project_root: Path,
    unit_id: str,
    *,
    status: str | None = None,
    maturity: str | None = None,
    confirmation_status: str | None = None,
    confirmed_by: str = "",
    evidence: list[str] | None = None,
    confirmation_method: str = "kb.py promote",
) -> Path:
    record, _ = locate_record(project_root, unit_id)
    if status:
        record["status"] = status
    if maturity:
        record["maturity"] = maturity
    if confirmation_status:
        if confirmation_status == "confirmed":
            apply_confirmation(
                record,
                confirmed_by=confirmed_by,
                evidence=evidence or [],
                method=confirmation_method,
                project_root=project_root,
            )
        else:
            record["confirmation_status"] = confirmation_status
    append_history(record, action="promoted", summary="Updated record lifecycle state.")
    return write_record(project_root, record)
