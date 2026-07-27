---
name: paper-analyst
description: 为 core paper unit 备料（解析源、产出待填结构）并校验 agent 填入的理解与证据，再过实质门确认。脚本不理解论文，理解由 runtime agent 填。
---

# Paper Analyst

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#unit-payload` · `#evidence-claims` · `#confirmation-gate` · `#runtime`

当任务是在分析某个 paper knowledge unit（而不只是入库）时，使用这个 skill。

## 第一性原理（SSOT 原则1 / §3.2）

**理解来自 agent，脚本只做搬运 + 验证。** 脚本负责：解析源、产出「待填结构」、逐字校验 agent 填入的每条判断带合法 evidence、过实质门、落盘。脚本**绝不**产出「这篇论文说了什么 / 属于哪类 / novelty 强不强」这类判断——那是 runtime agent 的活。deep read 是**两阶段**：脚本 `prepare` 出统一待填骨架 → agent 在会话里选择论文类型、填写理由与对应五要素并挂证据 → 脚本 `verify` 校验后落盘。

`runtime.paper` / `runtime.pdf` 是 soft preference catalog：只有与 paper id、operation、phase/mode、source/basic-info canonical inputs 绑定且 current 的 effective selection 才可改变对应操作；无 receipt 使用 neutral defaults，禁止直读 runtime soft 字段。写入 record 的 preference binding 只含 selection/task/receipt digest；`runtime.autonomy.auto_execute_scope` 作为 hard governance fallback 仍直接执行，且不能关闭 evidence、confirmation、containment 或 recovery。

## 负责范围

1. 从 `source-intake` 创建的 paper unit（已带完整 `source/document.md` 阅读层和兼容 parse-cache）出发。Agent 先读 Markdown 形成整体理解；需要核验逐字引用与既有 locator 时读 parse-cache，转换降级或细节缺失时回退原 PDF/HTML。
2. `complete-note --phase prepare`：不经过 quick screen，直接产出统一 deep-read scaffold。`paper_type / paper_type_reason / paper_type_evidence_refs` 留空，三套五要素分支全部存在且内容留空。
3. Runtime Agent 依据材料选择 `paper_type ∈ {method_system, benchmark, survey}`，填写分类理由与逐字 evidence，只填写对应分支的五要素；未选分支保持空白。
4. `complete-note --phase verify`：同时校验类型 evidence、所选五要素与未选分支为空。全过才生成独立 `claim-paper-type` + 五条要素 claims，将类型写入 `payload.deep_read.paper_type`，并写 `note.md` + `core_content`；任一类型/理由/要素空、无据、造据或跨分支混填都拒绝。
5. `prewarm-cache` / `extract-figures` / `refresh-structure`：纯机械搬运（解析、裁图、结构提示）。`extract-figures` 按 caption 编号产生稳定 ref key、按 PNG 内容哈希发布 asset 并写 `figure-index/v1`；它不得自选关键图，不得因机械提取而改写判断或降级整篇确认。
6. AI judgement 默认保持 `pending_user_confirmation`；类型与五要素作为同一份 deep-read 判断一起确认。

Markdown 阅读层中的图片只提供本地、可引用的源材料。脚本不得从图片文件名、alt text 或 OCR 片段自动生成论文判断；runtime agent 若使用图表内容，仍需在会话中实际阅读并挂可核验 evidence。

`figures.yaml` 的 caption/编号/页码/字节哈希都是机械事实，不是对图意义或重要性的判断。Agent 只在实际写作 claim/草稿中显式选择 ref key，该选择随所属 judgement 的 ConfirmationReceipt 一起确认。find、Obsidian 与写作消费端只使用通过 source/index/asset 字节重验的 current entry；缺失或篡改时不回退到遍历文件名。

## 按论文类型的五要素契约（runtime agent 照此填）

- `method_system`：motivation / method / experiment / limitation / insight
- `benchmark`：motivation / task_design / metrics / coverage_limitation / insight
- `survey`：scope / taxonomy / trends / gaps / insight

类型分类来自 runtime agent 的 deep-read 判断；脚本只提供槽位、校验枚举并选择结构，绝不根据关键词猜类型。旧 record 可只读 `quick_screen.paper_type` 并继续旧扁平 note fill，但不得写回该字段；新 unit 必须提供类型理由与 evidence，不得借兼容路径兜底。

每个 required element = 一条 judgement-class claim，**必须**带 ≥1 条 `evidence_refs`：

统一 fill 顶层先填写 `paper_type`、`paper_type_reason` 与至少一条 `paper_type_evidence_refs`；随后只填写 `element_sets.<paper_type>` 下的五个 element。每个 element 包含 `claim_type / content / evidence_refs`，其中 evidence 必须含当前 paper id、`parse-cache.yaml`、page/section locator 与短逐字 quote。

落盘映射：

- `method_system`：motivation→`core_content.motivation`；method→`core_content.method`；experiment→`core_content.changes_and_effects`；limitation→`critique.weak_spots`；insight→`core_content.why_it_might_work`。
- `benchmark`：motivation→`core_content.motivation`；task_design→`core_content.method`；metrics / coverage_limitation→`core_content.changes_and_effects`；insight→`core_content.why_it_might_work`。
- `survey`：scope→`core_content.motivation`；taxonomy→`core_content.method`；trends / gaps→`core_content.changes_and_effects`；insight→`core_content.why_it_might_work`。

所选五要素同时渲染进 `note.md`；每种类型都写入 `core_content`，因此实质门仍按原规则工作。

## 用户入口

- `kb ingest <论文来源>`：入库并直接进入 deep-read prepare；Agent 在同一流程完成类型与五要素填写/核验。
- `kb review`：展示待用户确认的类型与完整笔记判断。

## 启动澄清（Agent 用）

- 是否现在深读？`ask_first` 配置下先问；一旦选择深读就完成类型适配的五要素笔记。
- 侧重方法、实验还是局限？默认全面均衡。
- 深度：默认读 document.md 并用 parse-cache 核对引用；需图表细节再回 PDF。
