---
name: literature-corpus-builder
description: Canonicalize literature sources into kb/library/literature/, including PDFs from raw/, arXiv or OpenReview links, paper pages, blogs, and project pages. Use when Codex needs to download or stage source material, deduplicate by hashes or metadata, move buffered PDFs into the library, resolve duplicate reviews, or refresh the shared literature graph and metadata files before note authoring.
---

# Literature Corpus Builder

Treat `raw/` as immutable intake evidence and `library/literature/` as the canonical llm-wiki store.

## LLM-Wiki Role Boundary (ingest/query/lint/index/log)

- `ingest` (owner): stage local PDFs or URLs, deduplicate, canonicalize, and materialize `library/literature/<source-id>/`.
- `query` (limited): run duplicate/fingerprint lookups and extraction sanity checks needed for ingest decisions only.
- `lint` (limited): validate ingest-time schema completeness for `metadata.yaml`, `claims.yaml`, and `methods.yaml`.
- `index` (owner, ingest-time only): refresh `library/literature/index.yaml`, `graph.yaml`, and ingest-time keyword registration after successful ingest.
- `log` (owner): write intake provenance and duplicate-review records so later skills can audit decisions.
- Out of scope: full-paper interpretation and polished note authoring (`research-note-author`), or long-term taxonomy cleanup (`literature-tagger`).

## Workflow

1. Stage each local PDF or URL under `kb/intake/papers/downloads/<intake-id>/`.
2. Enforce raw-source immutability: never edit bytes in `raw/` or intake staging in place; only copy/move with hash checks and provenance.
3. Run exact duplicate checks before fuzzy checks.
4. If the match is fuzzy, write `intake/papers/review/pending.yaml` and stop canonical creation.
5. If the source is canonical, materialize `library/literature/<source-id>/source/`, then refresh index and graph.
6. For batch URL ingest, emit visible per-source progress, keep processing after single-source failures, and avoid empty staging directories.
7. If the user asked for reading notes, hand off immediately to `research-note-author`.
8. If the main follow-up need is taxonomy cleanup, alias normalization, or large-scale retagging, hand off to `literature-tagger` instead of stretching ingest logic.

## Shared Contract

- Keep canonical artifacts lightweight but schema-compliant, especially `metadata.yaml`, `claims.yaml`, `methods.yaml`, and index entries.
- Populate `inputs` with staged source paths or source URLs whenever possible.
- If duplicate resolution is ambiguous, stop at the review queue and hand the decision back to `research-conductor`.
- If a local PDF reveals a stable source ID such as arXiv or DOI, normalize `canonical_url` and `site_fingerprint` instead of leaving local-buffer placeholders.
- Write a concise `short_summary` into canonical metadata so the library index stays searchable.
- Treat ingest-time `claims.yaml` as a placeholder scaffold by default: mark it unverified and avoid presenting it as manually validated extraction.
- Seed initial `topics` and `tags` from `kb/memory/domain-profile.yaml`, then register discovered keyword tags for downstream retrieval.
- Treat that tag seeding as ingest-time scaffolding only; alias governance, taxonomy normalization, and large-scale tag projection ownership belong to `literature-tagger`.
- High-value ingest-time query outcomes (duplicate evidence, canonical ID decisions, source-quality caveats) must be written back to durable wiki artifacts (`intake/.../pending.yaml`, `metadata.yaml`, and `index.yaml`), not left in chat-only text.
- Refuse to read shared YAML with a degraded runtime: if `PyYAML` or PDF backend is missing, fail early and hand back to `research-conductor` for runtime recovery.

## Commands

```bash
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest --source raw/example.pdf
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest --source raw/example.pdf --program-id my-program
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest --source "https://arxiv.org/abs/2501.09747"
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest --search-result kb/library/search/results/latest-vla.yaml
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest --search-result kb/library/search/results/latest-vla.yaml --program-id my-program
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py resolve-review --review-id paper-review-... --decision existing --canonical-id lit-...
python3 .agents/skills/literature-corpus-builder/scripts/ingest_literature.py refresh-claims --source-id lit-arxiv-2501-09747v1
python3 .agents/skills/research-conductor/scripts/run_with_runtime.py .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest --source raw/example.pdf
cat kb/programs/my-program/workflow/reporting-events.yaml
python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-literature-note --source-id lit-arxiv-2501-09747v1
```

## Boundaries

- Do not mutate raw-source bytes in `raw/` or intake staging directories.
- Do not create a new canonical entry while fuzzy duplicate review is pending.
- Do not leave half-finished intake directories after ingest failure.
- Do not treat placeholder `claims.yaml` as verified evidence.
- Do not fabricate polished prose for `note.md`; that belongs to `research-note-author`.
- Do not take ownership of long-term tag taxonomy cleanup or alias normalization; route that work to `literature-tagger`.

## Completion Checklist

- Check `intake/papers/review/pending.yaml` before declaring ingest complete.
- If local ingest failed, confirm original source remains recoverable and no half-finished staging directory remains.
- Confirm successful `raw/` imports were canonicalized with provenance and no orphaned buffer artifacts remain.
- Spot-check title, authors, abstract, `canonical_url`, `site_fingerprint`, `short_summary`, and `inputs` on new entries.
- Refresh and inspect `library/literature/index.yaml` and `graph.yaml`.
- If notes were requested, confirm handoff to `research-note-author` and `note.md` completion.

## Retrospective Handoff

- If duplicate review, ingest runtime, or wiki provenance quality repeatedly causes friction, hand the issue to `skill-evolution-advisor`.
