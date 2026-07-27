# CAMPAIGN 台账（v2-campaign）

> 施工规格：`dev-docs/PROMPT-full-campaign-2026-07-26.md`。设计 SSOT：`dev-docs/reviews/skill-refactor-blueprint-2026-07-26.md`（蓝图 v2）。
> 恢复方式：新会话读本文件 + PROMPT 即可继续（用户说"继续 campaign"）。
> 分支：`v2-campaign`（自 `codex/review-remediation-integration` @ dfcc0b5 建出，携带 Wave 1 未提交改动）。不 push、不 tag、不合 master。
> 红线：仓库根 `kb/` 只读；承重墙（PROMPT §5）禁改；strict 档语义不变；AI 不可自签。

## 验收清单（Definition of Done）

### 功能验收
- [ ] A1 四类真实来源一链入库+深读骨架，≤2 次交互；5 链批量不逐个盘问
- [x] A2 快筛已移除，auto_screen 退役
- [ ] A3 概念页（提取→确认→定义带逐字出处+关联清单；find/Obsidian 可达）
- [ ] A4 检索三类（中/英/代码符号带 file:line），常规库 <3s
- [ ] A5 综述 ≥5 单元（taxonomy/trends/gaps，claim 带证据绑上游，确认后可被报告消费）
- [ ] A6 idea 全链（捕获→分析→讨论归档→选中→method handoff）
- [ ] A7 实验导入 ≥10 run；diagnose 确认门；audit 零 error 零 dirty
- [ ] A8 周报一句话可交差；PPT 素材差异化；与 outline 三者明显不同
- [ ] A9 论文 outline→分节草稿→bib 导出→LaTeX/MD 落 output/
- [ ] A10 图表 caption/编号索引，稳定引用键
- [ ] A11 偏好观察式记录+确认后生效；init 两问落盘且被消费
- [ ] A12 undo 点名；restore 无参列清单可按编号恢复；中断 resume 成功
- [ ] A13 交互章程冷验收（三场景 10 条逐条打分）

### 质量验收
- [x] Q1 pytest 全套绿（scratch `.venv`；R1 `2132 passed, 18 skipped`；不得回退新行为凑绿）
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

## 决定记录（含偏离蓝图的理由）

| # | 日期 | 决定 | 理由 |
|---|---|---|---|
| D1 | 07-26 | campaign 分支基线取 codex/review-remediation-integration@dfcc0b5 而非 main | Wave 1 改动叠在该分支之上且 HANDOFF 以此为前提；main（cd40859）落后 26 轮 remediation |

## 遗留清单

（随轮次滚动更新）
