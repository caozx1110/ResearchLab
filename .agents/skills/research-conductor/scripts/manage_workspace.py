#!/usr/bin/env python3
"""Bootstrap and maintain the research v1.1 workspace."""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from typing import Any

for candidate in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
    lib_root = candidate / ".agents" / "lib"
    if (lib_root / "research_v11" / "common.py").exists():
        sys.path.insert(0, str(lib_root))
        break

from research_v11.common import (
    append_program_reporting_event,
    append_wiki_log_event,
    blank_reporting_events,
    bootstrap_program,
    bootstrap_workspace,
    clean_text,
    current_runtime_capabilities,
    ensure_dir,
    ensure_research_runtime,
    find_project_root,
    format_runtime_report,
    inspect_python_runtime,
    load_literature_records,
    load_list_document,
    load_program_reporting_events,
    load_repo_summaries,
    load_runtime_registry,
    load_yaml,
    lint_wiki_workspace,
    normalize_title,
    preferred_runtime_record,
    program_reporting_events_path,
    query_keyword_terms,
    rebuild_wiki_index_markdown,
    remember_runtime as remember_runtime_record,
    research_root,
    slugify,
    utc_now_iso,
    write_query_artifact,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
)

DEFAULT_STAGES = (
    "problem-framing",
    "literature-analysis",
    "idea-generation",
    "idea-review",
    "method-design",
    "implementation-planning",
)
REPORT_SHORT_TOKENS = {"vla", "wbc", "gr00t", "g1", "rt1", "rt2", "pi0", "pi05", "octo"}
STABLE_MEMORY_CUES = (
    "i have",
    "we have",
    "i've got",
    "we've got",
    "prefer",
    "preferred",
    "default to",
    "reply in",
    "respond in",
    "risk preference",
    "long term",
    "long-term",
    "focus on",
    "access to",
    "available to us",
    "my setup",
    "our setup",
    "我有",
    "我们有",
    "现在有",
    "手上有",
    "可用",
    "能用",
    "配置",
    "偏好",
    "默认",
    "中文回复",
    "英文回复",
    "风险偏好",
    "长期方向",
    "长期研究",
    "长期关注",
)
ABUNDANT_ACCESS_CUES = ("ample", "plenty", "many", "abundant", "充足", "很多", "充裕")
RESOURCE_AVAILABILITY_CUES = (
    "i have",
    "we have",
    "i've got",
    "we've got",
    "access to",
    "available",
    "available to us",
    "my setup",
    "our setup",
    "我有",
    "我们有",
    "现在有",
    "手上有",
    "可用",
    "能用",
    "配置",
)


def existing_program_root(project_root: Path, program_id: str) -> Path:
    path = research_root(project_root) / "programs" / program_id
    if not path.exists():
        raise SystemExit(f"Program not found: {program_id}")
    return path


def monthly_history_path(project_root: Path) -> Path:
    stamp = utc_now_iso()[:7]
    return research_root(project_root) / "memory" / "history" / f"{stamp}.yaml"


def landscape_report_path(project_root: Path, survey_id: str) -> Path:
    return research_root(project_root) / "library" / "landscapes" / survey_id / "landscape-report.yaml"


def append_history(project_root: Path, event: dict[str, Any]) -> None:
    path = monthly_history_path(project_root)
    payload = load_list_document(path, f"history-{path.stem}", "research-conductor")
    payload["generated_at"] = utc_now_iso()
    payload["items"].append(event)
    write_yaml_if_changed(path, payload)


def append_decision_log_entry(project_root: Path, program_id: str, stage: str, summary: str) -> None:
    program_root = existing_program_root(project_root, program_id)
    path = program_root / "workflow" / "decision-log.md"
    existing = path.read_text(encoding="utf-8") if path.exists() else "# Decision Log\n\n"
    entry = f"- {utc_now_iso()}: [{stage}] {summary}\n"
    write_text_if_changed(path, existing + entry)


def parse_iso_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def within_window(timestamp: datetime | None, window_start: datetime, window_end: datetime) -> bool:
    return timestamp is not None and window_start <= timestamp < window_end


def report_window(days: int, end_date_text: str) -> tuple[datetime, datetime]:
    if days < 1:
        raise SystemExit("--days must be at least 1")
    if end_date_text:
        try:
            end_date = date.fromisoformat(end_date_text)
        except ValueError as exc:
            raise SystemExit(f"Invalid --end-date: {end_date_text}") from exc
        window_end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    else:
        window_end = datetime.now(timezone.utc).replace(microsecond=0)
    return window_end - timedelta(days=days), window_end


def report_window_label(window_start: datetime, window_end: datetime) -> str:
    inclusive_end = window_end - timedelta(seconds=1)
    return f"{window_start.date().isoformat()} to {inclusive_end.date().isoformat()} (UTC)"


def compact_text(text: Any, *, max_chars: int = 240) -> str:
    cleaned = re.sub(r"\s+", " ", clean_text(str(text or ""))).strip()
    if len(cleaned) <= max_chars:
        return cleaned
    trimmed = cleaned[: max_chars - 3].rsplit(" ", 1)[0].rstrip(" ,;:-")
    if not trimmed:
        trimmed = cleaned[: max_chars - 3]
    return f"{trimmed}..."


def markdown_cell(text: Any) -> str:
    return compact_text(text, max_chars=180).replace("|", "\\|").replace("\n", " ")


def report_tokens(*values: Any) -> set[str]:
    tokens: set[str] = set()
    for value in values:
        normalized = normalize_title(str(value or ""))
        if not normalized:
            continue
        for token in normalized.split():
            if len(token) >= 4 or token in REPORT_SHORT_TOKENS or any(char.isdigit() for char in token):
                tokens.add(token)
    return tokens


def has_phrase(normalized_text: str, *phrases: str) -> bool:
    return any(normalize_title(phrase) in normalized_text for phrase in phrases if phrase)


def list_strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [str(item).strip() for item in values if str(item).strip()]


def normalize_memory_value(text: Any) -> str:
    return re.sub(r"\s+", " ", clean_text(str(text or ""))).casefold()


def merge_unique_strings(existing: list[str], additions: list[str]) -> list[str]:
    merged = [item for item in existing if str(item).strip()]
    seen = {normalize_memory_value(item) for item in merged}
    for item in additions:
        value = clean_text(str(item or ""))
        if not value:
            continue
        key = normalize_memory_value(value)
        if key in seen:
            continue
        seen.add(key)
        merged.append(value)
    return merged


def split_topic_candidates(text: str) -> list[str]:
    if not text:
        return []
    parts = re.split(r"\s*(?:,|，|;|；|\band\b|与|和|以及|\bplus\b)\s*", text, flags=re.IGNORECASE)
    return [part for part in parts if clean_text(part)]


def normalize_topic_label(text: str) -> str:
    value = clean_text(text).strip(" ,，。.;；:：()[]{}\"'")
    value = re.sub(r"^(?:关于|做|研究|方向|主题|topic(?:s)?|focus(?:ing)? on|working on)\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"(?:方面|方向|主题)$", "", value)
    for token, replacement in {
        "vla": "VLA",
        "vlm": "VLM",
        "wbc": "WBC",
        "gr00t": "GR00T",
        "g1": "G1",
        "pi0": "PI0",
        "pi05": "PI0.5",
    }.items():
        value = re.sub(rf"\b{token}\b", replacement, value, flags=re.IGNORECASE)
    return clean_text(value).strip()


def merge_text_value(existing: Any, addition: str) -> str:
    current = clean_text(str(existing or ""))
    incoming = clean_text(addition)
    if not incoming:
        return current
    if not current:
        return incoming
    current_norm = normalize_memory_value(current)

    def covered(part: str) -> bool:
        normalized = normalize_memory_value(part)
        if not normalized:
            return True
        if normalized in current_norm:
            return True
        anchors = [
            token
            for token in re.findall(r"[a-z0-9]+", normalized)
            if token
            not in {
                "access",
                "to",
                "ample",
                "nvidia",
                "gpus",
                "gpu",
                "rtx",
                "robot",
                "humanoid",
                "workstation",
                "platform",
            }
        ]
        return bool(anchors) and all(token in current_norm for token in anchors)

    new_parts = [part.strip() for part in incoming.split(";") if part.strip()]
    uncovered = [part for part in new_parts if not covered(part)]
    if not uncovered:
        return current
    return f"{current}; {'; '.join(uncovered)}"


def summarize_resources(resources: list[str], *, kinds: tuple[str, ...]) -> str:
    selected: list[str] = []
    for resource in resources:
        lowered = resource.casefold()
        if "robot" in lowered or "humanoid" in lowered:
            resource_kind = "hardware"
        elif "dataset" in lowered or "data" in lowered or "demo" in lowered:
            resource_kind = "data"
        else:
            resource_kind = "compute"
        if resource_kind in kinds:
            selected.append(resource)
    return "; ".join(selected)


def has_stable_memory_cue(statement: str) -> bool:
    normalized = clean_text(statement).casefold()
    return any(cue in normalized for cue in STABLE_MEMORY_CUES)


def extract_language_preference(statement: str) -> str:
    raw = clean_text(statement)
    lowered = raw.casefold()
    if any(phrase in raw for phrase in ("中英双语", "双语")) or any(
        phrase in lowered for phrase in ("bilingual", "both chinese and english", "chinese and english")
    ):
        return "zh-CN/en-US"
    if any(phrase in raw for phrase in ("中文回复", "中文回答", "中文交流", "用中文", "默认中文", "中文为主")) or any(
        phrase in lowered for phrase in ("reply in chinese", "respond in chinese", "answer in chinese", "prefer chinese", "default to chinese")
    ):
        return "zh-CN"
    if any(phrase in raw for phrase in ("英文回复", "英语回复", "英文回答", "用英文", "默认英文", "英语交流")) or any(
        phrase in lowered for phrase in ("reply in english", "respond in english", "answer in english", "prefer english", "default to english")
    ):
        return "en-US"
    return ""


def extract_risk_preference(statement: str) -> str:
    raw = clean_text(statement)
    lowered = raw.casefold()
    if any(phrase in raw for phrase in ("高风险高回报", "激进", "冒险", "大胆一些", "更激进")) or any(
        phrase in lowered for phrase in ("high risk", "high-risk", "aggressive", "risk seeking", "higher risk")
    ):
        return "aggressive"
    if any(phrase in raw for phrase in ("保守", "稳妥", "稳健", "谨慎", "别太冒险", "不要太冒险")) or any(
        phrase in lowered for phrase in ("conservative", "risk averse", "risk-averse", "low risk", "safer")
    ):
        return "conservative"
    if any(phrase in raw for phrase in ("平衡", "折中")) or any(
        phrase in lowered for phrase in ("balanced", "middle ground", "moderate risk")
    ):
        return "balanced"
    return ""


def extract_long_term_topics(statement: str) -> list[str]:
    raw = clean_text(statement)
    topic_segments: list[str] = []
    patterns = [
        r"(?:长期研究方向(?:是|包括)?|长期方向(?:是|包括)?|长期想做|长期关注|长期重点(?:做|是)?|想长期做|未来想做|接下来主要做)\s*(.+)",
        r"(?:long[- ]term (?:topics?|focus|direction)s?(?:\s+(?:is|are))?|long[- ]term interest(?:s)?(?:\s+(?:is|are))?|want to work on long[- ]term)\s+(.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, raw, flags=re.IGNORECASE)
        if not match:
            continue
        tail = clean_text(match.group(1))
        stop = re.split(r"[。.!?？；;]", tail, maxsplit=1)[0]
        topic_segments.extend(split_topic_candidates(stop))

    normalized = [normalize_topic_label(item) for item in topic_segments]
    filtered = [item for item in normalized if item and len(item) >= 2]
    return merge_unique_strings([], filtered)


def extract_resource_facts(statement: str) -> list[str]:
    raw = clean_text(statement)
    lowered = raw.casefold()
    resources: list[str] = []
    availability_hint = any(cue in lowered for cue in RESOURCE_AVAILABILITY_CUES)
    topic_hint = any(cue in lowered for cue in ("long term", "long-term", "focus", "方向", "长期", "想做", "关注"))

    for match in re.finditer(r"(?<![a-z0-9])(?:rtx\s*)?((?:20|30|40|50)\d{2})(?![a-z0-9])", lowered, flags=re.IGNORECASE):
        model = match.group(1).upper()
        label = f"RTX {model} workstation" if ("workstation" in lowered or "工作站" in raw) else f"RTX {model} GPU"
        resources.append(label)

    for accelerator in ("H100", "H200", "A100", "A800", "L40S", "B200"):
        if re.search(rf"(?<![a-z0-9]){accelerator}(?![a-z0-9])", lowered, flags=re.IGNORECASE):
            label = f"NVIDIA {accelerator} GPUs"
            if any(cue in raw for cue in ABUNDANT_ACCESS_CUES) or any(cue in lowered for cue in ABUNDANT_ACCESS_CUES):
                label = f"Access to ample NVIDIA {accelerator} GPUs"
            resources.append(label)

    if re.search(r"(?<![a-z0-9])g1(?![a-z0-9])", lowered, flags=re.IGNORECASE) and (
        "unitree" in lowered or "宇树" in raw or "机器人" in raw or "robot" in lowered or "humanoid" in lowered or "人形" in raw
    ) and (availability_hint or not topic_hint):
        resources.append("Unitree G1 humanoid robot")
    elif ("人形机器人" in raw or "humanoid robot" in lowered) and availability_hint:
        resources.append("humanoid robot platform")

    return merge_unique_strings([], resources)


def update_charter_constraints(project_root: Path, program_id: str, updates: dict[str, str], *, apply_changes: bool = True) -> list[str]:
    if not program_id:
        return []
    program_root = existing_program_root(project_root, program_id)
    charter_path = program_root / "charter.yaml"
    payload = load_yaml(charter_path, default={})
    if not isinstance(payload, dict):
        payload = {}
    payload.setdefault("constraints", {})
    if not isinstance(payload["constraints"], dict):
        payload["constraints"] = {}

    changed_fields: list[str] = []
    for field, addition in updates.items():
        if field not in {"compute", "hardware", "data"}:
            continue
        merged = merge_text_value(payload["constraints"].get(field, ""), addition)
        if merged != str(payload["constraints"].get(field, "") or ""):
            payload["constraints"][field] = merged
            changed_fields.append(field)

    if changed_fields and apply_changes:
        write_yaml_if_changed(charter_path, payload)
    return changed_fields


def capture_memory(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")

    statement = clean_text(args.statement)
    resources = extract_resource_facts(statement)
    language_preference = extract_language_preference(statement)
    risk_preference = extract_risk_preference(statement)
    long_term_topics = extract_long_term_topics(statement)
    if not any([resources, language_preference, risk_preference, long_term_topics]):
        print("[ok] no stable memory facts recognized")
        print("captured: false")
        return 0

    profile_path = research_root(project_root) / "memory" / "user-profile.yaml"
    profile = load_yaml(profile_path, default={})
    if not isinstance(profile, dict):
        profile = {**yaml_default("user-profile", "research-conductor", status="active")}
    profile.setdefault("constraints", {})
    if not isinstance(profile["constraints"], dict):
        profile["constraints"] = {"compute": "", "data": "", "hardware": ""}
    profile.setdefault("available_resources", [])
    if not isinstance(profile["available_resources"], list):
        profile["available_resources"] = []

    profile_fields: list[str] = []
    merged_resources = merge_unique_strings(list_strings(profile.get("available_resources")), resources)
    if merged_resources != list_strings(profile.get("available_resources")):
        profile["available_resources"] = merged_resources
        profile_fields.append("available_resources")

    compute_summary = summarize_resources(resources, kinds=("compute",))
    if compute_summary:
        merged_compute = merge_text_value(profile["constraints"].get("compute", ""), compute_summary)
        if merged_compute != str(profile["constraints"].get("compute", "") or ""):
            profile["constraints"]["compute"] = merged_compute
            profile_fields.append("constraints.compute")

    hardware_summary = summarize_resources(resources, kinds=("hardware",))
    if hardware_summary:
        merged_hardware = merge_text_value(profile["constraints"].get("hardware", ""), hardware_summary)
        if merged_hardware != str(profile["constraints"].get("hardware", "") or ""):
            profile["constraints"]["hardware"] = merged_hardware
            profile_fields.append("constraints.hardware")

    data_summary = summarize_resources(resources, kinds=("data",))
    if data_summary:
        merged_data = merge_text_value(profile["constraints"].get("data", ""), data_summary)
        if merged_data != str(profile["constraints"].get("data", "") or ""):
            profile["constraints"]["data"] = merged_data
            profile_fields.append("constraints.data")

    if language_preference and language_preference != str(profile.get("language_preference", "") or ""):
        profile["language_preference"] = language_preference
        profile_fields.append("language_preference")

    if risk_preference and risk_preference != str(profile.get("risk_preference", "") or ""):
        profile["risk_preference"] = risk_preference
        profile_fields.append("risk_preference")

    profile.setdefault("long_term_topics", [])
    if not isinstance(profile["long_term_topics"], list):
        profile["long_term_topics"] = []
    merged_topics = merge_unique_strings(list_strings(profile.get("long_term_topics")), long_term_topics)
    if merged_topics != list_strings(profile.get("long_term_topics")):
        profile["long_term_topics"] = merged_topics
        profile_fields.append("long_term_topics")

    program_updates = {
        field: summary
        for field, summary in (
            ("compute", compute_summary),
            ("hardware", hardware_summary),
            ("data", data_summary),
        )
        if summary
    }
    program_fields = (
        update_charter_constraints(project_root, args.program_id, program_updates, apply_changes=not args.dry_run)
        if args.program_id
        else []
    )

    if args.dry_run:
        print("[ok] analyzed memory statement")
        print(f"stable_cue: {str(has_stable_memory_cue(statement)).lower()}")
        print(f"resources: {', '.join(resources)}")
        print(f"language_preference: {language_preference or 'none'}")
        print(f"risk_preference: {risk_preference or 'none'}")
        print(f"long_term_topics: {', '.join(long_term_topics) if long_term_topics else 'none'}")
        print(f"profile_fields: {', '.join(profile_fields) if profile_fields else 'none'}")
        print(f"program_fields: {', '.join(program_fields) if program_fields else 'none'}")
        print("captured: false")
        return 0

    if not profile_fields and not program_fields:
        print("[ok] no new memory updates were needed")
        print(f"resources: {', '.join(resources)}")
        print(f"language_preference: {language_preference or 'none'}")
        print(f"risk_preference: {risk_preference or 'none'}")
        print(f"long_term_topics: {', '.join(long_term_topics) if long_term_topics else 'none'}")
        print("captured: false")
        return 0

    if profile_fields:
        profile["generated_at"] = utc_now_iso()
        write_yaml_if_changed(profile_path, profile)

    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "memory-captured",
            "source": args.source,
            "statement": compact_text(statement, max_chars=240),
            "stable_cue": has_stable_memory_cue(statement),
            "resources": resources,
            "language_preference": language_preference,
            "risk_preference": risk_preference,
            "long_term_topics": long_term_topics,
            "profile_fields": profile_fields,
            "program_id": args.program_id,
            "program_fields": [f"constraints.{field}" for field in program_fields],
        },
    )

    print("[ok] captured stable memory")
    print(f"resources: {', '.join(resources)}")
    print(f"language_preference: {language_preference or 'none'}")
    print(f"risk_preference: {risk_preference or 'none'}")
    print(f"long_term_topics: {', '.join(long_term_topics) if long_term_topics else 'none'}")
    print(f"profile_fields: {', '.join(profile_fields) if profile_fields else 'none'}")
    print(f"program_fields: {', '.join(program_fields) if program_fields else 'none'}")
    print("captured: true")
    return 0


def load_program_context(project_root: Path, program_id: str) -> dict[str, Any]:
    program_root = existing_program_root(project_root, program_id)
    charter = load_yaml(program_root / "charter.yaml", default={})
    state = load_yaml(program_root / "workflow" / "state.yaml", default={})
    literature_map = load_yaml(program_root / "evidence" / "literature-map.yaml", default={})
    repo_choice = load_yaml(program_root / "design" / "repo-choice.yaml", default={})
    selected_idea = load_yaml(program_root / "design" / "selected-idea.yaml", default={})
    interfaces = load_yaml(program_root / "design" / "interfaces.yaml", default={})
    experiments = load_yaml(program_root / "experiments" / "matrix.yaml", default={})
    open_questions = load_list_document(
        program_root / "workflow" / "open-questions.yaml",
        f"{program_id}-open-questions",
        "research-conductor",
    )
    evidence_requests = load_list_document(
        program_root / "workflow" / "evidence-requests.yaml",
        f"{program_id}-evidence-requests",
        "research-conductor",
    )

    retrieval = literature_map.get("retrieval", {}) if isinstance(literature_map, dict) else {}
    selected_sources = retrieval.get("selected_sources", []) if isinstance(retrieval, dict) else []
    linked_lit_ids = {
        item.split(":", 1)[1]
        for item in list_strings((literature_map or {}).get("inputs"))
        if item.startswith("lit:")
    }
    topic_pool: set[str] = set()
    tag_pool: set[str] = set()
    for item in selected_sources if isinstance(selected_sources, list) else []:
        if not isinstance(item, dict):
            continue
        source_id = str(item.get("source_id") or "").strip()
        if source_id:
            linked_lit_ids.add(source_id)
        topic_pool.update(list_strings(item.get("topics")))
        tag_pool.update(list_strings(item.get("tags")))

    linked_repo_ids = set()
    if isinstance(repo_choice, dict):
        selected_repo = str(repo_choice.get("selected_repo") or "").strip()
        if selected_repo:
            linked_repo_ids.add(selected_repo)
        linked_repo_ids.update(list_strings(repo_choice.get("alternatives")))
        for item in repo_choice.get("candidate_repos", []) if isinstance(repo_choice.get("candidate_repos"), list) else []:
            if isinstance(item, dict):
                repo_id = str(item.get("repo_id") or "").strip()
                if repo_id:
                    linked_repo_ids.add(repo_id)
    if isinstance(state, dict):
        state_repo_id = str(state.get("selected_repo_id") or "").strip()
        if state_repo_id:
            linked_repo_ids.add(state_repo_id)

    keyword_pool = set()
    if isinstance(retrieval, dict):
        for query_term in list_strings(retrieval.get("query_terms")):
            keyword_pool.update(report_tokens(query_term))
        for query_tag in list_strings(retrieval.get("query_tags")):
            keyword_pool.update(report_tokens(query_tag))

    charter_question = str((charter or {}).get("question") or "")
    charter_goal = str((charter or {}).get("goal") or "")
    keyword_pool.update(report_tokens(charter_question, charter_goal))
    keyword_pool.update(report_tokens((selected_idea or {}).get("title"), (repo_choice or {}).get("selection_reason")))
    keyword_pool.update(
        query_keyword_terms(
            " ".join(part for part in [charter_question, charter_goal] if part).strip(),
            stopwords={"that", "with", "from", "into"},
            project_root=project_root,
        )
    )

    return {
        "program_root": program_root,
        "charter": charter if isinstance(charter, dict) else {},
        "state": state if isinstance(state, dict) else {},
        "literature_map": literature_map if isinstance(literature_map, dict) else {},
        "repo_choice": repo_choice if isinstance(repo_choice, dict) else {},
        "selected_idea": selected_idea if isinstance(selected_idea, dict) else {},
        "interfaces": interfaces if isinstance(interfaces, dict) else {},
        "experiments": experiments if isinstance(experiments, dict) else {},
        "open_questions": open_questions,
        "evidence_requests": evidence_requests,
        "linked_lit_ids": linked_lit_ids,
        "linked_repo_ids": linked_repo_ids,
        "topic_pool": topic_pool,
        "tag_pool": tag_pool,
        "keyword_pool": keyword_pool,
    }


def paper_profile(record: dict[str, Any]) -> dict[str, str]:
    text = normalize_title(
        " ".join(
            [
                str(record.get("canonical_title") or ""),
                str(record.get("short_summary") or ""),
                str(record.get("abstract") or ""),
                " ".join(list_strings(record.get("topics"))),
                " ".join(list_strings(record.get("tags"))),
            ]
        )
    )
    if has_phrase(text, "humanoid"):
        embodiment = "humanoid"
    elif has_phrase(text, "mobile manipulation", "loco manipulation"):
        embodiment = "mobile manipulation"
    elif has_phrase(text, "industrial"):
        embodiment = "industrial"
    elif has_phrase(text, "survey", "anatomy"):
        embodiment = "survey / landscape"
    else:
        embodiment = "general manipulation"

    if has_phrase(text, "survey", "anatomy", "readiness assessment"):
        mode = "survey / assessment"
    elif has_phrase(text, "memory", "episodic", "declarative memory"):
        mode = "memory-aware policy"
    elif has_phrase(text, "hierarchical", "latent", "interface", "tokenization"):
        mode = "structured / latent interface"
    elif has_phrase(text, "end to end", "language action model", "directly maps"):
        mode = "end-to-end policy"
    elif has_phrase(text, "benchmark", "dataset", "demonstration", "demonstrations"):
        mode = "data / benchmark"
    else:
        mode = "general VLA / control"
    return {"embodiment": embodiment, "mode": mode}


def repo_profile(record: dict[str, Any]) -> dict[str, str]:
    text = normalize_title(
        " ".join(
            [
                str(record.get("repo_name") or ""),
                str(record.get("short_summary") or ""),
                " ".join(list_strings(record.get("topics"))),
                " ".join(list_strings(record.get("tags"))),
                " ".join(list_strings(record.get("frameworks"))),
                " ".join(list_strings(record.get("entrypoints"))),
            ]
        )
    )
    if has_phrase(
        text,
        "gear sonic",
        "teleop",
        "runtime",
        "neural wbc",
        "deployment utilities",
        "deploy_g1",
        "unitree",
    ):
        role = "WBC / runtime backend"
    elif has_phrase(
        text,
        "vision language action",
        "vla",
        "gr00t",
        "transformers",
        "lerobot",
        "foundation model",
        "language directed",
        "promptable behavioral foundation model",
    ):
        role = "high-level VLA host"
    elif has_phrase(text, "demonstration", "demonstrations", "video", "imitation", "human demonstrations"):
        role = "data / demo learning stack"
    else:
        role = "general robotics stack"

    entrypoints = list_strings(record.get("entrypoints"))
    coverage_bits: list[str] = []
    if any(has_phrase(normalize_title(path), "train", "finetune", "launch_train") for path in entrypoints) or has_phrase(text, "training", "train"):
        coverage_bits.append("train")
    if any(has_phrase(normalize_title(path), "eval", "benchmark", "rollout", "test") for path in entrypoints) or has_phrase(text, "evaluation", "eval"):
        coverage_bits.append("eval")
    if any(has_phrase(normalize_title(path), "deploy", "server", "real robot", "onnx", "tensorrt") for path in entrypoints) or has_phrase(text, "deployment", "real world", "real robot"):
        coverage_bits.append("deploy")
    coverage = ", ".join(coverage_bits) if coverage_bits else "unclear"
    return {"role": role, "coverage": coverage}


def paper_relevance(record: dict[str, Any], context: dict[str, Any]) -> tuple[int, list[str]]:
    source_id = str(record.get("id") or "").strip()
    reasons: list[str] = []
    score = 0
    if source_id and source_id in context["linked_lit_ids"]:
        score += 30
        reasons.append("already linked in the current literature map")

    record_topics = set(list_strings(record.get("topics")))
    record_tags = set(list_strings(record.get("tags")))
    topic_overlap = sorted(record_topics & context["topic_pool"])
    tag_overlap = sorted(record_tags & context["tag_pool"])
    if topic_overlap:
        score += 6 * len(topic_overlap)
        reasons.append(f"topic overlap: {', '.join(topic_overlap[:3])}")
    if tag_overlap:
        score += 3 * len(tag_overlap)
        reasons.append(f"tag overlap: {', '.join(tag_overlap[:3])}")

    text_tokens = report_tokens(
        record.get("canonical_title"),
        record.get("short_summary"),
        " ".join(record_topics),
        " ".join(record_tags),
    )
    token_overlap = sorted(text_tokens & context["keyword_pool"])
    if token_overlap:
        score += min(len(token_overlap), 10)
        reasons.append(f"keyword overlap: {', '.join(token_overlap[:4])}")

    profile = paper_profile(record)
    if profile["embodiment"] == "humanoid":
        score += 2
    if profile["mode"] in {"structured / latent interface", "memory-aware policy", "end-to-end policy"}:
        score += 2
    return score, reasons


def repo_relevance(record: dict[str, Any], context: dict[str, Any]) -> tuple[int, list[str]]:
    repo_id = str(record.get("repo_id") or record.get("id") or "").strip()
    reasons: list[str] = []
    score = 0
    if repo_id and repo_id in context["linked_repo_ids"]:
        score += 30
        reasons.append("already referenced by the current design pack")

    record_topics = set(list_strings(record.get("topics")))
    record_tags = set(list_strings(record.get("tags")))
    topic_overlap = sorted(record_topics & context["topic_pool"])
    tag_overlap = sorted(record_tags & context["tag_pool"])
    if topic_overlap:
        score += 6 * len(topic_overlap)
        reasons.append(f"topic overlap: {', '.join(topic_overlap[:3])}")
    if tag_overlap:
        score += 3 * len(tag_overlap)
        reasons.append(f"tag overlap: {', '.join(tag_overlap[:3])}")

    text_tokens = report_tokens(
        record.get("repo_name"),
        record.get("short_summary"),
        " ".join(record_topics),
        " ".join(record_tags),
        " ".join(list_strings(record.get("frameworks"))),
        " ".join(list_strings(record.get("entrypoints"))),
    )
    token_overlap = sorted(text_tokens & context["keyword_pool"])
    if token_overlap:
        score += min(len(token_overlap), 10)
        reasons.append(f"keyword overlap: {', '.join(token_overlap[:4])}")

    profile = repo_profile(record)
    if profile["role"] in {"high-level VLA host", "WBC / runtime backend"}:
        score += 3
    return score, reasons


def fit_label(score: int) -> str:
    if score >= 30:
        return "high"
    if score >= 16:
        return "medium"
    if score >= 8:
        return "watch"
    return "background"


def paper_fit_reason(record: dict[str, Any], context: dict[str, Any], reasons: list[str]) -> str:
    profile = paper_profile(record)
    source_id = str(record.get("id") or "")
    if source_id in context["linked_lit_ids"]:
        return f"Already in the literature map; adds a {profile['mode']} angle to the current evidence base."
    if profile["mode"] == "memory-aware policy":
        return "Directly informs the program's long-horizon memory and recovery hypotheses."
    if profile["mode"] == "structured / latent interface":
        return "Useful for comparing explicit latent or interface-based control against direct action generation."
    if profile["mode"] == "end-to-end policy":
        return "Strong end-to-end baseline for testing whether the hierarchical interface actually earns its complexity."
    if profile["mode"] == "survey / assessment":
        return "Good for gap-finding and benchmark coverage rather than as a direct implementation template."
    if reasons:
        return compact_text("; ".join(reasons), max_chars=180)
    return "Provides broader background context around the current humanoid VLA / WBC problem."


def repo_fit_reason(record: dict[str, Any], context: dict[str, Any], reasons: list[str]) -> str:
    profile = repo_profile(record)
    repo_id = str(record.get("repo_id") or record.get("id") or "")
    if repo_id in context["linked_repo_ids"]:
        return f"Already referenced by the design pack; serves as a {profile['role']} candidate."
    if profile["role"] == "high-level VLA host":
        return "Most relevant if the program keeps the VLA-host / WBC-backend decomposition."
    if profile["role"] == "WBC / runtime backend":
        return "Most relevant for low-level execution, deployment constraints, and sim-to-real integration."
    if profile["role"] == "data / demo learning stack":
        return "Useful for data collection or imitation-learning baselines rather than as the main host."
    if reasons:
        return compact_text("; ".join(reasons), max_chars=180)
    return "General background repo that may still provide implementation cues."


def load_recent_items(
    records: list[dict[str, Any]],
    *,
    window_start: datetime,
    window_end: datetime,
    scorer: Any,
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for record in records:
        generated_at = parse_iso_datetime(record.get("generated_at"))
        if not within_window(generated_at, window_start, window_end):
            continue
        score, reasons = scorer(record, context)
        ranked.append(
            {
                "record": record,
                "generated_at": generated_at,
                "score": score,
                "reasons": reasons,
            }
        )
    ranked.sort(
        key=lambda item: (
            -item["score"],
            item["generated_at"].isoformat() if item["generated_at"] else "",
            str(item["record"].get("id") or item["record"].get("repo_id") or ""),
        ),
        reverse=False,
    )
    ranked.sort(key=lambda item: (-item["score"], item["generated_at"] or datetime.min.replace(tzinfo=timezone.utc)))
    return ranked


def rank_items_for_query(
    records: list[dict[str, Any]],
    *,
    scorer: Any,
    context: dict[str, Any],
    limit: int,
) -> list[dict[str, Any]]:
    ranked: list[dict[str, Any]] = []
    for record in records:
        score, reasons = scorer(record, context)
        if score <= 0:
            continue
        ranked.append(
            {
                "record": record,
                "generated_at": parse_iso_datetime(record.get("generated_at")),
                "score": score,
                "reasons": reasons,
            }
        )
    ranked.sort(
        key=lambda item: (
            -item["score"],
            item["generated_at"] or datetime.min.replace(tzinfo=timezone.utc),
            str(item["record"].get("id") or item["record"].get("repo_id") or ""),
        ),
    )
    return ranked[: max(limit, 0)]


def parse_decision_log_entries(program_root: Path) -> list[dict[str, Any]]:
    path = program_root / "workflow" / "decision-log.md"
    if not path.exists():
        return []
    entries: list[dict[str, Any]] = []
    pattern = re.compile(r"^- (.+?):(?: \[(.+?)\])? (.+)$")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.match(line.strip())
        if not match:
            continue
        timestamp = parse_iso_datetime(match.group(1))
        entries.append(
            {
                "timestamp": timestamp,
                "stage": (match.group(2) or "").strip(),
                "summary": match.group(3).strip(),
            }
        )
    return entries


def load_program_history_events(project_root: Path, program_id: str) -> list[dict[str, Any]]:
    history_root = research_root(project_root) / "memory" / "history"
    events: list[dict[str, Any]] = []
    for history_path in sorted(history_root.glob("*.yaml")):
        payload = load_list_document(history_path, f"history-{history_path.stem}", "research-conductor")
        for item in payload.get("items", []):
            if not isinstance(item, dict):
                continue
            if str(item.get("program_id") or "").strip() != program_id:
                continue
            event = dict(item)
            event["timestamp_dt"] = parse_iso_datetime(item.get("timestamp"))
            events.append(event)
    events.sort(key=lambda item: item.get("timestamp_dt") or datetime.min.replace(tzinfo=timezone.utc))
    return events


def program_artifact_updates(context: dict[str, Any]) -> list[dict[str, Any]]:
    program_root = context["program_root"]
    updates: list[dict[str, Any]] = []
    candidates = [
        ("evidence/literature-map.yaml", context["literature_map"]),
        ("design/selected-idea.yaml", context["selected_idea"]),
        ("design/repo-choice.yaml", context["repo_choice"]),
        ("design/interfaces.yaml", context["interfaces"]),
        ("experiments/matrix.yaml", context["experiments"]),
        ("workflow/state.yaml", context["state"]),
    ]
    for rel_path, payload in candidates:
        if not isinstance(payload, dict) or not payload:
            continue
        timestamp = parse_iso_datetime(payload.get("generated_at"))
        if timestamp is None:
            continue
        description = ""
        if rel_path.endswith("literature-map.yaml"):
            retrieval = payload.get("retrieval", {})
            selected_sources = retrieval.get("selected_sources", []) if isinstance(retrieval, dict) else []
            description = f"Built the literature map with {len(selected_sources)} selected sources."
        elif rel_path.endswith("selected-idea.yaml"):
            description = f"Selected `{payload.get('idea_id') or 'n/a'}` for the first design pack."
        elif rel_path.endswith("repo-choice.yaml"):
            alternatives = list_strings(payload.get("alternatives"))
            description = (
                f"Chose `{payload.get('selected_repo') or 'n/a'}` as the main host"
                + (f" and kept `{alternatives[0]}` as the fallback/backend reference." if alternatives else ".")
            )
        elif rel_path.endswith("interfaces.yaml"):
            description = (
                f"Defined {len(list_strings(payload.get('new_modules')))} new modules, "
                f"{len(list_strings(payload.get('modified_modules')))} edit surfaces, "
                f"and {len(list_strings(payload.get('metrics')))} tracked metrics."
            )
        elif rel_path.endswith("matrix.yaml"):
            description = "Updated the experiment matrix."
        elif rel_path.endswith("state.yaml"):
            description = f"Workflow state now points to stage `{payload.get('stage') or 'n/a'}`."
        if description:
            updates.append(
                {
                    "timestamp": timestamp,
                    "source": rel_path,
                    "text": description,
                    "path": (program_root / rel_path).as_posix(),
                }
            )
    updates.sort(key=lambda item: item["timestamp"])
    return updates


def weekly_progress_items(project_root: Path, context: dict[str, Any], window_start: datetime, window_end: datetime) -> list[str]:
    items: list[tuple[datetime, str]] = []
    for event in load_program_history_events(project_root, str(context["state"].get("program_id") or context["charter"].get("program_id") or "")):
        timestamp = event.get("timestamp_dt")
        if not within_window(timestamp, window_start, window_end):
            continue
        event_type = str(event.get("type") or "").strip()
        if event_type == "stage-updated":
            items.append((timestamp, f"Workflow stage changed to `{event.get('stage') or 'n/a'}`."))
        elif event_type == "program-created":
            items.append((timestamp, "Program workspace was initialized."))
        elif event_type == "program-created-from-landscape":
            items.append((timestamp, f"Program was bootstrapped from landscape survey `{event.get('survey_id') or 'n/a'}`."))
        elif str(event.get("summary") or "").strip():
            items.append((timestamp, compact_text(str(event.get("summary") or "").strip(), max_chars=220)))
        elif event_type == "memory-captured":
            resources = list_strings(event.get("resources"))
            profile_fields = list_strings(event.get("profile_fields"))
            program_fields = list_strings(event.get("program_fields"))
            fragments: list[str] = []
            if resources:
                fragments.append(f"remembered resources `{', '.join(resources[:4])}`")
            if program_fields:
                fragments.append(f"updated program fields `{', '.join(program_fields)}`")
            if profile_fields:
                fragments.append(f"updated profile fields `{', '.join(profile_fields)}`")
            if fragments:
                items.append((timestamp, compact_text("Captured stable memory and " + "; ".join(fragments) + ".", max_chars=220)))

    for event in load_program_reporting_events(project_root, str(context["state"].get("program_id") or context["charter"].get("program_id") or "")):
        timestamp = event.get("timestamp_dt")
        if not within_window(timestamp, window_start, window_end):
            continue
        summary = compact_text(event.get("summary") or event.get("title") or "", max_chars=220)
        if summary:
            items.append((timestamp, summary))

    for entry in parse_decision_log_entries(context["program_root"]):
        timestamp = entry.get("timestamp")
        if within_window(timestamp, window_start, window_end):
            items.append((timestamp, entry["summary"]))

    for update in program_artifact_updates(context):
        if within_window(update["timestamp"], window_start, window_end):
            items.append((update["timestamp"], update["text"]))

    deduped: list[str] = []
    seen: set[str] = set()
    for timestamp, text in sorted(items, key=lambda item: item[0]):
        rendered = f"{timestamp.date().isoformat()}: {text}"
        if rendered not in seen:
            seen.add(rendered)
            deduped.append(rendered)
    return deduped


def current_issues(project_root: Path, context: dict[str, Any]) -> list[str]:
    issues: list[str] = []

    open_items = [item for item in context["open_questions"].get("items", []) if isinstance(item, dict) and str(item.get("status") or "open") == "open"]
    for item in open_items:
        issues.append(f"Open question `{item.get('question_id') or 'q'}`: {compact_text(item.get('question'), max_chars=180)}")

    evidence_items = [
        item
        for item in context["evidence_requests"].get("items", [])
        if isinstance(item, dict) and str(item.get("status") or "open") == "open"
    ]
    for item in evidence_items:
        issues.append(f"Evidence request `{item.get('request_id') or 'req'}`: {compact_text(item.get('blocking_reason'), max_chars=180)}")

    repo_choice = context["repo_choice"]
    for risk in list_strings(repo_choice.get("risks"))[:4]:
        issues.append(compact_text(f"Design risk: {risk}", max_chars=220))

    state = context["state"]
    selected_idea = context["selected_idea"]
    state_idea_id = str(state.get("selected_idea_id") or "").strip()
    design_idea_id = str(selected_idea.get("idea_id") or "").strip()
    if state_idea_id and design_idea_id and state_idea_id != design_idea_id:
        issues.append(
            "Workflow/design mismatch: "
            f"`workflow/state.yaml` points to `{state_idea_id}` while `design/selected-idea.yaml` still names `{design_idea_id}`."
        )

    state_repo_id = str(state.get("selected_repo_id") or "").strip()
    design_repo_id = str(repo_choice.get("selected_repo") or "").strip()
    if design_repo_id and state_repo_id != design_repo_id:
        issues.append(
            "Workflow/design mismatch: "
            f"`workflow/state.yaml` has selected repo `{state_repo_id or 'empty'}` but `design/repo-choice.yaml` selects `{design_repo_id}`."
        )

    history_events = load_program_history_events(project_root, str(state.get("program_id") or context["charter"].get("program_id") or ""))
    stage_events = [item for item in history_events if str(item.get("type") or "") == "stage-updated" and item.get("timestamp_dt")]
    if stage_events:
        latest_stage_event = stage_events[-1]
        latest_stage = str(latest_stage_event.get("stage") or "").strip()
        current_stage = str(state.get("stage") or "").strip()
        if latest_stage and current_stage and latest_stage != current_stage:
            issues.append(
                "Stage tracking mismatch: "
                f"latest remembered stage change is `{latest_stage}`, but `workflow/state.yaml` currently says `{current_stage}`."
            )

    if not open_items and not evidence_items:
        issues.append(
            "Tracking gap: `workflow/open-questions.yaml` and `workflow/evidence-requests.yaml` are both empty, so unresolved design questions are not yet durable."
        )

    deduped: list[str] = []
    seen: set[str] = set()
    for issue in issues:
        if issue not in seen:
            seen.add(issue)
            deduped.append(issue)
    return deduped


def recent_item_overview_lines(recent_papers: list[dict[str, Any]], recent_repos: list[dict[str, Any]]) -> list[str]:
    paper_modes = Counter(paper_profile(item["record"])["mode"] for item in recent_papers)
    repo_roles = Counter(repo_profile(item["record"])["role"] for item in recent_repos)
    lines: list[str] = []
    if paper_modes:
        top_modes = ", ".join(f"{mode} ({count})" for mode, count in paper_modes.most_common(3))
        lines.append(f"This week's paper intake is concentrated around {top_modes}.")
    if repo_roles:
        top_roles = ", ".join(f"{role} ({count})" for role, count in repo_roles.most_common(3))
        lines.append(f"This week's repo intake is concentrated around {top_roles}.")
    return lines


def paper_comparison_lines(recent_papers: list[dict[str, Any]]) -> list[str]:
    if not recent_papers:
        return ["No new literature landed in the selected window."]
    grouped: dict[str, list[str]] = {}
    for item in recent_papers:
        mode = paper_profile(item["record"])["mode"]
        grouped.setdefault(mode, []).append(str(item["record"].get("canonical_title") or item["record"].get("id") or "paper"))

    lines: list[str] = []
    if grouped.get("end-to-end policy") and grouped.get("structured / latent interface"):
        lines.append(
            "The batch now covers both direct language-to-action baselines and structured / latent interface papers, which maps cleanly onto the program's main architecture choice."
        )
    if grouped.get("memory-aware policy"):
        lines.append(
            "Memory-aware additions strengthen the case for keeping `scene_task_memory` and recovery logic in scope instead of treating the task as single-step control."
        )
    if grouped.get("survey / assessment"):
        lines.append(
            "Survey / assessment papers are useful for gap-finding and benchmark coverage, but they should not replace task-specific baselines in the design pack."
        )
    if grouped.get("data / benchmark"):
        lines.append(
            "Data / benchmark papers help with demonstration sources and evaluation framing, which matters because whole-body mobile manipulation can otherwise collapse into anecdotal demos."
        )
    if not lines:
        lines.append("Most papers in the batch cluster around similar VLA / humanoid control themes, so ranking by direct project fit matters more than raw novelty.")
    return lines


def repo_comparison_lines(recent_repos: list[dict[str, Any]], context: dict[str, Any]) -> list[str]:
    if not recent_repos:
        return ["No new repos landed in the selected window."]
    grouped: dict[str, list[str]] = {}
    for item in recent_repos:
        role = repo_profile(item["record"])["role"]
        grouped.setdefault(role, []).append(str(item["record"].get("repo_name") or item["record"].get("repo_id") or "repo"))

    lines: list[str] = []
    if grouped.get("high-level VLA host") and grouped.get("WBC / runtime backend"):
        lines.append(
            "The repo batch supports a clean split between a high-level VLA host and a low-level WBC/runtime backend, which matches the current design-pack decomposition."
        )
    if grouped.get("data / demo learning stack"):
        lines.append(
            "Data / demo learning repos broaden the baseline set, but they are better treated as supporting evidence or auxiliary pipelines than as the main integration host."
        )
    selected_repo = str(context["repo_choice"].get("selected_repo") or "").strip()
    if selected_repo and selected_repo in {str(item["record"].get("repo_id") or "") for item in recent_repos}:
        lines.append(
            f"`{selected_repo}` is still the most directly aligned high-level host inside this week's intake, but it needs explicit synchronization back into `workflow/state.yaml`."
        )
    if not lines:
        lines.append("Most repo additions are complementary rather than mutually exclusive, so the main comparison axis is host role and integration burden rather than raw capability alone.")
    return lines


def weekly_report_markdown(
    *,
    program_id: str,
    context: dict[str, Any],
    window_start: datetime,
    window_end: datetime,
    recent_papers: list[dict[str, Any]],
    recent_repos: list[dict[str, Any]],
    progress_items: list[str],
    issues: list[str],
    max_detailed_papers: int,
    max_detailed_repos: int,
) -> str:
    state = context["state"]
    selected_idea = context["selected_idea"]
    repo_choice = context["repo_choice"]
    interfaces = context["interfaces"]
    report_generated_at = utc_now_iso()

    lines = [
        f"# 周报 Weekly Report: `{program_id}`",
        "",
        f"- 时间窗口: `{report_window_label(window_start, window_end)}`",
        f"- 生成时间: `{report_generated_at}`",
        f"- 当前阶段: `{state.get('stage') or 'n/a'}`",
        f"- Workflow active idea: `{state.get('active_idea_id') or 'n/a'}`",
        f"- Workflow selected idea: `{state.get('selected_idea_id') or 'n/a'}`",
        f"- Design-pack selected idea: `{selected_idea.get('idea_id') or 'n/a'}`",
        f"- Workflow selected repo: `{state.get('selected_repo_id') or 'n/a'}`",
        f"- Design-pack selected repo: `{repo_choice.get('selected_repo') or 'n/a'}`",
        f"- 本窗口新增: `{len(recent_papers)}` 篇论文，`{len(recent_repos)}` 个 repo",
        "",
        "## 执行摘要 Executive Summary",
        "",
    ]
    summary_lines = recent_item_overview_lines(recent_papers, recent_repos)
    summary_lines.insert(
        0,
        "当前 program 仍处在设计阶段的反复收敛中：首版 design pack 已经存在，但 workflow state、历史阶段迁移和被选中的产物之间已经出现轻微漂移，需要继续收口。",
    )
    lines.extend(f"- {line}" for line in summary_lines)

    lines.extend(["", "## 项目进展 Project Progress", ""])
    if progress_items:
        lines.extend(f"- {item}" for item in progress_items)
    else:
        lines.append("- 所选时间窗口内没有检测到新的 program 产物更新。")

    lines.extend(["", "## 本周新增论文 New Literature This Week", ""])
    lines.append("| Added | Paper | Mode | Embodiment | Fit |")
    lines.append("| --- | --- | --- | --- | --- |")
    for item in recent_papers:
        record = item["record"]
        profile = paper_profile(record)
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(item["generated_at"].date().isoformat() if item["generated_at"] else "n/a"),
                    markdown_cell(record.get("canonical_title") or record.get("id") or "paper"),
                    markdown_cell(profile["mode"]),
                    markdown_cell(profile["embodiment"]),
                    markdown_cell(fit_label(item["score"])),
                ]
            )
            + " |"
        )

    lines.extend(["", "### 论文细节笔记 Detailed Literature Notes", ""])
    detailed_papers = recent_papers[:max_detailed_papers]
    if detailed_papers:
        for item in detailed_papers:
            record = item["record"]
            profile = paper_profile(record)
            lines.extend(
                [
                    f"#### `{record.get('canonical_title') or record.get('id') or 'paper'}`",
                    f"- Added: `{item['generated_at'].date().isoformat() if item['generated_at'] else 'n/a'}`",
                    f"- Fit: `{fit_label(item['score'])}`",
                    f"- Focus: `{profile['mode']}` on `{profile['embodiment']}` problems",
                    f"- 摘要 Summary: {compact_text(record.get('short_summary') or record.get('abstract') or '暂无摘要。', max_chars=320)}",
                    f"- Why it matters: {paper_fit_reason(record, context, item['reasons'])}",
                ]
            )
    else:
        lines.append("- 没有展开论文细节，因为本窗口内没有检测到新增论文。")

    lines.extend(["", "### 论文对比 Literature Comparison", ""])
    lines.extend(f"- {line}" for line in paper_comparison_lines(recent_papers))

    lines.extend(["", "## 本周新增 Repos New Repos This Week", ""])
    lines.append("| Added | Repo | Role | Coverage | Fit |")
    lines.append("| --- | --- | --- | --- | --- |")
    for item in recent_repos:
        record = item["record"]
        profile = repo_profile(record)
        lines.append(
            "| "
            + " | ".join(
                [
                    markdown_cell(item["generated_at"].date().isoformat() if item["generated_at"] else "n/a"),
                    markdown_cell(record.get("repo_name") or record.get("repo_id") or "repo"),
                    markdown_cell(profile["role"]),
                    markdown_cell(profile["coverage"]),
                    markdown_cell(fit_label(item["score"])),
                ]
            )
            + " |"
        )

    lines.extend(["", "### Repo 细节笔记 Detailed Repo Notes", ""])
    detailed_repos = recent_repos[:max_detailed_repos]
    if detailed_repos:
        for item in detailed_repos:
            record = item["record"]
            profile = repo_profile(record)
            lines.extend(
                [
                    f"#### `{record.get('repo_name') or record.get('repo_id') or 'repo'}`",
                    f"- Added: `{item['generated_at'].date().isoformat() if item['generated_at'] else 'n/a'}`",
                    f"- Fit: `{fit_label(item['score'])}`",
                    f"- Role: `{profile['role']}`",
                    f"- Coverage: `{profile['coverage']}`",
                    f"- 摘要 Summary: {compact_text(record.get('short_summary') or '暂无摘要。', max_chars=320)}",
                    f"- Why it matters: {repo_fit_reason(record, context, item['reasons'])}",
                ]
            )
    else:
        lines.append("- 没有展开 repo 细节，因为本窗口内没有检测到新增 repo。")

    lines.extend(["", "### Repo 对比 Repo Comparison", ""])
    lines.extend(f"- {line}" for line in repo_comparison_lines(recent_repos, context))

    lines.extend(["", "## 当前问题 Current Issues", ""])
    if issues:
        lines.extend(f"- {issue}" for issue in issues)
    else:
        lines.append("- 当前 workflow 文件里没有检测到显式 open issues。")

    if isinstance(interfaces, dict) and interfaces:
        lines.extend(
            [
                "",
                "## 已经落盘的实现信号 Implementation Signals Already Captured",
                "",
                f"- New modules already specified: `{', '.join(list_strings(interfaces.get('new_modules'))[:6]) or 'n/a'}`",
                f"- Modified surfaces already specified: `{', '.join(list_strings(interfaces.get('modified_modules'))[:5]) or 'n/a'}`",
                f"- Metrics already specified: `{', '.join(list_strings(interfaces.get('metrics'))[:6]) or 'n/a'}`",
            ]
        )

    return "\n".join(lines).rstrip() + "\n"


def query_program(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")

    question = clean_text(args.question)
    if not question:
        raise SystemExit("--question cannot be empty")

    context = load_program_context(project_root, args.program_id)
    query_terms = query_keyword_terms(
        question,
        stopwords={"question", "program", "analysis", "about", "please"},
        project_root=project_root,
    )
    query_context = dict(context)
    query_context["keyword_pool"] = set(context.get("keyword_pool", set()))
    query_context["keyword_pool"].update(report_tokens(question))
    query_context["keyword_pool"].update(query_terms)

    paper_hits = rank_items_for_query(
        load_literature_records(project_root),
        scorer=paper_relevance,
        context=query_context,
        limit=args.max_papers,
    )
    repo_hits = rank_items_for_query(
        load_repo_summaries(project_root),
        scorer=repo_relevance,
        context=query_context,
        limit=args.max_repos,
    )

    top_paper_ids = [
        str(item["record"].get("id") or "").strip()
        for item in paper_hits
        if str(item["record"].get("id") or "").strip()
    ]
    top_repo_ids = [
        str(item["record"].get("repo_id") or item["record"].get("id") or "").strip()
        for item in repo_hits
        if str(item["record"].get("repo_id") or item["record"].get("id") or "").strip()
    ]
    stage = str(context.get("state", {}).get("stage") or "").strip()

    lines = [
        f"## Query",
        f"- Program: `{args.program_id}`",
        f"- Question: {question}",
        f"- Stage: `{stage or 'unknown'}`",
        f"- Query terms: `{', '.join(query_terms) if query_terms else 'n/a'}`",
        "",
        "## Synthesis",
        "",
        (
            f"Top signals suggest {len(paper_hits)} literature hits and {len(repo_hits)} repo hits relevant to this question. "
            "Use the highest-fit entries below as immediate evidence, and trigger literature-scout if freshness is uncertain."
        ),
        "",
        "## Literature Evidence",
    ]
    if paper_hits:
        for item in paper_hits:
            record = item["record"]
            source_id = str(record.get("id") or "").strip() or "unknown-lit"
            title = str(record.get("canonical_title") or source_id)
            reason = paper_fit_reason(record, query_context, item["reasons"])
            lines.append(
                f"- `{source_id}` ({fit_label(item['score'])} fit): {title}. Why: {compact_text(reason, max_chars=220)}"
            )
    else:
        lines.append("- No high-confidence literature hits found from current canonical metadata.")

    lines.extend(["", "## Repository Evidence"])
    if repo_hits:
        for item in repo_hits:
            record = item["record"]
            repo_id = str(record.get("repo_id") or record.get("id") or "").strip() or "unknown-repo"
            name = str(record.get("repo_name") or repo_id)
            reason = repo_fit_reason(record, query_context, item["reasons"])
            lines.append(f"- `{repo_id}` ({fit_label(item['score'])} fit): {name}. Why: {compact_text(reason, max_chars=220)}")
    else:
        lines.append("- No high-confidence repository hits found from current canonical metadata.")

    lines.extend(
        [
            "",
            "## Follow-ups",
            "- If the answer depends on the latest papers, run literature-scout and ingest new candidates before committing design decisions.",
            "- Promote this query result into a durable artifact so future sessions can reuse it directly.",
            "",
        ]
    )
    result_markdown = "\n".join(lines)

    artifact_path: Path | None = None
    if not args.no_save:
        artifact_path = write_query_artifact(
            project_root,
            query_text=question,
            result_markdown=result_markdown,
            title=args.title or f"{args.program_id} query",
            query_type="query",
            metadata={
                "program_id": args.program_id,
                "stage": stage,
                "paper_ids": top_paper_ids,
                "repo_ids": top_repo_ids,
            },
            generated_by="research-conductor",
        )
    else:
        append_wiki_log_event(
            project_root,
            "query",
            args.title or f"{args.program_id} ad-hoc query",
            summary=question,
            metadata={
                "program_id": args.program_id,
                "stage": stage,
                "paper_ids": top_paper_ids,
                "repo_ids": top_repo_ids,
                "saved_artifact": False,
            },
            generated_by="research-conductor",
        )

    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "program-query-executed",
            "program_id": args.program_id,
            "question": compact_text(question, max_chars=220),
            "artifact_path": artifact_path.relative_to(project_root).as_posix() if artifact_path else "",
            "paper_ids": top_paper_ids,
            "repo_ids": top_repo_ids,
        },
    )
    append_program_reporting_event(
        project_root,
        args.program_id,
        {
            "source_skill": "research-conductor",
            "event_type": "program-query-recorded",
            "title": args.title or "Program query recorded",
            "summary": (
                f"Answered program query with {len(top_paper_ids)} literature references and {len(top_repo_ids)} repo references."
            ),
            "artifacts": [artifact_path.relative_to(project_root).as_posix()] if artifact_path else [],
            "paper_ids": top_paper_ids,
            "repo_ids": top_repo_ids,
            "stage": stage,
            "tags": query_terms[:8],
        },
        generated_by="research-conductor",
    )

    print(result_markdown)
    if artifact_path:
        print(f"[ok] wrote query artifact to {artifact_path.as_posix()}")
    return 0


def lint_workspace(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")

    report_path = lint_wiki_workspace(project_root, generated_by="research-conductor")
    report_text = report_path.read_text(encoding="utf-8", errors="ignore")
    status_match = re.search(r"^- status:\s*(.+)$", report_text, flags=re.MULTILINE)
    issues_match = re.search(r"^- total_issues:\s*(\d+)$", report_text, flags=re.MULTILINE)
    status = (status_match.group(1).strip() if status_match else "UNKNOWN").upper()
    issue_count = int(issues_match.group(1)) if issues_match else 0

    append_wiki_log_event(
        project_root,
        "lint",
        "Workspace lint pass",
        summary=f"status={status}, total_issues={issue_count}",
        metadata={"report_path": report_path.relative_to(project_root).as_posix()},
        generated_by="research-conductor",
    )
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "workspace-linted",
            "status": status,
            "issue_count": issue_count,
            "report_path": report_path.relative_to(project_root).as_posix(),
        },
    )

    print(f"[ok] wrote lint report to {report_path.as_posix()}")
    print(f"status: {status}")
    print(f"issues: {issue_count}")
    if args.strict and status != "PASS":
        return 1
    return 0


def rebuild_wiki_index(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    index_path = rebuild_wiki_index_markdown(project_root)
    append_wiki_log_event(
        project_root,
        "index",
        "Wiki index rebuilt",
        metadata={"index_path": index_path.relative_to(project_root).as_posix()},
        generated_by="research-conductor",
    )
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "wiki-index-rebuilt",
            "index_path": index_path.relative_to(project_root).as_posix(),
        },
    )
    print(f"[ok] rebuilt wiki index at {index_path.as_posix()}")
    return 0


def repair_program_files(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    programs_root = research_root(project_root) / "programs"
    if not programs_root.exists():
        print("[ok] no programs found")
        return 0

    available_ids = sorted(path.name for path in programs_root.iterdir() if path.is_dir() and not path.name.startswith("."))
    target_ids = args.program_id if args.program_id else available_ids
    created_paths: list[str] = []
    missing_targets: list[str] = []

    for program_id in target_ids:
        program_root = programs_root / program_id
        if not program_root.exists():
            missing_targets.append(program_id)
            continue
        workflow_root = program_root / "workflow"
        workflow_root.mkdir(parents=True, exist_ok=True)
        reporting_path = program_reporting_events_path(project_root, program_id)
        if not reporting_path.exists():
            write_yaml_if_changed(reporting_path, blank_reporting_events(program_id, generated_by="research-conductor"))
            created_paths.append(reporting_path.relative_to(project_root).as_posix())

    index_path = rebuild_wiki_index_markdown(project_root)
    append_wiki_log_event(
        project_root,
        "repair",
        "Program workflow repair",
        summary=f"Created {len(created_paths)} missing reporting-events files.",
        metadata={
            "created_paths": created_paths,
            "missing_targets": missing_targets,
            "index_path": index_path.relative_to(project_root).as_posix(),
        },
        generated_by="research-conductor",
    )
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "program-files-repaired",
            "created_count": len(created_paths),
            "created_paths": created_paths,
            "missing_targets": missing_targets,
        },
    )
    print(f"[ok] repaired program files; created={len(created_paths)}")
    if created_paths:
        for path in created_paths:
            print(f"- created: {path}")
    if missing_targets:
        print(f"- missing targets: {', '.join(missing_targets)}")
    return 0


def write_weekly_report(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    context = load_program_context(project_root, args.program_id)
    window_start, window_end = report_window(args.days, args.end_date)

    recent_papers = load_recent_items(
        load_literature_records(project_root),
        window_start=window_start,
        window_end=window_end,
        scorer=paper_relevance,
        context=context,
    )
    recent_repos = load_recent_items(
        load_repo_summaries(project_root),
        window_start=window_start,
        window_end=window_end,
        scorer=repo_relevance,
        context=context,
    )
    progress_items = weekly_progress_items(project_root, context, window_start, window_end)
    issues = current_issues(project_root, context)

    inclusive_end = window_end - timedelta(seconds=1)
    report_name = f"{window_start.date().isoformat()}_to_{inclusive_end.date().isoformat()}.md"
    report_path = context["program_root"] / "weekly" / report_name
    report_text = weekly_report_markdown(
        program_id=args.program_id,
        context=context,
        window_start=window_start,
        window_end=window_end,
        recent_papers=recent_papers,
        recent_repos=recent_repos,
        progress_items=progress_items,
        issues=issues,
        max_detailed_papers=args.max_detailed_papers,
        max_detailed_repos=args.max_detailed_repos,
    )
    write_text_if_changed(report_path, report_text)

    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "weekly-report-generated",
            "program_id": args.program_id,
            "report_path": report_path.relative_to(project_root).as_posix(),
            "window_start": window_start.isoformat(),
            "window_end": window_end.isoformat(),
            "paper_ids": [str(item["record"].get("id") or "") for item in recent_papers if str(item["record"].get("id") or "").strip()],
            "repo_ids": [
                str(item["record"].get("repo_id") or item["record"].get("id") or "")
                for item in recent_repos
                if str(item["record"].get("repo_id") or item["record"].get("id") or "").strip()
            ],
            "issue_count": len(issues),
        },
    )

    print(f"[ok] wrote weekly report to {report_path.as_posix()}")
    print(f"window: {report_window_label(window_start, window_end)}")
    print(f"papers: {len(recent_papers)}")
    print(f"repos: {len(recent_repos)}")
    print(f"issues: {len(issues)}")
    return 0


def init_workspace(_: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    print(f"[ok] initialized research workspace at {(research_root(project_root)).as_posix()}")
    return 0


def create_program(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    constraints = {"compute": args.compute, "data": args.data, "hardware": args.hardware}
    program_root = bootstrap_program(
        project_root,
        args.program_id,
        question=args.question,
        goal=args.goal,
        constraints=constraints,
    )
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "program-created",
            "program_id": args.program_id,
            "question": args.question,
        },
    )
    print(f"[ok] prepared program at {program_root.as_posix()}")
    return 0


def set_profile(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    profile_path = research_root(project_root) / "memory" / "user-profile.yaml"
    payload = load_yaml(profile_path, default={})
    if not isinstance(payload, dict):
        payload = {**yaml_default("user-profile", "research-conductor", status="active")}
    payload["generated_at"] = utc_now_iso()
    payload[args.field] = args.value
    write_yaml_if_changed(profile_path, payload)
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "profile-updated",
            "field": args.field,
            "value": args.value,
        },
    )
    print(f"[ok] updated user profile field {args.field}")
    return 0


def set_preference(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    if args.scope == "global":
        pref_path = research_root(project_root) / "memory" / "skill-preferences.yaml"
        payload = load_yaml(pref_path, default={})
        if not isinstance(payload, dict):
            payload = {**yaml_default("skill-preferences", "research-conductor", status="active")}
        payload.setdefault("preferences", {})
        payload["preferences"].setdefault(args.target, {})
        payload["preferences"][args.target][args.key] = args.value
    else:
        pref_path = research_root(project_root) / "programs" / args.program_id / "workflow" / "preferences.yaml"
        payload = load_yaml(pref_path, default={})
        if not isinstance(payload, dict):
            payload = {
                **yaml_default(f"{args.program_id}-preferences", "research-conductor"),
                "preferences": {},
            }
        payload.setdefault("preferences", {})
        payload["preferences"][args.key] = args.value
    payload["generated_at"] = utc_now_iso()
    write_yaml_if_changed(pref_path, payload)
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "preference-updated",
            "scope": args.scope,
            "target": args.target if args.scope == "global" else args.program_id,
            "key": args.key,
            "value": args.value,
        },
    )
    print(f"[ok] updated {args.scope} preference {args.key}")
    return 0


def append_decision(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    append_decision_log_entry(project_root, args.program_id, args.stage, args.summary)
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "decision-log-entry",
            "program_id": args.program_id,
            "stage": args.stage,
            "summary": args.summary,
        },
    )
    print(f"[ok] appended decision for program {args.program_id}")
    return 0


def load_candidate_program(project_root: Path, survey_id: str, *, program_seed_id: str, candidate_index: int | None) -> tuple[Path, dict[str, Any], dict[str, Any]]:
    report_path = landscape_report_path(project_root, survey_id)
    payload = load_yaml(report_path, default={})
    if not isinstance(payload, dict):
        raise SystemExit(f"Invalid landscape report: {report_path}")
    candidates = payload.get("candidate_programs", [])
    if not isinstance(candidates, list) or not candidates:
        raise SystemExit(f"No candidate programs found in landscape report: {report_path}")

    seed: dict[str, Any] | None = None
    if candidate_index is not None:
        zero_index = candidate_index - 1
        if zero_index < 0 or zero_index >= len(candidates):
            raise SystemExit(f"--candidate-index out of range for {report_path}")
        item = candidates[zero_index]
        if isinstance(item, dict):
            seed = item
    elif program_seed_id:
        for item in candidates:
            if isinstance(item, dict) and str(item.get("program_seed_id") or "") == program_seed_id:
                seed = item
                break

    if seed is None:
        available = ", ".join(
            str(item.get("program_seed_id") or f"candidate-{idx + 1}")
            for idx, item in enumerate(candidates)
            if isinstance(item, dict)
        )
        raise SystemExit(f"Candidate program not found in {report_path}. Available: {available}")
    return report_path, payload, seed


def create_program_from_landscape(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    report_path, report_payload, seed = load_candidate_program(
        project_root,
        args.survey_id,
        program_seed_id=args.program_seed_id,
        candidate_index=args.candidate_index,
    )
    program_id = args.program_id or str(seed.get("program_seed_id") or "") or slugify(str(seed.get("title") or "landscape-program"), max_words=8)
    constraints = {"compute": args.compute, "data": args.data, "hardware": args.hardware}
    program_root = bootstrap_program(
        project_root,
        program_id,
        question=str(seed.get("question") or ""),
        goal=str(seed.get("goal") or ""),
        constraints=constraints,
    )

    report_rel = report_path.relative_to(project_root).as_posix()
    charter_path = program_root / "charter.yaml"
    charter = load_yaml(charter_path, default={})
    if not isinstance(charter, dict):
        charter = {
            **yaml_default(program_id, "research-conductor", status="active"),
            "program_id": program_id,
        }
    charter["generated_at"] = utc_now_iso()
    charter["inputs"] = [
        report_rel,
        *[f"lit:{item}" for item in seed.get("literature_refs", []) if str(item).strip()],
        *[f"repo:{item}" for item in seed.get("repo_refs", []) if str(item).strip()],
    ]
    charter["seed_context"] = {
        "survey_id": args.survey_id,
        "program_seed_id": seed.get("program_seed_id", ""),
        "title": seed.get("title", ""),
        "why_now": seed.get("why_now", ""),
        "suggested_tags": seed.get("suggested_tags", []),
        "bootstrap_prompt": seed.get("bootstrap_prompt", ""),
        "field": report_payload.get("field", ""),
        "scope": report_payload.get("scope", ""),
    }
    write_yaml_if_changed(charter_path, charter)

    state_path = program_root / "workflow" / "state.yaml"
    state = load_yaml(state_path, default={})
    if not isinstance(state, dict):
        state = {
            **yaml_default(f"{program_id}-state", "research-conductor", status="active"),
            "program_id": program_id,
            "stage": "problem-framing",
            "active_idea_id": "",
            "selected_idea_id": "",
            "selected_repo_id": "",
        }
    state["generated_at"] = utc_now_iso()
    state["inputs"] = [charter_path.relative_to(project_root).as_posix(), report_rel]
    state["stage"] = "problem-framing"
    write_yaml_if_changed(state_path, state)

    append_decision_log_entry(
        project_root,
        program_id,
        "problem-framing",
        (
            f"Program bootstrapped from landscape survey `{args.survey_id}` candidate "
            f"`{seed.get('program_seed_id', '') or seed.get('title', '')}`."
        ),
    )
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "program-created-from-landscape",
            "program_id": program_id,
            "survey_id": args.survey_id,
            "program_seed_id": seed.get("program_seed_id", ""),
            "field": report_payload.get("field", ""),
        },
    )
    print(f"[ok] prepared program from landscape seed at {program_root.as_posix()}")
    return 0


def add_evidence_request(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    program_root = existing_program_root(project_root, args.program_id)
    path = program_root / "workflow" / "evidence-requests.yaml"
    payload = load_list_document(path, f"{args.program_id}-evidence-requests", "research-conductor")
    payload["generated_at"] = utc_now_iso()
    payload["inputs"] = [str((program_root / "charter.yaml").relative_to(project_root))]
    payload["items"].append(
        {
            "request_id": args.request_id,
            "priority": args.priority,
            "blocking_reason": args.blocking_reason,
            "suggested_skill": args.suggested_skill,
            "notes": args.notes,
            "status": "open",
        }
    )
    write_yaml_if_changed(path, payload)
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "evidence-request-added",
            "program_id": args.program_id,
            "request_id": args.request_id,
        },
    )
    print(f"[ok] added evidence request {args.request_id}")
    return 0


def set_stage(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    program_root = existing_program_root(project_root, args.program_id)
    path = program_root / "workflow" / "state.yaml"
    payload = load_yaml(path, default={})
    if not isinstance(payload, dict):
        payload = {
            **yaml_default(f"{args.program_id}-state", "research-conductor", status="active"),
            "program_id": args.program_id,
            "stage": "problem-framing",
            "active_idea_id": "",
            "selected_idea_id": "",
            "selected_repo_id": "",
        }
    payload["generated_at"] = utc_now_iso()
    payload["inputs"] = [str((program_root / "charter.yaml").relative_to(project_root))]
    payload["stage"] = args.stage
    for field in ("active_idea_id", "selected_idea_id", "selected_repo_id"):
        value = getattr(args, field)
        if value is not None:
            payload[field] = value
    write_yaml_if_changed(path, payload)
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "stage-updated",
            "program_id": args.program_id,
            "stage": args.stage,
            "active_idea_id": payload.get("active_idea_id", ""),
            "selected_idea_id": payload.get("selected_idea_id", ""),
            "selected_repo_id": payload.get("selected_repo_id", ""),
        },
    )
    print(f"[ok] set stage for program {args.program_id} to {args.stage}")
    return 0


def add_open_question(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    ensure_research_runtime(project_root, "research-conductor")
    program_root = existing_program_root(project_root, args.program_id)
    path = program_root / "workflow" / "open-questions.yaml"
    payload = load_list_document(path, f"{args.program_id}-open-questions", "research-conductor")
    payload["generated_at"] = utc_now_iso()
    payload["inputs"] = [str((program_root / "charter.yaml").relative_to(project_root))]
    payload["items"].append(
        {
            "question_id": args.question_id,
            "question": args.question,
            "owner": args.owner,
            "notes": args.notes,
            "status": "open",
        }
    )
    write_yaml_if_changed(path, payload)
    append_history(
        project_root,
        {
            "timestamp": utc_now_iso(),
            "type": "open-question-added",
            "program_id": args.program_id,
            "question_id": args.question_id,
        },
    )
    print(f"[ok] added open question {args.question_id}")
    return 0


def remember_runtime(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    record = remember_runtime_record(
        project_root,
        args.python or sys.executable,
        label=args.label,
        notes=args.notes,
        set_default=not args.no_set_default,
    )
    preferred = preferred_runtime_record(project_root)
    print("[ok] remembered research runtime")
    print(format_runtime_report(record))
    if preferred and preferred.get("runtime_id") == record.get("runtime_id"):
        print("preferred: true")
    return 0


def show_runtime(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    registry = load_runtime_registry(project_root)
    runtime_id = args.runtime_id or registry.get("preferred_runtime_id", "")
    if runtime_id:
        record = registry["items"].get(runtime_id)
        if not isinstance(record, dict):
            raise SystemExit(f"Runtime not found: {runtime_id}")
        print(format_runtime_report(record))
        print(f"preferred: {runtime_id == registry.get('preferred_runtime_id', '')}")
        return 0

    current = current_runtime_capabilities()
    print(format_runtime_report({**current, "runtime_id": "current", "label": "current"}))
    print("preferred: false")
    return 0


def check_runtime(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    if args.python:
        status = inspect_python_runtime(args.python)
        status.setdefault("runtime_id", "probe")
        status.setdefault("label", args.label or "probe")
    else:
        status = {
            **current_runtime_capabilities(),
            "runtime_id": "current",
            "label": args.label or "current",
        }
    print(format_runtime_report(status))
    missing: list[str] = []
    if not status.get("yaml_support"):
        missing.append("PyYAML")
    if args.require_pdf and not status.get("pdf_support"):
        missing.append("PyPDF2 or pypdf")
    if missing:
        print(f"ready: false ({', '.join(missing)} missing)")
        preferred = preferred_runtime_record(project_root)
        if preferred:
            print(
                "hint: remembered preferred runtime -> "
                f"{preferred.get('label', '') or preferred.get('runtime_id', '')} @ {preferred.get('python', '')}"
            )
        return 1
    print("ready: true")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage the research v1.1 workspace and program state.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_cmd = subparsers.add_parser("init-workspace", help="Create the shared research workspace skeleton")
    init_cmd.set_defaults(func=init_workspace)

    create_cmd = subparsers.add_parser("create-program", help="Create a new program workspace")
    create_cmd.add_argument("--program-id", required=True)
    create_cmd.add_argument("--question", required=True)
    create_cmd.add_argument("--goal", required=True)
    create_cmd.add_argument("--compute", default="")
    create_cmd.add_argument("--data", default="")
    create_cmd.add_argument("--hardware", default="")
    create_cmd.set_defaults(func=create_program)

    create_from_landscape_cmd = subparsers.add_parser(
        "create-program-from-landscape",
        help="Create a new program from a research-landscape-analyst candidate program seed",
    )
    create_from_landscape_cmd.add_argument("--survey-id", required=True)
    seed_selector = create_from_landscape_cmd.add_mutually_exclusive_group(required=True)
    seed_selector.add_argument("--program-seed-id", default="")
    seed_selector.add_argument("--candidate-index", type=int, default=None)
    create_from_landscape_cmd.add_argument("--program-id", default="")
    create_from_landscape_cmd.add_argument("--compute", default="")
    create_from_landscape_cmd.add_argument("--data", default="")
    create_from_landscape_cmd.add_argument("--hardware", default="")
    create_from_landscape_cmd.set_defaults(func=create_program_from_landscape)

    profile_cmd = subparsers.add_parser("set-profile", help="Update a field on memory/user-profile.yaml")
    profile_cmd.add_argument("--field", required=True)
    profile_cmd.add_argument("--value", required=True)
    profile_cmd.set_defaults(func=set_profile)

    pref_cmd = subparsers.add_parser("set-preference", help="Update global or program preferences")
    pref_cmd.add_argument("--scope", choices=["global", "program"], required=True)
    pref_cmd.add_argument("--target", default="", help="Skill name for global preferences")
    pref_cmd.add_argument("--program-id", default="")
    pref_cmd.add_argument("--key", required=True)
    pref_cmd.add_argument("--value", required=True)
    pref_cmd.set_defaults(func=set_preference)

    capture_cmd = subparsers.add_parser(
        "capture-memory",
        help="Capture stable user resource facts or preferences from a natural-language statement",
    )
    capture_cmd.add_argument("--statement", required=True)
    capture_cmd.add_argument("--program-id", default="")
    capture_cmd.add_argument("--source", default="chat")
    capture_cmd.add_argument("--dry-run", action="store_true")
    capture_cmd.set_defaults(func=capture_memory)

    decision_cmd = subparsers.add_parser("append-decision", help="Append a markdown decision log entry")
    decision_cmd.add_argument("--program-id", required=True)
    decision_cmd.add_argument("--stage", required=True)
    decision_cmd.add_argument("--summary", required=True)
    decision_cmd.set_defaults(func=append_decision)

    request_cmd = subparsers.add_parser("add-evidence-request", help="Create a new evidence request")
    request_cmd.add_argument("--program-id", required=True)
    request_cmd.add_argument("--request-id", required=True)
    request_cmd.add_argument("--priority", default="medium")
    request_cmd.add_argument("--blocking-reason", required=True)
    request_cmd.add_argument("--suggested-skill", default="literature-scout")
    request_cmd.add_argument("--notes", default="")
    request_cmd.set_defaults(func=add_evidence_request)

    stage_cmd = subparsers.add_parser("set-stage", help="Update workflow/state.yaml for a program")
    stage_cmd.add_argument("--program-id", required=True)
    stage_cmd.add_argument("--stage", required=True, choices=DEFAULT_STAGES)
    stage_cmd.add_argument("--active-idea-id", default=None)
    stage_cmd.add_argument("--selected-idea-id", default=None)
    stage_cmd.add_argument("--selected-repo-id", default=None)
    stage_cmd.set_defaults(func=set_stage)

    question_cmd = subparsers.add_parser("add-open-question", help="Append an open question for a program")
    question_cmd.add_argument("--program-id", required=True)
    question_cmd.add_argument("--question-id", required=True)
    question_cmd.add_argument("--question", required=True)
    question_cmd.add_argument("--owner", default="research-conductor")
    question_cmd.add_argument("--notes", default="")
    question_cmd.set_defaults(func=add_open_question)

    query_cmd = subparsers.add_parser(
        "query-program",
        help="Run a program-scoped query over canonical literature/repos and optionally save a durable wiki artifact",
    )
    query_cmd.add_argument("--program-id", required=True)
    query_cmd.add_argument("--question", required=True)
    query_cmd.add_argument("--title", default="")
    query_cmd.add_argument("--max-papers", type=int, default=8)
    query_cmd.add_argument("--max-repos", type=int, default=6)
    query_cmd.add_argument("--no-save", action="store_true", help="Print query synthesis only; do not write a query artifact")
    query_cmd.set_defaults(func=query_program)

    lint_cmd = subparsers.add_parser(
        "lint-workspace",
        help="Run wiki-level workspace lint and write a durable lint report",
    )
    lint_cmd.add_argument("--strict", action="store_true", help="Exit non-zero when lint status is not PASS")
    lint_cmd.set_defaults(func=lint_workspace)

    rebuild_wiki_cmd = subparsers.add_parser(
        "rebuild-wiki-index",
        help="Regenerate kb/wiki/index.md from canonical workspace artifacts",
    )
    rebuild_wiki_cmd.set_defaults(func=rebuild_wiki_index)

    repair_cmd = subparsers.add_parser(
        "repair-program-files",
        help="Backfill missing workflow/reporting-events.yaml files for existing programs",
    )
    repair_cmd.add_argument("--program-id", action="append", default=[], help="Optional program ID filter (repeatable)")
    repair_cmd.set_defaults(func=repair_program_files)

    weekly_cmd = subparsers.add_parser(
        "write-weekly-report",
        help="Legacy alias for weekly-report-author; write a weekly markdown report for a program",
    )
    weekly_cmd.add_argument("--program-id", required=True)
    weekly_cmd.add_argument("--days", type=int, default=7)
    weekly_cmd.add_argument("--end-date", default="", help="Optional inclusive UTC end date in YYYY-MM-DD format")
    weekly_cmd.add_argument("--max-detailed-papers", type=int, default=8)
    weekly_cmd.add_argument("--max-detailed-repos", type=int, default=6)
    weekly_cmd.set_defaults(func=write_weekly_report)

    remember_runtime_cmd = subparsers.add_parser(
        "remember-runtime",
        help="Validate and remember a research Python runtime for future skill runs",
    )
    remember_runtime_cmd.add_argument("--python", default="", help="Python executable to validate and store")
    remember_runtime_cmd.add_argument("--label", default="research-default")
    remember_runtime_cmd.add_argument("--notes", default="")
    remember_runtime_cmd.add_argument("--no-set-default", action="store_true")
    remember_runtime_cmd.set_defaults(func=remember_runtime)

    show_runtime_cmd = subparsers.add_parser(
        "show-runtime",
        help="Show the preferred remembered runtime or a named runtime record",
    )
    show_runtime_cmd.add_argument("--runtime-id", default="")
    show_runtime_cmd.set_defaults(func=show_runtime)

    check_runtime_cmd = subparsers.add_parser(
        "check-runtime",
        help="Check whether a Python runtime satisfies research skill requirements",
    )
    check_runtime_cmd.add_argument("--python", default="", help="Optional Python executable to probe")
    check_runtime_cmd.add_argument("--label", default="")
    check_runtime_cmd.add_argument("--require-pdf", action="store_true")
    check_runtime_cmd.set_defaults(func=check_runtime)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
