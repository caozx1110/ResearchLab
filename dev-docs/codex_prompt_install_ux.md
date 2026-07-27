# install.sh 首次安装 UX 施工 handoff

## STEP 0 · base sync

先核对 `git rev-parse HEAD` 与关键文件 `install.sh`、`.agents/lib/research/tests/test_installer.py`、`docs/INSTALL.md`。预期基线为 main `bd85defd8511d3f0f65cfa51a2c0da15aab7107f`；若 worktree 不是该基线且无用户改动，先 `git reset --hard bd85defd8511d3f0f65cfa51a2c0da15aab7107f`，再核对后施工。主工作区不得执行该 reset。

## 文件所有权

只动：`temp/SYSTEM_DESIGN_SSOT.md`、`temp/BACKLOG.md`、`temp/codex_prompt_install_ux.md`、`install.sh`、`.agents/lib/research/tests/test_installer.py`、`docs/INSTALL.md`。不碰 skill 治理逻辑和真实 `kb/`。

## 锁定行为

- 交互向导统一中文、单列、短句，使用数字选择；保留英文 action/agent/scope 输入兼容。
- 输入无效时原地提示并重问，不退出安装器。
- 新手主路径不展示 scope、symlink、manifest、managed block、内部 `.agents/...` 脚本路径。
- 确认页说明操作、AI 工具、工作区、安装范围、终端快捷入口与数据保留。
- 完成页只输出自然语言与 `kb init` / `kb status` 伪 CLI；不展示内部执行路径。
- `--help` 明确“第一次使用直接无参数运行”，并把参数按用途分组。
- flags、非 TTY fail-fast、退出码、update/uninstall ownership guard、`NO_COLOR` 保持兼容。

## 红线与反模式

- 绝不碰真实 `kb/`；测试只用 pytest `tmp_path` 或 `/tmp`。
- 治理红线不变；不改 analyzer 或确认门。
- 用户可见的向导/完成页不得泄漏裸内部命令、`--flag`、`${…}`、内部路径或 `NEXT FOR AGENT:`。显式 `--help`/dry-run/诊断是技术界面例外。
- 不依赖 TTY 才能完成显式 flags 调用；向导的 PTY 仅用于人类直接运行 `install.sh`。
- 不 push；拿不准安装安全边界时 STOP and report。

## 验收

1. `bash -n install.sh`。
2. `NO_COLOR=1 bash install.sh --help`，确认无 ANSI、首次使用入口在首屏。
3. PTY 驱动无参数 `--dry-run`：数字选择可走通、错误输入原地重问、步骤编号不虚报总数。
4. 非 TTY 缺必需 flags 仍立即失败，不等待输入。
5. `python -m pytest .agents/lib/research/tests/test_installer.py -q` 与全量 `.agents/lib/research/tests`。
6. `git status --short` 确认真实 `kb/` 未动。

小步修改、逐步验证；若要提交则 commit-per-piece。
