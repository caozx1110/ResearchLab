# Contributing

人类可读 Markdown 默认中文优先。仓库开发规则见 [AGENTS.md](AGENTS.md)（`CLAUDE.md` 为其软链）；普通流程、并行与恢复细则见 [GitHub-only 开发工作流](docs/DEVELOPMENT_WORKFLOW.md)；安装态根指针与最小规则源码分别见 [runtime/AGENTS.md](runtime/AGENTS.md) 和 [runtime/WORKSPACE_RULES.md](runtime/WORKSPACE_RULES.md)。

## 文档与协作边界

- 当前设计：`docs/DESIGN.md`、`docs/decisions/`、五个 owner contract、代码和测试。
- 当前交付：GitHub Epic、Atomic Issue、remote commits、PR 和 Actions。
- 用户合同：`README.md`、用户文档、`CHANGELOG.md`、`SECURITY.md`。
- 安装后 Agent 合同源码：`runtime/AGENTS.md`（根稳定指针）、`runtime/WORKSPACE_RULES.md`（最小 always-on 规则）与 `skills/*/SKILL.md`（按需 owner 规则）；安装目标为根 `AGENTS.md` managed block 与 `.agents/**`。

GitHub 上的 tracked files、Issue、PR、remote refs/commits 和 Actions 是唯一协作与接力面。本地 scratch、提示词、聊天、模型 memory、worktree、stash、未 push commit 或本机日志都不能成为贡献前置或验收证据。

Python floor: `python_requires >= 3.9`。源码 checkout 使用 `PYTHONPATH=runtime/lib`；安装后仍使用 `.agents/lib`。本仓库不新增 `pyproject.toml`。

## GitHub 交付流程

1. Fetch default branch，阅读 tracked 设计、ADR、五个 owner contract、代码和测试，记录 exact baseline。
2. 新蓝图创建或复用一个 Epic；每个独立 outcome 在开工前建立一个 Atomic Issue，写清问题、方案、范围、依赖、风险、验收和测试。
3. 从 Issue 建 branch/worktree，小步 commit；需要接力的 checkpoint 必须 push，并在 Issue 写 full SHA、验证、blocker 和 next action。
4. 并行 track 的 owned paths 必须互斥，由唯一 integrator 合入 delivery branch；人类不负责拼装。
5. 集成候选跑相关与完整门禁，复现承重 claim，确认真实用户知识库/工作区（包括 legacy `kb/` 与 workspace-root 布局）零修改。
6. 创建一个 consolidated PR，使用 `Refs` 关联 Atomic Issue/Epic，记录 candidate SHA、测试/Actions、风险、回滚和限制。
7. Agent 停止于等待人类审查；人类处理 review 后在 GitHub 合并。合并后确认 smoke，再关闭 Atomic Issue并更新 Epic。

默认 `1 Atomic Issue = 1 wave = 1 consolidated PR`。普通改动不需要自定义 comment digest 或 receipt 状态机；跨 Agent 长期并行、takeover、安全、复杂迁移或发布时，按开发协议增加相应增强控制。

Issue/PR 是公开记录。漏洞、治理绕过、路径穿越、数据丢失、凭据暴露或私有研究材料按 `SECURITY.md` 走 private reporting。GitHub 不可可靠读写时停止普通施工、handoff、push 和 merge。

## 提交前门禁

```bash
pip install -r requirements-dev.txt && python -m pytest tests -q
python tools/check_rule_tokens.py
python tools/skill_validator.py skills
```

如果改过维护脚本，还要运行对应的只读帮助/校验入口，确认维护工具仍能加载；这不构成用户研究命令或兼容 CLI。
