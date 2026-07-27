# D1 Track A — diagnostics core/config

## STEP 0 · base sync

Work only in the assigned worktree. Verify `git rev-parse HEAD` is exactly `9dcd1ad6134e7700fbfe641d938dae6958af71f4` and the files below exist. If not, STOP and report; do not reset a dirty tree. Read the shared absolute SSOT section “开发者诊断 D1” before editing.

## Objective

Implement optional, local-only structured diagnostic issue capture and configuration. This track owns data/policy, not public routing or KB audit.

## File ownership — modify only these

- `.agents/lib/research/diagnostics.py` (new)
- `.agents/lib/research/prefs.py`
- `.agents/lib/research/SCHEMAS.md`
- `.agents/skills/skill-evolution-advisor/SKILL.md`
- `.agents/skills/skill-evolution-advisor/scripts/diagnostics.py` (new)
- `.agents/skills/research-config-manager/SKILL.md`
- `.agents/skills/research-config-manager/scripts/config.py`
- `.agents/lib/research/tests/test_d1_diagnostics_core.py` (new)

Do not edit kb-cli, index.py, knowledge-base-manager, wiki-adapter, workspace AGENTS, public docs, installer, or real `kb/`.

## Locked interface

Provide importable APIs with these semantic contracts (names may vary only if you tell root before merge):

- `diagnostics_path(project_root)` → `kb/memory/skill-evolution/issues.yaml`
- `diagnostics_policy(project_root, skill="")` → normalized effective policy
- `record_diagnostic_issue(project_root, *, category, severity, skill, summary, expected="", actual="", trigger="", source="runtime", reproducible="unknown", context="", error_class="")` → `(issue, created)` or a clearly documented equivalent
- `capture_runtime_failure(project_root, *, skill, operation, returncode, public_summary="")` → issue or `None` according to policy
- list/review (`confirmed|dismissed|resolved`) and a local redacted export-preview operation

Runtime preference contract:

- workspace mode `off|errors-only|developer`, default `off`
- per-skill `inherit|off|errors-only|developer`
- `local_only=true` forced true in D1
- nonnegative `token_budget_per_task`, positive `max_issues_per_task`, dedup/cooldown fields
- explicit user-requested capture remains possible even if automatic mode is off

Issue schema must include stable id, category, severity, status, skill, summary, expected/actual, trigger, source, reproducible, occurrences, first/last seen, bundle/source version fields when locally available, redacted context/error class, privacy classification. Similar issues merge deterministically and bump occurrences. Never store raw stdout/stderr, tracebacks, user messages, secrets, env vars, evidence/raw text, or absolute paths. Redaction must be deterministic and tested.

All writes use one root mutation transaction with exact targets. Concurrent 50 distinct captures must retain 50; near duplicates merge with full occurrence count. Reads on an absent root are byte-identical. Diagnostic failure must not mutate half a record.

## Red lines

- No telemetry/network/upload.
- Do not auto-edit skills or roadmap from a defect.
- Do not weaken confirmation/evidence/recovery gates.
- Scripts never infer root cause or research meaning.
- Never touch real repository `kb/`.

## Tests and commits

Add focused tests for defaults, per-skill override, off vs explicit capture, redaction, dedup, statuses, export preview, 50 concurrency, rollback, absent-root reads. Run focused tests plus existing learnings/config transaction suites. Commit per coherent piece; do not push. STOP and report any interface conflict.
