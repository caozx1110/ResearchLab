# 安装指南

这份指南说明如何把本仓库的 `.agents/` skills 接到 Claude Code、Codex 和可选的 `kb` 命令上。安装入口是仓库根目录的 `install.sh`。

## 硬不变量：symlink，不能 copy

Skill 目录必须用符号链接安装，不能复制。

原因是 skill 脚本会从 `__file__` 开始向上查找 `.agents/lib` 和 `.agents/skills`。`Path(__file__).resolve()` 会跟随 symlink 回到真实仓库，所以 symlink 能找到同级运行库；如果把某个 skill 目录 copy 到别处，脚本会在 import 阶段找不到 `.agents/lib` 并退出。

`install.sh` 只使用 `ln -sfn` 接线 skill 目录，不会复制 skill 目录。

## 准备 Python

脚本首次运行会自动创建并使用项目内受管 `.venv`（含 PyYAML）。用户无需手动创建 venv、运行 pip 或导出 `RESEARCH_PYTHON`。

高级用户仍可用 `RESEARCH_PYTHON` 覆盖解释器；也可用 `RESEARCH_VENV` 覆盖受管 venv 路径。设置 `RESEARCH_NO_MANAGED_VENV=1` 会关闭自动 venv，改用当前解释器，此时需要自备 PyYAML。

安装器仍会做一次 `import yaml` preflight；如果当前 Python 缺 PyYAML，它会提示安装 `requirements.txt` 或设置覆盖变量。

## 快速安装

在仓库根目录运行：

```bash
bash install.sh --help
bash install.sh --claude --project .
```

先看 dry-run：

```bash
bash install.sh --dry-run --claude --project .
```

同时配置 Claude 和 Codex：

```bash
bash install.sh --all --project .
```

系统级 Claude 安装：

```bash
bash install.sh --claude --system
```

可选把 `kb` 放到 PATH：

```bash
bash install.sh --claude --project . --kb-on-path
```

project scope 会写 `./bin/kb`，system scope 会写 `~/.local/bin/kb`。如果目标目录不在 `PATH`，安装器会提示。

卸载安装器管理的 symlink 和 managed block：

```bash
bash install.sh --claude --project . --uninstall
```

## Project Scope

Project scope 面向当前 workspace，默认目录是运行安装器时的 cwd，也可以显式传入：

```bash
bash install.sh --claude --project /path/to/workspace
```

### Claude Code project scope

Claude Code 在项目内读取：

- skills：`<workspace>/.claude/skills/`
- 规则：`<workspace>/CLAUDE.md`

如果 workspace 就是本仓库，安装器会建立：

```text
.claude/skills -> ../.agents/skills
CLAUDE.md      # managed block 内使用 @AGENTS.md
```

如果 workspace 不是本仓库，安装器会把 `.claude/skills` symlink 到本仓库的 `.agents/skills`，并在 `<workspace>/CLAUDE.md` 的 managed block 中生成来自本仓库 `AGENTS.md` 的内容。

`CLAUDE.md` 只更新以下标记之间的内容，不会覆盖用户文件的其他部分：

```text
# >>> workspace-oss managed >>>
# <<< workspace-oss managed <<<
```

`AGENTS.md` 仍是 workspace rules 的唯一源头；重新运行安装器会刷新 managed block。

### Codex project scope

Codex 读取项目根的 `AGENTS.md` 和 `.agents/`。如果 workspace 就是本仓库，不需要额外接线。

如果 workspace 不是本仓库，安装器会尽量创建：

```text
<workspace>/.agents  -> <repo>/.agents
<workspace>/AGENTS.md -> <repo>/AGENTS.md
```

如果目标 workspace 已有真实的 `AGENTS.md`，安装器不会覆盖它，会提示你手动合并规则。外部 workspace 运行脚本时建议设置：

```bash
export RESEARCH_SKILLS_HOME=/path/to/workspace-oss
```

## System Scope

System scope 面向用户主目录，适合希望多个 workspace 共用同一套 skills 的情况。

### Claude Code system scope

Claude Code 的系统级 skills 目录是：

```text
~/.claude/skills/
```

安装器会把本仓库 `.agents/skills/<name>` 下的每个 skill 逐个 symlink 到 `~/.claude/skills/<name>`，并在 `~/.claude/CLAUDE.md` 中追加或刷新 managed block。它不会覆盖 `~/.claude/CLAUDE.md` 的其他内容。

system scope 运行时请设置：

```bash
export RESEARCH_SKILLS_HOME=/path/to/workspace-oss
export RESEARCH_PROJECT_ROOT=/path/to/kb-workspace
```

也可以每次显式传 root：

```bash
kb --root /path/to/kb-workspace status
```

### Codex system scope

Codex 当前没有稳定的 `~/.codex/skills` system-scope 约定。安装器只做安全子集：

- 创建 `~/.codex/workspace-oss/AGENTS.md` symlink。
- 创建 `~/.codex/workspace-oss/.agents` symlink。
- 如果用户已经有 `~/.codex/skills/` 目录，则逐个 symlink skills；否则不主动创建该目录。

实际使用 Codex 时，仍建议在目标 workspace 放置本地 `AGENTS.md` / `.agents`，或设置：

```bash
export RESEARCH_SKILLS_HOME=/path/to/workspace-oss
export RESEARCH_PROJECT_ROOT=/path/to/kb-workspace
```

## 环境变量

| 变量 | 用途 |
|---|---|
| `RESEARCH_PYTHON` | 可选覆盖解释器；默认使用自动受管 `.venv`。 |
| `RESEARCH_NO_MANAGED_VENV` | 设为 `1` 时关闭自动 venv，改用当前解释器，需自备 PyYAML。 |
| `RESEARCH_VENV` | 覆盖受管 venv 路径。 |
| `RESEARCH_SKILLS_HOME` | 指向安装本仓库的目录；system scope 或外部 workspace 需要它来定位 `.agents/skills`。 |
| `RESEARCH_PROJECT_ROOT` | 指向当前 KB workspace；等价于给脚本传 `--root <workspace>`。 |

## 首次运行 KB

安装完成后，在你的 KB workspace 初始化：

```bash
kb init
```

如果还没有把 `kb` 放到 PATH，可以运行 `bash install.sh --kb-on-path`，或直接调用伪 CLI 本体：

```bash
.agents/skills/kb-cli/scripts/kb init
```

后续常用命令：

```bash
kb status
```

`kb init` 会创建 `kb/` 布局和基础配置。非交互环境可以用：

```bash
kb init --non-interactive
```

外部 workspace 或 system scope 下推荐显式传 root：

```bash
RESEARCH_SKILLS_HOME=/path/to/workspace-oss kb --root /path/to/kb-workspace status
```
