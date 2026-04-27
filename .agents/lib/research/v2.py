from __future__ import annotations

import copy
import hashlib
import re
import shutil
from pathlib import Path
from typing import Any

from .common import (
    ensure_dir,
    file_sha256,
    find_project_root,
    infer_topics_and_tags,
    is_url,
    load_yaml,
    program_root as common_program_root,
    research_root,
    slugify,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_duplicate_key_issues,
)

UNIT_KIND_DIRS = {
    "paper": "papers",
    "repo": "repos",
    "blog": "blogs",
    "idea": "ideas",
    "experiment": "experiments",
}
INFORMATION_TYPES = {"fact", "inference", "evaluation", "user_opinion", "unverified"}
MATURITY_LEVELS = {"lightweight", "complete"}
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
DEFAULT_REUSE_FLAGS = {
    "review": False,
    "idea": False,
    "experiment_design": False,
    "paper_writing": False,
    "weekly_report": False,
    "ppt": False,
}
DEFAULT_SETTINGS_MARKDOWN = """# Research Settings v2

- [x] 自动入库事实类基础信息
- [x] 默认维护 topic / tag / candidate pool 治理目录
- [x] 外部 source search 先进入 staging，再决定是否入库
- [ ] 自动生成详细论文笔记
- [ ] 快速筛选后自动进入完整入库
- [ ] 自动生成周报素材
- [ ] 自动提炼 PPT 可用表述
- [ ] 自动记录中间讨论过程
- [x] PDF 图片导出前检查 pdfimages / poppler
- [x] PDF 图片导出时过滤纯白图和 mask-like 图
- [x] AI 推断默认等待人工确认
- [x] AI 评价默认等待人工确认
- [x] 论文结构刷新 / figure 提取默认等待人工确认
- [x] idea review / select-best 默认保留显式决策痕迹
"""
DEFAULT_TOPIC_TAXONOMY = {
    "id": "topic-taxonomy-v2",
    "status": "active",
    "generated_by": "knowledge-base-manager",
    "policy": {
        "canonical_topic_style": "lowercase-hyphen-slug",
        "canonical_tag_style": "lowercase-hyphen-slug",
        "overwriteable_fields": ["topics", "tags", "candidate_pools", "summary"],
    },
    "topics": {},
    "tags": {},
}
DEFAULT_CANDIDATE_POOLS = {
    "id": "candidate-pools-v2",
    "status": "active",
    "generated_by": "knowledge-base-manager",
    "policy": {
        "selection_requires_confirmation": True,
        "default_membership_mode": "overwriteable",
    },
    "pools": {},
}
UNIT_KIND_PREFIXES = {
    "paper": "p",
    "repo": "r",
    "blog": "b",
    "idea": "i",
    "experiment": "x",
}
COMPACT_UNIT_ID_MAX_WORDS = 4
COMPACT_UNIT_ID_MAX_CHARS = 32
COMPACT_UNIT_ID_HASH_LEN = 8
TEXT_REWRITE_SUFFIXES = {".md", ".markdown", ".txt", ".yaml", ".yml", ".json"}
GREEK_LETTER_ALIASES = {
    "π": "pi",
    "Π": "pi",
    "ψ": "psi",
    "Ψ": "psi",
    "φ": "phi",
    "Φ": "phi",
    "α": "alpha",
    "Α": "alpha",
    "β": "beta",
    "Β": "beta",
    "γ": "gamma",
    "Γ": "gamma",
    "δ": "delta",
    "Δ": "delta",
    "λ": "lambda",
    "Λ": "lambda",
    "μ": "mu",
    "Μ": "mu",
    "σ": "sigma",
    "Σ": "sigma",
    "τ": "tau",
    "Τ": "tau",
    "ω": "omega",
    "Ω": "omega",
}


def project_root(start: Path | None = None) -> Path:
    return find_project_root(start)


def kb_root(project_root: Path) -> Path:
    return research_root(project_root)


def units_root(project_root: Path) -> Path:
    return kb_root(project_root) / "units"


def user_root(project_root: Path) -> Path:
    return kb_root(project_root) / "user"


def config_root(project_root: Path) -> Path:
    return kb_root(project_root) / "config"


def synthesis_root(project_root: Path) -> Path:
    return kb_root(project_root) / "synthesis"


def source_search_root(project_root: Path) -> Path:
    return synthesis_root(project_root) / "source-search"


def topic_taxonomy_path(project_root: Path) -> Path:
    return config_root(project_root) / "topic-taxonomy.yaml"


def candidate_pools_path(project_root: Path) -> Path:
    return config_root(project_root) / "candidate-pools.yaml"


def kind_dir(kind: str) -> str:
    if kind not in UNIT_KIND_DIRS:
        raise SystemExit(f"Unsupported unit kind: {kind}")
    return UNIT_KIND_DIRS[kind]


def unit_root(project_root: Path, kind: str, unit_id: str) -> Path:
    return units_root(project_root) / kind_dir(kind) / unit_id


def record_path(project_root: Path, kind: str, unit_id: str) -> Path:
    return unit_root(project_root, kind, unit_id) / "record.yaml"


def search_stage_path(project_root: Path, stage_id: str) -> Path:
    return source_search_root(project_root) / f"{stage_id}.yaml"


def rel(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def _slug_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    cleaned = {slugify(str(item), max_words=12) for item in values if str(item).strip()}
    return sorted(item for item in cleaned if item)


def _text_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def _artifact_list(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return sorted({str(item).strip() for item in values if str(item).strip()})


def _unique_text_list(values: Any) -> list[str]:
    seen: set[str] = set()
    items: list[str] = []
    for item in _text_list(values):
        if item in seen:
            continue
        seen.add(item)
        items.append(item)
    return items


def _deep_fill_missing(target: Any, defaults: Any) -> Any:
    if isinstance(defaults, dict):
        base = target if isinstance(target, dict) else {}
        for key, value in defaults.items():
            if key not in base:
                base[key] = copy.deepcopy(value)
            else:
                base[key] = _deep_fill_missing(base[key], value)
        return base
    return target if target is not None else copy.deepcopy(defaults)


def kind_payload_skeleton(kind: str, title: str = "") -> dict[str, Any]:
    if kind == "paper":
        return {
            "basic_info": {
                "title": title,
                "authors": [],
                "institutions": [],
                "venue": "",
                "year": "",
                "source_url": "",
                "code_url": "",
                "project_url": "",
            },
            "source_search": {
                "stage_ids": [],
                "candidate_ids": [],
                "queries": [],
            },
            "quick_screen": {
                "worth_deep_reading": "unknown",
                "judgement_reason": [],
                "backing_strength": "",
                "result_strength": "",
                "experiment_quality": "",
                "reliability": "",
                "novelty": "",
                "relevance_to_current_research": "",
                "takeaways": [],
                "recommended_next_action": "",
            },
            "core_content": {
                "research_problem": "",
                "motivation": "",
                "story": "",
                "method": "",
                "innovations": [],
                "changes_and_effects": [],
                "mechanism": "",
                "why_it_might_work": "",
            },
            "structure": {
                "refresh_status": "not_started",
                "detected_sections": [],
                "paper_outline": [],
                "open_questions": [],
            },
            "figures": {
                "extraction_status": "not_started",
                "candidate_figures": [],
                "key_figures": [],
            },
            "critique": {
                "assumptions": [],
                "weak_spots": [],
                "experiment_gaps": [],
                "reliability_risks": [],
                "failure_scenarios": [],
                "improvements": [],
                "key_insights": [],
            },
            "state": {
                "reading_status": "unread",
                "needs_reread": False,
                "useful_for_review": False,
                "useful_for_experiment": False,
                "useful_for_writing": False,
            },
        }
    if kind == "repo":
        return {
            "basic_info": {
                "name": title,
                "owner": "",
                "url": "",
                "paper_url": "",
                "license": "",
                "last_activity": "",
                "environment": [],
            },
            "source_search": {
                "stage_ids": [],
                "candidate_ids": [],
                "queries": [],
            },
            "capability": {
                "problem": "",
                "core_capabilities": [],
                "inputs": [],
                "outputs": [],
                "supported_tasks": [],
                "unsupported_tasks": [],
                "boundary": "",
                "candidate_roles": [],
            },
            "structure": {
                "scan_status": "not_started",
                "repo_root": "",
                "top_level_dirs": [],
                "top_level_files": [],
                "languages": [],
                "core_modules": [],
                "entrypoints": [],
                "training_flow": [],
                "inference_flow": [],
                "config_system": [],
                "data_flow": [],
                "critical_modules": [],
            },
            "reuse": {
                "directly_reusable": [],
                "worth_borrowing": [],
                "worth_modifying": [],
                "modification_difficulty": [],
                "pipeline_value": [],
            },
            "risk": {
                "engineering_complexity": "",
                "dependency_weight": "",
                "reproduction_barrier": "",
                "performance_boundary": "",
                "constraints": [],
                "not_suitable_for": [],
            },
        }
    if kind == "blog":
        return {
            "basic_info": {
                "title": title,
                "author": "",
                "platform": "",
                "year": "",
                "url": "",
            },
            "source_search": {
                "stage_ids": [],
                "candidate_ids": [],
                "queries": [],
            },
            "positioning": {
                "content_type": "",
                "best_reading_stage": "",
                "main_value": "",
            },
            "content": {
                "key_points": [],
                "hard_parts_explained": [],
                "intuitions": [],
                "supports": [],
            },
            "credibility": {
                "reference_mode": "",
                "good_for_reference": [],
                "needs_verification": [],
                "best_use": "",
            },
        }
    if kind == "idea":
        return {
            "origin": {
                "title": title,
                "source": "",
                "theme": "",
            },
            "candidate": {
                "bundle_id": "",
                "strategy": "",
                "pool": "",
            },
            "problem": {
                "problem_definition": "",
                "pain_point": "",
                "target_improvement": "",
                "scope": "",
            },
            "hypothesis": {
                "core_hypothesis": "",
                "why_it_might_work": "",
                "key_mechanism": "",
                "difference_from_prior_work": "",
            },
            "analysis": {
                "related_work": [],
                "novelty": "",
                "incremental_or_new_direction": "",
                "feasibility": "",
                "minimum_validation_path": "",
                "risks": [],
                "next_actions": [],
            },
            "review": {
                "review_status": "not_started",
                "recommendation": "pending_confirmation",
                "score_breakdown": {},
                "evidence_gaps": [],
                "killer_questions": [],
            },
            "selection": {
                "selected_rank": "",
                "selected_reason": "",
                "selected_at": "",
            },
            "state": {
                "progress_state": "spark",
                "worth_pursuing": "unknown",
            },
        }
    if kind == "experiment":
        return {
            "basic_info": {
                "title": title,
                "program_id": "",
                "idea_id": "",
                "goal": "",
                "owner": "",
            },
            "setup": {
                "data": [],
                "model": "",
                "hyperparameters": {},
                "runtime": {},
                "hardware": [],
                "environment": [],
            },
            "process": {
                "change_summary": [],
                "delta_from_previous": [],
                "why_this_run": "",
                "tested_hypothesis": "",
            },
            "results": {
                "metrics": {},
                "comparison": [],
                "met_expectation": "unknown",
                "abnormalities": [],
                "artifacts": [],
            },
            "diagnosis": {
                "failure_modes": [],
                "likely_causes": [],
                "ruled_out_causes": [],
                "unknowns": [],
                "next_actions": [],
            },
        }
    raise SystemExit(f"Unsupported unit kind: {kind}")


def build_unit_id(kind: str, title: str, source: str = "") -> str:
    return canonical_unit_id(kind, title=title, source=source)


def _unit_slug_seed(title: str, source: str = "") -> str:
    text = title.strip() or source.strip()
    if "://" in text:
        text = source.strip() or title.strip()
    text = re.sub(r"^\d{4}(?:[-/]\d{1,2}){1,2}\s+", "", text)
    for raw, alias in GREEK_LETTER_ALIASES.items():
        text = text.replace(raw, f" {alias} ")
    text = re.sub(r"([a-z])([A-Z][a-z])", r"\1 \2", text)
    text = re.sub(r"([A-Z]{2,})([A-Z][a-z])", r"\1 \2", text)
    return text.strip()


def compact_unit_slug(seed: str, *, max_words: int = COMPACT_UNIT_ID_MAX_WORDS, max_chars: int = COMPACT_UNIT_ID_MAX_CHARS) -> str:
    slug = slugify(_unit_slug_seed(seed), max_words=max_words) or "item"
    if len(slug) <= max_chars:
        return slug
    chosen: list[str] = []
    for part in slug.split("-"):
        candidate = "-".join(chosen + [part]) if chosen else part
        if len(candidate) > max_chars:
            break
        chosen.append(part)
    if chosen:
        return "-".join(chosen)
    return slug[:max_chars].strip("-") or "item"


def canonical_unit_id(kind: str, *, title: str, source: str = "", hash_size: int = COMPACT_UNIT_ID_HASH_LEN) -> str:
    if kind not in UNIT_KIND_PREFIXES:
        raise SystemExit(f"Unsupported unit kind: {kind}")
    seed = title or source or kind
    slug_seed = title or source or kind
    prefix = UNIT_KIND_PREFIXES[kind]
    compact_slug = compact_unit_slug(slug_seed)
    short_hash = hashlib.sha1(seed.encode("utf-8")).hexdigest()[: max(6, hash_size)]
    return f"{prefix}-{compact_slug}-{short_hash}"


def canonical_unit_id_with_hash(kind: str, *, title: str, source: str = "", hash_value: str = "") -> str:
    if kind not in UNIT_KIND_PREFIXES:
        raise SystemExit(f"Unsupported unit kind: {kind}")
    compact_slug = compact_unit_slug(title or source or kind)
    normalized_hash = re.sub(r"[^0-9a-f]", "", hash_value.lower())[:16]
    if len(normalized_hash) < 6:
        return canonical_unit_id(kind, title=title, source=source)
    return f"{UNIT_KIND_PREFIXES[kind]}-{compact_slug}-{normalized_hash}"


def is_canonical_unit_id(kind: str, unit_id: str) -> bool:
    prefix = UNIT_KIND_PREFIXES.get(kind, "")
    if not prefix:
        return False
    return bool(re.fullmatch(rf"{re.escape(prefix)}-[a-z0-9]+(?:-[a-z0-9]+)*-[0-9a-f]{{6,16}}", unit_id.strip()))


def _extract_unit_id_hash(unit_id: str) -> str:
    match = re.search(r"-([0-9a-f]{6,16})$", unit_id.strip().lower())
    return match.group(1) if match else ""


def _record_template(kind: str, *, title: str, maturity: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    unit_id = build_unit_id(kind, title, str(source.get("original_uri") if source else ""))
    now = utc_now_iso()
    return {
        "id": unit_id,
        "legacy_ids": [],
        "kind": kind,
        "title": title,
        "status": "draft",
        "maturity": maturity if maturity in MATURITY_LEVELS else "lightweight",
        "confirmation_status": "auto_confirmed",
        "needs_human_confirmation": False,
        "information_types": ["fact"],
        "confidence": 0.9,
        "created_at": now,
        "first_ingested_at": now,
        "updated_at": now,
        "last_human_confirmed_at": "",
        "tags": [],
        "topics": [],
        "candidate_pools": [],
        "program_ids": [],
        "priority": "normal",
        "summary": "",
        "links": [],
        "reuse_flags": dict(DEFAULT_REUSE_FLAGS),
        "taxonomy": {
            "primary_topic": "",
            "secondary_topics": [],
            "canonical_tags": [],
            "topic_sources": [],
            "tag_sources": [],
            "pool_sources": [],
        },
        "artifacts": [],
        "source": source or {},
        "payload": kind_payload_skeleton(kind, title),
        "history": [],
    }


def record_summary(record: dict[str, Any]) -> str:
    summary = str(record.get("summary") or "").strip()
    if summary:
        return summary
    payload = record.get("payload", {})
    if record.get("kind") == "paper":
        reason = payload.get("quick_screen", {}).get("judgement_reason", [])
        if reason:
            return str(reason[0])
        takeaways = payload.get("quick_screen", {}).get("takeaways", [])
        if takeaways:
            return str(takeaways[0])
    if record.get("kind") == "repo":
        boundary = payload.get("capability", {}).get("boundary")
        if boundary:
            return str(boundary)
        capabilities = payload.get("capability", {}).get("core_capabilities", [])
        if capabilities:
            return str(capabilities[0])
    if record.get("kind") == "idea":
        problem = payload.get("problem", {}).get("problem_definition")
        if problem:
            return str(problem)
        hypothesis = payload.get("hypothesis", {}).get("core_hypothesis")
        if hypothesis:
            return str(hypothesis)
    if record.get("kind") == "experiment":
        goal = payload.get("basic_info", {}).get("goal")
        if goal:
            return str(goal)
    return ""


def append_history(
    record: dict[str, Any],
    *,
    action: str,
    summary: str,
    information_types: list[str] | None = None,
    artifacts: list[str] | None = None,
) -> None:
    record.setdefault("history", []).append(
        {
            "timestamp": utc_now_iso(),
            "action": action,
            "summary": summary,
            "information_types": information_types or ["fact"],
            "artifacts": artifacts or [],
        }
    )
    record["updated_at"] = utc_now_iso()


def default_record(kind: str, *, title: str, maturity: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    record = _record_template(kind, title=title, maturity=maturity, source=source)
    append_history(record, action="created", summary=f"Created {kind} record.")
    return record


def normalize_record_schema(record: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise SystemExit("Invalid record payload")
    kind = str(record.get("kind") or "")
    if kind not in UNIT_KIND_DIRS:
        raise SystemExit(f"Unsupported unit kind: {kind}")
    title = str(record.get("title") or "")
    maturity = str(record.get("maturity") or "lightweight")
    source = record.get("source", {})
    template = _record_template(kind, title=title, maturity=maturity, source=source if isinstance(source, dict) else {})
    normalized = _deep_fill_missing(record, template)
    normalized["title"] = title or str(normalized.get("title") or normalized["id"])
    normalized["status"] = str(normalized.get("status") or "draft")
    normalized["maturity"] = str(normalized.get("maturity") or "lightweight")
    normalized["confirmation_status"] = str(normalized.get("confirmation_status") or "auto_confirmed")
    normalized["legacy_ids"] = [
        item
        for item in _unique_text_list(normalized.get("legacy_ids"))
        if item and item != str(normalized.get("id") or "")
    ]
    normalized["information_types"] = sorted(
        item for item in {str(value) for value in normalized.get("information_types", [])} if item in INFORMATION_TYPES
    ) or ["fact"]
    normalized["tags"] = _slug_list(normalized.get("tags"))
    normalized["topics"] = _slug_list(normalized.get("topics"))
    normalized["candidate_pools"] = _slug_list(normalized.get("candidate_pools"))
    normalized["program_ids"] = _slug_list(normalized.get("program_ids"))
    normalized["artifacts"] = _artifact_list(normalized.get("artifacts"))
    normalized["links"] = [dict(item) for item in normalized.get("links", []) if isinstance(item, dict) and item.get("target_id")]
    normalized["history"] = [dict(item) for item in normalized.get("history", []) if isinstance(item, dict)]
    if not normalized["history"]:
        append_history(normalized, action="created", summary=f"Backfilled history for {kind} record.")
    taxonomy = normalized.get("taxonomy", {})
    if not isinstance(taxonomy, dict):
        taxonomy = {}
    taxonomy.setdefault("primary_topic", normalized["topics"][0] if normalized["topics"] else "")
    taxonomy["secondary_topics"] = [topic for topic in normalized["topics"] if topic != taxonomy["primary_topic"]]
    taxonomy["canonical_tags"] = list(normalized["tags"])
    taxonomy["topic_sources"] = _text_list(taxonomy.get("topic_sources"))
    taxonomy["tag_sources"] = _text_list(taxonomy.get("tag_sources"))
    taxonomy["pool_sources"] = _text_list(taxonomy.get("pool_sources"))
    normalized["taxonomy"] = taxonomy
    payload = normalized.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}
    normalized["payload"] = _deep_fill_missing(payload, kind_payload_skeleton(kind, normalized["title"]))
    return normalized


def ensure_v2_workspace(project_root: Path) -> None:
    ensure_dir(units_root(project_root))
    for kind in UNIT_KIND_DIRS.values():
        ensure_dir(units_root(project_root) / kind)
    ensure_dir(kb_root(project_root) / "programs")
    ensure_dir(user_root(project_root))
    ensure_dir(user_root(project_root) / "reading-lists")
    ensure_dir(user_root(project_root) / "report-materials")
    ensure_dir(config_root(project_root))
    ensure_dir(synthesis_root(project_root))
    ensure_dir(source_search_root(project_root))
    settings = config_root(project_root) / "research-settings.md"
    if not settings.exists():
        write_text_if_changed(settings, DEFAULT_SETTINGS_MARKDOWN)
    navigation = user_root(project_root) / "navigation.md"
    if not navigation.exists():
        write_text_if_changed(navigation, "# Research Navigation v2\n\n- 运行 `research-navigator` 刷新当前入口页。\n")
    current_state = user_root(project_root) / "current-state.md"
    if not current_state.exists():
        write_text_if_changed(current_state, "# Current State\n\n尚未生成。\n")
    if not topic_taxonomy_path(project_root).exists():
        write_yaml_if_changed(topic_taxonomy_path(project_root), {**DEFAULT_TOPIC_TAXONOMY, "generated_at": utc_now_iso()})
    if not candidate_pools_path(project_root).exists():
        write_yaml_if_changed(candidate_pools_path(project_root), {**DEFAULT_CANDIDATE_POOLS, "generated_at": utc_now_iso()})


def load_topic_taxonomy(project_root: Path) -> dict[str, Any]:
    ensure_v2_workspace(project_root)
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
    ensure_v2_workspace(project_root)
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


def load_record(project_root: Path, kind: str, unit_id: str) -> dict[str, Any]:
    payload = load_yaml(record_path(project_root, kind, unit_id), default={})
    if not isinstance(payload, dict):
        raise SystemExit(f"Invalid record: {kind}/{unit_id}")
    return normalize_record_schema(payload)


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


def write_record(project_root: Path, record: dict[str, Any]) -> Path:
    normalized = normalize_record_schema(record)
    root = unit_root(project_root, str(normalized["kind"]), str(normalized["id"]))
    ensure_dir(root)
    path = root / "record.yaml"
    normalized["updated_at"] = utc_now_iso()
    write_yaml_if_changed(path, normalized)
    return path


def iter_records(project_root: Path, *, kind: str | None = None) -> list[dict[str, Any]]:
    kinds = [kind] if kind else list(UNIT_KIND_DIRS)
    items: list[dict[str, Any]] = []
    for item_kind in kinds:
        root = units_root(project_root) / kind_dir(item_kind)
        if not root.exists():
            continue
        for path in sorted(root.glob("*/record.yaml")):
            payload = load_yaml(path, default={})
            if isinstance(payload, dict):
                try:
                    items.append(normalize_record_schema(payload))
                except SystemExit:
                    items.append(payload)
    return items


def locate_record(project_root: Path, unit_id: str) -> tuple[dict[str, Any], Path]:
    for kind in UNIT_KIND_DIRS:
        path = record_path(project_root, kind, unit_id)
        if path.exists():
            payload = load_yaml(path, default={})
            if isinstance(payload, dict):
                return normalize_record_schema(payload), path
    for record in iter_records(project_root):
        if unit_id in _unique_text_list(record.get("legacy_ids")):
            current_kind = str(record.get("kind") or "")
            current_id = str(record.get("id") or "")
            if current_kind in UNIT_KIND_DIRS and current_id:
                return record, record_path(project_root, current_kind, current_id)
    raise SystemExit(f"Record not found: {unit_id}")


def refresh_record_schemas(project_root: Path, *, unit_ids: list[str] | None = None, kind: str | None = None) -> list[Path]:
    ensure_v2_workspace(project_root)
    paths: list[Path] = []
    if unit_ids:
        for unit_id in unit_ids:
            record, _ = locate_record(project_root, unit_id)
            paths.append(write_record(project_root, record))
        return paths
    for record in iter_records(project_root, kind=kind):
        paths.append(write_record(project_root, record))
    return paths


def rebuild_governance_catalogs(project_root: Path) -> tuple[Path, Path]:
    ensure_v2_workspace(project_root)
    existing_taxonomy = load_topic_taxonomy(project_root)
    existing_pools = load_candidate_pools(project_root)
    taxonomy = {**existing_taxonomy, "topics": {}, "tags": {}}
    pools = {**existing_pools, "pools": {}}

    for record in iter_records(project_root):
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

    taxonomy_path = write_topic_taxonomy(project_root, taxonomy)
    pools_path = write_candidate_pools(project_root, pools)
    return taxonomy_path, pools_path


def build_index(project_root: Path) -> tuple[Path, Path]:
    ensure_v2_workspace(project_root)
    rebuild_governance_catalogs(project_root)
    items = []
    for record in sorted(iter_records(project_root), key=lambda x: (str(x.get("kind")), str(x.get("title")))):
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
            "id": "kb-index-v2",
            "generated_at": utc_now_iso(),
            "items": items,
            "counts": {kind: len([item for item in items if item["kind"] == kind]) for kind in UNIT_KIND_DIRS},
        },
    )
    lines = ["# Research KB Index v2", ""]
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

    for record in iter_records(project_root):
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
                record, _ = locate_record(project_root, unit_id)
            except SystemExit:
                issues.append(f"{rel(project_root, state_file)}: active_unit_id `{unit_id}` not found")
                continue
            if program_id not in _slug_list(record.get("program_ids")):
                issues.append(f"{rel(project_root, state_file)}: `{unit_id}` missing reverse program_ids link to `{program_id}`")

    for record in iter_records(project_root):
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
    ensure_v2_workspace(project_root)
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
    issues.extend(lint_workspace_integrity(project_root))
    return ("PASS" if not issues else "FAIL"), issues


def search_records(project_root: Path, query: str, *, kind: str | None = None, pool: str | None = None) -> list[dict[str, Any]]:
    tokens = [token for token in query.lower().split() if token]
    normalized_pool = slugify(str(pool), max_words=12) if pool else ""
    hits: list[dict[str, Any]] = []
    for record in iter_records(project_root, kind=kind):
        if normalized_pool and normalized_pool not in record.get("candidate_pools", []):
            continue
        haystack = " ".join(
            [
                str(record.get("title") or ""),
                str(record.get("summary") or ""),
                " ".join(str(tag) for tag in record.get("tags", [])),
                " ".join(str(topic) for topic in record.get("topics", [])),
                " ".join(str(pool_name) for pool_name in record.get("candidate_pools", [])),
            ]
        ).lower()
        if all(token in haystack for token in tokens):
            hits.append(record)
    return hits


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
    ensure_v2_workspace(project_root)
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
    ensure_v2_workspace(project_root)
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
    shutil.copytree(src, dst)


def backup_source(project_root: Path, kind: str, unit_id: str, source: str) -> dict[str, Any]:
    root = unit_root(project_root, kind, unit_id) / "source"
    ensure_dir(root)
    if is_url(source):
        txt = root / "source-url.txt"
        write_text_if_changed(txt, source.strip() + "\n")
        return {"original_uri": source, "backup_paths": [rel(project_root, txt)], "backup_kind": "url", "file_hash": ""}

    src = Path(source).expanduser().resolve()
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


def detect_duplicate(project_root: Path, kind: str, source: str) -> dict[str, Any] | None:
    normalized = source.strip()
    file_hash = ""
    if not is_url(source):
        path = Path(source).expanduser().resolve()
        if path.exists() and path.is_file():
            file_hash = file_sha256(path)
            normalized = path.as_posix()
        elif path.exists():
            normalized = path.as_posix()
    for record in iter_records(project_root, kind=kind):
        record_source = record.get("source", {})
        if normalized and normalized == str(record_source.get("original_uri") or ""):
            return record
        if file_hash and file_hash == str(record_source.get("file_hash") or ""):
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
    ensure_v2_workspace(project_root)
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
        if new_id != old_id and (new_id in reserved_new_ids or (new_id in occupied_ids and new_id != old_id)):
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
) -> Path:
    record, _ = locate_record(project_root, unit_id)
    if status:
        record["status"] = status
    if maturity:
        record["maturity"] = maturity
    if confirmation_status:
        record["confirmation_status"] = confirmation_status
        if confirmation_status == "confirmed":
            record["last_human_confirmed_at"] = utc_now_iso()
            record["needs_human_confirmation"] = False
    append_history(record, action="promoted", summary="Updated record lifecycle state.")
    return write_record(project_root, record)
