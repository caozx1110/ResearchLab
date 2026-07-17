# 安装指南

这份指南说明如何把这套研究工作流接入 Claude Code、Codex 和可选的 `kb` 命令。安装入口是仓库根目录的 `install.sh`。

## 新用户快速安装

在仓库根目录运行：

```bash
bash install.sh
```

安装向导会依次询问五件事，按回车即可接受推荐选项：

1. 选择“安装或重新配置”。
2. 选择你使用的 AI 工具：Claude Code、Codex，或两者都用。
3. 选择“仅当前或指定工作区”。工作区就是你准备存放项目和研究资料的文件夹。
4. 确认工作区目录。
5. 选择是否创建终端 `kb` 快捷命令。它只是额外便利，不影响在 AI 对话中使用 `kb`。

确认页会列出安装目标和将发生的改动。安装完成后，打开刚才选择的 AI 工具，在对话中输入：

```text
kb init
```

初始化完成后可用 `kb status` 查看当前状态。更新和卸载都会保留已有研究资料。

## 安装模型（进阶）

安装器有两种模型：

- system scope 和同仓 `--project .` 使用 symlink。脚本经 `Path(__file__).resolve()` 跟随 symlink 回到源仓库，并在源仓库里找到同级 `.agents/lib`。
- 外部 `--project DIR` 使用 copy。安装器把整棵 `.agents/`（含使用规则 `.agents/AGENTS.md`）拷到 `DIR`，并把该使用规则写到 workspace 根 `DIR/AGENTS.md`；脚本从 `DIR/.agents/...` 向上 walk-up，命中 `DIR/.agents/lib` 和 `DIR/AGENTS.md`（root marker）。

反向不变量：整棵 `.agents` 一起拷贝是安全的；只把孤立的单个 skill 目录拷到别处会破坏 sibling import，不支持。

外部 copy workspace 不需要 `RESEARCH_SKILLS_HOME`。首次运行脚本时，受管 venv 会建在 `DIR/.venv`，安装器本身不会创建 venv。

## 准备 Python

`python3` 是安装器硬依赖。脚本首次运行会自动创建并使用项目内受管 `.venv`（含 PyYAML）。用户无需手动创建 venv、运行 pip 或导出 `RESEARCH_PYTHON`。

高级用户仍可用 `RESEARCH_PYTHON` 覆盖解释器；也可用 `RESEARCH_VENV` 覆盖受管 venv 路径。设置 `RESEARCH_NO_MANAGED_VENV=1` 会关闭自动 venv，改用当前解释器，此时需要自备 PyYAML。

安装器仍会做一次 `import yaml` preflight；如果当前 Python 缺 PyYAML，只会提示首次使用时自动准备受管运行环境，不需要手动运行 pip。只有显式设置 `RESEARCH_NO_MANAGED_VENV=1` 时，缺少 PyYAML 才是硬错误。

## 命令行与自动化

在仓库根目录运行：

```bash
bash install.sh
bash install.sh --help
bash install.sh --claude --project .
```

直接 `bash install.sh` 无参数会进入中文交互向导；支持数字选择，输入无效时会原地重问。显式 flag 和非交互/CI 用法保持不变；`NO_COLOR=1` 可关闭终端颜色。

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

选择创建终端快捷命令时，project scope 会写 `./bin/kb`，system scope 会写 `~/.local/bin/kb`。如果目标目录不在 `PATH`，安装器会提示。

## Project Scope

Project scope 面向当前 workspace，默认目录是运行安装器时的 cwd，也可以显式传入：

```bash
bash install.sh --all --project /path/to/workspace
```

### 同仓 project scope

如果 workspace 就是本仓库，安装器不会 copy，也不会写 manifest。Claude 使用：

```text
.claude/skills -> ../.agents/skills
CLAUDE.md      # managed block 内使用 @AGENTS.md
```

Codex 直接读取仓库已有的 `AGENTS.md`（开发者工作流；`CLAUDE.md` 为其软链）和 `.agents/`（含使用规则 `.agents/AGENTS.md`）。

### 外部 project scope

如果 workspace 不是本仓库，安装器会先创建自包含拷贝：

```text
<workspace>/.agents/                      # 真实目录，整棵拷贝
<workspace>/.agents/.install-manifest.json
<workspace>/AGENTS.md                     # 源仓 .agents/AGENTS.md 使用规则的受管拷贝
<workspace>/.claude/skills -> ../.agents/skills
<workspace>/CLAUDE.md                     # managed block 内使用 @AGENTS.md
```

`CLAUDE.md` 只更新以下标记之间的内容，不会覆盖用户文件的其他部分：

```text
# >>> workspace-oss managed >>>
# <<< workspace-oss managed <<<
```

`AGENTS.md` 冲突会拒绝安装：如果目标 workspace 已有真实 `AGENTS.md`，安装器不会覆盖，也不会 fallback 到 embedded block。先移动、合并或删除冲突文件后再安装。

`.install-manifest.json` 记录源仓、源 commit、安装时间、每个受管文件的 sha256，以及 `AGENTS.md` 的受管状态。它用于后续 update/uninstall 的精确同步和删除。

外部 workspace 可以是独立 Git 仓；如果不想把安装产物纳入业务仓库，建议忽略：

```gitignore
.agents/
AGENTS.md
.claude/
bin/kb
```

## 更新：update

外部 copy workspace 用显式 update 子命令：

```bash
bash install.sh update --project /path/to/workspace
```

`update` 只适用于外部 project copy 安装。system scope 请重跑 install；同仓 project scope 请用 `git pull` 更新仓库。

clean-sync 安全合同：

- 只枚举和写入 `DIR/.agents` 子树与单个 `DIR/AGENTS.md`。
- 永不枚举、写入或删除 `DIR/kb`、`DIR/.venv`。
- 排除 `__pycache__/`、`*.pyc`、`*.pyo`、`.venv/`、`.DS_Store` 和 manifest 本身。
- 删除只针对 manifest 里记录过、source 已不再提供、且仍在 `.agents` 下的文件；用户新增到 `.agents` 的文件会保留。
- 每个删除目标在 unlink 前都会重新校验仍落在 `DIR/.agents` 内；不使用 `rm -rf` 或 `rsync --delete`。

update 会打印 old commit -> new commit 和 added/changed/removed 差异。若发现 manifest 记录的 `.agents` 文件被本地改过，会阻断并退出；确认要覆盖托管漂移时再加：

```bash
bash install.sh update --project /path/to/workspace --force
```

`--force` 只绕过漂移门，不扩大删除范围，也不会触碰 `kb/` 或 `.venv/`。源不变时重复 update 是 no-op，manifest 字节不变。

也可以 dry-run：

```bash
bash install.sh update --project /path/to/workspace --dry-run
```

dry-run 打印真实差异、漂移和计划动作，但零写入。

## 卸载：uninstall

外部 copy workspace 用显式 uninstall 子命令：

```bash
bash install.sh uninstall --project /path/to/workspace
```

copy 安装会按 manifest 精确删除 `.agents` 下的受管文件，移除 `.claude/skills`、`CLAUDE.md` managed block 和可选 `bin/kb`。`AGENTS.md` 只有在 manifest 标记为 managed 且 sha 仍匹配时才会删除；如果用户改过，会保留并告警。

`DIR/kb` 和 `DIR/.venv` 永远保留。卸载后 workspace 只是变为 unmanaged，研究数据不受影响。

旧版外部 symlink 安装仍可用兼容卸载：

```bash
bash install.sh --all --project /path/to/workspace --uninstall
```

如果目标有真实 `.agents` 但没有本安装器 manifest，安装器会拒绝删除 `.agents`，但仍会清理明确属于 workspace-oss 的 Claude managed block 和匹配的 symlink。

system scope 继续使用旧 flag 形式：

```bash
bash install.sh --claude --system --uninstall
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

- 创建 `~/.codex/workspace-oss/AGENTS.md` symlink（指向源仓 `.agents/AGENTS.md` 使用规则）。
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
| `RESEARCH_SKILLS_HOME` | 指向安装本仓库的目录；system scope 或 legacy 外部 symlink 安装需要它。外部 copy workspace 不需要。 |
| `RESEARCH_PROJECT_ROOT` | 指向当前 KB workspace；等价于给脚本传 `--root <workspace>`。 |

## 首次运行 KB

安装完成后，打开已配置的 Claude Code 或 Codex，在对话中输入：

```text
kb init
```

初始化完成后，可以继续输入：

```text
kb status
```

`kb init` 会创建 `kb/` 布局并由 AI 用自然语言收集基础偏好。是否创建终端快捷命令不影响这条对话式主路径。
