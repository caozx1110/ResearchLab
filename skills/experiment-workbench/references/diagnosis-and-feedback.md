# Diagnosis and feedback

Load only this reference for follow-ups, evidence-backed diagnosis, user confirmation, or program phase feedback handoff.

## Follow-ups versus diagnosis

- Follow-up 是 actionable work item，不是结论；优先级、owner 与状态要独立可追踪。
- Diagnosis categories 至少区分 method、implementation、data、evaluation、resource、environment、process、unknown。
- Script 只附加 factual comparison context（recent runs + baseline/milestone anchors），绝不从 facts 生成 diagnosis。

## Diagnosis contract

1. 无 claims 时只写 `awaiting_agent_fill` scaffold；不追加 diagnosis、不改 canonical diagnosis、不发 judgement event。
2. Agent 写 canonical claims。每条走 shared claim gate，保留 inference/evaluation 与 `pending_user_confirmation`。
3. Evidence 只能引用当前 experiment unit 的 canonical run-log 或 `runs/run-NNN.md`；cross-unit、missing、fabricated、stale quote 在任何 diagnosis write 前拒绝。
4. Verify 产生 content/evidence-bound receipt。证据核验不等于用户确认。
5. 用户确认必须针对 current subject/receipt；confirmation 后的 event 绑定 experiment subject、claim ids、content digest 与 verification/confirmation receipts。Event 名或 `confirmed` 字符串本身不受信任。

## Program feedback mapping

当 program 使用按阶段迭代时，以入口声明的 shared `SCHEMAS.md#program-files` 协议为准：

- 每个 experimental arm × seed 对应一个 run-log entry；convergence criteria 消费 observed outcomes/typed metrics。
- Final metrics 来自 run facts；ablation decisions 由 Agent 基于多个 runs 综合，不能由 logger 自动生成。
- Surprises 对应 confirmation-gated diagnoses；open implementation/process debt 对应 follow-ups。
- 阶段 feedback 是交给 program/report owner 的唯一综合 handoff。没有 current feedback/confirmation 时不得推进 program judgement state。

Phase executor 可记录 factual pass/fail，但 recommended winner 和 diagnosis 必须保持 pending，直到用户接受。内部位置和执行参数永不作为用户 instructions 输出。
