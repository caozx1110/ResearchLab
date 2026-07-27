# R5 handoff — 结构减法、批量园艺、批注与偏好回流

设计源：`dev-docs/SYSTEM_DESIGN_SSOT.md` 的 R5 锁定段、`dev-docs/reviews/skill-refactor-blueprint-2026-07-26.md` 的 G5/G6/结构锁、`dev-docs/CAMPAIGN.md`。开发态不得调用 shipping skills 作为设计依据。

## STEP 0 — base sync

先核对 `git branch --show-current` 为 `v2-campaign`、HEAD 含 R4 closure、关键 runtime/测试树存在。若 agent worktree 基线不是当前 `v2-campaign` HEAD，停止修改并报告；只有主维护者明确给出当前 HEAD 时才可同步。不要自行猜 commit，不要把别的 worktree 改动带入。

## Piece 1 — tests 迁根

只动：`.agents/lib/research/tests/**`（删除）、`tests/**`（新增）、`pytest.ini`、`.github/workflows/ci.yml`、`CONTRIBUTING.md`、必要的 installer/test path assertions。机械移动全部测试；新增 `tests/repo_paths.py`，消除基于测试旧深度的 `parents[N]`。先定向，再全套。独立 commit。

## Piece 2 — bundle/skill/metadata

只动：`.agents/skills/**`、`.agents/lib/research/skill_validator.py`、`.agents/lib/research/preference_selection.py`、`.agents/lib/research/common.py`、`.agents/AGENTS.md`、必要 routing tests、`tools/research-navigator/**`、`tools/generate_skill_metadata.py`。创建 discoverable `unit-analyst` facade；四 analyzer 目录保留脚本但删除 discovery metadata；wiki helper 并入 kb-cli；navigator 移出 bundle。metadata SSOT 生成 15 份 tracked openai.yaml，validator check 闭合。不要迁移 record/receipt 的历史 owner identity。独立 commit。

## Piece 3 — G5

只动：source-intake、kb-cli add/next/status、orchestrator portfolio、survey rebuild、knowledge-base-manager governance/checkpoint、安全临时目录 GC 及对应新测试。`kb add` 1..20 整批 preflight + 单 transaction/checkpoint；任何 late failure 零 canonical 写。ordinary stale survey 只能生成重建候选/新 pending judgement；园艺不删除/不 defer/不确认。独立 commit。

## Piece 4 — G6/A11

只动：human-note intake、blog analysis handoff、learnings/preference confirmation、judgement/public review adapter、对应新测试。人工 Markdown 原文件不改；freeze 后才取证。偏好确认绑定逐字 observation、真实 signer、当前消息授权、snapshot/CAS；封死 `review_learning/promote_learning` 的 pending→生效旁路。独立 commit。

## Piece 5 — Q4/docs/acceptance

只动：`.agents/AGENTS.md`、`.agents/AGENT_GUIDE.md`、discoverable SKILL.md、token gate/requirements、公开文档、SCHEMAS、CAMPAIGN/GOLDEN。固定 `cl100k_base` 统计完整三文件组合，最坏 `<=8000`。冷装到 `/private/tmp` 跑结构/G5/G6/A11；再跑 Python 3.9 compile、validator、全套 pytest、install/update/uninstall。独立 commit。

## 全程红线

- 根 `kb/` 真实数据只读；测试只能在临时目录。
- 不 push、不 tag、不 merge；commit per piece，只 stage 明列文件。
- 原子写/journal/CAS/锁/checkpoint exact paths、逐字 evidence、ConfirmationReceipt、真人签字与 current-message authorization 只可加严。
- analyzer 脚本绝不理解材料：只准备结构、搬运 Agent fill、验证 evidence/currentness、过门。若出现“给材料、没有 runtime Agent 就自动吐理解/偏好/判断”的函数，删除它。
- 用户面只允许中文自然语言和 `kb <verb>`；无裸命令、flags、`${...}`、内部/绝对路径、TTY 依赖或 `NEXT FOR AGENT:`。
- 不覆盖他人未提交改动；不 stage `.learnings/ERRORS.md`。

## STOP-and-report

遇到需迁移 canonical owner/schema、需放松确认门、公开 verb 增删、无法把文件面保持互斥、或 fixture 与设计不适配时，停止该 piece，给出已复现证据、当前 diff 与两个安全选项；不要硬编兼容层或静默扩大范围。
