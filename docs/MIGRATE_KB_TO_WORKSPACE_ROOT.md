# 将旧版知识库迁移到 workspace root

这份指南适用于旧版本创建的 dedicated research workspace：研究数据位于一个物理 `kb/` 目录，而安装文件、根规则和 Agent 接入位于它的外层。迁移完成后，canonical 数据直接位于 workspace 根；记录中已有的 `kb/...` 引用保持逐字不变。

迁移不是 install、update、reinstall、`kb init` 或后台任务的一部分。普通操作发现旧布局时只会停止写入并指向本指南。请让 Agent 执行检查与迁移，不要手工剪切目录，也不要把一个现有项目仓库强行改造成知识库仓库。

## 何时适用

只有只读 detector 明确给出 `eligible-legacy` 时才适用。一个可迁移 workspace 必须同时满足：

- 外层是 dedicated workspace，不是另一个 Git 项目；
- 旧 `kb/` 拥有自己的普通 `.git/`，HEAD 位于本地分支，仓库 clean、对象健康且没有 linked worktree；
- canonical top-level 只来自已审查 inventory，没有未知文件、目标重名或 partial root layout；
- 没有未完成 journal；
- workspace、旧数据树、Git metadata、规则与恢复目标都没有 symlink 或 special node；
- workspace 与其同级恢复材料位于同一文件系统；
- 根集成文件和旧 canonical bytes 在计划、锁定与提交边界保持不变。

以下状态不能迁移，也不能用 force 绕过：`partial-ambiguous`、`outer-git`、`collision`、`dirty`、`incomplete-journal`、`symlink`、`special-node`。`root` 表示已经是目标布局；`no-layout` 表示没有旧知识库，只能按全新 workspace 处理。

特别注意：如果 workspace 根本身是一个代码项目或其它现有 Git repository，本流程不适用。请为知识库选择独立 workspace；系统不会合并两个 Git 历史，也不会推断同名文件应保留哪一份。

## 迁移前

1. 停止其它会写这个 workspace 的 Agent、编辑器任务和自动化。
2. 保存一份由用户控制的离线备份，并确认它不在待移动目录中。迁移自带的私有恢复材料用于精确回滚，不能替代独立备份。
3. 让 Agent 运行只读检测。检测不得创建 marker、lock、plan 文件、Git commit 或目录。
4. 若状态可迁移，让 Agent 生成冻结计划并私下核对 workspace identity、canonical tree digest、Git HEAD/ref/tree/index、所有 move target、根规则与安装 manifest receipt。
5. 阅读 Agent 给出的自然语言范围、拒绝条件和回滚说明。只有在当前消息明确授权后才能 apply；旧消息、Agent 自行生成的同意或含糊的“继续”不能复用为迁移授权。

计划只对生成时那一份精确状态有效。任何 canonical 文件、Git ref/index、journal、根规则、安装 manifest、文件类型或 identity 变化都会令计划 stale；此时应重新检查，而不是修改计划摘要或跳过验证。

## 迁移会做什么

Agent 使用 owner-only、receipt-bound 流程按固定顺序完成：

1. 在 workspace 同级创建权限受限且唯一的私有恢复材料，保存计划、当前授权摘要和迁移前根文件快照。
2. 在独占 workspace lock 内再次完成全量只读 preflight。
3. 先把旧知识库的 Git metadata 原子移动到 workspace root，再按精确 allowlist 移动 canonical 与 operational top-level；每个 source identity 和 destination absence 都会重新验证。
4. 保留根 `.gitignore` 的所有用户行，合并旧知识库规则，并补齐 reviewed、anchored 的 workspace-root ignore contract。
5. 写入 byte-canonical workspace layout marker。根 `AGENTS.md`、`.agents/WORKSPACE_RULES.md` 和安装 manifest 的 bytes 不由业务迁移修改。
6. 比较迁移前后的 canonical tree digest、Git refs/history、逻辑引用和集成文件 receipt，然后用 literal pathspec 创建一个普通 migration commit。原 HEAD 必须是该 commit 的直接父提交；不会 rebase、squash 或改写历史。
7. 将最终 migration HEAD 和完成状态写回私有恢复 receipt。恢复材料继续保留，不会自动删除、上传或进入知识库 Git。

迁移不会批量替换 `kb/...`。这些值是稳定的 logical artifact identity，因此 evidence、confirmation receipt、preference、survey、report binding 和历史记录不会因为物理目录少一层而重新签名或失效。

## 完成后验证

让 Agent 至少确认：

- 物理 `kb/` wrapper 已消失，canonical layout marker 精确有效；
- workspace root 的 Git HEAD 是 migration commit，父提交是原 HEAD，原 branches/tags/object history 仍可达；
- canonical artifact bytes 与迁移前 digest 相同，持久化引用仍为原 `kb/...` bytes；
- 根用户规则、最小 workspace rules、安装 manifest 和用户 `.gitignore` 行保持有效；
- Git clean，`.agents/`、`.runtime/`、`.journal/` 和其它 reserved/private state 没有进入业务 checkpoint；
- `kb help`、`kb doctor` 仍是只读救援面，随后 root-layout 的正常生命周期与验收通过。

完成验证后才恢复日常使用。update 或 reinstall 仍是独立的安装生命周期；它们可以在已激活的 root layout 上运行，但不会替迁移作决定。

## 中途失败与恢复材料

apply 的阶段包括 recovery prepared、Git moved、entries moved、ignore merged、marker written 和 commit created。任一阶段失败都会尝试在同一 lock 内恢复原 HEAD、原 `kb/` wrapper、原 canonical bytes、原根规则与 `.gitignore`。

若精确恢复成功，receipt 标记为 `rolled-back-after-failure`，旧 workspace 继续保持 eligible legacy。若外部变化、重复目标或其它不确定性令恢复无法证明完整，流程标记 `rollback-incomplete`，保留唯一恢复材料并停止。此时：

- 不要删除、重命名、复制回或手工编辑恢复材料；
- 不要再次运行 init、update、reinstall 或新的迁移；
- 把 Agent 报告的自然语言阶段、旧 HEAD、当前布局状态和 receipt currentness 作为支持信息；
- 由维护者在隔离副本中检查，确认唯一安全恢复动作后再取得新的当前消息授权。

私有 receipt、digest、绝对路径、内部脚本参数、故障 hook 和原始诊断不得复制到普通用户输出或公开 Issue。公开协作记录只写脱敏状态、候选 SHA、测试结果和是否需要人工恢复。

## 显式回滚已完成的迁移

成功迁移后的回滚也是新的破坏性决定，需要当前用户消息中的独立授权以及精确、当前的 recovery receipt digest。它不要求逐字重复迁移时的授权句子。

回滚先确认 workspace 仍位于冻结的 migration HEAD、Git/canonical/integration state clean 且没有漂移；随后创建一个普通 reverse commit，再把 canonical entries 与 Git metadata 反向移入旧 `kb/` wrapper，并恢复迁移前根 `.gitignore`。原 HEAD、migration commit 和 reverse commit 都保留在同一历史链中，不 force-push、不改写历史。

如果回滚中断，状态变为 `rollback-incomplete`，唯一恢复材料必须保留并停止。只有完整验证原布局、canonical digest、历史祖先关系和根用户 bytes 后，才能把回滚视为完成。

## 不会发生的事

- 不存在公共 `kb migrate` 动词；
- install、update、reinstall、普通 runtime 和后台任务不会自动迁移；
- 不会把任意 outer Git 项目并入知识库 Git；
- 不会猜测 collision、追随链接、搬运 unknown top-level 或删除恢复材料；
- 不会改写 logical `kb/...`、重签 confirmation receipt、发布 release、创建 tag 或推送用户数据。
