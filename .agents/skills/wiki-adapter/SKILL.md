---
name: wiki-adapter
description: Provide a thin wiki-style entrypoint for v2, routing generic “add/query/lint wiki” requests to the correct owner skills and saving reusable query notes under `kb/synthesis/wiki/`.
---

# Wiki Adapter

> 协议参考：`.agents/lib/research/SCHEMAS.md#ownership`

Use this skill when the user speaks in generic wiki or knowledge-base terms rather than naming the owner skill directly. This is a **thin router**：本 skill 自身不做深度分析，`add` 会直接委托 `source-intake` 完成入库；`query` 会把查询结果写入 `kb/synthesis/wiki/` 作为可复用笔记。

## When to use vs. when to delegate directly

- 用 wiki-adapter：用户说 "wiki / 词条 / 术语 / glossary / 知识库里有 X 吗"，并且不清楚走哪个 owner skill。
- 不用 wiki-adapter：用户已明确说 "添加 paper" / "深读 repo" / "看当前 program 状态"，此时直接调用对应 owner skill 更短路。
- 新用户起步：转给 `research-navigator` 的 `First-time use` 流程，而不是在这里堆术语。

## Routing table

| 用户意图（关键词） | 转给的 owner skill | 用什么命令 |
|---|---|---|
| add / 添加 paper · 入库 paper · 收一篇 paper | `source-intake` → `paper-analyst` | `wiki.py add --kind paper` 直接转发 `intake.py add --kind paper`，后续按 intake/paper 运行时策略继续分析 |
| add / 添加 repo · 加仓库 | `source-intake` → `repo-analyst` | `wiki.py add --kind repo` 直接转发 `intake.py add --kind repo` |
| add / 添加 blog | `source-intake` → `blog-analyst` | `wiki.py add --kind blog` 直接转发 `intake.py add --kind blog` |
| query / 查询 · 综述 · taxonomy · 多 source 综合 | `literature-synthesizer` | `synthesize.py survey/review/taxonomy` |
| query / 单条索引 · 找 unit · "X 是哪篇" | `knowledge-base-manager` | `kb.py query --query "..."` |
| lint · schema 检查 · 索引刷新 | `knowledge-base-manager` | `kb.py lint` / `kb.py refresh-schema` |
| topic / tag / pool 治理 | `knowledge-base-manager`（结构）+ `research-config-manager`（seed） | `kb.py govern` / `config.py set-taxonomy-seed` |
| 我是新用户 / 不知道从哪看起 | `research-navigator` | `navigate.py refresh` 后看 `kb/index.md` |
| 当前 program 状态 / next actions | `research-orchestrator` | `orchestrate.py status` |
| 想在 kb 里留一条复用笔记或术语解释 | 本 skill | `wiki.py query --question ...`（每次 query 都会落盘） |

## Commands

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/wiki-adapter/scripts/wiki.py query --question "哪些 paper 最适合当前方向？"
${RESEARCH_PYTHON:-python3} .agents/skills/wiki-adapter/scripts/wiki.py add --kind paper --source kb/raw/paper.pdf
${RESEARCH_PYTHON:-python3} .agents/skills/wiki-adapter/scripts/wiki.py lint
```
