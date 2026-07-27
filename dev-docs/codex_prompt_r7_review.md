# R7 Track U — 对话/Obsidian 多项 review UX handoff

## STEP 0 — base sync

1. 在分配的 worktree 中确认 `git rev-parse HEAD == fe85294`，并确认 `.agents/skills/kb-cli/scripts/kb` 与 `.agents/lib/research/review_batches.py` 存在；不符则停止报告。
2. 读取主工作区 `/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/temp/SYSTEM_DESIGN_SSOT.md` 的 R7.3；shipping SKILL 是产品源码。

## 目标

让对话 Top 3 和 Obsidian Top 3 共享“完整预检、一次授权、跨 owner 原子应用”的语义，并修复 validation failure 提前消费 snapshot。

## 文件所有权（只动这些）

- `.agents/skills/kb-cli/scripts/kb`
- `.agents/skills/kb-cli/SKILL.md`
- `.agents/lib/research/review_batches.py`
- `.agents/lib/research/tests/test_kb_cli_dispatcher.py`
- `.agents/lib/research/tests/test_obsidian_review_roundtrip.py`
- `.agents/lib/research/tests/test_r2_judgement_convergence.py`（只限 public adapter cases）

不要动 owner scripts、judgements.py、surveys.py、orchestrate.py、monitoring.py、preference_selection.py、SCHEMAS、README/USER_GUIDE/DESIGN/version；集成轨处理。

## 必须实现

1. `_load_review_snapshot` 变成纯读/lease-style validation；任何 invalid/duplicate/outside/多项请求、缺署名/授权/evidence、owner preflight failure 都不消费 snapshot。
2. 普通对话允许一次提交展示集合内 1–3 项 confirm/reject/defer，并复用已有跨 owner batch coordinator 在一个 root transaction 中原子 apply；任一失败零业务写、snapshot 仍可修正重试。
3. consumption 必须在锁内重新验证 snapshot/current owner plans/authorization 后与业务提交同一事务；成功一次性消费，replay 明确 already_applied。
4. Obsidian sheet 显示 sanitized public subject id、来源/定位摘要和 `expires_at`；同名同判断项目仍可知情区分。成功后 sheet 写明显 applied/archived 状态或移入安全归档，人工区内容不丢。
5. TTY/pipe/Agent 输出保持不读 stdin；在 standalone terminal 中明确要求回到 Agent 对话继续，不暴露私有 apply flags/token/path。
6. 不降低原有 tamper/symlink/rename/replay/expiry/content-stale/current-message authorization/CAS 防护。

## 必须复现的旧 bug

展示两个 ready item，一次提交两个 ref 当前返回 rc=2；随后单条重试仍 rc=2，canonical 零应用。修后要求：合法双决定原子成功；非法双决定 rc=2 且同 token 单条重试成功。

## 红线

- 不触碰真实 `kb/`；仅 temp fixture。
- 不先提交第一项再处理第二项；不让部分成功。
- 不新增公开 owner 命令/flags；用户面只自然语言 + `kb <verb>`。
- 若新 survey owner 尚未合入，用现有 unit/program/idea/method owner 验 coordinator；集成代理后续接 survey。

## 验收与提交

- 覆盖 ordinary multi confirm/reject/defer、mixed owners、invalid retry、stale/expiry/replay、checkpoint failure、Obsidian duplicate-title/expiry/applied state、TTY/pipe parity。
- 跑三个 owned test modules、`git diff --check`；小步 commit `fix(review):` / `test(review):`；不 push。
