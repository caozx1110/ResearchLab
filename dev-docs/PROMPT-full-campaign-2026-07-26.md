# 任务：把 workspace-oss 完整迭代到满足全部需求（自主多轮 campaign）

你在 `~/Documents/rl2lab/projects/vla/workspace-oss` 仓库根目录。这是一套研究知识库 skill 系统（`.agents/` 能力包 + `kb/` 数据，用户面=自然语言+16 个 `kb <verb>`，AI 填理解、人确认判断）。你的使命不是修一部分，而是**多轮自主迭代直到 §2 验收清单全部勾完**，交付一个满足我全部需求的版本。

## 0. 工作方式

- 在专用分支施工：`git checkout -b v2-campaign`。master 保持随时可用（我日常还在用这套 skill）。每完成一个里程碑就 commit（信息写清做了什么），**不 push、不打 tag、不合回 master**——最终验收通过后我来决定合并。
- 建立并维护台账 `dev-docs/CAMPAIGN.md`：验收清单勾选状态、每轮做了什么、遗留与决定记录。**会话中断后，新会话读台账即可恢复**（我会说"继续 campaign"）。
- 允许并鼓励：subagent、多 git worktree 并行、每轮末尾用不带施工上下文的冷 subagent 做验收。
- 设计 SSOT：`dev-docs/reviews/skill-refactor-blueprint-2026-07-26.md`（蓝图 v2）。可以偏离它，但每次偏离要在台账记录理由。
- 仓库根的 `kb/` 是我的真实旧数据：**只读，永不写入/迁移/删除**。新版本可以宣布与旧 kb 不兼容（我已决定旧库可弃），一切冒烟在 /tmp 的 scratch 工作区做。

## 1. 需求基线（一切工作的唯一目的）

我是 VLA/人形机器人研究者，单人使用为主（保留他人可安装的开源底线）。要求这套系统把以下事情做到**省心、省 token、结果可信**：

建库与阅读：①一句话入库论文/blog/repo，原始材料完整保留；②自动提取核心概念→一等公民概念页（定义带逐字出处+关联论文/repo/idea，入检索与 Obsidian）；③伴读论文+快速回顾要点；④随手记录想法；⑤AI 生成、我确认的综述/知识理解报告。
检索与讨论：⑥快速检索关键信息/论文/**代码**（file:line）；⑦理清方向脉络与趋势；⑧基于知识库有理有据讨论 idea/技术路线、发掘 idea。
落实与产出：⑨idea→方法构思；⑩归档并分析实验结果；⑪论文大纲→初稿+bib 引用；⑫随时生成能直接交差的周报/工作报告。
横切：⑬交流中观察式记录我的偏好；⑭记录 skill 自身可优化点。

已定决策：**移除论文快筛**（入库即深读，paper_type 并入深读 prepare）；周报编辑层、论文初稿+bib、PPT 素材差异化、图表可引用化全要；治理分档 `governance_profile: personal|strict`（personal 默认，只降仪式不降签字；strict 保留全部现行为供开源）。
交互章程（写进 `.agents/AGENT_GUIDE.md` 的 10 条，已存在，需全面落实到行为）：澄清用带默认值的选择题、讨论先复述理解、偏好任务尾攒批问、大活先小样、伴读三段式且落库先询问、口头分型（库内证据/推断/需验证）、技术路线三栏、开场接续、四行收尾、入库静默礼仪。
硬约束：研究判断必须我签字（AI 不可自签，这条永不放松）；零付费依赖；Python 3.9 兼容；公开输出中文自然语言、无 traceback/内部路径。

## 2. 验收标准（Definition of Done——全部勾完才算完成）

**功能验收**（每条都要在干净 /tmp 工作区实测，真实来源优先）：
- [ ] A1 真实 arXiv 论文（HTML 与 PDF 各一）、真实 GitHub repo、网页 blog、本地文件各一例：发一个链接即完成入库+深读骨架，全程 ≤2 次用户交互；一次发 5 个链接批量入库不逐个盘问
- [ ] A2 快筛已移除：论文入库直达按类型深读，无"值得细读"确认步骤；auto_screen 配置退役
- [ ] A3 概念页：从 ≥3 个已入库单元提取概念→我确认→概念页含定义（逐字出处）+关联清单；kb find 检索可达、Obsidian 可浏览
- [ ] A4 检索三类：中文查询、英文查询、代码符号查询均返回带定位结果（代码带 file:line），常规库 <3s
- [ ] A5 综述：从 ≥5 单元生成 survey（taxonomy/trends/gaps），claim 全带证据、绑定上游、确认后可被报告消费
- [ ] A6 idea 全链：一句话捕获→证据分析（corpus 违规消息可自解释）→讨论归档→选中→method handoff
- [ ] A7 实验：wandb export JSON 或 CSV 一次导入 ≥10 条 run；diagnose 走确认门；audit 零 error 零实验 dirty 警告
- [ ] A8 周报场景："为 <program> 生成本周周报"一句话→进展/问题/下一步叙事+证据附录，直接可交差；PPT 素材=每页一结论+证据+图引用；两者与 outline 三者输出明显不同
- [ ] A9 论文：outline→分节草稿（节级确认）→bib 导出（≥5 条去重、citation key 稳定）→LaTeX/MD 落 output/
- [ ] A10 图表：论文图片有 caption/编号索引，笔记与报告可按稳定引用键引用
- [ ] A11 偏好：纠正一次表达风格→任务尾被询问是否记住→确认后下次任务可见生效；init 两问（自动化档位/讨论风格）落盘且被消费（link_autodrive=auto_deep_read 时链接直达深读）
- [ ] A12 恢复：undo 点名对象；restore 无参列操作清单且可按编号恢复；中断操作 resume 成功
- [ ] A13 交互章程冷验收：冷 subagent 扮演我跑三场景（入库今天一篇 arXiv 并讨论是否跟进 / 陪我打磨一个 idea / 10 分钟出周报），章程 10 条逐条打分，无一条系统性缺失

**质量验收**：
- [ ] Q1 pytest 全套绿（`.venv` 下跑；断言随行为变更同步，但不得靠回退新行为凑绿）
- [ ] Q2 skill_validator 全部通过；安装 ≤60s；`bash install.sh` 冷装+update+uninstall 三态正常
- [ ] Q3 docs/GOLDEN_SUITE.md 8 条黄金对话全通过，且**零机制摸索失败**（agent 不需要读源码就能正确调用一切）
- [ ] Q4 单任务加载的规则文本 ≤8k tokens（AGENTS.md+当次相关 SKILL.md+AGENT_GUIDE 计）；kb next 决策 ≤3 步
- [ ] Q5 静默失败为零：任何非零退出都有一行可行动中文原因；私有协议含期望格式
- [ ] Q6 公开输出零 traceback/零绝对路径（含 owner 脚本直连时的 `[root]` 行治理）
- [ ] Q7 SCHEMAS.md、DESIGN.md、USER_GUIDE.md、README.md、CHANGELOG.md 与实现一致（rc 状态段单一事实源）

## 3. 工作包全集（建议轮次，可自行重排）

R0 Wave 1 落定：按 `dev-docs/HANDOFF-claude-code-2026-07-26.md` 跑套件、分诊修断言、commit（其 §2 是有意行为变更清单，不得回退）。
R1 流程减法：快筛移除；link_autodrive 消费（auto_deep_read 直达深读）；治理分档补全（personal 档 review 一批 >3、卡片有效期可配、D1 本地日志脱敏分档）；[root] 绝对路径行治理（同步测试）。
R2 知识层：G13 概念页（新 kind 或 synthesis/concepts，prepare/fill/verify 范式+确认门+Obsidian 投影+find 索引）；G3 context-pack（给定问题→组装相关单元 confirmed claims+locator 的上下文包，服务讨论与写作）。
R3 论文链：G1 bib（intake 抓 DOI/arXiv id/bibtex 元数据+report 导出）；G7 图表可引用化（caption/编号索引，打通 payload.figures）；G2 分节成稿（节绑定 claims/evidence、节级确认、LaTeX/MD 导出）。
R4 实验与报告：G4 实验导入（wandb/CSV/目录约定，fingerprint 沿用，来源标 imported）；G8 周报编辑层+PPT 差异化（三模板真正分化）。
R5 结构减法（需套件护航的大手术）：四个 analyst 合并为 unit-analyst（只动 SKILL.md 与入口路由，不动 lib 数据结构）；wiki-adapter 并入 kb-cli 路由后删除；research-navigator 移出 bundle；tests 移仓库根；20 份 openai.yaml 改构建生成；SKILL.md 契约瘦身（可代码强制的从提示词移进 validator）；G5 批量园艺（kb add 多目标、pending 清理、stale survey 重建路由）；G6 批注回流（inbox 笔记→pending 条目，signer=我）。
R6 终验：全量 DoD 清单逐项勾验 + A13 冷验收 + 最终报告 `dev-docs/reviews/campaign-final-report.md`（验收证据、指标前后对比、遗留清单、合并建议）。

## 4. 每轮流程契约

计划（更新台账）→ 施工（worktree/subagent 自便）→ pytest 全绿 → 相关 GOLDEN 条目行为验收 → 冷 subagent 对抗自查（找回归与静默失败）→ 修复 → 台账勾选 + commit。任何一轮结束时 v2-campaign 分支必须处于"可安装可用"状态——允许功能未齐，不允许挂掉。

## 5. 承重墙（禁改清单）

原子写/journal/CAS/精确路径锁；逐字 evidence+locator 位置校验；快照绑定确认（AI 不可自签、当前消息授权、内容变化即失效）；prepare→fill→verify 三段范式；raw/ 不可变与 document.md 阅读层；免插件 Obsidian（不写 .obsidian/、managed 只读可重建）；来源感知更新（fork 不被更新到上游）；strict 档全部现行为。治理分档只降仪式成本，永不降证据与签字。

## 6. 决策权

**你自行决定并记录台账**：实现细节、文件组织、schema 演进、轮次顺序、测试策略。
**攒批问我（用带默认推荐的选择题，每批 ≤4 问，别一个个抛）**：公开动词的增删改；任何触碰确认门语义的方案；删除某个既有能力；两个方案都合理但会改变我日常操作习惯的选择。拿不准且可逆→选保守默认做下去并记录；拿不准且不可逆→停下来问。

## 7. 最终交付

v2-campaign 分支（全部 commit）、勾满的 CAMPAIGN.md、campaign-final-report.md（含 DoD 逐项证据与前后指标对比：步数/轮次/token/耗时）、以及一段给我的合并指引。完成的标志只有一个：§2 每一个框都打了勾，或明确标注"未达成+原因+建议"。
