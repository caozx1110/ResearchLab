# workspace-oss 重构蓝图 v1（2026-07-26）

依据：冷启动实测 + 黄金路径全测（36 条发现，见 `tmp/skill-review-2026-07-26.md`）、结构专项审计、`temp/what_i_need.md` 原始需求、`temp/SYSTEM_DESIGN_SSOT.md` 与 OPTIMIZATION_PLAN/BACKLOG 既有结论。
已确认约束：**个人为主 + 可开源**；**旧 kb 可全部丢弃**（schema 自由，不做迁移工具）；承重墙不动。

## 0. 一句话诊断

系统的"墙"（存储、校验、事务、确认）经 26 轮对抗加固已经过硬，但"门"（Agent 如何走进来）没有配钥匙：机制知识散落在源码里，错误消息双重脱敏，最重的治理仪式压在最轻的操作上——而"节省 token、避免反复读取"恰是 what_i_need.md 的第一层需求。重构主线因此是**做减法与配钥匙**，不是再加墙。

## 1. 不动清单（承重墙）

原子写 / journal / CAS / 精确路径锁；逐字 evidence 校验与 substance 门；快照绑定确认（AI 不可自签、当前消息授权）；prepare→fill→verify 三段范式；raw 不可变与 document.md 阅读层；免插件 Obsidian 投影与勾选表原子批次；来源感知更新。凡涉及"判断须人确认"的语义一律保留——分档只改确认的**粒度与批量方式**，不改"谁签字"。

## 2. 目标架构（四层）

- **L0 storage core（lib）**：现有模块保留，补三个洞——locator 位置校验（发现 12/23）、checkpoint 覆盖策略统一（发现 19，即其自家 T-CHECKPOINT）、reject 状态语义（发现 20）。god-file 拆分沿用其 T-GODFILE-v2 计划。
- **L1 owner skills**：20 → **14 个**（§3）。
- **L2 Agent 接口层（本次重构的核心新增）**：
  - `AGENT_GUIDE.md`（≤3k tokens，装进 .agents/）：flag 位置、`--apply-snapshot`/`--confirm-ref kind:id`/batch_ref 来源、corpus 引用规则、常用 owner 调用速查。一次写清，终结"每会话重付学费"（发现 3/13/25）。
  - next-step 协议结构化：现有 `NEXT FOR AGENT` 字符串升级为统一 schema 的机器可读字段（雏形已在 ingest 协议里）。
  - **所有** prepare 一律产出待填 scaffold（portfolio/monitor 补齐，发现 16）。
  - 错误双通道：公开层保持自然语言；私有协议必含"期望格式/失败字段/建议动作"（终结 tampered_or_unknown 式黑箱与静默 exit，发现 4/14/18）。
- **L3 用户面**：16 动词不变；新增 1 个候选动词 `kb history`（列最近操作+编号，喂给 restore，发现 15）——或并入 `kb status --history` 保持 16 不变。

## 3. Skill 处置表（20 → 14）

| Skill | 处置 | 动作 |
|---|---|---|
| kb-cli | **keep+拆** | dispatcher 205KB 拆模块；SKILL.md 从治理文改为"触发+流程+调用速查" |
| knowledge-base-manager | keep | core owner 不动，吸收 C 类修复 |
| source-intake | **keep+修** | doctor/bootstrap/intake 三方依赖探测对齐（发现 2）；`kb add` 支持多目标批量 |
| paper-analyst ┐ | | |
| repo-analyst ┃ | **合并 → unit-analyst** | 四个 analyst 的 SKILL.md 与 preference-consumer 段高度同构，脚本层本就共享 records/evidence。合并为一份契约 + 四套要素模板（paper 四要素/repo 三要素/dataset 四要素/blog 四要素不变）。省 3 份契约文与上下文 |
| dataset-analyst ┃ | | |
| blog-analyst ┘ | | |
| literature-search | keep | 真机联网验收后再动；schema 不变 |
| research-monitor | **keep+补** | apply 增加 scaffold；写一页"宿主定时任务对接"指南（Claude scheduled task / cron 调 `kb next`，发现 8 类） |
| research-orchestrator | **keep+减仪式** | ①prepare-next-selection 产 scaffold（含候选 id/绑定 digest 预填）；②**单候选 fast-path**：procedural 决策自动记录，免手写 YAML；③偏好回执在个人档降为可选（§5），9 步循环收敛到 1–2 步（发现 11） |
| literature-synthesizer | keep | 不动 |
| idea-workbench | **keep+修** | 静默失败清零（bare SystemExit 全部带话）；`--input` 语义与 blog/repo 对齐；corpus 扩展入口（"把 r-xxx 加入本次分析语料"）+ 违规消息里列出可引用清单（发现 18）；slug 接受 Agent 提供的 ascii 别名（发现 8） |
| method-designer | keep | 不动 |
| experiment-workbench | **keep+扩** | G4 实验导入（§4）；log-run 输出补自然语言与 checkpoint（发现 10/19） |
| report-author | **keep+扩** | G1 引用管理 + G2 分节成稿（§4）；outline 的 repo 证据行补文件路径（发现 23）；"未确认"措辞修正（发现 6） |
| research-config-manager | **slim** | 偏好三档（§5）；record-effective 参数改文件路径+修 traceback（发现 14） |
| discussion-archivist | keep | 116 行，成本可忽略 |
| skill-evolution-advisor | **slim+对接** | 本地 issue 脱敏分档：本地日志记录错误类别/owner/操作/返回码明文（不含正文），导出才走强脱敏（发现 21）；与 dev-docs 化的 BACKLOG 流程打通——这是你"不定时完整优化"的原料管道 |
| wiki-adapter | **drop** | 94 行脚本配 3.6KB 契约文，泛 wiki 意图并入 kb-cli 路由表 |
| research-navigator | **移出 bundle** | dev-only 却背着全仓最大文件（xterm.js 489KB）且装进每个用户工作区（发现 30）。挪 tools/ 或独立仓库 |

## 4. 缺口补齐（对齐你的目标清单）

按建议优先级排序：

- **G1 引用管理（缺口，你清单里有）**：paper unit metadata 补 DOI/arXiv id/bibtex 字段（intake 时抓取）；report-author 增加 `bib` 输出（从 program 引用的 paper units 生成去重 .bib，citation key 稳定）；自然语言"把本文引用导出 bib"路由之。约 2–3 天。

  **R3 实现锁定（2026-07-27，bibliography）**：不新增公开 `kb` 动词；`report-author` 增加私有 `bib` operation，自然语言仍由 Agent 路由。paper `basic_info` 继续是 title/authors/year/venue/DOI/arXiv 的事实 SSOT，只增加由 canonical paper id 机械派生的 `citation_key` 与不重复上述字段的白名单 `bibtex` 补充元数据；旧 record 缺 key 时导出器只读派生，不迁移。DOI 规范化为无 scheme/prefix 的小写 identity，arXiv 去掉 `vN` 作为 work identity，精确版本仍只由 source URI/material binding 保存。key 固定为 `cite_<sanitized-unit-id>`，不依赖作者、题名、年份、program 顺序或库中碰撞顺序。intake 只从已归档 HTML/PDF bytes、staged candidate identity 和 canonical source URI 机械提取/合并；强 identity 冲突 fail closed，不请求 Crossref/OpenAlex/付费 API，也不接收 provider raw BibTeX。

  `.bib` 由结构化白名单字段机械转义/渲染，拒绝换行、macro 或新 entry 注入；选择集来自 program state + 全量 reporting events 中的 canonical paper ids，不受周报 stage/limit 截断。去重仅按 DOI、versionless arXiv、canonical source URL 的传递闭包；无强 identity 时退到 unit id，绝不用 title+year 硬合并；同一连通组含冲突 DOI/arXiv 或 key 冲突即拒绝。导出绑定 program state/events exact bytes、完整选择集与每个 paper record snapshot，在 render 后、write 后和 transaction commit boundary 聚合重验；输出 `kb/output/<program-id>/references.bib`，排序/字段顺序固定、重复导出字节一致。bibliography 是 factual metadata，不错误依赖 deep-read judgement ConfirmationReceipt；缺失字段显式留空/报告，不伪造类型或 venue。
- **G4 实验导入**：`experiment.py import-runs` 接受 wandb export JSON / CSV / 目录约定，批量生成 log-run（fingerprint 机制沿用，来源标 imported）。没有它，实验归档必然退化为手工口述。约 2–3 天。
- **G3 检索升级**：保 FTS5 词法为底座；新增 **context-pack**：给定问题 → find 检索 + 相关 unit 的 confirmed claims/摘要组装成一个带 locator 的上下文包（喂给 Agent 讨论/写作，直接服务"AI 基于库讨论 idea"与省 token 目标）。跨语言语义检索列为可选后续（不做硬依赖，守零付费承诺）。约 3–5 天。

  **R2 实现锁定（2026-07-27）**：不新增公开动词；现有 `kb find` 在私有 Agent protocol 中附带只读、临时的 `context-pack/v1`。候选顺序复用同一轮 FTS5 / deterministic fallback 检索，不做 query 改写、embedding、总结或相关性判断。正式内容 lane 只搬运 `confirmation_status=confirmed`、当前 ConfirmationReceipt 覆盖且 evidence/record snapshot 仍 current 的 canonical claims，并保留逐字 quote 与 locator；不能把顶层状态字符串当可信证明。摘要与 passage excerpt 因不在 ConfirmationReceipt 的 claim scope 内，只能作为明确标注 `confirmation_bound=false` 的导航提示，绝不冒充已确认结论。固定上限为 5 个 unit、每 unit 3 条 claim、每 claim 2 个 evidence ref，并用 6000 UTF-8 bytes 的保守预算做原子裁剪（claim/quote 不截断）；超限、stale、pending、rejected、重复 id 或不完整 locator 均 fail-closed 排除并计数。输出前聚合重验 snapshot；包不落 canonical KB、不进入 Git/Obsidian/确认门，idea/report 等下游正式产物仍走各自 verify/confirm/current gate。
- **G5 批量与园艺**：`kb add` 多目标；review 个人档支持一次 >3 条（治理档保 Top-3）；"园艺"自然语言路由（清 pending 积压、重建 stale survey、taxonomy 重整），不加新动词。约 3 天。
- **G2 论文成稿**：outline → 分节草稿工作流：每节绑定 claims/evidence，Agent 起草、节级确认，导出 LaTeX/Markdown 到 output/（引用 key 与 G1 联动）。约 1 周。

  **R3 实现锁定（2026-07-27，section draft）**：`report-author` 拥有 side judgement kind `paper_draft_section`；固定 canonical 目录为 `kb/programs/<program-id>/reports/paper-draft/`，其中 manifest 绑定 exact `paper-outline.md` bytes、固定七节有序 identity、可引用的 current confirmed source claim catalog、G1 bibliography catalog 与 G7 figure catalog；`fills/<section-id>-fill.yaml` 是 Agent authoring scaffold，`sections/<section-id>.yaml` 是独立待确认 judgement。prepare 只搭空段落结构；Agent 为每段填写 prose、epistemic claim type、source claim refs、citation keys 和可选 figure refs。verify 不判断文意，只机械验证段落非空、每段至少一条 current confirmed support claim、逐字 evidence、引用/图 key 存在且 current，并从支持 claim 搬运 evidence refs，生成 canonical pending claims、verification receipt 与上游 anchor。不得让脚本据 outline/claims 自动写论述，亦不得接受 raw Agent LaTeX。

  每节通过统一 `kb review` 单独真人确认，ConfirmationReceipt 绑定 prose、support/citation/figure refs、verification 与 exact 上游 digests；outline/source record/receipt/evidence/bib/figure 任一变化使该节 stale。最终 export 只接受七节全都唯一、current、verified、receipt-confirmed，按 manifest 顺序机械渲染 UTF-8 Markdown 与安全转义 LaTeX，并连同当前 `references.bib` 和 publication manifest 在同一 recovery transaction 原子发布到 `kb/output/<program-id>/paper-draft.{md,tex}`；render 后、write 后、commit boundary 均聚合重验，缺节、pending/rejected/stale 时零 publication write。每节可以独立重填/重验/重签，不能用 context-pack 或整篇顶层状态替代 receipt 验证。
- **G6 批注回流**：Obsidian inbox/annotations 的人写笔记 → 结构化 pending 条目（signer=你本人，走同一确认门），人写的知识不该比 AI 写的更难入库。约 2–3 天。

## 5. 治理分档（复杂度税的核心减法）

新增 workspace 级 `governance_profile: personal | strict`（默认 personal，安装时可选；strict 即现状语义，供开源多人场景）：

| 机制 | personal 档 | strict 档（现状） |
|---|---|---|
| 偏好分发 | hard constraints 由脚本兜底强制；soft 偏好=一份已确认清单，Agent 任务前读一遍，**免 receipt** | eligible view + accounted receipt + digest 绑定 |
| PortfolioDecision | 单候选 fast-path 自动记；多候选写 rationale 免 receipt | 全仪式 |
| review 批量 | 可 >3 条/批，卡片有效期可配 | Top-3 + 24h |
| D1 脱敏 | 本地日志明文类别/owner/返回码 | 现行强脱敏 |
| 确认签字 | **不变**：判断仍须你签，AI 不可自签 | 同左 |

原则：分档只降"仪式成本"，不降"证据与签字"。

**R1 实现锁定（2026-07-27）**：新 workspace 显式落 `personal`；已有 runtime preferences 缺失/非法 profile 仍解释为 `strict`，避免升级静默降档。strict 固定 Top-3 + 24h；personal 默认每批 10 条、`review.card_ttl_hours` 可配 `1..168` 小时。effective profile/limit/expiry 必须冻结在一次性 snapshot，apply 不重读可变配置；真人 signer、当前消息授权、逐字 evidence、content binding/CAS 与原子批量两档相同。personal 的 local-only D1 只额外保留规范化 category/owner/operation/return_code，所有自由文本仍脱敏；strict 保持现状，任何导出始终强脱敏。

## 6. 结构清理（一次性，半天）

1. `temp/` 高价值文档（SSOT、what_i_need、BACKLOG、OPTIMIZATION_PLAN、审计与验收报告、codex_prompt 全集）→ 入库为 `dev-docs/`（git 追踪；发现 29）；
2. `tmp/` 清空回收 4.7GB；temp/tmp 合并为单一 scratch；
3. `.learnings/` 有效条目并入 dev-docs 后删除；空的 `.worktrees/`、`.claude/worktrees` 删除；
4. 测试树移仓库根 `tests/`（发现 33）；
5. navigator/wiki-adapter 按 §3 摘除；20 份 openai.yaml 改构建生成；
6. 新 kb 存储策略：raw/ 不入 git（单独备份）或 LFS；repo 类 unit 浅克隆/引用式存储（发现 32）；
7. 文档去重：rc 状态与成熟度表单一事实源（发现 35）。

## 7. 行为级回归（重构的方向盘，先于一切大改）

把本次 review 的黄金路径固化为脚本化 golden suite（约 8 条：install→init→ingest md/pdf/repo→fill/verify→find→review 对话/Obsidian 两路→next→weekly/outline→undo/restore），每条记录：步数、失败次数、耗时、加载规则 token 估算。跑法沿用你们的"冷 Agent 验收"传统，但入 CI 可重复。**M2 起每个里程碑用它验收**；上下文税指标目标：单任务规则文本 ≤8k tokens（现 15–25k），黄金路径零"机制摸索失败"（现 6+3 次）。

## 8. 分期计划

| 里程碑 | 内容 | 量级 |
|---|---|---|
| M0 | §6 结构清理 + golden suite 骨架 | 0.5–1 天 |
| M1 | 两个冷启动阻断：安装错误透传 + 非 git 源 fallback（发现 1）；PDF 依赖三方对齐（发现 2） | 1–2 天 |
| M2 | L2 接口层：AGENT_GUIDE、错误双通道、scaffold 补齐、--input 统一、静默失败清零、kb history | 1–2 周 |
| M3 | C 类校验强度：locator 位置校验、checkpoint 策略、audit/关系规则一致、reject 语义、slug | 1 周 |
| M4 | §5 治理分档 + §3 analyst 合并 + §4 缺口（建议顺序 G1→G4→G3→G5→G2→G6） | 2–4 周 |
| M5 | 真机验收：真实 arXiv/HTML 来源、Obsidian Reading view、literature-search 联网；golden suite 全绿 → 冲 0.2.0 正式 tag | 3–5 天 |

M1/M2/M3 可并行分轨（沿用你们的 worktree track 模式）；M4 依赖 M2 的接口层先行。总量级：**全职约 4–6 周**；按你"不定时投入"的节奏折算 2–3 个月自然时间。

## 9. 风险与明确不做

不改确认门语义（判断永远人签）；不引入任何付费/API 依赖；不做跨语言 embedding 硬依赖（context-pack 先行）；不做旧库迁移工具（已决定重建）；strict 档保留完整现行为，开源承诺不降级。最大执行风险是 M4 的 analyst 合并触碰 1,866 项测试的存量断言——建议合并只动 SKILL.md 与入口路由、不动 lib 层数据结构，把测试改动面压到最小。

---

# 蓝图增补 v2：需求基线与工作包修订（2026-07-26，与用户当面对齐）

temp/what_i_need.md 已确认过时，原 v1.1 增补整体撤回。以下以用户 2026-07-26 的两段需求表述 + 四项当面决定为准。

## 10. 需求基线 v2（14 条）

**建库与阅读**：①方便入库整理论文/blog/repo，原始材料完整保留；②自动提取核心概念；③辅助论文阅读+快速回顾要点；④记录用户产生的想法；⑤AI 生成+用户确认的深加工材料（综述、知识理解报告等）。
**检索与讨论**：⑥快速检索关键信息/论文/代码；⑦理清发展脉络与趋势；⑧基于知识库有理有据地讨论 idea/技术路线、发掘 idea。
**落实与产出**：⑨落实 idea→方法构思；⑩归档并分析实验结果；⑪论文大纲→初稿+拉取引用；⑫随时撰写周报/工作报告。
**横切**：⑬交流中轻量记录用户偏好；⑭记录 skill 可优化点，支撑不定时完整优化。

## 11. 四项当面决定（2026-07-26）

1. **概念层 = 一等公民**（G13，≈1 周）：每个核心概念一页——定义（带逐字出处）+ 涉及它的论文/repo/blog + 关联 idea；进入 kb find 索引与 Obsidian 图谱，成为知识库的横向索引。落库 `kb/synthesis/concepts/`（或 units 新 kind，施工时定）；概念判断类内容仍走确认门。

   **R2 实现锁定（2026-07-27）**：选择 canonical unit 新 kind `concept`，落 `kb/units/concepts/<c-id>/record.yaml`，由 `literature-synthesizer` 生成，但不进入只接外部来源的 source-intake。ID 使用 `c-<compact-slug>-<digest>`；`payload.concept` 绑定定义、边界/别名与关联清单，顶层 `links` 仅作它的机械关系投影，两者在 verify 时必须一致。`concept prepare` 只创建 Agent 待填 scaffold，要求显式选择至少 3 个当前、唯一、非 rejected canonical unit；脚本不提炼概念。Agent 填定义/边界/每个关联的角色说明与逐字 evidence；`concept verify` 逐项校验来源 snapshot、quote+locator、关联目标和填充实质，生成 canonical claims + verification receipt，并以 `pending_user_confirmation` 写入 concept unit。定义及关联判断都纳入 ConfirmationReceipt 内容摘要，AI 不可自签；公共 `kb review` 复用 generic unit snapshot/CAS/真人授权合同，内容或证据变化自动失效。只有确认后才作为可信概念判断供 context-pack/正式报告消费；`kb find` 可检索 pending 页但必须显示待确认状态。通用 passage 索引、关系投影与 Obsidian unit page 复用 canonical unit 基建；概念页额外把定义和关联清单显式渲染出来。旧库不迁移。
2. **代码检索入索引**（G14，≈3–4 天）：repo 源码进 FTS5（文件/符号级），`kb find` 一个入口同时召回论文段落与代码位置，结果带 file:line；与概念页联动（概念→代码实现位置）。
3. **移除论文快筛**：入库即深读。quick_screen 的"值得细读"判断及其确认整体砍掉；`paper_type`（决定笔记要素集）并入深读 prepare 由 Agent 填写。paper 流程缩短一段，少一次确认打断——本身就是减法项（≈1 天改造）。

   **R1 实现锁定（2026-07-27）**：`complete-note prepare` 生成一个统一待填结构，包含空 `paper_type`、分类理由/逐字 evidence 与 method_system/benchmark/survey 三个要素分支；Agent 只填所选分支。verify 同时验证类型与对应五要素、拒绝未选分支内容，并把类型落 `payload.deep_read.paper_type`、生成独立 paper-type claim；新 unit 无类型不得 method_system 兜底。旧 `quick_screen.paper_type` 仅兼容读取。`kb ingest` 直接到 note prepare；`kb add` 按 `link_autodrive` 选择轻量入库+一次询问或复用完整 ingest 链。`auto_screen` 从默认值、init、配置展示与新路由中删除。
4. **报告与产出全量投入**：周报/工作报告编辑层（"进展/问题/下一步"叙事，≈2–3 天）+ 论文大纲→初稿+引用（G1+G2，≈1.5 周）+ PPT 素材差异化（每页一结论+证据+讲述顺序，≈2 天）+ 图表提取可引用化（G7，caption/编号索引，≈3 天）。

   **R3 实现锁定（2026-07-27，G7 figure references）**：每个 paper 的 `figures.yaml` 是 `figure-index/v1` SSOT，保存 source artifact digest、extraction settings、逻辑 entry 与内容哈希 asset binding；paper `payload.figures` 只机械投影 index artifact/digest、available ref keys 和 Agent 选择的 `key_figure_refs`，不得复制另一套 caption 数据。稳定 key 优先绑定论文 id + 类型 + 规范化 caption 编号（`fig:<paper-id>:fig:<number>` / `...:tbl:<number>`）；确实无编号时使用 page + caption digest 的显式 fallback。重复 panel/continued caption 合并为一个逻辑 entry 并可挂多个 asset；同 key 不同 caption/类型冲突 fail closed。crop 文件按 PNG sha256 落 `figures/assets/<sha256>.png`，遍历顺序和重跑不改变 ref key 或 asset path。

   caption/编号/页码/图像哈希是机械事实；提取本身不得把所有 asset 自选成“关键图”，不得改写已有判断 claim，也不得把整篇 paper confirmation 降为 pending。Agent 只在需要写作的 claim/草稿中显式选择 figure ref，该选择随相应 judgement ConfirmationReceipt 一起确认。所有消费端先重验 source/index/asset bytes：索引 caption/ref key 进入 find，Obsidian 和 report/draft 只展示 current entry；asset 缺失/篡改、source 或 index digest 漂移均 fail closed，不回退到 traversal filename。旧 figures shape 只可读为未绑定历史提示，重新 extract 后才获得正式稳定引用。

## 12. 对 v1 蓝图的修订

- **不变**：A–D 四类修复、治理分档、20→14 合并、M0–M3、golden suite 先行；G1/G2/G3/G4/G5/G6 全部保留。
- **降级/移除**：G9 配置面板 → 缩为轻量偏好记忆（现有 pending→confirm 机制即可，砍面板）；G10 idea 联网新意核查 → 可选项（默认基于库内讨论）；G11 六维筛选 → 取消（并连带移除现有快筛步骤）；research-monitor → 维持现状不投入；G12 → 只保留 repo 的代码链接/对应论文抓取（服务概念页与代码检索联动），license/活跃度等不做。
- **新增**：G13 概念层、G14 代码检索（如上）。论文伴读维持"对话内带证据答疑"模式不新建落盘产物；快速回顾由笔记+概念页承担——若使用中觉得不够再立项。
- **M4 工作包修订后建议顺序**（价值先落地）：G14 代码检索 → G13 概念层 → G1 bib → G4 实验导入 → 周报编辑层 → G3 context-pack → G7 图表 → G2 成稿 → PPT 差异化 → G5 批量园艺 → G6 批注回流 →（可选 G10）。
- **量级更新**：M4 由 2–4 周扩为 **4–6 周**（新增 G13/G14/报告全量 ≈ +2–3 周，快筛移除 −少许）；全项目全职约 **6–8 周**，按不定时投入折算约 3 个月自然时间。M0–M3 不变，仍建议先行。

## 13. 覆盖结论 v2

需求基线 14 条中：现系统已覆盖 9 条主体（①③④⑤⑦⑧⑨⑩⑬部分），蓝图 M0–M4 修复其可用性；②⑥(代码)⑪⑫ 由 G13/G14/G1+G2/报告编辑层补齐；⑭ 由 skill-evolution-advisor 减法改造 + dev-docs 化的 BACKLOG 流程承接。基线之外不再按旧文档扩需求。

## 14. 交互体验章程（精选 10 条，随 M2 落地）

从 17 条候选中精选。载体：全局条目进 `AGENT_GUIDE.md` 交互章程节（≤1.5k tokens）；场景条目写进对应 SKILL.md 的"启动澄清清单"；golden suite 加人工评分维度（该问的问了、不该问的没问、收尾格式对）。合计 ≈2–3 天，全部在 M2 内顺路。

1. **启动澄清清单**：每个 owner skill 带 2–4 个高价值边界问题+默认值（综述：时间窗/库内 or 补检索/深度；伴读：读法节奏；idea 讨论：目标与挑战强度）。"默认即可"永远合法；选择题优于问答题（2–4 个带默认的选项，不甩开放问题）。
2. **讨论前复述理解**：idea/技术路线讨论开场，先三句话复述所理解的问题与目标供纠偏；含糊术语先对齐定义，对齐结果落概念页（与 G13 闭环）。
3. **观察式偏好询问**：同类产出被连续修改成同一形态、或被明确纠正时，在任务收尾攒批问"要记为偏好吗"（一次 ≤2 个）；应用偏好时低频轻声说明。绝不开局问卷、绝不打断心流。
4. **大活先报价再小样**：预计要读多篇材料/长耗时的任务，先报量级并默认拿小样本试做，点头再全量。
5. **伴读三段式**：三句话地图（讲什么/结构/建议读法）→ 按用户节奏答疑、回答带 locator 可跳原文 → 读完询问"要点落笔记吗"。**落库是询问，不是自动**。
6. **口头信息类型区分**：讨论中每个论点标"库内证据 / 我的推断 / 需实验验证"——信息类型体系从 YAML 延伸到对话姿态。
7. **技术路线讨论三栏**：维护"当前共识 / 分歧点 / 待验证"，每告一段落复述一次，散会询问是否归档（discussion-archivist 主动触发点）。
8. **开场接续感**：新会话首句主动给"上次进行到 X，待拍板 Y 件，继续还是做别的"（消费 kb status/next 既有数据）。
9. **固定四行收尾**：做了什么 / 落了什么盘 / 哪些等你确认 / 建议下一步。
10. **入库与中断的静默礼仪**：丢链接默认轻量入库+两行简报+一句"要深读吗"，批量绝不逐个问；用户中途换方向时挂起流程并告知"说'继续刚才的'即可恢复"。

未入选条目的去向：术语对齐并入第 2 条；纠偏即记忆并入第 3 条；挑战强度改为 init 偏好（§15）；token 可感并入第 9 条收尾（低频附一句"本次复用库内笔记未重读原文"）；实验零口述已属 G4 交互面。

## 15. kb init 交互偏好扩展（与快筛移除联动）

现状 quick-setup 已问：署名、语言与术语风格、研究方向、资源与重要约束，并展示版本记录/论文自动初筛默认值——保留这个"约 1 分钟、可整体默认"的渐进式框架，做两处改动：

1. **新增两问**（进同一紧凑回合）：
   - **自动化档位**：丢给我链接后——A 轻量入库+问我是否深读（默认）/ B 自动深读到待确认笔记；
   - **讨论风格**：讨论 idea 时——A 严格挑刺（魔鬼代言人）/ B 帮我完善 / C 看情况自适应（默认）。会话中可随时临时改（"这轮往死里挑"）。
2. **联动修改**：快筛移除（§11 决定 3）后，原"论文自动初筛"默认值展示废弃，由"自动化档位"取代其位置；`auto_screen` 配置项随 G11 移除一并退役。

两问均写入偏好档案供交互章程消费（第 1/4/5 条读自动化档位，第 2/7 条读讨论风格）。init 总时长仍控制在约 1 分钟。
