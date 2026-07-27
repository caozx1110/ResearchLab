# Handoff · kb 快捷命令使用提示

## STEP 0 · base sync

1. 核对工作树干净、HEAD 与当前维护基线一致，并确认 `install.sh`、`docs/INSTALL.md`、`.agents/lib/research/tests/test_installer.py` 均存在。
2. 若 worktree 落在过时基线，先与维护者确认当前主线 HEAD；按既定流程同步到当前 HEAD 后重新核对，未确认前不得施工。

## 目标

不自动修改任何 shell 配置，只增强用户选择“创建 kb 快捷命令”后的说明，让用户知道安装完成后如何使用，以及终端暂时找不到 `kb` 时该做什么。

## 文件所有权

只改：

- `install.sh`
- `.agents/lib/research/tests/test_installer.py`
- `docs/INSTALL.md`

SSOT 与 BACKLOG 由维护者另行回写；不得改其它文件。

## 行为合同

1. 交互向导的“创建 kb 快捷命令”选项必须同时说明安装成功后可先运行 `kb help`，再运行 `kb init`；不得在安装成功前输出会让 partial-conflict 场景误以为已经可用的下一步。
2. 安装完成且快捷入口已在当前 `PATH` 时，明确说明终端可直接运行 `kb help` / `kb init`。
3. 快捷入口已创建但目录不在当前 `PATH` 时，不得假称可直接使用；说明把上方提示的目录加入 `PATH`、重新打开终端后运行 `kb help`。
4. 保持现有 `--kb-on-path` 语义：只创建快捷入口，绝不改 `.zshrc`、`.bashrc`、`.profile` 等 shell 配置。
5. AI 对话中的 `kb <verb>` 与终端 PATH 无关；提示里保持这一区分。
6. 用户可见主路径只出现自然语言与 `kb <verb>`；不得输出 `export PATH=...`、内部 Python/脚本路径、`${…}`、`NEXT FOR AGENT:` 或新 raw flag。

## 测试

- PTY 向导选中创建快捷命令后能看到使用说明。
- 默认不创建时不出现误导性的终端可用声明。
- PATH 已包含快捷入口目录与未包含两种完成页分支均被覆盖。
- `bash -n install.sh`、installer 定向测试全绿。
- 所有 E2E 只用临时 HOME/workspace；绝不碰真实 `kb/` 或用户 shell 配置。

## 红线

- 不放松治理门控，不改 analyzer/业务逻辑。
- 不自动写 shell 配置，不 push。
- 小步提交；任何输出合同不确定之处 STOP-and-report。
