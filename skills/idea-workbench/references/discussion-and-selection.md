# Discussion and selection

Load only this reference for idea-specific sparring, conclusion confirmation/rejection, or explicit idea selection.

## Idea sparring

`discuss`（别名 `spar`）使用 prepare → verify → confirm/reject：

1. Prepare 建一个空 conclusion，含 `challenge`、`probe`、`counter-example`、`constructive-suggestion` 与 `conclusion` 五条 judgement claims。
2. Agent 填 reviewer、总结 conclusion、五条 claims 及每条的 KB 逐字 evidence。Canonical conclusion claim text 必须与 summary conclusion 完全一致。
3. Verify 对每个 ref 在其 canonical `source_unit_id` artifact 中核验。Cross-unit 引用允许，但 quote 必须逐字存在于声明的 source artifact。
4. 每轮 verify 向 discussion judgements 追加独立 `idea_discussion_conclusion` subject，包含 canonical `payload.claims + payload.verification`；nested conclusion 只是人类可读 projection。
5. Confirm/reject 只作用于指定 conclusion 的 current receipt；多轮 spar 不覆盖既有 history 或已确认 analysis/review claims。

每条 discussion claim 使用 shared claim/evidence shape：稳定 id/role、Agent-authored text、`inference|evaluation`、`pending_user_confirmation` 与至少一个 source unit/artifact/locator/quote。`verified_at` 或 `evidence_verified` 只说明证据核验，不是用户确认。

## Selection

- `select` 只提议明确 idea；`select-best` 只消费 current review rank/canonical evidence，不运行 heuristic winner 规则。
- 两者都先生成 current `pending_user_confirmation` selection subject，不得由脚本自签 confirmed。
- 只有用户当前消息明确选择并且 content/evidence/preference/receipt 都 current 时才能 apply confirmation。
- Rejection 关闭同一 review subject，不选择 idea、不改 program stage，也不覆盖其它候选。
- Selection confirmation 必须绑定 canonical idea identity、content digest、evidence/verification receipt 与当前 task context。

## Routing distinction

Idea sparring 解决一个 canonical idea 的 challenge/probe；“归档研究路线讨论”仍属于 `discussion-archivist`。组合请求由 orchestrator 按意图有序路由，不能因出现“讨论/discussion”就吞掉明确的 meta-workflow owner。
