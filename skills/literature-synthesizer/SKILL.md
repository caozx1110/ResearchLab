---
name: literature-synthesizer
description: 负责跨 paper / repo / dataset / blog / idea 的 evidence-first survey、review、taxonomy 与一等概念单元综合。
---

# Literature Synthesizer

> 协议参考：`.agents/lib/research/SCHEMAS.md#evidence-first-outputs` · `#confirmation-gate` · `#unit-record`

当任务是在多个已入库知识单元之间形成 survey、review、taxonomy、topic map、趋势、gap 或核心概念，而不是分析单个 source 时使用本 skill。

## Routing boundary

- 单个 paper/repo/dataset/blog 深读属于 `unit-analyst`。
- 外部候选发现属于 `literature-search`，正式入库属于 `source-intake`。
- 本 skill 只综合 current、已确认且 evidence/receipt 仍有效的 canonical inputs。

## Operation selector

| Operation | Direct reference |
|---|---|
| `survey/review/taxonomy prepare → fill → verify`、schema、staleness、output | [Survey, review, and taxonomy contract](references/survey-contract.md) |
| `concept prepare → fill → verify` 与 evidence-gap composite | [Concept and composite contract](references/concept-and-composite.md) |

只加载所选 operation 的 reference；普通 survey 不加载 concept/composite 细节，concept 任务不加载七段 survey scaffold。

## Core workflow

1. 记录 mode、filters、caller-supplied `as_of`、可选 program ids 与 task-scoped preference context。
2. `prepare` 只冻结合格 input identity/bytes、创建空 scaffold，并公开 required cells/evidence shape；脚本不写理解。
3. Runtime Agent 阅读冻结的 canonical artifacts，填写所有 required cells，并为每条 claim 挂逐字 evidence refs。
4. `verify` 在 workspace transaction 中重验 input、receipt、preference binding、structure 与每条 quote；任一 stale/tamper 失败且不写正式结果。
5. 成功结果仍是 evidence-verified、`pending_user_confirmation` 的一等 judgement。通过统一 `kb review` 向用户展示；只有 current confirmed 版本可进入正式报告。

## Invariants

- 不从 topic/tag/pool/kind 计数、lexical overlap 或固定模板生成结论、confidence 或 winner。
- 不建 semantic index。选择与理解由 Agent 完成；脚本只做 metadata filter、结构、逐字 evidence 与事务门。
- 每个正式 claim cell 必须有 evidence refs，且 ref 只能在 prepare 冻结的对应 unit artifact 内核验。
- 新 matching unit、上游 record/receipt/evidence 变化或删除会让 consumer binding stale；读侧只报告，不静默刷新或继续消费。
- Preference consumer 固定为 `literature-synthesizer + synthesize`。未选 soft preferences 保持中性，hard constraints 始终生效；artifact 只保存 value-free binding。
- 用户可见输出不暴露脚本、schema、路径、flags 或内部状态。

私有入口为 `scripts/synthesize.py`；runtime Agent 根据 operation reference 选择内部 route。
