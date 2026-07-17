# Contributing

人类可读 Markdown 默认中文优先。开发/编辑规则、ownership 边界与开发工作流以仓库根的 [AGENTS.md](AGENTS.md)（`CLAUDE.md` 为其软链）为准；面向使用 kb 的 agent 的运行规则（skill 路由、确认门控、写作偏好）见 [.agents/AGENTS.md](.agents/AGENTS.md)。

Python floor: `python_requires >= 3.9`。本仓库保留 `PYTHONPATH=.agents/lib` 约定，不新增 `pyproject.toml`。

提交前的测试门禁：

```bash
pip install -r requirements.txt pytest && python -m pytest .agents/lib/research/tests -q
```

如果改过脚本，还要运行对应脚本的 `--help`，确认 CLI 仍能加载。
