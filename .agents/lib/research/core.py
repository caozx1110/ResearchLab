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
from .confirm import *
from .sources import *


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
