# R12 full product functional-contract audit

Read-only review of exact integration HEAD `57d62ab8f3c3ee91001775f7fb17543ea05eff6c`. Treat shipping skills as product source, not as design authority. Read root `AGENTS.md`, SSOT, schemas, public docs and code independently. Do not edit source/docs/git refs or any real `kb/`; use only `mktemp -d` workspaces for behavior probes. Do not push/tag/publish.

Assess, with two independent reproductions for any failure:

- Ease of use: GitHub-link Agent installation, no plugin requirement, natural-language/public `kb` surface, no raw flags/paths/token/digest/TTY leakage, actionable recovery.
- Intelligence: Agent chooses multi-program next actions and composite routing; rules only validate owners/facts. No fixed winner. Idea semantics are Agent-authored. Preferences use central eligible views plus task-specific Agent subset, while neutral skills stay neutral.
- Completeness: `literature-search` is the formal provider-neutral discovery owner; no OpenAlex runtime retrieval. Survey routes search→user selection→intake→analysis→synthesis→batch review→confirmation→report/global N/A with resume at the first stale edge. `research-navigator` remains dev-only.
- No-plugin review UX: Top 3 complete cards, multi-item natural-language batch, Obsidian editable draft that the Agent can read/apply after user dialogue, snapshot reuse on invalid request, single consumption on success.
- R11/R12 safety and maturity: exact reviewed install bytes; all consumer operation registries closed; source-intake private prepare/add handshake and failure zero workspace write; paper managed fill containment; experiment allocator binding; tree/file budget and root/ancestor identity checks; active monitor-run recovery.
- Honest product claims: current maturity labels and external release gates are not overstated.

Run the relevant existing tests and independent disposable probes. Compare actual producer context fields to the central registry. For each local finding report P0–P3, violated invariant, exact evidence and smallest repair. Separate external gates (Obsidian GUI, complex live sources, hosted OS/Python CI) from local blockers. A clean report must include a trace table, exact test counts and exact HEAD—not only “looks good.”
