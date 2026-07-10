#!/usr/bin/env python3
"""Blog analyst: script prepares fillable structure + verifies evidence; a runtime
agent fills the understanding (SSOT Principle 1 / §3.4).

The script is deliberately *not* allowed to understand the blog. It (a) reads the
parse-cache produced by source-intake, (b) emits a **fillable structure** (4-element
note skeleton) whose judgement fields are left blank for a runtime agent, and (c)
**verifies** every judgement the agent fills carries legit verbatim evidence
(research.evidence) before it clears the substance gate (research.confirm) and is
persisted. There is no keyword-count heuristic or Python-inferred positioning here:
any "this blog is a tutorial / this is fact not opinion" claim must come from an
agent, never from Python.

Blog sources are web pages only (no multimedia). The parse-cache uses
section/anchor locators (HTML, no page numbers).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

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

from research.common import (
    add_project_root_argument,
    clean_text,
    load_yaml,
    print_resolved_project_roots,
    write_text_if_changed,
    write_yaml_if_changed,
)
from research.core import (
    append_history,
    build_index,
    confirm_unit,
    locate_record,
    project_root,
    rel,
    write_record,
)
from research.evidence import (
    attach_claims,
    read_claims,
    validate_claims,
    verify_claim_evidence,
)

# --------------------------------------------------------------------------- #
# The 4-element fill contract (SSOT §3.4).                                    #
#                                                                              #
# A runtime agent fills these four elements; every element is a               #
# judgement-class claim and MUST carry >=1 evidence_ref (short verbatim       #
# quote + locator from the blog parse-cache). The script only verifies +      #
# routes them — it never authors content. Each element lands in a canonical   #
# payload field so a filled note clears has_substantive_content()             #
# (SUBSTANCE_CONTENT_SECTIONS["blog"] = ("content",)).                        #
# --------------------------------------------------------------------------- #
NOTE_ELEMENTS: tuple[str, ...] = (
    "positioning",
    "key_points",
    "credibility",
    "reusable_explanation",
)

ELEMENT_CLAIM_TYPE: dict[str, str] = {
    "positioning": "inference",
    "key_points": "inference",
    "credibility": "evaluation",
    "reusable_explanation": "inference",
}

# element -> (payload section, field, shape).
# key_points and reusable_explanation land in payload.content (the substance gate
# section for blogs), so a verified note is never hollow. positioning lands in
# payload.positioning; credibility lands in payload.credibility.
ELEMENT_TARGET: dict[str, tuple[str, str, str]] = {
    "positioning": ("positioning", "main_value", "str"),
    "key_points": ("content", "key_points", "list"),
    "credibility": ("credibility", "best_use", "str"),
    "reusable_explanation": ("content", "intuitions", "list"),
}

ELEMENT_HEADING: dict[str, str] = {
    "positioning": "Positioning",
    "key_points": "Key Points",
    "credibility": "Credibility",
    "reusable_explanation": "Reusable Explanation",
}

# Reusable, machine-readable description of the evidence_ref shape an agent must fill.
# Blog parse-cache uses section/anchor locators (HTML, no page numbers).
EVIDENCE_REF_FORMAT: dict[str, str] = {
    "source_unit_id": "b-... (this blog unit id)",
    "artifact": "parse-cache.yaml (unit-relative artifact the quote lives in)",
    "locator": "HTML: section or section:<anchor> (B4) — no page numbers for web sources",
    "quote": "short verbatim snippet — script checks it is a whitespace-normalized substring of the artifact",
    "summary": "optional one-line paraphrase",
}


def add_confirmation_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--confirmed-by", default="")
    parser.add_argument("--evidence", action="append", required=True)


def _cache_path(unit_root: Path) -> Path:
    return unit_root / "parse-cache.yaml"


def _load_cache_chunks(unit_root: Path) -> tuple[list[dict], str]:
    """Load chunks from parse-cache.yaml (built by source-intake). Returns (chunks, locator_kind)."""
    cache_path = _cache_path(unit_root)
    if not cache_path.exists():
        return [], "section"
    payload = load_yaml(cache_path, default={})
    if not isinstance(payload, dict):
        return [], "section"
    chunks = payload.get("chunks") or []
    locator_kind = str(payload.get("locator_kind") or "section")
    if not isinstance(chunks, list):
        return [], locator_kind
    return [c for c in chunks if isinstance(c, dict)], locator_kind


def _chunk_locator(chunk: dict) -> str:
    """Derive the evidence locator string for an HTML section chunk (B4).

    Blog parse-caches use section/anchor locators. Labels are ``section:<anchor>``
    or ``section:document``. This is pure transport — it copies the locator the
    agent should cite, it does not judge anything.
    """
    label = str(chunk.get("label") or "")
    if label.startswith("section:"):
        return label
    anchor = str(chunk.get("anchor") or "")
    if anchor:
        return f"section:{anchor}"
    return "section"


def _evidence_digest(chunks: list[dict], *, chunk_limit: int, excerpt_chars: int) -> list[dict]:
    """Build a locator-tagged excerpt list from parse-cache chunks for the agent.

    This is the "备料" (transport) half of Principle 1: it hands the agent the
    raw section text with citable locators. It contains no judgement and no grade.
    """
    digest: list[dict] = []
    for chunk in chunks[:chunk_limit]:
        text = clean_text(str(chunk.get("text") or ""))
        if not text:
            continue
        digest.append(
            {
                "locator": _chunk_locator(chunk),
                "artifact": "parse-cache.yaml",
                "label": str(chunk.get("label") or ""),
                "excerpt": text[:excerpt_chars],
            }
        )
    return digest


# --------------------------------------------------------------------------- #
# complete-note: 4-element fillable skeleton / verify + persist an agent fill  #
# --------------------------------------------------------------------------- #


def build_note_scaffold(
    record: dict,
    source_chunks: list[dict],
    *,
    digest_chunks: int,
    digest_chars: int,
) -> dict:
    """Produce the 4-element fillable note skeleton (positioning/key_points/
    credibility/reusable_explanation). Each element is blank for the agent to
    fill with content + >=1 evidence_ref. The script authors nothing here."""
    digest = _evidence_digest(source_chunks, chunk_limit=digest_chunks, excerpt_chars=digest_chars)
    elements = [
        {
            "element": name,
            "claim_type": ELEMENT_CLAIM_TYPE[name],
            "content": "",
            "evidence_refs": [],
        }
        for name in NOTE_ELEMENTS
    ]
    return {
        "blog_id": record["id"],
        "kind": "blog",
        "status": "awaiting_agent_fill",
        "phase": "prepare",
        "fill_contract": {
            "description": (
                "Agent fills all four required_elements with its own understanding, each "
                "backed by >=1 verbatim evidence_ref from the parse-cache. Then run "
                "`complete-note --phase verify` to validate + verbatim-check evidence + "
                "write blog-note.md + payload content. Empty or unevidenced elements are "
                "rejected; the script never authors content (SSOT §3.4)."
            ),
            "required_elements": list(NOTE_ELEMENTS),
            "element_claim_types": dict(ELEMENT_CLAIM_TYPE),
            "evidence_ref_format": EVIDENCE_REF_FORMAT,
        },
        "evidence_digest": digest,
        # --- agent fills each element.content + element.evidence_refs below ---
        "elements": elements,
    }


def _elements_by_name(fill: Any) -> dict[str, dict]:
    elements: dict[str, dict] = {}
    if isinstance(fill, dict):
        raw = fill.get("elements")
        if isinstance(raw, (list, tuple)):
            for item in raw:
                if isinstance(item, dict) and str(item.get("element") or "").strip():
                    elements[str(item.get("element")).strip().lower()] = item
    return elements


def _claim_from_element(name: str, element: dict) -> dict:
    return {
        "id": f"claim-{name}",
        "text": clean_text(str(element.get("content") or "")),
        "claim_type": str(element.get("claim_type") or ELEMENT_CLAIM_TYPE.get(name, "inference")),
        "confirmation_status": "pending_user_confirmation",
        "evidence_refs": element.get("evidence_refs") or [],
    }


def verify_note_fill(fill: Any, unit_dir: Path) -> tuple[list[str], list[dict]]:
    """Validate an agent-filled 4-element blog note. Returns (violations, claims).

    Violations name the offending element. All four elements must be present,
    carry non-empty content, be structurally valid (validate_claims), and every
    evidence_ref quote must verify verbatim against the artifact
    (verify_claim_evidence).
    """
    violations: list[str] = []
    elements = _elements_by_name(fill)
    claims: list[dict] = []
    for name in NOTE_ELEMENTS:
        element = elements.get(name)
        if element is None:
            violations.append(f"element '{name}': missing (all four elements are required)")
            continue
        content = clean_text(str(element.get("content") or ""))
        if not content:
            violations.append(f"element '{name}': empty content — the agent must fill it")
        refs = element.get("evidence_refs") or []
        if not refs:
            violations.append(f"element '{name}': no evidence_refs — every element must cite >=1 verbatim quote")
        claim = _claim_from_element(name, element)
        claims.append(claim)
        for violation in verify_claim_evidence(claim, unit_dir):
            violations.append(f"element '{name}': {violation}")
    # Structural + judgement-evidence rules (research.evidence).
    for violation in validate_claims(claims):
        violations.append(f"claim-structure: {violation}")
    return violations, claims


def _apply_note_fill_to_payload(record: dict, claims: list[dict]) -> None:
    """Route verified element content into canonical payload fields (in place)."""
    payload = record.setdefault("payload", {})
    positioning = payload.setdefault("positioning", {})
    content = payload.setdefault("content", {})
    credibility = payload.setdefault("credibility", {})
    by_id = {str(claim.get("id") or ""): claim for claim in claims}
    for name in NOTE_ELEMENTS:
        claim = by_id.get(f"claim-{name}")
        if claim is None:
            continue
        text = clean_text(str(claim.get("text") or ""))
        section, field, shape = ELEMENT_TARGET[name]
        if section == "positioning":
            target = positioning
        elif section == "content":
            target = content
        else:
            target = credibility
        if shape == "list":
            existing = target.get(field)
            items = list(existing) if isinstance(existing, list) else []
            if text and text not in items:
                items.append(text)
            target[field] = items
        else:
            target[field] = text


def render_note_md(record: dict, claims: list[dict]) -> str:
    """Render blog-note.md from verified elements + their evidence citations."""
    title = str(record.get("title") or record.get("id") or "")
    by_id = {str(claim.get("id") or ""): claim for claim in claims}
    lines = [
        f"# {title}",
        "",
        "> 本笔记由 runtime agent 依据 parse-cache 填写；脚本已逐字校验每条 evidence（SSOT 原则1/原则2）。",
        "> 博客来源为网页内容（HTML section/anchor 定位，无页码）。",
        "",
    ]
    for name in NOTE_ELEMENTS:
        lines.append(f"## {ELEMENT_HEADING[name]}")
        lines.append("")
        claim = by_id.get(f"claim-{name}")
        content = clean_text(str(claim.get("text") or "")) if claim else ""
        lines.append(content or "-")
        lines.append("")
        refs = (claim.get("evidence_refs") if claim else None) or []
        if refs:
            lines.append("证据：")
            for ref in refs:
                if not isinstance(ref, dict):
                    continue
                locator = str(ref.get("locator") or "?")
                quote = clean_text(str(ref.get("quote") or ""))
                summary = clean_text(str(ref.get("summary") or ""))
                suffix = f" — {summary}" if summary else ""
                lines.append(f"- [{locator}] \"{quote}\"{suffix}")
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _resolve_fill_input(unit_root: Path, default_name: str, explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = unit_root / explicit
        return candidate
    return unit_root / default_name


def next_for_agent_note(root: Path, record: dict, cache_path: Path, fill_path: Path) -> str:
    """One machine-readable navigation line for the ingestion auto-drive (SSOT §7).

    Pure navigation: names the parse-cache artifact to read, the elements to fill
    (each needs a verbatim quote + section/anchor locator), and the exact verify
    command to run after. Blogs are web pages (section/anchor locators, no page numbers).
    """
    elements = ",".join(NOTE_ELEMENTS)
    verify_cmd = (
        f"${{RESEARCH_PYTHON:-python3}} {SCRIPT_PATH} --root {root} "
        f"complete-note --blog-id {record['id']} --phase verify --input {fill_path.name}"
    )
    read_hint = rel(root, cache_path) if cache_path.exists() else "parse-cache.yaml"
    return (
        f"NEXT FOR AGENT: read {read_hint} (source quotes) then fill {rel(root, fill_path)} "
        f"elements [{elements}] — each needs content + >=1 verbatim quote+locator "
        f"(HTML section / section:<anchor>), then run: {verify_cmd}"
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Prepare fillable blog structures + verify agent-filled understanding."
    )
    add_project_root_argument(parser)
    subparsers = parser.add_subparsers(dest="command", required=True)

    note = subparsers.add_parser("complete-note")
    note.add_argument("--blog-id", required=True)
    note.add_argument("--phase", choices=["prepare", "verify"], default="prepare")
    note.add_argument("--input", default="")

    confirm = subparsers.add_parser("confirm")
    confirm.add_argument("--blog-id", required=True)
    add_confirmation_arguments(confirm)

    return parser


def _run_complete_note(args, root: Path, record: dict, unit_root: Path) -> int:
    fill_scaffold_path = unit_root / "blog-fill.yaml"
    note_path = unit_root / "blog-note.md"
    cache_path = _cache_path(unit_root)
    source_chunks, _locator_kind = _load_cache_chunks(unit_root)

    if args.phase == "prepare":
        payload = build_note_scaffold(
            record,
            source_chunks,
            digest_chunks=12,
            digest_chars=1200,
        )
        write_yaml_if_changed(fill_scaffold_path, payload)
        record["maturity"] = "complete"
        record["confirmation_status"] = "pending_user_confirmation"
        record["needs_human_confirmation"] = True
        record["information_types"] = ["fact", "inference", "evaluation", "unverified"]
        record["payload"].setdefault("state", {})["full_note_status"] = "awaiting_agent_fill"
        append_history(
            record,
            action="blog-note-scaffolded",
            summary="Prepared 4-element fillable blog note skeleton (script authored nothing).",
            information_types=["inference", "unverified"],
            artifacts=[rel(root, fill_scaffold_path), rel(root, cache_path)] if cache_path.exists() else [rel(root, fill_scaffold_path)],
        )
        write_record(root, record)
        build_index(root)
        print(f"[ok] wrote {fill_scaffold_path.relative_to(root)}")
        print(
            "下一步：agent 读 parse-cache 填四要素"
            "(positioning/key_points/credibility/reusable_explanation)"
            "带证据，再跑 `blog.py complete-note --phase verify --blog-id <id>`。"
        )
        print(next_for_agent_note(root, record, cache_path, fill_scaffold_path))
        return 0

    # verify
    fill_path = _resolve_fill_input(unit_root, "blog-fill.yaml", args.input)
    if not fill_path.exists():
        raise SystemExit(f"complete-note --phase verify: fill input not found: {fill_path}")
    fill = load_yaml(fill_path, default={})
    if not isinstance(fill, dict):
        raise SystemExit(f"complete-note --phase verify: {fill_path} is not a mapping")
    violations, claims = verify_note_fill(fill, unit_root)
    if violations:
        print("[reject] blog note fill failed verification:", file=sys.stderr)
        for violation in violations:
            print(f"  - {violation}", file=sys.stderr)
        raise SystemExit(1)

    _apply_note_fill_to_payload(record, claims)
    write_text_if_changed(note_path, render_note_md(record, claims))
    note_payload = {"blog_id": record["id"], "kind": "blog"}
    attach_claims(note_payload, claims)
    write_yaml_if_changed(unit_root / "blog-claims.yaml", note_payload)
    record["maturity"] = "complete"
    record["confirmation_status"] = "pending_user_confirmation"
    record["needs_human_confirmation"] = True
    record["information_types"] = ["fact", "inference", "evaluation", "unverified"]
    record["payload"].setdefault("state", {})["full_note_status"] = "pending_user_confirmation"
    append_history(
        record,
        action="blog-note-verified",
        summary="Verified + persisted agent 4-element blog note (evidence-grounded).",
        information_types=["inference", "evaluation", "unverified"],
        artifacts=[rel(root, note_path), rel(root, cache_path)] if cache_path.exists() else [rel(root, note_path)],
    )
    write_record(root, record)
    build_index(root)
    print(f"[ok] verified + wrote {note_path.relative_to(root)} (content filled, {len(claims)} elements)")
    return 0


def main() -> int:
    args = build_parser().parse_args()
    root = project_root(PROJECT_ROOT, explicit_root=args.root)
    print_resolved_project_roots(root)
    record, path = locate_record(root, args.blog_id, kind="blog")
    if record.get("kind") != "blog":
        raise SystemExit(f"{args.blog_id} is not a blog record")
    unit_root = path.parent

    if args.command == "complete-note":
        return _run_complete_note(args, root, record, unit_root)

    if args.command == "confirm":
        record = confirm_unit(
            record,
            "blog",
            confirmed_by=args.confirmed_by,
            evidence=args.evidence,
            method="blog.py confirm",
            project_root=root,
        )
        write_record(root, record)
        build_index(root)
        print(f"[ok] confirmed {args.blog_id}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
