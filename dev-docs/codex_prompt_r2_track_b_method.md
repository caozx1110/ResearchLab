# R2 Track B — method proposal / selection lifecycle

## STEP 0 · base sync

- 隔离 worktree HEAD 必须是 `dffcfe7eba239bc373ee8ed327cd435aeb19e464`；先核对 `method.py`、`confirm.py`、`evidence.py`、method tests 存在。
- 不符则只在隔离 worktree `git reset --hard dffcfe7eba239bc373ee8ed327cd435aeb19e464`，再核对。
- 设计依据读取主工作区 `temp/SYSTEM_DESIGN_SSOT.md` 的 2026-07-23 method decisions；shipping SKILL 是被开发源码。

## 目标

把当前“一次 design 自动选 top-1 并推进 program”改成 proposal→runtime-agent fill→verify→human confirm→selection。确认前不能写 `selected_repo_id`、不能推进 `implementation-planning`、不能发正式 method-selected event。

## 只动这些文件

- `.agents/skills/method-designer/scripts/method.py`
- `.agents/skills/method-designer/SKILL.md`
- `.agents/lib/research/tests/test_method_designer.py` 或仓库中现有 method 专项测试
- 可新增 `.agents/lib/research/tests/test_r2_method_lifecycle.py`

不要动 SCHEMAS、kb-cli、orchestrator、report、其他 skills、README/CHANGELOG、真实 `kb/`。

## 行为规格

1. `design` 旧调用保留兼容，但语义最多等价于 prepare：生成 candidate rankings、`proposed_repo_id`、待填 judgement/interface/baseline/risk slots；不产生正式 selection。
2. 增加清晰的 prepare/verify/confirm 生命周期（可用 `design --phase` + 独立 `confirm`，具体 CLI 兼容由你定）。所有 substantive 内容来自 runtime agent；脚本只给空槽与确定性候选。
3. verify 必须校验非空 repo-selection claim 与逐字 evidence，生成 current verification receipt；interfaces/baselines/risks 的 judgement 同样不能是脚本模板冒充完成。
4. confirm 复用现有 ConfirmationReceipt，要求真实 human actor、current-message authorization、非空 canonical claims/evidence。确认成功才原子写 `selected_repo_id`、推进 stage、发布带 binding 的 method-selected event。
5. `proposed_repo_id` 与 `selected_repo_id` 物理分开；下游 interfaces/matrix 在确认前只能标 proposal/pending，不能暗示已选。
6. design 目录及所有 artifact 的创建都在完整 transaction target set 内；prepare/verify/confirm 各有独立 checkpoint。不得 transaction 前 `ensure_dir` 留空目录。
7. 旧未确认 method artifact 读到时 fail-closed 或标 migration-needed，不能自动提升。

## 红线

- 脚本不生成方法判断；只生成可填结构、确定性 resource capacity 和验证。
- 不削弱确认门，不自签，不接受空 claims/evidence。
- 测试用临时目录，不碰真实 `kb/`；用户面无裸命令/内部路径；不 push。

## 验收与提交

- 回归必须证明 prepare 后 stage/selected_repo/event 均未推进；verify 后仍未推进；confirm 后三者同步推进；stale content 后确认失效；abort 不留空目录。
- 跑所有 method tests + program state 相关专项。
- commit-per-piece，至少 lifecycle 与 docs/tests 两个小提交；`git diff --check`。
- 若必须改所有权外共享 schema/API，STOP-and-report，说明最小所需接口，不要越界。

