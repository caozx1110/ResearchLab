# Preferences and private operations

Load only this reference for preference binding, private route selection, transaction boundaries, recovery, or public-output rules.

## Task-scoped preference contract

- `plan` 绑定 program、idea、目标与逐字 hypothesis。
- `log-run` 绑定 current experiment version、config revision 与本 run inputs。
- `follow-up` / `diagnose` 分别绑定 current experiment version 与当前 operation content。
- 每次操作由 owner 重算 task digest；wrong skill/operation/task receipt 或 canonical preference drift 在写入前 fail closed。
- 无 receipt 时 soft preference 保持中性；resources、constraints 与 auto-execution boundary 是 hard fallback，始终加载。
- Artifact 只保存 task digest、selection binding 与 hard-value digests，不复制 preference prose。
- Preference 只能改变安全边界内的执行/展示方式，不能降级 evidence、confirmation、journal、CAS 或 recovery。

## Private operation catalog

- `plan`：创建 canonical experiment 和 hypothesis/context binding。
- `log-run`：写一个 factual run。
- `import-runs`：按 bounded batch contract 导入事实。
- `follow-up`：记录独立 action item。
- `diagnose`：prepare/fill/verify judgement。
- `confirm`：只确认 current verified diagnosis subject。

Runtime Agent 在一次自然语言任务内选择 route。用户不需要也不得看到脚本路径、裸命令、flags、环境变量、artifact path 或私有 next step。

内部最小调用形态由 Agent 组装：`plan --title <title> --program-id <program> --idea-id <idea> --hypothesis <verbatim>`，随后以 `log-run --experiment-id <experiment> --config-revision <revision> --seed <seed>` 记录每次 factual run。它只属于私有 command catalog。

## Transaction and recovery

- 所有 mutation 先通过 workspace rules/layout/journal gate，再声明 exact targets。
- Run allocation、duplicate/collision check、artifact identity 与 write 必须在同一 lock/transaction 内。
- Batch import 以整个 batch 为原子边界；diagnosis prepare/verify/confirm 是独立 exact transactions。
- Write/commit boundary 重验 workspace、task/preference、source bytes、catalog 与 target identity。
- 失败保留旧 canonical state；incomplete journal 或 stale preflight 先进入统一 recovery，不做 partial fix-up。

## Public output

只说明记录了什么、哪些输入 stale/缺失、imported/skipped/conflict counts、哪些判断仍需人类确认，并可给自然语言或公开 `kb <verb>`。不得输出内部 schema、path、command、flag 或让用户代跑私有步骤。
