---
name: repo-cataloger
description: Canonicalize local repositories and GitHub URLs into doc/research/library/repos/, including staged downloads, duplicate review, entrypoint scanning, and reusable repo summaries. Use when Codex needs to bring a repository into the shared library, snapshot it into the workspace, refresh index metadata, or resolve possible duplicate repos before note authoring or downstream reuse.
---

# Repo Cataloger

Normalize repositories into the shared repo library before using them in ideas or design work.

## Workflow

1. Stage each local path or GitHub URL under `doc/research/intake/repos/downloads/<intake-id>/`.
2. Run duplicate checks against canonical remotes and owner/name fingerprints.
3. If the match is fuzzy, write `intake/repos/review/pending.yaml` and wait for confirmation.
4. If the repo is canonical, move the staged snapshot into `library/repos/<repo-id>/source/` and write summary, entrypoints, and modules.

## Shared Contract

- Preserve the shared YAML top-level fields on repo summaries, entrypoints, modules, and index updates.
- Populate `inputs` with the staged local path or canonical remote that produced the repo entry.
- Stop at the duplicate review queue when the canonical repo identity is uncertain.
- Treat repos under workspace `raw/` as a consumable buffer: move them through intake into the library instead of leaving the raw copy behind.
- Write a concise `short_summary` into canonical repo summaries so the library index stays searchable.
- Do not own final repo note authoring inside this skill. After canonical ingest, route immediately to `research-note-author` to prepare note assets and write `repo-notes.md`.

## Commands

```bash
python3 .agents/skills/repo-cataloger/scripts/catalog_repo.py ingest --repo /path/to/local/repo
python3 .agents/skills/repo-cataloger/scripts/catalog_repo.py ingest --repo https://github.com/example/project
python3 .agents/skills/repo-cataloger/scripts/catalog_repo.py resolve-review --review-id repo-review-... --decision existing --canonical-id repo-...
python3 .agents/skills/research-note-author/scripts/prepare_note_assets.py prepare-repo-note --repo-id repo-example
```

## Boundaries

- Do not treat a raw local path as the permanent fact source after cataloging.
- Do not download datasets or checkpoints unless the user explicitly asks for that.
- Do not let this skill fabricate polished prose for `repo-notes.md`; that belongs to `research-note-author`.
- Do not end the overall task after ingest if the user asked for notes; hand off to `research-note-author` first.

## Completion Checklist

- Check `intake/repos/review/pending.yaml` for fuzzy duplicate decisions before ending the run.
- Confirm local repos staged from workspace `raw/` were consumed and do not remain in `raw/`.
- If the user asked for notes, confirm `research-note-author` ran and that `repo-notes.md` landed in the canonical entry.
- Refresh and inspect `library/repos/index.yaml` so provenance reflects the whole current library, not only the latest import.

## Retrospective Handoff

- If repo intake exposed repeated duplicate ambiguity, thin repo notes, or missing summary tooling, hand the observation to `skill-evolution-advisor` before ending the task.
