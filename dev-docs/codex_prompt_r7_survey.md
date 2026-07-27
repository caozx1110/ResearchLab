# R7 Track S — survey JudgementArtifact 与可恢复 composite handoff

## STEP 0 — base sync

1. 在分配的 worktree 中确认 `git rev-parse HEAD == fe85294`，并确认 `.agents/skills/literature-synthesizer/scripts/synthesize.py`、`.agents/lib/research/surveys.py`、`.agents/lib/research/judgements.py` 存在；若不符先停止报告，不要在错误 base 上施工。
2. 读取主工作区 `/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/temp/SYSTEM_DESIGN_SSOT.md` 的 R7.1、R7.4 与 judgement/review invariants；shipping SKILL 是产品源码，不作为自我验收规则。

## 目标

关闭“survey 逐字证据已 verify，但永远 needs_agent_repair/无法 review/confirm/report”的死路，并为后续 composite route 提供 durable stage/state contract。

## 文件所有权（只动这些）

- `.agents/skills/literature-synthesizer/scripts/synthesize.py`
- `.agents/skills/literature-synthesizer/SKILL.md`
- `.agents/lib/research/surveys.py`
- `.agents/lib/research/judgements.py`
- `.agents/lib/research/tests/test_literature_synthesizer.py`
- 可新增 `.agents/lib/research/tests/test_survey_judgement_lifecycle.py`

不要动 kb-cli、report-author、preference_selection、orchestrate、monitoring、SCHEMAS、README/USER_GUIDE/DESIGN/VERSION/CHANGELOG；它们由集成轨负责。

## 必须实现

1. `prepare` 在没有合格且 current/confirmed 的输入 unit 时 fail with structured evidence-gap/composite handoff；不写零 unit fill scaffold。
2. `verify` 成功后生成一等 survey judgement：canonical claims、current verification、upstream bindings、content digest、pending confirmation；移除新产物的 `needs_agent_repair`。历史旧产物仍可兼容读取并显式要求 repair。
3. 提供 owner API/CLI 的 confirm/reject 以及 public batch coordinator 所需的 `prepare_review_batch_decision` / `apply_review_batch_decision` 同构接口；确认必须 current-message authorization、非 AI actor、evidence、expected snapshot 与 ConfirmationReceipt，拒绝不伪造确认。
4. `judgements.py` 能发现 ready survey judgement，生成稳定 subject/owner/path/substance/current binding；stale/空 claims/旧 needs_agent_repair 不进入 review。
5. 定义 durable composite survey state/helper，至少能表达 search、selection、intake/analysis、synthesis、review/confirm 的 ordered stages、inputs/outputs/blocker/resume 状态；脚本只校验与搬运，不语义选择论文。若完整 orchestrator 接线需共享文件，提供清晰 API，不越界修改。
6. confirmed survey 的任一内容、claims、verification、upstream unit/confirmation/evidence bytes 变化会 stale；confirm/reject/replay/CAS fail closed。

## 红线

- 脚本不理解材料、不生成 claim 内容；Agent fill 才产生理解。
- 不触碰真实 `kb/`；测试只用 pytest temp。
- 不自签、不削弱 evidence/confirmation/containment/journal/lock/CAS/recovery。
- 用户可见输出不得泄漏 owner 命令、flags、内部路径或 `${...}`。
- 若跨 owner 接线需要 kb-cli/report 文件，STOP-and-report 给集成代理，不要越界。

## 验收与提交

- 覆盖：zero-input、prepare/fill/verify、review discovery、confirm/reject、stale upstream/content/evidence、replay、batch plan/apply、旧 needs_agent_repair migration。
- 跑本 track 测试与 `test_r2_judgement_convergence.py` 相关用例；`git diff --check`。
- 每个承重 piece 小步 commit，commit message 前缀 `feat(survey):` / `test(survey):`；不 push。

