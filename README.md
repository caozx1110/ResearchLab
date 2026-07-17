# Open Research Workspace Skills

## English Quickstart

An open-source Codex workspace for research knowledge units. It gives agents skills, scripts, and schemas to keep papers, repos, blogs, ideas, experiments, and reports in a local `kb/` instead of chat history.

首次运行会自动创建并使用项目内受管 `.venv`，无需手动创建 venv 或安装 PyYAML。

```bash
kb init
kb status
```

## 这是什么

这是一个中文优先的 research workspace 骨架。

它不是现成知识库，而是一套让 Codex 持续维护科研工作区的规则、skills、脚本和文档。目标很简单：把论文、网页、仓库、idea、设计、实验记录和周报，尽量从聊天里搬到可复用、可检索、可确认、可版本化的工作区文件里。

公开内容主要有三层：

- `.agents/`：17 个本地 skill、脚本、共享运行库，以及使用规则 `.agents/AGENTS.md`（工作区运行规则、schema 约束和写作偏好；随 `.agents/` 分发到用户工作区根 `AGENTS.md`，面向使用 kb 的 agent）。
- `AGENTS.md` / `CLAUDE.md`（软链 → `AGENTS.md`）：面向开发/优化本 skill 系统的开发者工作流。
- `docs/`：按受众组织的用户指南和设计说明。

如果本地还没有 `kb/`，也没关系。这个仓库可以先只作为 workflow 和 skill 系统使用，知识库内容之后再在本地生成。

## Start Here

- [安装指南](docs/INSTALL.md)：说明 `install.sh`、Claude/Codex project/system scope、`CLAUDE.md` 生成和 `kb` 上 PATH。
- [用户指南](docs/USER_GUIDE.md)：给研究者，说明怎么安装、怎么开口、AI 和你如何分工、如何用 `kb` 快捷入口。
- [设计说明](docs/DESIGN.md)：给开发者，说明 architecture、skill 路由、数据模型、confirmation gate 和扩展原则。
- [贡献指南](CONTRIBUTING.md)：给贡献者，说明协作和变更流程。

安装入口支持 `bash install.sh` 交互式引导。安装模型：system scope 和同仓 `--project .` 使用 symlink；外部 `--project DIR` 会拷贝整棵 `.agents/`（含使用规则 `.agents/AGENTS.md`），并在 workspace 根写出 `AGENTS.md`（= `.agents/AGENTS.md` 使用规则），写入 manifest，并可用 `bash install.sh update --project DIR` 做 clean-sync 更新。详见 [安装指南](docs/INSTALL.md)。

## 核心想法

这套 workspace 的默认目录是：

```text
kb/
├── raw/
├── units/
│   ├── papers/
│   ├── repos/
│   ├── blogs/
│   ├── ideas/
│   └── experiments/
├── programs/
├── synthesis/
├── config/
├── output/
├── user/
└── .runtime/
```

可以把它粗略理解成：

- `raw/`：不可变外部 source bytes。
- `units/`：paper / repo / blog / idea / experiment 的 canonical record。
- `programs/`：具体研究方向、workflow、决策日志和 reporting events。
- `synthesis/`：跨 unit 的 survey、taxonomy、trend、gap。
- `config/`：运行时偏好、taxonomy seed、candidate pool。
- `output/`：导出产物，不是唯一真相。
- `user/`：人类入口页和复开页面。

核心原则：

1. Durable artifacts 优先于 chat-only answers。
2. 新材料先 lightweight ingestion，再决定是否深分析。
3. AI inference、evaluation、novelty judgement 和 failure diagnosis 默认需要人确认。
4. 高价值结果沉淀成可复用 knowledge units。

## 最小使用方式

多数时候你不需要复杂 prompt。

```text
请读取当前 knowledge base，判断我现在最该做哪一步，并直接执行安全步骤；遇到需要我确认或拍板的地方停下来。
```

高频动作可以用 `kb` 快捷入口：

```text
kb help
kb init
kb doctor
kb status
kb next
kb find humanoid vla recovery
kb add https://example.com/paper.pdf
kb review
kb recall
```

`kb` 动词清单以代码为准，共 11 个：`help` 打印能力菜单；`init` 初始化 KB 布局、索引和基础偏好；`doctor` 检查当前 Python、YAML 与 PDF 后端可用性；`status` 刷新并查看当前 KB / program 状态摘要；`next` 查看下一步实验或 program 推进建议；`find` 按关键词检索已入库知识单元；`add` 把论文、repo、博客或本地文件轻量入库；`ingest` 一条命令把 source 拉进来并备好待填骨架，随后 agent 自动填 grounded 笔记；`review` 查看待确认的 AI 判断，后续可交互式确认；`reject` 把误建 / 不采纳的知识单元标记为 rejected（清理出口）；`recall` 回忆已确认习惯、已知坑和待审 skill 问题。

idea / report 没有 `kb` 动词，默认用纯自然语言，例如“请基于当前知识库给我 3 个候选 idea”或“为这个 program 生成周报材料”。

## 能力成熟度（诚实标注，随实现推进更新）

不同能力成熟度差别很大——请按下表判断可依赖程度，**不要用某一项的表现外推整个系统**。

| 档位 | 含义 | 当前属于此档的能力 |
| --- | --- | --- |
| **beta** | 核心范式已落地（prepare/verify + 逐字证据 + 空心门），但"理解"那步依赖 agent 在会话里填 | 论文分析 / 仓库分析 / 博客分析（paper/repo/blog analyst）、双源入库、检索（`kb find` 词级 + agent 原生答题）、自动驱动入库链 |
| **scaffold** | 有可用骨架，但产出仍偏固定策略/直方图/事件流，尚未做到 evidence-first 的实质闭环 | 综述（literature-synthesizer，仍偏 tag 直方图）、idea / 方法设计 / 实验（固定矩阵、不验 artifact）、报告（report-author，偏事件 dump） |
| **dev-only** | 仅供开发/本地实验：现已加 token 鉴权 + PTY 默认关 + 强制回环 + 写保护 raw，但仍不建议用于共享或敏感环境 | Workbench（research-navigator browser：文件写端点带 token 鉴权，shell/PTY 需 `--enable-terminal` 显式开启） |

治理内核（confirmation 词汇、逐字 evidence、禁自签、空心门、派生证据不可变）是**跨全系统的真地基**，不随单个 skill 档位浮动。详见 `temp/SYSTEM_DESIGN_SSOT.md`（设计源）与 `temp/BACKLOG.md`（实时落地状态）。

如果你知道对象，也可以直接说：

```text
请把这篇论文先按 core 流程做轻量入库，再判断是否值得细读。
```

```text
请用 $literature-synthesizer 为 <program-id> 刷新 literature survey。
```

## 分工边界

AI 适合做提取、去重、索引、整理、追踪和汇总。AI 写出的事实 metadata 可以自动入库；AI 写出的判断、评价、诊断、idea review 和趋势归纳默认进入确认收件箱。

你负责确认和拍板：选 idea、选 baseline、确认实验诊断、决定研究阶段推进。确认时要留下 evidence，让后续报告知道哪些内容是人认可的定论，哪些仍是 pending。

## 发布说明

发布版是 workflow package，不捆绑私有 `kb/`。用户应在自己的机器上初始化 `kb/`。首次运行会自动创建受管 `.venv`；高级用户可用 `RESEARCH_PYTHON` 覆盖解释器。
