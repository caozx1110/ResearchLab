# R17 standalone literature continuation + empty-library status

## STEP 0 — base sync

以当前 integration HEAD 为 base，先核对 `research-orchestrator/scripts/orchestrate.py`、`sources.py` 与 `kb-cli/scripts/kb` 均存在且包含 Agent-led portfolio。若 worktree 过时，停止并报告，由维护者同步；不得在未知旧 base 上施工。

## 文件所有权

只改：

- `.agents/lib/research/sources.py`（若需要共享的只读 stage 枚举/绑定 helper）
- `.agents/skills/research-orchestrator/scripts/orchestrate.py`
- `.agents/skills/kb-cli/scripts/kb`
- 对应 `test_agent_next_selection.py`、`test_kb_cli_dispatcher.py`，必要时新增单一聚焦测试文件

不要改 updater/installer/journal/git_ops/version/release docs；不要碰真实 `kb/`。

## 要求

1. standalone literature stage 是 durable work：in-progress 投影 resume；terminal + effective include/maybe + 未 materialized 投影 human selection。
2. monitor-bound 与 composite-owned stage 不重复；terminal 无待选不制造动作。
3. dependency 绑定 stage bytes、stop、candidate identity/screening/status，任何漂移使旧 portfolio snapshot 失效。
4. stage 枚举拒绝 symlink/非普通文件/越界；读取失败 fail closed，不把外部 URL/note 直接送到公开 stdout。
5. `kb status` 零 unit 但有 program 时明确报告 program；公开名称过 sanitizer、最多展示少量，其余计数，完整 ids 仅私有 protocol；纯读零写。
6. 用户可见输出只含自然语言与 `kb <verb>`，不得泄漏 shell、flags、路径、`${...}`、TTY 要求或 `NEXT FOR AGENT:`。
7. 脚本不判断论文价值；effective include/maybe 只能机械读取 persisted screening/effective_screening。
8. 修 repo review P1：`readiness_violations` 必须把 canonical `record_external_source_contract(record)` 传给 verification；public list/snapshot/Obsidian apply 全部只消费 `discover_pending_judgements` 的同一 ready set，不能让粗 `is_ready_for_human_review` 单独放行。不得放宽 repo file:line evidence gate，多项 apply 继续全或无。

## 验收

- 先补红测并证明旧 HEAD 失败。
- 覆盖 standalone in-progress、terminal selection、materialized、excluded、composite-owned、monitor-bound、byte drift、symlink/非普通 stage。
- 覆盖 0 records + 0/1/多 programs、危险 program display text、status 纯读。
- 覆盖真实 mini repo 分析 receipt 的 standalone review confirm/reject，以及 repo+blog+dataset Obsidian batch；证明旧版“能展示、不能应用”转为成功，任一 item stale 时仍整批零写。
- 跑两份 owned tests、dispatcher/high-risk next tests、AST、diff check。
- 小步提交；拿不准 owner/selection 语义时 STOP-and-report。
