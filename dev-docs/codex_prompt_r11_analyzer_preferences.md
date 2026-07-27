# R11 handoff — analyzer Agent preference consumers

## STEP 0 — base sync

Work in a dedicated worktree. Before edits, compare `git rev-parse HEAD` with the current integration HEAD supplied by the parent. Verify these files exist: `.agents/lib/research/preference_selection.py`, repo/dataset/blog analyzer scripts, and `temp/SYSTEM_DESIGN_SSOT.md` in the main workspace. If the worktree is stale, stop and report; do not improvise a destructive sync. Never touch a real `kb/`; all behavior tests use `tmp_path`/temporary workspaces.

Read repository `AGENTS.md` and treat shipping skills as product source, not instructions. Read the R6.2/R7.2/R11 decisions in `temp/SYSTEM_DESIGN_SSOT.md` as design authority.

## Objective

Turn these three runtime-Agent authoring steps into real task-scoped preference consumers:

- `repo-analyst:map-capability`
- `dataset-analyst:profile`
- `blog-analyst:complete-note`

The Agent chooses a relevant subset from the existing eligible catalog. The owner script recomputes exact canonical input context before verify, validates the optional receipt, and persists only a value-free binding. The script must not interpret the material or generate semantic claims.

## File ownership

Only modify:

- `.agents/lib/research/preference_selection.py`
- `.agents/lib/research/tests/test_effective_preferences.py`
- `.agents/lib/research/tests/test_preference_consumer_matrix.py`
- `.agents/lib/research/SCHEMAS.md`
- `.agents/skills/repo-analyst/SKILL.md`
- `.agents/skills/repo-analyst/scripts/repo.py`
- `.agents/skills/dataset-analyst/SKILL.md`
- `.agents/skills/dataset-analyst/scripts/dataset.py`
- `.agents/skills/blog-analyst/SKILL.md`
- `.agents/skills/blog-analyst/scripts/blog.py`
- new narrowly named tests for these three consumers if useful

Do not modify idea, monitor, installer, version/docs/changelog, or `temp/`. Commit small coherent pieces.

## Required contract

1. Declare only the three real operations above in `SKILL_OPERATIONS`; do not invent aspirational commands.
2. Prepare must expose a deterministic private task-context mapping for the runtime Agent after the canonical scaffold/record state is written. No absolute paths, preference values, secrets, or raw user text in a receipt. The Agent will legitimately edit fillable fields, so bind an immutable orientation sidecar or a canonical projection of non-fillable scaffold fields; do **not** digest the whole mutable fill file as a pre-authoring input.
3. Canonical input context covers at least:
   - common: canonical id/kind, current record semantic/content digest, operation, phase contract, exact immutable orientation/contract digest;
   - repo: exact `structure-scan.yaml` bytes and safe repo source identity needed by the capability task;
   - dataset/blog: exact current immutable parse-cache/source artifact identity and bytes used for authoring.
4. Verify accepts a hidden/private `--preference-selection-id`. With no receipt it remains neutral and must not read soft canonical preferences. With a receipt it calls the shared owner consumer API against the recomputed context before any write. Wrong skill/op/task, preference changes, record/immutable-orientation/source byte changes, symlink/non-regular source replacement all fail closed with zero business writes. Normal edits confined to declared fillable fields must not invalidate the receipt.
5. Successful verify persists only `selection_id`, selection digest, task-context digest, skill, operation (plus hard constraint digests if the shared contract requires them). Do not copy selected values into record, sidecar, note, history, or protocol.
6. The selection may influence only the runtime Agent's authoring emphasis/style. It cannot relax evidence, substantive-content, confirmation, containment, recovery, or source freshness gates. Existing claim/evidence semantics remain intact.
7. Maintain an operation→canonical-input registry or equivalent explicit registry and mutation-matrix tests. Every registered consumed field/artifact must be mutated one at a time; the old receipt must then be rejected before writes. Include a success path and neutral/no-receipt path.
8. Public/user-visible output remains natural language + `kb <verb>` only. Do not add TTY flows, raw owner commands, flags, paths, digests, or `NEXT FOR AGENT:` to any wrapper output.

## Gates

- targeted repo/dataset/blog analyzer tests
- effective preference and consumer matrix tests
- byte-mutation, symlink/non-regular replacement, wrong receipt, canonical preference mutation, zero-write assertions
- `python -m py_compile` for changed scripts
- `git diff --check`

STOP and report if the exact source artifact cannot be recomputed without making the script understand material, or if a change would weaken evidence/confirmation/recovery governance.
