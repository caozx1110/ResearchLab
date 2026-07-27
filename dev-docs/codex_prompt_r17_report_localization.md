# R17 report localization + task-bound language preference

## STEP 0

从维护者给定 integration HEAD 建独立 worktree；读根 AGENTS.md、SSOT §3.10/R7.2 与 SCHEMAS report-author。shipping skill 是源码。base 不符先报告。

## 文件所有权

只动 `report-author/scripts/report.py`、`research/preference_selection.py`、report/preference consumer tests，必要时 report-author SKILL.md 的运行合同。不得动 source/kb-cli/orchestrator/review/updater/installer/journal/version/release docs/真实 kb。

## 合同

- report-author 每个 operation 的 disclosed/consumed allowlist 都包括 `profile.preferences.language_preference` 与 reporting style；Agent 仍负责 task-bound selected subset。
- 无 selection 或未选 language 时产品默认中文；current receipt 明确选英文值时才英文。不得直接从 profile 偷读 soft preference。
- 中文覆盖 title、headings、event/decision labels、pending/unverified 与 missing marker；逐字 evidence、canonical claim text、subject identity 不翻译/不改字节。
- language/style 只改展示，不改输入筛选、epistemic/confirmation 类型；report snapshot/preference binding 继续 current。
- outline 同样本地化；现有英文显式 preference 行为保留可测。

## 验收

- 默认 weekly/stage/PPT/writing/outline 中文且证据逐字相同；显式 task-bound `en-US` receipt 输出英文；仅 profile 英文但未选择仍中文；错 task/stale receipt 零写拒绝。
- operation→consumed-input registry/matrix 完整；未选 reporting style 仍 neutral。
- report-author、preference consumer/matrix tests、AST、diff check。小步提交，不 push。
