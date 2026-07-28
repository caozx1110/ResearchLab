# Unit Analyst 脚本物理归并 handoff（2026-07-28）

## STEP 0 — base sync

- 施工基线为 `v2-campaign@1d943c4`。先核对 HEAD、`.agents/skills/unit-analyst/SKILL.md`、四套 analyzer script 与 `dev-docs/SYSTEM_DESIGN_SSOT.md`；若 worktree 不是该基线或关键文件缺失，STOP-and-report，不在未知基线上硬改。
- 本任务直接在当前维护分支施工，不 reset、不 push、不 tag、不合并主分支。

## 目标

把 paper/repo/dataset/blog 四套 analyzer 的业务脚本物理迁入 `.agents/skills/unit-analyst/scripts/`，让 discoverable skill 与其 bundled resources 一致；所有新调用走单一 registry，同时保持四套历史持久逻辑身份不变。

## 文件面

- 设计/说明：`dev-docs/SYSTEM_DESIGN_SSOT.md`、`dev-docs/CAMPAIGN.md`、`CHANGELOG.md`、`.agents/AGENT_GUIDE.md`、`.agents/skills/unit-analyst/SKILL.md`。
- canonical scripts：`.agents/skills/unit-analyst/scripts/{paper,repo,dataset,blog}.py`。
- compatibility launchers：`.agents/skills/{paper,repo,dataset,blog}-analyst/scripts/*.py`，只允许薄转发。
- 单一 registry 与消费者：`.agents/lib/research/`、source-intake、knowledge-base-manager、kb-cli、research-orchestrator。
- 路径与安装生命周期相关测试：仓库根 `tests/`。

## 不变量与红线

- 不碰真实 `kb/`；所有行为测试只用 `/private/tmp`。
- 理解仍来自 runtime Agent；移动脚本不得引入自动判断。
- 保留 `paper-analyst:*`、`repo-analyst:*`、`dataset-analyst:*`、`blog-analyst:*` 的 preference/journal/receipt/provenance/diagnostic identity；不迁移或重签任何既有判断。
- 旧路径 launcher 不含业务逻辑，不复制 schema，不改变 argv/exit code/stdout/stderr；新生成命令只使用 canonical 路径。
- 更新安装必须把旧 full script 原子替换为 launcher 并新增 canonical script；本地 managed drift 仍 fail closed。
- 确认、evidence、CAS、锁、journal、checkpoint 门只可保持或加严。
- 小步提交；不确定兼容语义时 STOP-and-report。

## 验收

- `rg` 证明当前运行时代码除 compatibility launcher/显式迁移测试外不再硬编码旧路径。
- 四个 canonical script `--help` 可执行；旧 launcher 的代表性 `--help` 与 canonical exit/output 一致。
- analyzer、intake、review、orchestrator、installer/update 定向测试通过；全量 pytest、Python 3.9 compile、15-skill validator、规则预算与 `git diff --check` 通过。
- fresh install 只把 canonical path 作为新导航目标；从旧 manifest update 后旧 full script 被替换为 launcher、canonical scripts 入 manifest，最终安装副本 Git/manifest 一致。
- 真实 `kb/` 六个保护文件 SHA-256 与施工前一致。
