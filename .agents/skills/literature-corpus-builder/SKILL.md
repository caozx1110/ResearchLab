---
name: literature-corpus-builder
description: Canonicalize literature sources into doc/research/library/literature/, including PDFs from raw/, arXiv or OpenReview links, paper pages, blogs, and project pages. Use when Codex needs to download or stage source material, deduplicate by hashes or metadata, move buffered PDFs into the library, resolve duplicate reviews, or refresh the shared literature graph and metadata files.
---

# Literature Corpus Builder

Treat `raw/` as a buffer, not as the library.

## Workflow

1. Stage each local PDF or URL under `doc/research/intake/papers/downloads/<intake-id>/`.
2. Run exact duplicate checks before fuzzy checks.
3. If the match is fuzzy, write to `intake/papers/review/pending.yaml` and stop.
4. If the source is canonical, move it into `library/literature/<source-id>/source/` and refresh the index and graph.
5. For batch URL ingest, emit visible per-source progress and keep going through the batch even if one source fails; do not leave empty staging directories behind.

## Shared Contract

- Keep canonical artifacts lightweight but schema-compliant, especially `metadata.yaml`, `claims.yaml`, `methods.yaml`, and index entries.
- Populate `inputs` with the staged source path or source URL whenever possible.
- If duplicate resolution is ambiguous, stop at the review queue and hand the decision back to `research-conductor`.
- If a local PDF reveals a stable source ID such as arXiv or DOI, normalize `canonical_url` and `site_fingerprint` instead of leaving them as local-buffer placeholders.
- Write a concise `short_summary` into canonical metadata and generate `note.md` from the note template so agents can triage papers without reopening the full source.
- Treat ingest-time `claims.yaml` as a placeholder scaffold by default: mark it as unverified, note that it came from an abstract snippet, and do not present it as manually validated paper claims.
- Seed initial `topics` and `tags` during ingest using `doc/research/memory/domain-profile.yaml`, then auto-discover a small set of salient keyword tags from the title and abstract so new themes can start showing up in the shared tag list immediately.
- After a new canonical paper lands, refresh `tag-taxonomy.yaml` and `tags.yaml` just enough to register newly discovered keyword tags; leave heavier normalization and cleanup to `literature-tagger`.
- Refuse to read shared YAML with a degraded runtime: if `PyYAML` or the PDF backend is missing, fail early and hand back to `research-conductor` to use a remembered runtime.

## Commands

```bash
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest --source raw/example.pdf
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest --source "https://arxiv.org/abs/2501.09747"
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest --search-result doc/research/library/search/results/latest-vla.yaml
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py resolve-review --review-id paper-review-... --decision existing --canonical-id lit-...
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py refresh-notes --source-id lit-arxiv-2501-09747v1
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py refresh-claims --source-id lit-arxiv-2501-09747v1
```

## Boundaries

- Do not create a new canonical entry when a fuzzy duplicate review is pending.
- Do not leave ingested PDFs in `raw/`.
- Do not consume a `raw/` PDF until parsing and manifest creation succeed; on failure, clean the staging directory and leave the original source in place.
- Keep `metadata.yaml`, `claims.yaml`, `methods.yaml`, and `note.md` lightweight but present for every canonical source.
- Do not treat placeholder `claims.yaml` output as verified evidence extraction; promote claims only after manual reading or a dedicated claim pass.
- Do not treat this skill as the long-term owner of literature tag curation.
- Do not leave `note.md` as a raw abstract dump when a short summary and note scaffold can be generated.

## Completion Checklist

- Check `intake/papers/review/pending.yaml` for fuzzy duplicates before declaring the run complete.
- If the run failed on a local PDF, confirm the original file is still present in `raw/` and that no half-finished intake directory was left behind.
- If a batch URL ingest reported failures, confirm each failed source produced a clear error line and that the batch still advanced to later candidates.
- Confirm PDFs sourced from workspace `raw/` were consumed into intake/library and are no longer left in `raw/`.
- Spot-check title, authors, abstract, `canonical_url`, `site_fingerprint`, and `short_summary` on newly imported entries.
- Spot-check `claims.yaml` status and guidance so placeholder claims are clearly marked and not easy to mistake for verified extraction.
- Open `note.md` on at least one imported paper and confirm the template, quick summary, and retrieval cues are usable.
- Refresh and inspect `library/literature/index.yaml` and `graph.yaml` so batch-level provenance is present.
- If downstream work depends on curated tags, hand off to `literature-tagger` and refresh `library/literature/tags.yaml` there.
