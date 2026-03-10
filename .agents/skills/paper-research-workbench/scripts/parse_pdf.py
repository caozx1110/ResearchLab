#!/usr/bin/env python3
"""Parse paper PDFs into structured metadata, with incremental deduplication."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from _paper_utils import (
    clean_text,
    clean_title,
    ensure_dir,
    extract_urls,
    file_sha256,
    infer_tags_topics,
    infer_year_from_arxiv_id,
    load_yaml,
    make_identity_key,
    make_paper_id,
    normalize_arxiv_id,
    parse_author_string,
    relative_to_project,
    utc_now_iso,
    write_json_if_changed,
    write_text_if_changed,
    write_yaml,
)


def load_pdf_reader_backend() -> tuple[Any, str]:
    try:
        from PyPDF2 import PdfReader as backend  # type: ignore

        return backend, "PyPDF2"
    except ModuleNotFoundError:
        pass

    try:
        from pypdf import PdfReader as backend  # type: ignore

        return backend, "pypdf"
    except ModuleNotFoundError as exc:
        raise ModuleNotFoundError(
            "No PDF reader backend available. Install PyPDF2 or pypdf to parse new PDFs."
        ) from exc


def project_root_from_script() -> Path:
    # <project>/skills/paper-research-workbench/scripts/parse_pdf.py
    return Path(__file__).resolve().parents[3]


def collect_pdfs(input_path: Path) -> list[Path]:
    if input_path.is_file() and input_path.suffix.lower() == ".pdf":
        return [input_path]
    if input_path.is_dir():
        return sorted(input_path.rglob("*.pdf"))
    return []


def normalize_pdf_metadata(reader: Any) -> dict[str, str]:
    raw = reader.metadata or {}
    normalized: dict[str, str] = {}
    for key, value in raw.items():
        k = str(key).lstrip("/")
        v = clean_text(str(value))
        if v:
            normalized[k] = v
    return normalized


def extract_pages(reader: Any, max_pages: int) -> list[str]:
    page_count = len(reader.pages)
    limit = page_count if max_pages <= 0 else min(page_count, max_pages)
    pages: list[str] = []
    for idx in range(limit):
        try:
            text = reader.pages[idx].extract_text() or ""
        except Exception:
            text = ""
        pages.append(clean_text(text))
    return pages


def guess_title(metadata: dict[str, str], first_page: str, file_stem: str) -> str:
    embedded = clean_title(metadata.get("Title", ""))
    if is_reasonable_title(embedded):
        return embedded

    lines = [clean_title(line) for line in first_page.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return clean_title(file_stem.replace("_", " ").replace("-", " "))

    cutoff = len(lines)
    for idx, line in enumerate(lines):
        if line.lower().startswith("abstract"):
            cutoff = idx
            break
    cutoff = min(max(cutoff, 2), 14)
    window = lines[:cutoff]

    scored: dict[str, int] = {}
    for idx, line in enumerate(window):
        if looks_like_title_candidate(line):
            scored[line] = max(scored.get(line, -10_000), title_score(line, idx, False))
        if idx + 1 < len(window):
            next_line = window[idx + 1]
            if looks_like_title_candidate(line) and looks_like_title_candidate(next_line):
                combined = clean_title(f"{line} {next_line}")
                if is_reasonable_title(combined):
                    scored[combined] = max(
                        scored.get(combined, -10_000),
                        title_score(combined, idx, True),
                    )

    if scored:
        best = max(scored, key=scored.get)
        if is_reasonable_title(best):
            return best
    return clean_title(file_stem.replace("_", " ").replace("-", " "))


def title_score(text: str, index: int, combined: bool) -> int:
    low = text.lower()
    if len(text) < 8:
        return -200
    if len(text) > 220:
        return -150
    if low.startswith("http://") or low.startswith("https://"):
        return -300
    if "arxiv" in low:
        return -200
    if "abstract" == low:
        return -200
    score = 120 - (index * 18)
    score += min(len(text), 90)
    if combined:
        score += 25
    if ":" in text:
        score += 30
    if "-" in text:
        score += 8
    if any(ch.islower() for ch in text) and any(ch.isupper() for ch in text):
        score += 40
    if text.count(" ") >= 3:
        score += 15
    if re.search(r"\d{4}\.\d{4,5}", text):
        score -= 70
    if text.count("/") > 2:
        score -= 80
    if text.count(",") >= 2:
        score -= 120
    if re.search(r"[A-Za-z]\d|\d[A-Za-z]", text):
        score -= 100
    if len(text.split()) > 16:
        score -= 80
    if any(
        term in low
        for term in ("physical intelligence", "stanford", "berkeley", "university")
    ):
        score -= 90
    return score


def is_reasonable_title(text: str) -> bool:
    if not text:
        return False
    if len(text) < 8 or len(text) > 240:
        return False
    if len(text.split()) > 20:
        return False
    low = text.lower()
    if any(token in low for token in ("abstract", "introduction", "arxiv", "copyright")):
        return False
    return sum(ch.isalpha() for ch in text) >= 6


def looks_like_title_candidate(text: str) -> bool:
    low = text.lower()
    if low.startswith("http://") or low.startswith("https://"):
        return False
    if low.startswith("fig.") or "<loc" in low:
        return False
    if text.count(",") >= 2:
        return False
    if re.search(r"[A-Za-z]\d|\d[A-Za-z]", text):
        return False
    if any(term in low for term in ("stanford", "berkeley", "university", "institute")):
        return False
    if "physical intelligence" == low:
        return False
    if len(text) > 180:
        return False
    return sum(ch.isalpha() for ch in text) >= 6


def looks_like_affiliation(name: str) -> bool:
    low = name.lower()
    if low in {"physical intelligence"}:
        return True
    if any(
        token in low
        for token in (
            "university",
            "institute",
            "berkeley",
            "stanford",
            "intelligence",
            "laboratory",
        )
    ):
        return True
    return bool(re.search(r"\d", name))


def guess_authors(metadata: dict[str, str], first_page: str) -> list[str]:
    embedded = parse_author_string(metadata.get("Author", ""))
    if embedded:
        filtered = [name for name in embedded if not looks_like_affiliation(name)]
        if filtered and len(filtered) >= max(2, len(embedded) // 2):
            return filtered[:40]
        return embedded[:40]

    lines = [clean_text(line) for line in first_page.splitlines()]
    lines = [line for line in lines if line]
    candidates: list[str] = []
    for line in lines[1:18]:
        low = line.lower()
        if "abstract" in low:
            break
        if low.startswith("http://") or low.startswith("https://"):
            continue
        if len(line) > 500:
            continue
        if "," in line and re.search(r"[a-zA-Z]", line):
            candidates.append(line)

    parsed = parse_author_string("; ".join(candidates).replace(",", ";"))
    filtered = [name for name in parsed if not looks_like_affiliation(name)]
    return (filtered or parsed)[:40]


def guess_arxiv_id(metadata: dict[str, str], first_page: str, file_name: str) -> str:
    candidates = [
        metadata.get("arXivID", ""),
        metadata.get("DOI", ""),
        file_name,
        first_page[:4000],
    ]
    for candidate in candidates:
        arxiv_id = normalize_arxiv_id(candidate)
        if arxiv_id:
            return arxiv_id
    return ""


def guess_doi(metadata: dict[str, str], first_page: str) -> str:
    embedded = metadata.get("DOI", "")
    if embedded:
        return embedded
    doi_labeled = re.search(
        r"(?i)\bdoi\b\s*[:=]\s*(10\.\d{4,9}/[-._;()/:A-Za-z0-9]+)",
        first_page,
    )
    if doi_labeled:
        return doi_labeled.group(1)
    arxiv_doi = re.search(r"(10\.48550/arXiv\.\d{4}\.\d{4,5}(?:v\d+)?)", first_page)
    if arxiv_doi:
        return arxiv_doi.group(1)
    return ""


def guess_year(metadata: dict[str, str], arxiv_id: str, file_name: str) -> int | None:
    arxiv_year = infer_year_from_arxiv_id(arxiv_id)
    if arxiv_year:
        return arxiv_year

    for key in ("CreationDate", "ModDate"):
        value = metadata.get(key, "")
        date_match = re.search(r"D:(\d{4})", value)
        if date_match:
            return int(date_match.group(1))

    file_match = re.match(r"^(\d{2})(\d{2})\.\d{4,5}(?:v\d+)?\.pdf$", file_name)
    if file_match:
        return 2000 + int(file_match.group(1))
    return None


def extract_abstract(full_text: str) -> str:
    text = full_text.replace("-\n", "")
    abstract_match = re.search(r"(?is)\babstract\b\s*[-:]*\s*", text)
    if not abstract_match:
        return ""
    tail = text[abstract_match.end() :]
    lines = [clean_text(line) for line in tail.splitlines()]
    collected: list[str] = []
    for line in lines:
        if not line:
            if collected and len(" ".join(collected)) > 900:
                break
            continue
        low = line.lower()
        if "correspond" in low or "arxiv:" in low or "@" in line:
            continue
        normalized = re.sub(r"[^a-z0-9]", "", low)
        if normalized.startswith(
            ("1introduction", "iintroduction", "introduction", "keywords", "contents")
        ):
            break
        if low.startswith("fig."):
            continue
        collected.append(line)
        if len(" ".join(collected)) >= 6000:
            break

    snippet = clean_text(" ".join(collected))
    snippet = re.sub(r"^[\-\u2013\u2014:\s]+", "", snippet)
    if len(snippet) < 80:
        return ""
    return snippet


def extract_sections(full_text: str) -> list[str]:
    heading_patterns = [
        "abstract",
        "introduction",
        "related work",
        "background",
        "method",
        "approach",
        "experiments",
        "results",
        "discussion",
        "limitations",
        "conclusion",
    ]
    found: list[str] = []
    seen: set[str] = set()
    for heading in heading_patterns:
        pattern = rf"(?im)^\s*(?:\d+[\.\)]\s*)?{re.escape(heading)}\b"
        if re.search(pattern, full_text):
            normalized = heading.title()
            if normalized not in seen:
                seen.add(normalized)
                found.append(normalized)
    return found


def base_registry() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": utc_now_iso(),
        "paper_index": {},
        "source_index": {},
    }


def load_registry(path: Path) -> dict[str, Any]:
    payload = load_yaml(path)
    if not isinstance(payload, dict):
        return base_registry()
    payload.setdefault("schema_version", 1)
    payload.setdefault("generated_at", utc_now_iso())
    payload.setdefault("paper_index", {})
    payload.setdefault("source_index", {})
    return payload


def load_existing_records(output_root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for metadata_path in sorted(output_root.glob("*/metadata.yaml")):
        payload = load_yaml(metadata_path)
        if isinstance(payload, dict):
            records.append(payload)
    return records


def build_existing_indexes(
    records: list[dict[str, Any]],
    registry: dict[str, Any],
) -> dict[str, dict[str, str]]:
    by_arxiv_id: dict[str, str] = {}
    by_identity_key: dict[str, str] = {}
    by_source_hash: dict[str, str] = {}

    for record in records:
        paper_id = str(record.get("paper_id") or "")
        if not paper_id:
            continue
        arxiv_id = str(record.get("arxiv_id") or "")
        if arxiv_id:
            by_arxiv_id[arxiv_id] = paper_id
        identity_key = str((record.get("ingest") or {}).get("identity_key") or "")
        if not identity_key:
            identity_key = make_identity_key(
                title=str(record.get("title") or ""),
                authors=list(record.get("authors") or []),
                year=record.get("year"),
                arxiv_id=arxiv_id,
            )
        by_identity_key[identity_key] = paper_id

        source = record.get("source") or {}
        file_sha = str(source.get("file_sha256") or "")
        if file_sha:
            by_source_hash[file_sha] = paper_id

    source_index = registry.get("source_index") or {}
    if isinstance(source_index, dict):
        for entry in source_index.values():
            if not isinstance(entry, dict):
                continue
            file_sha = str(entry.get("file_sha256") or "")
            paper_id = str(entry.get("canonical_paper_id") or "")
            if file_sha and paper_id:
                by_source_hash[file_sha] = paper_id

    return {
        "by_arxiv_id": by_arxiv_id,
        "by_identity_key": by_identity_key,
        "by_source_hash": by_source_hash,
    }


def merge_with_existing(
    generated: dict[str, Any],
    existing_path: Path,
    *,
    force: bool,
) -> dict[str, Any]:
    if force or not existing_path.exists():
        return generated
    existing = load_yaml(existing_path)
    if not isinstance(existing, dict):
        return generated

    merged = dict(generated)
    existing_tags = existing.get("tags", [])
    existing_topics = existing.get("topics", [])
    if isinstance(existing_tags, list):
        merged["tags"] = sorted(set(generated["tags"]) | set(existing_tags))
    if isinstance(existing_topics, list):
        merged["topics"] = sorted(set(generated["topics"]) | set(existing_topics))
    for passthrough in ("reading_status", "priority", "owner", "manual_notes"):
        if passthrough in existing:
            merged[passthrough] = existing[passthrough]
    return merged


def write_artifacts(
    *,
    paper_dir: Path,
    page_texts: list[str],
    sections: list[str],
    title: str,
    source_pdf: str,
) -> None:
    artifacts_dir = paper_dir / "_artifacts"
    ensure_dir(artifacts_dir)

    text_lines = [
        f"# Extracted Text: {title}",
        "",
        f"- Source PDF: {source_pdf}",
        f"- Extracted at: {utc_now_iso()}",
        f"- Extracted pages: {len(page_texts)}",
        "",
    ]
    for idx, page in enumerate(page_texts, start=1):
        text_lines.extend([f"## Page {idx}", "", page or "[empty page text]", ""])
    write_text_if_changed(artifacts_dir / "text.md", "\n".join(text_lines))

    sections_payload = {
        "generated_at": utc_now_iso(),
        "section_count": len(sections),
        "sections": sections,
    }
    write_json_if_changed(artifacts_dir / "sections.json", sections_payload)


def update_registry_entry(
    *,
    registry: dict[str, Any],
    source_pdf: str,
    file_sha: str,
    canonical_paper_id: str,
    status: str,
    reason: str,
    metadata: dict[str, Any] | None = None,
) -> None:
    registry["generated_at"] = utc_now_iso()
    source_index = registry.setdefault("source_index", {})
    source_index[source_pdf] = {
        "canonical_paper_id": canonical_paper_id,
        "file_sha256": file_sha,
        "last_status": status,
        "reason": reason,
        "last_seen_at": utc_now_iso(),
    }
    if metadata is not None:
        update_paper_snapshot(registry, metadata)


def update_paper_snapshot(registry: dict[str, Any], metadata: dict[str, Any]) -> None:
    canonical_paper_id = str(metadata.get("paper_id") or "")
    if not canonical_paper_id:
        return
    source = metadata.get("source") or {}
    paper_index = registry.setdefault("paper_index", {})
    paper_index[canonical_paper_id] = {
        "paper_id": canonical_paper_id,
        "identity_key": (metadata.get("ingest") or {}).get("identity_key"),
        "arxiv_id": metadata.get("arxiv_id"),
        "title": metadata.get("title"),
        "year": metadata.get("year"),
        "primary_source_pdf": source.get("pdf"),
        "source_aliases": source.get("aliases") or [],
        "source_hashes": source.get("source_hashes") or [],
        "updated_at": utc_now_iso(),
    }


def append_alias_to_metadata(
    metadata_path: Path,
    *,
    alias_pdf: str,
    alias_sha: str,
) -> None:
    payload = load_yaml(metadata_path)
    if not isinstance(payload, dict):
        return
    source = payload.setdefault("source", {})
    aliases = source.setdefault("aliases", [])
    if alias_pdf not in aliases:
        aliases.append(alias_pdf)
    source_hashes = source.setdefault("source_hashes", [])
    if alias_sha not in source_hashes:
        source_hashes.append(alias_sha)
    source["aliases"] = sorted(aliases)
    source["source_hashes"] = sorted(source_hashes)
    write_yaml(metadata_path, payload)


def parse_and_generate(
    *,
    pdf_path: Path,
    project_root: Path,
    max_pages: int,
) -> tuple[dict[str, Any], list[str], list[str]]:
    pdf_reader_cls, parser_name = load_pdf_reader_backend()
    reader = pdf_reader_cls(str(pdf_path))
    metadata = normalize_pdf_metadata(reader)
    page_texts = extract_pages(reader, max_pages=max_pages)
    first_page = page_texts[0] if page_texts else ""
    full_text = "\n\n".join(page_texts)

    title = guess_title(metadata, first_page, pdf_path.stem)
    authors = guess_authors(metadata, first_page)
    arxiv_id = guess_arxiv_id(metadata, first_page, pdf_path.name)
    doi = guess_doi(metadata, first_page)
    year = guess_year(metadata, arxiv_id, pdf_path.name)
    abstract = extract_abstract(full_text)
    tags, topics = infer_tags_topics(title, abstract)
    urls = extract_urls(full_text[:6000])
    sections = extract_sections(full_text)
    source_pdf = relative_to_project(pdf_path, project_root)
    source_sha = file_sha256(pdf_path)
    identity_key = make_identity_key(
        title=title,
        authors=authors,
        year=year,
        arxiv_id=arxiv_id,
    )

    paper_id = (
        f"arxiv-{arxiv_id.replace('.', '-').replace('v', '-v')}"
        if arxiv_id
        else make_paper_id(
            title=title,
            authors=authors,
            year=year,
            fallback_stem=pdf_path.stem,
        )
    )

    generated = {
        "schema_version": 2,
        "paper_id": paper_id,
        "title": title,
        "authors": authors,
        "year": year,
        "arxiv_id": arxiv_id or None,
        "doi": doi or None,
        "abstract": abstract or None,
        "tags": tags,
        "topics": topics,
        "source": {
            "pdf": source_pdf,
            "file_name": pdf_path.name,
            "file_sha256": source_sha,
            "pdf_pages": len(reader.pages),
            "parsed_pages": len(page_texts),
            "parsed_at": utc_now_iso(),
            "parser": parser_name,
            "aliases": [],
            "source_hashes": [source_sha],
        },
        "ingest": {
            "identity_key": identity_key,
            "last_status": "parsed",
            "dedupe_reason": None,
            "last_seen_at": utc_now_iso(),
        },
        "urls": urls,
        "signals": {
            "has_embedded_metadata": bool(metadata),
            "text_characters": len(full_text),
            "section_count": len(sections),
        },
        "embedded_metadata": {
            key: metadata.get(key)
            for key in ("Title", "Author", "DOI", "arXivID", "CreationDate", "ModDate")
            if metadata.get(key)
        },
    }
    return generated, page_texts, sections


def process_pdf(
    *,
    pdf_path: Path,
    output_root: Path,
    registry_path: Path,
    project_root: Path,
    max_pages: int,
    force: bool,
    indexes: dict[str, dict[str, str]],
    registry: dict[str, Any],
) -> str:
    source_pdf = relative_to_project(pdf_path, project_root)
    source_sha = file_sha256(pdf_path)
    metadata_records = registry.get("source_index") or {}
    prior_source = metadata_records.get(source_pdf) if isinstance(metadata_records, dict) else None
    if (
        not force
        and isinstance(prior_source, dict)
        and prior_source.get("file_sha256") == source_sha
        and prior_source.get("canonical_paper_id")
    ):
        canonical_paper_id = str(prior_source["canonical_paper_id"])
        canonical_payload = load_yaml(output_root / canonical_paper_id / "metadata.yaml")
        update_registry_entry(
            registry=registry,
            source_pdf=source_pdf,
            file_sha=source_sha,
            canonical_paper_id=canonical_paper_id,
            status="unchanged",
            reason="same-source-same-hash",
            metadata=canonical_payload if isinstance(canonical_payload, dict) else None,
        )
        write_yaml(registry_path, registry)
        return f"[SKIP] {pdf_path.name} -> {canonical_paper_id} (unchanged)"

    generated, page_texts, sections = parse_and_generate(
        pdf_path=pdf_path,
        project_root=project_root,
        max_pages=max_pages,
    )
    paper_id = str(generated["paper_id"])
    arxiv_id = str(generated.get("arxiv_id") or "")
    identity_key = str((generated.get("ingest") or {}).get("identity_key") or "")

    canonical_paper_id = ""
    reason = ""
    if source_sha in indexes["by_source_hash"]:
        canonical_paper_id = indexes["by_source_hash"][source_sha]
        reason = "matching-source-hash"
    elif arxiv_id and arxiv_id in indexes["by_arxiv_id"]:
        canonical_paper_id = indexes["by_arxiv_id"][arxiv_id]
        reason = "matching-arxiv-id"
    elif identity_key and identity_key in indexes["by_identity_key"]:
        canonical_paper_id = indexes["by_identity_key"][identity_key]
        reason = "matching-identity-key"

    if canonical_paper_id:
        canonical_metadata_path = output_root / canonical_paper_id / "metadata.yaml"
        canonical_payload = load_yaml(canonical_metadata_path)
        canonical_source_pdf = ""
        if isinstance(canonical_payload, dict):
            canonical_source_pdf = str((canonical_payload.get("source") or {}).get("pdf") or "")
        if canonical_source_pdf and canonical_source_pdf != source_pdf:
            append_alias_to_metadata(
                canonical_metadata_path,
                alias_pdf=source_pdf,
                alias_sha=source_sha,
            )
            canonical_payload = load_yaml(canonical_metadata_path)
            update_registry_entry(
                registry=registry,
                source_pdf=source_pdf,
                file_sha=source_sha,
                canonical_paper_id=canonical_paper_id,
                status="duplicate",
                reason=reason,
                metadata=canonical_payload if isinstance(canonical_payload, dict) else None,
            )
            write_yaml(registry_path, registry)
            return f"[SKIP] {pdf_path.name} -> {canonical_paper_id} ({reason})"

    paper_dir = output_root / paper_id
    ensure_dir(paper_dir)
    metadata_path = paper_dir / "metadata.yaml"
    merged = merge_with_existing(generated, metadata_path, force=force)
    source = merged.setdefault("source", {})
    aliases = set(source.get("aliases") or [])
    aliases.discard(source_pdf)
    source["aliases"] = sorted(aliases)
    hashes = set(source.get("source_hashes") or [])
    hashes.add(source_sha)
    source["source_hashes"] = sorted(hashes)

    ingest = merged.setdefault("ingest", {})
    ingest["identity_key"] = identity_key
    ingest["last_status"] = "refreshed" if metadata_path.exists() else "parsed"
    ingest["dedupe_reason"] = None
    ingest["last_seen_at"] = utc_now_iso()
    write_yaml(metadata_path, merged)

    write_artifacts(
        paper_dir=paper_dir,
        page_texts=page_texts,
        sections=sections,
        title=str(merged.get("title") or ""),
        source_pdf=source_pdf,
    )
    update_registry_entry(
        registry=registry,
        source_pdf=source_pdf,
        file_sha=source_sha,
        canonical_paper_id=paper_id,
        status=str(ingest["last_status"]),
        reason="canonical",
        metadata=merged,
    )
    indexes["by_source_hash"][source_sha] = paper_id
    if arxiv_id:
        indexes["by_arxiv_id"][arxiv_id] = paper_id
    if identity_key:
        indexes["by_identity_key"][identity_key] = paper_id
    write_yaml(registry_path, registry)
    return f"[OK] {pdf_path.name} -> {paper_id}"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Parse one PDF or a directory of PDFs into paper metadata.",
    )
    parser.add_argument(
        "--input",
        default="raw",
        help="Input PDF path or directory (default: raw)",
    )
    parser.add_argument(
        "--output-root",
        default="doc/papers/papers",
        help="Output paper directory root (default: doc/papers/papers)",
    )
    parser.add_argument(
        "--registry-path",
        default="doc/papers/index/registry.yaml",
        help="Registry path used for deduplication and incremental refresh",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=16,
        help="Maximum number of pages to extract text from each PDF (default: 16)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reparse even if the source file has the same hash as the last run",
    )
    args = parser.parse_args()

    project_root = project_root_from_script()
    input_path = (project_root / args.input).resolve()
    output_root = (project_root / args.output_root).resolve()
    registry_path = (project_root / args.registry_path).resolve()
    ensure_dir(output_root)
    ensure_dir(registry_path.parent)

    pdf_files = collect_pdfs(input_path)
    if not pdf_files:
        raise SystemExit(f"No PDF files found under: {input_path}")

    registry = load_registry(registry_path)
    records = load_existing_records(output_root)
    for record in records:
        update_paper_snapshot(registry, record)
    indexes = build_existing_indexes(records, registry)

    for pdf_path in pdf_files:
        try:
            print(
                process_pdf(
                    pdf_path=pdf_path,
                    output_root=output_root,
                    registry_path=registry_path,
                    project_root=project_root,
                    max_pages=args.max_pages,
                    force=args.force,
                    indexes=indexes,
                    registry=registry,
                )
            )
        except Exception as exc:
            print(f"[ERROR] Failed to parse {pdf_path}: {exc}")


if __name__ == "__main__":
    main()
