# Handoff · installer 重复安装分流与卸载安全

## STEP 0 · base sync

1. 核对施工基线包含提交 `6e6bcfb`，并确认 `install.sh`、`install-lib/ws_sync.py` 及对应测试存在。
2. 当前根工作区有用户运行安装器生成的未跟踪 `bin/kb`；绝不删除、暂存、改写或纳入提交。
3. 若 worktree 过时，先按维护者确认的当前 HEAD 同步并重新核对；拿不准立即 STOP-and-report。

## Track A · 向导动作与 system 快捷入口

只改：

- `install.sh`
- `.agents/lib/research/tests/test_installer.py`

要求：

1. 首屏动作显式为：首次安装、更新、重装或修复、卸载；四个数字映射到四个真实 action。
2. 交互式 install 选定外部 workspace 后，若存在有效 copy manifest，二次询问：更新（推荐）、重装或修复、取消。不得直接报错；不得静默重装。
3. 非交互/无 TTY 的显式 install 遇已有安装继续非零退出。
4. 已有安装分流必须发生在询问 `kb` 快捷入口之前，避免 update/reinstall 仍询问 install-only 选项。
5. system/legacy 卸载无条件调用快捷入口清理；清理函数仍只删除目标匹配的 symlink，外来文件/链接保留。
6. 更新既有 PTY 测试的动作编号，并覆盖 update/reinstall/cancel、非交互 fail-closed、system shortcut 无 flag 卸载。

## Track B · 卸载 drift 保留

只改：

- `install-lib/ws_sync.py`
- `.agents/lib/research/tests/test_bundle_lifecycle.py`

要求：

1. uninstall 对 manifest 列出的 `.agents/**`：仅普通文件且 sha256 与 manifest 一致时删除。
2. 内容 drift、目录/特殊类型、替换成 symlink 时保留并告警；不得跟随 symlink。
3. manifest 最终仍移除；残留文件成为用户自管，`.agents` 非空则保留。
4. `AGENTS.md` managed block 与 `agents_md_sha` 不一致时保留整文件并告警；一致时只移除 block，区块外文本保留。
5. 新测试覆盖受管文件 drift、symlink 替换、AGENTS block drift，以及普通卸载仍完整清理。
6. 冷验收发现 install smoke/runtime 会生成未进 manifest 的 `__pycache__/*.pyc`；只清理能由 manifest 中受管 `.py` 模块名归属的标准 bytecode cache。无关 cache、symlink、目录或异型路径继续保留，clean uninstall 不得因此残留 `.agents`。
7. 2026-07-19 集成审查已独立复现：若正常安装后把 workspace `.agents` 整体替换成指向外部目录的 symlink，direct `ws_sync.py uninstall` 会经 symlink 读取并删除外部 `.install-manifest.json`。在 load manifest 之前对 `.agents` 根和 manifest leaf 做 `lstat` 边界验证；symlink/类型变化/不可读一律 fail-closed，外部 manifest 与内容字节不变，且不得经 prune 跟随链接。
8. 已独立复现 `core.user-owned.pyc` 被宽松的 `module_name + "."` 前缀匹配误删。cache 清理只能匹配由受管 source 与支持的 Python cache tag 严格推导出的标准 `__pycache__` 文件名；同前缀异型 `.pyc` 必须保留。新增两条回归，并用 `/private/tmp/r1_installer_boundary_probe.py` 复验两个布尔值均为 survived/unchanged。

## Track D · 文档

只改：

- `docs/INSTALL.md`

同步四动作入口、重复安装分流、update/reinstall 差异和卸载删除/保留边界；明确安装器不自动改 shell 配置。

## 总红线

- 不碰真实 `kb/`、`.venv/`、用户 shell 配置和未跟踪 `bin/kb`；E2E 只用 `/tmp`。
- 不削弱 manifest/路径/外来 symlink 安全门。
- analyzer/治理逻辑零改动；不 push。
- 用户主路径只输出自然语言 + `kb <verb>`；技术 help/dry-run 可保留参数。
- 各 track 不越过文件所有权；主 agent 独立复现承重声明后统一提交。
