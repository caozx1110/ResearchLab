# R1 public governance / conversational UX handoff

## STEP 0 — base sync

Worktree 必须以 integration HEAD `5d5c7ec4a463e4ef6bf2067df76301d9c3af407a` 为 base。先核对 HEAD，并确认下列模块存在；若不符，STOP-and-report，不要在错误 base 上施工。不要 reset 用户工作树。

## 目标

修复 2026-07-19 冷验收的 F1/F2/F3/F4/F6，使用户除了 `kb <verb>` 伪 CLI 外只需用自然语言和 agent 对话；public stdout 与 AgentProtocol 的治理语义一致。

## 文件所有权（只动这些）

- `.agents/skills/kb-cli/scripts/kb`
- `.agents/skills/research-config-manager/scripts/config.py`
- `.agents/lib/research/records.py`
- `.agents/skills/research-orchestrator/scripts/orchestrate.py`
- 与上述行为直接对应的现有测试文件；优先：
  - `.agents/lib/research/tests/test_kb_cli_dispatcher.py`
  - `.agents/lib/research/tests/test_review_queue.py`
  - `.agents/lib/research/tests/test_program_dashboard_navigation.py`
  - `.agents/lib/research/tests/test_r1_canonical_convergence.py`
  - `.agents/lib/research/tests/test_r1_conversational_release.py`

不要改 installer/updater、evidence、git_ops、docs/SSOT/BACKLOG 或其他 analyzer owner。

## 必须修复的行为

1. `kb init` 幂等：无参数重复调用保留 human name、language、auto-screen、auto-commit、autonomy/persona；只补真正缺失的默认字段。owner 子进程 `stream=False`，public 成功只一条自然语言总结，无 `[ok]`、`created`、`initial_commit` 或重复输出。
2. 唯一 canonical readiness：判断类 record 保留 record-level `unverified` 不得令“完整 canonical claims + current verification”的 unit 永久停在 awaiting fill；claim 自身 `unverified`、hollow、未验证仍 fail-closed。`review` public 与 AgentProtocol 都只消费 `is_ready_for_human_review`，同一集合、同一数量。
3. `find/status/next/review/reject` public 输出不含内部 enums、`|` 机器行、score/pools、`loose:<id>`、owner-only `init-program`、裸命令/flags/internal paths。错误和成功自然语言化；reject 成功明确“已拒绝”，并只给 `kb undo` 作为撤销入口。
4. `next` 区分空 KB 与已有资料暂无待办；blog `source_ready` 有合理 Agent 下一步；已验证 judgement 进入用户确认，不回到 agent fill；不制造 `kb next` 自循环。
5. 保持所有 public verbs 的退出码、TTY/pipe/headless 语义一致，AgentProtocol 仍有足够结构化字段供 agent 执行。

## 必须新增/强化的回归

- 初始化指定偏好后再普通 init，配置语义不变；public stdout 单一且不泄漏。
- paper/blog/repo 至少覆盖：hollow 不进 review、完整验证 judgement 进入 review、public/protocol ID 集合一致。
- blog-only active/source_ready 的 `kb next` 不是“KB 为空”；无待办但有资料时明确自然语言区别。
- `find/status next invalid/reject` forbidden-token 扫描与成功反馈。
- 在 fresh installed/copy fixture（若现有 helper 可复用）验证，不只测源码树。

## 红线

- 不碰真实 `kb/`；测试仅 tmp_path/临时 clone。
- 不削弱禁自签、逐字 evidence、current verification/receipt 门；hollow 必须 fail-closed。
- 脚本不理解材料，只做 deterministic classifier/过滤/协议。
- public 输出只能自然语言 + `kb <verb>`；无 TTY/input。
- checkpoint 不扩大；不 push。
- 小步 commit-per-piece；拿不准立即 STOP-and-report。

## 验收与交付

先定向 tests，再全量 pytest、compileall、`git diff --check`、worktree clean。报告每个 finding 的独立 fixture/probe、commit SHA、修改文件和测试计数。
