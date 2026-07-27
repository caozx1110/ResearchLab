# R26 handoff — portfolio history post-write rollback gate

## STEP 0 base sync

独立 worktree 必须从主分支当前 `b704c23` 创建，确认 `5dcf03f` validation plan snapshot retention 已存在；不符 STOP-and-report。

## 文件所有权

只动：

- `.agents/skills/research-orchestrator/scripts/orchestrate.py`
- `.agents/lib/research/tests/test_orchestrator_program_next.py`（若真实 owner test 文件不同，只可选一个现有 portfolio test 文件并在回报中说明）

不得动其他文件。

## 目标

- 确定性复现 `require_program_decisions_current()` 写前成功、history write 后 source container 内容或 same-bytes inode 被替换，旧代码仍返回 success/stored stale decision。
- 在同一个 `mutation_transaction` 内，history write 后、commit 前再次用原 `_PortfolioDecisionValidationPlan` 重验全部 bound program decision snapshots；失败抛出并由 transaction 恢复 history exact bytes/mode或删除 fresh target。
- changed 与 idempotent replay 两条路径都保留最后 current gate；不得把 digest-only 重算当 snapshot current。
- stable path 首次写和 replay行为兼容，checkpoint只在成功提交后发生。

## 验收/红线

覆盖 content replacement、same-bytes new inode、existing history rollback、fresh history zero residue、稳定写与 replay。跑 portfolio/orchestrator/judgement focused、Python 3.9 AST、diff-check。真实 kb零修改；不联网、不引入 Key/付费/插件；不 push/tag；小步 commit。
