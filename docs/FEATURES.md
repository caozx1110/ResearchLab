# 功能总览（core）

> 这个工作区是**给科研全流程用的知识操作系统**：把论文、仓库、博客、想法、方法、实验、周报，从聊天里搬进可复用、可检索、可确认、可版本化的文件。
> 本文回答一个问题——**现在它到底能做什么，怎么用，背后是什么原理**。

---

## 0. 三条核心原理（先懂这个，其余都好理解）

1. **一切先变成"知识单元"（knowledge-unit-first）**
   论文/仓库/博客/想法/实验，五种对象都落成一个 `kb/units/<kind>s/<id>/record.yaml`。这个 record 是**唯一真相**——状态、标签、关联、确认状态、历史都在里面；详细笔记是它的附属文件，不能取代它。
   *为什么*：统一结构后，检索、综述、报告、导航都只面对一种东西，而不是一堆散落的 markdown。

2. **AI 说的话默认"待确认"（confirmation gate）**
   凡是 AI 的推断/评价/判断（不是客观事实），record 默认标 `pending_user_confirmation`，**必须人明确确认后**才算数。确认时还要留下**谁确认的、凭什么确认**（`--confirmed-by` + `--evidence`），AI 不能自己给自己盖章。
   *为什么*：让"机器猜的"和"人认可的"永远可区分，报告不会把未验证的推断当既定事实。

3. **研究挂在"program"上，改动留痕、自动进 git**
   具体研究方向是一个 `kb/programs/<id>/`，有状态机、待解问题、证据需求、决策日志、事件流。里程碑写入会**自动 git checkpoint**。
   *为什么*：随时能重开一个方向的来龙去脉，而不是靠记忆。

---

## 1. 把材料变成知识单元　`source-intake` → `*-analyst`

| 你想做 | 怎么用（示例） | 原理一句话 |
|---|---|---|
| 新论文/仓库/博客**轻量入库**（去重+备份原件） | `intake.py add --kind paper --source <url或路径>` | 先 staging 去重，再建 record + 备份原始 bytes 到 `kb/raw/` |
| 入库前**先记录搜索候选** | `intake.py search --kind paper --query "..."` | 把一批候选存成 stage，再挑要不要正式入库 |
| 论文**快速筛选**该不该细读 | `paper.py screen --paper-id <id>` | 抽 PDF 前几页 + 摘要，给"值不值得读"的判断（pending 待确认） |
| 论文**完整笔记 / 图表抽取 / 结构刷新** | `paper.py complete-note` · `extract-figures` · `refresh-structure` | 结构化 payload；图表用几何聚类从 PDF 裁出 |
| 仓库**能力边界 + 复用价值** | `repo.py scan-structure` · `map-capability` | 扫目录结构 + 映射能力/入口/训练推理路径 |
| 博客**总结 + 可信度判断** | `blog.py summarize` | 定位、要点、可信度分级 |
| **人工确认**一个单元 | `paper.py confirm --paper-id <id> --confirmed-by 你 --evidence <笔记路径>` | 盖章需留人证+凭据（见原理②） |

## 2. 检索与发现　`kb.py query` / `wiki-adapter`

| 你想做 | 怎么用 | 原理一句话 |
|---|---|---|
| **搜知识库**（带排序的全文） | `kb.py query --query "vla recovery" [--kind paper] [--confirmation-status pending_user_confirmation]` | 不只搜标题标签，**连笔记正文/payload 都搜**，按 tags/topics/title/正文加权排序 |
| 快速 wiki 式**查/加/lint** | `wiki.py query --question "..."` · `wiki.py add ...` · `wiki.py lint` | 薄入口，转发给真正的 owner skill |

> ⚠️ 现状：检索是**每次即时全文扫描**（够用于百级单元规模）；持久化增量索引与近义词扩展是已规划的后续增强。

## 3. 综述 / 趋势 / 方法分类　`literature-synthesizer`

| 你想做 | 怎么用 |
|---|---|
| 生成**综述** / **方法对比** / **方法分类树** | `synthesize.py survey --field "..."` · `review --query "..."` · `taxonomy` |

*原理*：跨已入库单元做聚合，产出落到 `kb/synthesis/`。（自动"空白点检测"是规划中的下一步。）

## 4. 想法 → 方法 → 实验　`idea-workbench` → `method-designer` → `experiment-workbench`

| 阶段 | 怎么用 | 说明 |
|---|---|---|
| **想法卡片**：捕获/生成/多候选/评审/选定 | `idea.py capture` · `generate` · `analyze` · `review` · `select` · `select-best` | novelty / feasibility / 最小验证路径分析 |
| selected idea → **方法设计** | `method.py design --idea-id <id> --program-id <p>` | 选 repo、定接口、展开实验矩阵 |
| **实验**：计划/记录 run/追踪/诊断/确认 | `experiment.py plan` · `log-run` · `follow-up` · `diagnose` · `confirm` | run-log（只记事实）/ diagnoses（AI 推断，待确认）/ follow-ups（行动）职责分离 |

## 5. 研究编排 —— "我现在该干嘛"　`research-orchestrator`

| 你想做 | 怎么用 | 原理 |
|---|---|---|
| 建/管一个研究 program | `orchestrate.py init-program` · `set-stage` · `status` | program 状态机 + workflow 文件 |
| **跨 program 仪表盘** | `orchestrate.py dashboard` | 一张表：每个 program 的 stage、阻塞证据数、高优问题数、事件新鲜度 |
| **下一步该做什么**（自动排序建议） | `orchestrate.py next` | 按 阻塞证据→高优问题→待确认→停滞阶段 排序 |
| 待解问题 / 证据需求**全生命周期** | `add-open-question`/`answer-question`/`drop-question`；`request-evidence`/`resolve-evidence`/`drop-evidence` | 问题和证据能被真正"关闭"，计数不再虚高 |
| 记决策 / 发事件 / 关联单元 / 路由任务 | `log-decision` · `add-reporting-event` · `attach-unit` · `route --task "..."` | 决策留痕；事件流是给周报的数据源 |

## 6. 确认门控 & 确认收件箱　`kb.py review-queue`

| 你想做 | 怎么用 | 原理 |
|---|---|---|
| **看有哪些在等我确认** | `kb.py review-queue [--kind ...] [--limit N]` | 跨所有单元收集 `pending_user_confirmation`，按时间排序，每条给一条可直接跑的确认命令 |
| **确认 / 提升**一个单元 | `kb.py promote --id <id> --confirmation-status confirmed --confirmed-by 你 --evidence <凭据>` | 盖章必须留人证+凭据；否则直接拒绝 |

*为什么重要*：整个系统靠"确认门"保证质量——收件箱让你**批量清账**，确认溯源保证"confirmed"确实是人认可的。

## 7. 报告与汇报　`report-author`

| 你想做 | 怎么用 |
|---|---|
| **周报 / 阶段总结 / PPT 素材 / 写作素材** | `report.py weekly` · `stage-summary` · `ppt-materials` · `writing-materials`（都 `--program-id <p>`） |

*原理*：从 program 的**事件流**读取，而不是重新编——所以只要过程里 emit 了事件，报告就能自动汇总。

## 8. 人类入口与本地浏览器　`research-navigator`

| 你想做 | 怎么用 |
|---|---|
| 刷新"我现在该看什么"的人面向页面 | `navigate.py refresh`（生成 `kb/user/` 下页面） |
| 看当前所有 program 状态 / 阅读清单 | `navigate.py current-state` · `reading-list` |
| 打开**本地浏览器 Workbench**（预览/编辑 md、底部终端、启动 Codex） | `open_kb_browser.py` |

*原理*：所有人面向页面都是从 canonical 数据**生成**的；浏览器编辑器只允许改 `.md/.txt`，不碰原始数据和 YAML。

## 9. 配置与治理　`research-config-manager` / `knowledge-base-manager`

| 你想做 | 怎么用 |
|---|---|
| 配资源画像 / 语言 / 自动化开关 / taxonomy 种子 / pool 策略 | `config.py init` · `show` · `set` · `toggle` · `set-taxonomy-seed` · `set-pool` |
| 初始化 / lint / 重建索引 / 治理 / 关联 / 版本 | `kb.py init` · `lint` · `index` · `rebuild-governance` · `govern` · `link` · `git-status`/`git-log`/`git-checkpoint` |

*原理*：config-manager 管"输入的偏好/种子"，kb-manager 管"统一 schema/索引/taxonomy/版本"，职责分开。

## 10. 讨论沉淀　`discussion-archivist`
把一次关键技术路线讨论（结论/权衡/待验证）存成 `kb/programs/<id>/discussions/` 下的 durable note：`archive.py archive ...`。

---

## 目录速览

```text
kb/
├── raw/         # 不可变原始 source bytes（入库时备份）
├── units/       # papers / repos / blogs / ideas / experiments 的 record.yaml
├── programs/    # 研究方向：state + 待解问题/证据/决策/事件流
├── synthesis/   # 跨单元综述 / 趋势 / 分类
├── config/      # 运行偏好、taxonomy 种子、candidate pool
├── user/        # 人面向入口页（生成的）
├── output/      # 导出产物
└── .runtime/    # 运行时缓存
```

---

## 最近新增（第 4 轮 Top 6）

这些是最新加进来的能力，上面已分散标注，这里集中列一遍：

- **确认收件箱** `kb.py review-queue` —— 一条命令看清所有待确认项 + 直接可跑的确认命令。
- **确认溯源** —— confirm/promote 必须带 `--confirmed-by` + `--evidence`，AI 不能自签。
- **程序仪表盘 + 下一步** `orchestrate.py dashboard` / `next` —— 跨 program 一览 + 自动排下一步。
- **问题/证据生命周期** `answer-question` / `resolve-evidence` / `drop-*` —— 能真正关闭，计数准确。
- **带排序的全文检索** `kb.py query` —— 连笔记正文都搜，按相关度排序（此前只匹配 5 个元数据字段）。

> 想看更完整的路线图（还没做的功能 / 优化 / 结构演进），见仓库根目录的 `OPTIMIZATION_PLAN.md`（Part B）。
