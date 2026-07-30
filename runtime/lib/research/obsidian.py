"""No-plugin Obsidian projection for the canonical research KB.

The projection is fully derived.  Only ``kb/obsidian/managed`` is owned by this
module; ``inbox`` and ``annotations`` are human space and are never traversed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import quote as url_quote

from .common import utc_now_iso
from .journal import mutation_transaction
from .paths import UNIT_KIND_DIRS, ensure_kb_gitignore, kb_gitignore_path, kb_root, topic_taxonomy_path, unit_root, units_root
from .records import normalize_record_schema, snapshot_project_file
from .figures import FigureIndexError, load_current_figure_index
from .relations import (
    BLOCK_ID_RE,
    inverse_relation,
    project_relation_edges,
    stable_block_id,
)
from .yaml_io import (
    StrictYamlError,
    dump_yaml,
    load_yaml,
    load_yaml_mapping_bytes_strict,
    write_text_if_changed,
    write_yaml_if_changed,
)


OBSIDIAN_PROJECTION_SCHEMA = "research-kb-obsidian/v1"
OBSIDIAN_RENDERER_REVISION = 11
MANIFEST_NAME = "manifest.yaml"
HUMAN_DIRS = ("inbox", "annotations")
OBSIDIAN_BASE_PRESENTATION_RESET_SCHEMA = "research-kb-obsidian-base-presentation-reset/v1"
OBSIDIAN_BASE_PRESENTATION_FILES = frozenset(
    {
        "dashboards/All Units.base",
        "dashboards/Pending Review.base",
        "dashboards/By Topic.base",
    }
)
_OBSIDIAN_BASE_MAX_BYTES = 256 * 1024
_OBSIDIAN_BASE_SORT_DIRECTIONS = frozenset({"ASC", "DESC"})
UNIT_HEADINGS = frozenset(
    {
        "Overview", "Definition", "Associations", "Metadata", "Relationships", "Claims", "Figures",
        "概览", "定义", "关联清单", "元数据", "关系", "判断", "插图",
    }
)
_MARKDOWN_INLINE_RE = re.compile(r"([\\`*_{}\[\]()<>~$|^&=#!])")
_LEADING_MARKDOWN_RE = re.compile(r"^(?P<prefix>(?:[+-])|(?:\d+[.)]))(?=\s)")
_CLAIM_TYPE_LABELS = {
    "fact": "Fact",
    "inference": "Inference",
    "evaluation": "Evaluation",
    "user_opinion": "User opinion",
    "unverified": "Unverified",
}
_CONFIRMATION_LABELS = {
    "pending_user_confirmation": "Pending human confirmation",
    "confirmed": "Confirmed",
    "rejected": "Rejected",
    "auto_confirmed": "Automatically confirmed",
    "unverified": "Unverified",
}
_CLAIM_TYPE_LABELS_ZH = {
    "fact": "事实",
    "inference": "推断",
    "evaluation": "评价",
    "user_opinion": "用户观点",
    "unverified": "未验证",
}
_CONFIRMATION_LABELS_ZH = {
    "pending_user_confirmation": "等待人工确认",
    "confirmed": "已确认",
    "rejected": "已拒绝",
    "auto_confirmed": "已自动确认",
    "unverified": "未验证",
}


def _t(zh: bool, english: str, chinese: str) -> str:
    return chinese if zh else english


def obsidian_root(project_root: Path) -> Path:
    return kb_root(project_root) / "obsidian"


def obsidian_managed_root(project_root: Path) -> Path:
    return obsidian_root(project_root) / "managed"


def obsidian_manifest_path(project_root: Path) -> Path:
    return obsidian_managed_root(project_root) / MANIFEST_NAME


def obsidian_review_annotations_root(project_root: Path) -> Path:
    """Human-owned exchange area for explicit, no-plugin review handoffs.

    Projection update/status code must never traverse this directory.  A review
    sync may read one registry-bound regular file from it only after the user
    explicitly asks the runtime Agent to do so.
    """
    return obsidian_root(project_root) / "annotations"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _safe_component(value: Any, *, fallback: str) -> str:
    raw = str(value or "").strip()
    candidate = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-")
    if not candidate:
        candidate = fallback
    if candidate != raw:
        candidate = f"{candidate}-{hashlib.sha256(raw.encode('utf-8')).hexdigest()[:8]}"
    return candidate


def _frontmatter(properties: dict[str, Any]) -> str:
    # Obsidian properties parse wikilinks most reliably when each link stays on
    # one physical YAML line.  The projection owns these bounded documents, so
    # a deliberately wide dump is preferable to PyYAML's presentation wrapping.
    return f"---\n{dump_yaml(properties, width=1_000_000).strip()}\n---\n"


def _single_line(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _escape_display(value: Any) -> str:
    return _single_line(value).replace("|", "／").replace("]", "］")


def _markdown_text(value: Any) -> str:
    """Render canonical free text without allowing Markdown reinterpretation."""
    text = _single_line(value)
    text = _MARKDOWN_INLINE_RE.sub(lambda match: f"\\{match.group(0)}", text)
    return _LEADING_MARKDOWN_RE.sub(lambda match: f"\\{match.group('prefix')}", text)


def _inline_code(value: Any, *, fallback: str = "") -> str:
    text = _single_line(value) or fallback
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * (longest + 1)
    return f"{fence} {text} {fence}"


def _human_label(value: Any, labels: dict[str, str], *, fallback: str = "Unverified") -> str:
    raw = _single_line(value)
    if not raw:
        return fallback
    return labels.get(raw, raw.replace("_", " ").capitalize())


def _source_markdown(value: Any, *, zh: bool = False) -> str:
    uri = _single_line(value)
    if re.match(r"^https?://", uri, flags=re.IGNORECASE):
        encoded = url_quote(uri, safe=":/?#[]@!$&'()*+,;=%")
        return f"[{_t(zh, 'Open source', '打开在线原文')}](<{encoded}>)"
    return _t(zh, "Local source archived", "本地原始材料已归档")


def _canonical_source_path(project_root: Path, raw: Any, *, suffix: str | None) -> Path | None:
    text = _single_line(raw)
    if not text:
        return None
    lexical = PurePosixPath(text)
    if lexical.is_absolute() or not lexical.parts or lexical.parts[0] != "kb":
        return None
    if any(part in {"", ".", ".."} for part in lexical.parts):
        return None
    if suffix is not None and lexical.suffix.lower() != suffix:
        return None
    candidate = project_root.joinpath(*lexical.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(kb_root(project_root).resolve())
    except (OSError, ValueError):
        return None
    if candidate.is_symlink() or not candidate.is_file():
        return None
    return resolved


def _canonical_kb_entry(project_root: Path, raw: Any, *, directory: bool) -> Path | None:
    """Resolve a canonical KB file/directory without exposing paths in page text."""
    text = _single_line(raw)
    if not text:
        return None
    lexical = PurePosixPath(text)
    if lexical.is_absolute() or not lexical.parts or lexical.parts[0] != "kb":
        return None
    if any(part in {"", ".", ".."} for part in lexical.parts):
        return None
    candidate = project_root.joinpath(*lexical.parts)
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(kb_root(project_root).resolve())
    except (OSError, ValueError):
        return None
    if candidate.is_symlink():
        return None
    if directory and not candidate.is_dir():
        return None
    if not directory and not candidate.is_file():
        return None
    return resolved


def _source_document_vault_path(project_root: Path, source: dict[str, Any]) -> str:
    raw = _single_line(source.get("markdown_path"))
    resolved = _canonical_source_path(project_root, raw, suffix=".md")
    if resolved is None:
        return ""
    try:
        relative = resolved.relative_to(kb_root(project_root).resolve())
    except ValueError:
        return ""
    return PurePosixPath(relative.as_posix()).with_suffix("").as_posix()


def _source_document_link(project_root: Path, source: dict[str, Any], *, zh: bool = False) -> str:
    vault_path = _source_document_vault_path(project_root, source)
    return _wikilink(vault_path, display=_t(zh, "Read material", "阅读 Markdown 全文")) if vault_path else ""


def _local_repo_quick_links(project_root: Path, record: dict[str, Any], *, zh: bool) -> list[str]:
    """Expose a bounded set of useful entry files for an archived local repo."""
    if str(record.get("kind") or "") != "repo":
        return []
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    backup_paths = source.get("backup_paths") if isinstance(source.get("backup_paths"), list) else []
    roots = [
        resolved
        for raw in backup_paths
        if (resolved := _canonical_kb_entry(project_root, raw, directory=True)) is not None
    ]
    if not roots:
        return []
    root = roots[0]
    candidates = (
        "README.md",
        "README.rst",
        "README.txt",
        "README",
        "pyproject.toml",
        "package.json",
        "setup.py",
        "Cargo.toml",
    )
    links: list[str] = []
    for name in candidates:
        candidate = root / name
        if candidate.is_symlink() or not candidate.is_file():
            continue
        if candidate.suffix.lower() == ".md":
            relative = candidate.resolve().relative_to(kb_root(project_root).resolve())
            links.append(_wikilink(PurePosixPath(relative.as_posix()).with_suffix("").as_posix(), display=name))
        else:
            encoded = url_quote(candidate.resolve().as_uri(), safe=":/?#[]@!$&'()*+,;=%")
            links.append(f"[{name}](<{encoded}>)")
        if len(links) >= 3:
            break
    folder_uri = url_quote(root.as_uri(), safe=":/?#[]@!$&'()*+,;=%")
    links.append(f"[{_t(zh, 'Open source folder', '打开本地源码目录')}](<{folder_uri}>)")
    return links


def _source_materialization_summary(project_root: Path, source: dict[str, Any]) -> dict[str, Any]:
    """Return bounded, presentation-safe source health from the immutable receipt."""
    materialization = source.get("materialization")
    materialization = materialization if isinstance(materialization, dict) else {}
    status = _single_line(materialization.get("status")) or "not_materialized"
    summary: dict[str, Any] = {"status": status, "warnings": [], "output": {}}
    conversion_path = _canonical_source_path(
        project_root,
        materialization.get("conversion_path"),
        suffix=".yaml",
    )
    if conversion_path is None:
        return summary
    try:
        conversion = load_yaml(conversion_path, default={})
    except (OSError, RuntimeError):
        return summary
    if not isinstance(conversion, dict):
        return summary
    summary["status"] = _single_line(conversion.get("status")) or status
    raw_warnings = conversion.get("warnings", [])
    if isinstance(raw_warnings, list):
        summary["warnings"] = [_single_line(item) for item in raw_warnings if _single_line(item)][:3]
    quality = conversion.get("quality")
    quality = quality if isinstance(quality, dict) else {}
    output = quality.get("output")
    summary["output"] = output if isinstance(output, dict) else {}
    return summary


def _record_claims(record: dict[str, Any]) -> list[dict[str, Any]]:
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    claims = payload.get("claims")
    return [item for item in claims if isinstance(item, dict)] if isinstance(claims, list) else []


def _analysis_stage(record: dict[str, Any]) -> str:
    claims = _record_claims(record)
    confirmation = _single_line(record.get("confirmation_status"))
    # Canonical claim rows intentionally preserve their pre-decision epistemic
    # status so the ConfirmationReceipt digest remains stable.  A normalized
    # record is top-level confirmed only while that receipt is current, so the
    # projection must treat its covered claims as confirmed instead of showing
    # a contradictory pending banner.
    if claims and confirmation == "confirmed":
        return "evidence_recorded"
    claim_pending = any(
        _single_line(claim.get("confirmation_status")) == "pending_user_confirmation"
        for claim in claims
    )
    if claims and (confirmation == "pending_user_confirmation" or claim_pending):
        return "awaiting_confirmation"
    if claims:
        return "evidence_recorded"
    return "awaiting_analysis"


def _projected_claim_confirmation(record: dict[str, Any], claim: dict[str, Any]) -> str:
    status = _single_line(claim.get("confirmation_status"))
    if _single_line(record.get("confirmation_status")) != "confirmed":
        return status
    receipt = record.get("confirmation")
    receipt = receipt if isinstance(receipt, dict) else {}
    claim_ids = receipt.get("claim_ids")
    claim_ids = claim_ids if isinstance(claim_ids, list) else []
    if _single_line(claim.get("id")) in {_single_line(item) for item in claim_ids}:
        return "confirmed"
    return status


def _analysis_stage_label(stage: str, *, zh: bool = False) -> str:
    labels = {
        "awaiting_analysis": _t(zh, "Awaiting AI analysis", "等待 AI 分析"),
        "evidence_recorded": _t(zh, "Evidence-backed analysis available", "已有证据支持的分析"),
        "awaiting_confirmation": _t(zh, "Awaiting human confirmation", "等待人工确认"),
    }
    return labels.get(stage, stage.replace("_", " ").capitalize())


def _display_summary(record: dict[str, Any], analysis_stage: str, *, zh: bool = False) -> str:
    summary = _single_line(record.get("summary"))
    if not summary or re.fullmatch(r"Lightweight \w+ intake for `?.+?`?\.", summary):
        if analysis_stage == "awaiting_confirmation":
            return _t(
                zh,
                "Evidence-backed claims are recorded below and await human confirmation.",
                "下方已记录有逐字证据支持的判断，正在等待人工确认。",
            )
        if analysis_stage == "evidence_recorded":
            return _t(
                zh,
                "Evidence-backed claims and their supporting quotes are available below.",
                "下方已列出有逐字证据支持的判断及其证据。",
            )
        return _t(
            zh,
            "The material is safely archived and readable. AI analysis has not been completed yet.",
            "原始材料已安全归档并可直接阅读，AI 尚未完成内容分析。",
        )
    return _markdown_text(summary)


def _source_evidence_link(
    project_root: Path,
    record: dict[str, Any],
    ref: dict[str, Any],
    artifact: str,
) -> str:
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    vault_path = _source_document_vault_path(project_root, source)
    if not vault_path:
        return ""
    materialization = source.get("materialization") if isinstance(source.get("materialization"), dict) else {}
    source_map = _canonical_source_path(project_root, materialization.get("source_map_path"), suffix=".yaml")
    block_id = ""
    if source_map is not None:
        try:
            payload = load_yaml(source_map, default={})
        except (OSError, RuntimeError):
            payload = {}
        blocks = payload.get("blocks", []) if isinstance(payload, dict) else []
        locator = _single_line(ref.get("locator"))
        page_match = re.fullmatch(r"page\s*=\s*(\d+)", locator, flags=re.IGNORECASE)
        section_match = re.fullmatch(r"(?:section|anchor)\s*:\s*(.+)", locator, flags=re.IGNORECASE)
        for item in (blocks if isinstance(blocks, list) else []):
            if not isinstance(item, dict):
                continue
            matches = False
            if page_match:
                try:
                    matches = int(item.get("page")) == int(page_match.group(1))
                except (TypeError, ValueError):
                    matches = False
            elif section_match:
                target = section_match.group(1).strip()
                matches = target in {_single_line(item.get("anchor")), _single_line(item.get("heading"))}
            elif locator.lower() in {"section", "document"}:
                matches = _single_line(item.get("anchor")) == "document"
            if matches and BLOCK_ID_RE.fullmatch(_single_line(item.get("block_id"))):
                block_id = _single_line(item.get("block_id"))
                break
    target = f"{vault_path}#^{block_id}" if block_id else vault_path
    return _wikilink(target, display=artifact)


def _local_repo_artifact_uri(record: dict[str, Any], ref: dict[str, Any]) -> str:
    external = ref.get("external_source") if isinstance(ref.get("external_source"), dict) else {}
    if str(record.get("kind") or "") != "repo" or str(external.get("kind") or "") != "repo":
        return ""
    payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
    structure = payload.get("structure") if isinstance(payload.get("structure"), dict) else {}
    root_text = str(structure.get("repo_root") or "").strip()
    artifact = str(ref.get("artifact") or "").strip()
    relative = PurePosixPath(artifact)
    if not root_text or relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
        return ""
    root = Path(root_text).expanduser()
    if root.is_symlink() or not root.is_dir():
        return ""
    try:
        root_resolved = root.resolve(strict=True)
        lexical = root.joinpath(*relative.parts)
        if lexical.is_symlink() or not lexical.is_file():
            return ""
        resolved = lexical.resolve(strict=True)
        resolved.relative_to(root_resolved)
    except (OSError, ValueError):
        return ""
    return resolved.as_uri()


def _artifact_markdown(
    project_root: Path,
    record: dict[str, Any],
    ref: dict[str, Any],
    artifact: str,
) -> str:
    uri = _local_repo_artifact_uri(record, ref)
    if uri:
        encoded = url_quote(uri, safe=":/?#[]@!$&'()*+,;=%")
        return f"[{_inline_code(artifact)}](<{encoded}>)"
    source_link = _source_evidence_link(project_root, record, ref, artifact)
    return source_link or _inline_code(artifact)


def _unit_page_path(unit_id: str) -> str:
    return f"obsidian/managed/units/{_safe_component(unit_id, fallback='unit')}"


def _program_page_path(program_id: str) -> str:
    return f"obsidian/managed/programs/{_safe_component(program_id, fallback='program')}"


def _topic_page_path(topic_id: str) -> str:
    return f"obsidian/managed/topics/{_safe_component(topic_id, fallback='topic')}"


def _wikilink(path: str, *, display: str = "", locator: dict[str, Any] | None = None) -> str:
    suffix = ""
    if isinstance(locator, dict):
        kind = str(locator.get("kind") or "")
        value = str(locator.get("value") or "")
        if kind == "heading" and value:
            suffix = f"#{value}"
        elif kind == "block" and value:
            suffix = f"#^{value}"
    label = f"|{_escape_display(display)}" if display else ""
    return f"[[{path}{suffix}{label}]]"


def _unit_link(
    unit_id: str,
    records_by_id: dict[str, dict[str, Any]],
    *,
    locator: dict[str, Any] | None = None,
) -> str:
    record = records_by_id.get(unit_id, {})
    display = str(record.get("title") or unit_id)
    return _wikilink(_unit_page_path(unit_id), display=display, locator=locator)


def _claims(record: dict[str, Any]) -> list[dict[str, Any]]:
    payload = record.get("payload")
    values = payload.get("claims", []) if isinstance(payload, dict) else []
    return [item for item in values if isinstance(item, dict) and _single_line(item.get("text"))]


def _claim_block_id(claim: dict[str, Any], index: int) -> str:
    return stable_block_id(claim.get("id") or f"claim-{index:03d}", prefix="claim")


def _evidence_block_id(claim_block: str, index: int) -> str:
    return stable_block_id(f"evidence-{claim_block}-{index:03d}", prefix="evidence")


def _available_unit_anchors(record: dict[str, Any]) -> tuple[set[str], set[str]]:
    headings = set(UNIT_HEADINGS)
    blocks: set[str] = set()
    for claim_index, claim in enumerate(_claims(record), start=1):
        claim_id = _claim_block_id(claim, claim_index)
        blocks.add(claim_id)
        headings.add(f"Claim {claim_id}")
        refs = claim.get("evidence_refs", [])
        if isinstance(refs, list):
            for evidence_index, ref in enumerate(refs, start=1):
                if isinstance(ref, dict):
                    blocks.add(_evidence_block_id(claim_id, evidence_index))
    return headings, blocks


def _flat_relation_properties(
    unit_id: str,
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
    records_by_id: dict[str, dict[str, Any]],
) -> dict[str, list[str]]:
    properties: dict[str, list[str]] = defaultdict(list)
    for edge in outgoing.get(unit_id, []):
        key = f"rel_{edge['relation']}"
        properties[key].append(
            _unit_link(str(edge["target_id"]), records_by_id, locator=edge.get("target_locator"))
        )
    for edge in incoming.get(unit_id, []):
        key = f"rel_{inverse_relation(str(edge['relation']))}"
        properties[key].append(
            _unit_link(str(edge["source_id"]), records_by_id, locator=edge.get("source_locator"))
        )
    return {key: sorted(set(values)) for key, values in sorted(properties.items())}


def _render_relations(
    unit_id: str,
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
    records_by_id: dict[str, dict[str, Any]],
    *,
    zh: bool = False,
) -> list[str]:
    grouped: dict[str, list[str]] = defaultdict(list)
    for edge in outgoing.get(unit_id, []):
        link = _unit_link(str(edge["target_id"]), records_by_id, locator=edge.get("target_locator"))
        note = f" — {_markdown_text(edge.get('note'))}" if _single_line(edge.get("note")) else ""
        grouped[str(edge["relation"])].append(f"- {link}{note}")
    for edge in incoming.get(unit_id, []):
        relation = inverse_relation(str(edge["relation"]))
        link = _unit_link(str(edge["source_id"]), records_by_id, locator=edge.get("source_locator"))
        note = f" — {_markdown_text(edge.get('note'))}" if _single_line(edge.get("note")) else ""
        grouped[relation].append(f"- {link}{note}")
    if not grouped:
        return [_t(zh, "No typed relationships yet.", "暂时没有已建立的类型化关系。")]
    lines: list[str] = []
    for relation in sorted(grouped):
        lines.extend([f"### {relation}", "", *sorted(set(grouped[relation])), ""])
    return lines[:-1]


def _render_concept_sections(
    record: dict[str, Any],
    records_by_id: dict[str, dict[str, Any]],
    *,
    zh: bool = False,
) -> list[str]:
    if str(record.get("kind") or "") != "concept":
        return []
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    concept = payload.get("concept")
    concept = concept if isinstance(concept, dict) else {}
    definition = _single_line(concept.get("definition")) or _t(
        zh, "No verified definition is available.", "尚无已核验的定义。"
    )
    aliases = [str(item) for item in concept.get("aliases", []) if str(item).strip()]
    raw_associations = payload.get("associations")
    associations = raw_associations if isinstance(raw_associations, list) else []
    lines = [
        f"## {_t(zh, 'Definition', '定义')}",
        "",
        _markdown_text(definition),
    ]
    if aliases:
        lines.extend(
            [
                "",
                f"- {_t(zh, 'Aliases', '别名')}: " + ", ".join(_markdown_text(item) for item in aliases),
            ]
        )
    lines.extend(["", f"## {_t(zh, 'Associations', '关联清单')}", ""])
    rendered = 0
    for association in associations:
        if not isinstance(association, dict):
            continue
        target_id = _single_line(association.get("target_id"))
        if not target_id:
            continue
        relation = _single_line(association.get("relation")) or "related_to"
        role = _single_line(association.get("role"))
        suffix = f" — {_markdown_text(role)}" if role else ""
        lines.append(
            f"- {_unit_link(target_id, records_by_id)} · {_inline_code(relation)}{suffix}"
        )
        rendered += 1
    if not rendered:
        lines.append(_t(zh, "- No associated units.", "- 暂无关联单元。"))
    return lines


def _render_claims(
    project_root: Path,
    record: dict[str, Any],
    records_by_id: dict[str, dict[str, Any]],
    *,
    zh: bool = False,
) -> list[str]:
    claims = _claims(record)
    if not claims:
        return [_t(zh, "No canonical claims yet.", "尚未形成可确认的知识判断。")]
    lines: list[str] = []
    current_id = str(record.get("id") or "")
    for claim_index, claim in enumerate(claims, start=1):
        block_id = _claim_block_id(claim, claim_index)
        text = _markdown_text(claim.get("text"))
        lines.extend(
            [
                f"### {_t(zh, 'Claim', '判断')} {block_id}",
                "",
                f"{text} ^{block_id}",
                "",
                f"- {_t(zh, 'Type', '类型')}: {_human_label(claim.get('claim_type'), _CLAIM_TYPE_LABELS_ZH if zh else _CLAIM_TYPE_LABELS)}",
                f"- {_t(zh, 'Confirmation', '确认状态')}: {_human_label(_projected_claim_confirmation(record, claim), _CONFIRMATION_LABELS_ZH if zh else _CONFIRMATION_LABELS)}",
            ]
        )
        refs = claim.get("evidence_refs", [])
        refs = refs if isinstance(refs, list) else []
        if not refs:
            lines.extend([f"- {_t(zh, 'Evidence: none', '证据：暂无')}", ""])
            continue
        lines.extend(["", f"#### {_t(zh, 'Evidence', '证据')}", ""])
        for evidence_index, ref in enumerate(refs, start=1):
            if not isinstance(ref, dict):
                continue
            evidence_id = _evidence_block_id(block_id, evidence_index)
            source_id = str(ref.get("source_unit_id") or current_id)
            source_link = _unit_link(source_id, records_by_id)
            source_record = records_by_id.get(source_id, {})
            locator = _single_line(ref.get("locator")) or _t(zh, "unspecified locator", "未指定定位")
            artifact = _single_line(ref.get("artifact")) or _t(zh, "unspecified artifact", "未指定材料")
            quote = str(ref.get("quote") or "").strip()
            lines.append(
                f"- {source_link} · {_artifact_markdown(project_root, source_record, ref, artifact)} · {_inline_code(locator)}"
            )
            if quote:
                for quote_line in quote.splitlines():
                    lines.append(f"> {_markdown_text(quote_line)}")
            else:
                lines.append("> " + _t(zh, "No verbatim quote recorded.", "尚未记录逐字证据。"))
            lines.extend(["", f"^{evidence_id}", ""])
    return lines[:-1]


def _render_unit_page(
    project_root: Path,
    record: dict[str, Any],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
    records_by_id: dict[str, dict[str, Any]],
    *,
    figure_index: dict[str, Any] | None = None,
    zh: bool = False,
) -> str:
    unit_id = str(record.get("id") or "")
    title = _single_line(record.get("title")) or unit_id
    topics = [str(item) for item in record.get("topics", []) if str(item).strip()]
    programs = [str(item) for item in record.get("program_ids", []) if str(item).strip()]
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    source_health = _source_materialization_summary(project_root, source)
    materialization_status = _single_line(source_health.get("status")) or "not_materialized"
    analysis_stage = _analysis_stage(record)
    properties: dict[str, Any] = {
        "id": unit_id,
        "kind": str(record.get("kind") or ""),
        "title": title,
        "aliases": [title] if title and title != unit_id else [],
        "status": str(record.get("status") or ""),
        "maturity": str(record.get("maturity") or ""),
        "confirmation_status": str(record.get("confirmation_status") or ""),
        "analysis_stage": analysis_stage,
        "materialization_status": materialization_status,
        "updated": str(record.get("updated_at") or record.get("created_at") or ""),
        "topics": [_wikilink(_topic_page_path(topic), display=topic) for topic in topics],
        "programs": [_wikilink(_program_page_path(program), display=program) for program in programs],
        "tags": sorted({str(item) for item in record.get("tags", []) if str(item).strip()}),
        "managed_by": "research-kb",
        "source_path": f"units/{UNIT_KIND_DIRS.get(str(record.get('kind') or ''), '')}/{unit_id}/record.yaml",
    }
    properties.update(_flat_relation_properties(unit_id, outgoing, incoming, records_by_id))
    summary = _display_summary(record, analysis_stage, zh=zh)
    concept_sections = _render_concept_sections(record, records_by_id, zh=zh)
    source_uri = _single_line(source.get("original_uri"))
    source_document = _source_document_link(project_root, source, zh=zh)
    repo_links = _local_repo_quick_links(project_root, record, zh=zh)
    primary_access = source_document or (" · ".join(repo_links) if repo_links else "")
    lines = [
        _frontmatter(properties).rstrip(),
        "",
        f"# {_markdown_text(title)}",
        "",
        f"## {_t(zh, 'Overview', '概览')}",
        "",
        summary,
        *(["", *concept_sections] if concept_sections else []),
        "",
        f"> [!info] {_t(zh, 'Quick access', '快速入口')}",
        "> " + (primary_access if primary_access else _t(zh, "No reading entry is available yet.", "暂时没有可用的阅读入口。")),
        "> " + (_source_markdown(source_uri, zh=zh) if source_uri else _t(zh, "No original source link is available.", "没有可用的原始来源链接。")),
        "",
        f"> [!{'success' if materialization_status == 'complete' else 'warning'}] {_t(zh, 'Source health', '来源健康')} · {_human_label(materialization_status, {'complete': '完整', 'degraded': '有局部限制', 'not_materialized': '未转换'} if zh else {}, fallback=_t(zh, 'Not materialized', '未转换'))}",
        "> " + (
            _t(zh, "The source has a complete Markdown reading view.", "原始材料已有完整的 Markdown 阅读页。")
            if materialization_status == "complete"
            else _t(zh, "The source is readable with limitations; see the notes below.", "材料可以阅读，但存在局部限制；详情见下方说明。")
            if materialization_status == "degraded"
            else _t(zh, "The source has not been converted to a Markdown reading view.", "该材料没有生成 Markdown 阅读页。")
        ),
        "",
        f"> [!{'warning' if analysis_stage == 'awaiting_confirmation' else 'todo' if analysis_stage == 'awaiting_analysis' else 'success'}] {_t(zh, 'Analysis', '分析状态')} · {_analysis_stage_label(analysis_stage, zh=zh)}",
        "> " + (
            _t(zh, "Review the pending evidence-backed claims and confirm or reject them.", "请检查下方有证据支持的待定判断，并决定确认或拒绝。")
            if analysis_stage == "awaiting_confirmation"
            else _t(zh, "Ask AI to analyze this material with verbatim evidence, or run `kb next`.", "可以让 AI 基于逐字证据分析这份材料，或运行 `kb next`。")
            if analysis_stage == "awaiting_analysis"
            else _t(zh, "Claims and evidence are available below.", "下方已列出判断及其证据。")
        ),
        "",
        f"## {_t(zh, 'Relationships', '关系')}",
        "",
        *_render_relations(unit_id, outgoing, incoming, records_by_id, zh=zh),
        "",
        f"## {_t(zh, 'Claims', '判断')}",
        "",
        *_render_claims(project_root, record, records_by_id, zh=zh),
    ]
    entries = figure_index.get("entries") if isinstance(figure_index, dict) else []
    entries = entries if isinstance(entries, list) else []
    if entries:
        lines.extend(["", f"## {_t(zh, 'Figures', '插图')}", ""])
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            ref_key = _single_line(entry.get("ref_key"))
            caption = _single_line(entry.get("caption"))
            page = entry.get("page")
            if not ref_key or not caption:
                continue
            lines.extend(
                [
                    f"### {_inline_code(ref_key)}",
                    "",
                    _markdown_text(caption),
                    "",
                    f"- {_t(zh, 'Page', '页码')}: {_inline_code(page)}",
                ]
            )
            assets = entry.get("assets") if isinstance(entry.get("assets"), list) else []
            for asset in assets:
                asset_path = _single_line(asset.get("path")) if isinstance(asset, dict) else ""
                if asset_path:
                    lines.extend(["", f"![[units/papers/{unit_id}/{asset_path}]]"])
            lines.append("")
    lines.extend(
        [
            "",
            f"## {_t(zh, 'Metadata', '元数据')}",
            "",
            f"- {_t(zh, 'Unit', '单元')}: {_inline_code(unit_id)}",
            f"- {_t(zh, 'Kind', '类型')}: {_inline_code(properties['kind'])}",
            f"- {_t(zh, 'Status', '状态')}: {_inline_code(properties['status'])}",
            f"- {_t(zh, 'Maturity', '成熟度')}: {_inline_code(properties['maturity'])}",
            f"- {_t(zh, 'Confirmation', '确认状态')}: {_inline_code(properties['confirmation_status'])}",
        ]
    )
    if source_uri:
        lines.append(f"- {_t(zh, 'Source', '来源')}: {_source_markdown(source_uri, zh=zh)}")
    if source_document:
        lines.append(f"- {_t(zh, 'Reading', '阅读页')}: {source_document}")
    output = source_health.get("output")
    output = output if isinstance(output, dict) else {}
    if output.get("document_characters") is not None:
        lines.append(f"- {_t(zh, 'Reading size', '正文长度')}: {_inline_code(output.get('document_characters'))} {_t(zh, 'characters', '字符')}")
    if output.get("image_count") is not None:
        lines.append(
            f"- {_t(zh, 'Images', '图片')}: {_inline_code(output.get('local_asset_reference_count', 0))} {_t(zh, 'local', '已本地化')} / "
            f"{_inline_code(output.get('image_count', 0))} {_t(zh, 'referenced', '处引用')}"
        )
    warnings = source_health.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.append(f"- {_t(zh, 'Source notes', '来源说明')}: " + "; ".join(_markdown_text(item) for item in warnings))
    if topics:
        lines.append(f"- {_t(zh, 'Topics', '主题')}: " + ", ".join(_wikilink(_topic_page_path(topic), display=topic) for topic in topics))
    if programs:
        lines.append(f"- {_t(zh, 'Programs', '研究项目')}: " + ", ".join(_wikilink(_program_page_path(program), display=program) for program in programs))
    lines.append("")
    return "\n".join(lines)


def _safe_records(project_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    base = units_root(project_root)
    issues: list[str] = []
    if base.is_symlink():
        return [], ["units-root-symlink"]
    if not base.exists():
        return [], []
    if not base.is_dir():
        return [], ["units-root-not-directory"]
    records: list[dict[str, Any]] = []
    for kind, directory_name in UNIT_KIND_DIRS.items():
        kind_root = base / directory_name
        if kind_root.is_symlink():
            issues.append(f"unit-kind-symlink:{kind}")
            continue
        if not kind_root.exists():
            continue
        if not kind_root.is_dir():
            issues.append(f"unit-kind-not-directory:{kind}")
            continue
        try:
            units = sorted(kind_root.iterdir(), key=lambda path: path.name)
        except OSError:
            issues.append(f"unit-kind-unreadable:{kind}")
            continue
        for unit in units:
            if unit.is_symlink():
                issues.append(f"unit-symlink:{kind}:{unit.name}")
                continue
            if not unit.is_dir():
                continue
            path = unit / "record.yaml"
            if path.is_symlink():
                issues.append(f"record-symlink:{kind}:{unit.name}")
                continue
            if not path.exists():
                continue
            if not path.is_file():
                issues.append(f"record-not-file:{kind}:{unit.name}")
                continue
            try:
                payload = load_yaml(path, default={})
            except (OSError, RuntimeError):
                issues.append(f"record-unreadable:{kind}:{unit.name}")
                continue
            if not isinstance(payload, dict):
                issues.append(f"record-invalid:{kind}:{unit.name}")
                continue
            try:
                records.append(normalize_record_schema(payload, project_root=project_root))
            except SystemExit:
                issues.append(f"record-schema-invalid:{kind}:{unit.name}")
    return sorted(records, key=lambda record: str(record.get("id") or "")), issues


def _safe_program_states(project_root: Path) -> tuple[list[dict[str, Any]], list[str]]:
    base = kb_root(project_root) / "programs"
    if base.is_symlink():
        return [], ["programs-root-symlink"]
    if not base.exists():
        return [], []
    if not base.is_dir():
        return [], ["programs-root-not-directory"]
    states: list[dict[str, Any]] = []
    issues: list[str] = []
    try:
        entries = sorted(base.iterdir(), key=lambda path: path.name)
    except OSError:
        return [], ["programs-root-unreadable"]
    for directory in entries:
        if directory.is_symlink():
            issues.append(f"program-symlink:{directory.name}")
            continue
        if not directory.is_dir():
            continue
        state_path = directory / "state.yaml"
        if state_path.is_symlink():
            issues.append(f"program-state-symlink:{directory.name}")
            continue
        if not state_path.exists():
            continue
        if not state_path.is_file():
            issues.append(f"program-state-not-file:{directory.name}")
            continue
        try:
            payload = load_yaml(state_path, default={})
        except (OSError, RuntimeError):
            issues.append(f"program-state-unreadable:{directory.name}")
            continue
        if isinstance(payload, dict):
            state = dict(payload)
            state.setdefault("program_id", directory.name)
            states.append(state)
        else:
            issues.append(f"program-state-invalid:{directory.name}")
    return states, issues


def _safe_taxonomy(project_root: Path) -> tuple[dict[str, Any], list[str]]:
    path = topic_taxonomy_path(project_root)
    if path.parent.is_symlink() or path.is_symlink():
        return {}, ["taxonomy-path-symlink"]
    if not path.exists():
        return {}, []
    if not path.is_file():
        return {}, ["taxonomy-not-file"]
    try:
        payload = load_yaml(path, default={})
    except (OSError, RuntimeError):
        return {}, ["taxonomy-unreadable"]
    return (payload, []) if isinstance(payload, dict) else ({}, ["taxonomy-invalid"])


def _safe_projection_locale(project_root: Path) -> tuple[str, list[str]]:
    path = kb_root(project_root) / "config/user-profile.yaml"
    if path.parent.is_symlink() or path.is_symlink():
        return "en", ["user-profile-path-symlink"]
    if not path.exists():
        return "en", []
    if not path.is_file():
        return "en", ["user-profile-not-file"]
    try:
        payload = load_yaml(path, default={})
    except (OSError, RuntimeError):
        return "en", ["user-profile-unreadable"]
    preferences = payload.get("preferences") if isinstance(payload, dict) else {}
    preferences = preferences if isinstance(preferences, dict) else {}
    language = _single_line(preferences.get("language_preference")).lower()
    return ("zh" if language.startswith("zh") else "en"), []


def _projection_inputs(project_root: Path) -> dict[str, Any]:
    records, record_issues = _safe_records(project_root)
    programs, program_issues = _safe_program_states(project_root)
    programs = sorted(programs, key=lambda state: str(state.get("program_id") or ""))
    taxonomy, taxonomy_issues = _safe_taxonomy(project_root)
    locale, locale_issues = _safe_projection_locale(project_root)
    figures: dict[str, dict[str, Any]] = {}
    for record in records:
        if record.get("kind") != "paper":
            continue
        unit_id = str(record.get("id") or "")
        payload = record.get("payload") if isinstance(record.get("payload"), dict) else {}
        projection = payload.get("figures") if isinstance(payload.get("figures"), dict) else {}
        index_artifact = str(projection.get("index_artifact") or "").strip()
        expected_digest = str(projection.get("index_digest") or "").strip()
        if not unit_id or projection.get("schema") != "figure-index/v1" or index_artifact != "figures.yaml" or not expected_digest:
            continue
        root = unit_root(project_root, "paper", unit_id)
        try:
            figures[unit_id] = load_current_figure_index(
                root / index_artifact,
                unit_root=root,
                project_root=project_root,
                expected_index_digest=expected_digest,
            )
        except FigureIndexError:
            continue
    digest_payload = {
        "schema": OBSIDIAN_PROJECTION_SCHEMA,
        "renderer_revision": OBSIDIAN_RENDERER_REVISION,
        "records": records,
        "programs": programs,
        "taxonomy": taxonomy,
        "locale": locale,
        "figures": figures,
    }
    return {
        "records": records,
        "programs": programs,
        "taxonomy": taxonomy,
        "locale": locale,
        "figures": figures,
        "input_issues": [*record_issues, *program_issues, *taxonomy_issues, *locale_issues],
        "input_digest": _sha256_text(_canonical_json(digest_payload)),
    }


def _render_program_page(
    state: dict[str, Any], records_by_id: dict[str, dict[str, Any]], *, zh: bool = False
) -> str:
    program_id = str(state.get("program_id") or "")
    title = _single_line(state.get("title")) or program_id
    raw_unit_ids = state.get("active_unit_ids", [])
    raw_unit_ids = raw_unit_ids if isinstance(raw_unit_ids, list) else []
    unit_ids = [str(item) for item in raw_unit_ids if str(item).strip()]
    properties = {
        "id": program_id,
        "kind": "program",
        "title": title,
        "aliases": [title] if title and title != program_id else [],
        "status": str(state.get("status") or ""),
        "stage": str(state.get("stage") or ""),
        "units": [_unit_link(unit_id, records_by_id) for unit_id in unit_ids],
        "managed_by": "research-kb",
        "source_path": f"programs/{program_id}/state.yaml",
    }
    lines = [
        _frontmatter(properties).rstrip(),
        "",
        f"# {_markdown_text(title)}",
        "",
        f"## {_t(zh, 'Goal', '目标')}",
        "",
        _markdown_text(state.get("goal")) or _t(zh, "No goal recorded.", "尚未记录目标。"),
        "",
        f"## {_t(zh, 'Research question', '研究问题')}",
        "",
        _markdown_text(state.get("question")) or _t(zh, "No research question recorded.", "尚未记录研究问题。"),
        "",
        f"## {_t(zh, 'Active units', '当前单元')}",
        "",
    ]
    lines.extend([f"- {_unit_link(unit_id, records_by_id)}" for unit_id in unit_ids] or [_t(zh, "No active units.", "暂无当前单元。")])
    lines.extend(["", f"## {_t(zh, 'Next actions', '下一步')}", ""])
    actions = state.get("next_actions", [])
    if isinstance(actions, list) and actions:
        for action in actions:
            if isinstance(action, dict):
                text = _single_line(action.get("summary") or action.get("action") or action.get("title") or action)
                status = _single_line(action.get("status"))
                lines.append(
                    f"- {_markdown_text(text)}" + (f" · {_inline_code(status)}" if status else "")
                )
            else:
                lines.append(f"- {_markdown_text(action)}")
    else:
        lines.append(_t(zh, "No next actions.", "暂无下一步行动。"))
    return "\n".join(lines).rstrip() + "\n"


def _topic_members(records: Iterable[dict[str, Any]]) -> dict[str, list[str]]:
    members: dict[str, list[str]] = defaultdict(list)
    for record in records:
        unit_id = str(record.get("id") or "")
        for topic in record.get("topics", []):
            topic_id = str(topic).strip()
            if topic_id and unit_id:
                members[topic_id].append(unit_id)
    return {topic: sorted(set(unit_ids)) for topic, unit_ids in members.items()}


def _render_topic_page(
    topic_id: str,
    item: dict[str, Any],
    unit_ids: list[str],
    records_by_id: dict[str, dict[str, Any]],
    *,
    zh: bool = False,
) -> str:
    raw_aliases = item.get("aliases", [])
    raw_aliases = raw_aliases if isinstance(raw_aliases, list) else []
    aliases = [_single_line(value) for value in raw_aliases if _single_line(value)]
    title = aliases[0] if aliases else _single_line(topic_id)
    properties = {
        "id": topic_id,
        "kind": "topic",
        "title": title,
        "aliases": sorted(set([topic_id, *aliases]) - {title}),
        "unit_count": len(unit_ids),
        "managed_by": "research-kb",
        "source_path": "config/topic-taxonomy.yaml",
    }
    lines = [
        _frontmatter(properties).rstrip(),
        "",
        f"# {_markdown_text(title)}",
        "",
        _markdown_text(item.get("note")) or _t(zh, "Canonical research topic.", "知识库中的规范研究主题。"),
        "",
        f"## {_t(zh, 'Units', '相关单元')}",
        "",
    ]
    lines.extend([f"- {_unit_link(unit_id, records_by_id)}" for unit_id in unit_ids] or [_t(zh, "No linked units.", "暂无关联单元。")])
    return "\n".join(lines).rstrip() + "\n"


def _base_file(*, name: str, view_filter: str = "", group_by: str = "", zh: bool = False) -> str:
    view: dict[str, Any] = {
        "type": "table",
        "name": name,
    }
    if view_filter:
        view["filters"] = {"and": [view_filter]}
    if group_by:
        view["groupBy"] = {"property": group_by, "direction": "ASC"}
    # Obsidian 1.12.7 saves filters/groupBy before order and indents block
    # sequences.  Emit that byte-canonical form directly so merely opening a
    # generated Base never looks like a human edit to the manifest guard.
    view["order"] = [
        "file.name",
        "title",
        "kind",
        "analysis_stage",
        "materialization_status",
        "confirmation_status",
        "topics",
        "updated",
    ]
    payload = {
        "filters": {
            "and": [
                'file.inFolder("obsidian/managed/units")',
                'file.ext == "md"',
            ]
        },
        "properties": {
            "title": {"displayName": _t(zh, "Title", "标题")},
            "kind": {"displayName": _t(zh, "Kind", "类型")},
            "status": {"displayName": _t(zh, "Status", "状态")},
            "maturity": {"displayName": _t(zh, "Maturity", "成熟度")},
            "confirmation_status": {"displayName": _t(zh, "Confirmation", "确认状态")},
            "analysis_stage": {"displayName": _t(zh, "Analysis", "分析状态")},
            "materialization_status": {"displayName": _t(zh, "Source health", "来源健康")},
            "topics": {"displayName": _t(zh, "Topics", "主题")},
            "programs": {"displayName": _t(zh, "Programs", "研究项目")},
            "updated": {"displayName": _t(zh, "Updated", "更新时间")},
        },
        "views": [view],
    }
    return dump_yaml(payload, width=1_000_000, indent_sequences=True)


def _legacy_obsidian_normalized_base(relative: str) -> dict[str, Any] | None:
    """Known Obsidian 1.12 normalization of renderer revision 3 Base files.

    This narrow migration exception lets a generated v3 projection converge to
    v4 without treating Obsidian's own ``note.foo`` -> ``foo`` rewrite as a
    human edit.  Any other semantic or structural change remains a conflict.
    """
    definitions = {
        "dashboards/All Units.base": ("All units", "", ""),
        "dashboards/Pending Review.base": (
            "Pending review",
            'confirmation_status == "pending_user_confirmation"',
            "",
        ),
        "dashboards/By Topic.base": ("By topic", "", "topics"),
    }
    definition = definitions.get(relative)
    if definition is None:
        return None
    name, view_filter, group_by = definition
    view: dict[str, Any] = {
        "type": "table",
        "name": name,
        "order": [
            "file.name",
            "title",
            "kind",
            "status",
            "maturity",
            "confirmation_status",
            "topics",
            "programs",
        ],
    }
    if view_filter:
        view["filters"] = {"and": [view_filter]}
    if group_by:
        view["groupBy"] = {"property": group_by, "direction": "ASC"}
    return {
        "filters": {"and": ['file.inFolder("obsidian/managed/units")', 'file.ext == "md"']},
        "properties": {
            "title": {"displayName": "Title"},
            "kind": {"displayName": "Kind"},
            "status": {"displayName": "Status"},
            "maturity": {"displayName": "Maturity"},
            "confirmation_status": {"displayName": "Confirmation"},
            "topics": {"displayName": "Topics"},
            "programs": {"displayName": "Programs"},
        },
        "views": [view],
    }


def _render_home(
    project_root: Path,
    generated_at: str,
    records: list[dict[str, Any]],
    programs: list[dict[str, Any]],
    *,
    zh: bool = False,
) -> str:
    records_by_id = {str(record.get("id") or ""): record for record in records}
    kind_counts: dict[str, int] = defaultdict(int)
    pending = 0
    degraded = 0
    for record in records:
        kind_counts[str(record.get("kind") or "unknown")] += 1
        if _analysis_stage(record) == "awaiting_confirmation":
            pending += 1
        source = record.get("source") if isinstance(record.get("source"), dict) else {}
        if _source_materialization_summary(project_root, source).get("status") == "degraded":
            degraded += 1
    recent = sorted(
        records,
        key=lambda record: str(record.get("updated_at") or record.get("created_at") or ""),
        reverse=True,
    )[:8]
    lines = [
            _frontmatter(
                {
                    "id": "research-kb-home",
                    "kind": "dashboard",
                    "title": _t(zh, "Research KB", "研究知识库"),
                    "managed_by": "research-kb",
                }
            ).rstrip(),
            "",
            f"# {_t(zh, 'Research KB', '研究知识库')}",
            "",
            _t(zh, "Your human-readable entry point to the canonical research knowledge base.", "这里是知识库的主要阅读与导航入口。"),
            "",
            f"> [!summary] {_t(zh, 'Current state', '当前状态')}",
            f"> **{len(records)}** {_t(zh, 'units', '个单元')} · **{len(programs)}** {_t(zh, 'programs', '个研究项目')} · **{pending}** {_t(zh, 'awaiting confirmation', '项等待确认')} · **{degraded}** {_t(zh, 'sources need attention', '份来源需留意')}",
            "",
            f"## {_t(zh, 'Start here', '从这里开始')}",
            "",
            f"- [[obsidian/managed/dashboards/All Units.base|{_t(zh, 'Browse all units', '浏览全部单元')}]]",
            f"- [[obsidian/managed/dashboards/Pending Review.base|{_t(zh, 'Browse pending conclusions (read-only overview)', '浏览待确认判断（只读总览）')}]]",
            f"- [[obsidian/managed/dashboards/By Topic.base|{_t(zh, 'Explore by topic', '按主题浏览')}]]",
            "",
            f"## {_t(zh, 'Library overview', '资料概览')}",
            "",
        ]
    lines.extend(
        [f"- {_human_label(kind, {}, fallback=_t(zh, 'Unknown', '未知'))}: **{count}**" for kind, count in sorted(kind_counts.items())]
        or [_t(zh, "No material has been added yet.", "尚未添加任何资料。")]
    )
    lines.extend(["", f"## {_t(zh, 'Recently updated', '最近更新')}", ""])
    lines.extend(
        [
            f"- {_unit_link(str(record.get('id') or ''), records_by_id)} · "
            f"{_analysis_stage_label(_analysis_stage(record), zh=zh)}"
            for record in recent
        ]
        or [_t(zh, "No recent units.", "暂无最近更新的单元。")]
    )
    lines.extend(
        [
            "",
            f"> [!tip] {_t(zh, 'Reading view', '阅读视图')}",
            "> " + _t(zh, "Generated pages are designed for Obsidian Reading view. Use the book icon in the upper-right; editor mode intentionally shows wikilinks and block IDs.", "生成页面针对 Obsidian 阅读视图优化。请使用右上角书本图标；编辑模式会按设计显示双向链接和块 ID 源码。"),
            "",
            f"## {_t(zh, 'Human notes', '人工笔记')}",
            "",
            _t(zh, "- Put unprocessed notes in `obsidian/inbox/`.", "- 未整理笔记请放在 `obsidian/inbox/`。"),
            _t(zh, "- Put durable human commentary in `obsidian/annotations/`.", "- 需要长期保留的人工批注请放在 `obsidian/annotations/`。"),
            _t(
                zh,
                "- Editable review sheets may appear in annotations after you ask the Agent; checkbox changes are drafts until you return to the conversation and explicitly authorize sync.",
                "- 让 Agent 生成待确认表后，可直接在人工批注区勾选；勾选只是草稿，必须回到对话明确授权同步才会生效。",
            ),
            "",
            f"> [!warning] {_t(zh, 'Managed projection', '受管投影')}",
            "> " + _t(zh, "Files below `obsidian/managed` are generated. Put human-authored notes in inbox or annotations.", "`obsidian/managed` 下的文件会自动生成；人工内容请写入 inbox 或 annotations。"),
            "",
            f"<small>{_t(zh, 'Projection refreshed', '投影更新时间')} {generated_at}.</small>",
            "",
        ]
    )
    return "\n".join(lines)


def _base_projection_files(inputs: dict[str, Any]) -> dict[str, str]:
    zh = str(inputs.get("locale") or "en") == "zh"
    return {
        "dashboards/All Units.base": _base_file(name=_t(zh, "All units", "全部单元"), zh=zh),
        "dashboards/Pending Review.base": _base_file(
            name=_t(zh, "Pending review", "待确认"),
            view_filter='analysis_stage == "awaiting_confirmation"',
            zh=zh,
        ),
        "dashboards/By Topic.base": _base_file(
            name=_t(zh, "By topic", "按主题"), group_by="topics", zh=zh
        ),
    }


def _projection_files(project_root: Path, inputs: dict[str, Any], *, generated_at: str) -> dict[str, str]:
    records = inputs["records"]
    programs = inputs["programs"]
    taxonomy = inputs["taxonomy"]
    zh = str(inputs.get("locale") or "en") == "zh"
    figures = inputs.get("figures") if isinstance(inputs.get("figures"), dict) else {}
    records_by_id = {str(record.get("id") or ""): record for record in records if str(record.get("id") or "")}
    edges = project_relation_edges(records)
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        outgoing[str(edge["source_id"])].append(edge)
        incoming[str(edge["target_id"])].append(edge)

    files: dict[str, str] = {"Home.md": _render_home(project_root, generated_at, records, programs, zh=zh)}
    for record in records:
        unit_id = str(record.get("id") or "")
        if not unit_id:
            continue
        files[f"units/{_safe_component(unit_id, fallback='unit')}.md"] = _render_unit_page(
            project_root,
            record,
            outgoing,
            incoming,
            records_by_id,
            figure_index=figures.get(unit_id) if isinstance(figures.get(unit_id), dict) else None,
            zh=zh,
        )
    for state in programs:
        program_id = str(state.get("program_id") or "")
        if program_id:
            files[f"programs/{_safe_component(program_id, fallback='program')}.md"] = _render_program_page(
                state, records_by_id, zh=zh
            )
    topic_items = taxonomy.get("topics", {}) if isinstance(taxonomy, dict) else {}
    topic_items = topic_items if isinstance(topic_items, dict) else {}
    members = _topic_members(records)
    for topic_id in sorted(set(topic_items) | set(members)):
        item = topic_items.get(topic_id, {})
        item = item if isinstance(item, dict) else {}
        files[f"topics/{_safe_component(topic_id, fallback='topic')}.md"] = _render_topic_page(
            topic_id, item, members.get(topic_id, []), records_by_id, zh=zh
        )
    files.update(_base_projection_files(inputs))
    return dict(sorted(files.items()))


def _manifest_files(manifest: dict[str, Any]) -> dict[str, str]:
    values = manifest.get("files")
    if not isinstance(values, dict):
        return {}
    return {str(path): str(digest) for path, digest in values.items() if str(path) and str(digest)}


def _strict_manifest_files(manifest: dict[str, Any]) -> dict[str, str] | None:
    values = manifest.get("files")
    if not isinstance(values, dict) or not values:
        return None
    files: dict[str, str] = {}
    for relative, digest in values.items():
        if (
            not isinstance(relative, str)
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
        ):
            return None
        try:
            _validate_relative_managed_path(relative)
        except SystemExit:
            return None
        files[relative] = digest
    return files


def _manifest_renderer_revision(manifest: dict[str, Any]) -> int:
    value = manifest.get("renderer_revision")
    if isinstance(value, bool):
        return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _validate_relative_managed_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise SystemExit(f"Invalid Obsidian managed path: {value!r}")
    if path.name == MANIFEST_NAME:
        raise SystemExit("The Obsidian manifest cannot own itself.")
    return path


def _managed_path(managed: Path, relative: str) -> Path:
    pure = _validate_relative_managed_path(relative)
    candidate = managed.joinpath(*pure.parts)
    current = managed
    for part in pure.parts[:-1]:
        current = current / part
        if current.is_symlink():
            raise SystemExit(f"Obsidian managed path traverses a symlink: {relative}")
    return candidate


def _load_manifest(project_root: Path) -> tuple[dict[str, Any] | None, str]:
    managed = obsidian_managed_root(project_root)
    if managed.is_symlink() or (managed.exists() and not managed.is_dir()):
        return None, "managed-root-unsafe"
    path = obsidian_manifest_path(project_root)
    if path.is_symlink():
        return None, "manifest-is-symlink"
    if not path.exists():
        return None, "missing"
    if not path.is_file():
        return None, "manifest-not-file"
    try:
        payload = load_yaml(path, default={})
    except (OSError, RuntimeError):
        return None, "manifest-unreadable"
    if not isinstance(payload, dict) or payload.get("schema") != OBSIDIAN_PROJECTION_SCHEMA:
        return None, "manifest-invalid"
    try:
        for relative in _manifest_files(payload):
            _validate_relative_managed_path(relative)
    except SystemExit:
        return None, "manifest-invalid-path"
    return payload, "ok"


def _managed_tree_has_content(managed: Path) -> bool:
    if managed.is_symlink() or not managed.exists():
        return managed.is_symlink()
    if not managed.is_dir():
        return True
    try:
        with os.scandir(managed) as entries:
            return next(entries, None) is not None
    except OSError:
        return True


def _safe_managed_entries(managed: Path) -> tuple[set[str], set[str]]:
    """Return regular files and unsafe entries without following symlinks."""
    files: set[str] = set()
    unsafe: set[str] = set()
    if managed.is_symlink() or not managed.is_dir():
        return files, unsafe
    for current, dirnames, filenames in os.walk(managed, topdown=True, followlinks=False):
        current_path = Path(current)
        safe_dirs: list[str] = []
        for name in dirnames:
            path = current_path / name
            relative = path.relative_to(managed).as_posix()
            if path.is_symlink():
                unsafe.add(relative)
            else:
                safe_dirs.append(name)
        dirnames[:] = safe_dirs
        for name in filenames:
            path = current_path / name
            relative = path.relative_to(managed).as_posix()
            if path.is_symlink() or not path.is_file():
                unsafe.add(relative)
            elif relative != MANIFEST_NAME:
                files.add(relative)
    return files, unsafe


def _preflight_update(
    managed: Path,
    previous: dict[str, Any] | None,
    desired: dict[str, str],
) -> list[str]:
    conflicts: list[str] = []
    previous_files = _manifest_files(previous or {})
    current_files, unsafe_entries = _safe_managed_entries(managed)
    conflicts.extend(unsafe_entries)
    conflicts.extend(current_files - set(previous_files) - set(desired))
    for relative, text in desired.items():
        try:
            path = _managed_path(managed, relative)
        except SystemExit:
            conflicts.append(relative)
            continue
        if path.is_symlink() or (path.exists() and not path.is_file()):
            conflicts.append(relative)
            continue
        if not path.exists():
            continue
        current_digest = _file_sha256(path)
        desired_digest = _sha256_text(text)
        if current_digest == desired_digest:
            continue
        previous_digest = previous_files.get(relative)
        if previous_digest is not None and current_digest == previous_digest:
            continue
        legacy_expected = (
            _legacy_obsidian_normalized_base(relative)
            if _manifest_renderer_revision(previous) == 3
            else None
        )
        if legacy_expected is not None:
            try:
                current_payload = load_yaml(path, default={})
            except (OSError, RuntimeError):
                current_payload = None
            if current_payload == legacy_expected:
                continue
        conflicts.append(relative)

    for relative, previous_digest in previous_files.items():
        if relative in desired:
            continue
        try:
            path = _managed_path(managed, relative)
        except SystemExit:
            conflicts.append(relative)
            continue
        if not path.exists() and not path.is_symlink():
            continue
        if path.is_symlink() or not path.is_file() or _file_sha256(path) != previous_digest:
            conflicts.append(relative)
    return sorted(set(conflicts))


def _base_sort_is_presentation_only(current: dict[str, Any], desired: dict[str, Any]) -> tuple[bool, int]:
    """Recognize only the exact sort shape saved by Obsidian 1.12.7.

    ``sort`` remains a user-side presentation preference.  Recognition never
    adopts it into renderer output; a separately authorized repair resets the
    file to the current renderer bytes.
    """
    current_views = current.get("views")
    desired_views = desired.get("views")
    if not isinstance(current_views, list) or not isinstance(desired_views, list):
        return False, 0
    if not current_views or len(current_views) != len(desired_views):
        return False, 0
    normalized = deepcopy(current)
    normalized_views = normalized.get("views")
    if not isinstance(normalized_views, list):  # pragma: no cover - guarded above
        return False, 0
    sort_count = 0
    for index, (current_view, desired_view) in enumerate(zip(current_views, desired_views)):
        if not isinstance(current_view, dict) or not isinstance(desired_view, dict):
            return False, 0
        if "sort" in desired_view:
            return False, 0
        extra_keys = set(current_view) - set(desired_view)
        if extra_keys not in (set(), {"sort"}):
            return False, 0
        if "sort" not in current_view:
            continue
        sort_items = current_view.get("sort")
        order = desired_view.get("order")
        if (
            not isinstance(sort_items, list)
            or not sort_items
            or len(sort_items) > 32
            or not isinstance(order, list)
            or not all(isinstance(item, str) and item for item in order)
        ):
            return False, 0
        properties: set[str] = set()
        for item in sort_items:
            if not isinstance(item, dict) or set(item) != {"property", "direction"}:
                return False, 0
            property_name = item.get("property")
            direction = item.get("direction")
            if (
                not isinstance(property_name, str)
                or property_name not in order
                or property_name in properties
                or not isinstance(direction, str)
                or direction not in _OBSIDIAN_BASE_SORT_DIRECTIONS
            ):
                return False, 0
            properties.add(property_name)
        normalized_view = normalized_views[index]
        if not isinstance(normalized_view, dict):  # pragma: no cover - deepcopy preserves the shape
            return False, 0
        normalized_view.pop("sort", None)
        sort_count += len(sort_items)
    return normalized == desired and sort_count > 0, sort_count


def _strict_base_payload(raw_bytes: bytes) -> dict[str, Any] | None:
    try:
        payload = load_yaml_mapping_bytes_strict(raw_bytes)
    except (RuntimeError, StrictYamlError):
        return None
    if not all(isinstance(key, str) for key in payload):
        return None
    return payload


def _presentation_sort_candidate(
    project_root: Path,
    *,
    relative: str,
    expected_digest: str,
    desired_text: str,
) -> dict[str, Any] | None:
    if relative not in OBSIDIAN_BASE_PRESENTATION_FILES:
        return None
    desired_digest = _sha256_text(desired_text)
    if expected_digest != desired_digest:
        return None
    project_relative = f"kb/obsidian/managed/{relative}"
    snapshot = snapshot_project_file(project_root, project_relative, max_bytes=_OBSIDIAN_BASE_MAX_BYTES)
    if snapshot is None or snapshot.byte_sha256 == desired_digest:
        return None
    current_payload = _strict_base_payload(snapshot.raw_bytes)
    desired_payload = _strict_base_payload(desired_text.encode("utf-8"))
    if current_payload is None or desired_payload is None:
        return None
    presentation_only, sort_count = _base_sort_is_presentation_only(current_payload, desired_payload)
    if not presentation_only or not snapshot.is_current():
        return None
    return {
        "relative": relative,
        "path": snapshot.path,
        "current_digest": snapshot.byte_sha256,
        "desired_digest": desired_digest,
        "desired_text": desired_text,
        "sort_count": sort_count,
    }


def _base_presentation_reset_preview(
    project_root: Path,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Build a pure-read, exact-byte preview for a reset-to-renderer repair."""
    inputs = _projection_inputs(project_root)
    if inputs["input_issues"]:
        raise SystemExit("Canonical projection inputs are unsafe; presentation reset was not prepared.")
    manifest_snapshot = snapshot_project_file(
        project_root,
        "kb/obsidian/managed/manifest.yaml",
        max_bytes=_OBSIDIAN_BASE_MAX_BYTES,
    )
    if manifest_snapshot is None:
        raise SystemExit("The Obsidian projection manifest is unavailable; presentation reset was not prepared.")
    manifest = _strict_base_payload(manifest_snapshot.raw_bytes)
    if manifest is None or manifest.get("schema") != OBSIDIAN_PROJECTION_SCHEMA:
        raise SystemExit("The Obsidian projection manifest is invalid; presentation reset was not prepared.")
    manifest_files = _strict_manifest_files(manifest)
    if manifest_files is None:
        raise SystemExit("The Obsidian projection manifest is invalid; presentation reset was not prepared.")
    if (
        _manifest_renderer_revision(manifest) != OBSIDIAN_RENDERER_REVISION
        or str(manifest.get("input_digest") or "") != inputs["input_digest"]
    ):
        raise SystemExit("The Obsidian projection is stale; refresh it before preparing presentation reset.")
    managed = obsidian_managed_root(project_root)
    current_files, unsafe_entries = _safe_managed_entries(managed)
    if unsafe_entries or current_files != set(manifest_files):
        raise SystemExit("The Obsidian managed area contains unsafe or unowned content; nothing was reset.")
    desired_bases = _base_projection_files(inputs)
    candidates: list[dict[str, Any]] = []
    for relative, expected_digest in sorted(manifest_files.items()):
        path = _managed_path(managed, relative)
        if path.is_symlink() or not path.is_file():
            raise SystemExit("A managed projection path is unsafe or missing; nothing was reset.")
        if relative in OBSIDIAN_BASE_PRESENTATION_FILES:
            current_snapshot = snapshot_project_file(
                project_root,
                f"kb/obsidian/managed/{relative}",
                max_bytes=_OBSIDIAN_BASE_MAX_BYTES,
            )
            if current_snapshot is None:
                raise SystemExit("A managed Base is unsafe, oversized, or unreadable; nothing was reset.")
            current_digest = current_snapshot.byte_sha256
        else:
            current_digest = _file_sha256(path)
        if current_digest == expected_digest:
            continue
        desired_text = desired_bases.get(relative)
        if desired_text is None:
            raise SystemExit("Managed projection drift is not an allowlisted Base sort change; nothing was reset.")
        candidate = _presentation_sort_candidate(
            project_root,
            relative=relative,
            expected_digest=expected_digest,
            desired_text=desired_text,
        )
        if candidate is None:
            raise SystemExit("Managed projection drift is not an allowlisted Base sort change; nothing was reset.")
        candidates.append(candidate)
    if not manifest_snapshot.is_current():
        raise SystemExit("The Obsidian projection changed while preparing the preview; retry from current state.")
    if not candidates:
        return {
            "schema": OBSIDIAN_BASE_PRESENTATION_RESET_SCHEMA,
            "status": "no_presentation_drift",
            "preview_digest": "",
            "file_count": 0,
            "sort_count": 0,
            "files": [],
        }, []
    binding = {
        "schema": OBSIDIAN_BASE_PRESENTATION_RESET_SCHEMA,
        "renderer_revision": OBSIDIAN_RENDERER_REVISION,
        "input_digest": inputs["input_digest"],
        "manifest_digest": manifest_snapshot.byte_sha256,
        "files": [
            {
                "relative": item["relative"],
                "current_digest": item["current_digest"],
                "desired_digest": item["desired_digest"],
                "sort_count": item["sort_count"],
            }
            for item in candidates
        ],
    }
    preview_digest = _sha256_text(_canonical_json(binding))
    return {
        "schema": OBSIDIAN_BASE_PRESENTATION_RESET_SCHEMA,
        "status": "needs_user_authorization",
        "preview_digest": preview_digest,
        "file_count": len(candidates),
        "sort_count": sum(int(item["sort_count"]) for item in candidates),
        "files": [Path(str(item["relative"])).name for item in candidates],
    }, candidates


def preview_obsidian_base_presentation_reset(project_root: Path) -> dict[str, Any]:
    """Return a redacted, zero-write preview for allowlisted Base sort drift."""
    preview, _candidates = _base_presentation_reset_preview(project_root)
    return preview


def reset_obsidian_base_presentation_drift(
    project_root: Path,
    *,
    expected_preview_digest: str,
    user_authorization: str,
    authorization_source: str,
) -> dict[str, Any]:
    """Reset allowlisted Base sort drift after exact preview-bound authorization."""
    if not str(user_authorization or "").strip() or authorization_source != "user_message":
        raise SystemExit("Base presentation reset requires current-message user authorization.")
    expected = str(expected_preview_digest or "").strip()
    preview, candidates = _base_presentation_reset_preview(project_root)
    if (
        preview.get("status") != "needs_user_authorization"
        or not expected
        or expected != preview.get("preview_digest")
    ):
        raise SystemExit("The authorized Base presentation preview is stale; request a fresh preview.")
    targets = [Path(item["path"]) for item in candidates]
    with mutation_transaction(
        project_root,
        "reset_obsidian_base_presentation_sort",
        targets,
        operation_role="derived",
    ):
        locked_preview, locked_candidates = _base_presentation_reset_preview(project_root)
        if locked_preview.get("preview_digest") != expected:
            raise SystemExit("The Base presentation drift changed after authorization; nothing was reset.")
        if [item["relative"] for item in locked_candidates] != [item["relative"] for item in candidates]:
            raise SystemExit("The Base presentation reset target set changed; nothing was reset.")
        for item in locked_candidates:
            write_text_if_changed(Path(item["path"]), str(item["desired_text"]))
    refreshed = update_obsidian_projection(project_root)
    final_status = obsidian_projection_status(project_root)
    blocking_codes = {
        "OBSIDIAN_BASE_PRESENTATION_SORT_DRIFT",
        "OBSIDIAN_MANAGED_FILE_DRIFT",
        "OBSIDIAN_MANAGED_FILE_MISSING",
        "OBSIDIAN_MANAGED_FILE_UNOWNED",
        "OBSIDIAN_MANAGED_PATH_UNSAFE",
        "OBSIDIAN_HUMAN_PATH_UNSAFE",
        "OBSIDIAN_PROJECTION_STALE",
    }
    if any(finding.get("code") in blocking_codes for finding in final_status.get("findings", [])):
        raise SystemExit("The Base presentation reset did not converge; detailed state was preserved for recovery.")
    return {
        "changed": True,
        "file_count": len(candidates),
        "sort_count": sum(int(item["sort_count"]) for item in candidates),
        "preview_digest": expected,
        "projection_changed": bool(refreshed.get("changed")),
        "status": final_status,
    }


def _remove_empty_generated_dirs(managed: Path, paths: Iterable[Path]) -> None:
    candidates: set[Path] = set()
    for path in paths:
        current = path.parent
        while current != managed and managed in current.parents:
            candidates.add(current)
            current = current.parent
    for directory in sorted(candidates, key=lambda path: len(path.parts), reverse=True):
        if directory.is_symlink() or not directory.is_dir():
            continue
        try:
            directory.rmdir()
        except OSError:
            pass


def update_obsidian_projection(project_root: Path) -> dict[str, Any]:
    """Rebuild the managed projection without traversing human-authored areas."""
    canonical_root = kb_root(project_root)
    if canonical_root.is_symlink() or (canonical_root.exists() and not canonical_root.is_dir()):
        raise SystemExit("The canonical KB root is not a safe directory.")
    inputs = _projection_inputs(project_root)
    if inputs["input_issues"]:
        raise SystemExit("Unsafe or invalid canonical projection inputs were preserved for review.")
    previous, manifest_state = _load_manifest(project_root)
    root = obsidian_root(project_root)
    managed = obsidian_managed_root(project_root)
    gitignore_path = kb_gitignore_path(project_root)
    gitignore_ready = False
    if gitignore_path.is_file() and not gitignore_path.is_symlink():
        gitignore_ready = "obsidian/managed/" in gitignore_path.read_text(encoding="utf-8").splitlines()
    if root.is_symlink() or (root.exists() and not root.is_dir()):
        raise SystemExit("Obsidian projection root is not a safe directory.")
    if managed.is_symlink() or (managed.exists() and not managed.is_dir()):
        raise SystemExit("Obsidian managed root is not a safe directory.")
    if manifest_state not in {"ok", "missing"}:
        raise SystemExit("Existing Obsidian projection manifest is invalid; managed files were preserved.")
    if manifest_state == "missing" and _managed_tree_has_content(managed):
        raise SystemExit("Unowned files already exist in the Obsidian managed area; nothing was overwritten.")

    if (
        previous
        and _manifest_renderer_revision(previous) == OBSIDIAN_RENDERER_REVISION
        and str(previous.get("input_digest") or "") == inputs["input_digest"]
    ):
        current_status = obsidian_projection_status(project_root)
        human_dirs_ready = all((root / name).is_dir() and not (root / name).is_symlink() for name in HUMAN_DIRS)
        rewrite_codes = {
            "OBSIDIAN_PROJECTION_STALE",
            "OBSIDIAN_MANAGED_FILE_MISSING",
            "OBSIDIAN_MANAGED_FILE_DRIFT",
            "OBSIDIAN_BASE_PRESENTATION_SORT_DRIFT",
            "OBSIDIAN_MANAGED_PATH_UNSAFE",
            "OBSIDIAN_MANAGED_FILE_UNOWNED",
        }
        if (
            not rewrite_codes.intersection({item["code"] for item in current_status["findings"]})
            and human_dirs_ready
            and gitignore_ready
        ):
            return {
                "changed": False,
                "input_digest": inputs["input_digest"],
                "generated_at": str(previous.get("generated_at") or ""),
                "file_count": len(_manifest_files(previous)),
                "status": current_status,
            }

    generated_at = utc_now_iso()
    desired = _projection_files(project_root, inputs, generated_at=generated_at)
    conflicts = _preflight_update(managed, previous, desired)
    for name in HUMAN_DIRS:
        human_path = root / name
        if human_path.is_symlink() or (human_path.exists() and not human_path.is_dir()):
            conflicts.append(f"../{name}")
    if conflicts:
        raise SystemExit(
            "Obsidian managed files contain unowned or human-edited content; preserved: "
            + ", ".join(sorted(set(conflicts)))
        )

    manifest = {
        "schema": OBSIDIAN_PROJECTION_SCHEMA,
        "renderer_revision": OBSIDIAN_RENDERER_REVISION,
        "generated_at": generated_at,
        "input_digest": inputs["input_digest"],
        "record_count": len(inputs["records"]),
        "program_count": len(inputs["programs"]),
        "files": {relative: _sha256_text(text) for relative, text in desired.items()},
    }
    missing_human_dirs = [root / name for name in HUMAN_DIRS if not (root / name).exists()]
    targets = [managed, *missing_human_dirs, *([] if gitignore_ready else [gitignore_path])]
    with mutation_transaction(
        project_root,
        "rebuild_obsidian_projection",
        targets,
        operation_role="derived",
    ):
        locked_inputs = _projection_inputs(project_root)
        if locked_inputs["input_issues"] or locked_inputs["input_digest"] != inputs["input_digest"]:
            raise SystemExit("Canonical projection inputs changed during the update; retry from current state.")
        locked_previous, locked_manifest_state = _load_manifest(project_root)
        if locked_manifest_state not in {"ok", "missing"}:
            raise SystemExit("The Obsidian projection changed to an invalid state during the update.")
        locked_conflicts = _preflight_update(managed, locked_previous, desired)
        for name in HUMAN_DIRS:
            human_path = root / name
            if human_path.is_symlink() or (human_path.exists() and not human_path.is_dir()):
                locked_conflicts.append(f"../{name}")
        if locked_conflicts:
            raise SystemExit("Obsidian projection files changed during the update; all concurrent content was preserved.")
        if gitignore_ready and (
            not gitignore_path.is_file()
            or gitignore_path.is_symlink()
            or "obsidian/managed/" not in gitignore_path.read_text(encoding="utf-8").splitlines()
        ):
            raise SystemExit("The KB ignore policy changed during the update; retry from current state.")

        managed.mkdir(parents=True, exist_ok=True)
        for human_path in missing_human_dirs:
            if not human_path.exists():
                human_path.mkdir(parents=True, exist_ok=False)
        if not gitignore_ready:
            ensure_kb_gitignore(project_root)
        for relative, text in desired.items():
            write_text_if_changed(_managed_path(managed, relative), text)
        removed: list[Path] = []
        for relative in sorted(set(_manifest_files(locked_previous or {})) - set(desired)):
            path = _managed_path(managed, relative)
            if path.exists() and not path.is_symlink():
                path.unlink()
                removed.append(path)
        _remove_empty_generated_dirs(managed, removed)
        write_yaml_if_changed(obsidian_manifest_path(project_root), manifest)

    return {
        "changed": True,
        "input_digest": inputs["input_digest"],
        "generated_at": generated_at,
        "file_count": len(desired),
        "status": obsidian_projection_status(project_root),
    }


def _finding(code: str, severity: str, subject: str, message: str) -> dict[str, str]:
    return {"code": code, "severity": severity, "subject": subject, "message": message}


def _locator_issue(
    locator: Any,
    *,
    unit_id: str,
    records_by_id: dict[str, dict[str, Any]],
) -> str:
    if not isinstance(locator, dict):
        return ""
    record = records_by_id.get(unit_id)
    if record is None:
        return "missing-unit"
    kind = str(locator.get("kind") or "")
    value = str(locator.get("value") or "")
    headings, blocks = _available_unit_anchors(record)
    if kind == "heading" and value not in headings:
        return "missing-heading"
    if kind == "block" and (not BLOCK_ID_RE.fullmatch(value) or value not in blocks):
        return "missing-block"
    return ""


def _relation_findings(records: list[dict[str, Any]]) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    records_by_id = {str(record.get("id") or ""): record for record in records if str(record.get("id") or "")}
    for edge in project_relation_edges(records):
        source_id = str(edge["source_id"])
        target_id = str(edge["target_id"])
        subject = f"{source_id}:{edge['relation']}:{target_id}"
        if target_id not in records_by_id:
            findings.append(
                _finding("OBSIDIAN_LINK_TARGET_MISSING", "error", subject, "A canonical relation targets a missing unit.")
            )
            continue
        for field, unit_id in (("source_locator", source_id), ("target_locator", target_id)):
            issue = _locator_issue(edge.get(field), unit_id=unit_id, records_by_id=records_by_id)
            if issue:
                findings.append(
                    _finding(
                        "OBSIDIAN_LOCATOR_UNRESOLVED",
                        "error",
                        subject,
                        f"The {field} does not resolve in the generated unit page ({issue}).",
                    )
                )
        if edge.get("provenance") == "legacy_reverse":
            findings.append(
                _finding(
                    "OBSIDIAN_LEGACY_REVERSE_LINK",
                    "warning",
                    subject,
                    "An orphan legacy reverse relation is preserved as a derived forward edge.",
                )
            )
    return findings


def _projection_link_findings(
    project_root: Path,
    records: list[dict[str, Any]],
    programs: list[dict[str, Any]],
) -> list[dict[str, str]]:
    findings: list[dict[str, str]] = []
    record_ids = {str(record.get("id") or "") for record in records if str(record.get("id") or "")}
    program_ids = {
        str(state.get("program_id") or "") for state in programs if str(state.get("program_id") or "")
    }
    for record in records:
        unit_id = str(record.get("id") or "")
        source = record.get("source") if isinstance(record.get("source"), dict) else {}
        markdown_path = str(source.get("markdown_path") or "").strip()
        if markdown_path:
            document = _canonical_source_path(project_root, markdown_path, suffix=".md")
            if document is None:
                findings.append(
                    _finding(
                        "OBSIDIAN_SOURCE_DOCUMENT_MISSING",
                        "error",
                        f"{unit_id}:source-document",
                        "The canonical Markdown reading view is missing or unsafe.",
                    )
                )
            elif str(source.get("markdown_hash") or "").strip() and _file_sha256(document) != str(
                source.get("markdown_hash")
            ).strip():
                findings.append(
                    _finding(
                        "OBSIDIAN_SOURCE_DOCUMENT_DRIFT",
                        "error",
                        f"{unit_id}:source-document",
                        "The canonical Markdown reading view no longer matches its recorded digest.",
                    )
                )
        materialization = source.get("materialization") if isinstance(source.get("materialization"), dict) else {}
        if materialization:
            for field, suffix in (("source_map_path", ".yaml"), ("conversion_path", ".yaml")):
                if _canonical_source_path(project_root, materialization.get(field), suffix=suffix) is None:
                    findings.append(
                        _finding(
                            "OBSIDIAN_SOURCE_BUNDLE_INCOMPLETE",
                            "error",
                            f"{unit_id}:{field}",
                            "A declared canonical source-bundle file is missing or unsafe.",
                        )
                    )
            archive_value = _single_line(materialization.get("archive_path"))
            if archive_value:
                archive = _canonical_source_path(project_root, archive_value, suffix=".html")
                if archive is None:
                    findings.append(
                        _finding(
                            "OBSIDIAN_SOURCE_BUNDLE_INCOMPLETE",
                            "error",
                            f"{unit_id}:archive_path",
                            "The declared offline HTML reading page is missing or unsafe.",
                        )
                    )
                elif _single_line(materialization.get("archive_hash")) and _file_sha256(archive) != _single_line(
                    materialization.get("archive_hash")
                ):
                    findings.append(
                        _finding(
                            "OBSIDIAN_SOURCE_ARCHIVE_DRIFT",
                            "error",
                            f"{unit_id}:archive",
                            "The offline HTML reading page no longer matches its recorded digest.",
                        )
                    )
            asset_paths = materialization.get("asset_paths", [])
            for asset_index, asset in enumerate(asset_paths if isinstance(asset_paths, list) else [], start=1):
                if _canonical_source_path(project_root, asset, suffix=None) is None:
                    findings.append(
                        _finding(
                            "OBSIDIAN_SOURCE_ASSET_MISSING",
                            "error",
                            f"{unit_id}:asset:{asset_index}",
                            "A declared local source asset is missing or unsafe.",
                        )
                    )
        for program_id in record.get("program_ids", []):
            target_id = str(program_id).strip()
            if target_id and target_id not in program_ids:
                findings.append(
                    _finding(
                        "OBSIDIAN_PROGRAM_TARGET_MISSING",
                        "error",
                        f"{unit_id}:program:{target_id}",
                        "A unit links to a program without canonical program state.",
                    )
                )
        for claim_index, claim in enumerate(_claims(record), start=1):
            refs = claim.get("evidence_refs", [])
            refs = refs if isinstance(refs, list) else []
            for evidence_index, ref in enumerate(refs, start=1):
                if not isinstance(ref, dict):
                    continue
                source_id = str(ref.get("source_unit_id") or unit_id).strip()
                if source_id and source_id not in record_ids:
                    findings.append(
                        _finding(
                            "OBSIDIAN_EVIDENCE_SOURCE_MISSING",
                            "error",
                            f"{unit_id}:claim:{claim_index}:evidence:{evidence_index}:{source_id}",
                            "A canonical evidence reference links to a missing source unit.",
                        )
                    )
                source_record = next((item for item in records if str(item.get("id") or "") == source_id), {})
                external = ref.get("external_source") if isinstance(ref.get("external_source"), dict) else {}
                if str(external.get("kind") or "") == "repo" and not _local_repo_artifact_uri(source_record, ref):
                    findings.append(
                        _finding(
                            "OBSIDIAN_LOCAL_CODE_UNAVAILABLE",
                            "warning",
                            f"{unit_id}:claim:{claim_index}:evidence:{evidence_index}",
                            "A repository evidence file cannot currently be opened from its trusted local root.",
                        )
                    )
    for state in programs:
        program_id = str(state.get("program_id") or "")
        active_ids = state.get("active_unit_ids", [])
        active_ids = active_ids if isinstance(active_ids, list) else []
        for unit_id in active_ids:
            target_id = str(unit_id).strip()
            if target_id and target_id not in record_ids:
                findings.append(
                    _finding(
                        "OBSIDIAN_PROGRAM_UNIT_MISSING",
                        "error",
                        f"{program_id}:unit:{target_id}",
                        "A program links to an active unit that is not present in the canonical KB.",
                    )
                )
    return findings


def obsidian_projection_status(project_root: Path) -> dict[str, Any]:
    """Read-only projection audit.  Missing workspaces remain byte-identical."""
    canonical_root = kb_root(project_root)
    if canonical_root.is_symlink() or (canonical_root.exists() and not canonical_root.is_dir()):
        return {
            "status": "FAIL",
            "input_digest": "",
            "generated_at": "",
            "counts": {"total": 1, "error": 1, "warning": 0, "records": 0, "programs": 0, "managed_files": 0},
            "findings": [
                _finding(
                    "OBSIDIAN_KB_ROOT_UNSAFE",
                    "error",
                    "kb",
                    "The canonical KB root is a symlink or non-directory.",
                )
            ],
        }
    inputs = _projection_inputs(project_root)
    records = inputs["records"]
    findings = _relation_findings(records)
    findings.extend(_projection_link_findings(project_root, records, inputs["programs"]))
    findings.extend(
        _finding(
            "OBSIDIAN_CANONICAL_INPUT_UNSAFE",
            "error",
            issue,
            "A canonical projection input is invalid or traverses an unsafe path.",
        )
        for issue in inputs["input_issues"]
    )
    manifest, manifest_state = _load_manifest(project_root)
    managed = obsidian_managed_root(project_root)
    if manifest is None:
        if manifest_state not in {"missing", "ok"}:
            findings.append(
                _finding(
                    "OBSIDIAN_MANIFEST_INVALID",
                    "error",
                    "obsidian",
                    "The managed projection manifest is invalid.",
                )
            )
        elif records or inputs["programs"]:
            findings.append(
                _finding(
                    "OBSIDIAN_PROJECTION_NOT_GENERATED",
                    "warning",
                    "obsidian",
                    "Canonical knowledge exists but no managed Obsidian projection has been generated.",
                )
            )
        current_files, unsafe_entries = _safe_managed_entries(managed)
        for relative in sorted(current_files):
            findings.append(
                _finding(
                    "OBSIDIAN_MANAGED_FILE_UNOWNED",
                    "warning",
                    relative,
                    "An unowned file exists in the generated area and was preserved.",
                )
            )
        for relative in sorted(unsafe_entries):
            findings.append(
                _finding(
                    "OBSIDIAN_MANAGED_PATH_UNSAFE",
                    "error",
                    relative,
                    "A symlink or special entry exists in the generated area.",
                )
            )
    else:
        presentation_desired: dict[str, str] = {}
        if (
            _manifest_renderer_revision(manifest) != OBSIDIAN_RENDERER_REVISION
            or str(manifest.get("input_digest") or "") != inputs["input_digest"]
        ):
            findings.append(
                _finding(
                    "OBSIDIAN_PROJECTION_STALE",
                    "warning",
                    "obsidian",
                    "The canonical knowledge base changed after the last projection update.",
                )
            )
        else:
            presentation_desired = _base_projection_files(inputs)
        for relative, expected_digest in _manifest_files(manifest).items():
            try:
                path = _managed_path(managed, relative)
            except SystemExit:
                findings.append(
                    _finding("OBSIDIAN_MANAGED_PATH_UNSAFE", "error", relative, "A manifest path is unsafe.")
                )
                continue
            if path.is_symlink() or not path.exists() or not path.is_file():
                findings.append(
                    _finding("OBSIDIAN_MANAGED_FILE_MISSING", "error", relative, "A manifest-owned file is missing or retyped.")
                )
                continue
            if _file_sha256(path) != expected_digest:
                candidate = None
                desired_text = presentation_desired.get(relative)
                if desired_text is not None:
                    candidate = _presentation_sort_candidate(
                        project_root,
                        relative=relative,
                        expected_digest=expected_digest,
                        desired_text=desired_text,
                    )
                if candidate is not None:
                    findings.append(
                        _finding(
                            "OBSIDIAN_BASE_PRESENTATION_SORT_DRIFT",
                            "warning",
                            relative,
                            "A generated Base has an allowlisted presentation sort change; it was not reset.",
                        )
                    )
                else:
                    findings.append(
                        _finding(
                            "OBSIDIAN_MANAGED_FILE_DRIFT",
                            "warning",
                            relative,
                            "A generated file was edited after projection; it was not overwritten.",
                        )
                    )
        current_files, unsafe_entries = _safe_managed_entries(managed)
        owned_files = set(_manifest_files(manifest))
        for relative in sorted(current_files - owned_files):
            findings.append(
                _finding(
                    "OBSIDIAN_MANAGED_FILE_UNOWNED",
                    "warning",
                    relative,
                    "An unowned file exists in the generated area and was preserved.",
                )
            )
        for relative in sorted(unsafe_entries):
            findings.append(
                _finding(
                    "OBSIDIAN_MANAGED_PATH_UNSAFE",
                    "error",
                    relative,
                    "A symlink or special entry exists in the generated area.",
                )
            )
    root = obsidian_root(project_root)
    for name in HUMAN_DIRS:
        human_path = root / name
        if human_path.is_symlink() or (human_path.exists() and not human_path.is_dir()):
            findings.append(
                _finding(
                    "OBSIDIAN_HUMAN_PATH_UNSAFE",
                    "error",
                    name,
                    "A human-authored Obsidian area is a symlink or non-directory and was not traversed.",
                )
            )
    error_count = sum(item["severity"] == "error" for item in findings)
    warning_count = sum(item["severity"] == "warning" for item in findings)
    status = "FAIL" if error_count else ("WARN" if warning_count else "PASS")
    return {
        "status": status,
        "input_digest": inputs["input_digest"],
        "generated_at": str((manifest or {}).get("generated_at") or ""),
        "counts": {
            "total": len(findings),
            "error": error_count,
            "warning": warning_count,
            "records": len(records),
            "programs": len(inputs["programs"]),
            "managed_files": len(_manifest_files(manifest or {})),
        },
        "findings": findings,
    }


__all__ = [
    "OBSIDIAN_PROJECTION_SCHEMA",
    "OBSIDIAN_RENDERER_REVISION",
    "OBSIDIAN_BASE_PRESENTATION_RESET_SCHEMA",
    "MANIFEST_NAME",
    "HUMAN_DIRS",
    "obsidian_root",
    "obsidian_managed_root",
    "obsidian_manifest_path",
    "update_obsidian_projection",
    "obsidian_projection_status",
    "preview_obsidian_base_presentation_reset",
    "reset_obsidian_base_presentation_drift",
]
