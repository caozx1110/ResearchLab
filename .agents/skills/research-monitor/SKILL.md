---
name: research-monitor
description: 维护研究订阅、机械到期事实与冻结运行回执；当用户要求定期追踪新文献、周期复查 survey 或既有结论时使用，实际检索与研究判断仍由 runtime Agent 完成。
---

# Research Monitor

把“以后继续关注”变成可恢复的订阅和 run receipt，而不是只留在聊天记录里。脚本只维护时间、状态、引用、CAS 和恢复；runtime Agent 决定搜什么、使用什么当前可用工具，以及新材料是否值得关注。

## 用户交互

- 用户可以直接说“每两周关注这个方向的新论文”“每月复查这份综述”或“暂停这项跟踪”。不新增公开 `kb` 动词。
- 建立或修改宿主 automation 前必须得到当前用户明确授权。没有 automation 时，订阅仍然有效；到期事实可在下一次 `kb next` 或 Agent 会话中被发现。
- 不安装 daemon、cron、launchd、文件 watcher 或 Obsidian 插件。
- 面向用户只说明订阅目标、周期、是否到期、这轮覆盖范围、停止原因和待选择事项。不得展示内部脚本、参数、payload、绝对路径或运行时状态码。

## Agent 工作流

1. 与用户确认监测目标、周期、时区、范围与硬预算。订阅类型是文献跟踪、survey freshness 或已有 unit 复查之一。
2. 对 finalized create-subscription 请求生成 task-scoped eligible view；runtime Agent 只选择本任务相关 soft preference 来补充尚缺表达。当前用户明确给出的 target/scope/budget 始终优先，脚本不从 preference 选择查询词、研究优先级或扩大预算。私有 apply 携带 selection id；无 receipt 时 soft-neutral。
3. 私下创建 subscription。consumer 重算 request、current program/unit/survey references 与 operation contract，错误或 stale receipt 在写入前拒绝；subscription 只保存 value-free binding。脚本使用带时区 anchor 机械计算 due，不解释研究内容。
4. 到期后创建一个冻结 run。同一过期窗口只创建一次；漏过多个周期合并为一次，不补出一串历史任务。run 同时冻结 current subscription content digest 与 create-subscription preference binding；后续 literature-search 仍针对该 frozen run 独立重选自己的 search preference。
5. 文献跟踪由 Agent 调用 `literature-search`，使用当前实际可用的 search/browser/connector。开始检索前从冻结 run 取得 `run_id + task_digest`，作为 `monitor_binding` 写入 literature stage；完成时同时记录该 stage 的实际字节摘要。survey 复查复用纯读 freshness 结果，再绑定实际读取的 survey bytes；unit recheck 必须列出全部冻结 unit id。
6. Agent 把结果标为新增、重复、矛盾候选、值得复查或无实质变化，写明理由并挂引用。脚本只验证枚举、逐字引用、对象存在和 digest，不判断标注是否正确。
7. 矛盾只生成 candidate。既有 confirmed claim 不得被监测 run 自动改写、撤销或覆盖；需要改变结论时交现有 review/confirmation 流程，由用户拍板。
8. completed run 的每个结果都会继续出现在 `kb next` 的事实候选中，直到写入 `acknowledged / materialized / sent_to_review / dismissed` 之一。新增或值得复查的材料不能只因 run 已完成就从系统消失；materialized 必须绑定当前用户消息授权和实际 canonical unit，矛盾候选只能绑定现有 review 项。
9. planned/running/blocked/failed_retryable run 通过独立 `resume-monitor-run` factual candidate 进入 portfolio；它不会因 due 读取跳过 `active_run_id` 而消失。terminal run 不出现，坏 link fail closed，run/subscription state/revision/content/stop 变化会使旧 portfolio decision stale。
10. completed/cancelled run 不可重开。blocked 与 retryable failure 可恢复；真正新一轮使用下一 anchored due window。
11. 绑定 program 的 completed run 会在同一原子操作中写一条纯 operational/factual reporting event，只说明本轮已完成和 outcome 数量；它不把任何 `new / worth_reviewing / contradiction_candidate` 判断升级为已确认结论。

## 状态与恢复

- subscription 为 `active / paused / completed`。completed 不可恢复为 active；有 active run 时不能直接完成 subscription。
- run 为 `planned / running / blocked / failed_retryable / completed / cancelled`。每次写入携带当前 revision，陈旧写入 fail closed。
- run 冻结创建时的 target、scope digest、budget、cadence、subscription revision/content digest 与 value-free preference binding；后来暂停订阅不得篡改已开始 run。
- run receipt 用 content digest 覆盖其完整 canonical 内容；加载、恢复和完成前都会重验。文献 stage、survey 或 receipt bytes 事后变化会使旧完成绑定失效，而不是继续显示为已验证。
- terminal run 完成后，`next_due_at` 从原 anchor 推到完成时间之后的第一个窗口，而不是从完成时间重新起算。
- 所有业务写入使用精确文件 target、workspace lock、journal、before-image 和原子替换；引用路径必须在 canonical KB 边界内且不得经过 symlink。

## 内部接口

Agent 私下使用 `scripts/monitor.py` 读取一个有界 JSON payload，执行 create-subscription、set-subscription-status、create-due-run、transition-run、finish-run 或 set-outcome-disposition；只读 due 与 unresolved-outcomes 检查也通过同一 helper。该接口不是用户命令，不得原样转发到对话。
