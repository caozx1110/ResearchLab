---
name: research-config-manager
description: 管理 v2 研究系统配置，包括资源画像、语言偏好、taxonomy seed、candidate pool policy 与自动化开关。
---

# Research Config Manager

当任务是在配置 `kb/config/` 下的研究系统行为，而不是直接分析知识单元时，使用这个 skill。

## 负责范围

1. 初始化可读的用户 profile 与 markdown settings。
2. 捕获资源、约束、偏好，并保持脚本可读。
3. 显式维护 topic / tag taxonomy seed 与 candidate pool policy。
4. 让其他 v2 skills 可以稳定读取统一配置。

## 常用命令

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py init
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py show --section all
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py set --key preferences.language_preference --value zh-CN
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py toggle --key 自动生成详细论文笔记 --state off
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py capture-resources --statement "我现在有 8 卡训练资源和人形平台"
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py set-taxonomy-seed --topic humanoid-robotics --tag vla --tag whole-body-control --alias humanoid
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py set-pool --pool current-reading --topic humanoid-robotics --tag vla --description "当前优先阅读池"
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py set-runtime-pref --section browser --key default_terminal_mode --value codex
```
