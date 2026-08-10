# Reporting workflows

Load only this reference for aggregate, editorial weekly/PPT, stage, writing, outline, or bibliography operations.

## Input assembly

1. 读取 program `state.yaml`、reporting events 与 decision log。
2. 从 `state.active_unit_ids`、event 的 `unit_id` / `*_ids` 和 artifact 引用做 exact record lookup；不做模糊猜测。
3. 对 record claims 运行 shared evidence reader/validator，只聚合 current confirmed/auto-confirmed claims。
4. 每条 claim 同时携带 source unit、locator、逐字 quote 与可选 context/summary；不把 essential evidence 留给读者自行查找。
5. 固定 H2 decision blocks 与筛选后的 events 一并冻结。没有 events、decisions、claims、records 或 outline inputs 时分别保留明确缺失标记。

## Internal operation catalog

- `weekly`：兼容机械 aggregate；新的自然语言周报默认走 `weekly-prepare → weekly-verify`。
- `stage-summary`：按 stage 筛 events，同时保留关联 claims/evidence/decisions。
- `ppt-materials`：兼容机械 aggregate；新的自然语言 PPT 默认走 `ppt-prepare → ppt-verify`。
- `writing-materials`：输出真实 Writing Claims & Evidence 与 program context。
- `outline`：建立 Introduction / Related Work / Method / Experiments / Results / Discussion / Conclusion；Related Work 必须有 confirmed claims 与 evidence。
- `bib`：从当前 program 的 canonical paper citation metadata 导出去重、稳定 key、确定性排序的 BibTeX；只搬事实，不接受 raw BibTeX。
- `weekly-prepare / weekly-verify`：冻结 current catalog、提供四区空 fill、校验 Agent narrative refs 后发布。
- `ppt-prepare / ppt-verify`：冻结 current catalog、提供独立 slide-card fill、核验单页结论/evidence/figures/notes/transitions 后发布。

以上 routes 都是 Agent 私有入口。一次自然语言请求中自动完成 prepare、填写与 verify；只在缺少可引用输入或确需用户选择读者/范围时暂停，不把内部位置或参数交给用户。

内部周报最小形态为 `weekly-prepare --program-id <program>`，只在 `reports/editorial/weekly/fill.yaml` 中填写四区 `text` / `refs`，再走 `weekly-verify --program-id <program>`；整条链在同一自然语言任务内完成。

## Weekly editorial contract

- 固定四区：本周摘要、进展、问题与风险、下周计划。
- 每条 Agent 正文带预设 epistemic label，并至少引用一个 frozen support ref。
- pending/stale 输入只能作为“问题与风险”的显式 risk hint，不得冒充 formal support。
- fill 只允许修改四区的 `text` / `refs`；identity、label、status 和 catalog 都由 owner 管理。
- 成品含四区与完整证据附录，不暴露 catalog ref、schema、receipt 或内部 claim/event 术语。

## PPT editorial contract

- 1–12 张独立 slide cards；每页恰一条 Agent 结论、至少一条 evidence ref、speaker note 与 transition。
- 可引用 current figure catalog；catalog 非空时整套至少使用一张，catalog 为空时明确说明缺图。
- PPT 不复用周报段落或 outline 七节 scaffold。
- 每页结论、evidence、figure、讲述与过渡都由 verify 校验后再渲染。

## Editorial manifest

Manifest exact 绑定 program state/events bytes、current claims/evidence/receipts、confirmed decisions、figure index/assets 和 task-bound presentation preference。prepare 可保留仍绑定 current manifest 的 fill；verify 在最终事务边界聚合重验，任何 stale/tamper 都不得覆盖旧成品。
