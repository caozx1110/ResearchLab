---
name: wiki-adapter
description: Provide a thin wiki-style entrypoint for core, routing generic “add/query/lint wiki” requests to the correct owner skills and saving reusable query notes under `kb/synthesis/wiki/`.
---

# Wiki Adapter

Preference contract: explicitly neutral with an empty eligible catalog. This thin router delegates semantic preference consumption to the selected canonical owner.

> 协议参考：`.agents/lib/research/SCHEMAS.md#ownership` · `#runtime`

Use this skill when the user speaks in generic wiki or knowledge-base terms rather than naming the owner skill directly. This is a **thin router**：本 skill 自身不做深度分析，`add` 会直接委托 `source-intake` 完成入库；`query` 会把查询结果写入 `kb/synthesis/wiki/` 作为可复用笔记。

## When to use vs. when to delegate directly

- 用 wiki-adapter：用户说 "wiki / 词条 / 术语 / glossary / 知识库里有 X 吗"，并且不清楚走哪个 owner skill。
- 不用 wiki-adapter：用户已明确说 "添加 paper" / "深读 repo" / "看当前 program 状态"，此时直接调用对应 owner skill 更短路。
- 新用户起步：直接使用公开的 `kb init`、`kb status`、`kb next` 对话入口；不要把可选投影 helper 包装成正式产品入口。

## Routing table

| 用户意图（关键词） | 转给的 owner skill | 用什么命令 |
|---|---|---|
| add / 添加 paper · 入库 paper · 收一篇 paper | `source-intake` → `paper-analyst` | `wiki.py add --kind paper` 直接转发 `intake.py add --kind paper`，后续按 intake/paper 运行时策略继续分析 |
| add / 添加 repo · 加仓库 | `source-intake` → `repo-analyst` | `wiki.py add --kind repo` 直接转发 `intake.py add --kind repo` |
| add / 添加 blog | `source-intake` → `blog-analyst` | `wiki.py add --kind blog` 直接转发 `intake.py add --kind blog` |
| query / 查询 · 综述 · taxonomy · 多 source 综合 | `literature-synthesizer` | `synthesize.py survey/review/taxonomy` |
| query / 单条索引 · 找 unit · "X 是哪篇" | `knowledge-base-manager` | `kb.py query --query "..."` |
| lint · schema 检查 · 索引刷新 | `knowledge-base-manager` | `kb.py lint` / `kb.py refresh-schema` |
| 检查知识库健康 · 恢复/安全/质量机械审计 | `knowledge-base-manager` | Agent 私下调用 owner `audit`，自然语言概述结果；不增加公开 `kb` 动词 |
| topic / tag / pool 治理 | `knowledge-base-manager`（结构）+ `research-config-manager`（seed） | `kb.py govern` / `config.py set-taxonomy-seed` |
| 我是新用户 / 不知道从哪看起 | `kb-cli` + `research-orchestrator` | Agent 依次使用 `kb init`、`kb status`、`kb next` 并自然语言解释 |
| 当前 program 状态 / next actions | `research-orchestrator` | `orchestrate.py status` |
| 想在 kb 里留一条复用笔记或术语解释 | 本 skill | `wiki.py query --question ...`（每次 query 都会落盘） |

## Commands

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/wiki-adapter/scripts/wiki.py query --question "哪些 paper 最适合当前方向？"
${RESEARCH_PYTHON:-python3} .agents/skills/wiki-adapter/scripts/wiki.py add --kind paper --source kb/raw/paper.pdf
${RESEARCH_PYTHON:-python3} .agents/skills/wiki-adapter/scripts/wiki.py lint
```

`audit` 是 Agent-only 的只读路由：wiki-adapter 只转发同一份分层机械报告，不理解研究材料，不刷新索引，也不做网络/依赖或 LLM 语义扫描。不得把 owner JSON、绝对路径或内部命令直接展示给普通用户。

## 启动澄清（Agent 用）

- 意图：查询、入库还是治理？默认按路由表转对应 owner。
- 查询结果要留成复用笔记吗？默认要，落 kb/synthesis/wiki/。
