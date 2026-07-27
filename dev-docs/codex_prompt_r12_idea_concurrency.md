# R12 idea authoring concurrency + lossless prepare handoff

## STEP 0 — base sync

Work only in the worktree and branch named in the agent task. Verify HEAD equals the supplied maintainer base and that the files below exist. If not exact, stop and report; do not reset or edit another worktree.

## Objective

Close the cold-acceptance P2 where `prepare all → Agent fill all → verify all` for multiple ideas fails because every regular file under `kb/units` is treated as a global byte lock, and a retrying prepare overwrites a nonempty Agent fill.

## File ownership

Only modify:

- `.agents/skills/idea-workbench/scripts/idea.py`
- `.agents/lib/research/tests/test_idea_evidence_analysis.py`
- if needed, one additional existing idea-workbench test file under `.agents/lib/research/tests/`

Do not modify SSOT/SCHEMAS/docs/version/installer, any other skill, or any real `kb/`.

## Locked design

1. A frozen corpus is an allowlisted pre-authoring artifact manifest, not a lock on every later byte anywhere in `kb/units`.
2. Never include Agent authoring control artifacts such as `*-fill.yaml`, `*-orientation.yaml`, or `*-evidence-corpus.yaml` in the corpus, for the current or any other unit.
3. At verify, validate the frozen manifest's schema/digests, then for every evidence ref actually used by the fill require: canonical source unit/path; entry existed in the frozen manifest; current regular-file identity and bytes exactly equal the frozen entry; current verbatim evidence verification passes. Newly created artifacts cannot be cited. A referenced artifact mutation/replacement/symlink must fail closed.
4. Unreferenced artifact changes, new units, other idea prepares, and other idea verifies do not stale the current task. The immutable orientation, current target record, task preference receipt, actual fill, and cited artifacts remain exact write-boundary inputs.
5. Re-running prepare when an existing fill contains any Agent-authored change must reject before changing the target record, fill, orientation, or corpus. Preserve bytes exactly and give a natural recovery message. Exact empty scaffold retry may be no-op; an unfilled scaffold may be safely refreshed without losing content.
6. Apply the shared contract consistently to generate/analyze/review/discuss. Do not weaken evidence, preference, containment, transaction, confirmation, or recovery gates. Scripts validate/transport; they do not author research judgement.
7. Public UX remains natural language + `kb` verbs only, no raw commands/flags/internal paths/digests/TTY requirement.

## Permanent tests

- Three real ideas: prepare all, fill all with valid evidence, verify all. Run twice from fresh temp workspaces. All succeed; unrelated task control files never enter manifests.
- Mutate or replace one actually cited frozen artifact after prepare: corresponding verify rejects with zero canonical result write. Symlink/unsafe replacement rejects.
- Add a new artifact after prepare and cite it: reject because absent from frozen manifest.
- Change/add only unreferenced artifacts or complete another idea: current verify still succeeds.
- After writing a nonempty Agent fill, rerun prepare: nonzero rejection and exact byte preservation of record/fill/orientation/corpus. Cover at least analyze and one other shared phase; generation too if its prepare path differs.
- Empty-scaffold repeated prepare is idempotent or safely refreshed and remains verifiable.
- Frozen manifest tampering, duplicate paths, malformed entries, bad digest/order/unsafe path fail closed.

## Verification

Run focused idea tests, adjacent preference/recovery tests, Python 3.9-compatible compileall for changed Python, and `git diff --check`. Do not push. Commit implementation/tests in small commits and report hashes and exact counts.

## STOP and report

If current preference context cannot represent a frozen manifest without comparing the entire live KB, or a safe lossless retry requires a schema change outside scope, stop and identify the exact missing contract. Do not retain global serialization as a hidden workaround and do not overwrite fills.
