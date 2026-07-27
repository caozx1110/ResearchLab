# Codex handoff — P0 hotfixes from review verification

You are implementing 4 independently-verified, pure-bug hotfixes surfaced by a code review that I (the maintainer's Claude) already reproduced against real code. These are NOT design changes — do not redesign gates, workflow state, or schema. Fix exactly what is specified, small-commit per fix, run the suite, stop-and-report on any surprise.

Model: gpt-5.6-sol, reasoning xhigh, full access. Repo root = current working dir.

---

## STEP 0 — base sync (do this FIRST, before any edit)

Worktrees here have historically been opened on a stale April commit. Verify you are on current main:

1. `git rev-parse HEAD` MUST print `46d3b017d74c27cfac486f29e71538233576c5ab`. If not, `git status` then `git reset --hard 46d3b01` (only if clean / no wanted local work) and re-verify.
2. Confirm these anchors exist (they are the fix sites; if line numbers drift, locate by content, do NOT trust the numbers):
   - `.agents/lib/research/retrieval.py` line ~10: `TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+-]*", re.IGNORECASE)`
   - `.agents/skills/research-orchestrator/scripts/orchestrate.py` line ~961: `if args.command == "status":`
   - `.agents/skills/kb-cli/scripts/kb` line ~190: `def handle_next` (does `del args`)
   - `README.md` line ~97: `kb\` 动词清单以代码为准，共 9 个`
3. Test runner — **use the managed venv interpreter, NOT system python3.** The suite hard-imports `fitz` (PyMuPDF); system `/usr/bin/python3` (3.9.6) lacks it and gives 2 unrelated PDF-backend failures. The managed venv at the repo root has fitz+yaml. Run:

   ```
   PY=/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python3
   $PY -m pytest .agents/lib/research/tests -q
   ```

   (config in `pytest.ini`; `pythonpath` is already set to `.agents/lib` + navigator scripts). **Expected green baseline = `287 passed`.** Run it once now to confirm before you touch anything, and report the count. If you instead see `285 passed, 2 failed` with `ModuleNotFoundError: No module named 'fitz'`, you used the wrong interpreter — switch to `$PY` above. Those 2 fitz failures are pre-existing and unrelated to all 4 fixes; do NOT treat them as your regression, but do NOT use them as an excuse to skip the green-baseline check either — use `$PY` so the baseline is a clean 287.

---

## FILE OWNERSHIP — touch ONLY these

- Fix 1: `.agents/lib/research/retrieval.py` + `.agents/lib/research/tests/test_ranked_retrieval.py`
- Fix 2: `.agents/skills/research-orchestrator/scripts/orchestrate.py` + a test file under `.agents/lib/research/tests/`
- Fix 3: `.agents/skills/kb-cli/scripts/kb` + `.agents/skills/research-orchestrator/scripts/orchestrate.py` + a test file
- Fix 4: `README.md` + `docs/USER_GUIDE.md` (docs only)

Fixes 2 and 3 BOTH edit `orchestrate.py` — do them in the SAME session, sequentially, commit-per-fix. Do NOT parallelize across worktrees.

---

## FIX 1 — CJK/Unicode query tokenizer (retrieval.py)

**Bug (verified):** `TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_+-]*", re.IGNORECASE)` matches ASCII only. `tokenize_query` therefore returns `[]` for a pure-Chinese query. In `rank_records` (retrieval.py ~87): `if not query_tokens: return list(records)` → a real CJK search silently degrades to "return ALL records, unranked." This is a hard failure for a Chinese-first system.

**Downstream context (already correct, do NOT change):** `score_record` matches via substring `token in lowered` (retrieval.py ~71), so once `tokenize_query` emits CJK tokens, scoring/matching already works. The fix is confined to tokenization.

**Required behavior:**
- A pure-CJK query (e.g. `"灵巧手 recovery"`) MUST tokenize to a NON-empty token list including the CJK run(s) and the ASCII token, so `rank_records` filters+ranks instead of returning everything.
- An EMPTY / whitespace-only query MUST still tokenize to `[]` (this preserves the filter-only path — see the invariant test below).
- Keep it dependency-free (stdlib `re` only; no jieba/segmentation lib — this is a tokenizer, not a word segmenter). Approach: broaden the regex to also capture runs of non-ASCII "word" characters. A workable pattern is to match EITHER the existing ASCII token OR a run of Unicode word chars that are not ASCII-space/punctuation. E.g. treat each maximal run of CJK (and other non-ASCII letters) as a token, alongside ASCII `[a-z0-9][a-z0-9_+-]*`. Use `re.UNICODE` semantics. Do NOT lowercase-break CJK. Verify `tokenize_query("  ")==[]` and `tokenize_query("灵巧手recovery")` yields both a CJK token and `recovery` (or the combined-then-split behavior you choose — document it in a comment).

**Invariant you MUST NOT break:** `.agents/lib/research/tests/test_ranked_retrieval.py::test_empty_search_keeps_filter_only_behavior_for_review_queue` (empty query → filter-only, no `_search_score`). Run it after.

**Add tests** to `test_ranked_retrieval.py`:
- CJK query returns only the matching record(s), NOT all records, and sets `_search_score`.
- Mixed CJK+ASCII query works.
- Empty query still returns filter-only (assert existing behavior explicitly if not already).

Commit: `fix(retrieval): tokenize CJK/Unicode queries so Chinese search filters instead of returning all`

---

## FIX 2 — `orchestrate.py status` must not create programs on read

**Bug (verified, reproduced live):** the `status` subcommand (orchestrate.py ~961) calls `ensure_program_files(root, args.program_id)` + `load_state` + `write_state` unconditionally. `load_state` fabricates a default state doc for any unknown id and `write_state` persists it, `ensure_program_files` creates the whole dir tree. So `orchestrate.py status --program-id typo-program` silently MATERIALIZES a new empty program (exit 0, no error) instead of erroring on a typo.

**Required behavior:**
- `status` is a READ command. If the program does not already exist, it MUST fail fast with a clear non-zero error (`raise SystemExit("program `<id>` not found; existing: <list>. Use init-program to create it.")`) and MUST NOT create any directory or state file.
- Program existence = the program dir already exists. Use the existing `program_ids(root)` helper (orchestrate.py ~430, lists `kb/programs/*` dirs) or a direct `program_root(root, id).exists()` check. Prefer `program_root(...).is_dir()`.
- Do NOT weaken `init-program` / `set-stage` / any WRITE command — those legitimately create. Only `status` (and ONLY status) gets the read-only guard. Do not touch the create path.
- Keep the `program_file_lock` usage intact for the read.

**Add a test** (e.g. extend `test_program_dashboard_navigation.py` or a new `test_status_no_create.py`): calling the `status` command entry with a non-existent program id raises SystemExit / non-zero AND creates no `kb/programs/<id>/` dir; while `status` on an existing program still works.

Commit: `fix(orchestrate): status on unknown program errors instead of silently creating it`

---

## FIX 3 — `kb next <program>` silently ignores its program arg

**Bug (verified):** `kb next` accepts a positional `program` (kb script ~855, help text literally says "预留 program id ... 当前底层按全局优先级输出"), but `handle_next` (kb ~190) does `del args` and forwards a bare `["next"]` to `orchestrate.py`, ignoring the program entirely. Meanwhile `orchestrate.py next` (~831) only has `--limit`, no program filter — so there is no arg to forward to yet.

**Decision (minimal, honest — pick this, do NOT over-build):** make the ignored arg HONEST rather than silently dropped. Two acceptable options; implement option A:

- **Option A (preferred):** In `handle_next`, if `args.program` is provided, forward it to the orchestrator `next` as a filter. Add an OPTIONAL `--program-id` arg to `orchestrate.py`'s `next` subparser (default None) and have `format_next` / `program_dashboard_items` filter to that program when set (filter the items list by `item["program_id"] == program_id`; if none match, print a clear "no such program / no actions" line, non-zero only if the program truly doesn't exist per Fix 2's helper). Keep global behavior identical when no program is passed.
- If wiring the filter cleanly proves larger than ~40 lines or touches ranking internals you're unsure about: STOP and report — do not hack it. (Fallback option B would be to make `kb next` reject/ignore-with-warning the arg explicitly, but A is preferred.)

**Do NOT** touch the pending/`full_note_status` recommend-next logic — that's a separate design item, out of scope here.

**Add a test:** `kb next <existing-program>` forwards a program filter that reaches orchestrate and narrows output; `kb next` with no arg is unchanged.

Commit: `fix(kb-cli): honor program arg on 'kb next' instead of silently dropping it`

---

## FIX 4 — doc drift: README/USER_GUIDE verb count (docs only)

**Bug (verified):** `README.md` ~97 says `共 9 个` and lists 9 verbs, omitting `ingest` and `reject`. The actual CLI has 11 (the kb script's own `HELP_MENU` already correctly says "11 个" and lists ingest+reject — use it as the source of truth). `docs/USER_GUIDE.md` verb table (~201-209) and the routing line (~318 `kb help/init/doctor/status/next/find/add/review/recall`) are likewise missing ingest+reject.

**Required:**
- README.md ~97: change `共 9 个` → `共 11 个` and add the two missing verbs with descriptions matching `HELP_MENU` in `.agents/skills/kb-cli/scripts/kb` (ingest: "一条命令把 source 拉进来并备好待填骨架，随后 agent 自动填 grounded 笔记"; reject: "把误建 / 不采纳的知识单元标记为 rejected（清理出口）").
- docs/USER_GUIDE.md: add `kb ingest <链接或路径>` and `kb reject <单元 id>` rows to the verb table (~201-209), and update the ~318 routing line to include ingest+reject.
- Match the EXACT wording/verbs from the kb script's `HELP_MENU` so this can't drift again. Do NOT invent capabilities.

**Verify:** the existing `test_skill_docs_cli_drift.py` checks SKILL.md (not README/USER_GUIDE), so it won't catch this — just re-run the full suite to confirm nothing breaks. This fix is purely to stop README/USER_GUIDE lying about the verb set.

Commit: `docs: correct kb verb count/list to 11 (add ingest+reject) in README + USER_GUIDE`

---

## RED LINES (non-negotiable)

- NEVER touch the real `kb/` user data. Tests use `tmp_path` / temp roots only.
- Do NOT weaken any governance/gate/confirmation logic. Fixes 2 and 3 must not alter the confirmation gate, substance gate, or `full_note_status` recommend-next behavior.
- Do NOT `git push`. The maintainer merges. Commit locally only.
- Do NOT add third-party deps (no jieba, no requests, etc.). Stdlib only.
- Small commits: one commit per fix (4 commits). Infra here has had transient 504/stream drops — commit each fix as soon as its tests pass so progress isn't lost.
- After ALL fixes: run `$PY -m pytest .agents/lib/research/tests -q` (the managed-venv `$PY` from STEP 0) and paste the final summary line. Baseline was `287 passed`; after your new tests it should be `287 + N passed`. Report per-fix: what you changed, the new test names, and the pass count delta.
- If any fix doesn't fit as specified, or a test you didn't expect goes red: STOP and report with the diff + failure, do not force it.

## FINAL REPORT FORMAT

For each of the 4 fixes: files changed, one-line diff summary, new test name(s), pass/fail. Then the final full-suite summary line and the 4 commit hashes (`git log --oneline -5`).

