# R1 kb next pure-read and capability maturity disclosure

## STEP 0

Start from latest integration HEAD supplied by root. Read AGENTS/SSOT. Verify pure config loaders are present. Never touch a real `kb/`.

## Ownership

- `.agents/skills/research-orchestrator/scripts/orchestrate.py`
- `README.md`
- `docs/USER_GUIDE.md`
- `.agents/lib/research/tests/test_r1_pure_readers.py`
- `.agents/lib/research/tests/test_r1_conversational_release.py`
- one new narrow next/read test if necessary

Do not edit kb CLI dispatcher, source intake, report/experiment, or shared journal.

## Reproduced facts

`/private/tmp/r1_public_next_add_probe.py <repo>` on a freshly installed copy runs `kb next` with exit 0 but creates `.gitignore`, runtime preferences, taxonomy/pools and user navigation files. SSOT requires semantic reads to be byte-identical. SSOT line 59 also requires a public `stable / beta / scaffold / dev-only` capability matrix in README and USER_GUIDE; both currently omit it.

## Required

1. Orchestrator must classify `next` and any dashboard/route command that is semantically read-only before calling `ensure_workspace`; on absent KB it builds defaults in memory and writes nothing. Mutating commands retain explicit transaction-owned seeding.
2. Installed-copy black-box `kb next` on fresh workspace is byte-identical across every file and directory; output stays natural language + supported `kb <verb>` only. Add similar empty-root snapshots for directly exposed read routes affected by the same pre-dispatch bootstrap.
3. Add an honest compact capability maturity matrix to README and USER_GUIDE using SSOT categories: analyzers beta; survey/idea/method/experiment/report scaffold unless evidence proves a higher level; browser/workbench dev-only; core install/recovery/governance may be stable only if accurately scoped. Explicitly say one analyzer's score is not the whole bundle.
4. Release test asserts both docs contain all four maturity labels and representative skill rows, without introducing raw internal commands to USER_GUIDE.

No push. Small commits; targeted + full, diff-check, clean status.
