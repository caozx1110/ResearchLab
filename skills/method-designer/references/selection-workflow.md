# Selection workflow

Load only this reference for prepare, verify, human confirmation/rejection, or experiment handoff.

## Prepare

1. 读取 selected idea record/analysis；拒绝未选择或 stale selection。
2. 读取 program state。候选 repo 首选 `active_unit_ids` 中的 repo units；仅当 program 没有附挂 repo 时才能使用 KB-wide fallback，并在 proposal 明示。
3. 冻结 idea substance、program state、candidate corpus、resources、task/preference binding。
4. 建 `candidate_repos`、`proposed_repo_id`、四条空 canonical claim slots、interfaces 与 expanded experiment matrix。兼容 `design` route 仍只是 prepare。
5. Prepare 不写 `selected_repo_id`、不推进 stage、不发 method-selected event。

## Verify

- Runtime Agent 填 `method-repo-selection`、`method-interfaces`、`method-baselines`、`method-risks` 四条 judgement claims。
- Repo-selection claim 必须逐字包含并引用 proposed repo unit；所有 claims 走 shared claim/evidence gate。
- Verify 重算 task/context/catalog/resource/preference，核验 canonical unit、artifact、locator 与 quote。
- 成功只创建 current byte-bound verification receipt 并让 subject 可由 public review 发现；仍不选择 repo。
- Empty claim、缺少 required id、fact/unverified type、fabricated quote、stale bytes 或 verify 后编辑都 fail closed。

## Human decision

- Public review 展示 proposal、claims 与 evidence。
- Confirm-selection 只接受用户当前消息对 current subject 的明确授权；原子写 selected repo、推进到 implementation planning、更新 dependent artifacts 并发一个带 subject/content/claims/verification/confirmation binding 的 event。
- Reject-selection 只关闭同一 review subject，不写 selected repo、不推进 stage、不发 method-selected event。
- 旧 artifact 若在未确认状态已经含 `selected_repo_id`，必须显式迁移，绝不自动提升。

## Transaction and handoff

Prepare/verify/confirm/reject 是独立 exact-target transactions，之后只 checkpoint canonical paths。首次 prepare 失败不能留下空 design directory；已有 design 更新失败保留旧 bytes。只有 current confirmed selection 的 matrix 才能交给 experiment owner。
