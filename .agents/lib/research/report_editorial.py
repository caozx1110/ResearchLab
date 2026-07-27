"""Pure contracts and renderers for Agent-authored weekly/PPT editorial fills."""

from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any, Mapping


EDITORIAL_SCHEMA = "report-editorial/v1"
FILL_SCHEMA = "report-editorial-fill/v1"
OUTPUT_KINDS = {"weekly", "ppt-materials"}
WEEKLY_SECTIONS = (
    "executive_summary",
    "progress",
    "problems_and_risks",
    "next_steps",
)
EPISTEMIC_LABELS = {"fact", "synthesis", "risk", "plan"}
MAX_TEXT_BYTES = 8192
MAX_FILL_BYTES = 128 * 1024
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,255}")
_HTML_RE = re.compile(r"<\s*/?\s*[A-Za-z][^>]*>")
_LATEX_RE = re.compile(
    r"(?:\\(?:begin|end|input|include|documentclass|usepackage|write|catcode|newcommand|[A-Za-z]{2,})\b|\\[\[(]|\$\$)"
)
_ABSOLUTE_PATH_RE = re.compile(r"(?:^|[\s(])(?:/(?:Users|private|home|var|tmp)/|[A-Za-z]:[\\/])")
_INTERNAL_TOKEN_RE = re.compile(r"(?:^|[\s(])(?:\.agents/|dev-docs/|scripts/|kb/(?:units|programs|config|\.runtime)/|--[A-Za-z]|\$\{)")


class EditorialError(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _safe_id(value: Any, *, field: str) -> str:
    text = str(value or "").strip()
    if not _SAFE_ID_RE.fullmatch(text) or text in {".", ".."}:
        raise EditorialError(f"{field} must be a stable reference-safe identity")
    return text


def _catalog_entries(catalog: Mapping[str, Mapping[str, Any]], *, key: str) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for ref in sorted(catalog):
        _safe_id(ref, field=f"{key} ref")
        value = catalog[ref]
        if not isinstance(value, Mapping):
            raise EditorialError(f"{key} catalog entries must be mappings")
        entry = copy.deepcopy(dict(value))
        if str(entry.get("ref") or "") != ref:
            raise EditorialError(f"{key} catalog key and entry ref differ")
        entries.append(entry)
    return entries


def manifest_anchor_digest(manifest: Mapping[str, Any]) -> str:
    payload = copy.deepcopy(dict(manifest))
    payload.pop("anchor_digest", None)
    return _digest(payload)


def build_editorial_manifest(
    *,
    program_id: str,
    output_kind: str,
    as_of: str,
    request: Mapping[str, Any],
    input_bindings: Mapping[str, Any],
    support_catalog: Mapping[str, Mapping[str, Any]],
    risk_catalog: Mapping[str, Mapping[str, Any]],
    figure_catalog: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    clean_program = _safe_id(program_id, field="program id")
    if output_kind not in OUTPUT_KINDS:
        raise EditorialError("output kind must be weekly or ppt-materials")
    if not str(as_of or "").strip():
        raise EditorialError("manifest as_of is required")
    manifest = {
        "schema_version": EDITORIAL_SCHEMA,
        "kind": "report_editorial_manifest",
        "program_id": clean_program,
        "output_kind": output_kind,
        "as_of": str(as_of),
        "request": copy.deepcopy(dict(request)),
        "input_bindings": copy.deepcopy(dict(input_bindings)),
        "catalogs": {
            "support": _catalog_entries(support_catalog, key="support"),
            "risks": _catalog_entries(risk_catalog, key="risk"),
            "figures": _catalog_entries(figure_catalog, key="figure"),
        },
        "anchor_digest": "",
    }
    manifest["anchor_digest"] = manifest_anchor_digest(manifest)
    violations = editorial_manifest_violations(manifest)
    if violations:
        raise EditorialError("invalid editorial manifest: " + "; ".join(violations))
    return manifest


def editorial_manifest_violations(value: Any) -> list[str]:
    if not isinstance(value, Mapping):
        return ["manifest must be a mapping"]
    violations: list[str] = []
    expected = {
        "schema_version", "kind", "program_id", "output_kind", "as_of",
        "request", "input_bindings", "catalogs", "anchor_digest",
    }
    if set(value) != expected:
        violations.append("manifest has missing or unexpected top-level fields")
    if value.get("schema_version") != EDITORIAL_SCHEMA:
        violations.append("manifest schema version is invalid")
    if value.get("kind") != "report_editorial_manifest":
        violations.append("manifest kind is invalid")
    try:
        _safe_id(value.get("program_id"), field="program id")
    except EditorialError as exc:
        violations.append(str(exc))
    if value.get("output_kind") not in OUTPUT_KINDS:
        violations.append("manifest output kind is invalid")
    if not str(value.get("as_of") or "").strip():
        violations.append("manifest as_of is missing")
    if not isinstance(value.get("request"), Mapping):
        violations.append("manifest request must be a mapping")
    if not isinstance(value.get("input_bindings"), Mapping):
        violations.append("manifest input bindings must be a mapping")
    catalogs = value.get("catalogs")
    if not isinstance(catalogs, Mapping) or set(catalogs) != {"support", "risks", "figures"}:
        violations.append("manifest catalogs must contain support, risks, and figures")
    else:
        for name in ("support", "risks", "figures"):
            entries = catalogs.get(name)
            if not isinstance(entries, list) or any(not isinstance(item, Mapping) for item in entries):
                violations.append(f"manifest {name} catalog must be a list of mappings")
                continue
            refs = [str(item.get("ref") or "") for item in entries]
            if refs != sorted(refs) or len(refs) != len(set(refs)):
                violations.append(f"manifest {name} refs must be unique and sorted")
            for ref in refs:
                try:
                    _safe_id(ref, field=f"{name} ref")
                except EditorialError as exc:
                    violations.append(str(exc))
    anchor = str(value.get("anchor_digest") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", anchor):
        violations.append("manifest anchor digest is invalid")
    elif anchor != manifest_anchor_digest(value):
        violations.append("manifest anchor digest does not match exact contents")
    try:
        if len(_canonical_bytes(value)) > MAX_FILL_BYTES * 4:
            violations.append("manifest exceeds the safe size limit")
    except (TypeError, ValueError):
        violations.append("manifest contains a non-canonical value")
    return list(dict.fromkeys(violations))


def build_editorial_fill_scaffold(manifest: Mapping[str, Any]) -> dict[str, Any]:
    violations = editorial_manifest_violations(manifest)
    if violations:
        raise EditorialError("invalid editorial manifest: " + "; ".join(violations))
    base = {
        "schema_version": FILL_SCHEMA,
        "kind": "report_editorial_fill",
        "program_id": str(manifest["program_id"]),
        "output_kind": str(manifest["output_kind"]),
        "manifest_anchor": str(manifest["anchor_digest"]),
        # Lifecycle is owner-controlled: the Agent only fills semantic leaves.
        # Empty prose/refs still fail the substantive verifier.
        "status": "ready_for_verify",
    }
    if manifest["output_kind"] == "weekly":
        labels = {
            "executive_summary": "synthesis",
            "progress": "fact",
            "problems_and_risks": "risk",
            "next_steps": "plan",
        }
        base["sections"] = {
            section: [{"text": "", "refs": [], "epistemic_label": labels[section]}]
            for section in WEEKLY_SECTIONS
        }
    else:
        base["figure_status"] = ""
        base["slides"] = [
            {
                "order": 1,
                "title": "",
                "conclusion": "",
                "evidence_refs": [],
                "figure_refs": [],
                "speaker_note": "",
                "transition": "",
            }
        ]
    return base


def fill_matches_manifest(fill: Any, manifest: Mapping[str, Any]) -> bool:
    return bool(
        isinstance(fill, Mapping)
        and fill.get("schema_version") == FILL_SCHEMA
        and fill.get("kind") == "report_editorial_fill"
        and fill.get("program_id") == manifest.get("program_id")
        and fill.get("output_kind") == manifest.get("output_kind")
        and fill.get("manifest_anchor") == manifest.get("anchor_digest")
    )


def _catalog_map(manifest: Mapping[str, Any], name: str) -> dict[str, dict[str, Any]]:
    catalogs = manifest.get("catalogs") if isinstance(manifest.get("catalogs"), Mapping) else {}
    entries = catalogs.get(name) if isinstance(catalogs, Mapping) else []
    return {
        str(item.get("ref") or ""): dict(item)
        for item in entries or []
        if isinstance(item, Mapping) and str(item.get("ref") or "")
    }


def _text(value: Any, *, field: str, required: bool = True) -> tuple[str, list[str]]:
    if not isinstance(value, str):
        return "", [f"{field} must be text"]
    text = value.strip()
    violations: list[str] = []
    if required and not text:
        violations.append(f"{field} must not be empty")
    if len(text.encode("utf-8")) > MAX_TEXT_BYTES:
        violations.append(f"{field} exceeds the safe text limit")
    if "\x00" in text or "<!--" in text or _HTML_RE.search(text):
        violations.append(f"{field} contains raw markup")
    if _LATEX_RE.search(text):
        violations.append(f"{field} contains raw LaTeX")
    if _ABSOLUTE_PATH_RE.search(text):
        violations.append(f"{field} contains an absolute machine path")
    if _INTERNAL_TOKEN_RE.search(text):
        violations.append(f"{field} contains an internal path, flag, or template token")
    return text, violations


def _refs(value: Any, *, field: str, allowed: set[str], required: bool = True) -> tuple[list[str], list[str]]:
    if not isinstance(value, list):
        return [], [f"{field} must be a list"]
    refs = [str(item or "").strip() for item in value]
    violations: list[str] = []
    if required and not refs:
        violations.append(f"{field} must contain at least one ref")
    if any(not ref for ref in refs):
        violations.append(f"{field} contains an empty ref")
    if len(refs) != len(set(refs)):
        violations.append(f"{field} contains duplicate refs")
    unknown = sorted(set(refs) - allowed)
    if unknown:
        violations.append(f"{field} contains unknown refs: {', '.join(unknown)}")
    if len(refs) > 12:
        violations.append(f"{field} exceeds the per-item ref limit")
    return refs, violations


def validate_editorial_fill(fill: Any, manifest: Mapping[str, Any]) -> list[str]:
    violations = editorial_manifest_violations(manifest)
    if violations:
        return violations
    if not isinstance(fill, Mapping):
        return ["fill must be a mapping"]
    if not fill_matches_manifest(fill, manifest):
        violations.append("fill does not bind the current manifest")
    if fill.get("status") != "ready_for_verify":
        violations.append("fill status must be ready_for_verify")
    support = set(_catalog_map(manifest, "support"))
    risks = set(_catalog_map(manifest, "risks"))
    figures = set(_catalog_map(manifest, "figures"))
    common = {"schema_version", "kind", "program_id", "output_kind", "manifest_anchor", "status"}
    if manifest["output_kind"] == "weekly":
        if set(fill) != common | {"sections"}:
            violations.append("weekly fill has missing or unexpected top-level fields")
        sections = fill.get("sections")
        if not isinstance(sections, Mapping) or tuple(sections) != WEEKLY_SECTIONS:
            violations.append("weekly sections must use the exact ordered four-section contract")
        else:
            for section in WEEKLY_SECTIONS:
                entries = sections.get(section)
                if not isinstance(entries, list) or not 1 <= len(entries) <= 8:
                    violations.append(f"weekly section {section} must contain 1 to 8 entries")
                    continue
                for index, item in enumerate(entries):
                    where = f"sections.{section}[{index}]"
                    if not isinstance(item, Mapping) or set(item) != {"text", "refs", "epistemic_label"}:
                        violations.append(f"{where} must contain exactly text, refs, and epistemic_label")
                        continue
                    _value, errors = _text(item.get("text"), field=f"{where}.text")
                    violations.extend(errors)
                    label = str(item.get("epistemic_label") or "")
                    if label not in EPISTEMIC_LABELS:
                        violations.append(f"{where}.epistemic_label is invalid")
                    allowed = support | risks if section == "problems_and_risks" else support
                    refs, errors = _refs(item.get("refs"), field=f"{where}.refs", allowed=allowed)
                    violations.extend(errors)
                    if any(ref in risks for ref in refs) and (section != "problems_and_risks" or label != "risk"):
                        violations.append(f"{where} may use risk hints only as a risk in problems_and_risks")
    else:
        if set(fill) != common | {"figure_status", "slides"}:
            violations.append("PPT fill has missing or unexpected top-level fields")
        slides = fill.get("slides")
        if not isinstance(slides, list) or not 1 <= len(slides) <= 12:
            violations.append("PPT fill must contain 1 to 12 slides")
            slides = []
        cited_figures: list[str] = []
        for index, slide in enumerate(slides, start=1):
            where = f"slides[{index - 1}]"
            expected = {"order", "title", "conclusion", "evidence_refs", "figure_refs", "speaker_note", "transition"}
            if not isinstance(slide, Mapping) or set(slide) != expected:
                violations.append(f"{where} has missing or unexpected fields")
                continue
            if slide.get("order") != index:
                violations.append(f"{where}.order must equal its one-based position")
            for name in ("title", "conclusion", "speaker_note", "transition"):
                _value, errors = _text(slide.get(name), field=f"{where}.{name}")
                violations.extend(errors)
            _evidence, errors = _refs(slide.get("evidence_refs"), field=f"{where}.evidence_refs", allowed=support)
            violations.extend(errors)
            figure_refs, errors = _refs(
                slide.get("figure_refs"), field=f"{where}.figure_refs", allowed=figures, required=False
            )
            violations.extend(errors)
            cited_figures.extend(figure_refs)
        figure_status = str(fill.get("figure_status") or "")
        if figures:
            if figure_status != "cited" or not cited_figures:
                violations.append("PPT must cite at least one current figure when the catalog is non-empty")
        elif figure_status != "missing" or cited_figures:
            violations.append("PPT must explicitly mark figures missing when no current figure exists")
    try:
        if len(_canonical_bytes(fill)) > MAX_FILL_BYTES:
            violations.append("fill exceeds the safe total size limit")
    except (TypeError, ValueError):
        violations.append("fill contains a non-canonical value")
    return list(dict.fromkeys(violations))


def _plain(value: Any) -> str:
    text = str(value or "").replace("<", "&lt;").replace(">", "&gt;").replace("\x00", "")
    text = _ABSOLUTE_PATH_RE.sub(" [path omitted]", text)
    text = _INTERNAL_TOKEN_RE.sub(" [internal detail omitted]", text)
    replacements = {
        "current ConfirmationReceipt": "当前人工确认",
        "ConfirmationReceipt": "人工确认记录",
        "canonical claims": "结构化研究结论",
    }
    for internal, public in replacements.items():
        text = text.replace(internal, public)
    return text


def _ref_line(entry: Mapping[str, Any], *, language: str, number: int, risk: bool = False) -> str:
    title = _plain(entry.get("title") or entry.get("source_title") or entry.get("kind") or "source")
    text = (
        "This source is not yet eligible as formal evidence and is shown only as a risk."
        if risk and language.lower().startswith("en")
        else "该来源尚未满足正式证据条件，暂仅作为风险提示。"
        if risk
        else _plain(entry.get("text") or entry.get("summary") or entry.get("rationale") or "")
    )
    prefix = "来源" if not language.lower().startswith("en") else "Source"
    marker = f"[{number}]" if language.lower().startswith("en") else f"〔{number}〕"
    return f"- {marker} {prefix}：{title} · {text}"


def render_weekly_editorial(fill: Mapping[str, Any], manifest: Mapping[str, Any], *, language: str) -> str:
    violations = validate_editorial_fill(fill, manifest)
    if violations:
        raise EditorialError("weekly fill failed verification: " + "; ".join(violations))
    english = language.lower().startswith("en")
    headings = {
        "executive_summary": "Executive Summary" if english else "本周摘要",
        "progress": "Progress" if english else "进展",
        "problems_and_risks": "Problems and Risks" if english else "问题与风险",
        "next_steps": "Next Steps" if english else "下周计划",
    }
    label_names = (
        {"fact": "Fact", "synthesis": "Synthesis", "risk": "Risk", "plan": "Plan"}
        if english
        else {"fact": "事实", "synthesis": "综合判断", "risk": "风险", "plan": "计划"}
    )
    support_entries = list(manifest["catalogs"]["support"])
    risk_entries = list(manifest["catalogs"]["risks"])
    all_entries = support_entries + risk_entries
    ref_numbers = {str(entry.get("ref") or ""): index for index, entry in enumerate(all_entries, start=1)}
    request = manifest.get("request") if isinstance(manifest.get("request"), Mapping) else {}
    display_title = _plain(request.get("program_title") or manifest["program_id"])
    lines = [
        f"# {'Weekly Report' if english else '周报'}：{display_title}",
        "",
        f"> {'As of' if english else '截至'}：{_plain(manifest['as_of'])}",
        "",
    ]
    for section in WEEKLY_SECTIONS:
        lines.extend([f"## {headings[section]}", ""])
        for item in fill["sections"][section]:
            refs = " ".join(
                f"[{ref_numbers[ref]}]" if english else f"〔{ref_numbers[ref]}〕"
                for ref in item["refs"]
            )
            label = label_names[str(item["epistemic_label"])]
            lines.append(
                f"- **{label}**：{_plain(item['text'])} "
                f"（{'依据' if not english else 'Sources'}：{refs}）"
            )
        lines.append("")
    lines.extend([f"## {'Evidence Appendix' if english else '证据附录'}", ""])
    groups = (
        (("Confirmed Decisions", "已确认决策", "decision"), ("Claims and Evidence", "研究结论与证据", "claim"), ("Events", "事实进展", "event"))
    )
    for english_heading, chinese_heading, kind in groups:
        lines.extend([f"### {english_heading if english else chinese_heading}", ""])
        entries = [entry for entry in support_entries if entry.get("kind") == kind]
        if not entries:
            missing = {
                "decision": "No confirmed decision is available for this period." if english else "缺少：本期没有可引用的已确认决策。",
                "claim": "No confirmed research claim is available for this period." if english else "缺少：本期没有可引用的已确认研究结论。",
                "event": "No factual event is available for this period." if english else "缺少：本期没有可引用的事实进展。",
            }[kind]
            lines.append(f"- {missing}")
        for entry in entries:
            lines.append(_ref_line(entry, language=language, number=ref_numbers[str(entry["ref"])]))
            for evidence in entry.get("evidence_refs", []) if isinstance(entry.get("evidence_refs"), list) else []:
                if isinstance(evidence, Mapping) and str(evidence.get("quote") or "").strip():
                    lines.append(f"  - {'Quote' if english else '逐字证据'}：{_plain(evidence.get('quote'))}")
        lines.append("")
    if risk_entries:
        lines.extend([f"### {'Unverified Risk Hints' if english else '未验证风险提示'}", ""])
        lines.extend(
            _ref_line(entry, language=language, number=ref_numbers[str(entry["ref"])], risk=True)
            for entry in risk_entries
        )
    return "\n".join(lines).strip() + "\n"


def render_ppt_editorial(fill: Mapping[str, Any], manifest: Mapping[str, Any], *, language: str) -> str:
    violations = validate_editorial_fill(fill, manifest)
    if violations:
        raise EditorialError("PPT fill failed verification: " + "; ".join(violations))
    english = language.lower().startswith("en")
    support = _catalog_map(manifest, "support")
    figures = _catalog_map(manifest, "figures")
    lines = [
        f"# {'PPT Materials' if english else 'PPT 素材'}：{_plain(manifest['program_id'])}",
        "",
        f"> {'Speaking order' if english else '讲述顺序'}：1 → {len(fill['slides'])}",
        "",
    ]
    if fill["figure_status"] == "missing":
        lines.extend([f"> {'Missing: no current citable figure.' if english else '缺少：当前没有可引用图示。'}", ""])
    for slide in fill["slides"]:
        lines.extend([
            f"## Slide {slide['order']} · {_plain(slide['title'])}",
            "",
            f"- {'Conclusion' if english else '结论'}：{_plain(slide['conclusion'])}",
            f"- {'Evidence' if english else '证据'}：",
        ])
        for ref in slide["evidence_refs"]:
            entry = support[ref]
            lines.append(f"  - `{_plain(ref)}` · {_plain(entry.get('text') or entry.get('summary') or entry.get('rationale'))}")
        lines.append(f"- {'Figure' if english else '图示'}：")
        if slide["figure_refs"]:
            for ref in slide["figure_refs"]:
                entry = figures[ref]
                lines.append(f"  - `{_plain(ref)}` · {_plain(entry.get('caption'))}")
        else:
            lines.append(f"  - {'None for this slide' if english else '本页无图示'}")
        lines.extend([
            f"- {'Speaker note' if english else '讲述'}：{_plain(slide['speaker_note'])}",
            f"- {'Transition' if english else '过渡'}：{_plain(slide['transition'])}",
            "",
        ])
    return "\n".join(lines).strip() + "\n"
