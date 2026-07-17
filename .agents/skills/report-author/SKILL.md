---
name: report-author
description: Generate self-contained weekly reports, stage summaries, PPT or writing materials, and evidence-backed paper outlines from program claims, events, evidence, and decisions.
---

# Report Author

> 协议参考：`.agents/lib/research/SCHEMAS.md#program-files` · `#experiment-files` · `#ownership` · `#runtime`

把 program 的已确认 claims、逐字 evidence、reporting events 与 decisions 聚合成可独立阅读的报告材料。脚本只解析、聚合和校验结构；叙事、取舍与综合仍由 runtime agent 完成。

## 适用场景

- 周报、阶段总结、PPT 素材、写作素材。
- 论文提纲：本 skill 拥有 `outline` verb，不另建 paper-outline skill。
- 面向导师或合作者的报告必须脱离本地对话和知识库导航也能理解。

## Agent Workflow

1. 读取 program 的 `state.yaml`、`workflow/reporting-events.yaml` 与 `workflow/decision-log.md`。
2. 从 `state.active_unit_ids`、event 的 `unit_id` / `*_ids` 字段及 unit artifact 引用收集关联 unit；只做 exact record lookup，不做模糊猜测。
3. 对每个 record 的 `payload.claims` 调用 `research.evidence.read_claims`；仅聚合 `confirmed` / `auto_confirmed` claims，并用 `validate_claims` 过结构门。
4. 将 claim 文本与 evidence ref 的 `source_unit_id`、`locator`、逐字 `quote`、可选 `summary` 一起写入材料；不把 essential evidence 留给读者自行打开。
5. 聚合固定 H2 decision blocks 与筛选后的 events。最终叙事由 agent 基于这些输入填写，不允许脚本生成判断。
6. 任一输入缺失时保留明确的 `missing: X`；禁止静默省略、补写或推测。
7. 只读加载 `kb/config/user-profile.yaml` 的自由文本 `reporting_style`：包含“简洁”/`concise`/`brief` 时压缩 decisions、claims 与 events 的展示量；包含“详细”/`detailed`/`full` 时保留完整输入；缺失、不可解析或无匹配信号时维持原默认行为。精简模式仍保留 decisions、claims + evidence、events 三部分及全部适用的 `missing:` 标记。

## Internal Verbs

- `weekly`：生成包含 decisions、confirmed claims + evidence、reporting events 的周报底稿。
- `stage-summary`：按 stage 筛选 events，同时保留关联 claims、evidence 与 decisions。
- `ppt-materials`：生成 evidence-backed slide inputs，而不是 event dump。
- `writing-materials`：生成真实的 Writing Claims & Evidence 与 program context。
- `outline`：生成 Introduction / Related Work / Method / Experiments / Results / Discussion / Conclusion 骨架；Related Work 必须携带 confirmed claims + evidence。

这些 verbs 由 agent 内部执行。用户只需用自然语言提出报告需求；用户可见回复不得包含脚本路径、裸命令、flags、变量占位符或内部 next-step 指令。

## Output Contract

- 报告正文按 decisions、claims + evidence、events 组成 self-contained triple，不再以 event log 充当报告。
- `reporting_style` 只控制展示量，不改变 claim confirmation status、不删除适用的缺失标记，也不生成补全文本。
- confirmed claim 的最小结构为 `id`、`text`、`claim_type`、`confirmation_status`、`evidence_refs`。
- evidence ref 展示来源 unit、locator、逐字 quote 与可选 context；空 evidence 显式写 `missing: evidence for claim ...`。
- 无 events、decisions、confirmed claims、关联 record 或 outline section inputs 时分别写 `missing: ...`。
- 不输出 raw commands 或内部路径作为用户下一步；需要推进时改写成自然语言或已存在的 `kb <verb>`。
- 不修改 source units、reporting events 或 decision log；报告是只读聚合后的派生产物。

## Quality Gate

- 核对报告无需打开本地 artifact 即可理解核心 claim、证据、事件和决策。
- 核对 judgement 仍保留原 epistemic type 与 confirmation status。
- 核对缺失项明确、无 fabricated prose、无 raw command 泄漏。
- 最终提交前由 agent 把结构化底稿改写为自然、紧凑、面向目标读者的叙事。
