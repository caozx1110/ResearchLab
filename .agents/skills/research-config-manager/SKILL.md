---
name: research-config-manager
description: 管理 core 研究系统配置，包括资源画像、语言偏好、taxonomy seed、candidate pool policy 与自动化开关。
---

# Research Config Manager

> 协议参考：`.agents/lib/research/SCHEMAS.md#config-files` · `#ownership` · `#runtime`
>
> 治理边界：本 skill 写入 `kb/config/runtime-preferences.yaml` 与 markdown settings，并向 `knowledge-base-manager` 提交 taxonomy seed / pool policy 输入。`candidate-pools.yaml` 与 `topic-taxonomy.yaml` 的实际结构归 `knowledge-base-manager` 治理。

当任务是在配置 `kb/config/` 下的研究系统行为，而不是直接分析知识单元时，使用这个 skill。

## 负责范围

1. 初始化可读的用户 profile、taxonomy / pool seed catalog 与 runtime preferences；markdown settings 由 workspace bootstrap 保证存在，并通过 `toggle` 更新条目。
2. 捕获资源、约束、偏好，并保持脚本可读。
3. 显式维护 topic / tag taxonomy seed 与 candidate pool policy。
4. 让其他 skills 可以稳定读取统一配置。
5. 管理 `kb` 独立仓库的 versioning 策略，例如 `manual | milestone | aggressive`。
6. 给用户解释 paper intake 的默认模式，并提供可直接复制的配置修改命令。
7. 管理本地可选诊断策略：workspace `off|errors-only|developer`、逐 skill override、任务 token/issue 上限与 dedup/cooldown；`local_only=true` 不可关闭。

## 诊断配置交互

普通用户无需记命令。Agent 接到“开启开发者诊断”“只在出错时记录”“关闭 paper-analyst 诊断”等自然语言请求后，私下写 runtime preference，再用自然语言确认 effective mode。诊断只控制额外记录与复盘，绝不能关闭 evidence、confirmation、schema、containment 或 recovery 门。

- `off`：不自动记录、不做 Agent 复盘；用户明确要求“记下这个问题”时仍记录。
- `errors-only`：只做确定性失败捕获，不调用 LLM。
- `developer`：包含 errors-only，并允许预算内触发式短复盘。
- per-skill `inherit` 跟随 workspace 总模式，其余值覆盖总模式。

D1 无 telemetry、网络上传或自动修改 skill。不要向用户展示 owner 命令、flags、内部路径或 token 计数实现细节。

## 常用命令

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py init
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py show --section all
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py set --key preferences.language_preference --value zh-CN
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py toggle --key 自动生成详细论文笔记 --state off
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py capture-resources --statement "我现在有 8 卡训练资源和人形平台"
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py set-taxonomy-seed --topic retrieval --tag rag --tag grounding --alias retrieval-augmentation
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py set-pool --pool current-reading --topic retrieval --tag rag --description "当前优先阅读池"
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py guide --focus paper-intake
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py set-runtime-pref --section browser --key default_terminal_mode --value codex
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py set-runtime-pref --section paper --key auto_complete_note --value true
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py set-runtime-pref --section versioning --key auto_commit_mode --value milestone
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py set-diagnostics --mode errors-only
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py set-diagnostics --mode developer --token-budget-per-task 2000 --max-issues-per-task 20
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py set-diagnostics --skill paper-analyst --skill-mode off
```
