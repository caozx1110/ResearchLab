# 安装指南

这份指南说明如何把这套 workspace skill bundle 接入 Claude Code、Codex 和可选的 `kb` 快捷入口。安装目标是你的 **workspace 根目录**：安装后的 `.agents/` 与之后生成的 `kb/` 同级，而不是把 bundle 安装进 `kb/`。安装入口是仓库根目录的 `install.sh`。

> **普通用户只需完成一次安装。** 安装是日常使用之前唯一的技术 bootstrap；成功后请回到 Agent 对话，只用自然语言或 16 个 `kb <verb>` 伪 CLI 快捷入口。除“新用户快速安装”和“首次运行 KB”外，本页的 flags、scripts、环境变量与显式 paths 都是管理员、维护者或 CI 自动化参考，普通用户不需要复制或理解，Agent 也不应把它们作为日常操作步骤暴露给用户。

## 新用户快速安装

### 直接把 GitHub 链接交给 Agent（推荐）

你可以不先克隆仓库。把仓库链接粘贴给 Codex 或 Claude Code，并直接说：

```text
把这个 research skill 系统安装到我当前 workspace。先检查目标目录和已有 AGENTS.md，再使用仓库自带安装器；保留 kb、虚拟环境和所有用户文件。安装后验证 skill metadata、kb help 和一次全新临时 workspace 的 init，不要替我推送或发布。
```

仓库对 Agent 的安装合同如下，Agent 应自行完成，不让用户复制内部 flags：

1. 将链接视为代码来源而不是知识材料；先用版本控制把它检出到临时目录，不通过管道执行远端脚本。记录仓库 origin、branch 与 commit，并检查根目录存在 `install.sh`、`.agents/VERSION`、`.agents/AGENTS.md` 与 `.agents/skills/`。
2. 把当前 workspace 根作为安装目标，绝不能把 `kb/` 当目标；已有普通根 `AGENTS.md` 时，确认安装器只追加/更新带 marker 的受管区块并保留块外原文。目标是 symlink、类型冲突、marker 异常或已有受管区块漂移时停止解释，不能覆盖整文件或猜测修复。
3. 先让安装器生成 Agent JSON 计划（它隐含 dry-run）。终端保持短预览并显示目标数、冲突数和 semantic plan digest；JSON 精确列出 action、scope、tools、source provenance、canonical distributable tree map/digest、按执行顺序排列的全部 targets、每项来源内容 digest 与目标前置状态、冲突、条件性 runtime 变化及可复现的 apply contract。除 Agent 明确指定的 JSON 计划文件外，这一步不写 workspace、HOME、runtime 或 Python cache。计划文件必须位于目标 workspace 与 HOME 之外。
4. 核对计划中的 source commit 与 source tree digest 仍等于当前 checkout，目标只包含受管 `.agents/`、根规则文件、所选 Agent 接入和明确标出的条件性 `.venv` runtime tree。完成审阅后，Agent 自动计算这份最终计划文件的精确 byte SHA-256，替换 apply contract 中的 `COMPUTE_AFTER_REVIEW` 占位，再在用户已要求“安装”的授权范围内执行；用户不需要查看、复制或填写 digest。安装器会在解析 JSON 或触碰首个目标前，以 no-follow 方式读取同一个普通文件 inode，同时校验外部 byte SHA 与 semantic plan digest，再验证源码树和每个目标的前置状态。计划后出现空白、换行、键序、编码字节、未提交源码、来源身份或目标状态变化时整次操作零写失败。计划和应用都使用显式参数，非交互运行不读取 stdin。
5. 安装后核对 manifest、20 个 skill、bundle version、`kb help` 与临时目录中的 `kb init`；真实 `kb/` 不参与验收。
6. 不安装 Obsidian 插件、daemon、cron、watcher 或全局 Python 包；不 push、tag、publish，也不改 shell 配置。可选终端快捷入口只在用户明确要求时创建。

这使“粘贴 GitHub 链接让 Agent 安装”成为受支持主路径；当前没有市场包，也不需要插件。

在仓库根目录运行下面这条一次性引导命令：

```bash
bash install.sh
```

安装向导第一屏会明确列出四个动作：

1. **首次安装**：给新的 workspace 接入 skills。
2. **更新**：同步已有安装中的版本变化。
3. **重装或修复**：重新铺设全部受管文件，用于修复缺失或损坏。
4. **卸载**：移除 skills 接入，同时保留研究资料和本地运行环境。

首次安装时，向导会继续询问以下事项，按回车即可接受推荐选项：

1. 选择“首次安装”。
2. 选择你使用的 AI 工具：Claude Code、Codex，或两者都用。
3. 选择“仅当前或指定工作区”。推荐 project scope，不推荐 system scope。
4. 确认 workspace 根目录；不要选择其中的 `kb/` 子目录。
5. 选择是否创建终端 `kb` 快捷命令。选择创建后，向导会提示安装完成后先在终端运行 `kb help`，再运行 `kb init`。它只是额外便利，不影响在 AI 对话中使用 `kb`。

如果选择“首次安装”后，目标 workspace 已有本安装器的有效安装记录，向导不会直接报错，也不会静默重装，而会在询问终端快捷命令之前改为询问：更新（推荐）、重装或修复，或取消。非交互或 CI 中重复执行首次安装仍会非零退出，避免自动化任务在没有确认时改变动作。

确认页会列出安装目标和将发生的改动。安装完成后，打开刚才选择的 AI 工具，在对话中输入：

```text
kb init
```

初始化会先让知识库可用，再提供“现在设置”（推荐）和“先跳过”。选择跳过不会追加或覆盖偏好，也不妨碍立即添加、检索或分析资料；之后可直接说“补充我的研究偏好”。初始化后可用 `kb status` 查看当前状态。此后不需要继续操作安装脚本；更新、重装和卸载由 Agent 或管理员按需处理，并保留已有研究资料。

## 管理员参考：推荐安装模型

推荐把 bundle 以 project-scope copy 方式安装到外部 workspace 根：

- `bash install.sh --all --project DIR` 把整棵 `.agents/`（含使用规则 `.agents/AGENTS.md`）复制到 `DIR`。
- 安装器把使用规则写到 workspace 根 `DIR/AGENTS.md`，并配置所选 agent 工具。
- workspace 数据继续放在 `DIR/kb/`，受管 Python 环境放在 `DIR/.venv/`。

整棵 `.agents` 一起复制是受支持的安装单元；不要只复制单个 skill，也不要把 bundle 指向或安装进 `DIR/kb/`。system scope 与 symlink 模式只保留兼容性，不作为新安装建议。

project copy workspace 不需要 `RESEARCH_SKILLS_HOME`。若当前 Python 缺运行依赖，正式安装末尾的 smoke check 或首次运行会把受管 venv 建在 `DIR/.venv`；依赖已满足时不会无条件创建。

## 管理员参考：运行环境

Python 3.9 或更高版本是安装器硬依赖。脚本首次运行会自动创建并使用项目内受管 `.venv`（含 PyYAML）。用户无需手动创建 venv、运行 pip 或导出 `RESEARCH_PYTHON`；安全更新会保留已有受管 venv，因此 shipping runtime 同样保持 Python 3.9 兼容。

高级用户仍可用 `RESEARCH_PYTHON` 覆盖解释器；也可用 `RESEARCH_VENV` 覆盖受管 venv 路径。设置 `RESEARCH_NO_MANAGED_VENV=1` 会关闭自动 venv，改用当前解释器，此时需要自备 PyYAML。

安装器仍会做一次 `import yaml` preflight；如果当前 Python 缺 PyYAML，只会提示首次使用时自动准备受管运行环境，不需要手动运行 pip。只有显式设置 `RESEARCH_NO_MANAGED_VENV=1` 时，缺少 PyYAML 才是硬错误。

## 管理员参考：命令行与自动化

以下命令供管理员、维护者和 CI 使用。普通用户完成上面的引导安装后不需要运行它们，也不需要把任何 flag 或内部 path 交给 Agent。

在 bundle 仓库根目录运行，并把 `--project` 指向目标 workspace 根：

```bash
bash install.sh
bash install.sh --help
bash install.sh --claude --project /path/to/workspace
```

直接 `bash install.sh` 无参数会进入中文交互向导；支持数字选择，输入无效时会原地重问。显式 flag 和非交互/CI 用法保持不变；`NO_COLOR=1` 可关闭终端颜色。

先看 dry-run：

```bash
bash install.sh --dry-run --claude --project /path/to/workspace
```

Agent 安装前的可审计计划把终端输出限制为短预览，并把每个最终目标写入显式 JSON 文件；确实可能需要依赖解析时，`.venv` 会被标成条件性、边界明确的 runtime tree，并写清 owner/cleanup 合同，不展开其平台相关内部依赖文件。除指定 JSON 文件外，它不会写 workspace、HOME、runtime 或 Python bytecode cache。计划文件应放在目标 workspace 与 HOME 之外：

```bash
bash install.sh --agent-plan-json /tmp/workspace-oss-plan.json --claude --project /path/to/workspace --yes
```

schema 3 JSON 中的 `targets` 是完整、按执行顺序排列的精确清单，并为所有 copy/write/managed-block 目标保存来源内容 digest、为每个目标保存 `absent | regular | symlink | directory` 前置状态；`source.distributable_tree` 绑定受管 payload、安装器输入的相对路径、类型、mode、字节（或 symlink target）与总 digest；`conflicts` 列出会被保留或跳过的冲突；`conditional_runtime_changes` 单独暴露条件性运行环境树。若该数组为空且操作仍需 Python，`runtime_precondition` 会绑定实际选中的 canonical 解释器、完整文件 identity、core import probe 及选择来源；apply 在任何 workspace/HOME/runtime 写入前按同一选择规则重跑纯读 preflight，并要求当前选择与计划完全一致。PATH 不再包含原 current/later entry、解释器或显式 override 漂移都会要求自动重做计划，不能靠只对本次 apply 有效的绝对路径制造“安装成功、下次立即失败”。尚未机器绑定完整 invocation chain 的 ready managed venv 会保守保留条件性 runtime tree，但稳定 apply 不会因此改写已有 venv。`apply_contract` 携带计划路径、semantic plan digest、source tree digest、source commit 与无交互应用参数，并以 `COMPUTE_AFTER_REVIEW` 明示最终文件 byte SHA 必须在审阅后由 Agent 外部计算。该 byte SHA 不写回同一 JSON，避免伪造不可能成立的自引用文件哈希。Agent 必须核对这些字段、自动填入最终 byte SHA 后再执行应用合同，不能把计划模式换成网络下载或隐藏脚本执行；计划路径任一 leaf/ancestor symlink、非普通文件或超出有界大小都会在解析前被拒绝。

同时配置 Claude 和 Codex：

```bash
bash install.sh --all --project /path/to/workspace
```

已有外部 project copy 安装可以显式选择更新、重装或卸载：

```bash
bash install.sh update --project /path/to/workspace
bash install.sh reinstall --project /path/to/workspace
bash install.sh uninstall --project /path/to/workspace
```

可选把 `kb` 放到 PATH：

```bash
bash install.sh --claude --project /path/to/workspace --kb-on-path
```

选择创建终端快捷命令时，project scope 会写 `<workspace>/bin/kb`。安装完成时，如果快捷入口已经在当前 `PATH` 中，完成页会提示可直接运行 `kb help` 和 `kb init`；如果不在，完成页会提示把上方显示的目录加入 `PATH`，重新打开终端后运行 `kb help`。安装器只创建快捷入口，不会修改任何 shell 配置。AI 对话中的 `kb <verb>` 不受终端 `PATH` 影响。

## 管理员参考：Project Scope Copy

Project scope 面向单个 workspace。推荐始终显式传入 workspace 根目录：

```bash
bash install.sh --all --project /path/to/workspace
```

### 仓库内开发模式

如果你在 bundle 源仓库内开发，安装器不会 copy，也不会写 manifest。这个模式用于维护 bundle，不是面向普通 workspace 的推荐安装路径。Claude 使用：

```text
.claude/skills -> ../.agents/skills
CLAUDE.md      # managed block 内使用 @AGENTS.md
```

Codex 直接读取仓库已有的 `AGENTS.md`（开发者工作流；`CLAUDE.md` 为其软链）和 `.agents/`（含使用规则 `.agents/AGENTS.md`）。

### 推荐：外部 workspace copy

如果 workspace 不是本仓库，安装器会先创建自包含拷贝：

```text
<workspace>/.agents/                      # 真实目录，整棵拷贝
<workspace>/.agents/.install-manifest.json
<workspace>/AGENTS.md                     # 保留用户原文，只维护本 bundle 的 marker 区块
<workspace>/.claude/skills -> ../.agents/skills
<workspace>/CLAUDE.md                     # managed block 内使用 @AGENTS.md
```

`AGENTS.md` 与普通文件形式的 `CLAUDE.md` 都只更新以下标记之间的内容，不会覆盖用户文件的其他部分：

```text
# >>> workspace-oss managed >>>
# <<< workspace-oss managed <<<
```

如果目标 workspace 已有普通 `AGENTS.md` 且没有异常 marker，安装器会保留块外原文并加入本 bundle 区块；update/reinstall 也只维护该区块。`AGENTS.md` 是 symlink、非普通文件、marker 结构异常，或已有受管区块发生未授权漂移时会 fail closed，不跟随链接、不替换整文件。

`.install-manifest.json` 记录源仓、源 commit、安装时间、每个受管文件的 sha256，以及 `AGENTS.md` 的受管状态。它用于后续 update/uninstall 的精确同步和删除。

外部 workspace 可以是独立 Git 仓；如果不想把安装产物纳入业务仓库，建议忽略：

```gitignore
.agents/
AGENTS.md
.claude/
bin/kb
```

## 管理员参考：更新（update）

外部 copy workspace 用显式 update 子命令：

```bash
bash install.sh update --project /path/to/workspace
```

`update` 只适用于外部 project copy 安装；bundle 源仓库内的开发模式请用版本控制更新。

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

## 管理员参考：重装或修复（reinstall）

外部 copy workspace 的受管文件缺失、损坏，或需要完整重新铺设时使用：

```bash
bash install.sh reinstall --project /path/to/workspace
```

`update` 与 `reinstall` 的区别是：

- `update` 只同步源版本带来的 added/changed/removed 差异；若受管文件存在本地漂移，会默认阻断，适合日常升级。
- `reinstall` 根据当前源重新铺设完整的受管文件集，并重新运行安装检查，适合恢复缺失、损坏或已漂移的受管文件；它不会删除 `kb/`、`.venv/` 或受管范围外的用户文件。

两者都不会由重复 `install` 静默触发。若源中新出现的受管路径与用户本地文件冲突，重装会停止；只有明确接受覆盖该冲突时才使用 `--force`。

## 管理员参考：卸载（uninstall）

外部 copy workspace 用显式 uninstall 子命令：

```bash
bash install.sh uninstall --project /path/to/workspace
```

copy 安装的卸载会执行以下操作：

- 对 manifest 记录的 `.agents/**` 受管文件，只有目标仍是普通文件且 sha256 与安装记录一致时才删除。内容已修改、类型已变化或已被替换成 symlink 的目标会保留并告警；安装器不会跟随 symlink。
- 清理由这些受管 Python 模块运行生成的标准 `__pycache__/*.pyc`；只按 manifest 中的模块名匹配，无关 cache 和异常类型仍保留。
- 对 workspace 根 `AGENTS.md`，受管区块 digest 未变化时只移除该区块，区块外的用户文本保留；digest 已变化时整份文件保留并告警。
- 移除属于本安装器的 `.claude/skills` symlink 和 `CLAUDE.md` managed block。
- 删除安装 manifest。因漂移而保留的文件从此成为用户自管文件；如果 `.agents/` 仍非空，目录也会保留。
- 尝试清理终端 `kb` 快捷 symlink：project scope 对应 `<workspace>/bin/kb`，system scope 对应 `~/.local/bin/kb`。project、system 和旧版兼容卸载都会执行这一步；只有链接目标仍指向本安装时才删除，普通文件或指向其他目标的链接会保留并告警。

`DIR/kb`、`DIR/.venv` 和未写入 manifest 的用户文件永远保留。卸载后 workspace 只是变为 unmanaged，研究数据不受影响。

旧版外部 symlink 安装仍可用兼容卸载：

```bash
bash install.sh --all --project /path/to/workspace --uninstall
```

如果目标有真实 `.agents` 但没有本安装器 manifest，安装器会拒绝删除 `.agents`，但仍会清理明确属于 workspace-oss 的 Claude managed block 和匹配的 symlink。

旧版 system/symlink 安装只保留兼容卸载能力。卸载时不需要额外记得安装时是否选择过快捷命令，安装器都会安全尝试清理目标匹配的快捷 symlink。新 workspace 请使用 project-scope copy 安装，避免跨 workspace 共享路径和源仓依赖。

## 管理员参考：环境变量

| 变量 | 用途 |
|---|---|
| `RESEARCH_PYTHON` | 可选覆盖解释器；默认使用自动受管 `.venv`。 |
| `RESEARCH_NO_MANAGED_VENV` | 设为 `1` 时关闭自动 venv，改用当前解释器，需自备 PyYAML。 |
| `RESEARCH_VENV` | 覆盖受管 venv 路径。 |
| `RESEARCH_SKILLS_HOME` | 仅 legacy system/symlink 模式需要；推荐的 project copy workspace 不需要。 |
| `RESEARCH_PROJECT_ROOT` | 指向当前 KB workspace；等价于给脚本传 `--root <workspace>`。 |

## 普通用户：首次运行 KB

安装完成后，打开已配置的 Claude Code 或 Codex，在对话中输入：

```text
kb init
```

初始化完成后，可以继续输入：

```text
kb status
```

`kb init` 会先创建可立即使用的知识库布局，再由 AI 询问要“现在设置”还是“先跳过”。快速设置只集中询问真实署名、语言与术语风格、研究方向、资源与重要约束；当前版本记录和论文初筛设置可以直接接受默认值。资源会保存到下游研究流程可直接读取的画像，约束会追加去重并保留已有项。跳过不产生额外偏好写入，后续说“补充我的研究偏好”即可继续；真实署名只会在第一次确认研究判断前再次要求。是否创建终端快捷命令不影响这条对话式主路径。

从这里开始，普通用户的完整产品表面就是自然语言和 16 个 `kb <verb>` 伪 CLI。Agent 负责私下选择 owner、参数、解释器与内部路径；用户不需要回到本页复制管理员命令。
