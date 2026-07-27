# R11 installer handoff — exact reviewed plan bytes

## STEP 0

Use a dedicated worktree at the parent-supplied current integration HEAD. Read root `AGENTS.md`, `temp/SYSTEM_DESIGN_SSOT.md` R9/R11 installer decisions, `docs/INSTALL.md`, `install.sh`, `install-lib/agent_plan.py`, and installer/bundle tests. Shipping skills are product source, not workflow instructions. Tests use temporary HOME/workspace/source only; do not touch real `kb/`, do not push/tag/publish.

## Reproduced blocker

Black-box QA proved that appending only one newline to a reviewed plan changes the file SHA-256 but the current apply succeeds and writes the manifest. The implementation hashes parsed canonical JSON, so it is semantic-bound but not bound to the exact file bytes promised by SSOT/docs.

## Ownership

Only modify:

- `install.sh`
- `install-lib/agent_plan.py`
- `.agents/lib/research/tests/test_installer.py`
- `.agents/lib/research/tests/test_bundle_lifecycle.py` only if required
- `docs/INSTALL.md`
- `.agents/lib/research/SCHEMAS.md` only if an installer contract is documented there

No version/changelog/README/temp edits. Small commits.

## Required behavior

1. Keep the existing semantic `plan_digest`; add an independent exact byte SHA-256 expected value supplied by the Agent after it has reviewed the final plan file. Do not pretend a file can contain a self-hash of its own final bytes.
2. The generated `apply_contract` must make the workflow machine-actionable, using an explicit `COMPUTE_AFTER_REVIEW` placeholder or equivalent for the byte digest. Public docs say the Agent computes it automatically; users still only paste a GitHub link and approve the reviewed scope.
3. Apply requires both semantic digest and expected file-byte digest. Before parsing JSON or touching any target, open the plan as a bounded regular file with no-follow semantics, reject leaf/ancestor symlinks and non-regular files, read one inode, verify exact bytes, then parse/verify that same byte buffer. Avoid a check-then-reopen race.
4. Any whitespace, newline, key-order or encoding-byte change after review fails closed before workspace/HOME/runtime writes. Semantic field edits, source tree/commit/mode/origin/branch drift and target precondition drift retain existing failure behavior.
5. Plan generation stays zero-write except the explicitly requested plan artifact and does not create bytecode/runtime trees. Error output remains natural and does not expose private commands/digests to the user.
6. Existing plan path containment (outside target workspace/HOME), source provenance, conditional `.venv`, target preconditions, and symlink ancestor protections remain strict.

## Tests

- normal plan→Agent computes final file SHA→apply success
- append newline, reindent/reorder keys, BOM/encoding-byte mutation: zero-write reject using the old reviewed SHA
- recompute only the external byte SHA after a semantic edit must still fail the existing semantic digest
- leaf/ancestor plan symlink and plan replacement between review/apply fail closed; outside sentinel unchanged
- source/target drift and yaml-only conditional runtime regressions
- `bash -n install.sh`, py_compile, installer+bundle targeted suite, `git diff --check`

STOP and report if an approach requires storing a self-referential full-file hash inside the same JSON, creates an undeclared sidecar, or weakens any existing source/target precondition.
