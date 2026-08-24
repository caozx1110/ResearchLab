# ADR 0004: Workspace root canonical data and logical artifact namespace

- Status: Accepted（由 [PR #31](https://github.com/caozx1110/ResearchLab/pull/31) 经人类 review 合入 default branch；后续实现的交付状态以对应 Issue/PR/Actions 为准）
- Date: 2026-08-04
- Atomic Issue: [#27](https://github.com/caozx1110/ResearchLab/issues/27)
- Parent Epic: [#21](https://github.com/caozx1110/ResearchLab/issues/21)
- Decision owners: human maintainer + Wave 1 delivery owner
- Supersedes: [ADR 0002](0002-separate-product-source-and-local-agent-tools.md) 中固定 installed `kb/` 物理 data layout、复制完整 runtime rules 到根 `AGENTS.md`/`.agents/AGENTS.md` 的部分；其 source/product/local-tool 分离决定继续有效
- Superseded by: [ADR 0005](0005-markdown-semantic-source-and-five-skill-research-vault.md)（仅 supersede `record.yaml`/逻辑 `kb/...` canonical data model、旧 canonical top-level inventory、旧 Obsidian managed projection 和兼容迁移目标；本 ADR 的 root-role、containment、原子写、journal、lock、CAS 与 fail-closed 安全原则继续适用，当前 v1 实现在 hard cutover 前也仍服从本 ADR）

## Context

本 ADR 制定时的安装态把三种不同职责隐含在一个 `project_root` 与一个物理 `kb/` 前缀周围：

1. workspace/integration root：用户选择的工作区，以及 `.agents/`、`.venv/`、根 `AGENTS.md`、Claude/Codex 接入和安装 manifest 的归属边界；
2. canonical data root：unit、program、synthesis、config、memory、source、journal 与 KB Git 的物理根；
3. product bundle root：shipping skills 与 shared runtime 的可信来源。

ADR 0002 正确地把 tracked product source、维护者本地工具和安装 payload 分开，但为避免当时的迁移风险，同时固定了 installed `<workspace>/kb/` data layout，并让完整 `runtime/AGENTS.md` 同时进入 `.agents/AGENTS.md` 与根 managed block。Epic #21 选择进一步解耦：dedicated KB workspace 自身将成为 canonical data root，`.agents/**` 仍是 ignored、可重装的产品面，根 `AGENTS.md` 由用户拥有且安装器只维护一个稳定加载指针。

直接把 `research_root()` 从 `<workspace>/kb` 改为 `<workspace>` 不安全。现有 journal、Git、strict reader 与 owner 以“位于 data root 下”近似“属于 canonical KB”；扩大根后，`.agents/**`、`.git/**`、`.venv/**`、`.claude/**`、根 `AGENTS.md`、`CLAUDE.md` 与 `bin/**` 会被错误纳入 mutation、recovery 或 checkpoint 候选。

同时，records、history、evidence、survey/report bindings 与 confirmation receipts 已经持久化 `kb/...`。这些 bytes 是 artifact identity 或 digest 输入；物理迁移若批量去掉 `kb/`，会无必要地使 evidence/receipt stale，并把物理布局泄漏进长期 schema。

## Decision

### 1. 三种 root 是显式角色

- **Workspace/integration root** 是安装、用户入口与 integration files 的边界。
- **Canonical data root** 是 canonical artifacts 与 KB-local operational state 的物理根。legacy layout 为 `<workspace>/kb`；目标 layout 为 `<workspace>`。
- **Product bundle root** 是已验证 shipping skills/runtime 的来源，不从 target workspace 的同名路径猜测。

调用方必须通过 typed root roles 声明 layout；不得再让一个未标注的 `root` 参数同时承担三种角色。本 ADR 的交付顺序要求 Wave 1 只交付纯合同与测试，不改变当时生产 owner 的 legacy root 选择；Wave 2 在各 owner 明确接入后才激活 workspace-root data layout。

### 2. `kb/...` 是稳定逻辑 namespace

`kb/...` 从现在起定义为 persisted logical artifact reference，而不是“workspace 下必须有一个名为 `kb` 的目录”。

- legacy layout：`kb/units/papers/p/record.yaml` 映射到 `<workspace>/kb/units/papers/p/record.yaml`；
- workspace-root layout：同一 reference 映射到 `<workspace>/units/papers/p/record.yaml`；
- reverse mapping 必须恢复完全相同的 UTF-8 bytes；record、history、evidence、receipt、survey/report binding 不因物理迁移改写；
- logical ref 只接受 canonical POSIX spelling：精确 `kb/` 前缀、非空 segment、无 absolute/traversal/backslash/double separator，且 top-level 必须在已审查 inventory 中。

物理路径与逻辑 reference 的转换由单一窄 owner 完成。业务代码不得用字符串 replace、`lstrip("kb/")` 或散落的 `root / "kb"` 复制该协议。

### 3. Canonical namespace 与 reserved workspace paths fail closed

初始 canonical artifact top-level inventory 为：

```text
.gitignore  config/  eval/  index.md  index.yaml  memory/  monitoring/
obsidian/   output/  programs/  raw/  synthesis/ units/    user/
```

`.journal/` 与 `.runtime/` 有稳定 logical identity，但分类为 operational state；普通 business owner 不得因它们位于 data root 下而取得写权限。journal/runtime owner 必须显式 opt in。

以下 workspace top-level 永远是 reserved integration targets，不能成为 canonical business mutation、journal snapshot、strict-reader artifact 或 Git pathspec：

```text
.agents/  .git/  .venv/  .claude/  AGENTS.md  CLAUDE.md  bin/
```

比较 reserved names 时按 case-folded identity fail closed，以覆盖常见大小写不敏感文件系统。未知 top-level、外部绝对路径、traversal、symlink ancestor/leaf 与 FIFO/socket/device 等 special node 一律拒绝；不得因为“目前不存在”就把未知 workspace sibling 归为 KB 数据。

根 `AGENTS.md` 可以由用户选择纳入 workspace Git 历史，但它仍不是业务 artifact，安装器也不得借 KB mutation API 修改 marker 外 bytes。Git integration 必须使用显式 root-level ownership policy，而不是把 `AGENTS.md` 伪装成 `kb/...`。

### 4. Lexical containment 与 filesystem identity 分层

Path contract 先做不跟随 symlink 的 lexical classification，再用 `lstat` 对当前 data root、existing ancestors 与 leaf 做只读 no-follow precondition。该结果不是跨时间授权：mutation、journal、Git 与 strict-reader owner 必须在自己的 descriptor/lock/commit boundary 重新验证 identity，并继续使用现有 atomic write、journal、CAS 与 exact-target 规则。

合同 helper 不创建目录、不移动数据、不初始化 Git、不 checkpoint，也不导入 `research.core` facade。提示词不能替代 reserved-path 或 no-follow 机械门。

### 5. Downstream wave obligations

Wave 2 在激活 root layout 前必须：

- 让 common/paths、所有 owner、journal、Git、strict readers、index/retrieval 与 recovery 使用显式 root roles 和统一 resolver；
- 对 business、operational、derived 与 root-integration targets 使用各自明确 allowlist；
- KB Git 初次提交只枚举审查后的 canonical/root-owned pathspec，绝不以 workspace root 执行无范围 `git add -A`；
- 保留 logical `kb/...` bytes，并以 legacy/root 双 layout fixtures 验证 receipt、evidence、history 与 report/survey bindings；
- 对 outer Git repo、dirty/incomplete journal、collision、symlink 和 special node fail closed。

Wave 3 必须让根 `AGENTS.md` 保持 user-owned，managed block 只含稳定 `.agents/WORKSPACE_RULES.md` 指针；删除或证明 `.agents/AGENTS.md` 重复副本的必要性。skill progressive disclosure 与最小 always-on rules 不得通过复制全文绕过。

Issue #22 对应的实现落实该 Wave 3 obligation：根 managed block 只保留指针，`.agents/WORKSPACE_RULES.md` 是带机械身份门的最小规则层，旧 `.agents/AGENTS.md` / `.agents/AGENT_GUIDE.md` 仅按 manifest ownership 安全清理，多操作 owner 使用一跳 references。候选、合并与验收状态只在 GitHub Issue/PR/Actions 记录，不在本 ADR 复制易漂移的活动状态。

Wave 4 只通过显式迁移文档/流程处理 legacy workspace。普通 install/update 不静默移动 canonical data；新 runtime 发现未迁移 legacy layout 时给出安全迁移指引并停止 root-layout 写入。

Issue #29 对应的实现落实该 Wave 4 obligation：detector 保持只读并区分 root、eligible legacy 与全部拒绝状态；owner-only plan/apply/rollback 绑定 exact filesystem/Git/tree/receipt、当前消息授权、同盘私有恢复材料与独占 lock。迁移 commit 以旧 HEAD 为直接父提交，显式 rollback 使用新的授权与普通 reverse commit；两者都保留 logical `kb/...` bytes，拒绝 outer Git、history rewrite、自动迁移和不完整恢复。完整操作合同见[迁移指南](../MIGRATE_KB_TO_WORKSPACE_ROOT.md)，交付状态仍由 GitHub 记录。

## Alternatives considered

- **继续永久使用物理 `<workspace>/kb/`。** 拒绝：它让 dedicated knowledge workspace 多一层无语义容器，并继续把产品安装、Agent 入口与数据所有权耦合在 installer 假设中。
- **迁移时把 persisted `kb/...` 全部改成 root-relative。** 拒绝：会改写 canonical bytes、evidence/receipt digest 与历史 identity，却没有用户价值。
- **让 resolver 同时长期猜测两种 layout。** 拒绝：双物理真相会让 owner、recovery 与 Git scope 随目录存在性漂移。迁移期可以显式声明 layout，但 active workspace 只能有一个 data root。
- **把 workspace root 下除 denylist 外的一切都当 KB。** 拒绝：未知项目文件、未来工具目录和大小写别名会自动进入 mutation/checkpoint，无法 fail closed。
- **只用 `Path.resolve()` 做 containment。** 拒绝：它会跟随 attacker-controlled symlink，混淆 lexical ownership 与当前 filesystem identity，也不能替代 commit-boundary no-follow/CAS。
- **只在 Agent rules 中声明不可触碰路径。** 拒绝：confirmation、containment、recovery 与 checkpoint 是机械安全边界，不能依赖 prompt compliance。

## Consequences

- Physical layout 可以迁移，而 logical evidence/artifact identity 保持稳定。
- Workspace integration files 与 canonical business artifacts 有机器可检验的边界；未知 top-level 默认拒绝。
- Downstream owner 必须显式携带 root role 与 target class，短期增加接口迁移工作，但消除 `project_root` 多义性。
- Legacy arbitrary files directly under `kb/` 不会被静默认作 root-layout canonical top-level；Wave 4 必须在 preflight 中报告并由人处理 collision/placement。
- `AGENTS.md` 可进入用户 Git 历史，但业务 mutation 与 installer ownership 仍分离，需要 Git owner 的专门 allowlist。
- Wave 1 merge 本身没有激活新布局；包含 Wave 2–4 实现的 revision 会让新初始化的 dedicated workspace 使用 workspace-root 布局，而 legacy workspace 仍须经过显式迁移，不能由普通 runtime 或 installer 自动转换。

## Migration and rollback

本 ADR/Wave 1 自身不迁移数据，也不激活新 layout；它只新增纯 resolver/classifier/no-follow API、设计和 characterization tests。后续 runtime activation 与 legacy migration 分别遵守上面的 Wave 2 和 Wave 4 边界。

若 Wave 1 需要回滚，revert 对应 PR 即可；现有 workspace、KB Git、record/evidence/receipt bytes 与 installer payload 均不变化。后续已执行的 legacy migration 必须按 Wave 4 文档在 clean HEAD、无 incomplete journal、无 collision 条件下 exact 恢复原 Git metadata 与 canonical tree，并重装上一个兼容版本；不得改写 default history 或批量重签 receipt。

## Validation

- Direct tests 覆盖两种 layout 的 byte-identical round trip、absolute/traversal/separator/unknown/reserved 拒绝。
- Filesystem fixtures 覆盖 data-root、ancestor、leaf symlink，以及 FIFO/special node；helper 全程只读。
- Wave 1 characterization tests 锁定当时 `research_root()`、owner path、KB Git root、installer plan 与 public output 的 legacy behavior，供后续 wave 显式变更而非静默漂移。
- 每个 downstream candidate 需通过 focused security/path tests、full pytest、skill validator、rule-token check、compileall、diff check，以及 exact-head candidate/tested-merge Actions。
- 只使用隔离临时 workspace；不读取或修改真实用户知识库/工作区（包括 legacy `kb/` 与 workspace-root 布局）。
