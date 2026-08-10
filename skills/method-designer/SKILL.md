---
name: method-designer
description: Turn a selected core idea unit into a per-program method design handoff with repo choice, interfaces, and an expanded experiment matrix.
---

# Method Designer

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#program-files` · `#confirmation-gate` · `#runtime`

只在 idea 已由用户显式选择后，将它转成 per-program method design proposal：候选 repo、接口、baselines/risks 与 experiment matrix。脚本提供结构和 deterministic resource arithmetic；方法判断及逐字 evidence 来自 runtime Agent。

## Routing boundary

- 未选择 idea 时返回 idea selection，不提前设计。
- Method repo proposal、interfaces、baseline/risk claims 与 run-grid proposal 属于本 owner。
- 只有 confirmed run grid 才交给 `experiment-workbench`；本 skill 不记录实验 run 或 diagnosis。

## Operation selector

| Operation | Direct reference |
|---|---|
| `design prepare → verify → confirm-selection/reject-selection` 与 stage handoff | [Selection workflow](references/selection-workflow.md) |
| candidate corpus、resource scaling、canonical claims、preference/evidence boundary | [Resources and claims](references/resource-and-claims.md) |

只按当前 phase 加载所需 reference；查看资源 shape 不需要加载 confirmation 执行细节。

## Core workflow

1. 读取 selected idea、analysis 与 program state；冻结 current task/preference/resource/candidate corpus binding。
2. Prepare 建候选 repo order、`proposed_repo_id`、空的四条 canonical claims、interfaces 和 experiment matrix；不得写 `selected_repo_id` 或推进 stage。
3. Agent 填 repo-selection、interfaces、baselines、risks 四条 judgement claims 及逐字 evidence。
4. Verify 核验 claims/evidence 并建立 current byte-bound receipt；状态仍为 ready for human review，不代表 selection。
5. 只有用户当前消息明确授权时才能 confirm-selection；它原子写 selected repo、推进 stage、更新依赖 artifacts 并产生一个 bound event。Reject 不选择、不推进、不发 selection event。

## Invariants

- Candidate ordering/lexical scoring 只是提案信号，不能升级成方法 verdict。
- `proposed_repo_id` 与 `selected_repo_id` 永远分离；后者在 confirmation 前不得出现在任何 canonical proposal/state 中。
- Soft preferences 只在 current task receipt 中选中时影响方案；resources/constraints 是 hard boundary，不能被偏好或调用方绕过。
- 用户可见回复只解释 proposal、evidence 与 review state，可提供公开 `kb <verb>`；不泄漏私有 routes、flags、路径或环境变量。
- 私有入口为 `scripts/method.py`。

## 启动澄清（Agent 用）

- 目标 program 与已选择 idea 是哪个？未选先返回选择流程。
- 资源边界是否变化？默认读取 current profile resources。
- 候选 repo 有人工倾向吗？默认从 program 附挂 repos 提案。
