# R26 handoff — report 最终发布事务与 unit 线性索引

## STEP 0 base sync

独立 worktree 必须从主分支当前 `b704c23` 创建并核对 aggregate report commits 已存在；不符 STOP-and-report。

## 文件所有权

只动：

- `.agents/skills/report-author/scripts/report.py`
- `.agents/lib/research/tests/test_report_author.py`

不得动其他文件。

## 目标

1. 复现并修复 render 第二次 current-check 后、实际 report write 前替换 canonical record/evidence 仍写出旧正式 claim 的 P1。
2. 正式文本选择/current-check/write 必须在 exact-target `command_mutation` 内；正式 write 后、transaction commit 前重验全部 formal validators，失败抛出让 journal 恢复原 report bytes或不存在状态。进入事务前已 stale 时只可写 generic pending + factual lane。
3. weekly/stage/ppt/writing/outline 所有输出路径遵守同一门；preference comment 不得成为绕过点。
4. `load_confirmed_claim_sources` 一轮只枚举 canonical records 一次，建立唯一 id index；N=4/8/16 的 yield 为 N（或固定线性上界），duplicate identity fail closed，语义输出兼容。

## 红测/验收

- 确定性 hook 在 render return 后、write 前替换 record/content与 same-bytes inode；旧 claim 不得落盘。
- hook 在 write helper 内/后替换 source；post-write gate 失败并恢复先前 report exact bytes/mode，fresh target则不存在。
- pending/issues/factual lane仍完整，不被 generic 误伤。
- N=4/8/16 unit scan计数线性。
- 跑 report/judgement/survey/experiment focused；Python 3.9 AST、diff-check。

## 红线

不触碰真实 kb，不降低 confirmation/evidence/containment，不输出裸命令/路径，不联网，不引入 Key/付费/插件，不 push/tag。小步 commit；拿不准停止报告。
