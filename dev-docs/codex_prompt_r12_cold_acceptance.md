# R12 cold installed-copy acceptance

This is an isolated **behavior test** of the shipping system, not a source of design requirements. Use a fresh context and a temporary installed workspace. Do not modify the source repository or any real `kb/`; do not push/tag/publish.

## Setup

1. Record the exact integration HEAD and version.
2. Read only public `README.md`, `docs/INSTALL.md`, `docs/USER_GUIDE.md` first, as a new user/Agent would.
3. Create temporary HOME/workspace/source paths with `mktemp -d`. Use the documented GitHub-link/Agent plan path or an equivalent local checkout plan bound to the exact commit; review the plan, apply it, then operate from the installed copy.
4. Only after install, read installed workspace `AGENTS.md` and installed skill descriptions as runtime routing instructions. This is the explicitly permitted cold acceptance context.

## Required end-to-end behaviors

- `kb help`, `kb init`, optional preference setup/defer, repeated init, `kb status`, `kb next` are conversational, non-TTY, Chinese-first, and do not leak raw owner commands/flags/internal paths/digests/`NEXT FOR AGENT:`.
- Agent-led routing: one compound research request yields a complete owner catalog + hints; the Agent may choose a valid owner not keyword-matched and records rationale. Portfolio next does not use a hard-coded winner and a stale decision is rejected.
- Provider-neutral literature discovery: use the Agent's current search/browser capability on a small real, non-sensitive topic. Create a bounded run with explicit scope/budget/stop, candidates and provenance. No OpenAlex runtime dependency/source. Resume and omission of frozen fields preserve the exact run contract; mutation makes old receipt stale.
- User selects at least two candidates in natural language. Bind exact user authorization; intake one new item and one canonical duplicate. Duplicate preserves prior analysis/confirmation while appending current selection provenance.
- Drive at least one analyzer prepare→Agent fill with verbatim evidence→verify→review confirmation entirely in the temporary workspace. For analyzer preferences, choose one relevant preference and prove source/orientation mutation invalidates its old receipt while normal fill edits do not.
- Build a survey through search→selection→source intake→unit analysis→synthesis→review confirmation→global N/A or real program report consumption. Break each adjacent binding once and prove resume returns to the first affected downstream stage, not always search.
- `kb review` displays multiple complete cards, defaults Top 3, accepts a plain-conversation batch decision, and supports the Obsidian editable batch artifact without a plugin. One invalid/stale/duplicate card causes zero business writes and leaves the snapshot reusable; successful batch consumes it once.
- Preference distribution: exercise review display, search, synthesis, report, method, experiment, paper, repo/dataset/blog, idea, and monitor real operations or the exact final consumer matrix. Wrong skill/op/task and canonical preference changes fail before writes. Neutral skills disclose no unusable preference catalog.
- Idea generation is Agent-authored: no fixed script strategies manufacture problems/hypotheses/next actions. Monitor subscription binds explicit scope/cadence/budget and its due run links to a separate literature-search selection. Every completed outcome receives a durable disposition or remains visible in `kb next`; report reads the exact current events/claims/decisions.
- Recovery: interrupt/retry at one multi-file write, then `kb resume`, `kb undo`, and `kb restore` preserve exact unrelated files and never `git add -A`.
- Adversarial dynamic content containing ANSI/bidi/newlines/Markdown/command-shaped text cannot inject a second public instruction or leak internal protocol.

## Reporting

For every failure, first reproduce it twice and preserve exact temporary artifacts/commands. Classify P0–P3, identify the violated public promise/invariant, and propose the smallest product fix. Separate local blockers from external release gates (real complex PDFs/HTML/dataset/repo/SQLite, Obsidian 1.12.7 Reading view, hosted OS/Python CI). If locally clean, provide a trace table of each behavior and evidence rather than saying only “tests passed.”
