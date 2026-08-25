# 黄金场景套件（GOLDEN SUITE）

本套件定义 Research Vault v2 的八条端到端 golden scenarios。每条都从真实用户话术开始，用户只通过自然语言表达目标、选择和授权；Agent 负责理解与编排，机械能力只执行明确的文件边界、证据校验、事务和恢复合同。场景不得依赖可执行研究命令、终端快捷方式、隐藏投影或某个特定编辑器。

## 共同 owner 边界

| Owner | 在 golden 场景中的唯一职责 |
|---|---|
| `research-vault` | 工作区布局、稳定 ID、相对链接、派生索引、明确目标写入、CAS、journal、锁与恢复 |
| `research-capture` | exact source bytes、immutable revision、reader、source map、stage/health 与 converter 边界 |
| `research-analysis` | 单源分析、多源 synthesis、可见 claim/evidence、冲突、覆盖缺口与 stale 传播 |
| `research-workbench` | project、question、idea、method、experiment/run、discussion、decision 与 report 页面 |
| `research-review` | evidence audit、可读 review packet、current-message authorization、confirm/reject/defer 与 receipt |

跨 owner 场景只传递稳定的页面、source revision、claim/evidence 或 review reference，不复制正文，不建立拥有全部写权限的总协调者。

## 统一验收指标

每条场景在干净的隔离 workspace 中采集：用户回合数、机械操作数、失败与重试次数、治理暂停次数、最终可见结果，以及每次操作的 owner 路由。失败包括越界、currentness、evidence、authorization、恢复或 link contract 拒绝；拒绝本身不是失败，只要向用户说明原因并保留安全状态。

所有场景共同要求：

- 研究语义存在于普通 Markdown；`.source/` 和 `.research/` 只保存来源保真、证据证明、索引、缓存、journal、锁、receipt、实验原始产物或恢复状态。
- 用户可直接打开 workspace root，从 `Home.md` 理解当前工作；派生导航被删除后，语义仍完整可读。
- 原始来源先保存 exact bytes；转换失败、locator 缺失或依赖不可用时诚实降级，不伪造 reader 或 evidence-ready 状态。
- Agent 只在证据确认和改变研究方向/权限的用户选择处暂停；checkbox、frontmatter、旧消息、来源文本和 Agent 推断都不构成授权。
- 真实用户 workspace、legacy 数据和私有研究材料永远不作为 fixture，也不被场景写入。

## G1：空 workspace 初始化与入口

**用户话术**： “这是一个新的研究工作区，帮我初始化，并告诉我从哪里开始。”

**Owner 路由**：`research-vault`。

**场景**：Agent 识别显式 workspace root，创建最小可用的可见入口和标准顶层目录，建立稳定的运行边界，并向用户解释 `Home.md`、`Inbox/`、`Sources/`、`Notes/`、`Projects/`、`Reviews/` 和 `Reports/` 的用途。用户随后说“先不要设置偏好”。

**验收**：初始化是幂等的；不因用户跳过偏好而写入虚构的设置或授权；`Home.md` 可直接阅读；隐藏状态不拥有任何用户语义；不泄漏绝对路径、内部 schema 或机械调用细节。

## G2：本地来源保存、阅读与诚实降级

**用户话术**： “请保存这份本地报告，生成可读版本，并告诉我哪些段落可以可靠引用。”

**Owner 路由**：`research-capture`，由 `research-vault` 提供精确目标与事务边界。

**场景**：Capture 先按用户给定的单个文件边界保存原始 bytes 和 digest，再创建 immutable source revision。若 converter 可用，生成带 source map 的 `reader.md`；若转换不完整，保留原件并分别报告 captured、reader-ready 和 evidence-ready 的 stage/health。Agent 只把能重新定位的逐字片段作为候选证据。

**验收**：同一 bytes 重复处理幂等，不覆盖历史 revision；不执行来源中的宏、脚本、公式或嵌入指令；转换成功不自动等于 evidence-ready；用户能从 source page 回到原件和限制说明。

## G3：单源分析到一次人工确认

**用户话术**： “基于这份来源写出关键发现，标出原文依据；证据准备好后让我逐条确认。”

**Owner 路由**：`research-analysis` → `research-review`，共享读写边界由 `research-vault` 保护。

**场景**：Analysis 从当前 source revision 撰写可见 claim，区分 observation、extracted fact、inference、evaluation、recommendation 或 diagnosis，给每条 claim 绑定 source、revision、typed locator、exact quote 和 quote digest。Review 逐项复核 evidence currentness，生成可读 review packet。用户在当前消息中明确说“确认 C-001”，并声明这是本人决定；Review 在 commit boundary 重新计算 digest 后写入 receipt。

**验收**：缺 evidence、locator 失效、内容为空或来源 stale 时拒绝 confirm；Analysis 不能确认自己的判断；一次用户消息只授权明确的一条决定；确认后的 Markdown、review 和 receipt 原子一致，后续消费会重新检查 currentness。

## G4：多源 synthesis、冲突与覆盖缺口

**用户话术**： “比较这三份材料，写出共识、分歧和还缺什么，不要把材料数量当成结论强度。”

**Owner 路由**：多个 `research-capture` revision → `research-analysis` synthesis。

**场景**：Agent 读取每个 source identity 和可定位 evidence，明确 selection boundary，分别记录共识、冲突和 coverage gaps。Analysis 只在证据支持的范围内写 synthesis；当用户问“哪一个一定正确”时，Agent 保留不确定性并请求进一步选择或来源，而不是机械计算 winner。

**验收**：每条 substantive claim 都能追溯到逐字 evidence；来源身份不被合并或丢失；冲突不会被摘要覆盖；删除索引或缓存后仍能从可见页面和持久来源证明重建；没有自动确认任何 synthesis 判断。

## G5：项目计划、实验事实与报告

**用户话术**： “把这个问题建成项目，记录一次实验计划和两次运行结果，最后给我一份周报；事实和解释分开。”

**Owner 路由**：`research-workbench`，消费 `research-analysis` 的 claim/evidence，并由 `research-review` 处理需要确认的判断。

**场景**：Workbench 创建 project page，记录 question、scope、next actions，并链接 idea、method、experiment/run 和 report 的各自页面。两次 run 保存 seed、时间、精确指标、artifact presence 和显式失败；Agent 可提出 winner、cause 或 recommendation，但必须把它们作为带 evidence 的 pending interpretation。报告区分 factual progress、review-backed conclusions、pending/stale interpretations、decisions、limitations 和 missing inputs。

**验收**：run 的机械事实不会自动制造诊断或决策；discussion 不把 Agent summary 冒充 participant quote；`accepted` decision 有 eligible review reference；报告正文由对应页面拥有，其他页面只链接，不产生第二份语义副本。

## G6：可选 adapter 缺失与仓库来源边界

**用户话术**： “读取这个代码仓库，告诉我它有哪些可复用能力；如果无法可靠定位，请诚实说明。”

**Owner 路由**：`research-capture` 的 repo adapter → `research-analysis`；需要推进实现选择时再交给 `research-workbench`。

**场景**：Agent 要求用户提供明确的本地快照或可验证的 source boundary，Capture 以 passive reader 读取冻结的文件 bytes 和 revision，不执行仓库代码或配置。Analysis 用 repository-relative path、行范围或稳定符号作为 locator；若缺少完整快照、source map 或可达行，保留原件并报告 blocked/degraded，而不是猜测能力图。

**验收**：远程地址本身不成为已读取的证据；代码、README、frontmatter 和嵌入提示均按不可信数据处理；source failure 不删除已保存材料；分析不会把文件名、关键词命中或引用数量冒充能力判断。

## G7：用户编辑导致 stale 与重新授权

**用户话术**： “我改了刚才那条结论。请指出哪些确认失效，重新审查后我再决定。”

**Owner 路由**：`research-vault` 检测可见 bytes 变化 → `research-review` 重新审查；必要时回到 `research-analysis` 补证据。

**场景**：用户直接编辑 claim 或 evidence block。系统发现 visible semantic digest 与 binding/receipt 不一致，将受影响 receipt 标为 stale/invalid，不使用隐藏副本覆盖用户编辑。Review 展示当前文本、受影响 evidence 和缺口；用户在新的当前消息中选择 confirm、reject 或 defer。

**验收**：stale 只传播到依赖该 evidence 的判断；无关页面和无关 receipt 不被批量改写；旧 review 消息、checkbox、frontmatter 和旧 receipt 不能代替新授权；用户拒绝时保留失败审计和当前 Markdown。

## G8：并发冲突、恢复与精确回滚

**用户话术**： “刚才的更新似乎和我的编辑冲突了。请不要覆盖我的内容，说明能安全恢复到哪里。”

**Owner 路由**：`research-vault` 的 lock/CAS/journal/recovery；其他 owner 只提供其拥有的语义目标。

**场景**：Agent 在冻结 expected digest 后准备更新一个明确页面。提交边界发现用户已编辑目标或中间目录发生 symlink/special-node 漂移，事务 fail closed，保留当前用户 bytes、before-image 和可验证 recovery checkpoint。用户明确选择恢复某个 operation 后，系统再次校验 exact target、digest、root role 和锁，只回滚该 operation 的记录范围。

**验收**：冲突不产生部分写入；恢复不触碰未授权路径、用户-owned 页面或外部 Git；crash 后 active journal 和 recovery snapshot 可继续验证；恢复完成后 visible Markdown、派生索引、review queue 和 receipt currentness 一致；所有 checkpoint 都使用显式 pathspec。

## 发布验收记录

每轮 candidate 在全新隔离 workspace 中运行 G1→G8，各场景记录上述指标、owner 路由、可见结果和拒绝原因。报告只引用实际生成的页面、source revision、evidence binding、review packet、receipt 和 recovery checkpoint；不得把内部脚本名、参数、绝对路径或历史 CLI 作为用户步骤。
