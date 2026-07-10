---
name: blog-analyst
description: Analyze blog and technical article units using a prepare/verify paradigm — the script prepares a fillable structure and verifies evidence; a runtime agent fills the understanding (SSOT Principle 1 / §3.4). Web-page sources only (HTML section/anchor locators, no multimedia).
---

# Blog Analyst

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#unit-payload` · `#confirmation-gate` · `#runtime`

当任务是分析某个 blog 或技术文章 knowledge unit，而不是只做 source intake 时，使用这个 skill。

## 范式（与 paper-analyst 对齐）

**脚本绝不理解博客。** 它 (a) 读取 source-intake 生成的 parse-cache，(b) 产出四要素**待填结构**（留白，等 runtime agent 填），(c) 校验 agent 填的每条判断有逐字 evidence 后才落盘。

- Script 做：备料（parse-cache 摘要 + section/anchor 定位）、结构校验、证据核验、落盘。
- Agent 做：读 parse-cache，理解博客，填四要素（每条带 >=1 逐字 evidence_ref）。
- 博客来源为网页内容（HTML），locator 为 section/anchor，无页码。

## 四要素填充契约

agent 填 `blog-fill.yaml` 的 `elements` 列表，每个 element 需含：

| element | claim_type | payload target | 说明 |
|---|---|---|---|
| `positioning` | `inference` | `payload.positioning.main_value` | 内容定位（入门解释/原理分析/经验总结/工程教程）—— agent 判断，非脚本硬编码 |
| `key_points` | `inference` | `payload.content.key_points[]` | 核心知识点/概念列表 |
| `credibility` | `evaluation` | `payload.credibility.best_use` | 明确区分事实整理 vs 作者观点 |
| `reusable_explanation` | `inference` | `payload.content.intuitions[]` | 可复用的解释/直觉素材 |

`key_points` 和 `reusable_explanation` 落在 `payload.content`（substance gate 检查区），填完即过 `has_substantive_content`。

### evidence_ref 格式

每条 evidence_ref 必须含：

```yaml
source_unit_id: b-...           # 本 blog unit id
artifact: parse-cache.yaml      # unit 目录内相对路径
locator: "section:intro"        # HTML: section 或 section:<anchor>（B4）— 无页码
quote: "..."                    # 短逐字片段 —— 脚本检查它逐字存在于 artifact
summary: "..."                  # 可选转述
```

## 负责范围

1. 从 `source-intake` 创建的 blog unit 出发（`intake.py add --kind blog --source ...`），不在此 skill 内做 intake。
2. `complete-note --phase prepare`：读 parse-cache，产四要素待填结构（`blog-fill.yaml`）。
3. Agent 读 parse-cache，填 `blog-fill.yaml` 四要素，每条带逐字 evidence_ref。
4. `complete-note --phase verify`：校验 evidence 逐字存在 + validate_claims + 落盘 `blog-note.md` + 填 payload content section。
5. `confirm`：substance gate（有内容才可 confirm）+ 人工确认。

不适用场景：正式 paper（arxiv/会议 PDF）→ `paper-analyst`；codebase walkthrough → `repo-analyst`；仅引用单术语 → `wiki-adapter`。

## 上下游

- 上游：`source-intake`（创建 blog unit + parse-cache）
- 下游：`literature-synthesizer`（综述）、`report-author`（周报引用 reusable_explanation）

## 常用命令

```bash
# Step 1: 备料 — 产待填结构
${RESEARCH_PYTHON:-python3} .agents/skills/blog-analyst/scripts/blog.py \
  complete-note --phase prepare --blog-id b-example-12345678

# Step 2: Agent 填 blog-fill.yaml（positioning/key_points/credibility/reusable_explanation，带 evidence）

# Step 3: 校验 + 落盘
${RESEARCH_PYTHON:-python3} .agents/skills/blog-analyst/scripts/blog.py \
  complete-note --phase verify --blog-id b-example-12345678

# Step 4: 人工确认
${RESEARCH_PYTHON:-python3} .agents/skills/blog-analyst/scripts/blog.py \
  confirm --blog-id b-example-12345678 \
  --confirmed-by czx \
  --evidence kb/units/blogs/b-example-12345678/blog-note.md
```
