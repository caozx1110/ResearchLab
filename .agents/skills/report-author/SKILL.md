---
name: report-author
description: Generate self-contained weekly reports, stage summaries, PPT or writing materials, and evidence-backed paper outlines from program claims, events, evidence, and decisions.
---

# Report Author

> 协议参考：`.agents/lib/research/SCHEMAS.md#program-files` · `#experiment-files` · `#evidence-first-outputs` · `#ownership` · `#runtime`

把 program 的已确认 claims、逐字 evidence、reporting events 与 decisions 聚合成可独立阅读的报告材料。脚本只解析、聚合和校验结构；叙事、取舍与综合仍由 runtime agent 完成。

## 适用场景

- 周报、阶段总结、PPT 素材、写作素材。
- 论文提纲：本 skill 拥有 `outline` verb，不另建 paper-outline skill。
- 论文引用：自然语言请求导出当前 program 的 BibTeX，内部走 `bib`，不增加公开 `kb` 动词。
- 论文初稿：从当前 outline 和已确认 claim 准备七节待填结构，由 Agent 写正文、用户逐节确认后一次发布 Markdown / LaTeX / BibTeX。
- 面向导师或合作者的报告必须脱离本地对话和知识库导航也能理解。

## Agent Workflow

1. 读取 program 的 `state.yaml`、`workflow/reporting-events.yaml` 与 `workflow/decision-log.md`。
2. 从 `state.active_unit_ids`、event 的 `unit_id` / `*_ids` 字段及 unit artifact 引用收集关联 unit；只做 exact record lookup，不做模糊猜测。
3. 对每个 record 的 `payload.claims` 调用 `research.evidence.read_claims`；仅聚合 `confirmed` / `auto_confirmed` claims，并用 `validate_claims` 过结构门。
4. 将 claim 文本与 evidence ref 的 `source_unit_id`、`locator`、逐字 `quote`、可选 `summary` 一起写入材料；不把 essential evidence 留给读者自行打开。
5. 聚合固定 H2 decision blocks 与筛选后的 events。周报/PPT 先冻结 editorial manifest，再由 Agent 填写；不允许脚本生成进展、问题、结论或讲述叙事。
6. 任一输入缺失时保留明确的 `缺少：X`（显式英文模板为 `missing: X`）；禁止静默省略、补写或推测。
7. 按 workspace 统一偏好合同为本次 report operation 记录并加载 task-bound effective selection；task digest 由 owner 按 program、operation、stage、limit 与完整输入快照重算，不能由调用方传入。`weekly / stage-summary / ppt-materials / writing-materials / outline` 五个展示型 operation 的 consumed allowlist 都包含 `profile.preferences.language_preference` 与 `profile.personalization.reporting_style`。只有被 Agent 为当前任务选中的英文语言值才切到英文模板；未选择语言、只在 profile 配置英文、缺失或不可解析时一律使用产品默认中文。只有被当前任务选中的 reporting style 才控制展示量：包含“简洁”/`concise`/`brief` 时压缩 decisions、claims 与 events；包含“详细”/`detailed`/`full` 时保留完整输入；未选中时维持 neutral default。不得通过旧顶层字段或 canonical profile 直读 soft preference。报告持久化 selection/task/receipt digest 绑定，不复制偏好原值。精简模式仍保留 decisions、claims + evidence、events 三部分及全部适用的缺失标记。
8. Reporting events 默认 fail-closed：显式 factual/operational 事件可进普通区；decision/diagnosis/discussion conclusion/survey inference/novelty/evaluation 与未知未分型事件均视为 judgement。只有能经无 symlink canonical containment 解析 subject、binding 完全一致且 verification artifact 当前 bytes 仍匹配的 ConfirmationReceipt 才进入普通区；pending/rejected/stale 全部隔离到 `Pending / Unverified judgements`。
9. Survey inference 还必须通过 `consumer_binding` 的纯读 freshness 检查；新增匹配 unit、上游 content/evidence 变化、删除或 confirmation 失效时只进入 pending/stale 区，不得自动改写 survey 或继续当正式结论。
10. 初稿先确认已有 current `paper-outline.md`；准备阶段只创建七节空白 fill 和冻结 manifest，不替 Agent 生成正文。manifest 的 claim/bibliography/figure catalog 均来自 program 当前 exact 选择集，并在后续每个边界重验。
11. Agent 按段填写 plain-text prose、原 epistemic claim type、至少一个 current confirmed support claim ref、至少一个 stable citation key 和可选 stable figure ref；不得填写 raw LaTeX、虚构 citation 或绕过 frozen catalog。
12. 逐节核验后通过统一 `kb review` 向用户展示完整正文及引用，等待真人逐节确认。outline、上游 claim/receipt/evidence、citation metadata、figure index/assets 或 section bytes 变化都会使 pending/confirmation 失效，必须基于新快照重新准备或核验。
13. 只有七节全部 current confirmed 时才发布；Markdown、LaTeX、`references.bib` 与 publication manifest 必须在一个原子事务中一起成功或一起保持旧版本。
14. 周报使用私有 prepare→Agent fill→verify：固定“本周摘要 / 进展 / 问题与风险 / 下周计划”，每条 Agent 正文带 epistemic label 并引用至少一个 frozen support ref；pending/stale 只可作为 `problems_and_risks` 的显式 risk hint，不能冒充 formal support。
15. PPT 使用独立 slide-card fill：1–12 页，每页恰一条 Agent 结论、至少一条 evidence ref、可选 current figure refs、speaker note 与 transition。figure catalog 非空时整套至少引用一张；为空时必须显式说明缺图。PPT 不复用周报段落或 outline 七节。
16. editorial manifest exact 绑定 program state/events bytes、current claims/evidence/receipts、confirmed decisions、figure index/assets 与 task-bound presentation preference。prepare 保留仍绑定当前 manifest 的已编辑 fill；verify 在 render/write/commit boundary 聚合重验，任何 stale/tamper 均不得覆盖旧成品。

## Internal Verbs

- `weekly`：兼容用的机械 aggregate 底稿。新的自然语言周报请求默认必须走 `weekly-prepare` → Agent fill → `weekly-verify`，不得直接把 aggregate 当成成品。
- `stage-summary`：按 stage 筛选 events，同时保留关联 claims、evidence 与 decisions。
- `ppt-materials`：兼容用的机械 aggregate 底稿。新的自然语言 PPT 请求默认必须走 `ppt-prepare` → Agent fill → `ppt-verify`，不得直接把 aggregate 当成成品。
- `writing-materials`：生成真实的 Writing Claims & Evidence 与 program context。
- `outline`：生成 Introduction / Related Work / Method / Experiments / Results / Discussion / Conclusion 骨架；Related Work 必须携带 confirmed claims + evidence。
- `bib`：从 program 全量关联的 canonical paper citation metadata 导出去重、稳定 key、确定性排序的 `references.bib`；只搬运事实，不要求 deep-read judgement receipt，也不接受 raw BibTeX。
- `draft-prepare`：冻结 outline、program 选择集、current confirmed claims、citation 与 figure catalogs，生成七节空白 Agent fill。
- `draft-verify`：核验一节 Agent 正文及其 support/citation/figure refs，生成带逐字 evidence receipt 的 pending section judgement。
- `draft-export`：要求七节各自 current confirmed，原子发布 Markdown、LaTeX、BibTeX 与 byte-bound publication manifest。
- `weekly-prepare` / `weekly-verify`：私有周报编辑链；prepare 只建 current catalog + 空 fill，verify 校验 Agent 四区叙事 refs 后发布自包含周报。
- `ppt-prepare` / `ppt-verify`：私有 PPT 编辑链；prepare 只建 current catalog + 空 slide card，verify 校验一页一结论/evidence/figure/讲述顺序后发布。

这些 verbs 由 agent 内部执行。用户只需用自然语言提出报告需求；用户可见回复不得包含脚本路径、裸命令、flags、变量占位符或内部 next-step 指令。
一次自然语言周报/PPT 请求中，Agent 应自动完成 prepare、填写与 verify；只有缺少可引用输入或确需用户选择读者/范围时才暂停，不能把内部 fill 位置或参数交给用户续跑。
周报 fill 只改四区 `text`/`refs`；label 已按摘要=综合、进展=事实、问题=风险、计划=计划预填，status 由 owner 管理。成品不得出现 catalog ref、schema、receipt 或 claim/event 内部术语。

## Output Contract

- 报告正文按 decisions、claims + evidence、events 组成 self-contained triple，不再以 event log 充当报告。
- 周报成品固定为摘要、进展、问题与风险、下周计划及完整证据附录；PPT 成品固定为逐页结论、证据、图示、讲述与过渡。二者都与论文 outline 的七节结构不同。
- editorial 正文只来自 Agent fill；脚本只冻结 current catalog、校验 refs/epistemic label/文本安全并渲染。raw HTML/LaTeX、绝对机器路径、内部路径、裸 flags、模板变量、空白/未知/重复 refs 均 fail closed。
- 默认报告与 outline 的标题、章节、事件/决策标签、待确认区和缺失标记使用中文；只有当前 task receipt 明确选择英文语言值时才使用英文模板。
- `language_preference` 与 `reporting_style` 只控制展示，不改变输入筛选、claim 文本、逐字 evidence、subject identity、epistemic/confirmation 类型，不删除适用的缺失标记，也不生成补全文本。
- confirmed claim 的最小结构为 `id`、`text`、`claim_type`、`confirmation_status`、`evidence_refs`。
- evidence ref 展示来源 unit、locator、逐字 quote 与可选 context；空 evidence 用当前模板语言显式标缺。
- 无 events、decisions、confirmed claims、关联 record 或 outline section inputs 时分别用当前模板语言显式标缺。
- 不输出 raw commands 或内部路径作为用户下一步；需要推进时改写成自然语言或已存在的 `kb <verb>`。
- 不修改 source units、reporting events 或 decision log；报告是只读聚合后的派生产物。
- `*-confirmed` 名称或 `confirmation_status: confirmed` 字符串本身不构成信任；confirmed event 必须绑定 subject、claim ids、content digest 与 verification receipt。
- 初稿 section 是 `report-author` 拥有的 program side judgement，不是 source unit；固定七节各自确认，不存在整篇自签或“全部确认”状态降级。
- 初稿正文只来自 Agent fill；渲染器只做稳定排序、plain-text 转义、citation/figure key 投影。任一上游或 section receipt stale 时禁止覆盖现有发布件。

## Quality Gate

- 核对报告无需打开本地 artifact 即可理解核心 claim、证据、事件和决策。
- 核对 judgement 仍保留原 epistemic type 与 confirmation status。
- 核对缺失项明确、无 fabricated prose、无 raw command 泄漏。
- 核对七节 identity/path 唯一、每段有 support claim + citation、可选 figure ref current，且发布四件套 byte binding 一致。
- 核对 weekly 四区与 PPT slide cards 结构/内容明显不同；每条正文可追溯到 current support 或显式 risk hint，PPT 每页只有一个结论并有讲述/过渡。
- 最终提交前由 agent 把结构化底稿改写为自然、紧凑、面向目标读者的叙事。

脚本入口：`scripts/report.py`（weekly / weekly-prepare / weekly-verify / stage-summary / ppt-materials / ppt-prepare / ppt-verify / writing-materials / outline / bib / draft-prepare / draft-verify / draft-export，均使用 program identity）。

## 启动澄清（Agent 用）

- 读者与场合：导师周会、合作者还是自存档？默认导师周会。
- 周期与 stage 范围？默认最近一周、全部 stage。
- 体裁：周报、阶段总结、PPT 素材还是 outline？默认按用户措辞。
