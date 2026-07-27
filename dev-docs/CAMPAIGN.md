# CAMPAIGN 台账（v2-campaign）

> 施工规格：`dev-docs/PROMPT-full-campaign-2026-07-26.md`。设计 SSOT：`dev-docs/reviews/skill-refactor-blueprint-2026-07-26.md`（蓝图 v2）。
> 恢复方式：新会话读本文件 + PROMPT 即可继续（用户说"继续 campaign"）。
> 分支：`v2-campaign`（自 `codex/review-remediation-integration` @ dfcc0b5 建出，携带 Wave 1 未提交改动）。不 push、不 tag、不合 master。
> 红线：仓库根 `kb/` 只读；承重墙（PROMPT §5）禁改；strict 档语义不变；AI 不可自签。

## 验收清单（Definition of Done）

### 功能验收
- [ ] A1 四类真实来源一链入库+深读骨架，≤2 次交互；5 链批量不逐个盘问
- [x] A2 快筛已移除，auto_screen 退役
- [x] A3 概念页（提取→确认→定义带逐字出处+关联清单；find/Obsidian 可达）
- [ ] A4 检索三类（中/英/代码符号带 file:line），常规库 <3s
- [ ] A5 综述 ≥5 单元（taxonomy/trends/gaps，claim 带证据绑上游，确认后可被报告消费）
- [ ] A6 idea 全链（捕获→分析→讨论归档→选中→method handoff）
- [ ] A7 实验导入 ≥10 run；diagnose 确认门；audit 零 error 零 dirty
- [ ] A8 周报一句话可交差；PPT 素材差异化；与 outline 三者明显不同
- [x] A9 论文 outline→分节草稿→bib 导出→LaTeX/MD 落 output/
- [x] A10 图表 caption/编号索引，稳定引用键
- [ ] A11 偏好观察式记录+确认后生效；init 两问落盘且被消费
- [ ] A12 undo 点名；restore 无参列清单可按编号恢复；中断 resume 成功
- [ ] A13 交互章程冷验收（三场景 10 条逐条打分）

### 质量验收
- [x] Q1 pytest 全套绿（普通文件型 scratch `.venv`；R3 `2200 passed, 18 skipped`；不得回退新行为凑绿）
- [x] Q2 skill_validator 20/20；冷装约 2s；install.sh install+update+uninstall 三态正常
- [ ] Q3 GOLDEN_SUITE 8 条全过且零机制摸索失败
- [ ] Q4 单任务规则文本 ≤8k tokens；kb next ≤3 步
- [ ] Q5 静默失败为零（非零退出带一行可行动中文原因；私有协议含期望格式）
- [ ] Q6 公开输出零 traceback/零绝对路径（含 [root] 行治理）
- [ ] Q7 SCHEMAS/DESIGN/USER_GUIDE/README/CHANGELOG 与实现一致（rc 状态单一事实源）

## 轮次记录

### R0 Wave 1 落定（完成，2026-07-26 → 2026-07-27）
- 建 `v2-campaign` 分支（基线 dfcc0b5 + Wave 1 未提交 42 文件改动）。
- 计划：pytest 全套 → 分诊（HANDOFF §2 为有意变更清单，不得回退）→ 修断言/真回归 → skill_validator → T3 文档同步 → 分组 commit。
- 已做：skill_validator 20/20 通过；T3 文档同步完成（SCHEMAS.md 三段：governance_profile / portfolio-selection-draft / passage cache 代码检索扩展 + monitor template；DESIGN.md 四类→六类快速字段；CHANGELOG Unreleased 加 Wave 1 条目未升版；.gitignore `_to_delete/` 已在）。
- 首轮完整套件（常规 Python 3.13 运行时）：`2105 passed, 18 skipped, 5 failed`；5 项全为 Wave 1 预告的断言/公开契约同步，定向复核 `5 passed`。第二轮 `2109 passed, 18 skipped, 1 failed`，唯一失败由运行中修改 source tree 触发 update 正确检出变化，不是产品回归。
- 真回归修复：恢复 5 个 shipping 入口的可执行位；PDF 后端准备失败补 1 小时节流标记；`experiment log-run` 新建 run 事实在事务 precommit 二次校验，补回 post-dispatch/precommit 防替换缺口；并发 `log-run` 的 canonical record 目标发现纳入同一 workspace lease，消除原子替换窗口的偶发 `Record not found`。
- 测试契约同步：PDF doctor/init 新字段与文案；installer PDF runtime 条件、失败尾部 ≤8 行；macOS `xcrun_db` 工具链缓存豁免（产品自有写入仍禁止）；socket/bind 不可用环境明确 skip。
- 环境与最终门：仓库 `.venv/bin/python` 经 symlink 规范化后指向 Xcode base Python，会使 Agent-plan 测试判定解释器缺少模块；未削弱 runtime identity 合同，而是用普通文件型 scratch `.venv` 终验：`2113 passed, 18 skipped, 7 warnings`。Python 3.9 `compileall` 通过，skill validator `Validated 20 skills.`。
- 冷启动冒烟：`install.sh --claude` 约 2s；`kb init/help/doctor` 通过，PDF 深读能力诚实报告就绪；update 命中 no-change；uninstall 移除安装器管理文件并保留 scratch `kb/`。
- 红线检查：仓库根 `kb/` 未修改；未 push/tag/merge。

### R1 流程减法与治理分档（完成，2026-07-27）
- 已完成三条只读定位：论文 quick-screen/link_autodrive、review/TTL/D1 治理分档、公开根路径/安装器错误尾部；未调用 shipping skills，未修改真实 `kb/`。
- 已先回写设计 SSOT：paper 统一 deep-read scaffold（类型+类型证据+三分支）、新 workspace personal/旧 workspace 缺省 strict、personal review 默认 10 条且 TTL 1..168h、D1 personal 仅放开四个机械字段、公开输出不显示绝对根路径或原始错误尾部。
- 论文链：新 paper skeleton 改为 `deep_read.paper_type`；`complete-note prepare` 一次生成类型理由/类型 evidence + 三套五要素分支，verify 拒绝空类型、错误 claim type、未选分支内容和逐字证据不匹配，写 `claim-paper-type` + 所选五条 claim。`kb ingest`、`kb next`、query 提示和 orchestrator 新 unit 路由全部直达 `complete-note`；`screen` 仅供已有 `quick_screen` record 兼容，source-intake 不再准备 analyzer scaffold。
- 对话链：`kb add` 已消费 `link_autodrive`；`ask_first` 轻量入库并在私有 action 绑定原 source 后只问一次，`auto_deep_read` 复用完整 ingest prepare。init/default/runtime config 中 `auto_screen` 与 screening 配置均退役，旧配置加载/写回会清理。
- 治理链：新 workspace 明确 `personal`，已有缺失/非法 profile 的 workspace 保持 `strict`；strict 固定 3 条/24h，personal 默认 10 条、可配 4..20 条与 1..168h。profile/limit/TTL 同时冻结进对话 snapshot 与 Obsidian batch，apply 不重读配置；两档都保留真实 signer、当前消息授权、逐字 evidence、content binding、CAS 与跨 owner 原子批量。新增对抗测试证明 personal 可一次应用 4 条，strict 无法把上限抬高。
- D1/公开面：personal local-only 自动错误记录仅额外保存规范化 category/owner/operation/return_code，自由文本仍脱敏；strict 与所有 export 保持强脱敏。公共 `[root]` banner、cwd 绝对路径、git-init/复盘绝对路径、安装计划/快捷入口路径与同步器原始错误尾部均已移除；R5 将删除的 navigator 仍作为最终 Q6 遗留，不在本轮虚报完成。
- 回归：Python 3.9 `py_compile`、`bash -n install.sh`、`Validated 20 skills.`；承重定向 `747 passed`，review/prefs/D1 `323 passed`，最终全套 `2132 passed, 18 skipped, 7 warnings`（8m05s）。
- 安装态 scratch：冷装约 2s；paper ingest 生成统一 `note-fill.yaml` 且无 `screening.yaml`；Agent 填类型+5 要素后 verify 成功并生成 6 条 pending claims；ask-first 只入库一次，auto-deep-read 直接备好同一深读 scaffold。scratch 位于 `/private/tmp/workspace-oss-r1-scratch.PSFm8r`，仓库根 `kb/` 未触碰。
- A11 本轮只闭环 init 两问与 `link_autodrive` 消费；“观察纠正→任务尾询问→确认后跨任务生效”仍待后续轮实现/验收，因此 A11 不提前勾选。
- 运行时/测试/随包契约提交：`ba39491 feat(research): remove paper screening and bind review governance`；公开文档与本台账另作 R1 文档提交。

### R2 知识层（完成，2026-07-27）
- 已完成只读架构审计，未调用 shipping skills、未修改真实 `kb/`。概念层确定为 canonical `concept` unit（不是特殊 side YAML），从而复用统一 record snapshot、evidence/ConfirmationReceipt、FTS 与 Obsidian 关系图；source-intake 仍只处理 paper/repo/dataset/blog。
- 已在蓝图锁定 concept prepare/fill/verify、至少 3 个 current unit、定义/关联判断全部逐字证据并待真人确认，以及 `payload.concept` 与 top-level links 一致性。
- context-pack 确定附着现有 `kb find` 私有协议，不增加公开动词、不落 canonical 产物；正式 lane 只含 current receipt 覆盖的 confirmed claims，summary/passage 只作未确认导航提示，并实行 5 unit × 3 claims × 2 refs + 6000-byte 原子预算。
- 概念实现：新增 canonical `concept` kind 与 `c-` ID，`literature-synthesizer` 提供 prepare/fill/verify；至少 3 个 current confirmed 非 concept 单元，定义、可选 scope 和每条关联角色都必须由 runtime Agent 填写并带逐字 evidence。verify 冻结上游 record/receipt/evidence，写 pending concept；公共 `kb review` 通过 generic knowledge writer 做 snapshot/CAS/真人授权确认。上游、anchor 或关联→links 投影变化都会使旧确认失效。
- 检索/投影：concept 进入统一 index/FTS 与 Obsidian unit 图谱，页面显式渲染定义和关联清单。冷验收发现“顶层已确认但 claim/分析 banner 仍显示 pending”，修为只在 normalized top-level current confirmed 且 receipt 覆盖 claim id 时投影为已确认，不改 canonical claim bytes 或 ConfirmationReceipt digest。
- context-pack：`kb find` 私有 protocol 新增只读 `context-pack/v1`；formal 只搬运唯一 canonical snapshot 中 current receipt 覆盖且 evidence current 的 claims，navigation summary/passage 明确不绑定确认。重复 ID、pending/rejected/forged/stale、不完整 locator 与路径泄漏均 fail-closed；限制 5×3×2 和 6000 UTF-8 bytes，超预算整对象删除，末尾聚合重验，全程不写 canonical KB。
- 安装态 A3：固定 commit 冷装到 `/private/tmp/workspace-oss-r2-a3.pIuuAM`；构造 current confirmed paper/repo/idea 后，真实跑 concept prepare→Agent fill→verify→公共 `kb review`（5 条 grounded claim）→真人署名确认。`kb find` 命中 concept，私有 pack 含 3 条 receipt-bound formal claim、总 5843 bytes、无绝对路径；Obsidian 页显示定义、3 条关联和 5 条已确认 claim。仓库根 `kb/` 零改动。
- 质量门：概念/context 定向 `298 passed`；Obsidian 修复定向 `39 passed`；Python 3.9.6 `py_compile`、skill validator `Validated 20 skills.`；最终全套 `2147 passed, 18 skipped, 7 warnings`（9m17s）。安装器从已提交 release allowlist 冷装成功，后续 update 保留 scratch `kb/`。
- 提交：`4aa35aa feat(research): add concepts and bounded context packs`；`acda252 fix(obsidian): project receipt-bound claims as confirmed`。

### R3 论文链（完成，2026-07-27）
- 已完成 bibliography / figure reference / section draft 三条现状的独立只读审计；未调用 shipping skills、未修改真实 `kb/`。确认当前缺口包括：paper intake 丢部分 citation metadata；caption crop 依遍历序号命名且自动把全部图设为 key figure；outline 只有机械 Markdown 骨架，没有分节 judgement/receipt/publication 合同。
- 设计门已锁：citation key 绑定 canonical paper id，DOI/arXiv/source URL 强身份去重，raw BibTeX 永不进入渲染面；program `.bib` 绑定完整选择集与 paper snapshots，纯事实导出不错误依赖 deep-read judgement receipt。
- figure index 锁为 `figure-index/v1`：ref key 绑定 paper + 规范化 caption 编号，PNG 资产按内容哈希落盘；机械提取不再选择“关键图”或降级整篇确认，Agent 的图引用选择随实际写作 judgement 确认。
- figure index 已实现：caption 编号规范化、panel/continued 逻辑合并、无编号 fallback、冲突 fail closed、PNG sha256 地址化、source/index/asset 字节 currentness 重验。`extract-figures` 不再自选 key figure，不改 paper claim/顶层 confirmation；重跑保持 ref/index/asset 稳定。caption/ref key 已进 find，Obsidian 投影 current 图与图注；source/index/asset 任一篡改时两端都撤下陈旧条目。
- figure 定向质量门：真实构造 PDF 端到端提取+重跑+篡改验收，find/Obsidian 与 recovery/governance/preferences/report 联合回归 `349 passed`；Python 3.9 compile、skill validator `Validated 20 skills.`、`git diff --check` 通过，仓库根 `kb/` 零改动。
- section draft 锁为 `paper_draft_section` side judgement：七节各自 prepare/fill/verify/confirm，段落逐一绑定 current confirmed source claims/evidence、citation keys 和可选 figure refs；全节 current confirmed 后才将 MD/LaTeX/bib/publication manifest 原子发布到 `kb/output/<program-id>/`。
- section draft 已实现：新增纯合同层与 read-only snapshot runtime，manifest 冻结 exact outline、program selection、current confirmed claim/evidence、citation 和 figure bindings；prepare 只建七节空 fill，verify 机械搬运逐字 evidence 并生成 pending section。`paper_draft_section` 已接入统一 dialogue/Obsidian review batch、真人签字/当前消息授权/实质门/版本锚定确认；public card 展示完整正文与 support/citation/figure refs。
- 发布门要求固定顺序七节全部 current confirmed；Markdown、LaTeX、`references.bib`、byte-bound publication manifest 在单一 recovery transaction 原子写入。outline、selected unit（含 capture 时缺失后出现）、record/receipt/evidence、citation、figure index/assets 或 section bytes 任一漂移均 fail closed，并保留旧发布字节；非法 section id、fill leaf/ancestor symlink 与非普通文件均在业务写前拒绝。
- section draft 质量门：纯合同/实质门与真实七节集成全部通过；集成覆盖 5 篇 current paper、7 节逐节核验/统一 review owner/测试署名确认、确认前零输出、outline stale 撤卡、bib ≥5、稳定 figure ref、figure asset 篡改后拒绝且旧四件套不变、缺失 selection 后出现与 fill symlink 对抗。与 confirmation/judgement/review/report/kb-cli/bib/figure/find/Obsidian 联合回归 `624 passed`；Python 3.9.6 compile、skill validator `Validated 20 skills.`、`git diff --check` 通过，仓库根 `kb/` 零改动。
- R3 全套：仓库 `.venv` 的 symlink interpreter 会让安装计划隔离探测看不到 venv modules，沿用 R0 已记录的方法，用普通文件型 Miniconda 3.13 scratch venv `/private/tmp/workspace-oss-r3-full-py313` 终验；`2200 passed, 18 skipped, 7 warnings`（9m54s），warnings 均为既有 SWIG deprecation。未改产品门或测试断言来规避环境问题。
- 固定提交冷装 A9/A10：从 `9bdcb24` 直接 `git archive`，以安装器正式 snapshot-source 模式装入 `/private/tmp/workspace-oss-r3-a9a10.0rzwII/workspace2`（约 2s）。测试专用 researcher fixture 建 5 篇 current confirmed paper（不代表真实研究确认），真实生成 PDF 并两次运行 figure extraction，稳定得到 `fig:p-cold-r3-1-abcdef:fig:1` 与 sha256-addressed PNG；find 与 Obsidian note 均命中 caption/ref。
- 冷装随后真实跑中文 outline（含 5 条 confirmed claim + 逐字 evidence）→七节 Agent fill/verify→公共 review owner 预检→七节测试署名确认→原子发布。`references.bib` 恰 5 条去重 entry，MD/LaTeX 各 7 节，MD 与 Obsidian note 均保留稳定 figure ref，output 四件套为 `paper-draft.md / paper-draft.tex / references.bib / publication-manifest.yaml`；篡改 figure asset 后再次发布被拒且旧四件套 bytes 不变。仓库根 `kb/` 全程零改动。
- R3 提交：`ac86d1b`（设计 gate）、`5e0badb`（bibliography）、`2e425ab`（figure index）、`6fcdf44`（section draft）、`9bdcb24`（公开/运行文档）。未 push/tag/merge。
- 下一步：进入 R4 实验导入与周报/PPT/outline 三模板差异化。

### R4 实验与报告（施工中，2026-07-27）
- 只读审计完成，未调用 shipping skills、未修改真实 `kb/`。实验单 run 已有 fingerprint/repeat/seed/config、原子 allocator、comparison 和诊断确认门，但无批量入口；逐条调用会产生部分成功。报告的 weekly/PPT 除标题/小节名外仍共用同一 decisions/claims/events dump，未达到编辑层与 slide card 差异化。
- 设计 gate 已锁：`import-runs` 私有、project-contained staging、W&B JSON/CSV/单层 JSON 目录、raw byte provenance、1000-run 有界、同 item 幂等、conflict fail closed、整批单事务/单 checkpoint；不新增公开 verb，不让 importer 生成诊断。
- 报告编辑层锁为私有 prepare/fill/verify：weekly 四区叙事 + evidence appendix；PPT 每页一结论+证据+current figure+speaker/transition；正文由 runtime Agent 填，脚本只冻结 current catalog、校验 refs 和原子发布，stale 不覆盖旧成品。outline 七节保持独立。
- 下一步：先提交本设计 gate，再按 experiment import → weekly/PPT editorial 两个小里程碑施工与冷验收。

## 决定记录（含偏离蓝图的理由）

| # | 日期 | 决定 | 理由 |
|---|---|---|---|
| D1 | 07-26 | campaign 分支基线取 codex/review-remediation-integration@dfcc0b5 而非 main | Wave 1 改动叠在该分支之上且 HANDOFF 以此为前提；main（cd40859）落后 26 轮 remediation |
| D2 | 07-27 | 概念采用 canonical `concept` unit，而不是 `kb/synthesis/concepts` side YAML | 统一复用 record snapshot、ConfirmationReceipt、索引、review、关系和 Obsidian 基建；代价是把第七类 unit 全面接入 schema/枚举并补全生命周期测试 |
| D3 | 07-27 | 论文分节采用 program-scoped side judgement；citation/figure key 均绑定 canonical identity | 草稿不是新的来源 unit，但每节必须独立确认；稳定 key 不能随作者/题名修订、集合顺序或 crop 遍历顺序漂移 |
| D4 | 07-27 | 批量实验导入整批原子；周报/PPT 使用 Agent editorial fill 而非脚本自动写叙事 | 避免半批 run、重复导入和把机械模板冒充可交付叙事，同时保持用户一句话触发与判断来源透明 |

## 遗留清单

（随轮次滚动更新）
