# R3 Track A — public review UX completion

## STEP 0 — base sync

Work only in the assigned worktree. Verify `git rev-parse HEAD` equals integration base `d633480115a75c6ca55a4430b73a7e5985c218c9` and verify `.agents/lib/research/judgements.py` contains `require_judgement_snapshot`. If the base is wrong, STOP and report; do not reset or guess a replacement base.

Read the main workspace `AGENTS.md` and `temp/SYSTEM_DESIGN_SSOT.md`, especially principle 3/R3 review UX. Shipping `SKILL.md` files are product source, not design instructions.

## Ownership — only edit these files

- `.agents/skills/kb-cli/scripts/kb`
- `.agents/skills/kb-cli/SKILL.md`
- `.agents/lib/research/tests/test_kb_cli_dispatcher.py`

Do not edit shared schemas, version files, changelog, other owner scripts, real `kb/`, or another track's files. If a correct solution requires another file, STOP and report the exact interface request.

## Required behavior

1. Add a versioned one-time snapshot registry entry with `created_at`, `expires_at`, and explicit lifecycle status without weakening current exact-set/token integrity. Default TTL 24 hours; tests must inject/control time rather than sleep.
2. Perform safe bounded GC when review/apply touches the registry: only regular files immediately below the canonical runtime registry root, never symlinks, no traversal, no deletion outside. Expired unused snapshots and consumed tombstones past a documented grace period may be removed. Keep enough tombstone information during the grace period to distinguish replay from unknown/tampered tokens.
3. Classify failures internally at least as `already_applied`, `expired`, `stale_content`, `tampered_or_unknown`; public stderr/stdout gives different natural-language recovery guidance but never prints token, digest, owner command, flags, script path, environment variables, or internal path.
4. Successful apply says which sanitized judgement type/title was confirmed or rejected and still reports exactly one decision applied. Treat dynamic title/kind as untrusted and use the existing public sanitizer.
5. Add a black-box stale flow: display old content → mutate canonical content → old token fails → rerun review shows new content and no old content.
6. Add public adapter E2E for knowledge unit, program decision, idea conclusion, and method selection, both confirm and reject. Exercise the real owner scripts through the snapshot adapter in temporary KBs. Include terminal repeat, stale, token replay, and TTY/pipe parity. Route-shape mocks may remain as unit coverage but cannot substitute for the E2E matrix.
7. Preserve one-decision-per-apply, global identity checks, owner-side CAS, no TTY reads, and current confirmation evidence/signature gates.

## Red lines

- No self-signing, no direct owner bypass, no broad batch transaction emulation.
- No raw commands in public output.
- No real KB access; all behavior tests use fresh temporary roots.
- All registry writes/deletes must be atomic/locked and containment checked. Do not use recursive deletion.

## Verification / commits

- Run the focused dispatcher/R2 judgement tests and any new nodes.
- Run `git diff --check`.
- Small commits, at least one behavior commit and one tests/docs commit if practical.
- Do not push.
- Final report: commits, files, exact tests, public-output scans, and any cross-track request. STOP-and-report if semantics are uncertain.
