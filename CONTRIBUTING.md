# Contributing

人类可读 Markdown 默认中文优先。开发/编辑规则、ownership 边界与开发工作流以仓库根的 [AGENTS.md](AGENTS.md)（`CLAUDE.md` 为其软链）为准；面向使用 kb 的 agent 的运行规则（skill 路由、确认门控、写作偏好）见 [.agents/AGENTS.md](.agents/AGENTS.md)。

## 文档边界

- 当前用户合同：`README.md`、`docs/`、`CHANGELOG.md`、`SECURITY.md`。
- 当前开发合同：根 `AGENTS.md`、本文件、`.agents/lib/research/SCHEMAS.md`。
- 安装后 Agent 合同：`.agents/AGENTS.md`、`.agents/AGENT_GUIDE.md`、各 `SKILL.md` 与必要 reference。
- `dev-docs/` 是维护者本地、Git-ignored 的 SSOT 草案、backlog、一次性 handoff 与历史审查工作台，不进入提交或安装包。稳定结论必须先 graduate 到上述 tracked 文档，公共 clone 不得依赖本地工作台。

历史 handoff 和 audit 保留其时间点上的路径、commit 与测试数，不用于说明当前布局。审查文档漂移时，以实际 `.agents/skills/*/SKILL.md` inventory、当前 schema 和发布测试为准。

Python floor: `python_requires >= 3.9`。本仓库保留 `PYTHONPATH=.agents/lib` 约定，不新增 `pyproject.toml`。

提交前的测试门禁：

```bash
pip install -r requirements-dev.txt && python -m pytest tests -q
python tools/check_rule_tokens.py
python .agents/lib/research/skill_validator.py .agents/skills
```

如果改过脚本，还要运行对应脚本的 `--help`，确认 CLI 仍能加载。
