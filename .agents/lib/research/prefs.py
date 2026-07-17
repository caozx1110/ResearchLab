"""Runtime preferences (incl. autonomy) and workspace bootstrap.

ensure_workspace lives here with default_runtime_preferences because the two are
mutually dependent (load_runtime_preferences -> ensure_workspace ->
default_runtime_preferences); co-locating them keeps the layering acyclic."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

from .common import (
    ensure_dir,
    load_yaml,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
)
from .paths import (
    UNIT_KIND_DIRS,
    _deep_fill_missing,
    candidate_pools_path,
    config_root,
    ensure_kb_gitignore,
    kb_root,
    kb_runtime_root,
    output_storage_root,
    raw_storage_root,
    runtime_preferences_path,
    source_search_root,
    synthesis_root,
    topic_taxonomy_path,
    units_root,
    user_root,
)

DEFAULT_SETTINGS_MARKDOWN = """# Research Settings

- [x] 自动入库事实类基础信息
- [x] 默认维护 topic / tag / candidate pool 治理目录
- [x] 外部 source search 先进入 staging，再决定是否入库
- [x] 新论文入库后自动快速筛选
- [x] intake 阶段预热 PDF 解析缓存
- [ ] 自动生成详细论文笔记
- [ ] 完整笔记后自动提取 Figure / Table
- [x] 完整笔记后自动刷新结构
- [ ] 自动生成周报素材
- [ ] 自动提炼 PPT 可用表述
- [ ] 自动记录中间讨论过程
- [x] PDF Figure / Table 默认按 caption 裁整块版面
- [x] PDF 图片导出时过滤纯白图和 mask-like 图
- [x] AI 推断默认等待人工确认
- [x] AI 评价默认等待人工确认
- [x] 论文结构刷新 / figure 提取默认等待人工确认
- [x] idea review / select-best 默认保留显式决策痕迹
- [x] 知识库独立 Git 仓库默认启用
- [x] 自动提交策略默认使用 milestone，可在 runtime preferences 调整

模式说明：

- 论文完整笔记触发条件、完整笔记模式（`scaffold` / `draft`）请使用 runtime preferences 管理。
"""


DEFAULT_TOPIC_TAXONOMY = {
    "id": "topic-taxonomy",
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
    "id": "candidate-pools",
    "status": "active",
    "generated_by": "knowledge-base-manager",
    "policy": {
        "selection_requires_confirmation": True,
        "default_membership_mode": "overwriteable",
    },
    "pools": {},
}


VERSIONING_COMMIT_MODES = {"manual", "milestone", "aggressive"}


PAPER_AUTO_COMPLETE_CONDITIONS = {
    "after_screen",
    "suggested_worth_reading",
    "strong_relevance",
}


PAPER_NOTE_MODES = {"scaffold", "draft"}


def default_runtime_preferences() -> dict[str, Any]:
    return {
        **yaml_default("runtime-preferences", "research-config-manager", status="active"),
        "browser": {
            "default_workbench_mode": "preview",
            "default_terminal_mode": "codex",
            "auto_open_recent_file": True,
        },
        "identity": {
            "default_confirmed_by": "",
        },
        "learned_preferences": {
            "items": [],
        },
        "autonomy": {
            "auto_execute_scope": ["screen", "build-index", "refresh", "generate-note"],
        },
        "paper": {
            "auto_screen_on_intake": True,
            "auto_complete_note": False,
            "auto_complete_note_condition": "suggested_worth_reading",
            "complete_note_mode": "scaffold",
            "auto_extract_figures_after_note": False,
            "auto_refresh_structure_after_note": True,
            "parse_cache_prewarm_on_intake": True,
            "parse_cache_front_limit": 8,
            "parse_cache_back_limit": 0,
            "parse_cache_per_page_char_limit": 3000,
            "screening_mode": "heuristic_structured",
            "screening_context_pages": 6,
            "screening_max_chars": 12000,
            "prompt_for_preference_updates": True,
        },
        "pdf": {
            "prefer_structured_source": True,
            "auto_extract_figures": False,
            "figure_extraction_mode": "caption-region",
            "reuse_cached_parse": True,
            "figure_include_tables": True,
            "figure_render_scale": 2.5,
            "figure_crop_padding_pt": 12,
            "filter_blank_and_mask_images": True,
        },
        "versioning": {
            "enabled": True,
            "separate_repo": True,
            "auto_init_repo": True,
            "auto_commit_mode": "milestone",
            "commit_on_browser_save": False,
            "debounce_seconds": 30,
            "ignored_paths": ["raw/", "output/", "user/kb/", ".runtime/"],
        },
    }


def load_runtime_preferences(project_root: Path) -> dict[str, Any]:
    ensure_workspace(project_root)
    payload = load_yaml(runtime_preferences_path(project_root), default={})
    if not isinstance(payload, dict) or not payload:
        payload = default_runtime_preferences()
    normalized = _deep_fill_missing(payload, default_runtime_preferences())
    browser = normalized.get("browser", {})
    if not isinstance(browser, dict):
        browser = {}
    browser["default_workbench_mode"] = str(browser.get("default_workbench_mode") or "preview")
    browser["default_terminal_mode"] = str(browser.get("default_terminal_mode") or "codex")
    browser["auto_open_recent_file"] = bool(browser.get("auto_open_recent_file"))
    normalized["browser"] = browser

    identity = normalized.get("identity", {})
    if not isinstance(identity, dict):
        identity = {}
    identity["default_confirmed_by"] = str(identity.get("default_confirmed_by") or "").strip()
    normalized["identity"] = identity

    learned_preferences = normalized.get("learned_preferences", {})
    if not isinstance(learned_preferences, dict):
        learned_preferences = {}
    items = learned_preferences.get("items", [])
    learned_preferences["items"] = [item for item in items if isinstance(item, dict)] if isinstance(items, list) else []
    normalized["learned_preferences"] = learned_preferences

    autonomy = normalized.get("autonomy", {})
    if not isinstance(autonomy, dict):
        autonomy = copy.deepcopy(default_runtime_preferences()["autonomy"])
    scope = autonomy.get("auto_execute_scope", [])
    if not isinstance(scope, list):
        scope = copy.deepcopy(default_runtime_preferences()["autonomy"]["auto_execute_scope"])
    autonomy["auto_execute_scope"] = [str(item).strip() for item in scope if str(item).strip()]
    normalized["autonomy"] = autonomy

    paper = normalized.get("paper", {})
    if not isinstance(paper, dict):
        paper = {}
    paper["auto_screen_on_intake"] = bool(paper.get("auto_screen_on_intake", True))
    paper["auto_complete_note"] = bool(paper.get("auto_complete_note"))
    condition = str(paper.get("auto_complete_note_condition") or "suggested_worth_reading").strip()
    paper["auto_complete_note_condition"] = (
        condition if condition in PAPER_AUTO_COMPLETE_CONDITIONS else "suggested_worth_reading"
    )
    note_mode = str(paper.get("complete_note_mode") or "scaffold").strip()
    paper["complete_note_mode"] = note_mode if note_mode in PAPER_NOTE_MODES else "scaffold"
    paper["auto_extract_figures_after_note"] = bool(paper.get("auto_extract_figures_after_note"))
    paper["auto_refresh_structure_after_note"] = bool(paper.get("auto_refresh_structure_after_note", True))
    paper["parse_cache_prewarm_on_intake"] = bool(paper.get("parse_cache_prewarm_on_intake", True))
    try:
        paper["parse_cache_front_limit"] = max(1, int(paper.get("parse_cache_front_limit") or 8))
    except (TypeError, ValueError):
        paper["parse_cache_front_limit"] = 8
    try:
        paper["parse_cache_back_limit"] = max(0, int(paper.get("parse_cache_back_limit") or 0))
    except (TypeError, ValueError):
        paper["parse_cache_back_limit"] = 0
    try:
        paper["parse_cache_per_page_char_limit"] = max(500, int(paper.get("parse_cache_per_page_char_limit") or 3000))
    except (TypeError, ValueError):
        paper["parse_cache_per_page_char_limit"] = 3000
    paper["screening_mode"] = str(paper.get("screening_mode") or "heuristic_structured").strip() or "heuristic_structured"
    try:
        paper["screening_context_pages"] = max(1, int(paper.get("screening_context_pages") or 6))
    except (TypeError, ValueError):
        paper["screening_context_pages"] = 6
    try:
        paper["screening_max_chars"] = max(1000, int(paper.get("screening_max_chars") or 12000))
    except (TypeError, ValueError):
        paper["screening_max_chars"] = 12000
    paper["prompt_for_preference_updates"] = bool(paper.get("prompt_for_preference_updates", True))
    normalized["paper"] = paper

    pdf = normalized.get("pdf", {})
    if not isinstance(pdf, dict):
        pdf = {}
    pdf["prefer_structured_source"] = bool(pdf.get("prefer_structured_source"))
    pdf["auto_extract_figures"] = bool(pdf.get("auto_extract_figures"))
    pdf["figure_extraction_mode"] = "caption-region"
    pdf["reuse_cached_parse"] = bool(pdf.get("reuse_cached_parse"))
    pdf["figure_include_tables"] = bool(pdf.get("figure_include_tables", True))
    try:
        pdf["figure_render_scale"] = max(1.0, float(pdf.get("figure_render_scale") or 2.5))
    except (TypeError, ValueError):
        pdf["figure_render_scale"] = 2.5
    try:
        pdf["figure_crop_padding_pt"] = max(0.0, float(pdf.get("figure_crop_padding_pt") or 12))
    except (TypeError, ValueError):
        pdf["figure_crop_padding_pt"] = 12.0
    pdf["filter_blank_and_mask_images"] = bool(pdf.get("filter_blank_and_mask_images"))
    normalized["pdf"] = pdf

    versioning = normalized.get("versioning", {})
    if not isinstance(versioning, dict):
        versioning = {}
    versioning["enabled"] = bool(versioning.get("enabled"))
    versioning["separate_repo"] = bool(versioning.get("separate_repo"))
    versioning["auto_init_repo"] = bool(versioning.get("auto_init_repo"))
    mode = str(versioning.get("auto_commit_mode") or "milestone").strip().lower()
    versioning["auto_commit_mode"] = mode if mode in VERSIONING_COMMIT_MODES else "milestone"
    versioning["commit_on_browser_save"] = bool(versioning.get("commit_on_browser_save"))
    try:
        versioning["debounce_seconds"] = max(0, int(versioning.get("debounce_seconds") or 0))
    except (TypeError, ValueError):
        versioning["debounce_seconds"] = 30
    ignored = versioning.get("ignored_paths", [])
    normalized_ignored: list[str] = []
    if isinstance(ignored, list):
        for item in ignored:
            text = str(item).strip()
            if not text:
                continue
            if text.startswith("kb/"):
                text = text[3:]
            normalized_ignored.append(text)
    versioning["ignored_paths"] = normalized_ignored
    normalized["versioning"] = versioning
    return normalized


def write_runtime_preferences(project_root: Path, payload: dict[str, Any]) -> Path:
    current = load_runtime_preferences(project_root)
    merged = copy.deepcopy(current)
    for key in ("browser", "identity", "learned_preferences", "autonomy", "paper", "pdf", "versioning"):
        value = payload.get(key)
        if isinstance(value, dict):
            target = merged.setdefault(key, {})
            if not isinstance(target, dict):
                target = {}
                merged[key] = target
            target.update(value)
    normalized = _deep_fill_missing(merged, default_runtime_preferences())
    write_yaml_if_changed(runtime_preferences_path(project_root), normalized)
    return runtime_preferences_path(project_root)


def ensure_workspace(project_root: Path) -> None:
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
    ensure_dir(raw_storage_root(project_root))
    ensure_dir(output_storage_root(project_root))
    ensure_dir(kb_runtime_root(project_root))
    ensure_kb_gitignore(project_root)
    settings = config_root(project_root) / "research-settings.md"
    if not settings.exists():
        write_text_if_changed(settings, DEFAULT_SETTINGS_MARKDOWN)
    navigation = user_root(project_root) / "navigation.md"
    if not navigation.exists():
        write_text_if_changed(navigation, "# Research Navigation\n\n- 运行 `research-navigator` 刷新当前入口页。\n")
    current_state = user_root(project_root) / "current-state.md"
    if not current_state.exists():
        write_text_if_changed(current_state, "# Current State\n\n尚未生成。\n")
    if not topic_taxonomy_path(project_root).exists():
        write_yaml_if_changed(topic_taxonomy_path(project_root), {**DEFAULT_TOPIC_TAXONOMY, "generated_at": utc_now_iso()})
    if not candidate_pools_path(project_root).exists():
        write_yaml_if_changed(candidate_pools_path(project_root), {**DEFAULT_CANDIDATE_POOLS, "generated_at": utc_now_iso()})
    if not runtime_preferences_path(project_root).exists():
        write_yaml_if_changed(runtime_preferences_path(project_root), default_runtime_preferences())


__all__ = [
    "DEFAULT_SETTINGS_MARKDOWN",
    "DEFAULT_TOPIC_TAXONOMY",
    "DEFAULT_CANDIDATE_POOLS",
    "VERSIONING_COMMIT_MODES",
    "PAPER_AUTO_COMPLETE_CONDITIONS",
    "PAPER_NOTE_MODES",
    "default_runtime_preferences",
    "load_runtime_preferences",
    "write_runtime_preferences",
    "ensure_workspace",
]
