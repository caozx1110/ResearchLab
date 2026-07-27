# D2 · dataset first-class + kb next integrity handoff

## STEP 0 · base sync

- 核对当前 HEAD、`.agents/VERSION`、`research.paths/ids/records`、source-intake、orchestrator 与 analyzer 文件都存在。
- 本工作树已有 ar5iv/screening-first 未提交改动；它们属于同一维护者工作，必须保留，不得 reset/checkout 覆盖。
- 若关键模块与当前工作树不符，STOP-and-report；本轮禁止 `git reset --hard`，因为现有未提交改动是已知用户工作。

## Objective

一次性解决真实 `/Users/czx/Documents/knowledge_base` 暴露的两类缺陷：dataset 被当 repo 导致伪代码扫描；聊天承诺未持久化导致 `kb next` 选择错误 loose maintenance。

## Locked design

1. 新增 canonical `dataset` kind、`d-` ID、`datasets/` 目录和 `dataset-analyst` prepare/fill/verify/confirm/reject owner。
2. Hugging Face dataset URL 自动推断为 dataset；source-intake/kb-cli/索引/确认/检索/导航/report 路由全覆盖。
3. repo scan 仅接受真实代码树；HTML snapshot/card 页面不可扫描。
4. `record_workflow_state == done` 时 `safe_unit_step` 无条件无动作；program durable work 优先 loose maintenance。
5. repo mechanical scan 不手工撤销有效 confirmation；真正 claim/evidence 变化仍由 canonical receipt validator fail-closed。
6. 增加 journaled dataset migration：dry-run 默认、显式 apply；repo→dataset 改 subject 后旧确认失效并需重新确认，保留 legacy id/history/program/links。
7. Agent 只有在 program `next_actions` 已持久化后才可承诺 `kb next` 继续综述/路线图。

## File ownership

- Design/docs: `temp/SYSTEM_DESIGN_SSOT.md`, `temp/BACKLOG.md`, `.agents/lib/research/SCHEMAS.md`, `.agents/AGENTS.md`, relevant `SKILL.md`/agent metadata/public maturity docs.
- Core: `.agents/lib/research/{paths,ids,records,common,intake_cli,index,...}.py` only as required by canonical kind.
- Owners: source-intake, kb-cli, research-orchestrator, repo-analyst, knowledge-base-manager, new dataset-analyst.
- Tests: add focused dataset/migration/next/repo-confirmation tests and update kind matrices.
- Preserve all pre-existing modified files and unrelated user changes.

## Red lines

- 不碰真实 `kb/`；E2E 只用临时 workspace。
- 脚本不理解 dataset；只 prepare + validate evidence + persist。
- 禁自签；judgement 必须 canonical claims + verbatim evidence + current verification + user authorization。
- public stdout 只自然语言 + `kb <verb>`，不泄漏脚本、flag、内部路径或 protocol。
- migration 先 dry-run、apply 才写；journal/lock/CAS/undo 完整。
- 不 push、不 tag、不发布。

## Commit / recovery discipline

- 本轮不替维护者提交；保持小步可审 diff。
- 任一步与当前 schema/确认 digest 不适配时 STOP-and-report，不硬编迁移 receipt。

## Acceptance

- HF dataset 推断、intake、prepare/verify/review/confirm 全链成立。
- confirmed/done unit 即便旧字段 `scan_status=not_started` 也不出现在 `kb next`。
- HTML snapshot repo scan fail-closed 且零写；真实 code tree scan 成功且不手工撤销有效 receipt。
- persisted program survey action 优先 loose maintenance；无 program 时不虚构 survey。
- HIW-500 风格旧 repo migration dry-run/apply/undo 合同测试通过。
- skill validator、compileall、专项测试、完整 suite、diff-check 全绿；真实 `kb/` 零改动。
