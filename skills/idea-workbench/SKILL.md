---
name: idea-workbench
description: 负责 core idea unit 的生成、evidence-first analysis、陪练讨论、多候选管理、显式选择与归档。
---

# Idea Workbench

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#config-files` · `#confirmation-gate` · `#runtime`

将研究方向收敛成可评审、可比较、可由用户显式选择的 idea units。理解、novelty/feasibility 判断、counter-example 与建议来自 runtime Agent；脚本只冻结 corpus、建立结构、核验逐字 evidence 和执行事务。

## Routing boundary

- 捕获/批量生成 idea、evidence-first analysis/review、idea 内 reviewer sparring、显式 selection 与 archive 属于本 owner。
- 研究路线讨论的通用归档属于 `discussion-archivist`；只有 discussion subject 明确是某个 idea 的 challenge/probe 时才走本 skill。
- 外部 source 发现/入库属于 literature/source owners；本 skill 只消费 current canonical corpus。

## Operation selector

| Operation family | Direct reference |
|---|---|
| `capture`、`generate prepare → verify`、`analyze/review prepare → verify` | [Generation and analysis](references/generation-and-analysis.md) |
| `discuss/spar prepare → verify → confirm/reject`、`select/select-best` | [Discussion and selection](references/discussion-and-selection.md) |
| private routes、scaffold ownership、preference/recovery/output boundary、archive | [Private operations](references/private-operations.md) |

只加载当前 operation 的 reference；普通 capture/generate 不加载 sparring schema，analysis 不加载 selection/archive 执行细节。

## Core workflow

1. 冻结用户逐字题目、orientation、current canonical evidence corpus 与 task-scoped preference binding。
2. Prepare 只创建空候选或空 judgement claims；Agent 填 substance 和 evidence refs。
3. Verify 重算 request/orientation/corpus/preference，核验所有 source unit、artifact、locator 与逐字 quote；任一失败零正式 judgement/candidate 写入。
4. Evidence verification 只证明 grounded；所有 novelty、feasibility、recommendation、discussion conclusion 与 selection 仍为 `pending_user_confirmation`。
5. 只有当前消息的显式用户授权才能确认一个 current selection/conclusion；多轮 history 互不覆盖。

## Invariants

- 不从字段数、链接数、lexical overlap、固定阈值或旧 heuristic score 生成 verdict/winner。
- Retrieval 使用 Agent 原生能力；本 skill 不建 semantic index。
- Preference 不能覆盖当前用户明确题目/scope/资源边界，也不能削弱 evidence、confirmation 或 recovery。
- 用户可见输出只含自然语言与公开 `kb <verb>`；不暴露私有脚本、flags、路径或 scaffold 参数。
- 私有入口为 `scripts/idea.py`；runtime Agent 按 operation reference 选择 route。

## 启动澄清（Agent 用）

- 目标：捕获、批量生成、分析还是陪练讨论？默认按用户措辞。
- 挑战强度：温和梳理还是 reviewer 式挑战？默认中等。
- 证据只用当前冻结 corpus？默认是；不足先说明再扩语料。
