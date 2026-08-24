# Product runtime source

这个目录存放 workspace-oss 的共享运行库和安装规则源码；当前 shipping inventory 收敛为 5 个 Markdown-first skill：`research-vault`、`research-capture`、`research-analysis`、`research-workbench`、`research-review`。安装时只将这五个可发现入口和声明的 runtime 文件复制到 `.agents/`。

## Layout

- `../skills/`: 五个可发现 skill；普通 Markdown 是用户语义真相。
- `lib/research/`: 源码树中的 Python helper。安装 allowlist 只发布 `v2_bootstrap.py`、`legacy_detector.py`、`updater.py` 与 package marker；其余 v1 helper 只供源码级回归测试，不进入安装态。
- `AGENTS.md`: 只供根 managed block 使用的稳定加载指针；不复制到 `.agents/`。
- `WORKSPACE_RULES.md`: 最小 always-on runtime 合同，详细 owner 流程留在五个 skill 的一跳 references。

## Shipping boundaries

- `research-vault`: root/Home/layout, visible Markdown identity, indexes, atomic writes, journals, locks, CAS, and recovery.
- `research-capture`: exact source bytes, immutable revisions, readers, maps, readiness, health, and optional adapters.
- `research-analysis`: visible claims, exact evidence, source revision bindings, synthesis, and stale propagation.
- `research-workbench`: project, idea, method, experiment, discussion, decision, and report pages.
- `research-review`: independent evidence audit, authorization, decisions, and digest-bound receipts.

Defuddle、`obsidian-markdown`、`obsidian-cli`、`obsidian-bases` 与 AnyDoc 都是外部接口或可选 adapter，不复制到 runtime，不进入 inventory。`.research/` 与对象内 `.source/` 只能保存来源、证据和运行证明，不得成为第二语义真相。

旧 v1 skill implementation files may remain in the source checkout as non-discoverable internal material while hard cutover removes their shipping entrypoints. The installer and release enumeration must never package those legacy directories.

仓库根 `tools/` 与 ignored `/.agents/` 下的维护者工具不属于产品发布树，也不会复制到安装后的 workspace。

## Runtime

Runtime 会优先复用已安装 PyYAML 的兼容 Python；只有需要时才在 workspace-local managed environment 安装固定版本 PyYAML。PDF、HTML、Office 或其它 converter 依赖均由可选外部 adapter 自己管理，installer 不准备它们。普通调用不会向任意 shared interpreter 安装依赖。

精简安装包只包含运行所需文件，不包含本文件、仓库测试、内部审查材料或维护者工具。源码开发与提交门以仓库根 `AGENTS.md` 和 `CONTRIBUTING.md` 为准。
