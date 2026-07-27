# R12 paper verify containment repair

## STEP 0 — base sync

- Create an isolated worktree/branch from exact integration base `34c4114e7902fa18395a2708df2b2b9c90a48e9e`; verify HEAD before editing.

## Ownership

Only modify:

- `.agents/skills/paper-analyst/scripts/paper.py`
- new paper-specific tests under `.agents/lib/research/tests/` whose filenames start `test_paper_`

Do not edit shared preference registry/matrix, intake, experiment, docs/version, real `kb/`, or unrelated files.

## Reproduced blocker

Paper verify currently accepts an absolute ordinary fill outside the workspace because the containment helper returns early. An external fill can obtain a receipt and publish canonical judgement.

All verify fills must be managed files inside the current canonical unit/workspace and within the exact allowed phase location. Reject workspace siblings, absolute external paths, `..`, ancestor/leaf symlinks, hardlinks that violate the intended managed identity if detectable, inode replacement, and byte changes. Open ancestors and leaf no-follow; bind and parse the same fd/bytes where practical, and revalidate at the write boundary. Every failure must leave canonical record, evidence, receipts, staging, journals, and runtime files unchanged.

Add two-round adversarial tests for external sibling, symlink ancestor/leaf, byte mutation after receipt, inode replacement with same bytes, wrong phase/unit, and valid managed screen/note flows. Preserve all existing evidence/substance/confirmation gates.

Red lines: no semantic judgement in scripts; no governance weakening; public output contract unchanged; no push. Run targeted paper/preference tests, `py_compile`, `git diff --check`; commit and report hashes.
