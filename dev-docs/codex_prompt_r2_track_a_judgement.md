# R2 Track A — judgement / report convergence

## STEP 0 · base sync（先做，未通过不得施工）

- 隔离 worktree 必须以 `dffcfe7eba239bc373ee8ed327cd435aeb19e464` 为 HEAD。
- 先运行 `git rev-parse HEAD` 并核对下列关键文件存在：`confirm.py`、`evidence.py`、`report.py`、`orchestrate.py`、`experiment.py`、`idea.py`。
- 若 HEAD 不符，在**该隔离 worktree**执行 `git reset --hard dffcfe7eba239bc373ee8ed327cd435aeb19e464` 后重新核对；不要碰主工作区。
- 设计依据读取主工作区绝对路径 `temp/SYSTEM_DESIGN_SSOT.md` 的 2026-07-23 R2 decisions；shipping SKILL 只是被开发源码，不得反向决定需求。

## 目标

修复已复现的非 unit judgement deadzone 和报告洗白：program decision、experiment diagnosis、idea discussion conclusion 必须有 canonical claims + current verification 后才可进入 ready-for-review/confirm；pending decision 不能进入普通 Reporting Events。提供一个可供之后公共 `kb review` 消费的跨-owner discovery/route contract。discussion archive 与 survey 不能继续把无治理 AI judgement 当正式结论；若完整迁移太大，至少 fail-closed 并留下显式 repair/migration 状态，绝不伪装完成。

## 只动这些文件

- `.agents/lib/research/judgements.py`（可新增）
- `.agents/lib/research/SCHEMAS.md`
- `.agents/skills/research-orchestrator/scripts/orchestrate.py`
- `.agents/skills/research-orchestrator/SKILL.md`
- `.agents/skills/experiment-workbench/scripts/experiment.py`
- `.agents/skills/experiment-workbench/SKILL.md`
- `.agents/skills/idea-workbench/scripts/idea.py`
- `.agents/skills/idea-workbench/SKILL.md`
- `.agents/skills/report-author/scripts/report.py`
- `.agents/skills/report-author/SKILL.md`
- `.agents/skills/discussion-archivist/scripts/archive.py`
- `.agents/skills/discussion-archivist/SKILL.md`
- `.agents/skills/literature-synthesizer/scripts/synthesize.py`
- `.agents/skills/literature-synthesizer/SKILL.md`
- 对应既有 tests：`test_report_author.py`、`test_idea_discussion.py`、experiment/orchestrator/synthesis/archive 专项；可新增 `test_r2_judgement_convergence.py`

不要动 `kb-cli/scripts/kb`、method-designer、paper/repo/blog/dataset analyzer、README/CHANGELOG/CONTRIBUTING、真实 `kb/`。

## 行为规格

1. `log-decision`/`diagnose` 不得成功创建 canonical claims 为空且以后必然无法 confirm 的 judgement。采用 prepare→agent-filled claims file→verify/persist 的现有风格；兼容入口若缺 claims 要返回可恢复的 agent-fill 状态，不得写一个假 ready 判断。
2. 每个可确认 side artifact 必须保留原 epistemic types，使用现有 evidence verification + ConfirmationReceipt；禁止自签、禁止空 evidence、内容变更使 receipt 失效。
3. idea discussion verify 后不得只写 nested silo；必须产生可发现、可版本绑定的 canonical judgement，且不能静默覆盖无关已确认 analysis/review claims。必要时用独立 subject artifact。
4. 新 discovery API 返回统一 pending judgement card：`subject(kind,id,owner,path)`、claims、verification、confirmation status、priority/updated_at、内部 confirm route。它只返回 `ready_for_review`，空/未 verify/stale 一律排除。
5. report event classifier fail-closed：`decision` 必须识别为 judgement；未知 event 若含 judgement information types/confirmation status/subject binding 也不得进 ordinary。pending/rejected/stale 分区明确；只有 factual operational event 或 receipt-current judgement 可进正式区。
6. confirmed event 必须引用被确认 subject/receipt；不能只改 event_type 名。
7. discussion archive/survey 任何 substantive AI conclusion 要么走同一 judgement artifact，要么明确 `needs_agent_repair`/pending，绝不能落成已验证正式结论后直接给 report 消费。

## 红线

- 脚本绝不理解材料；只 scaffold、搬运、验证、过门。
- 治理只能加严，不能放松现有 unit gate。
- 测试只用临时目录，绝不碰真实 `kb/`。
- 用户可见输出不泄漏裸命令、`--flag`、环境变量、内部路径或 `NEXT FOR AGENT:`。
- 不 push。

## 验收与提交

- 先加失败回归：pending decision report、无 claims diagnosis/decision、discussion review reachability、stale receipt。
- 跑专项测试与相关既有 tests。
- 至少两次小提交：`judgement lifecycle`、`report/discovery/docs`；每次提交前 `git diff --check`。
- 拿不准 schema 兼容或发现需要改所有权外文件时 STOP-and-report，不要硬编。

