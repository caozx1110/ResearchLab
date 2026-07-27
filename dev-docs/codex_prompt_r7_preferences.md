# R7 Track P — 偏好强制消费与 task binding handoff

## STEP 0 — base sync

1. 在分配的 worktree 中确认 `git rev-parse HEAD == fe85294`，并确认 `.agents/lib/research/preference_selection.py` 存在；不符则停止报告。
2. 读取主工作区 `/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/temp/SYSTEM_DESIGN_SSOT.md` 的 R7.2；shipping SKILL 只作为被修改产品源码。

## 目标

把 PreferenceSelection 从“正确 API + 文档自觉”收敛成真实 consumer 强制合同；未选 soft preference 绝不再静默影响任务。

## 文件所有权（只动这些）

- `.agents/lib/research/preference_selection.py`
- `.agents/skills/research-config-manager/scripts/config.py`
- `.agents/skills/research-config-manager/SKILL.md`
- `.agents/skills/report-author/scripts/report.py`
- `.agents/skills/source-intake/scripts/intake.py`
- `.agents/skills/paper-analyst/scripts/paper.py`
- `.agents/skills/repo-analyst/scripts/repo.py`
- `.agents/skills/dataset-analyst/scripts/dataset.py`
- `.agents/skills/blog-analyst/scripts/blog.py`
- `.agents/skills/method-designer/scripts/method.py`
- `.agents/skills/experiment-workbench/scripts/experiment.py`
- `.agents/skills/literature-search/scripts/search.py`
- `.agents/skills/research-monitor/scripts/monitor.py`
- 上述 skill 的 SKILL.md（只有在真实 consumer contract 变化时）
- `.agents/lib/research/tests/test_effective_preferences.py`
- 各 owner 已有 preference 相关测试；可新增 `test_preference_consumer_matrix.py`

不要动 synthesizer、orchestrate、kb-cli、review_batches、monitoring.py、surveys.py、judgements.py、SCHEMAS、公开 docs/version；集成轨处理。

## 必须实现

1. 共享 helper 能由 owner canonical inputs 计算 task digest，并加载严格绑定的 receipt；caller 不能用任意 64 hex 冒充另一个 task。
2. 每个实际 preference-sensitive operation 有明确 operation name、task digest 和 neutral-default/fail-closed 策略。soft preference 缺 receipt 时不得直读 canonical profile/runtime preferences。
3. 删除或隔离现有 soft bypass，至少包括 report reporting_style、source-intake/paper runtime.paper；资源/constraints/diagnostics 等 hard fallback 可保留，但必须只读取 hard 字段并在 contract 中注明。
4. persistence artifact/protocol 能记录 selection id/digest，使输入或 catalog 变化可判 stale；不要把偏好原值复制进各 skill。
5. operation 级 allowlist 真正生效，而不是只把 operation 写进 receipt；`learned.*` 若无匹配 skill/operation hint 不得广播给所有 skill。
6. 建立真实 consumer 矩阵测试：未选 soft 不影响、选中才影响、wrong skill/op/task 拒绝、catalog 变化 stale、hard constraint 仍执行。测试必须调用真实 owner helper/operation，不只测 eligibility table。

## 红线

- preference 不得关闭 evidence/confirmation/containment/recovery。
- 不触碰真实 `kb/`；测试只用 temp。
- 不让用户复制内部命令/flags/path。
- 不为了测试全绿保留 soft direct-read compatibility；旧 profile 可迁移为 neutral/default，但不能继续静默生效。
- 跨文件接口拿不准 STOP-and-report，不越界改 shared integration 文件。

## 验收与提交

- 跑 `test_effective_preferences.py`、新增矩阵和所有被改 owner 测试；Python 3.9 grammar、`git diff --check`。
- 小步 commit，前缀 `feat(preferences):` / `test(preferences):`；不 push。

