---
name: repo-cataloger
description: Canonicalize local repositories and GitHub URLs into doc/research/library/repos/, including staged downloads, duplicate review, entrypoint scanning, and reusable repo summaries. Use when Codex needs to bring a repository into the shared library, snapshot it into the workspace, refresh index metadata, or resolve possible duplicate repos before note authoring or downstream reuse.
---

# Repo Cataloger

Normalize repositories into the shared repo library before idea, design, or implementation reuse.

## LLM-Wiki Role Boundary (ingest/query/lint/index/log)

- `ingest` (owner): stage local/GitHub repos and canonicalize into `library/repos/<repo-id>/`.
- `query` (limited): perform duplicate/fingerprint checks and entrypoint discovery required for ingest.
- `lint` (limited): validate repo summary schema and required metadata fields.
- `index` (owner): refresh `library/repos/index.yaml` and related projections.
- `log` (owner): persist intake provenance and duplicate-review outcomes.
- Out of scope: polished repo note prose (`research-note-author`) and model/dataset download expansion unless requested.

## Workflow

1. Stage each local path or GitHub URL under `doc/research/intake/repos/downloads/<intake-id>/`.
2. Treat intake snapshots as immutable evidence during ingest: no in-place rewrite of staged source trees.
3. Run duplicate checks against canonical remotes and owner/name fingerprints.
4. If the match is fuzzy, write `intake/repos/review/pending.yaml` and wait for confirmation.
5. If canonical, materialize `library/repos/<repo-id>/source/`, `summary.yaml`, and entrypoint/module metadata.
6. If notes are requested, route immediately to `research-note-author`.

## Shared Contract

- Preserve shared YAML top-level fields on summaries, entrypoints, modules, and index updates.
- Populate `inputs` with the staged local path or canonical remote used for cataloging.
- Stop at duplicate review queue when canonical repo identity is uncertain.
- Write concise `short_summary` into `summary.yaml` so library search and weekly reports stay efficient.
- High-value query outcomes during cataloging (duplicate rationale, key entrypoints, risk flags) must be written back to wiki artifacts (`summary.yaml`, review queue, index), not kept only in chat.

## Commands

```bash
python3 .agents/skills/repo-cataloger/scripts/catalog_repo.py ingest --repo /path/to/local/repo
python3 .agents/skills/repo-cataloger/scripts/catalog_repo.py ingest --repo /path/to/local/repo --program-id my-program
python3 .agents/skills/repo-cataloger/scripts/catalog_repo.py ingest --repo https://github.com/example/project
python3 .agents/skills/repo-cataloger/scripts/catalog_repo.py ingest --repo https://github.com/example/project --program-id my-program
python3 .agents/skills/repo-cataloger/scripts/catalog_repo.py resolve-review --review-id repo-review-... --decision existing --canonical-id repo-... --program-id my-program
python3 .agents/skills/repo-cataloger/scripts/catalog_repo.py refresh-notes --repo-id repo-example --program-id my-program
python3 .agents/skills/research-conductor/scripts/run_with_runtime.py .agents/skills/repo-cataloger/scripts/catalog_repo.py ingest --repo https://github.com/example/project
cat doc/research/programs/my-program/workflow/reporting-events.yaml
python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-repo-note --repo-id repo-example
```

## Boundaries

- Do not treat raw local paths as permanent fact sources after cataloging.
- Do not silently download datasets or checkpoints unless explicitly requested.
- Do not fabricate polished prose for `repo-notes.md`; that belongs to `research-note-author`.

## Completion Checklist

- Check `intake/repos/review/pending.yaml` for unresolved fuzzy duplicates.
- Confirm staged raw repo artifacts were consumed into canonical library without orphaned intake leftovers.
- If notes were requested, confirm `repo-notes.md` handoff completion.
- Refresh and inspect `library/repos/index.yaml`.

## Retrospective Handoff

- If duplicate ambiguity, summary quality, or repo provenance repeatedly causes friction, hand the observation to `skill-evolution-advisor`.
