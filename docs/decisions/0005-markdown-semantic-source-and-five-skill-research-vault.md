# ADR 0005: Markdown semantic source and five-skill research vault

- Status: Accepted（仅在本 ADR 经人类 review 合入目标分支后生效；合并前仍为 proposal）
- Date: 2026-08-24
- Atomic Issue: [#47](https://github.com/caozx1110/ResearchLab/issues/47)
- Parent Epic: [#46](https://github.com/caozx1110/ResearchLab/issues/46)
- Decision owners: human maintainer + Wave 0 delivery owner
- Supersedes: [ADR 0004](0004-workspace-root-canonical-data-and-logical-artifact-namespace.md) 中 `record.yaml`/逻辑 `kb/...` canonical data model、旧 canonical top-level inventory、旧 Obsidian managed projection 和兼容迁移目标；ADR 0004 的 root-role、containment、原子写、journal、lock、CAS 与 fail-closed 安全原则在 hard cutover 前后继续适用
- Superseded by: N/A

## Context

现有 v1 系统经过多轮演进后同时维护：

1. `record.yaml` 和相关 schema 所定义的 canonical knowledge unit；
2. `kb/user/`、source reader 和 `obsidian/managed/` 等人类阅读投影；
3. evidence、confirmation、index、journal、runtime cache 和 logical `kb/...` identity；
4. 15 个 shipping skill 对上述对象的分散 ownership。

这些层各自解决过真实问题，但组合后的产品合同要求人类在 YAML canonical 与 Markdown projection 之间理解哪一层才是事实；Agent 和脚本还必须长期维护 projection currentness、旧路径兼容、逻辑/物理路径转换和多个 owner 的一致性。Markdown 虽然可读，却不是可直接拥有和编辑的唯一语义真相。

维护者已经确认一个不兼容的新目标：Obsidian 直接打开安装后工作区根目录，普通 Markdown 承载全部人类可理解语义；原始材料、证据绑定、确认回执和运行恢复分别进入隐藏来源/运行区域。旧 `kb/`、`record.yaml` canonical、`obsidian/managed/` 和旧兼容路径不需要保留。

本决定的完整目标合同见 [Research Vault v2 蓝图](../blueprints/research-vault-v2/BLUEPRINT.md)。本 ADR 只记录承重选择、替代方案和 rollout 边界。

## Decision

### 1. 可见 Markdown 是唯一人类语义真相

标题、来源说明、摘要、claim、逐字 evidence、判断、项目状态、实验结果、决定、review 和报告必须存在于普通 Markdown。JSON、YAML、SQLite、cache 或运行日志不得拥有只在机器层存在的研究语义。

Markdown 可以使用少量 YAML frontmatter 作为 ID、kind 和 status 路由属性，但不得把 v1 `record.yaml` 搬入 frontmatter 形成事实上的同一 canonical record。

### 2. 来源保真和运行证明使用隐藏区域

- `Sources/<source-id>/.source/` 保存 immutable raw revisions、assets、转换快照、source map 和 manifest。
- 根 `.research/` 保存 evidence binding、confirmation receipt、index、operation journal、lock、cache、log、recovery 和 experiment raw artifacts。
- 隐藏文件只能证明、索引、恢复或加速可见语义，不能生成或覆盖 claim、决定和项目状态。
- 隐藏 binding 与 Markdown 不一致时，binding/receipt 变为 stale 或 invalid；系统不得选择隐藏副本反向覆盖用户 Markdown。

### 3. Workspace root 是 Obsidian vault

安装后工作区根直接包含 `Home.md`、`Sources/`、`Notes/`、`Projects/`、`Decisions/`、`Experiments/`、`Reviews/`、`Reports/`、`Views/` 和 `.research/`。`Home.md` 是主要入口。

`.obsidian/` 由用户拥有；核心合同使用普通 Markdown 和标准相对链接，不依赖 plugin、Bases 或 Obsidian CLI。`Views/` 和 `.base` 是可删除重建的导航层。

### 4. v2 不兼容 v1 canonical model

v2 不保留：

- 物理或逻辑 `kb/...` canonical namespace；
- `record.yaml` canonical unit；
- `kb/user/` 或 `obsidian/managed/` 双真相投影；
- 旧 `SCHEMAS.md` 对 v2 对象的约束；
- `kb <verb>` compatibility surface；
- 旧 owner identity、alias、dual-read 或 dual-write。

不兼容不授权删除用户资料。v2 runtime 发现 legacy workspace 时必须安全停止，不自动读取、迁移、移动或删除旧 `kb/`。未来如需迁移，必须另立 Blueprint/ADR/Atomic Issue 并提供显式、可验证、可恢复的一次性导入。

### 5. Shipping inventory 收敛为五个 skill

最终 inventory 为：

1. `research-vault`：Markdown/file/index/transaction/recovery 基础合同；
2. `research-capture`：发现、摄入、source revision、reader 和 adapter；
3. `research-analysis`：单源分析、多源 synthesis 和 claim/evidence；
4. `research-workbench`：project、idea、method、experiment、discussion、decision 和 report；
5. `research-review`：evidence audit、review packet、current-message authorization 和 receipt。

`research-workbench` 不合入 `research-vault`，因为长期研究活动不是存储基础设施。`research-review` 不合入产出判断的 skill，因为不可自签是独立治理边界。不再保留独立 god-orchestrator 或 executable CLI skill。

### 6. 外部工具只定义 adapter 边界

Defuddle、`obsidian-markdown`、`obsidian-cli`、`obsidian-bases` 和 AnyDoc 不迁移、不复制、不计入 shipping inventory。

- Defuddle 是 HTML→候选 Markdown converter；
- Obsidian tools 提供可选格式/UI/视图能力；
- AnyDoc 是 Office/ODF/RTF/EPUB/CSV 等格式的可选本地 converter；
- 所有 converter 都在 exact bytes 保存之后运行，输出不自动等于 evidence-ready。

### 7. 安全与恢复原则保留，owner 和 identity 重写

ADR 0004 中 typed root role、reserved-path containment、no-follow、atomic replace、operation journal、lock、revision/CAS、exact checkpoint 和禁止 `git add -A` 等原则继续有效，但它们服务于新 Markdown/source/operational ownership，不再服务于逻辑 `kb/...` 或 `record.yaml` canonical。

### 8. Target acceptance 与 runtime rollout 分离

本 ADR 合入后，v2 成为 accepted target；在后续 waves 完成 hard cutover 前，当前代码和测试仍是 v1 implementation fact。`docs/DESIGN.md` 必须同时清楚标记这两个时间边界，不能把尚未实现的 v2 能力写成当前行为。

## Alternatives considered

### 继续在 v1 上打补丁

拒绝。它会继续要求 YAML canonical、Markdown projection、logical path、compatibility 和多个 owner 同时演进，无法消除双真相和 ownership 复杂度。

### 保留 JSON/YAML canonical，只把投影做得更好

拒绝。用户仍不能只凭 Markdown 编辑和备份完整语义；projection currentness 仍是核心正确性问题。

### 使用四个 skill，把 workbench 合入 vault 或 analysis

拒绝。项目、实验和报告是纵向研究生命周期，不属于文件基础设施；合入 analysis 又会混淆形成判断与管理研究活动。五个 skill 是保持治理边界后的最小清晰集合。

### 把 review 合入 analysis

拒绝。让生成判断的同一 skill 同时拥有确认入口，会削弱“AI 不得自签”的独立边界和审计可读性。

### 使用数据库或完整 Web 应用作为主存储

拒绝。它重新引入应用依赖、导出投影和 lock-in，不满足文件系统、文本编辑器和 Obsidian 直接拥有内容的目标。

### 依赖 Obsidian plugin/Bases 作为 canonical 界面

拒绝。插件缺失、格式变化或 Obsidian 不运行时会使核心内容不可用。它们只适合作为可选派生体验。

### 为旧 workspace 提供长期 dual-read/dual-write

拒绝。它会把 v1/v2 两套 identity、schema、receipt 和恢复合同永久耦合。安全检测 legacy 并停止不属于兼容层，而是防止误写的数据保护。

## Consequences

### Positive

- 用户可直接阅读、编辑、链接、Git 管理和备份全部研究语义。
- Markdown 与 Obsidian 不再是 canonical 数据库的投影。
- 删除索引、cache、Views 或 Bases 不损失知识。
- 来源原件、证据证明和用户语义有清楚的不同 owner。
- 15 个 skill 的重叠路由和 ownership 收敛为五个稳定边界。
- 外部 converter 可以替换、缺失或失败，而不改变核心文件合同。

### Costs and risks

- Markdown parser、stable ID、link repair、claim/evidence block digest 和冲突处理必须足够严格。
- 人工直接编辑 `reader.md`、claim 或 review 会产生 currentness/receipt invalidation，需要清楚的 lint 和 UX。
- Raw、source map、receipt 和 recovery 仍需要结构化隐藏文件；团队必须持续防止它们扩张为第二语义层。
- v2 与 v1 不兼容，旧用户若需要迁移必须经过另行设计和审查。
- Accepted target 与尚未完成的 current implementation 会暂时并存，所有文档和 Issue 必须显式标记阶段。

## Migration and rollback

Wave 0 只修改 tracked 文档，不迁移数据、不改变 installer/runtime、不创建 skill skeleton。回滚可 revert 对应文档 PR；v1 代码、schema、安装态和用户 workspace 不受影响。

后续 rollout 按蓝图分 waves：vault foundation、capture、analysis/review、workbench/hard cutover。每个 wave 使用独立 Atomic Issue 和 consolidated PR。Hard cutover 之前不得让部分 v2 owner 静默写入 v1 canonical tree；需要并存测试时只使用隔离 fixture 和独立 namespace。

Hard cutover 仍不迁移或删除真实旧 workspace。若实现出现回归，使用普通 revert/fix-forward PR 恢复上一候选；不得重写 default history 或批量重签 evidence/receipt。

## Validation

Wave 0：

- 蓝图覆盖目录、页面、六类 workflow 契约、外部工具、15→5 mapping、waves 和 DoD；
- ADR 与 `docs/DESIGN.md` 清楚区分 v2 accepted target 和 v1 current implementation；
- Markdown relative links、`git diff --check` 和 focused inventory 检查通过；
- diff 只包含 Issue #47 声明的文档路径。

后续 waves：

- fresh-vault fixture 证明 Obsidian/普通 Markdown 从 `Home.md` 可读；
- 删除 index/cache/Views/Bases 后可重建且语义不丢失；
- source revision、locator、quote、claim digest、receipt stale 可端到端复现；
- converter 缺失、失败、无 OCR 或无 source map 时诚实降级；
- mutation/recovery 覆盖 crash、CAS conflict、symlink/special node 和 exact checkpoint；
- 五个 skill 通过 validator、隔离行为测试和无旧路径依赖检查；
- 真实旧 `kb/` 和用户 vault 零修改。
