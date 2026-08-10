# Output and quality contract

Load only this reference when validating reporting freshness, presentation preferences, self-contained output, or recovery behavior.

## Judgement and event freshness

- 显式 factual/operational event 可进入普通区。
- decision、diagnosis、discussion conclusion、survey inference、novelty、evaluation 与 unknown/untyped event 都属于 judgement。
- judgement 只有在 subject canonical containment、binding、verification bytes 和 ConfirmationReceipt 全部 current 时进入正式区；pending/rejected/stale 全部进入 `Pending / Unverified judgements`。
- Survey inference 还要通过 consumer binding 的纯读 freshness 检查。新增匹配 unit、上游 bytes/evidence/confirmation 变化或删除时只报告 stale，不自动改写 survey 或继续消费。

## Task-scoped presentation preferences

展示型 operation 的 allowlist 可包含 language preference 与 reporting style。Task digest 由 owner 结合 program、operation、stage、limit 与完整输入快照重算，不能由调用方指定。

- 只有当前 task selection 明确选择英文时才用英文模板；缺失、不可解析或仅 profile 配置英文时仍用默认中文。
- 只有当前 task selection 选择 `concise/brief` 或 `detailed/full` 时改变展示量；未选择时保持 neutral default。
- 精简模式仍必须保留 decisions、claims + evidence、events 与所有适用缺失标记。
- Artifact 只存 selection/task/receipt digests，不复制 preference 原值；偏好不改变输入筛选、claim/evidence、identity 或 confirmation。

## Output safety

- 报告正文是 decisions、claims + evidence、events 的 self-contained triple。
- Evidence 展示 source unit、locator、逐字 quote 与可选 context；空 evidence 使用当前模板语言显式标缺。
- Editorial text 拒绝 raw HTML/LaTeX、绝对机器路径、内部路径、裸 flags、模板变量、空白/未知/重复 refs。
- 不修改 source units、events 或 decision log；报告只读聚合后生成派生产物。
- 用户可见下一步必须是自然语言或公开 `kb <verb>`，不得泄漏私有执行面。

## Transaction and quality gate

- Prepare/verify/publish 各自使用 exact target transaction；render/write/commit 前重验 identity、bytes、receipt、catalog 与 preference binding。
- 失败保留旧成品，不留下半成品、空目录或部分 publication set。
- 最终核对：无需打开本地 artifact 即可理解核心内容；judgement 保留原 epistemic/confirmation 状态；缺失项明确；无 fabricated prose；weekly、PPT 与七节 outline/draft 结构清晰区分。
