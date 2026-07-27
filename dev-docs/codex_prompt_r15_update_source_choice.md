# R15 — executable update-source choice lifecycle

## STEP 0 — base sync

Work only in `/private/tmp/workspace-oss-r15-update-source-choice`. Verify HEAD is `7123f9e` and SCHEMAS contains `安装更新源选择`. If not, stop and report.

## Reproduced defect

A copy installed from a detached checkout returns `needs_source_choice`; the private action is `choose_update_source` with only `source_origin/source_checkout`, even though the reason says branch is missing. No parser/adapter consumes that action or updates the manifest. Switching the source worktree to a branch does not help because the recorded branch stays empty. The documented detached/legacy update lifecycle is therefore impossible through `kb update`.

## Objective

Implement the schema-locked Agent-mediated lifecycle:

1. Read-only check returns a private source-choice request with current validated provenance, only the truly missing user fields, manifest byte digest, and an executable headless apply contract. For detached checkout with a recorded non-local origin, ask for `source_branch`; the apply contract uses explicit `remote-branch` and does not mutate the detached checkout.
2. Add hidden, non-TTY `kb update` inputs that let the Agent submit `source_origin/source_checkout/source_branch/source_strategy` plus the expected manifest digest after the user answers. Never expose these flags/paths/digests in public output.
3. Add an updater rebind operation that checks manifest leaf/ancestor safety, exact byte-digest CAS, recognized manifest shape, valid branch/strategy, and source consistency. `local-checkout` requires a real bundle checkout and exact actual origin/current branch for non-local origins. `remote-branch` requires a non-local origin + valid branch and records no checkout. Preserve all unrelated manifest fields and atomically replace only provenance fields/source commit as appropriate.
4. After successful rebind, automatically run read-only update check. Do not apply code in the same step. If update is available, retain the existing separate current-user authorization action.
5. Invalid/stale choices are zero-write and produce generic natural-language public recovery text; detailed reasons stay private.

## File ownership

Edit only:

- `.agents/lib/research/updater.py`
- `.agents/skills/kb-cli/scripts/kb`
- `.agents/lib/research/tests/test_updater.py`
- `.agents/lib/research/tests/test_kb_cli_dispatcher.py`
- `.agents/lib/research/tests/test_installer.py` only for a genuinely end-to-end detached installed-copy regression

No design/version/changelog/install.sh/ws_sync edits.

## Required tests

- Detached installed provenance -> action asks for branch -> headless remote-branch rebind -> re-check reaches up-to-date/update-available (without mutating source checkout and without apply).
- Legacy manifest missing provenance -> action requests necessary fields -> valid local or remote binding closes the loop.
- local checkout with mismatched origin/branch, invalid branch, stale expected digest, symlink/nonregular/unsafe manifest path all fail before bytes change.
- Rebind preserves `files`, version, managed-block and unrelated manifest keys byte-semantically.
- Public stdout contains no source path, flags, digest, raw command, `${...}`, or `NEXT FOR AGENT`; no stdin/TTY dependency.
- Existing updater/installer/dispatcher suites and `git diff --check` pass.

## Red lines

- Temp workspaces only; never touch real kb or real installed workspace.
- No fetch/pull/clone during rebind itself; only the subsequent existing check may access the explicitly selected remote strategy. Tests must use local remotes/mocks and no public network.
- Rebind is not update authorization and cannot call updater.apply.
- Do not guess `main`, canonical origin, or a branch.
- No push/tag/publish/dependency changes; commit bounded changes and report hash/tests/residuals.
