# D1 Track C — public/Agent integration and docs

## STEP 0 · base sync

Work only in the assigned worktree. Verify HEAD is exactly `9dcd1ad6134e7700fbfe641d938dae6958af71f4`. Read the shared absolute SSOT “开发者诊断 D1”. If base/files differ or tree is dirty, STOP and report.

## Objective

Wire optional runtime failure capture into the conversational dispatcher, teach installed Agents the natural-language diagnostic contract, and document the honest capability without adding a public verb.

## File ownership — modify only these

- `.agents/skills/kb-cli/scripts/kb`
- `.agents/AGENTS.md`
- `README.md`
- `docs/USER_GUIDE.md`
- `docs/DESIGN.md`
- `CHANGELOG.md`
- `.agents/lib/research/tests/test_d1_public_diagnostics.py` (new)

Do not edit diagnostics.py/prefs/config, index.py, knowledge-base-manager/wiki scripts, other tests, installer, or real `kb/`.

## Locked integration API

Track A will provide `research.diagnostics.capture_runtime_failure(project_root, *, skill, operation, returncode, public_summary="")` and normalized policy reads. Track B will provide `research.index.audit_workspace(project_root)`. Code defensively during parallel work, but do not create duplicate implementations.

Requirements:

- After a child owner returns nonzero, call capture only after the original result is known; default off creates nothing; errors-only/developer may create one redacted issue; per-skill off wins.
- Never pass raw stdout/stderr/traceback/arguments/user input/absolute paths into capture. Use stable owner skill, public verb/operation, return code, and a fixed Chinese-safe summary only.
- Capture exceptions are swallowed into private protocol diagnostics and never change the original exit code or public message.
- Success/no-op never creates an issue.
- `kb doctor` public stdout stays concise Chinese. Its private Agent protocol may include effective diagnostic mode and Track B mechanical audit summary after merge, but ordinary calls must remain read-only and must not create an uninitialized KB.
- Installed Agent rules: obey off/errors-only/developer, explicit user requests always record, corrections/reusable friction captured only when enabled, deep retrospective only in developer mode and budget, never auto-upload or auto-edit skills, use natural language such as “开启开发者诊断/检查知识库健康”.
- Preserve exactly 15 public verbs; do not add `kb lint` or `kb diagnostics`.

Docs must distinguish mandatory governance gates from optional diagnostics, document local-only privacy and token cost, and keep maturity honest (D1 initially beta/scaffold, not stable).

## Red lines

- Public stdout only natural language + supported `kb <verb>`.
- No internal paths/flags/env/protocol markers.
- No TTY interaction and no background telemetry.
- Never touch real repository `kb/`.

## Tests and commits

Add installed-style dispatcher tests: default off zero write, enabled failure one issue, same failure bumps, per-skill off, success zero issue, capture exception preserves exit/public text, doctor read-only/public-safe/private summary, 15 verbs unchanged. Run dispatcher/public contract tests. Commit per coherent piece; do not push.
