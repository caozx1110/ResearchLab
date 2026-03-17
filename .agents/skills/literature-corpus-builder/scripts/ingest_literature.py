#!/usr/bin/env python3
"""Ingest local PDFs and literature URLs into doc/research/library/literature."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Any

for candidate in [Path(__file__).resolve()] + list(Path(__file__).resolve().parents):
    lib_root = candidate / ".agents" / "lib"
    if (lib_root / "research_v11" / "common.py").exists():
        sys.path.insert(0, str(lib_root))
        break

from research_v11.common import (
    bootstrap_workspace,
    canonical_literature_source,
    canonicalize_url,
    clean_text,
    discover_keyword_tags,
    domain_profile_path,
    ensure_research_runtime,
    extract_pdf_record,
    fetch_url,
    file_sha256,
    find_first_pdf_link,
    find_project_root,
    guess_source_kind,
    html_to_text,
    infer_topics_and_tags,
    is_url,
    literature_index_path,
    literature_tag_taxonomy_path,
    literature_tags_path,
    load_index,
    load_list_document,
    load_yaml,
    make_source_id,
    merge_keyword_tags,
    parse_arxiv_id,
    parse_openreview_id,
    pending_paper_reviews_path,
    raw_root,
    research_root,
    rebuild_literature_index,
    rebuild_literature_tag_index,
    resolved_paper_reviews_path,
    score_fuzzy_literature_match,
    slugify,
    slugify_tag,
    utc_now_iso,
    write_text_if_changed,
    write_yaml_if_changed,
    yaml_default,
)


def intake_root(project_root: Path) -> Path:
    return research_root(project_root) / "intake" / "papers" / "downloads"


NOTE_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "assets" / "note-template.md"
MANUAL_NOTE_HEADERS = ("## Working Notes", "## Manual Notes")


def canonical_entry_root(project_root: Path, source_id: str) -> Path:
    return research_root(project_root) / "library" / "literature" / source_id


def log_progress(message: str) -> None:
    print(message, flush=True)


def relative_path(project_root: Path, path: Path) -> str:
    return path.resolve().relative_to(project_root.resolve()).as_posix()


def blank_tag_taxonomy_payload() -> dict[str, Any]:
    return {
        **yaml_default("literature-tag-taxonomy", "literature-corpus-builder", status="active", confidence=0.75),
        "policy": {
            "canonical_style": "lowercase-hyphen-slug",
            "unknown_tag_policy": "allow-with-lint",
            "notes": "Canonical tags should be short, reusable, and stable across papers.",
        },
        "items": {},
    }


def auto_tagging_payload(project_root: Path, candidate: dict[str, Any]) -> dict[str, Any]:
    keyword_candidates = [item for item in candidate.get("keyword_candidates", []) if isinstance(item, dict)]
    auto_adopted = [
        slugify_tag(str(tag))
        for tag in candidate.get("auto_adopted_tags", [])
        if slugify_tag(str(tag))
    ]
    text_field = "field:abstract" if str(candidate.get("abstract") or "").strip() else "field:text_preview"
    return {
        "updated_by": "literature-corpus-builder",
        "updated_at": utc_now_iso(),
        "mode": "seed",
        "strategy": "domain-profile-plus-keyword-discovery",
        "inputs": [
            "field:canonical_title",
            text_field,
            relative_path(project_root, domain_profile_path(project_root)),
        ],
        "keyword_candidates": keyword_candidates,
        "auto_adopted_tags": sorted(set(auto_adopted)),
    }


def refresh_tag_views_for_source(project_root: Path, metadata: dict[str, Any]) -> None:
    taxonomy_path = literature_tag_taxonomy_path(project_root)
    taxonomy = load_yaml(taxonomy_path, default={})
    if not isinstance(taxonomy, dict):
        taxonomy = blank_tag_taxonomy_payload()
    taxonomy.setdefault("id", "literature-tag-taxonomy")
    taxonomy.setdefault("status", "active")
    taxonomy.setdefault("generated_by", "literature-corpus-builder")
    taxonomy.setdefault("generated_at", utc_now_iso())
    taxonomy.setdefault("inputs", [])
    taxonomy.setdefault("confidence", 0.75)
    taxonomy.setdefault("policy", blank_tag_taxonomy_payload()["policy"])
    items = taxonomy.get("items", {})
    taxonomy["items"] = items if isinstance(items, dict) else {}

    tagging = metadata.get("tagging", {})
    keyword_tags = {
        slugify_tag(str(item.get("tag") or ""))
        for item in tagging.get("keyword_candidates", [])
        if isinstance(item, dict) and slugify_tag(str(item.get("tag") or ""))
    } if isinstance(tagging, dict) else set()
    auto_adopted = {
        slugify_tag(str(item))
        for item in tagging.get("auto_adopted_tags", [])
        if isinstance(tagging, dict) and slugify_tag(str(item))
    } if isinstance(tagging, dict) else set()
    discovered_tags = keyword_tags | auto_adopted

    for raw_tag in metadata.get("tags", []):
        canonical = slugify_tag(str(raw_tag))
        if not canonical:
            continue
        item = taxonomy["items"].get(canonical, {})
        aliases = sorted(
            {
                slugify_tag(str(alias))
                for alias in item.get("aliases", [])
                if slugify_tag(str(alias)) and slugify_tag(str(alias)) != canonical
            }
        ) if isinstance(item, dict) else []
        topic_hints = sorted(
            set(str(topic).strip() for topic in (metadata.get("topics", []) or []) if str(topic).strip())
            | set(str(topic).strip() for topic in (item.get("topic_hints", []) if isinstance(item, dict) else []) if str(topic).strip())
        )
        description = ""
        if isinstance(item, dict):
            description = str(item.get("description") or "").strip()
        if not description and canonical in discovered_tags:
            description = "Auto-discovered keyword tag from canonical literature metadata."
        status = ""
        if isinstance(item, dict):
            status = str(item.get("status") or "").strip()
        if not status:
            status = "discovered" if canonical in discovered_tags else "active"
        taxonomy["items"][canonical] = {
            "id": canonical,
            "canonical_tag": canonical,
            "aliases": aliases,
            "topic_hints": topic_hints,
            "description": description,
            "status": status,
        }

    existing_inputs = taxonomy.get("inputs", [])
    inputs = {str(item).strip() for item in existing_inputs if str(item).strip()}
    if metadata.get("id"):
        inputs.add(f"lit:{metadata['id']}")
    taxonomy["inputs"] = sorted(inputs)
    taxonomy["generated_by"] = "literature-corpus-builder"
    taxonomy["generated_at"] = utc_now_iso()
    write_yaml_if_changed(taxonomy_path, taxonomy)
    rebuild_literature_tag_index(project_root, generated_by="literature-corpus-builder")


def _load_note_template() -> str:
    return NOTE_TEMPLATE_PATH.read_text(encoding="utf-8")


def _format_inline_values(values: list[str]) -> str:
    cleaned = [str(value).strip() for value in values if str(value).strip()]
    if not cleaned:
        return "n/a"
    return ", ".join(f"`{value}`" for value in cleaned)


def _truncate_summary(text: str, max_chars: int = 320) -> str:
    text = re.sub(r"\s+", " ", clean_text(text)).strip()
    if len(text) <= max_chars:
        return text
    trimmed = text[: max_chars - 3].rsplit(" ", 1)[0].rstrip(" ,;:-")
    if not trimmed:
        trimmed = text[: max_chars - 3]
    return f"{trimmed}..."


def _split_summary_sentences(text: str) -> list[str]:
    cleaned = re.sub(r"\s+", " ", clean_text(text)).strip()
    if not cleaned:
        return []
    parts = [clean_text(part) for part in re.split(r"(?<=[.!?])\s+", cleaned) if clean_text(part)]
    return parts or [cleaned]


def _normalize_extracted_abstract(text: str) -> str:
    text = str(text or "").replace("\u00ad", "")
    match = re.search(r"(?i)\babstract\b\s*[:\-\u2013\u2014 ]*", text)
    if match and match.start() <= 600:
        text = text[match.end() :]
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    return clean_text(text)


def _is_noisy_abstract(text: str) -> bool:
    cleaned = clean_text(text)
    if not cleaned:
        return True
    if len(re.findall(r"/C\d{1,3}", cleaned)) >= 5:
        return True
    if sum(ch.isalpha() for ch in cleaned) < 40:
        return True
    return False


def _fallback_title_summary(title: str, *, max_chars: int = 320) -> str:
    title = clean_text(title)
    title = re.sub(r"[${}\\]", "", title)
    title = title.replace("_", "")
    title = re.sub(r"\s+", " ", title).strip()
    if not title:
        return "No summary available yet."
    if ":" in title:
        head, tail = [clean_text(part) for part in title.split(":", 1)]
        if head and tail:
            return _truncate_summary(f"Paper introducing {head}, {tail.rstrip('.')}.", max_chars=max_chars)
    return _truncate_summary(f"Paper on {title.rstrip('.')}.", max_chars=max_chars)


def build_short_summary(title: str, abstract: str, *, max_chars: int = 320) -> str:
    title = clean_text(title)
    abstract = _normalize_extracted_abstract(abstract)
    if not abstract or _is_noisy_abstract(abstract):
        return _fallback_title_summary(title, max_chars=max_chars)
    sentences = _split_summary_sentences(abstract)
    selected: list[str] = []
    keywords = (" propose ", " present ", " introduce ", " show ", " evaluate ", " release ", " train ", " scale ", " achieve ", " outperform ", " match ")
    for sentence in sentences:
        normalized = clean_text(sentence)
        if not normalized:
            continue
        lowered = f" {normalized.lower()} "
        if not selected:
            selected.append(normalized)
            continue
        if any(token in lowered for token in keywords) or len(selected) < 2:
            candidate = " ".join(selected + [normalized])
            if len(candidate) <= max_chars:
                selected.append(normalized)
            break
    summary = " ".join(selected) or abstract
    if title and summary.lower().startswith(title.lower()):
        summary = clean_text(summary[len(title) :].lstrip(" :-\u2013\u2014"))
    return _truncate_summary(summary or abstract, max_chars=max_chars)


def _working_notes_block(note_path: Path) -> str:
    if note_path.exists():
        existing = note_path.read_text(encoding="utf-8")
        for header in MANUAL_NOTE_HEADERS:
            start = existing.find(header)
            if start >= 0:
                preserved = existing[start:].strip()
                if preserved:
                    return preserved
    return (
        "## Working Notes\n\n"
        "- Pending deeper read: replace this scaffold with concrete claims, method details, benchmarks, and caveats.\n"
    )


def _render_note_template(context: dict[str, str]) -> str:
    note = _load_note_template()
    for key, value in context.items():
        note = note.replace(f"{{{{{key}}}}}", value)
    return note.rstrip() + "\n"


def ensure_metadata_short_summary(metadata: dict[str, Any], *, rewrite: bool = False) -> str:
    existing = clean_text(str(metadata.get("short_summary") or ""))
    if existing and not rewrite:
        return existing
    summary = build_short_summary(
        str(metadata.get("canonical_title") or ""),
        str(metadata.get("abstract") or ""),
    )
    metadata["short_summary"] = summary
    return summary


def build_literature_note(source_id: str, metadata: dict[str, Any], *, note_path: Path) -> str:
    summary = ensure_metadata_short_summary(metadata, rewrite=False)
    authors = [str(author).strip() for author in metadata.get("authors", []) if str(author).strip()]
    cleaned_abstract = _normalize_extracted_abstract(str(metadata.get("abstract") or ""))
    if _is_noisy_abstract(cleaned_abstract):
        cleaned_abstract = "Abstract extraction looks noisy for this source. Inspect the PDF or landing page directly if you need the full text."
    retrieval_lines = [
        f"- Search tags: {_format_inline_values(metadata.get('tags', []))}",
        f"- Search topics: {_format_inline_values(metadata.get('topics', []))}",
    ]
    if authors:
        retrieval_lines.append(f"- Author cue: `{authors[0]}`")
    if metadata.get("year"):
        retrieval_lines.append(f"- Time cue: `{metadata['year']}`")
    context = {
        "title": str(metadata.get("canonical_title") or source_id),
        "source_id": source_id,
        "source_kind": str(metadata.get("source_kind") or "paper"),
        "year": str(metadata.get("year") or "unknown"),
        "authors": ", ".join(authors) if authors else "n/a",
        "canonical_url": str(metadata.get("canonical_url") or "n/a"),
        "tags": _format_inline_values(metadata.get("tags", [])),
        "topics": _format_inline_values(metadata.get("topics", [])),
        "short_summary": summary or "No short summary available yet.",
        "retrieval_cues": "\n".join(retrieval_lines),
        "abstract": cleaned_abstract or "No abstract extracted yet.",
        "working_notes_block": _working_notes_block(note_path),
    }
    return _render_note_template(context)


def build_placeholder_claims(source_id: str, abstract: str, *, source_inputs: list[str]) -> dict[str, Any]:
    cleaned_abstract = _normalize_extracted_abstract(abstract)
    snippet = _truncate_summary(cleaned_abstract, max_chars=500) if cleaned_abstract else ""
    observed: list[dict[str, Any]] = []
    if snippet:
        observed.append(
            {
                "claim_id": f"{source_id}-claim-placeholder-1",
                "claim_kind": "placeholder-abstract-snippet",
                "verified": False,
                "statement": snippet,
                "notes": "Auto-seeded from the abstract for retrieval triage only.",
            }
        )
    return {
        **yaml_default(f"{source_id}-claims", "literature-corpus-builder", status="placeholder", confidence=0.25),
        "inputs": source_inputs,
        "claim_status": "placeholder-unverified",
        "claim_origin": "abstract-snippet",
        "usage_guidance": "Do not treat Observed statements in this file as verified paper claims. Replace them after manual reading or a dedicated claim extraction pass.",
        "Observed": observed,
        "Inferred": [],
        "Suggested": [],
        "OpenQuestions": (
            ["Which claims should be promoted from this placeholder scaffold after manual reading?"]
            if observed
            else ["No abstract snippet was available. Add verified claims after reading the source."]
        ),
    }


def refresh_canonical_notes(project_root: Path, source_ids: list[str] | None = None, *, rewrite_summary: bool = False) -> int:
    literature_root = research_root(project_root) / "library" / "literature"
    metadata_paths = (
        [literature_root / source_id / "metadata.yaml" for source_id in source_ids]
        if source_ids
        else sorted(literature_root.glob("*/metadata.yaml"))
    )
    changed = 0
    for metadata_path in metadata_paths:
        if not metadata_path.exists():
            raise SystemExit(f"Missing literature metadata: {metadata_path}")
        metadata = load_yaml(metadata_path, default={})
        if not isinstance(metadata, dict) or not metadata.get("id"):
            raise SystemExit(f"Invalid literature metadata: {metadata_path}")
        source_id = str(metadata["id"])
        before_summary = clean_text(str(metadata.get("short_summary") or ""))
        summary = ensure_metadata_short_summary(metadata, rewrite=rewrite_summary)
        if summary != before_summary:
            write_yaml_if_changed(metadata_path, metadata)
            changed += 1
        note_path = metadata_path.parent / "note.md"
        note_text = build_literature_note(source_id, metadata, note_path=note_path)
        before_note = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
        write_text_if_changed(note_path, note_text)
        if note_text != before_note:
            changed += 1
    rebuild_literature_index(project_root)
    return changed


def refresh_placeholder_claims(project_root: Path, source_ids: list[str] | None = None, *, force: bool = False) -> int:
    literature_root = research_root(project_root) / "library" / "literature"
    metadata_paths = (
        [literature_root / source_id / "metadata.yaml" for source_id in source_ids]
        if source_ids
        else sorted(literature_root.glob("*/metadata.yaml"))
    )
    changed = 0
    curated_statuses = {"curated", "verified", "manually-reviewed"}
    for metadata_path in metadata_paths:
        if not metadata_path.exists():
            raise SystemExit(f"Missing literature metadata: {metadata_path}")
        metadata = load_yaml(metadata_path, default={})
        if not isinstance(metadata, dict) or not metadata.get("id"):
            raise SystemExit(f"Invalid literature metadata: {metadata_path}")
        source_id = str(metadata["id"])
        claims_path = metadata_path.parent / "claims.yaml"
        existing = load_yaml(claims_path, default={}) if claims_path.exists() else {}
        existing_observed = existing.get("Observed", []) if isinstance(existing, dict) else []
        existing_status = str(existing.get("claim_status") or "").strip().lower() if isinstance(existing, dict) else ""
        has_verified_claims = any(
            isinstance(item, dict) and bool(item.get("verified"))
            for item in existing_observed
        )
        if claims_path.exists() and not force and (existing_status in curated_statuses or has_verified_claims):
            continue
        source_inputs = [str(item) for item in metadata.get("inputs", [])] if isinstance(metadata.get("inputs"), list) else []
        claims_payload = build_placeholder_claims(
            source_id,
            str(metadata.get("abstract") or ""),
            source_inputs=source_inputs,
        )
        before_text = claims_path.read_text(encoding="utf-8") if claims_path.exists() else ""
        write_yaml_if_changed(claims_path, claims_payload)
        after_text = claims_path.read_text(encoding="utf-8")
        if after_text != before_text:
            changed += 1
    return changed


def unique_source_id(project_root: Path, base_id: str) -> str:
    existing = load_index(literature_index_path(project_root), "literature-index", "literature-corpus-builder")
    items = existing.get("items", {})
    if base_id not in items:
        return base_id
    suffix = 2
    while f"{base_id}-{suffix}" in items:
        suffix += 1
    return f"{base_id}-{suffix}"


def _to_manifest_value(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        **candidate,
        "staged_pdf": str(candidate["staged_pdf"]) if candidate.get("staged_pdf") else "",
        "staged_html": str(candidate["staged_html"]) if candidate.get("staged_html") else "",
        "staged_capture": str(candidate["staged_capture"]) if candidate.get("staged_capture") else "",
    }


def _from_manifest_value(candidate: dict[str, Any]) -> dict[str, Any]:
    candidate["staged_pdf"] = Path(candidate["staged_pdf"]) if candidate.get("staged_pdf") else None
    candidate["staged_html"] = Path(candidate["staged_html"]) if candidate.get("staged_html") else None
    candidate["staged_capture"] = Path(candidate["staged_capture"]) if candidate.get("staged_capture") else None
    return candidate


def stage_local_pdf(project_root: Path, source: Path) -> tuple[Path, dict[str, Any]]:
    intake_id = f"paper-intake-{utc_now_iso().replace(':', '-').replace('+00:00', 'z')}-{slugify(source.stem, max_words=4)}"
    stage_dir = intake_root(project_root) / intake_id
    source_dir = stage_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)
    staged_pdf = source_dir / source.name
    raw_dir = raw_root(project_root).resolve()
    consumed_from_raw = source.resolve().is_relative_to(raw_dir)
    shutil.copy2(source, staged_pdf)
    try:
        parsed = extract_pdf_record(staged_pdf)
        keyword_candidates = discover_keyword_tags(
            parsed["title"],
            parsed["abstract"],
            project_root=project_root,
            existing_tags=parsed.get("tags", []),
        )
        merged_tags = merge_keyword_tags(parsed.get("tags", []), keyword_candidates)
        canonical_url, site_fingerprint = canonical_literature_source(
            {
                "arxiv_id": parsed["arxiv_id"],
                "doi": parsed["doi"],
                "openreview_id": "",
            }
        )
        candidate = {
            "intake_id": intake_id,
            "title": parsed["title"],
            "authors": parsed["authors"],
            "abstract": parsed["abstract"],
            "year": parsed["year"],
            "source_kind": "paper",
            "canonical_url": canonical_url,
            "site_fingerprint": site_fingerprint or "local-pdf",
            "external_ids": {
                "arxiv_id": parsed["arxiv_id"],
                "doi": parsed["doi"],
                "openreview_id": "",
            },
            "topics": parsed["topics"],
            "tags": merged_tags,
            "keyword_candidates": keyword_candidates,
            "auto_adopted_tags": [item["tag"] for item in keyword_candidates if item.get("tag") in merged_tags],
            "file_sha256": file_sha256(staged_pdf),
            "staged_pdf": staged_pdf,
            "staged_html": None,
            "staged_capture": None,
            "source_label": str(source),
            "text_preview": parsed["text_preview"],
        }
        write_yaml_if_changed(stage_dir / "manifest.yaml", {"candidate": _to_manifest_value(candidate)})
    except Exception:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise
    if consumed_from_raw:
        source.unlink()
    return stage_dir, candidate


def _extract_html_title(html: str) -> str:
    match = re.search(r"(?is)<title>(.*?)</title>", html)
    return clean_text(match.group(1)) if match else ""


def stage_url(project_root: Path, url: str) -> tuple[Path, dict[str, Any]]:
    canonical_url = canonicalize_url(url)
    intake_id = f"paper-intake-{utc_now_iso().replace(':', '-').replace('+00:00', 'z')}-{slugify(canonical_url, max_words=4)}"
    stage_dir = intake_root(project_root) / intake_id
    source_dir = stage_dir / "source"
    source_dir.mkdir(parents=True, exist_ok=True)

    arxiv_id = parse_arxiv_id(canonical_url)
    openreview_id = parse_openreview_id(canonical_url)
    landing_url = canonical_url
    pdf_url = ""
    title = ""
    authors: list[str] = []
    year: int | None = None
    abstract = ""
    topics: list[str] = []
    tags: list[str] = []
    file_sha = ""
    doi = ""
    staged_pdf: Path | None = None
    staged_html: Path | None = None
    staged_capture: Path | None = None
    source_kind = "paper"
    content_type = ""

    capture_text = ""
    try:
        if arxiv_id:
            landing_url = f"https://arxiv.org/abs/{arxiv_id}"
            pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
        elif openreview_id:
            pdf_url = f"https://openreview.net/pdf?id={openreview_id}"

        if pdf_url or canonical_url.lower().endswith(".pdf"):
            binary_url = pdf_url or canonical_url
            log_progress(f"[download-pdf] {binary_url}")
            payload, content_type = fetch_url(binary_url, binary=True)
            staged_pdf = source_dir / "primary.pdf"
            staged_pdf.write_bytes(payload)
            log_progress(f"[parse-pdf] {staged_pdf.name}")
            parsed = extract_pdf_record(staged_pdf)
            title = parsed["title"]
            authors = parsed["authors"]
            year = parsed["year"]
            abstract = parsed["abstract"]
            topics = parsed["topics"]
            tags = parsed["tags"]
            file_sha = file_sha256(staged_pdf)
            doi = parsed["doi"]
            if not arxiv_id:
                arxiv_id = parsed["arxiv_id"]

        log_progress(f"[download-html] {landing_url}")
        html_payload, html_type = fetch_url(landing_url, binary=False)
        content_type = content_type or html_type
        staged_html = source_dir / "landing.html"
        staged_html.write_text(html_payload, encoding="utf-8")
        title = title or _extract_html_title(html_payload)
        capture_text = html_to_text(html_payload)
        staged_capture = source_dir / "capture.md"
        staged_capture.write_text(
            f"# Capture\n\n- URL: {landing_url}\n- Captured At: {utc_now_iso()}\n\n{capture_text[:8000]}\n",
            encoding="utf-8",
        )
        source_kind = guess_source_kind(canonical_url, title=title, content_type=content_type)
        if not staged_pdf:
            maybe_pdf = find_first_pdf_link(html_payload, landing_url)
            if maybe_pdf:
                log_progress(f"[discover-pdf] {maybe_pdf}")
                payload, _ = fetch_url(maybe_pdf, binary=True)
                staged_pdf = source_dir / "primary.pdf"
                staged_pdf.write_bytes(payload)
                log_progress(f"[parse-pdf] {staged_pdf.name}")
                parsed = extract_pdf_record(staged_pdf)
                title = parsed["title"] or title
                authors = parsed["authors"] or authors
                year = parsed["year"] or year
                abstract = parsed["abstract"] or abstract
                topics = parsed["topics"] or topics
                tags = parsed["tags"] or tags
                file_sha = file_sha256(staged_pdf)
                doi = parsed["doi"] or doi
                if not arxiv_id:
                    arxiv_id = parsed["arxiv_id"]

        if not topics or not tags:
            topics, tags = infer_topics_and_tags(f"{title}\n{capture_text[:3000]}")
        keyword_candidates = discover_keyword_tags(
            title,
            abstract or capture_text[:3000],
            project_root=project_root,
            existing_tags=tags,
        )
        tags = merge_keyword_tags(tags, keyword_candidates)

        candidate = {
            "intake_id": intake_id,
            "title": title or canonical_url,
            "authors": authors,
            "abstract": abstract,
            "year": year,
            "source_kind": source_kind,
            "canonical_url": canonical_url,
            "site_fingerprint": re.sub(r"^www\.", "", canonical_url.split("/")[2]).lower(),
            "external_ids": {
                "arxiv_id": arxiv_id,
                "doi": doi,
                "openreview_id": openreview_id,
            },
            "topics": topics,
            "tags": tags,
            "keyword_candidates": keyword_candidates,
            "auto_adopted_tags": [item["tag"] for item in keyword_candidates if item.get("tag") in tags],
            "file_sha256": file_sha,
            "staged_pdf": staged_pdf,
            "staged_html": staged_html,
            "staged_capture": staged_capture,
            "source_label": url,
            "text_preview": abstract or capture_text[:1500],
        }
        write_yaml_if_changed(stage_dir / "manifest.yaml", {"candidate": _to_manifest_value(candidate)})
        return stage_dir, candidate
    except Exception:
        shutil.rmtree(stage_dir, ignore_errors=True)
        raise


def load_manifest_candidate(stage_dir: Path) -> dict[str, Any]:
    payload = load_yaml(stage_dir / "manifest.yaml", default={})
    if not isinstance(payload, dict) or not isinstance(payload.get("candidate"), dict):
        raise SystemExit(f"Invalid intake manifest: {stage_dir / 'manifest.yaml'}")
    return _from_manifest_value(payload["candidate"])


def exact_match(existing: dict[str, Any], candidate: dict[str, Any]) -> bool:
    ext = existing.get("external_ids", {})
    cand_ext = candidate.get("external_ids", {})
    if candidate.get("file_sha256") and candidate.get("file_sha256") in existing.get("file_hashes", []):
        return True
    if candidate.get("canonical_url") and candidate.get("canonical_url") == existing.get("canonical_url"):
        return True
    for key in ("arxiv_id", "doi", "openreview_id"):
        if ext.get(key) and ext.get(key) == cand_ext.get(key):
            return True
    return False


def register_resolved_review(project_root: Path, review_item: dict[str, Any]) -> None:
    payload = load_list_document(resolved_paper_reviews_path(project_root), "resolved-paper-reviews", "literature-corpus-builder")
    payload["generated_at"] = utc_now_iso()
    payload["items"].append(review_item)
    write_yaml_if_changed(resolved_paper_reviews_path(project_root), payload)


def append_pending_review(project_root: Path, review_item: dict[str, Any]) -> None:
    payload = load_list_document(pending_paper_reviews_path(project_root), "pending-paper-reviews", "literature-corpus-builder")
    payload["generated_at"] = utc_now_iso()
    payload["items"].append(review_item)
    write_yaml_if_changed(pending_paper_reviews_path(project_root), payload)


def remove_pending_review(project_root: Path, review_id: str) -> dict[str, Any]:
    payload = load_list_document(pending_paper_reviews_path(project_root), "pending-paper-reviews", "literature-corpus-builder")
    kept: list[dict[str, Any]] = []
    matched: dict[str, Any] | None = None
    for item in payload["items"]:
        if item.get("review_id") == review_id:
            matched = item
        else:
            kept.append(item)
    if matched is None:
        raise SystemExit(f"Pending literature review not found: {review_id}")
    payload["items"] = kept
    payload["generated_at"] = utc_now_iso()
    write_yaml_if_changed(pending_paper_reviews_path(project_root), payload)
    return matched


def update_graph(project_root: Path) -> None:
    rebuild_literature_index(project_root)


def attach_alias(project_root: Path, canonical_id: str, candidate: dict[str, Any], *, resolution: str) -> None:
    literature_root = research_root(project_root) / "library" / "literature"
    metadata_path = literature_root / canonical_id / "metadata.yaml"
    metadata = load_yaml(metadata_path, default={})
    if not isinstance(metadata, dict):
        raise SystemExit(f"Missing canonical literature metadata: {metadata_path}")
    alias_entry = {
        "alias_id": candidate["intake_id"],
        "source_label": candidate["source_label"],
        "canonical_url": candidate.get("canonical_url", ""),
        "file_sha256": candidate.get("file_sha256", ""),
        "resolved_at": utc_now_iso(),
        "resolution": resolution,
    }
    metadata.setdefault("aliases", [])
    metadata["aliases"].append(alias_entry)
    metadata.setdefault("file_hashes", [])
    if candidate.get("file_sha256") and candidate["file_sha256"] not in metadata["file_hashes"]:
        metadata["file_hashes"].append(candidate["file_sha256"])

    alias_root = literature_root / canonical_id / "source" / "aliases" / candidate["intake_id"]
    alias_root.mkdir(parents=True, exist_ok=True)
    for staged_key, target_name in (("staged_pdf", "alias.pdf"), ("staged_html", "landing.html"), ("staged_capture", "capture.md")):
        staged = candidate.get(staged_key)
        if staged and Path(staged).exists():
            shutil.move(str(staged), alias_root / target_name)
    write_yaml_if_changed(metadata_path, metadata)

    index_payload = load_index(literature_index_path(project_root), "literature-index", "literature-corpus-builder")
    item = index_payload["items"].get(canonical_id, {})
    item.setdefault("aliases", [])
    item["aliases"].append(alias_entry)
    item.setdefault("source_paths", {})
    item["source_paths"].setdefault("aliases", [])
    item["source_paths"]["aliases"].append(alias_root.relative_to(find_project_root()).as_posix())
    item.setdefault("file_hashes", [])
    if candidate.get("file_sha256") and candidate["file_sha256"] not in item["file_hashes"]:
        item["file_hashes"].append(candidate["file_sha256"])
    index_payload["items"][canonical_id] = item
    write_yaml_if_changed(literature_index_path(project_root), index_payload)
    rebuild_literature_index(project_root)


def finalize_new_candidate(project_root: Path, candidate: dict[str, Any]) -> str:
    source_id = unique_source_id(project_root, make_source_id(candidate))
    entry_root = canonical_entry_root(project_root, source_id)
    source_root = entry_root / "source"
    source_root.mkdir(parents=True, exist_ok=True)
    source_paths: dict[str, Any] = {}
    if candidate.get("staged_pdf") and Path(candidate["staged_pdf"]).exists():
        target = source_root / "primary.pdf"
        shutil.move(str(candidate["staged_pdf"]), target)
        source_paths["primary_pdf"] = target.relative_to(find_project_root()).as_posix()
    if candidate.get("staged_html") and Path(candidate["staged_html"]).exists():
        target = source_root / "landing.html"
        shutil.move(str(candidate["staged_html"]), target)
        source_paths["landing_html"] = target.relative_to(find_project_root()).as_posix()
    if candidate.get("staged_capture") and Path(candidate["staged_capture"]).exists():
        target = source_root / "capture.md"
        shutil.move(str(candidate["staged_capture"]), target)
        source_paths["capture"] = target.relative_to(find_project_root()).as_posix()
    (source_root / "assets").mkdir(parents=True, exist_ok=True)
    (source_root / "aliases").mkdir(parents=True, exist_ok=True)
    source_inputs = [f"intake:{candidate['intake_id']}"]
    if candidate.get("canonical_url"):
        source_inputs.append(candidate["canonical_url"])
    source_inputs.extend(source_paths.values())

    metadata = {
        **yaml_default(source_id, "literature-corpus-builder", status="active", confidence=0.9),
        "inputs": source_inputs,
        "source_kind": candidate["source_kind"],
        "canonical_title": candidate["title"],
        "short_summary": build_short_summary(candidate["title"], candidate.get("abstract", "")),
        "authors": candidate.get("authors", []),
        "year": candidate.get("year"),
        "abstract": candidate.get("abstract", ""),
        "canonical_url": candidate.get("canonical_url", ""),
        "site_fingerprint": candidate.get("site_fingerprint", ""),
        "external_ids": candidate.get("external_ids", {}),
        "topics": candidate.get("topics", []),
        "tags": candidate.get("tags", []),
        "tagging": auto_tagging_payload(project_root, candidate),
        "source_paths": source_paths,
        "aliases": [],
        "file_hashes": [candidate["file_sha256"]] if candidate.get("file_sha256") else [],
    }
    claims = build_placeholder_claims(
        source_id,
        str(candidate.get("abstract") or ""),
        source_inputs=source_inputs,
    )
    methods = {
        **yaml_default(f"{source_id}-methods", "literature-corpus-builder"),
        "inputs": source_inputs,
        "Observed": [
            {
                "module_id": f"{source_id}-method-1",
                "summary": "Auto-generated placeholder. Replace with concrete method details after reading.",
            }
        ],
        "Inferred": [],
        "Suggested": [],
        "OpenQuestions": [],
    }
    note = build_literature_note(source_id, metadata, note_path=entry_root / "note.md")
    write_yaml_if_changed(entry_root / "metadata.yaml", metadata)
    write_yaml_if_changed(entry_root / "claims.yaml", claims)
    write_yaml_if_changed(entry_root / "methods.yaml", methods)
    write_text_if_changed(entry_root / "note.md", note)
    refresh_tag_views_for_source(project_root, metadata)

    index_payload = load_index(literature_index_path(project_root), "literature-index", "literature-corpus-builder")
    index_payload["generated_at"] = utc_now_iso()
    index_payload["items"][source_id] = {
        "id": source_id,
        "source_kind": candidate["source_kind"],
        "canonical_title": candidate["title"],
        "short_summary": metadata["short_summary"],
        "authors": candidate.get("authors", []),
        "year": candidate.get("year"),
        "canonical_url": candidate.get("canonical_url", ""),
        "site_fingerprint": candidate.get("site_fingerprint", ""),
        "external_ids": candidate.get("external_ids", {}),
        "aliases": [],
        "topics": candidate.get("topics", []),
        "tags": candidate.get("tags", []),
        "source_paths": source_paths,
        "file_hashes": [candidate["file_sha256"]] if candidate.get("file_sha256") else [],
    }
    write_yaml_if_changed(literature_index_path(project_root), index_payload)
    rebuild_literature_index(project_root)
    return source_id


def ingest_candidate(project_root: Path, candidate: dict[str, Any]) -> tuple[str, str]:
    index_payload = load_index(literature_index_path(project_root), "literature-index", "literature-corpus-builder")
    items = index_payload.get("items", {})
    for canonical_id, existing in items.items():
        if exact_match(existing, candidate):
            attach_alias(project_root, canonical_id, candidate, resolution="exact-duplicate")
            return "merged", canonical_id

    fuzzy_matches: list[tuple[float, str, list[str]]] = []
    for canonical_id, existing in items.items():
        score, reasons = score_fuzzy_literature_match(existing, candidate)
        if score >= 0.75:
            fuzzy_matches.append((score, canonical_id, reasons))
    fuzzy_matches.sort(reverse=True)
    if fuzzy_matches:
        top_score, top_canonical, reasons = fuzzy_matches[0]
        review_id = f"paper-review-{candidate['intake_id']}"
        append_pending_review(
            project_root,
            {
                "review_id": review_id,
                "intake_id": candidate["intake_id"],
                "candidate_title": candidate["title"],
                "candidate_year": candidate.get("year"),
                "candidate_authors": candidate.get("authors", []),
                "candidate_source_kind": candidate["source_kind"],
                "suggested_canonical_id": top_canonical,
                "similarity": round(top_score, 2),
                "reasons": reasons,
                "status": "pending",
            },
        )
        return "pending-review", review_id

    return "imported", finalize_new_candidate(project_root, candidate)


def persist_manifest(stage_dir: Path, candidate: dict[str, Any], *, status: str, result: str) -> None:
    write_yaml_if_changed(
        stage_dir / "manifest.yaml",
        {
            "candidate": _to_manifest_value(candidate),
            "status": status,
            "result": result,
            "updated_at": utc_now_iso(),
        },
    )


def ingest_sources(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    candidates = list(args.source)
    if args.search_result:
        search_payload = load_yaml(Path(args.search_result), default={})
        if isinstance(search_payload, dict):
            for item in search_payload.get("candidates", []):
                if isinstance(item, dict) and item.get("status", "shortlisted") in {"shortlisted", "selected"}:
                    url = item.get("url") or item.get("source_url")
                    if url:
                        candidates.append(str(url))
    if not candidates:
        candidates = [str(path) for path in sorted(Path(args.raw_dir).glob("*.pdf"))]
    if not candidates:
        raise SystemExit("No literature sources found to ingest.")

    failures: list[str] = []
    total = len(candidates)
    for index, raw_source in enumerate(candidates, start=1):
        log_progress(f"[start {index}/{total}] {raw_source}")
        stage_dir: Path | None = None
        candidate: dict[str, Any] | None = None
        try:
            if is_url(raw_source):
                log_progress(f"[fetch {index}/{total}] staging URL source")
                stage_dir, candidate = stage_url(project_root, raw_source)
            else:
                log_progress(f"[stage {index}/{total}] staging local PDF")
                stage_dir, candidate = stage_local_pdf(project_root, Path(raw_source).resolve())
            log_progress(f"[dedupe {index}/{total}] {candidate['title']}")
            status, result = ingest_candidate(project_root, candidate)
            persist_manifest(stage_dir, candidate, status=status, result=result)
            if status == "pending-review":
                log_progress(f"[review] {candidate['title']} -> {result}")
            else:
                register_resolved_review(
                    project_root,
                    {
                        "review_id": f"resolved-{candidate['intake_id']}",
                        "intake_id": candidate["intake_id"],
                        "title": candidate["title"],
                        "resolution": status,
                        "canonical_id": result,
                    },
                )
                log_progress(f"[ok] {candidate['title']} -> {result} ({status})")
        except Exception as exc:
            message = clean_text(str(exc) or exc.__class__.__name__)
            if stage_dir and candidate and stage_dir.exists():
                persist_manifest(stage_dir, candidate, status="failed", result=message)
            log_progress(f"[error] {raw_source} -> {message}")
            failures.append(f"{raw_source}: {message}")
    if failures:
        log_progress(f"[summary] completed with {len(failures)} failure(s)")
        for item in failures:
            log_progress(f"[failed] {item}")
        return 1
    return 0


def resolve_review(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    review_item = remove_pending_review(project_root, args.review_id)
    stage_dir = intake_root(project_root) / review_item["intake_id"]
    candidate = load_manifest_candidate(stage_dir)
    if args.decision == "existing":
        if not args.canonical_id:
            raise SystemExit("--canonical-id is required when decision=existing")
        attach_alias(project_root, args.canonical_id, candidate, resolution="confirmed-duplicate")
        resolution = args.canonical_id
    else:
        resolution = finalize_new_candidate(project_root, candidate)
    persist_manifest(stage_dir, candidate, status="resolved", result=resolution)
    register_resolved_review(
        project_root,
        {
            "review_id": review_item["review_id"],
            "intake_id": review_item["intake_id"],
            "title": review_item["candidate_title"],
            "resolution": args.decision,
            "canonical_id": resolution,
        },
    )
    print(f"[ok] resolved {args.review_id} -> {resolution}")
    return 0


def refresh_notes(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    changed = refresh_canonical_notes(
        project_root,
        source_ids=list(args.source_id),
        rewrite_summary=args.rewrite_summary,
    )
    print(f"[ok] refreshed literature notes and summaries ({changed} file updates)")
    return 0


def refresh_claims(args: argparse.Namespace) -> int:
    project_root = find_project_root()
    bootstrap_workspace(project_root)
    changed = refresh_placeholder_claims(
        project_root,
        source_ids=list(args.source_id),
        force=args.force,
    )
    print(f"[ok] refreshed placeholder claims ({changed} file updates)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest PDFs and literature URLs into the research v1.1 library.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    ingest_cmd = subparsers.add_parser("ingest", help="Ingest raw PDFs or URL sources")
    ingest_cmd.add_argument("--source", action="append", default=[], help="Local PDF path or literature URL")
    ingest_cmd.add_argument("--raw-dir", default="raw", help="Fallback PDF buffer directory")
    ingest_cmd.add_argument("--search-result", default="", help="Optional search result YAML")
    ingest_cmd.set_defaults(func=ingest_sources)

    resolve_cmd = subparsers.add_parser("resolve-review", help="Resolve a pending duplicate review")
    resolve_cmd.add_argument("--review-id", required=True)
    resolve_cmd.add_argument("--decision", choices=["existing", "new"], required=True)
    resolve_cmd.add_argument("--canonical-id", default="")
    resolve_cmd.set_defaults(func=resolve_review)

    rebuild_cmd = subparsers.add_parser("rebuild-index", help="Rebuild the literature index and graph from canonical entries")
    rebuild_cmd.set_defaults(func=lambda _args: (rebuild_literature_index(find_project_root()), print("[ok] rebuilt literature index and graph"), 0)[2])

    refresh_notes_cmd = subparsers.add_parser("refresh-notes", help="Refresh note.md and short_summary from canonical metadata")
    refresh_notes_cmd.add_argument("--source-id", action="append", default=[], help="Canonical literature source ID to refresh")
    refresh_notes_cmd.add_argument("--rewrite-summary", action="store_true", help="Regenerate short_summary even if one already exists")
    refresh_notes_cmd.set_defaults(func=refresh_notes)

    refresh_claims_cmd = subparsers.add_parser("refresh-claims", help="Refresh claims.yaml as placeholder claim scaffolds")
    refresh_claims_cmd.add_argument("--source-id", action="append", default=[], help="Canonical literature source ID to refresh")
    refresh_claims_cmd.add_argument("--force", action="store_true", help="Overwrite claims files even if they look manually curated")
    refresh_claims_cmd.set_defaults(func=refresh_claims)
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    project_root = find_project_root()
    require_pdf_backend = args.command == "ingest"
    ensure_research_runtime(project_root, "literature-corpus-builder", require_pdf_backend=require_pdf_backend)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
