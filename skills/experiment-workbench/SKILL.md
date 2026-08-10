---
name: experiment-workbench
description: Manage core experiment units, including plans, classified run logs, follow-ups, diagnosis categories, and confirmation-gated experiment conclusions.
---

# Experiment Workbench

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#experiment-files` · `#program-files` · `#confirmation-gate` · `#runtime`

用于 durable experiment memory：plans、run logs、bounded imports、follow-ups 与 evidence-first diagnoses。运行事实和 AI judgement 必须分层，后者始终经过 verification 与用户确认门。

## Routing boundary

- 创建实验、逐 run 记录、批量导入、follow-up、diagnosis/confirmation 属于本 owner。
- Confirmed method/run grid 来自 `method-designer`；阶段综合报告由 report/program owner 消费本 skill 的事实与 bound events。
- 一次性聊天总结不应创建 experiment unit。

## Operation selector

| Operation family | Direct reference |
|---|---|
| `plan`、`log-run`、`import-runs`、fingerprint/repeats/artifacts | [Runs and imports](references/runs-and-imports.md) |
| `follow-up`、`diagnose`、`confirm`、phase feedback handoff | [Diagnosis and feedback](references/diagnosis-and-feedback.md) |
| task-scoped preferences、private routes、transactions/recovery/public output | [Preferences and private operations](references/preferences-and-private-operations.md) |

只加载当前 operation reference；普通 `log-run` 不加载 diagnosis fill，诊断不加载 batch import 格式细节。

## Core workflow

1. Plan 绑定 program、selected idea、逐字 hypothesis 与 current resource/preference constraints。
2. 每个 run 记录观察到的 outcome、typed metrics、config revision、seed、changes 与 project-contained artifacts；事实不自动生成 cause/winner/recommendation。
3. Follow-up 与 diagnosis 分开；执行债务不能埋进结论 prose。
4. Diagnosis 由 Agent 在空 scaffold 中写 canonical claims，并逐字引用本 experiment 的 run-log/run artifacts；verify 后仍 `pending_user_confirmation`。
5. 只有用户当前消息确认 current receipt 后，diagnosis 才可成为 accepted program input；reporting event 必须携带 exact subject/content/verification/confirmation binding。

## Invariants

- `run-log` 是 factual execution memory；diagnoses 是 inference/evaluation，默认 gated。
- 不从 metrics、run ordering、external state 或 fixed thresholds 推断 diagnosis、significance、winner 或 recommendation。
- Absolute paths 永不成为 durable identity；用户可见输出不泄漏脚本、flags、环境变量、内部路径或续跑指令。
- 私有入口为 `scripts/experiment.py`；runtime Agent 按 operation reference 路由。

## 启动澄清（Agent 用）

- 本轮验证什么假设？必答并逐字绑定 plan。
- 对比哪个 baseline、主指标是什么？默认沿用 confirmed method matrix。
- 预算与 seed 数？默认遵守 current hard resource constraints。
