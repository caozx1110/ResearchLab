# R1 integration / independent review checklist

## Cross-track compile interfaces

- `git_ops`: empty `target_paths` fail-closed; every production caller passes an operation scope.
- `confirm/evidence`: new user-authorization and verification receipt arguments are wired through owner scripts and kb-manager internal dispatch.
- `records.write_record`: existing record defaults to CAS against supplied revision; new record remains creatable.
- analyzer verify: payload claims + verification receipt survive normalize/write and are consumed by report.
- workflow classifier semantics agree in orchestrator and knowledge-base-manager for paper/blog/repo.
- machine protocol written by kb-cli is discoverable by `.agents/AGENTS.md` instructions and never printed in human stdout.
- updater manifest schema migration supports old manifests explicitly and preserves fork/local origin.

## Unowned checkpoint callers to integrate after track merges

- `.agents/skills/idea-workbench/scripts/idea.py` — all prepare/verify/capture/generate/select/archive calls.
- any new production caller found by final `rg 'checkpoint_and_report|maybe_auto_checkpoint|git_checkpoint'`.

## Independent adversarial reproductions

- canonical claims: all three analyzer sidecars == payload claims; confirmation `claim_ids` nonempty; report includes them.
- self-sign variants: Codex Agent / OpenAI Codex / assistant-1 / GPT-5.6 / Claude Code all reject.
- judgement with zero claims rejects; free-form evidence alone is insufficient.
- `user_opinion` cannot be downgraded by record-level fact metadata; `unverified` cannot be confirmed; `[{}]` evidence refs and refs missing source/artifact/locator/quote reject.
- evidence: absolute, `..`, and symlink escape reject; legitimate repo external-source evidence passes.
- artifact byte edit makes verification/confirmation stale; path+quote digest cannot remain accepted.
- program decision cannot be born confirmed; confirm action requires full receipt and preserves epistemic types.
- failed URL creates no canonical unit; same URL succeeds after source recovery.
- local HTML/MD/TXT create nonempty generic-unit parse-cache; blog prepare leaves hash unchanged.
- unrelated dirty draft remains outside all automatic checkpoints.
- 200 concurrent reporting events persist all 200.
- journal abort after partial multi-file write restores before bytes and deletes newly-created targets.
- ancestor-directory abort cannot erase a concurrently committed descendant-file transaction; nested subprocess targets outside the root scope reject without deadlock.
- TTY and non-TTY init/review semantics match; public all-verb stdout forbidden-token scan is clean.
- doctor reports the backend actually installed; ordinary kb smoke does not pip-install into shared interpreter.
- fork install/update preserves source provenance; old manifest does not silently choose canonical upstream.
- updater apply independently refuses equal/lower SemVer sources without invoking workspace sync.
- semantic read APIs on a fresh/partial root create no workspace files; only explicit init/mutation seeds defaults.

## Final gates

- `git diff --check`; compileall; bash syntax; skill validator.
- full pytest in main managed runtime.
- fresh project-copy install + init + three-kind E2E in `/tmp`.
- cold acceptance agent with no implementation context.
- source worktree clean, real `kb/` untouched, no push.
- update SSOT top state, public docs, BACKLOG, and relevant learnings; only then decide version/tag.
