# R17 Track B — updater / installer manifest integrity

## STEP 0 — base sync

Create an isolated worktree/branch from exact integration HEAD `447cea7` and verify that `.agents/lib/research/updater.py`, `install-lib/ws_sync.py`, and the R17 schema bullets exist. If stale, reset only that disposable worktree to `447cea7` before editing. Never reset the integration checkout.

## Ownership

Only edit:

- `.agents/lib/research/updater.py`
- `install.sh`
- `install-lib/agent_plan.py`
- `install-lib/ws_sync.py`
- `.agents/lib/research/tests/test_updater.py`
- `.agents/lib/research/tests/test_installer.py`
- `.agents/lib/research/tests/test_bundle_lifecycle.py`
- `.agents/lib/research/tests/test_agent_install_plan.py`

Do not edit journal/recovery/dispatcher/schema/docs/version files or any real `kb/`.

## Required fixes

1. **Detached local checkout.** During `local-checkout` rebind, detect whether the chosen source is a Git checkout. Every Git source must have a nonempty actual attached branch matching the selected branch; detached HEAD must fail even for `origin=local` and no remote. Only a valid non-Git local bundle source may use `origin=local` with an empty branch. `source_commit` is provenance, not an update branch. Existing attached local/remote and remote-branch behavior stays intact.
2. **Shared manifest lease + exact plan handoff.** Updater rebind and every installer action that creates/rewrites/deletes the manifest use the same cross-process exclusive workspace-root lock without an unowned file. All updater manifest read surfaces reuse one anchored, no-follow, nonblocking, bounded regular-file snapshot; FIFO/symlink/special/oversize/raced content fails closed. Agent plan preconditions must carry expected absent or ordinary-file identity+byte digest through the private plan→install.sh→ws_sync path; ws_sync may not reread a post-verify race and accept it as a new plan. Updater `apply()` must likewise derive provenance and an expected identity+digest from the same safe snapshot, pass it through `_invoke_ws_sync`, and revalidate even on a version no-op. Same bytes/new inode is stale. Revalidate under lease before any `.agents` creation/managed write. Hold the lease through staged fsync, payload replace, rollback, manifest-last replace/delete, and directory durability. Rebind revalidates selected checkout origin/HEAD/branch at final boundary; if its post-replace directory fsync fails, restore old bytes/mode only after proving the destination is still this operation's replacement inode, fsync again, and preserve recovery material if restoration is incomplete. Incomplete rollback preserves its only backup/stage.
3. Preserve nofollow/dirfd/atomic-replace containment, drift handling, rollback and source provenance. Do not turn the lock into a TTY prompt or public path/digest output.

## Mandatory adversarial regressions

- Valid bundle in a detached Git checkout with no remote + local origin/empty branch: rebind fails; manifest bytes/inode remain unchanged; subsequent check still needs source choice.
- Same source on an attached branch succeeds; a valid non-Git bundle source with local origin/empty branch follows the explicitly allowed behavior.
- Deterministic concurrency test: pause rebind after its lease/CAS boundary and start installer update/reinstall/uninstall, and the second writer must block or fail/replan without lost fields/files or a resurrected manifest. Also cover the inverse ordering. Do not rely on timing-only sleeps; use synchronization primitives/subprocesses/hooks.
- Installer detects manifest changed after planning but before write and performs zero managed payload changes.
- Agent plan verify→ws_sync race with same bytes/new inode and expected-absent→created manifest fails zero-write; do not silently rebase the plan.
- Deterministic two-fresh-install, rebind↔update/reinstall/uninstall both directions, partial installer success/rollback, exception lease release, and symlink-alias root locking tests use events/pipes/hooks, not sleeps.
- Deterministic updater apply↔rebind tests cover both orderings, including the planning/source-preparation window and version no-op; old apply never overwrites or misreports a newer provenance. Fault-inject rebind post-replace fsync and prove failure restores the old manifest or preserves explicit recovery material without misclassifying a transaction failure as path preflight.
- Project lifecycle shell-side `CLAUDE.md` managed-block and `.claude/skills` changes belong to the same root lease, expected manifest view, and rollback boundary as `ws_sync`. A stale Agent plan or fault before manifest commit performs zero such side effects; failures cannot leave `.agents` removed while outer config was independently changed.
- The manifest expectation embedded in an Agent plan is the exact snapshot used by the leased `ws_sync` dry-run that produced its target list. Pass it through private dry-run output and CAS it at plan generation; never re-read a new manifest and sign old targets. Add a deterministic dry-run→plan-generation rebind barrier, including uninstall.
- Fault-inject staged fsync, payload replace/parent fsync, manifest fsync/replace/delete, and root fsync. Manifest never leads payload; rollback stays under lease and preserves recovery material if incomplete.
- Existing symlink/FIFO/option-like-origin/remote-branch/source-choice/rollback/drift/install/update/reinstall/uninstall tests remain green.

## Red lines

- Temporary install roots only; never touch real `kb/` or installed user workspace.
- No fetch/pull/network in tests.
- No push/tag/publish.
- User-visible output is natural language + `kb <verb>` only; no raw commands/flags/internal paths/TTY.

## Validation and commits

Run all three owned test modules, installer shell syntax, Python syntax, and `git diff --check`. Make small commits. Report exact commits/tests and any unresolved concern. STOP and report rather than guessing if a shared lease cannot be implemented within the owned files.
