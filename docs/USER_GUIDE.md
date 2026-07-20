# 用户指南

这套 workspace 帮你把论文、代码仓、技术文章、想法、实验和汇报，从聊天里的临时内容变成可复用、可检索、可确认的本地知识。

它不是预装好的知识库。安装后，能力包与研究数据分开保存。AI 负责提取、整理、追踪和汇总；你负责判断、确认和拍板。

当前候选版本是 **`0.2.0-rc.1`**。它已通过完整本地测试套件和冷启动安装副本验收，达到项目定义的本地 release-candidate 质量；但它不是 stable 或 GA，也尚未 tag/publish。正式打发布 tag 前，仍须让 hosted Linux/macOS CI matrix 全绿；当前不承诺兼容性或响应时限 SLA。

## 能力成熟度（按组件）

这里的等级只描述某个组件的当前边界，不代表整个 bundle 已稳定：

- **stable**：所列基础设施合同已有确定性的发布测试；
- **beta**：主流程真实可用，但仍依赖 Agent 判断或来源材料质量；
- **scaffold**：持久化和治理骨架已存在，研究内容质量仍在加固；
- **dev-only**：只作为本地开发能力，不承诺为正式用户入口。

| Skill | 成熟度 | 当前边界 |
|---|---|---|
| `kb-cli` | stable | 十五个动词的路由、自然语言输出过滤和恢复入口。 |
| `knowledge-base-manager` | stable | 数据规范、证据、确认、精确恢复和索引治理；不负责理解研究材料。 |
| `source-intake` | beta | 异构来源的暂存、去重、原始材料留存和可重试失败。 |
| `paper-analyst` | beta | 带证据的准备与验证是真实流程；实质阅读由 Agent 完成。 |
| `repo-analyst` | beta | 能力地图准备与代码证据验证是真实流程；代码理解由 Agent 完成。 |
| `blog-analyst` | beta | 文章准备与观点证据验证是真实流程；解释和可信度判断由 Agent 完成。 |
| `research-config-manager` | beta | 偏好与策略可以持久化，但尚非所有偏好都被所有下游能力消费。 |
| `discussion-archivist` | beta | 按结论保存讨论、证据和开放问题。 |
| `research-orchestrator` | scaffold | 研究计划主线、路由、看板和事件流已存在，优先级仍以固定策略为主。 |
| `literature-synthesizer` | beta | 综述、分类、趋势、矛盾与空白会形成有证据的持久产物；综合质量仍依赖 Agent 与来源覆盖。 |
| `idea-workbench` | beta | 候选、evidence-first 评审、讨论和显式选择已实现；创新性判断仍需用户或专家拍板。 |
| `method-designer` | beta | 基于仓库证据的方法交接和实验矩阵已实现；生成设计仍需专家复核。 |
| `experiment-workbench` | beta | 强类型计划、运行记录、follow-up 和确认门控诊断已实现；诊断质量仍依赖 Agent。 |
| `report-author` | beta | 报告与大纲会消费持久 claim、event、evidence 和 decision；成文质量与覆盖仍需复核。 |
| `skill-evolution-advisor` | scaffold | 本地学习与诊断问题的记录、复核已存在，不承诺自动修改 skill。 |
| `wiki-adapter` | scaffold | 仅提供轻量兼容与路由，不是独立分析引擎。 |
| `research-navigator` | dev-only | 本地浏览工作台仍是开发能力；自然语言导航摘要属于 beta。 |

某个组件的一次成功运行，只能说明对应流程的表现，不能外推到其他流程或整个 bundle。上面范围受限的 **stable** 组件，也不代表当前 release candidate 已成为稳定发布。

## 第一次使用

先按[安装指南](INSTALL.md)完成一次性安装，然后在 Codex 或 Claude Code 的对话中输入：

```text
kb init
```

初始化会创建本地知识库骨架，并由 Agent 在对话中询问缺少的姓名、语言或研究偏好。它不会要求你进入脚本内的交互界面，也不依赖终端是不是 TTY。

一次性安装是普通用户唯一需要接触的技术 bootstrap；管理员也可以用自动化完成同一 bootstrap。安装完成后，日常使用只需要自然语言和下文十五个 `kb <verb>` 伪 CLI 快捷入口；内部 flags、scripts、环境变量和 paths 都由 Agent 私下处理，不是用户操作步骤。

之后可以输入：

```text
kb status
```

或者直接说：

```text
请读取当前知识库，判断我现在最该做哪一步；安全步骤直接继续，需要我确认或选择时再停下来。
```

## 你与 AI 的边界

AI 适合自动完成：

1. 提取论文、仓库和文章的事实 metadata；
2. 去重、建立索引和搜索本地知识单元；
3. 从受保护的原始材料与派生证据填写带逐字证据的分析；
4. 跟踪 program open question、实验 follow-up 和待确认判断；
5. 生成导航、周报素材和可复开的 durable artifacts；
6. 在中断后按 operation journal 恢复，或按精确路径建立 KB checkpoint。

以下内容必须由你拍板：

1. 是否接受 AI 的 inference、evaluation、novelty judgement 或 failure diagnosis；
2. 推进哪个 idea、baseline 或 ablation；
3. 实验结论是否成立；
4. 研究阶段何时推进；
5. 出现矛盾证据时采用哪种解释。

确认不是一句可永久复用的授权。Agent 必须在真正写入时验证当前用户消息中的授权，并把它与当前内容和 evidence 绑定。内容或 evidence 改变后，旧确认自动失效；Agent 会先按最新材料重新核验，再把更新后的判断交给你确认，不会要求你处理内部状态或命令。AI 不能给自己签字。

## 加入和理解资料

你可以直接发链接或本地文件并说明目标：

```text
请把这篇论文入库，完成有证据的核心笔记，再告诉我它是否值得细读。
```

```text
把这个 GitHub repo 变成知识单元，梳理能力边界、训练与推理入口，以及它能否复用。
```

```text
入库这篇技术文章，总结关键观点，并把可信度判断单独标出来让我确认。
```

Agent 会连续完成安全步骤：轻量入库、准备填充结构、阅读派生证据、填写带 locator 的逐字引用、验证内容，以及可用时的安全刷新。脚本只搬运、建结构和验证；对材料的理解由 Agent 完成。

当资料仍在等待 Agent 填写、等待验证，或处于可重试失败时，它不会进入你的确认收件箱。只有实质内容和 evidence 已过门的判断才会由 `kb review` 提请你决定。

## 十五个 `kb` 伪 CLI 动词

这是完整的公开快捷入口。你可以在对话里说，也可以在已安装快捷入口的终端里运行。两种方式的语义一致。

| 你说或运行 | 用途 |
|---|---|
| `kb help` | 查看能力菜单和例子。 |
| `kb init` | 初始化知识库，并在对话中补齐基础偏好。 |
| `kb doctor` | 检查本地运行环境是否能支持当前 workspace。 |
| `kb update` | 检查更新；只有你明确同意后才应用。 |
| `kb add <链接或路径>` | 轻量加入论文、代码仓、文章或本地文件。 |
| `kb ingest <链接或路径>` | 加入资料并准备有证据的深读流程。 |
| `kb review` | 查看已准备好的人类判断项，并用自然语言确认或拒绝。 |
| `kb status` | 刷新并查看当前 KB 或研究计划状态。 |
| `kb next` | 查看当前最值得推进的下一步。 |
| `kb find <关键词>` | 搜索已入库知识单元。 |
| `kb recall` | 回忆已确认习惯、已知坑和待审 skill 问题。 |
| `kb resume` | 恢复中断的知识库操作。 |
| `kb undo` | 撤销最近一次已提交的知识库操作。 |
| `kb restore <操作编号>` | 恢复到指定操作之前。 |
| `kb reject <单元编号>` | 拒绝误建或不采用的知识单元。 |

`kb` 的用户输出只应包含自然语言和这些动词。内部脚本、参数、环境配置、绝对路径和 Agent 协议都不会要求你阅读或复制。`kb init` 与 `kb review` 在终端、pipe 和 Agent 调用中行为相同，也不会从标准输入提问。

Idea 与报告不需要额外动词，直接自然语言描述即可：

```text
请基于当前知识库给我 3 个候选 idea，分别说明证据、新意风险和最小验证路径。
```

```text
为这个研究计划生成本周周报材料，明确区分已确认结论和待确认判断。
```

## 确认收件箱

可以这样开始：

```text
kb review
```

Agent 会优先呈现最值得看的少数判断，以及为什么现在需要你看。你可以自然语言回复：

```text
我确认第一条论文筛选判断。依据是它的实验设置与我们当前问题一致。
```

```text
拒绝这个 repo 复用判断；它的训练接口不支持我们的数据流。
```

Paper、repo 和 blog 使用同一套 review readiness 规则。事实型 metadata 可以轻量确认；判断型内容必须有实质分析和 evidence。每次确认都会保存确认人、当前授权来源、evidence，以及内容版本摘要。

## 检索、综述与陪练

```text
在知识库里找和 retrieval-augmented generation 相关的 paper、repo 和 idea。
```

```text
请基于当前已入库资料，为这个方向生成方法分类、趋势、矛盾证据和空白点。
```

```text
和我陪练这个 idea：逐条挑战它的 novelty、可行性与最小实验，并把形成的结论持久化。
```

临时阅读问题可以只在对话里回答；需要复用的综述、讨论结论或 outline 才落成 durable artifact。所有判断都要回链到知识单元和短 evidence，不能把 inference 写成 source fact。

## 实验与报告

```text
记录一次实验：baseline 无检索，perplexity=5.23，pass@1=0.42。
```

```text
诊断这次实验为什么效果不好，区分 likely causes、ruled out 和 unknowns。
```

Run log 是事实；diagnosis 是推断，默认待确认。报告系统从 program events、confirmed artifacts 和明确标注的 pending material 汇总，不会把未确认判断伪装成定论。

## 恢复、撤销与版本

知识库写入采用原子写、revision/CAS、operation journal 和精确范围锁。多文件操作在开始前声明目标集合；恢复与 checkpoint 使用同一集合，不会把无关研究资料一股脑加入版本历史。

如果操作中断，可使用 `kb resume`。如果想回到最近一次操作之前，可使用 `kb undo`；指定历史操作则使用 `kb restore <操作编号>`。当 KB 没有变化时，手动 checkpoint 是成功的 no-op。

`kb update` 会保留安装来源与分支：本地 checkout 仍使用本地 checkout，fork 的非 main 分支仍使用原 fork branch。旧安装如果没有可信来源或 branch，会先请你选择，不会悄悄切换到某个默认远端。Detached checkout 绑定当前 commit，后续更新前需要选择 branch。正常调用不会往共享 Python 解释器里安装包。

## 数据心智模型

只需记住五层：受保护的原始证据、可复用的知识单元、研究计划与决策、跨材料综合，以及可重新生成的导出物。原始材料和完整派生证据只读不覆盖；知识单元与研究计划是主要真相；导航和导出都可以从它们重建。

更新、迁移和卸载不会把私有研究数据带进发布包，也不会重写无关的 workspace 文件。

## 记忆与偏好

当 Agent 观察到稳定偏好时，可以记录为待确认记忆：

```text
记住：我的 summary 用中文，保留技术术语英文，结论尽量简洁。
```

偏好确认后才能影响后续行为。Skill defect 只记录和复盘，不能触发自动改 skill。

## 可选的本地开发者诊断

开发者诊断用于记录可复现的能力问题，不是遥测，也不能关闭 schema、evidence、confirmation、containment、事务或恢复等强制安全门。它属于 beta/scaffold 能力，默认关闭自动记录，不应被理解为 stable 承诺。

你仍然只需使用自然语言，例如：

```text
开启开发者诊断。
```

```text
仅在出错时记录；关闭 paper-analyst 诊断。
```

```text
把刚才的失败做脱敏记录和短复盘，不要上传。
```

```text
检查知识库健康，只做只读机械检查，不要修改资料。
```

三种模式的含义是：`off` 不自动记录；`errors-only` 只做确定性失败捕获，不调用 Agent 复盘；`developer` 允许在每任务 token 与问题数量预算内做触发式短复盘。单个能力可以设置得比 workspace 更严格。即使自动诊断关闭，你当前消息中明确要求“记下这个问题”时，Agent 仍会记录；没有明确要求时，纠正和可复用摩擦只在策略允许时自动捕获。

诊断资料只保存在本地，没有后台 telemetry 或自动上传。生成脱敏导出预览需要你在当前消息中明确授权；D1 不负责上传第三方 issue tracker。默认不会包含论文原文、逐字 evidence、用户消息、绝对路径、环境变量、secret 或完整 traceback，记录也不会自动修改 skill、roadmap 或研究结论。

普通 `kb doctor` 仍只显示简短的运行能力结果。由 Agent 执行健康检查时，它可以私下读取当前诊断模式和机械 audit 计数，再用中文解释；公开面仍保持十五个动词，不增加 `lint` 或 `diagnostics` 入口。

## 进一步阅读

- [安装与更新](INSTALL.md)
- [设计与扩展](DESIGN.md)
- [发布变化](../CHANGELOG.md)
- [安全报告](../SECURITY.md)
