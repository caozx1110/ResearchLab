---
name: blog-analyst
description: Analyze blog and technical article units in the v2 research system, including content positioning, key concepts, credibility judgement, and reusable explanation material for later discussion and reporting.
---

# Blog Analyst

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#unit-payload` · `#confirmation-gate`

当任务是在分析某个 blog 或技术文章 knowledge unit，而不是只做 source intake 时，使用这个 skill。结构与 `paper-analyst` 对齐，但 credibility 判定额外考虑作者匿名 / 平台权威 / 是否有可验证引用。

## 负责范围

1. 从 `source-intake` 创建的 blog unit 出发（`intake.py add --kind blog --source ...`），不在此 skill 内做 intake。
2. 先 `summarize` 做轻量摘要 + positioning（postface vs walkthrough vs opinion vs tutorial）。
3. 再 `complete-note` 写完整 note，包含 key concepts、credibility（作者背景 / 出版平台 / 是否引用同行评议来源 / 可复现要素）、reusable explanation material（适合在周报或讨论里复述的段落）。
4. AI judgement 默认保持 `pending_user_confirmation`，与 paper-analyst 一致。
5. 不适用的场景：正式 paper（arxiv/会议论文 PDF）走 `paper-analyst`；codebase walkthrough 同时引用源码的，走 `repo-analyst`；只想引用一句术语的，走 `wiki-adapter` 沉淀为复用笔记。

## 上下游

- 上游：`source-intake`（创建 blog unit + raw 备份）
- 下游：`literature-synthesizer`（综述）、`report-author`（在周报里引用 reusable material）

## 常用命令

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/blog-analyst/scripts/blog.py summarize --blog-id b-example-12345678
${RESEARCH_PYTHON:-python3} .agents/skills/blog-analyst/scripts/blog.py complete-note --blog-id b-example-12345678
${RESEARCH_PYTHON:-python3} .agents/skills/blog-analyst/scripts/blog.py confirm --blog-id b-example-12345678 --confirmed-by czx --evidence kb/units/blogs/b-example-12345678/blog-note.md
```
