# R1 updater monotonic apply gate

## STEP 0 — base sync

Verify the isolated worktree starts at integration commit `29ce3db` (full SHA may be checked with `git rev-parse`) and contains the R1 provenance-aware updater. If not, STOP and report; do not reset to another branch.

## Objective

Make update application independently fail-safe against stale authorization or an accidental direct apply: an external copy must never synchronize from a source whose SemVer is equal to or lower than the installed version.

## File ownership — only these files

- `.agents/lib/research/updater.py`
- `.agents/skills/kb-cli/scripts/kb`
- `.agents/lib/research/tests/test_updater.py`
- `.agents/lib/research/tests/test_kb_cli_dispatcher.py` or one new narrow updater test if needed

## Required behavior

1. After resolving/pulling the recorded source for an external copy, read its `.agents/VERSION` and compare with the installed version using the existing SemVer implementation. If source <= installed, do not call workspace sync and return a successful `up_to_date` result with before/after unchanged.
2. A source checkout updating itself keeps its existing `git pull --ff-only` behavior; it cannot be downgraded through workspace sync.
3. `kb update` apply handles `up_to_date` conversationally with exit 0. Public output must not expose flags, internal paths, or commands.
4. Tests must cover equal version, lower stable, lower prerelease-vs-stable, a genuinely higher version that still syncs, and the public handler status/output. Assert the sync helper is never invoked in no-op cases.

## Red lines

- Preserve exact origin/checkout/branch validation and detached/source-choice fail-closed behavior.
- Do not edit installer manifests or unrelated CLI verbs.
- No real workspace writes; tests use temporary directories/mocks. No push.
- Commit the coherent fix, run targeted tests plus full research suite, `git diff --check`, report exact results.
