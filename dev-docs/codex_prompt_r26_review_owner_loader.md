# R26 public review owner-loader compatibility

## STEP 0 — base sync

Create/use a dedicated worktree from current integration HEAD `839e732`; verify `.agents/skills/kb-cli/scripts/kb` contains `_review_owner_module` and the R26 report/portfolio commits. If the worktree is stale, sync it to `839e732` before editing. Do not alter the main worktree.

## Ownership

Only edit:

- `.agents/skills/kb-cli/scripts/kb`
- the smallest relevant test file(s) under `.agents/lib/research/tests/`

Do not edit docs, schemas, installer files, report-author, orchestrator, portfolio code, real `kb/`, version metadata, or ignored SSOT/BACKLOG.

## Reproduced defect and locked contract

`_review_owner_module` calls `module_from_spec` then `exec_module` without registering the module in `sys.modules`. A real public `kb review` subprocess can fail while importing a dataclass-bearing owner on supported Python versions. Dynamic loading must follow normal import lifecycle:

1. use a unique stable module name per owner/path;
2. register the exact module object in `sys.modules` before `exec_module`;
3. on execution or interface validation failure, remove only the entry if it is still this module object; do not cache a partial module;
4. on success, retain both module-table identity and existing `_REVIEW_OWNER_MODULES` cache behavior;
5. preserve path containment and public output contracts.

First add a focused red regression proving registration exists during execution and failure cleanup is safe. Then implement the smallest fix. Reproduce the existing failing public route:

`/Users/czx/miniconda3/bin/pytest -q .agents/lib/research/tests/test_r2_judgement_convergence.py::test_public_review_snapshot_executes_real_program_owner_route`

Run adjacent kb/review tests and Python 3.9-compatible AST parse. No network, API key, paid service, plugin, push, tag, or publish.

## Red lines

Scripts do not infer research meaning. Do not weaken confirmation/evidence/CAS/transaction gates. Public output remains natural language plus `kb <verb>` only. Tests use temporary directories, never real `kb/`.

Commit red test and implementation separately where practical. STOP and report if the diagnosis does not reproduce or requires expanding the owned file surface.
