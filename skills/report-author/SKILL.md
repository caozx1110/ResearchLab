---
name: report-author
description: Generate self-contained weekly reports, stage summaries, PPT or writing materials, and evidence-backed paper outlines from program claims, events, evidence, and decisions.
---

# Report Author

> 协议参考：`.agents/lib/research/SCHEMAS.md#program-files` · `#experiment-files` · `#evidence-first-outputs` · `#ownership` · `#runtime`

将 program 的 current confirmed claims、逐字 evidence、reporting events 与 decisions 聚合为可独立阅读的报告材料。脚本只冻结输入、建立结构、核验引用与原子发布；叙事、取舍和综合由 runtime Agent 完成。

## Routing boundary

- 周报、阶段总结、PPT、写作材料、论文 outline/BibTeX/七节初稿属于本 owner。
- 上游 source 理解属于 unit owner；实验事实与 diagnosis 属于 `experiment-workbench`。
- 新自然语言周报/PPT 必须走 editorial prepare → Agent fill → verify，不把机械 aggregate 当成成品。

## Operation selector

| Operation family | Direct reference |
|---|---|
| `weekly`、`stage-summary`、`ppt-materials`、`writing-materials`、`outline`、`bib` 及 editorial variants | [Reporting workflows](references/reporting-workflows.md) |
| `draft-prepare → draft-verify → draft-export` 与逐节确认 | [Paper draft contract](references/paper-draft-contract.md) |
| self-contained output、judgement/event freshness、偏好、quality/recovery boundary | [Output and quality contract](references/output-and-quality.md) |

只按当前 operation 加载对应 reference；普通周报/PPT 不加载初稿七节合同，BibTeX 导出不加载 editorial fill 细节。

## Core workflow

1. 冻结 program state、events、decisions、关联 unit、claims/evidence/receipts、figures 与 task-scoped preference binding。
2. 只允许 current `confirmed` / `auto_confirmed` claim 进入正式输入；pending、rejected、stale 或不能解析 binding 的 judgement 进入明确隔离区。
3. Agent 在 owner 提供的空结构中写 self-contained 正文并引用冻结 catalog；缺少输入时写明确 `缺少：X`，禁止补写或猜测。
4. verify 在 render/write/commit boundary 重验全部 bytes、identity、receipt、evidence、preference 和 figure binding；任一漂移不得覆盖旧成品。
5. 需要人类判断的初稿 section 通过统一 `kb review` 逐节确认；只有所有 current confirmation 都有效时原子发布。

## Invariants

- 报告必须携带核心 claim、逐字 evidence、events 和 decisions；不能要求读者打开本地 artifact 才能理解。
- editorial prose 只来自 Agent fill；脚本不得从 event log、字段数、模板或 lexical signals 生成结论。
- 默认中文；只有当前 task receipt 选中的语言/展示偏好才改变呈现，绝不改变输入、epistemic type、确认门或缺失标记。
- 用户可见输出只含自然语言与已存在的 `kb <verb>`；不泄漏脚本、flags、内部路径、schema 或续跑参数。
- 私有入口为 `scripts/report.py`；由 runtime Agent 按 operation reference 路由。

## 启动澄清（Agent 用）

- 读者与场合：导师周会、合作者还是自存档？默认导师周会。
- 周期与 stage 范围？默认最近一周、全部 stage。
- 体裁：周报、阶段总结、PPT、outline 还是初稿？默认按用户措辞。
