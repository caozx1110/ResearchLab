# D1 Track B — layered read-only KB audit

## STEP 0 · base sync

Work only in the assigned worktree. Verify HEAD is exactly `9dcd1ad6134e7700fbfe641d938dae6958af71f4`. Read the shared absolute SSOT “开发者诊断 D1”. If base/files differ or the tree is dirty, STOP and report.

## Objective

Keep existing lint compatibility and add a deterministic, layered, byte-read-only workspace audit that finds the real quality/recovery/security gaps observed in two-paper cold tests.

## File ownership — modify only these

- `.agents/lib/research/index.py`
- `.agents/skills/knowledge-base-manager/SKILL.md`
- `.agents/skills/knowledge-base-manager/scripts/kb.py`
- `.agents/skills/wiki-adapter/SKILL.md`
- `.agents/skills/wiki-adapter/scripts/wiki.py`
- `.agents/lib/research/tests/test_d1_kb_audit.py` (new)

Do not edit diagnostics.py/prefs/config, kb-cli, workspace AGENTS, public docs, installer, or real `kb/`.

## Locked report contract

Add an importable `audit_workspace(project_root)` or equivalent returning a dict with `status`, `counts`, and stable structured `findings`. Each finding contains at least `code`, `category` (`schema|integrity|recovery|security|quality`), `severity` (`error|warning|info`), a path-safe relative `subject`, and a concise message. `PASS` = no findings, `WARN` = warning/info only, `FAIL` = any error. Audit commands exit nonzero only for FAIL; WARN remains actionable success.

First version must include existing lint findings plus:

- stale/invalid current confirmation or verification binding detectable without writes;
- incomplete operation journal;
- dirty/untracked product-owned KB files when a KB Git repo exists (ignore configured raw/output/runtime exclusions; report relative paths only);
- paper metadata gaps: empty authors/year/abstract and taxonomy still only uncategorized/research after complete analysis;
- figures.yaml duplicate candidate identities and suspicious multi-letter nonnumeric labels such as `da`/`in`;
- symlink under KB resolving outside KB (never follow it).

Audit must be byte-identical read-only on empty, clean, and broken workspaces: no bootstrap, locks, journal, index refresh, Git mutation, or mtime change. Do not run semantic LLM analysis. Existing `lint_records` behavior/API stays compatible.

Expose owner `audit` in knowledge-base-manager and wiki-adapter for Agent use. It is not a new public `kb` verb. Output must avoid absolute paths and raw source/evidence content.

## Red lines

- Scripts do not judge research conclusions or taxonomy quality beyond locked deterministic emptiness checks.
- No network/dependency scan in D1; say unsupported rather than fake it.
- Do not weaken record validators or alter records while auditing.
- Never touch real repository `kb/`.

## Tests and commits

Use synthetic temp KB fixtures for PASS and each finding. Include a digest/mtime zero-write assertion and existing lint compatibility. Recreate the two-paper defects minimally: dirty note-fill, empty metadata/taxonomy, duplicate + `figure-da`, incomplete journal, stale receipt, symlink escape. Run focused index/wiki/recovery tests. Commit per coherent piece; do not push.
