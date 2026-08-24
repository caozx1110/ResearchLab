# 安装与维护 Research Vault Skills

这份文档面向安装者、维护者和 CI。普通用户完成一次安装后，应回到 Agent 对话并用自然语言工作，不需要运行内部 skill 脚本。

## 安装边界

安装目标是 workspace 根目录。Project scope 会管理：

- `.agents/skills/` 下五个 shipping skill 与 `metadata.yaml`；
- `.agents/lib/research/` runtime library；
- `.agents/WORKSPACE_RULES.md`、requirements、version 和 license；
- root `AGENTS.md` 中一个稳定、可验证的 managed pointer block；
- 选择 Claude Code 时的 workspace skill integration。

安装器不管理 `Home.md`、Sources、Notes、Projects、Experiments、Reviews、Reports、`.research/`、`.source/` 或 `.obsidian/`。Update、reinstall 和 uninstall 都保留这些用户数据。

安装器不提供 executable research CLI，不创建 terminal shortcut，不修改 shell 配置，也不迁移 legacy workspace。

## 新用户快速安装

从可信的 Git checkout 运行：

```bash
bash install.sh
```

向导会选择：

1. install、update、reinstall 或 uninstall；
2. Claude Code、Codex 或两者；
3. project 或 system scope；
4. project workspace 根目录；
5. 预览并确认受管范围。

推荐 project scope。安装完成后，在 Agent 对话中说：

```text
帮我在当前工作区初始化 Research Vault，并说明下一步。
```

初始化是 `research-vault` 的运行行为，不属于 installer。安装本身不会创建研究语义文件。

## 非交互安装

常用维护命令：

```bash
bash install.sh install --codex --project /path/to/workspace --yes
bash install.sh install --claude --project /path/to/workspace --yes
bash install.sh install --all --project /path/to/workspace --yes
bash install.sh update --project /path/to/workspace --yes
bash install.sh reinstall --project /path/to/workspace --yes
bash install.sh uninstall --project /path/to/workspace --yes
```

`--project` 的值必须是 workspace 根，不是某个研究子目录。目标 root、`.agents` 或 selected integration parent 是 symlink、special node 或类型冲突时，安装器 fail closed。

`--dry-run` 只展示折叠后的受管变化，不写 workspace、HOME 或 runtime：

```bash
bash install.sh install --dry-run --codex --project /path/to/workspace
```

## Agent exact plan

Agent 可以生成零写、byte-bound JSON plan：

```bash
bash install.sh install \
  --agent-plan-json /safe/path/install-plan.json \
  --codex \
  --project /path/to/workspace \
  --yes
```

Plan 绑定：

- action、scope、workspace、HOME 和 selected tools；
- source checkout/origin/branch/full commit；
- distributable tree digest 与每个 source byte digest；
- exact target、operation、precondition 和 source content digest；
- current manifest identity；
- bound ready interpreter，或唯一 conditional workspace runtime tree；
- apply argv、plan digest 与 plan-byte digest placeholder。

应用前必须重新计算 plan file 的 byte digest，并保持 source commit、tree、target preconditions、runtime identity 与 manifest 未变化。任何 drift 都在第一笔写入前停止并要求重新生成/审阅 plan。

Plan schema 4 不含旧 terminal shortcut option。

## 五 skill 发布验证

Post-install smoke 只读验证：

- `metadata.yaml` 恰好列出五个 owner；
- 五个 `SKILL.md` 全部存在；
- vault、capture、analysis 的 mechanical entrypoint 可以显示 help；
- runtime 可以加载必要依赖；
- installed runtime 恰好只有 package marker、`v2_bootstrap`、read-only `legacy_detector` 和 installer `updater`，不包含旧 schema、migration、CLI 或 canonical-record helper；
- smoke 不创建研究语义或 bytecode。

唯一核心 Python dependency 是 PyYAML。缺少它且离线无法准备时，安装器保留已复制文件并明确报告 runtime 未就绪。安装者应使用可信 mirror 或 wheelhouse 按 `.agents/requirements.txt` 准备 workspace-local runtime，再重新运行 install/reinstall 检查。Converter dependency 不属于 installer。不要把 credential 写进 requirements 或 workspace Markdown。

## Runtime 选择

安装器按以下顺序选择兼容 runtime：

1. 明确指定且完整可用的 Python；
2. 当前完整可用的 Python；
3. 既有安全、完整的 workspace managed venv；
4. PATH 中 identity 稳定且完整可用的 Python；
5. 在 workspace-local `.venv/` 准备隔离环境。

普通运行不会向任意 shared interpreter 安装 package。Managed runtime 是用户本地运行状态，不进入 release bundle，update/reinstall/uninstall 默认保留。

## Source provenance

Project copy manifest 记录 source strategy、checkout、origin、branch 和 exact commit。Local checkout 安装继续绑定该 checkout；remote branch source 继续绑定该 origin/branch；detached source 绑定 exact commit，后续 update 前必须明确选择可验证 branch。

Git worktree source 通过 tracked release allowlist 枚举。ZIP/snapshot 不能区分 tracked 与 untracked 文件，默认拒绝；维护者只有在明确接受风险时才使用 snapshot source，并仍受确定性 release roots、excluded paths 和五 skill allowlist 约束。

## Update

Update 只适用于已有 project copy manifest：

```bash
bash install.sh update --project /path/to/workspace --yes
```

它原子更新 installer-owned files，删除 manifest-owned retired skill files，保留 drifted/user-owned paths 并给出统一 preservation warning。Source 不变且 bytes 已一致时是 no-op，manifest 保持稳定。

`--force` 只允许覆盖已漂移的 installer-owned regular file，不扩大 target 或删除范围，也不触碰研究数据。

## Reinstall

Reinstall 从当前 source 重新铺设完整 managed set：

```bash
bash install.sh reinstall --project /path/to/workspace --yes
```

它适合修复缺失、损坏或不完整的产品文件，重新运行五 skill smoke，并保留所有研究 Markdown、hidden proof、Obsidian 配置和 workspace-local runtime。

## Uninstall

```bash
bash install.sh uninstall --project /path/to/workspace --yes
```

Uninstall 只删除 manifest 中仍与安装记录 byte/type 相符的受管文件和 managed pointer block。已修改、retyped、symlinked 或不明 ownership 的目标会保留并告警。Research data、`.research/`、`.source/`、`.obsidian/` 和 `.venv/` 保留。

Retired CLI shortcuts 不属于 v2 installer 管理范围；uninstall 不猜测或删除任意 `bin/`、`~/.local/bin/` 用户文件。

## System scope

System scope 只适合维护者为当前用户配置共享 skill integration。它仍只暴露五个 discoverable skill，并优先使用 symlink 到可信 checkout。Codex 的系统级 skill discovery 能力可能因宿主版本而不同，因此普通使用推荐 project scope。

System uninstall 只移除目标仍匹配本安装 source 的 managed symlink；foreign link、普通文件和不明 target 保留。

## Legacy layout

发现 legacy canonical layout 时，install/update/reinstall 不进行数据迁移。不要通过手工移动目录、修改 manifest 或关闭 preflight 绕过。

当前 v2 release 不提供兼容或 migration contract。需要导入旧资料时，应先建立独立设计、原子 Issue、显式 selection boundary、exact backup、dry-run plan、current-message authorization、rollback 和 clean-vault acceptance。

## 验收建议

对临时空 workspace 执行：

1. project install；
2. 检查 manifest 只含五 skill release surface；
3. 用 installed `research-vault` 初始化；
4. 确认 `Home.md`、可见目录和 `.research/` 分类；
5. 重复 init 不覆盖 Preferences 或其他 user Markdown；
6. rebuild index 不读取 `AGENTS.md` 为研究页面，不改 semantic pages；
7. update/reinstall/uninstall 生命周期测试；
8. 确认无真实用户 workspace、legacy data 或 `.obsidian/` 修改。

开发仓库的完整门见根 [AGENTS.md](../AGENTS.md) 和 [CONTRIBUTING.md](../CONTRIBUTING.md)。
