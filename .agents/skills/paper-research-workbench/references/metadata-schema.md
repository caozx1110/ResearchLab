# Metadata Schema

`metadata.yaml` must remain compact and factual.

## Required Keys

- `schema_version`: integer schema version.
- `paper_id`: stable paper identifier used as folder name.
- `title`: normalized title.
- `authors`: list of author names.
- `year`: publication year if known.
- `tags`: fine-grained labels.
- `topics`: higher-level buckets.
- `source.pdf`: original PDF path.
- `source.file_sha256`: source file fingerprint.
- `source.parsed_at`: parse timestamp.
- `ingest.identity_key`: stable dedupe key.
- `ingest.last_status`: last ingest status.

## Recommended Keys

- `arxiv_id`: arXiv id if detected.
- `doi`: DOI if detected.
- `abstract`: extracted abstract text.
- `urls`: related URLs from first pages.
- `signals`: parser quality and extraction signals.
- `embedded_metadata`: selected metadata fields copied from PDF.
- `source.aliases`: duplicate source paths that map to the same canonical paper.
- `source.source_hashes`: all observed file hashes for this canonical paper.

## Rules

- Keep observed values in metadata. Do not add speculative claims.
- Keep tag/topic casing stable (lowercase kebab-case).
- Do not store large text blocks beyond the abstract.
- Store full extracted text under `_artifacts/text.md`, not in metadata.
