# R17 handoff — literature selection owner adapter

## STEP 0 — base sync

Work in an isolated worktree. Before editing, compare your HEAD with the integration branch HEAD supplied by the parent. Confirm that the literature-search and source-intake files named below exist at that base. If the worktree is stale, stop and report it; do not silently implement against an old tree. Never touch a real user `kb/`; all behavior tests use `tmp_path` or another fresh temporary project.

## Objective

Close the cold-acceptance P3 leak in the default flow from a user-approved `literature-search` candidate to the canonical `source-intake` owner. The runtime Agent must have one formal private adapter that:

- accepts an exact, bounded current-user selection payload;
- binds the literature stage bytes/current candidate identity and the user's selected candidate(s) before invoking the owner;
- delegates canonical materialization to `source-intake` without duplicating its ownership or research judgement;
- captures every owner stdout/stderr line privately, including root diagnostics, `[auto]`, paths, raw flags and `NEXT FOR AGENT:`;
- on success emits only a short natural-language result and, when useful, a `kb <verb>` next step; on failure emits no false success and no untrusted/raw child output to the user;
- is fully headless and does not use a TTY.

The design is already locked in `temp/SYSTEM_DESIGN_SSOT.md` R17 owner-adapter and `.agents/lib/research/SCHEMAS.md`. Treat those as requirements, not suggestions.

## File ownership

You may edit only:

- `.agents/skills/literature-search/scripts/search.py`
- `.agents/skills/literature-search/SKILL.md`
- `.agents/skills/literature-search/references/stage-contract.md` if the private payload contract needs documentation
- `.agents/skills/source-intake/scripts/intake.py` only if a minimal private machine entrypoint/result contract is necessary; do not change canonical intake semantics
- `.agents/lib/research/tests/test_literature_search.py`
- one new narrowly named test file under `.agents/lib/research/tests/` only if separation is materially clearer

Do not edit SSOT, SCHEMAS, BACKLOG, version, release docs, dispatcher, journal, updater, installer, other skills or fixtures owned by parallel tracks.

## Required behavior

1. Prefer a structured, bounded private selection payload over assembling free-form shell commands. Reject symlink/non-regular/oversize/malformed/unknown-field payloads before mutation. Do not pass arbitrary user text through a shell.
2. The payload must identify one existing `literature-search` stage and one or more exact candidate IDs, carry current user-message authorization, and reject empty/fabricated authorization source. Preserve `source-intake`'s existing authorization and candidate-binding gates.
3. Read/bind the stage and candidate before delegation, then verify the owner result corresponds to that exact selection. A concurrent stage/candidate mutation must fail closed. Reuse existing canonical digest helpers when possible; do not invent relevance or selection judgement.
4. Invoke the owner with argv/no shell and captured stdout/stderr, or expose a value-returning private owner function. The adapter's public stdout/stderr must never replay child output, internal paths, raw commands/flags, `${...}`, ANSI/bidi control text, or `NEXT FOR AGENT:`.
5. Multiple selected candidates may be processed sequentially. Report exact success/failure counts. If one fails after prior successes, do not claim all succeeded; leave already committed canonical owner transactions truthful and make retry safe/idempotent.
6. The final stage candidate status/record ID remains owned by `source-intake`. The adapter must not write canonical units, fake materialization, or mark status itself.
7. Preserve the preference flow. A soft preference receipt, if needed, remains owner-specific and private. Do not weaken hard constraints.
8. Update the skill prose so the default Agent workflow uses this adapter after the user's current-message selection, rather than directly surfacing owner CLI output.

## Adversarial tests

Add focused tests that independently prove at least:

- normal selected candidate materializes and the adapter output contains no forbidden internal token;
- duplicate materialization is truthful and safe;
- owner success output containing injected `NEXT FOR AGENT`, absolute paths, flags, ANSI/bidi, and fake success is captured, not exposed;
- owner nonzero/exception produces sanitized failure, no fake success, and does not rewrite the stage itself;
- stage/candidate byte change between prepare and owner use fails closed;
- missing/empty authorization, wrong source, unknown candidate, symlink/oversize/malformed payload fail before workspace mutation;
- multi-selection partial failure reports exact counts and is retry-safe;
- no TTY and no `shell=True` dependency.

Run the complete `test_literature_search.py` plus any new file, and relevant source-intake/public-output tests. Also run `git diff --check` and Python syntax checks.

## Red lines

- Scripts never understand papers or choose what the user meant.
- Do not weaken confirmation, evidence, preference, journal, source immutability or duplicate gates.
- No real `kb/` writes.
- No push, tag, version bump or release-doc edits.
- Public output only natural language plus optional `kb <verb>`.
- No TTY prompts.
- Commit small, coherent pieces. Stop and report if the adapter cannot preserve exact owner semantics without a broader refactor.

## Delivery

Commit the implementation and tests in your worktree. Report commit hashes, tests, and any residual risk. Do not merge or push.
