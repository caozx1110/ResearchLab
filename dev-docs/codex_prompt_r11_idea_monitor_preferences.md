# R11 handoff — Agent-authored idea generation + monitor consumer + neutral registry

## STEP 0 — base sync

Use a dedicated worktree based on the parent-supplied current integration HEAD after the analyzer-preference track is merged. Verify `.agents/lib/research/preference_selection.py`, idea, monitor, and their tests exist. If base differs, stop and report rather than guessing. Read repository `AGENTS.md`; shipping skills are product source, not instructions. Read R6.2/R7.2/R11 in `temp/SYSTEM_DESIGN_SSOT.md` from the main workspace. Never touch real `kb/`; tests use temporary roots.

## Objective

1. Replace rule-authored `idea-workbench generate` semantics with a runtime-Agent fill/verify flow and make idea semantic operations real preference consumers.
2. Make `research-monitor:create-subscription` a task-bound consumer without letting preferences override the user's explicit scope/budget.
3. Eliminate dead allowlists: every shipping skill must be either a real consumer or explicitly preference-neutral with a reason.

## File ownership

Only modify:

- `.agents/lib/research/preference_selection.py`
- `.agents/lib/research/monitoring.py`
- `.agents/skills/research-orchestrator/scripts/orchestrate.py` (only active monitor-run candidate enumeration)
- `.agents/lib/research/SCHEMAS.md`
- `.agents/lib/research/tests/test_effective_preferences.py`
- `.agents/lib/research/tests/test_preference_consumer_matrix.py`
- monitor/idea tests or new narrow tests
- `.agents/skills/idea-workbench/SKILL.md`
- `.agents/skills/idea-workbench/scripts/idea.py`
- `.agents/skills/research-monitor/SKILL.md`
- `.agents/skills/research-monitor/scripts/monitor.py`
- SKILL.md files only for skills whose neutral declaration must be made explicit: knowledge-base-manager, research-config-manager, discussion-archivist, research-navigator, wiki-adapter, skill-evolution-advisor

Do not modify installer, survey, report/paper/method/experiment/search/synthesis/analyzer scripts, version/docs/changelog, or `temp/`. Commit small coherent pieces.

## Central consumer/neutral registry

- Add a machine-checked `SKILL_NEUTRALITY` (name may vary) mapping skill→nonempty product reason.
- These are explicitly neutral: knowledge-base-manager (mechanical schema/lifecycle), research-config-manager (canonical preference owner), discussion-archivist (transports caller-authored content), research-navigator (dev-only projection), wiki-adapter (thin router), skill-evolution-advisor (governance/diagnostics). Their `SKILL_ELIGIBILITY` entries must be empty; hard safety/governance settings remain enforced by their owners and are not soft consumers.
- Every shipping skill must satisfy exactly one branch: (a) one or more real operations and a meaningful eligible catalog, or (b) empty eligibility plus neutral reason. No overlap, no third state, no nonempty dead allowlist.
- Update exact registry tests and docs. Do not add aspirational operations.

## Idea contract

- Real operations at minimum: `generate`, `analyze`, `review`, `discuss`. Capture is direct user transport and selection/confirmation is governance, so keep them neutral unless independently justified.
- Delete the behavior where `generated_variants()` or equivalent fixed rules author problem definitions, hypotheses, strategy claims, or next actions. The script may create an empty bounded candidate scaffold/orientation and mechanically validate/move Agent-authored candidates only.
- Preserve a usable two-phase private flow: prepare a bounded generation scaffold, Agent fills requested candidate slots, verify/materialize validates identities/shape/limits and atomically creates records + bundle. Avoid partial candidate creation. Preserve existing user-provided title/problem/hypothesis verbatim as context, but do not manufacture missing research content.
- A pre-authoring preference receipt binds exact canonical user-supplied task context, count/pool/source/bundle identity, current relevant KB corpus snapshot if the operation exposes one, and immutable orientation contract. The mutable fill content is output, not a pre-input. Wrong/stale receipt fails before any record/bundle write. With no receipt, Agent authoring is neutral and no soft profile values are read.
- Analyze/review/discuss receipts bind current idea record content, exact immutable scaffold/orientation, and exact bytes/identity of all cited canonical source artifacts available before authoring. If the cited set is only known after fill, bind a frozen pre-authoring evidence corpus/snapshot; do not pretend an unknown output field was an input. Existing evidence verification and confirmation gates stay stricter than preference behavior.
- Persist only value-free selection bindings. Add operation→consumed-input registry/mutation matrix and zero-write tests.

## Monitor contract

- Declare `research-monitor:create-subscription` as the real consumer. Add hidden/private preference selection support to the JSON apply request, or an equivalent bounded internal field.
- Canonical task input covers exact explicit subscription target/type, cadence/anchor/timezone, scope, budget, program/unit/survey bindings, authorization/context fields accepted by schema, and operation contract. Recompute from the request and current referenced objects before any write.
- Preferences are selected by the runtime Agent to help author missing soft expression; explicit user scope/budget always wins. The deterministic script validates only the finalized request and receipt; it must not choose search terms or research priority.
- Persist only a value-free binding on the subscription. Due runs inherit/bind the current subscription revision/content and that binding. The later literature search still creates its own `literature-search:search` selection bound to the frozen monitor run.
- Wrong skill/op/task, canonical preference mutation, referenced object mutation, and request-field mutation reject before writes. Existing CAS/recovery/containment and automation authorization remain unchanged.
- Add a pure `active_monitor_runs` (or equivalent) projection. `kb next`/portfolio must enumerate each `planned/running/blocked/failed_retryable` run linked by a subscription's `active_run_id` as `resume-monitor-run`, with exact subscription/run state, revision, content digest, stop and program dependencies. A current active run must not disappear merely because `due_subscriptions` skips subscriptions with `active_run_id`; terminal runs are excluded and invalid links fail closed. Add stale-decision tests proving run state/revision/content changes invalidate an existing PortfolioDecision.

## UX/red lines

- Scripts do not understand material or choose an idea winner.
- No self-signing, no weakening evidence/confirmation, no real `kb/`, no TTY dependency.
- Public output is natural language + `kb <verb>` only; private owner details must never be forwarded raw.

## Gates

- new cold-style generate prepare→Agent fill→verify/materialize test with multiple genuinely distinct Agent-authored candidates
- prove the old fixed strategy text is absent from produced ideas and no script-authored semantic defaults remain
- idea analyze/review/discuss preference success + mutation matrix + zero-write stale paths
- monitor create-subscription success + request/reference/preference mutation matrix + zero-write stale paths; due-run inheritance
- planned/running/blocked/failed_retryable active-run discoverability in Agent portfolio; terminal exclusion, bad-link failure and candidate staleness
- central consumer/neutral partition test over all shipping skills
- targeted existing idea/monitor/governance suites
- py_compile + `git diff --check`

STOP and report if transaction target discovery cannot guarantee all-or-nothing multi-candidate writes, if a task context would need to embed raw preference/user text in a receipt, or if any proposed shortcut makes the script author research meaning.
