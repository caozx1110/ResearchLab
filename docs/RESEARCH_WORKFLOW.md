# 科研工作流完整指南

> **给科研人员**：这套 skills 能可靠地帮你做什么，哪些必须你把关。<br/>
> 目标：让你把精力花在**判断、选择、设计**上，把**提取、整理、汇总、追踪**交给 AI。

**使用方式**：你用自然语言跟 AI 对话，AI 调用这些 skills 完成任务。本文档列出"你可以这样对 AI 说"的意图清单。<br/>
**快捷方式**：少数高频动作可以直接对 AI 说 `kb help` / `kb status` / `kb review` 等（见文末"快捷命令"一节）。

---

## 核心分工（AI 做什么 vs 你做什么）

### ✅ AI **可靠**自动完成的事（质量稳定，无需逐条审）

1. **提取事实信息**：论文标题/作者/年份/引用/链接、代码仓库 README/依赖/API 边界、博客关键点 → 结构化存进 `kb/units/`。
2. **去重**：新加的论文/仓库与已有的自动去重（按 DOI/URL/标题相似度）。
3. **索引/检索**：全文检索、wikilink 跳转、按主题/tag/候选池筛选 —— 秒级响应。
4. **跟踪待办**：experiment 的 follow-up、program 的 open-question、review-queue 里的待确认项 —— 自动维护，不会漏。
5. **Git 备份**：每个写入可配成自动 commit 进 `kb/.git`（默认 milestone 模式 —— 大动作才提交）。
6. **产物路径管理**：提取的 figure、裁出的 table、生成的周报 markdown、PPT 素材 → 全在 `kb/` 下，有索引，不散落。

### ⚠️ AI **需要你确认**的事（默认 `pending`，进确认收件箱）

AI 写的这些是**推断/评估/意见** → 默认 `pending_user_confirmation`，进确认收件箱供你批量审：

- **论文筛选结论**（quick-screen 的"值得读"判断 + 理由）
- **idea 评审**（review 的"可行性/新颖性/难度"评分 + 建议）
- **experiment 诊断**（likely_causes / ruled_out / unknowns）
- **仓库复用判断**（某个 repo 是否适合你的场景）
- **综述归类**（taxonomy 的主题树、literature 综述的趋势判断）

**你审过、确认了，这些才算"定论"** → 之后 report/周报/PPT 会引用。AI 不能自签。

### 🔴 **只有你能做**的四件事（AI 不动，必须你亲自决策）

1. **选最终 idea**（AI 会给候选 + 评分，但**最终拍板是你**）。
2. **设计关键参数**（method 设计的实验矩阵 AI 会起草，**实际跑哪组超参 / 哪个 baseline 你决定**）。
3. **判定实验结论**（AI 写 diagnosis，你确认才算定论）。
4. **推进科研阶段**（AI 会建议 next action，**何时从"探索"转"验证"你决定**）。

---

## 完整工作流（按场景）

### 场景 A：扩充知识库（加论文/仓库/博客）

**目标**：把外部材料变成可检索的知识单元。

#### 你可以这样对 AI 说

> "加这篇论文 arXiv:2301.12345 到知识库"<br/>
> "把 GitHub 仓库 user/repo 加进来"<br/>
> "入库这个博客 https://blog.example.com/post"

→ AI 自动去重、提取元信息、结构化存储。

> "筛选最新加的论文，哪些值得读"<br/>
> "给论文 transformer 的那篇做快速筛选"

→ AI 生成 quick-screen（是否值得读 + 3 句理由），默认 `pending` 进确认收件箱。

> "我要确认筛选结论"（或 `kb review`）<br/>
> "批量确认所有待审的筛选，evidence 是 decision-log"

→ 你批量审 AI 的筛选结论（可选 --all-reviewed 全过），需提供 evidence 溯源防盲签。

> "给那篇 transformer 论文生成完整笔记"<br/>
> "扫描 pytorch 仓库的结构"<br/>
> "总结刚加的那篇博客"

→ AI 生成完整笔记 / 结构扫描 / 总结（耗时，仍 pending 你审）。

**AI 做了什么**：去重、提取元信息、快筛（给理由）、结构化存储。<br/>
**你做什么**：① 批量审 quick-screen（或信任 AI 全过）；② 决定谁进 candidate pool（后续 idea/method 会读）。

---

### 场景 B：迭代 idea（从模糊想法 → 可验证问题）

**目标**：把"我觉得可以试试 X"变成"问题定义 + 核心假设 + 验证步骤"。

#### 你可以这样对 AI 说

> "记下一个想法：用 retrieval-augmented generation 改进代码补全。现有补全模型上下文窗口小，能不能从代码库检索相关片段再生成"

→ AI 存为初始 idea。

> "把这个 RAG 代码补全的 idea 扩写成完整的研究问题"

→ AI 扩写成结构化 idea（problem / hypothesis / expected_benefit），默认 `pending`。

> "确认这个 idea，我是 czx，evidence 是讨论会 2026-07-04 一致认为可行"

→ 你确认 AI 扩写的 idea。

> "评审一下这个 idea 的可行性和新颖性"<br/>
> "对比候选池里的所有 idea，哪个最值得做"

→ AI 打分（novelty / feasibility / difficulty）+ 给建议，pending 你审。

> "我选这个 RAG 代码补全的 idea，开始推进"

→ **你拍板选哪个**（AI 不代你决定）。

**AI 做了什么**：把你的一句话扩成结构化 idea、打分、对比候选、找已有论文支撑/反驳。<br/>
**你做什么**：① 确认 AI 扩写的 idea 是你想的；② 最终选哪个 idea（这是决策点）。

---

### 场景 C：迭代方法与实验（idea → 可跑的代码 → 结果）

#### C1. 方法设计

**你可以这样对 AI 说**

> "基于 RAG 代码补全这个 idea，设计实验方案"<br/>
> "用 pytorch 仓库作为基础，起草 method 设计"

→ AI 起草 method 设计（实验矩阵 + baseline 选择 + 关键超参候选值 + 数据集建议），pending。

**AI 做了什么**：读 idea + repo，起草实验矩阵。<br/>
**你做什么**：审 method 设计，**决定实际跑哪组参数**（不是全跑）。

#### C2. 实验循环（每一轮）

**你可以这样对 AI 说**

> "记录一次实验 run：baseline 无检索，perplexity=5.23，pass@1=0.42，结果一般"

→ AI 存为 run-log（客观指标，fact-only）。

> "诊断一下这次实验为什么效果不好"

→ AI 推断原因（likely_causes / ruled_out / unknowns），生成 diagnoses.yaml，pending。

> "确认诊断结论，我是 czx，evidence 是复现 3 次确认是检索召回率低"

→ 你确认诊断是否靠谱。

> "给出下一步改进建议"

→ AI 生成 follow-up actions（调检索器 / 换数据集 / 加 ablation）。

**AI 做了什么**：分类指标、推断原因、生成下一步。<br/>
**你做什么**：① 记录真实指标（AI 不跑实验）；② 确认诊断是否靠谱；③ 决定下一轮改什么。

#### C3. 阶段推进（program 编排）

**你可以这样对 AI 说**

> "看一下 survey-rag 这个 program 的当前状态"（或 `kb status survey-rag`）<br/>
> "给我这个 program 的 dashboard"

→ AI 展示进展、待办、阻塞项。

> "建议我下一步该做什么"（或 `kb next`）

→ AI 给出按优先级排序的 next-action 列表。

> "自动执行所有能跑的安全步骤，遇到需要确认的停下来"

→ AI 跑完所有可自动化的（screen / refresh / build-index），遇 confirm / select 停住告诉你"需要你确认 X"（不越界）。

**AI 做了什么**：跟踪 program 状态、生成 next-action 优先级、自动跑安全步骤。<br/>
**你做什么**：① 读 dashboard 了解进展；② 决定何时从"探索"转"验证"（设 stage）；③ 批量确认 review-queue 里的 AI 推断。

---

### 场景 D：产出科研成果（报告 / PPT / 论文素材）

**你可以这样对 AI 说**

> "生成 survey-rag 这个 program 的本周周报"<br/>
> "汇总 2026 年第 28 周的进展"

→ AI 自动汇总本周完成的 unit（paper screen / idea review / experiment run）、关键发现（从 confirmed 的 diagnosis / review 提取）、下周计划（从 open-question / follow-up 提取）。

> "提取 survey-rag baseline 阶段的 PPT 素材"

→ AI 生成可直接贴进 PPT 的 bullet points、figure 路径（已裁好的高清图）、对比表格（markdown，易转 LaTeX）。

> "提取 related-work 部分的论文写作素材"

→ AI 提取 confirmed 的论文 summary、你标注的 reuse_flags: paper_writing。

**AI 做了什么**：从 confirmed 条目汇总、按时间/stage 分组、生成 markdown/figure 路径。<br/>
**你做什么**：① 在 AI 素材基础上写/改（AI 给材料，不是写成品）；② 决定哪些内容进最终版。

---

## 确认收件箱工作流

**核心**：AI 生成的**推断/评估/意见**全进确认收件箱，你批量审完再继续。

**你可以这样对 AI 说**

> "看一下确认收件箱里有什么待审的"（或 `kb review`）

→ AI 列出当前所有 pending 条目（按时间排序）。

> "确认这条论文筛选，我是 czx，evidence 是 decision-log"<br/>
> "批量确认所有待审的，evidence 是 decision-log"

→ 你逐条或批量确认（必须提供 evidence 溯源，防盲签）。

> "拒绝这篇论文，我是 czx，evidence 是与我们方向无关"

→ 你驳回某条（不采纳 AI 的判断）。

**关键规则**：
- **`evidence` 必填**（溯源），防"盲签"—— 即使你全信 AI，也得指向一个 decision-log / 会议记录 / 你的判断依据。
- **默认 confirmer 可配**：告诉 AI "把我设为默认确认人"后可省略每次声明身份（但 evidence 永远必填）。
- **AI 自动执行不越界**：只跑 `screen` / `build-index` / `refresh` 等安全步骤，遇 `confirm` / `select` 停住 —— AI 不代你做决策。

---

## 记忆机制（learnings）—— 让 AI 记住你的习惯 & 坑

**目标**：AI 走弯路/被你纠正时记一笔，下次不再犯；你的使用习惯积累成"偏好"。

**你可以这样对 AI 说**

> "记住：我的 summary 喜欢中文，简洁风格"<br/>
> "记一条习惯：我偏好中文简洁的总结"

→ AI 记为 user-preference，默认 pending。

> "记录一个 skill 问题：orchestrate route 把'入库'错分给了 wiki-adapter"

→ AI 记为 skill-defect（只记录，**不自动修 skill**）。

> "看一下已知的习惯和坑"（或 `kb recall`）<br/>
> "列出待我审的 skill 问题"

→ AI 展示已确认的习惯、已知坑、待审的 skill 缺陷（按复现次数排序）。

> "确认这条习惯，提升进配置"

→ 你确认一条习惯 → AI 写进配置（以后自动生效）。

> "看看有哪些 skill 缺陷需要修"

→ AI 列出被复现多次的 skill 问题，**你决定要不要修**（AI 不自动改 skill / OPTIMIZATION_PLAN）。

**分工边界**：
- **`user-preference` / `recurring-issue`** → 确认后进 AI 记忆（自动生效）。
- **`skill-defect`** → **只记录，不自动修 skill / OPTIMIZATION_PLAN**（你阅读后决定要不要优化）。

---

## 万能起手式（不知道先做什么时）

**你可以这样对 AI 说**

> "看一下当前状态"（或 `kb status`）

→ AI 展示当前进展、待办、确认收件箱计数、下一步建议。

> "给我这个 program 的 dashboard 和建议的下一步"

→ AI 展示 dashboard + next-action 优先级列表。

> "处理确认收件箱"（或 `kb review`）

→ AI 列出所有 pending 条目，你批量审/确认/驳回。

> "自动跑所有能跑的，遇到需要我决策的停下来"

→ AI 自动执行安全步骤，遇决策点停住告诉你"需要你确认 X"。

**AI 告诉你"现在该干嘛"** → 你审一眼 → 批量确认/决策 → AI 继续。

---

## 快捷命令（伪 CLI 形式）

对于少数高频动作，你可以直接对 AI 说这些关键词，AI 会识别并返回结果（入口还是 AI，只是简化了表达）：

| 你对 AI 说 | AI 做什么 |
|---|---|
| `kb help` | 打印能力菜单（加材料/检索/idea/实验/报告/确认/状态），每项一句话解释 |
| `kb status` | 展示当前状态：进展、待办、确认收件箱计数、下一步建议 |
| `kb review` | 列出确认收件箱所有 pending 条目（可进入交互式逐条确认） |
| `kb next` | 给出按优先级排序的 next-action 建议 |
| `kb add <url或arxiv或github>` | 快速入库材料 |
| `kb find <关键词>` | 检索知识库 |
| `kb recall` | 展示已知习惯、已知坑、待审 skill 问题 |

**这些都用模糊 id**（last / 标题片段 / 前缀），不用记 hash。例如：

- `kb review transformer` → 列出标题包含 transformer 的待审条目
- `kb find last paper` → 找最后加的论文
- `kb status survey-rag` → 看 survey-rag program 的状态

---

## 你只需记住的三条原则

1. **AI 提取事实可靠，AI 的判断/意见必须你审。**<br/>
   → 元信息/索引/去重放心用；quick-screen / review / diagnosis 进确认收件箱你批量审。

2. **所有"决策点"都是你：选 idea / 选 baseline / 判定实验结论 / 推进阶段。**<br/>
   → AI 给建议 + 理由，你拍板。AI 自动执行遇决策点会停。

3. **`evidence` 是溯源红线，AI 自动执行有安全边界。**<br/>
   → confirm 必须给 evidence（防盲签）；自动执行只跑安全步骤（不越界）。

**AI 做重复劳动（提取、整理、追踪、汇总），你做判断 —— 这是设计的分工。**
