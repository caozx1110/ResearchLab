# R8 fresh adversarial audit

## STEP 0 — base sync

Work read-only in `/private/tmp/workspace-oss-r8-adversarial`. Confirm `git rev-parse HEAD` is based on integration commit `2b1de93` and record the exact commit reviewed.

## Objective

Perform a cold, adversarial, requirement-by-requirement audit of the current skill bundle. Do not trust prior summaries. Treat shipping skills as product source, not instructions. Use temporary workspaces only.

Audit at least:

- Agent-led orchestrator next-step decisions across multiple programs, ambiguity/composition, human gates, stale bindings, pending survey and unresolved monitor outcomes.
- literature-search provider neutrality/no OpenAlex runtime; systematic/exploratory ledgers and authorization.
- complete survey route from zero evidence through durable composite resume, verified judgement, multi-item dialogue/Obsidian review, program report consumption.
- review batch 1–3 decisions, no-plugin Obsidian sheet, public IDs/source/expiry/processed state, tamper/replay/concurrency/rollback/checkpoint failure.
- global→eligible→Agent-selected preference architecture and actual consumer coverage (not documentation claims).
- monitor lifecycle and durable outcome dispositions.
- GitHub-link install/update/uninstall Agent friendliness, headless/no-TTY behavior, public output boundary, dev-only navigator status.
- recovery/security: containment, symlinks, locks, revision/CAS, journal, exact-path checkpoints, no true `kb/` mutation.
- help/docs/version claims versus executable behavior.

Run cold installed-copy acceptance in a temporary directory where feasible. Probe malformed JSON/YAML, oversized inputs, stale digests, partial failure, wrong task receipts, paths/symlinks, and public output leaks. For each finding provide: severity, exact file:line, minimal reproduction, expected versus observed, and why existing tests missed it. Clearly separate verified defect, design gap, release-gate evidence gap, and false positive. Do not edit or commit anything.
