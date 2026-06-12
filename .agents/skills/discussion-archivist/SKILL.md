---
name: discussion-archivist
description: Archive important technical route discussions into durable program notes under `kb/programs/<program-id>/discussions/`, including conclusions, tradeoffs, open questions, and next validation actions.
---

# Discussion Archivist

> 协议参考：`.agents/lib/research/SCHEMAS.md#program-files` · `#ownership`

Use this skill when an important research discussion should become a durable note instead of staying only in chat. 产出落在 `kb/programs/<program-id>/discussions/<slug>.md`。

## 与 decision-log 的边界

- **写到 `decision-log.md`（由 `research-orchestrator` 维护）**：单点、明确的"我们决定 X"，需要 stage 迁移、citation evidence、alternatives 一并落下。决策本身是事实，理由可能是 AI 推断（仍 pending）。
- **写到 `discussions/<slug>.md`（本 skill）**：讨论过程比结论更值得保存 —— 多个 tradeoff、还没拍板的分歧、暂时挂起的 open question、需要后续 evidence 才能闭合的路线。常见场景：研讨结束但未决议、用户主导的研究方向辩论、要给协作者看的"我们当时怎么权衡的"。

二者经常成对出现：先 `archive` 保存讨论过程，等用户拍板后再 `research-orchestrator log-decision` 引用本讨论笔记的 path 作为 evidence。

## 必填要素

`title`、`summary`、至少一项 `--tradeoff` 或 `--open-question`；`--decision` 留空时会自动写入"待确认"以示尚未拍板。

## 上下游

- 上游：聊天里发生的重要技术讨论；或来自 `research-orchestrator open-questions.yaml` 的待决问题
- 下游：`research-orchestrator log-decision`（拍板时引用本笔记）、`report-author`（周报里引用未决讨论）

## 命令

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/discussion-archivist/scripts/archive.py archive \
  --program-id physics-aware-fb-z-space \
  --title "是否在 Phase 2 保留 latent interface" \
  --summary "Phase 1 已收敛 motion token；下一步是直接接 controller 还是先暴露 latent interface。" \
  --tradeoff "保留 latent interface 增加 VLA 接入面，但延后 controller 实验" \
  --tradeoff "直接 controller-only 更快验证 tracking，但 VLA 集成会回头返工" \
  --open-question "Latent interface 接 controller 的 sim2real 损失能否容忍" \
  --next-action "用一周 lite-smoke 实测两条路径在 tracking RMSE 上的差距"
```
