---
name: research-config-manager
description: 管理 core 研究系统配置，包括资源画像、语言偏好、taxonomy seed、candidate pool policy 与自动化开关。
---

# Research Config Manager

偏好合同：本 owner 是 canonical preference fact owner，因此不消费自己的 soft profile；eligible catalog 为空。它只为真实下游 consumer 生成 task-scoped view/receipt。

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
8. 为具体任务生成分层偏好视图：本 skill 保持总偏好唯一事实源，规则只筛出目标 skill/operation 有资格看到的字段，runtime Agent 再选择本次真正相关的子集并记录理由。

## 分层偏好分发

不要给每个 skill 复制一份用户画像。执行需要个性化的任务时：

1. 私下读取目标 skill/operation 的 eligible view；它只是最小披露 allowlist，不代表每项都与本任务相关。
2. Agent 结合当前任务选择 relevant subset；每个 selected 项写明如何影响本次工作，每个未选 soft 项写明为何无关。hard 项必须保留，且任何偏好都不能关闭 evidence、confirmation、containment、journal、lock、CAS 或 recovery。
3. 保存 effective-selection receipt。回执只持久化 preference ID、value digest、理由和 task-context digest，不复制偏好正文、用户原话、secret 或绝对路径。
4. consumer 按 `selection_id + skill + operation` 加载；总偏好变化会使旧回执 stale，必须重新选择。不得把一个 skill 的回执转给另一个 skill，也不得把 planning 偏好当成用户对研究判断的确认。

推断出的偏好必须先经过现有 learning review/promotion；pending 或 dismissed learning 不进入 eligible view。规则决定“能不能给”，Agent 决定“这次要不要用”。

## 渐进式首次配置

`kb init` 先完成可立即使用的 KB 结构，再由 Agent 提供“现在设置”（推荐）或“先跳过”。选择先跳过后不追加或覆盖任何偏好（不产生额外偏好写入），不写 sentinel，不把 Agent 名称当署名，也不制造确认记录；后续用户说“补充我的研究偏好”或再次使用 `kb init` 时继续即可。

用户选择现在设置时，只在一个紧凑回合收集四类高价值信息：真实署名、语言与术语风格、研究方向、资源与重要约束。显示当前版本记录节奏与论文自动初筛值，并允许用户回答“默认即可”。报告风格、协作边界、开发者诊断等低频项按需渐进补充，不塞进首次问卷。

Agent 必须遵循 init private protocol 的逐字段 input mapping，不自行选择 dotted key。I1 的自然语言资源保存到 profile 顶层 `resources.quick_setup`，保留 `resources` 下已有键，让 method design 等既有消费者可直接读取；重要约束追加并去重到顶层 `constraints` 列表，不覆盖已有项。研究方向与术语风格继续写 canonical personalization 字段；旧 alternate/persona resource 路径只兼容读取或旧调用，不作为新快速设置写入目标。

真实署名只在应用第一次 judgement confirmation 前强制。若此前跳过，Agent 在用户选择确认后先自然语言询问，再只更新署名字段并保留所有其他配置；AI 名称和伪确认仍必须拒绝。所有写入由 Agent 私下复用现有 headless 能力，不向用户展示内部参数或路径。

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

## 启动澄清（Agent 用）

- 现在设置还是先跳过？默认可跳过，不阻塞入库与检索。
- 这是长期偏好还是仅本次任务生效？默认仅本次；长期偏好经确认后落 profile。
