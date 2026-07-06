# Open Research Workspace Skills

## English Quickstart

An open-source Codex workspace for research knowledge units. It gives agents skills, scripts, and schemas to keep papers, repos, blogs, ideas, experiments, and reports in a local `kb/` instead of chat history.

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export RESEARCH_PYTHON="$(pwd)/.venv/bin/python"
```

```bash
# Coming soon as the single first-run entrypoint:
kb init

# Current first-run commands:
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py init
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py init
${RESEARCH_PYTHON:-python3} .agents/skills/kb-cli/scripts/kb status
```

## 这是什么

这是一个中文优先的 research workspace 骨架。

它不是现成知识库，而是一套让 Codex 持续维护科研工作区的规则、skills、脚本和文档。目标很简单：把论文、网页、仓库、idea、设计、实验记录和周报，尽量从聊天里搬到可复用、可检索、可确认、可版本化的工作区文件里。

公开内容主要有三层：

- `.agents/`：17 个本地 skill、脚本和共享运行库。
- `AGENTS.md`：工作区规则、schema 约束和写作偏好。
- `docs/`：按受众组织的用户指南和设计说明。

如果本地还没有 `kb/`，也没关系。这个仓库可以先只作为 workflow 和 skill 系统使用，知识库内容之后再在本地生成。

## Start Here

- [用户指南](docs/USER_GUIDE.md)：给研究者，说明怎么安装、怎么开口、AI 和你如何分工、如何用 `kb` 快捷入口。
- [设计说明](docs/DESIGN.md)：给开发者，说明 architecture、skill 路由、数据模型、confirmation gate 和扩展原则。
- [贡献指南](CONTRIBUTING.md)：给贡献者，说明协作和变更流程。

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
kb status
kb next
kb find humanoid vla recovery
kb review
kb recall
```

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

发布版是 workflow package，不捆绑私有 `kb/`。用户应在自己的机器上初始化 `kb/`，并用 `RESEARCH_PYTHON` 指向带依赖的 runtime。脚本和文档默认使用 `${RESEARCH_PYTHON:-python3}`。
