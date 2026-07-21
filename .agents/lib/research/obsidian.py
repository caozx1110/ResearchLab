"""No-plugin Obsidian projection for the canonical research KB.

The projection is fully derived.  Only ``kb/obsidian/managed`` is owned by this
module; ``inbox`` and ``annotations`` are human space and are never traversed.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
from collections import defaultdict
from pathlib import Path, PurePosixPath
from typing import Any, Iterable
from urllib.parse import quote as url_quote

from .common import utc_now_iso
from .journal import mutation_transaction
from .paths import UNIT_KIND_DIRS, ensure_kb_gitignore, kb_gitignore_path, kb_root, topic_taxonomy_path, units_root
from .records import normalize_record_schema
from .relations import (
    BLOCK_ID_RE,
    inverse_relation,
    project_relation_edges,
    stable_block_id,
)
from .yaml_io import dump_yaml, load_yaml, write_text_if_changed, write_yaml_if_changed


OBSIDIAN_PROJECTION_SCHEMA = "research-kb-obsidian/v1"
OBSIDIAN_RENDERER_REVISION = 2
MANIFEST_NAME = "manifest.yaml"
HUMAN_DIRS = ("inbox", "annotations")
UNIT_HEADINGS = frozenset({"Overview", "Metadata", "Relationships", "Claims"})
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


def obsidian_root(project_root: Path) -> Path:
    return kb_root(project_root) / "obsidian"


def obsidian_managed_root(project_root: Path) -> Path:
    return obsidian_root(project_root) / "managed"


def obsidian_manifest_path(project_root: Path) -> Path:
    return obsidian_managed_root(project_root) / MANIFEST_NAME


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


def _source_markdown(value: Any) -> str:
    uri = _single_line(value)
    if re.match(r"^https?://", uri, flags=re.IGNORECASE):
        encoded = url_quote(uri, safe=":/?#[]@!$&'()*+,;=%")
        return f"[Open source](<{encoded}>)"
    return "Local source"


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
        return ["No typed relationships yet."]
    lines: list[str] = []
    for relation in sorted(grouped):
        lines.extend([f"### {relation}", "", *sorted(set(grouped[relation])), ""])
    return lines[:-1]


def _render_claims(record: dict[str, Any], records_by_id: dict[str, dict[str, Any]]) -> list[str]:
    claims = _claims(record)
    if not claims:
        return ["No canonical claims yet."]
    lines: list[str] = []
    current_id = str(record.get("id") or "")
    for claim_index, claim in enumerate(claims, start=1):
        block_id = _claim_block_id(claim, claim_index)
        text = _markdown_text(claim.get("text"))
        lines.extend(
            [
                f"### Claim {block_id}",
                "",
                f"{text} ^{block_id}",
                "",
                f"- Type: {_human_label(claim.get('claim_type'), _CLAIM_TYPE_LABELS)}",
                f"- Confirmation: {_human_label(claim.get('confirmation_status'), _CONFIRMATION_LABELS)}",
            ]
        )
        refs = claim.get("evidence_refs", [])
        refs = refs if isinstance(refs, list) else []
        if not refs:
            lines.extend(["- Evidence: none", ""])
            continue
        lines.extend(["", "#### Evidence", ""])
        for evidence_index, ref in enumerate(refs, start=1):
            if not isinstance(ref, dict):
                continue
            evidence_id = _evidence_block_id(block_id, evidence_index)
            source_id = str(ref.get("source_unit_id") or current_id)
            source_link = _unit_link(source_id, records_by_id)
            locator = _single_line(ref.get("locator")) or "unspecified locator"
            artifact = _single_line(ref.get("artifact")) or "unspecified artifact"
            quote = str(ref.get("quote") or "").strip()
            lines.append(
                f"- {source_link} · {_inline_code(artifact)} · {_inline_code(locator)}"
            )
            if quote:
                for quote_line in quote.splitlines():
                    lines.append(f"> {_markdown_text(quote_line)}")
            else:
                lines.append("> No verbatim quote recorded.")
            lines.extend(["", f"^{evidence_id}", ""])
    return lines[:-1]


def _render_unit_page(
    record: dict[str, Any],
    outgoing: dict[str, list[dict[str, Any]]],
    incoming: dict[str, list[dict[str, Any]]],
    records_by_id: dict[str, dict[str, Any]],
) -> str:
    unit_id = str(record.get("id") or "")
    title = _single_line(record.get("title")) or unit_id
    topics = [str(item) for item in record.get("topics", []) if str(item).strip()]
    programs = [str(item) for item in record.get("program_ids", []) if str(item).strip()]
    properties: dict[str, Any] = {
        "id": unit_id,
        "kind": str(record.get("kind") or ""),
        "title": title,
        "aliases": [title] if title and title != unit_id else [],
        "status": str(record.get("status") or ""),
        "maturity": str(record.get("maturity") or ""),
        "confirmation_status": str(record.get("confirmation_status") or ""),
        "topics": [_wikilink(_topic_page_path(topic), display=topic) for topic in topics],
        "programs": [_wikilink(_program_page_path(program), display=program) for program in programs],
        "tags": sorted({str(item) for item in record.get("tags", []) if str(item).strip()}),
        "managed_by": "research-kb",
        "source_path": f"units/{UNIT_KIND_DIRS.get(str(record.get('kind') or ''), '')}/{unit_id}/record.yaml",
    }
    properties.update(_flat_relation_properties(unit_id, outgoing, incoming, records_by_id))
    summary = _markdown_text(record.get("summary")) or "No summary yet."
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    source_uri = _single_line(source.get("original_uri"))
    lines = [
        _frontmatter(properties).rstrip(),
        "",
        f"# {_markdown_text(title)}",
        "",
        "## Overview",
        "",
        summary,
        "",
        "## Metadata",
        "",
        f"- Unit: {_inline_code(unit_id)}",
        f"- Kind: {_inline_code(properties['kind'])}",
        f"- Status: {_inline_code(properties['status'])}",
        f"- Maturity: {_inline_code(properties['maturity'])}",
        f"- Confirmation: {_inline_code(properties['confirmation_status'])}",
    ]
    if source_uri:
        lines.append(f"- Source: {_source_markdown(source_uri)}")
    if topics:
        lines.append("- Topics: " + ", ".join(_wikilink(_topic_page_path(topic), display=topic) for topic in topics))
    if programs:
        lines.append("- Programs: " + ", ".join(_wikilink(_program_page_path(program), display=program) for program in programs))
    lines.extend(
        [
            "",
            "## Relationships",
            "",
            *_render_relations(unit_id, outgoing, incoming, records_by_id),
            "",
            "## Claims",
            "",
            *_render_claims(record, records_by_id),
            "",
        ]
    )
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


def _projection_inputs(project_root: Path) -> dict[str, Any]:
    records, record_issues = _safe_records(project_root)
    programs, program_issues = _safe_program_states(project_root)
    programs = sorted(programs, key=lambda state: str(state.get("program_id") or ""))
    taxonomy, taxonomy_issues = _safe_taxonomy(project_root)
    digest_payload = {
        "schema": OBSIDIAN_PROJECTION_SCHEMA,
        "renderer_revision": OBSIDIAN_RENDERER_REVISION,
        "records": records,
        "programs": programs,
        "taxonomy": taxonomy,
    }
    return {
        "records": records,
        "programs": programs,
        "taxonomy": taxonomy,
        "input_issues": [*record_issues, *program_issues, *taxonomy_issues],
        "input_digest": _sha256_text(_canonical_json(digest_payload)),
    }


def _render_program_page(state: dict[str, Any], records_by_id: dict[str, dict[str, Any]]) -> str:
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
        "## Goal",
        "",
        _markdown_text(state.get("goal")) or "No goal recorded.",
        "",
        "## Research question",
        "",
        _markdown_text(state.get("question")) or "No research question recorded.",
        "",
        "## Active units",
        "",
    ]
    lines.extend([f"- {_unit_link(unit_id, records_by_id)}" for unit_id in unit_ids] or ["No active units."])
    lines.extend(["", "## Next actions", ""])
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
        lines.append("No next actions.")
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
        _markdown_text(item.get("note")) or "Canonical research topic.",
        "",
        "## Units",
        "",
    ]
    lines.extend([f"- {_unit_link(unit_id, records_by_id)}" for unit_id in unit_ids] or ["No linked units."])
    return "\n".join(lines).rstrip() + "\n"


def _base_file(*, name: str, view_filter: str = "", group_by: str = "") -> str:
    view: dict[str, Any] = {
        "type": "table",
        "name": name,
        "order": [
            "file.name",
            "note.title",
            "note.kind",
            "note.status",
            "note.maturity",
            "note.confirmation_status",
            "note.topics",
            "note.programs",
        ],
    }
    if view_filter:
        view["filters"] = {"and": [view_filter]}
    if group_by:
        view["groupBy"] = {"property": group_by, "direction": "ASC"}
    payload = {
        "filters": {
            "and": [
                'file.inFolder("obsidian/managed/units")',
                'file.ext == "md"',
            ]
        },
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
    return dump_yaml(payload, width=1_000_000)


def _render_home(generated_at: str, records: list[dict[str, Any]], programs: list[dict[str, Any]]) -> str:
    return "\n".join(
        [
            _frontmatter(
                {
                    "id": "research-kb-home",
                    "kind": "dashboard",
                    "title": "Research KB",
                    "managed_by": "research-kb",
                }
            ).rstrip(),
            "",
            "# Research KB",
            "",
            f"Generated from the canonical knowledge base at {generated_at}.",
            "",
            f"- Units: {len(records)}",
            f"- Programs: {len(programs)}",
            "",
            "> [!tip] Reading view",
            "> Generated pages are designed for Obsidian Reading view. Use the book icon in the upper-right; editor mode intentionally shows wikilinks and block IDs.",
            "",
            "## Database views",
            "",
            "- [[obsidian/managed/dashboards/All Units.base|All units]]",
            "- [[obsidian/managed/dashboards/Pending Review.base|Pending review]]",
            "- [[obsidian/managed/dashboards/By Topic.base|By topic]]",
            "",
            "## Human notes",
            "",
            "- Put unprocessed notes in `obsidian/inbox/`.",
            "- Put durable human commentary in `obsidian/annotations/`.",
            "",
            "> [!warning] Managed projection",
            "> Files below `obsidian/managed` are generated. Put human-authored notes in inbox or annotations.",
            "",
        ]
    )


def _projection_files(inputs: dict[str, Any], *, generated_at: str) -> dict[str, str]:
    records = inputs["records"]
    programs = inputs["programs"]
    taxonomy = inputs["taxonomy"]
    records_by_id = {str(record.get("id") or ""): record for record in records if str(record.get("id") or "")}
    edges = project_relation_edges(records)
    outgoing: dict[str, list[dict[str, Any]]] = defaultdict(list)
    incoming: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for edge in edges:
        outgoing[str(edge["source_id"])].append(edge)
        incoming[str(edge["target_id"])].append(edge)

    files: dict[str, str] = {"Home.md": _render_home(generated_at, records, programs)}
    for record in records:
        unit_id = str(record.get("id") or "")
        if not unit_id:
            continue
        files[f"units/{_safe_component(unit_id, fallback='unit')}.md"] = _render_unit_page(
            record, outgoing, incoming, records_by_id
        )
    for state in programs:
        program_id = str(state.get("program_id") or "")
        if program_id:
            files[f"programs/{_safe_component(program_id, fallback='program')}.md"] = _render_program_page(
                state, records_by_id
            )
    topic_items = taxonomy.get("topics", {}) if isinstance(taxonomy, dict) else {}
    topic_items = topic_items if isinstance(topic_items, dict) else {}
    members = _topic_members(records)
    for topic_id in sorted(set(topic_items) | set(members)):
        item = topic_items.get(topic_id, {})
        item = item if isinstance(item, dict) else {}
        files[f"topics/{_safe_component(topic_id, fallback='topic')}.md"] = _render_topic_page(
            topic_id, item, members.get(topic_id, []), records_by_id
        )
    files["dashboards/All Units.base"] = _base_file(name="All units")
    files["dashboards/Pending Review.base"] = _base_file(
        name="Pending review", view_filter='confirmation_status == "pending_user_confirmation"'
    )
    files["dashboards/By Topic.base"] = _base_file(name="By topic", group_by="note.topics")
    return dict(sorted(files.items()))


def _manifest_files(manifest: dict[str, Any]) -> dict[str, str]:
    values = manifest.get("files")
    if not isinstance(values, dict):
        return {}
    return {str(path): str(digest) for path, digest in values.items() if str(path) and str(digest)}


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
        if previous_digest is None or current_digest != previous_digest:
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
    desired = _projection_files(inputs, generated_at=generated_at)
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
    findings.extend(_projection_link_findings(records, inputs["programs"]))
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
    "MANIFEST_NAME",
    "HUMAN_DIRS",
    "obsidian_root",
    "obsidian_managed_root",
    "obsidian_manifest_path",
    "update_obsidian_projection",
    "obsidian_projection_status",
]
