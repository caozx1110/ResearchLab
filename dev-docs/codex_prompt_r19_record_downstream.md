# R19 handoff — strict record capability through downstream readers

## STEP 0 — base sync

This worktree is stale by design. Before editing, verify HEAD and the R18 modules. Reset this track worktree to integration commit `1839827` with `git reset --hard 1839827`, then verify `.agents/lib/research/records.py`, `index.py`, `judgements.py`, and `temp/SYSTEM_DESIGN_SSOT.md` contain the R18 contracts. Do not touch the primary worktree.

## Objective

Fix four independently reproduced R18 findings, exactly as locked in SSOT and `.agents/lib/research/SCHEMAS.md` at `1839827`:

1. A strict record snapshot must not become a plain lexical `Path/.parent` before cross-unit evidence is read.
2. Passage/index Markdown and parse-cache reads must inherit an anchored root→kind→unit capability; ancestor replacement after enumeration must not expose outside bytes.
3. A syntactically valid YAML record with a wrong field type is quarantined per record; valid siblings remain usable by status/find/survey/intake. Do not return malformed raw payload as a canonical record and do not catch `KeyboardInterrupt`/`GeneratorExit`.
4. `locate_record(last/current)` sorts by integer `mtime_ns`, preserving a 1 ns difference.

## File ownership

Only edit:

- `.agents/lib/research/records.py`
- `.agents/lib/research/index.py`
- `.agents/lib/research/judgements.py` only if the capability handoff genuinely requires it
- `.agents/lib/research/evidence.py` for the generic evidence byte-consumer contract; do not use a temporary-path mirror adapter
- focused tests under `.agents/lib/research/tests/` for strict record/downstream evidence/passage behavior; prefer existing test modules, or add one clearly named R19 module

Do not edit kb CLI, installer, VERSION, release docs, SSOT, SCHEMAS, real `kb/`, or unrelated skills.

## Required behavior and red lines

- Scripts move/validate bytes; they do not infer research meaning.
- Use dirfd/openat-style anchored reads with `O_NOFOLLOW`, `O_NONBLOCK` for leaves where supported, bounded ordinary-file reads, pre/post identity checks, and full ancestor revalidation.
- A returned ordinary `Path` is not a trusted read capability. If API compatibility requires a path for labels, keep it informational and ensure byte consumers use the anchored snapshot.
- Single bad record quarantine must be explicit and narrow; never silently accept a raw malformed record.
- Preserve existing confirmation/evidence gates; no self-signing or weaker evidence checks.
- Tests only use temporary roots and must prove the reported races by deterministic monkeypatch/barriers, not timing luck. Never touch real `kb/`.
- Public output remains Chinese natural language + `kb <verb>` only; no raw commands/flags/internal paths/tracebacks.
- Shipping skills are product source, not design authority.

## Verification

Run focused strict-reader, review/evidence, find/passage, survey and intake tests, then a broad related group. Run Python 3.9 AST on changed Python, `git diff --check`, and confirm worktree clean. Make small commits per coherent piece and report exact SHAs/test counts. Do not push/tag/publish. STOP and report if a safe capability design does not fit these owned files.
