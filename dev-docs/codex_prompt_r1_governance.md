# R1 Track G — trust chain / governance handoff

## STEP 0 · base sync（必须先做）

1. 你在主 agent 已创建的独立 worktree 中工作；先 `pwd`、`git status --short --branch`、`git rev-parse HEAD`。
2. 基线必须是 `4a857327f7e3d989bfbd604f6879c3350ea3a6e3`，关键模块 `evidence.py/confirm.py/records.py` 与三 analyzer 均存在。不符立即 STOP-and-report；不要自行 reset 到别的提交。
3. 先读根 `AGENTS.md`、主工作区绝对路径下 `temp/SYSTEM_DESIGN_SSOT.md` 的“发布闭环 R1”、本 handoff 全文。

## 目标

封闭 claims → verification → ConfirmationReceipt → report 的信任链，并把 program decision 纳入同一 judgement gate。所有变更只加严治理，不得弱化现有 hollow/self-sign/evidence 规则。

## 文件所有权（只动这些）

- `.agents/lib/research/evidence.py`
- `.agents/lib/research/confirm.py`
- `.agents/lib/research/records.py`
- `.agents/lib/research/SCHEMAS.md`
- `.agents/skills/paper-analyst/scripts/paper.py`
- `.agents/skills/blog-analyst/scripts/blog.py`
- `.agents/skills/repo-analyst/scripts/repo.py`
- `.agents/skills/report-author/scripts/report.py`
- `.agents/skills/research-orchestrator/scripts/orchestrate.py`
- `.agents/skills/experiment-workbench/scripts/experiment.py`
- `.agents/skills/idea-workbench/scripts/idea.py`
- 上述行为专属测试；优先新建 `test_r1_governance.py`，若必须更新既有治理测试只改同一契约断言。

禁止碰：`git_ops.py/common.py/journal.py/sources.py/intake.py`、kb-cli/knowledge-base-manager、README/USER_GUIDE/DESIGN、installer/updater/CI/VERSION。

## 必做行为

1. **Canonical claims**
   - paper/blog/repo 的 verify 成功后，把同一份已验证 claims 持久化进 `record.payload.claims`；sidecar 可保留但必须是投影，不是唯一真源。
   - judgement track confirm 时 canonical claims 必须非空；receipt `claim_ids` 必须非空且覆盖 canonical claims。
   - report 只消费 confirmed、receipt-bound canonical claims。修复真实回归：sidecar 有 claims、payload 0、receipt `claim_ids=[]`、报告 0 claims。

2. **Evidence containment / external repo contract**
   - 普通 artifact 只允许 unit 根内的相对路径；拒绝 absolute、`..` 和 symlink escape。
   - repo 工作区源码证据不能被误杀：实现显式 external-source/base-root contract，并验证 artifact resolve 后仍在声明 repo root 内。不要让普通 blog/paper claim 借此越界。

3. **Verification receipt + byte binding**
   - analyzer verify 成功后写 canonical verification receipt：`verified_at`、claims digest、evidence digest、每个 artifact 的 canonical identity + byte sha256。
   - confirmation 复用且校验该 receipt；artifact 字节、claims 或 confirmable content 改变时 confirmation 自动降级 pending。
   - evidence digest 不能只哈希 path/locator/quote。

4. **ConfirmationReceipt / user authorization**
   - judgement confirmation 必须要求并保存 `user_authorization`（用户原话）与 `authorization_source=user_message`，以及 `verified_at`。
   - actor AI 检测由 exact membership 改为大小写归一后的 token/边界检测，至少拒绝 `Codex Agent`、`OpenAI Codex`、`assistant-1`、`GPT-5.6`、`Claude Code`，但不能误拒常见真实人名。
   - 代码/文档诚实：本地 CLI 不是密码学身份认证；它校验 attestation 完整性并留痕。
   - fact-only metadata 可保留轻确认，但 AI self-sign 仍拒绝。

5. **统一 program decision gate**
   - `log-decision` 不得凭一个 `confirmed/auto_confirmed` 值直接写事实。创建 judgement decision 默认/强制 pending。
   - 增加独立 confirm-decision 行为或等价两阶段：必须 actor/evidence/user authorization/receipt，确认后保留 inference/evaluation 类型。
   - 用户面由 U track 清洗；本轨只实现内部 owner 行为。

   同一原则覆盖 experiment diagnosis/confirm 与 idea analysis/review/select：经 verify 的 judgement claims 进入 canonical payload + verification receipt；任何调用 `confirm_unit`/selection confirmation 的路径传递 user authorization，并保留 epistemic 类型。Idea 的“选择推进”仍是 selection 语义，不伪装成事实确认，但其用户授权必须留痕。

6. **Workflow classifier（orchestrator 半边）**
   - 统一识别 paper/blog/repo 的 `awaiting_agent_fill/ready_to_verify/ready_for_review`，hollow 和 failed-retryable 不进入 user-confirmable。
   - 不要只 special-case paper。

7. **Recovery caller scope（仅本轨文件）**
   - 本轨触及的 `checkpoint_and_report` 调用必须显式传本 operation 目标路径；不要等待底层 `git add -A`。

## 红线 / 反模式

- 脚本绝不理解材料：只搬运 agent 已填内容、验证 evidence、写 receipt。出现“给材料无 agent 就生成判断”的函数，删掉。
- 不碰真实 `kb/`，E2E 一律 `/tmp`。
- 不 push；小步 commit-per-piece。
- 不通过删测试、放宽 hollow/validate_write、允许空 claims 来“修绿”。
- 外部 repo evidence 必须显式建模，不能重新开放任意绝对路径。
- 拿不准 receipt schema 或兼容策略就 STOP-and-report，不硬编。

## 最低测试 / 承重复现

- absolute / `..` / symlink evidence fail；合法 unit-relative 和合法 repo-root-relative pass。
- 三 analyzer verify 后 `payload.claims` 非空且与 sidecar digest 相同。
- judgement 无 claims、无 verification、artifact 改字节、claims 改动、`Codex Agent` 等 actor 均拒绝。
- valid human + exact user authorization + current verification receipt 可确认，receipt claim_ids 非空。
- program decision 直接 confirmed 拒绝；两阶段确认成功且 receipt 完整。
- confirmed canonical claim 出现在 report。
- 先跑定向测试，再用主工作区受管解释器 `/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python -m pytest ...` 跑所有与你文件相关的既有测试（worktree 自身没有 `tmp/rvenv`）。

## 交付

按 piece 提交（建议：containment → canonical claims/verification → receipt → decision/report/workflow → tests/docs schema），最后报告 commit 列表、测试、仍需主 agent 处理的跨轨接口。不要 merge/push。
