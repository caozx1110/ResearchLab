# 设计说明

这份文档面向想理解或扩展系统的开发者。它解释 architecture、skill 路由、数据模型、确认门控和扩展方式。具体 on-disk schema 以 [`.agents/lib/research/SCHEMAS.md`](../.agents/lib/research/SCHEMAS.md) 为准；本文只保留心智模型和原则。

## 设计目标

Open Research Workspace Skills 是一个 knowledge-unit-first 的 research operating system。它不把聊天记录当工作区，而是让 AI 把研究过程持续写入 `kb/`：

1. 外部材料先进入 `kb/raw/`，保持不可变。
2. 论文、仓库、博客、想法和实验都成为 `kb/units/<kind>s/<id>/record.yaml`。
3. 具体研究方向挂在 `kb/programs/<program-id>/`。
4. 综述、taxonomy、趋势和 gap 放在 `kb/synthesis/`。
5. 人类入口页从 canonical 数据生成到 `kb/user/`。

这个设计吸收了 LLM-maintained wiki 的核心思路：让 AI 持续维护可链接、可复开的中间知识层，而不是每次查询都从 raw documents 重新做 RAG。区别是本系统把 wiki 思路收敛成 typed knowledge units、program workflow 和 confirmation gate。

## 架构层次

```text
.agents/
├── skills/             # 17 个本地 skill：16 个 core-chain skill + kb-cli
├── lib/research/       # 跨 skill 共享 Python helper
└── README.md

kb/
├── raw/
├── units/
├── programs/
├── synthesis/
├── config/
├── user/
├── output/
└── .runtime/
```

公开包提供 `.agents/`（含使用规则 `.agents/AGENTS.md`）、面向开发者的 `AGENTS.md`/`CLAUDE.md`（软链）、`README.md` 和 `docs/`。用户本地运行后生成自己的 `kb/`；发布包不应捆绑私有 knowledge base。

`kb/` 可以是嵌套 Git repository。runtime state、browser snapshots 和本地缓存应忽略，canonical records 和 durable notes 才是知识库主体。

## Skill 系统和路由

系统当前有 17 个本地 skill：

| 分组 | Skills |
|---|---|
| Governance and routing | `knowledge-base-manager`, `research-config-manager`, `source-intake`, `research-orchestrator` |
| Analysis | `paper-analyst`, `repo-analyst`, `blog-analyst`, `literature-synthesizer` |
| Creation and execution | `idea-workbench`, `method-designer`, `experiment-workbench`, `report-author` |
| Navigation and meta | `research-navigator`, `discussion-archivist`, `wiki-adapter`, `skill-evolution-advisor` |
| Shortcut dispatcher | `kb-cli` |

路由原则：

1. 用户可以自然语言描述任务，不必点名 skill。
2. 明确 owner 的任务应交给 owner skill，不复制业务逻辑。
3. `research-orchestrator` 负责跨 program 的状态、next action、open question、evidence request、decision-log 和 reporting event。
4. `kb-cli` 只做薄 dispatcher，把 `help/status/next/find/recall/add/review` 转译到底层 owner 脚本。
5. `wiki-adapter` 是薄入口，处理“加到 wiki/查 wiki/lint wiki”这类泛化表达，再转给真正 owner。

Skill 的 `SKILL.md` 负责触发语义和职责边界；`agents/openai.yaml` 应与它保持一致。重复、确定性的行为应该沉到 `scripts/`，避免让提示词承担流程控制。

## 数据模型

每个 unit 至少有一个 `record.yaml`，它是 canonical record。详细笔记、payload、figure、diagnosis、report material 都是附属产物，不能替代 record。

最小 record 需要表达：

- `id`
- `kind`
- `status`
- `maturity`
- `confirmation_status`
- `needs_human_confirmation`
- `information_types`
- `tags`
- `topics`
- `links`
- `reuse_flags`
- `history`

Unit 类型包括：

- `paper`
- `repo`
- `blog`
- `idea`
- `experiment`

Program 文件落在 `kb/programs/<program-id>/`，核心包括：

- `state.yaml`
- `workflow/open-questions.yaml`
- `workflow/evidence-requests.yaml`
- `workflow/decision-log.md`
- `workflow/reporting-events.yaml`
- `design/`
- `experiments/`
- `reports/`
- `discussions/`

`report-author` 主要从 reporting events 和 confirmed artifacts 汇总周报、阶段总结、PPT 素材和写作素材。`research-navigator` 主要从 canonical 数据生成 `kb/user/` 下的人类入口页。

Config 文件落在 `kb/config/`，包括 candidate pools、topic taxonomy、runtime preferences、user profile 等。`research-config-manager` 写入偏好和 seed；`knowledge-base-manager` 负责更广义的 schema、索引、治理和 lifecycle。

完整字段和约束见 [SCHEMAS.md](../.agents/lib/research/SCHEMAS.md)。

## Confirmation Gate

确认门控是系统质量边界。

事实信息可以 `auto_confirmed`。凡是 AI 推断、评价、用户意见归纳或未验证信息，默认应是 `pending_user_confirmation`。例如：

- `information_types` 包含 `inference`
- `information_types` 包含 `evaluation`
- `information_types` 包含 `user_opinion`
- `source.kind` 是 `ai`

把内容提升到 `confirmed` 时必须提供确认人和 evidence。底层 helper 会写入 confirmation provenance，记录谁确认、何时确认、凭什么确认。

当前实现要诚实看待两个边界：

1. Unit `record.yaml` 写入会走 `validate_write()`；默认违规是 warning，设置 `RESEARCH_VALIDATE_STRICT=1` 或显式 strict 时才拦截。
2. Program state、workflow files、reporting events 等旁路文件目前不全部经过同等强度的 gate，因此写文档和 report 时必须继续区分 fact、inference、evaluation 和 unverified。

开发者扩展系统时，不要把 AI judgement 静默提升成事实。

## `kb/` 目录心智模型

```text
kb/raw/              # immutable external source bytes
kb/units/            # canonical knowledge units
kb/programs/         # concrete research programs and workflow state
kb/synthesis/        # cross-unit surveys, taxonomy, trends, gaps
kb/config/           # runtime preferences, taxonomy seeds, candidate pool policy
kb/user/             # generated human-facing navigation and reopen pages
kb/output/           # exports only
kb/.runtime/         # local runtime/cache state
```

`raw/` 不重写；`units/` 和 `programs/` 是主要真相；`user/` 是生成入口；`output/` 只是导出，不是唯一 source of truth。

## 如何扩展或新增 skill

新增 skill 时，先明确 owner 边界，再写脚本。

推荐步骤：

1. 在 `.agents/skills/<skill-name>/SKILL.md` 写清触发条件、职责、输入输出和禁止事项。
2. 同步更新 `.agents/skills/<skill-name>/agents/openai.yaml`，保持触发语义一致。
3. 能确定执行的流程放进 `scripts/`，并提供 `--help`。
4. 读写 unit record 时复用 `.agents/lib/research/` helper，尤其是 ID、YAML、root discovery、confirmation 和 write helpers。
5. AI 推断和评价默认写成 `pending_user_confirmation`。
6. 如果写 program workflow，尽量 emit reporting event，让 `report-author` 和 `research-navigator` 能复用。
7. 给共享行为补测试；至少运行新脚本的 `--help`。
8. 更新 `docs/DESIGN.md` 或 `docs/USER_GUIDE.md` 中面向用户或开发者的对应说明。

不要让两个 skill 长期拥有同一类 canonical artifact。出现重叠时，优先收敛 owner，而不是靠提示词约定谁先谁后。

## Runtime 和已知结构

脚本默认使用 `${RESEARCH_PYTHON:-python3}`。文档和 generated command 应保持这个形式，让用户可以通过 `RESEARCH_PYTHON` 指向自己的 venv。

多数 skill 脚本会从 `Path(__file__).resolve()` 开始向上查找 `.agents/lib`，并临时插入 `sys.path`。这让脚本在源码树里直接运行很方便，也支持 `--root` / `RESEARCH_PROJECT_ROOT` 做显式项目根；但它也意味着符号链接 sandbox 可能解析回真实仓库。需要隔离演练时，复制 `.agents/` 或显式传 root。

当前 `.agents/lib/research/core.py` 是一个较大的 god-file，集中了承载 record、schema、confirmation、runtime preference、program helper 等职责；`.agents/lib/research/common.py` 承担 root discovery、路径和通用工具。这是当前结构现实，不应在 docs 里假装已经完全模块化。后续拆分应以测试覆盖和 owner 边界为前提。

## 发布和兼容性

发布面向的是 workflow package，不是私有知识库。新用户应创建自己的 `kb/`：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
export RESEARCH_PYTHON="$(pwd)/.venv/bin/python"
${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py init
${RESEARCH_PYTHON:-python3} .agents/skills/research-config-manager/scripts/config.py init
```

文档里的路径应优先使用相对路径和可配置 runtime，避免写入维护者本机路径。
