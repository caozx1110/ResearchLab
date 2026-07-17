# 用户指南

这份文档面向使用者和研究者，回答一个问题：怎么把论文、仓库、博客、想法、实验和汇报，从聊天里变成可复用、可检索、可确认的本地知识库。

这个系统不是一个预装好的知识库。它是一套给 Codex 使用的 research workspace：AI 负责提取、整理、追踪和汇总，你负责判断、确认和拍板。默认人类可读内容用中文；英文论文标题、repo 名、benchmark 名和技术术语保留原文。

## 安装与首次运行

首次运行会自动创建并使用项目内受管 `.venv`（含 PyYAML），无需手动创建 venv、安装依赖或设置 `RESEARCH_PYTHON`。

初始化本地 `kb/`：

```bash
kb init
```

`kb init` 会创建 `kb/` 骨架、索引、语言、资源画像和运行偏好等基础配置。

如果你使用 `kb` 快捷入口，可以先试：

```bash
kb help
kb status
```

## 先看哪里

初始化后，优先打开这些入口：

1. `kb/index.md`
2. `kb/user/current-state.md`
3. `kb/user/navigation.md`
4. `kb/user/reading-lists/current-reading.md`

如果这些页面还不存在，可以让 AI 刷新导航：

```text
请刷新 research navigator，然后告诉我当前最该看什么。
```

如果你已经知道 `program-id`，再看：

1. `kb/programs/<program-id>/state.yaml`
2. `kb/programs/<program-id>/workflow/decision-log.md`
3. `kb/programs/<program-id>/design/`
4. `kb/programs/<program-id>/reports/`

## 核心分工

AI 做重复劳动，你做判断。这是整套系统最重要的边界。

### AI 可以稳定自动完成

1. 提取事实信息：论文标题、作者、年份、链接，repo README、依赖、入口，博客要点。
2. 去重：新材料和已有 paper/repo/blog unit 按 DOI、URL、标题相似度等线索去重。
3. 索引和检索：按标题、tag、topic、正文、payload 搜索本地 `kb/`。
4. 追踪待办：program open question、evidence request、experiment follow-up、确认收件箱。
5. 产物落点管理：record、note、figure、report material 都落在 `kb/` 下。
6. 导航复开：生成 `kb/user/` 下的人类入口页。

### AI 的判断默认需要你确认

这些内容是推断、评价或意见，默认进入 `pending_user_confirmation`：

- 论文 quick-screen 的“值不值得读”判断。
- idea 的 novelty、feasibility、difficulty 评审。
- experiment diagnosis 的 likely causes。
- repo 是否适合复用的判断。
- literature survey 的趋势、分类和空白点判断。
- 用户习惯、 recurring issue、skill defect 的归纳。

确认时必须留下确认人和 evidence。AI 不能自己给自己盖章。

### 信息类型和确认状态怎么看

`information_types` 说明“这句话是什么性质”，`confirmation_status` 说明“现在谁认可它”。常见组合可以这样理解：

| information_types | auto_confirmed | pending_user_confirmation | confirmed | rejected |
|---|---|---|---|---|
| `fact` | AI 抄录的客观事实，已自动入库 | 客观事实但还等你核对 | 你签过字的事实 | 你否掉的事实记录 |
| `inference` | 不常用；AI 推断通常不应自动定论 | AI 的推断，等你确认 | 你认可过的推断 | 你否掉的推断 |
| `evaluation` | 不常用；AI 评价通常不应自动定论 | AI 的评价，等你确认 | 你认可过的评价 | 你否掉的评价 |
| `user_opinion` | 不常用；用户意见应保留来源 | AI 代记的用户意见，等你确认 | 你签过字的个人意见或偏好 | 你否掉的意见记录 |
| `unverified` | 未核验信息，已作为线索入库 | 未核验信息，等你确认或补证据 | 你确认可作为结论使用 | 你确认不采用 |

一条 record 可以同时有多种 `information_types`。只要包含 AI 推断、评价或用户意见，就应默认进入 `pending_user_confirmation`，直到你确认或拒绝。

### 只有你能拍板

1. 选择最终推进哪个 idea。
2. 决定实际跑哪组 baseline、超参和 ablation。
3. 判定实验结论是否成立。
4. 决定研究阶段何时从探索转向验证、从验证转向写作。

AI 可以给建议和理由，但遇到这些决策点应该停下来让你决定。

## 你可以这样对 AI 说

大多数时候不需要点名 skill。自然语言说清楚任务即可。

### 不知道下一步做什么

```text
请读取当前 knowledge base，判断我现在最该做哪一步，并直接执行安全步骤；遇到需要我确认或拍板的地方停下来。
```

```text
看一下当前状态，给我这个 program 的 dashboard 和下一步建议。
```

### 加论文、仓库、博客

```text
请把这篇论文轻量入库，然后判断是否值得细读。
```

```text
把这个 GitHub repo 变成知识单元，并给出能力边界、训练/推理入口和复用价值。
```

```text
入库这个博客，总结关键观点并标出可信度判断。
```

AI 会先做 lightweight ingestion，再按对象类型路由到 `paper-analyst`、`repo-analyst` 或 `blog-analyst`。

### 做综述和检索

```text
请基于当前已入库知识单元，为这个方向生成趋势、方法分类和空白点总结。
```

```text
在知识库里找和 humanoid VLA recovery 相关的 paper、repo 和 idea。
```

### 从想法到方法

```text
记下一个想法：用 retrieval-augmented generation 改进代码补全。
```

```text
把这个 idea 扩写成可评审的研究问题，并分析新意、可行性和最小验证路径。
```

```text
我选择这个 idea，开始推进。请把选择过程写入 decision-log。
```

```text
基于这个 selected idea 起草 method design，给出 repo choice、接口、baseline 和实验矩阵。
```

### 记录实验和诊断

```text
记录一次实验 run：baseline 无检索，perplexity=5.23，pass@1=0.42。
```

```text
诊断这次实验为什么效果不好，列出 likely causes、ruled out 和 unknowns。
```

```text
确认这条诊断，我是 czx，evidence 是复现三次后确认检索召回率低。
```

run-log 只记录事实；diagnosis 是 AI 推断，默认待确认；follow-up 是下一步行动。

### 生成汇报材料

```text
生成这个 program 的本周周报。
```

```text
提取 related-work 写作素材，只使用 confirmed 或明确标注 pending 的内容。
```

```text
提取 PPT 素材，包括 bullet points、figure 路径和对比表。
```

报告系统从 program 的 reporting events、confirmed notes 和 follow-ups 里汇总，不应该把未确认判断伪装成定论。

### 打开工作台

```text
请用 research-navigator 打开本地知识库浏览器，我要在 Workbench 里预览和编辑 Markdown。
```

浏览器 Workbench 面向 `kb/user/` 和 Markdown 预览/编辑；canonical YAML 和 raw source 不应通过浏览器随意改。

## `kb` 快捷入口

`kb-cli` 是第 17 个本地 skill，也是一个薄 dispatcher。它把高频动作收敛成短命令，底层仍转发给 owner skill。你可以在终端运行，也可以直接对 AI 说这些短句。

| 你说或运行 | 用途 |
|---|---|
| `kb help` | 打印能力菜单。 |
| `kb init` | 初始化 KB 布局、索引和基础偏好。 |
| `kb doctor` | 检查当前 Python、YAML 与 PDF 后端可用性。 |
| `kb status [program]` | 刷新并查看当前 KB / program 状态摘要。 |
| `kb next [program]` | 查看下一步实验或 program 推进建议。 |
| `kb find <关键词>` | 按关键词检索已入库知识单元。 |
| `kb add <链接或路径>` | 把论文、repo、博客或本地文件轻量入库。 |
| `kb ingest <链接或路径>` | 一条命令把 source 拉进来并备好待填骨架，随后 agent 自动填 grounded 笔记。 |
| `kb review [fuzzy]` | 查看待确认的 AI 判断，后续可交互式确认。 |
| `kb reject <单元 id>` | 把误建 / 不采纳的知识单元标记为 rejected（清理出口）。 |
| `kb recall [kind]` | 回忆已确认习惯、已知坑和待审 skill 问题。 |

idea / report 没有 `kb` 动词，默认用纯自然语言：

| 意图 | 对 AI 说 |
|---|---|
| 推进候选 idea 的生成、分析和选择 | 请基于当前知识库给我 3 个候选 idea |
| 生成周报、PPT 素材或阶段总结 | 为这个 program 生成周报材料 |

示例：

```bash
kb doctor
kb find policy gradient
kb review
```

对 AI 说也可以：

```text
kb status
kb next survey-rag
kb find transformer calibration
kb recall gotchas
```

## 确认收件箱

确认收件箱收集所有 `pending_user_confirmation` 的条目，适合定期清账：

```text
看一下确认收件箱里有什么待审的。
```

```text
确认这条论文筛选，我是 czx，evidence 是 kb/programs/survey-rag/workflow/decision-log.md。
```

```text
拒绝这条 repo 复用判断，evidence 是接口不支持我们的训练流程。
```

规则很简单：

1. `confirmed` 必须有确认人和 evidence。
2. evidence 可以是 decision-log、会议记录、复现实验、你写下的判断依据。
3. 即使批量确认，也要给 evidence。
4. AI 自动执行安全步骤时，遇到 confirm、select、stage change 这类决策应停下。

## 记忆和 learnings

系统会把用户习惯、反复出现的问题和 skill 缺陷写入 `kb/memory/learnings.yaml`，但默认也是 pending。确认后才会成为以后可遵守的记忆。

你可以这样说：

```text
记住：我的 summary 喜欢中文，风格简洁。
```

```text
记录一个 skill 问题：入库任务被错分给了 wiki-adapter。
```

```text
看一下已知习惯和坑。
```

```text
确认这条习惯，提升到配置。
```

边界：

1. `user-preference` 确认后可以进入 runtime preferences。
2. `recurring-issue` 确认后会出现在 recall 摘要中。
3. `skill-defect` 只记录，不能自动修改 skill 或内部计划文档。

## 17 个本地 skill

默认全用自然语言，点名 `$skill` 仅在你想强制某一步时可选。普通使用者不需要背 skill 名，但知道 owner 有助于和 AI 对齐。

| 分组 | Skills |
|---|---|
| 治理与路由 | `knowledge-base-manager`, `research-config-manager`, `source-intake`, `research-orchestrator` |
| 分析 | `paper-analyst`, `repo-analyst`, `blog-analyst`, `literature-synthesizer` |
| 创建与执行 | `idea-workbench`, `method-designer`, `experiment-workbench`, `report-author` |
| 导航与元能力 | `research-navigator`, `discussion-archivist`, `wiki-adapter`, `skill-evolution-advisor` |
| 快捷入口 | `kb-cli` |

### 能力成熟度（诚实标注，随实现推进更新）

不同 skill 的成熟度差别很大——请按下表判断可依赖程度，**不要用某一项（如论文分析）的表现外推整个系统**。

| 档位 | 含义 | 当前属于此档 |
|---|---|---|
| **beta** | 核心范式已落地（prepare/verify + 逐字证据 + 空心门），但"理解"那步依赖 agent 在会话里填 | 论文 / 仓库 / 博客分析、双源入库、检索（`kb find` 词级 + agent 原生答题）、自动驱动入库链 |
| **scaffold** | 有可用骨架，但产出仍偏固定策略 / 直方图 / 事件流，尚未做到 evidence-first 的实质闭环 | 综述（`literature-synthesizer`）、idea / 方法设计 / 实验、报告（`report-author`） |
| **dev-only** | 仅供本地实验：现已加 token 鉴权 + PTY 默认关 + 强制回环 + 写保护 raw，仍不建议共享 / 敏感环境 | 工作台（`research-navigator` browser：文件写带 token；shell/PTY 需 `--enable-terminal` 显式开） |

治理内核（confirmation 词汇、逐字 evidence、禁自签、空心门、派生证据不可变、确认锚定版本）是**跨全系统的真地基**，不随单个 skill 档位浮动。

### task 到 owner skill 的一句话索引

| 你想做什么 | Owner skill |
|---|---|
| 初始化、lint、索引、schema、确认收件箱 | `knowledge-base-manager` |
| 配置语言、确认人、运行偏好、taxonomy seed、candidate pool | `research-config-manager` |
| 添加 paper / repo / blog / 本地文件，先做 lightweight intake | `source-intake` |
| 看当前 program 状态、next actions、open questions、decision-log | `research-orchestrator` |
| 论文 quick-screen、完整笔记、Figure / Table、结构刷新、确认 | `paper-analyst` |
| Repo 结构扫描、能力映射、复用判断 | `repo-analyst` |
| Blog / 技术文章摘要、可信度和可复用解释 | `blog-analyst` |
| 跨 paper / repo / blog / idea 做 survey、taxonomy、趋势、gap | `literature-synthesizer` |
| 生成、分析、review、选择候选 idea | `idea-workbench` |
| 把已选 idea 展开成 method design、接口、baseline、实验矩阵 | `method-designer` |
| 记录实验 run、诊断、follow-up、实验结论 | `experiment-workbench` |
| 生成周报、阶段总结、PPT 素材、写作素材 | `report-author` |
| 刷新 `kb/user/` 导航、current-state、reading list、打开浏览器工作台 | `research-navigator` |
| 把重要讨论归档成 program discussion note | `discussion-archivist` |
| 处理泛 wiki / 词条 / 知识库查询，并路由到 owner skill | `wiki-adapter` |
| 记录、回忆、确认习惯、已知坑和 skill defect | `skill-evolution-advisor` |
| 用 `kb help/init/doctor/status/next/find/add/ingest/review/reject/recall` 快捷转发 | `kb-cli` |

如果你明确知道要哪一步，可以点名：

```text
请用 $paper-analyst 对 last paper 做 quick screen。
```

```text
请用 $literature-synthesizer 为 <program-id> 刷新 literature survey。
```

否则让 AI 通过 `research-orchestrator` 路由即可。

## 目录心智模型

```text
kb/
├── raw/          # 不可变外部 source bytes
├── units/        # papers / repos / blogs / ideas / experiments
├── programs/     # 具体研究方向
├── synthesis/    # 跨 unit 的 survey / taxonomy / trends / gaps
├── config/       # 语言、资源画像、taxonomy seed、candidate pool 策略
├── user/         # 人类入口页和复开页面
├── output/       # 导出产物
└── .runtime/     # 运行时缓存
```

`raw/` 是源材料，`units/` 是 canonical knowledge units，`programs/` 是研究方向，`user/` 是给人复开的入口。不要把 `kb/output/` 当唯一真相。

## 三条原则

1. AI 提取事实可靠，AI 的判断必须你审。
2. 所有关键科研决策由你拍板。
3. 高价值结果要落成 durable artifact，而不是只留在聊天里。
