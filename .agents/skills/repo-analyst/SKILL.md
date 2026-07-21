---
name: repo-analyst
description: 为 repo unit 备料（扫描结构、产出三要素待填结构）并校验 agent 填入的能力理解与 file:line 证据，再过实质门确认。脚本不理解仓库，理解由 runtime agent 填。
---

# Repo Analyst

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#unit-payload` · `#evidence-claims` · `#confirmation-gate` · `#runtime`

当任务是在分析某个 repository knowledge unit（而不只是入库）时，使用这个 skill。

## 第一性原理（SSOT 原则1 / §3.3）

**理解来自 agent，脚本只做搬运 + 验证。** 脚本负责：扫描仓库结构（纯机械）、产出「三要素待填结构」、逐字校验 agent 填入的每条判断带合法 file:line 证据、过实质门、落盘。脚本**绝不**产出「这个 repo 的核心能力是 X / 适合做 baseline / 偏 data 角色」这类判断——那是 runtime agent 的活。`map-capability` 是**两阶段**：脚本 `prepare` 出待填骨架 → agent 在会话里读关键文件填理解+挂 file:line 证据 → 脚本 `verify` 校验后落盘。

> 反模式（已删除）：旧版 `capability_map` / `infer_repo_roles` 用 README 摘录 + 目录关键词猜「候选角色 / 支持任务」，把 Python 的关键词命中当成能力判断落库。现在这类判断一律由 agent 给出并 grounding 到 file:line。README 摘录只作为 `agent_orientation` 的定位线索，**不落成判断字段**。

## 负责范围

1. 从 `source-intake` 创建且确认拥有本地真实源码树的 repo unit 出发；HTML/data-card 快照不冒充 repo root。
2. `scan-structure`：仅当 `scan_applicability=applicable` 时做纯机械扫描——列顶层目录/文件、入口候选、语言分布、配置文件、README 摘录。远程 URL 或非目录快照记为 unavailable，不改写既有分析内容、确认状态或证据。
3. `map-capability --phase prepare`：产出**三要素待填骨架** capability / reuse_points / entry_map，每要素留空、需 agent 填内容 + ≥1 条 `evidence_refs`（file:line）。附 `agent_orientation`（机械结构摘要）供 agent 导航。
4. `map-capability --phase verify`：逐要素校验（`validate_claims` 结构 + `verify_claim_evidence` 逐字据），全过才写 `repo-note.md` + `payload.capability`（过 `has_substantive_content`，可被确认）；任一要素空/无据/造据/引用文件不可达则拒绝并点名。
5. AI judgement 默认保持 `pending_user_confirmation`；确认走已有空心门（`confirm`）。

## 三要素填充契约（runtime agent 照此填）

每个 required element = 一条 judgement-class claim，**必须**带 ≥1 条 `evidence_refs`。**证据 artifact = 仓库内真实文件（相对 repo_root），locator = `line=N`，quote = 该文件里的逐字片段**（如 README 一句、某入口文件一行）：

```yaml
elements:
  - element: capability        # capability|reuse_points|entry_map 三个全填
    claim_type: evaluation     # entry_map 为 inference，其余 evaluation
    content: "agent 用自己的话写：这个 repo 解决什么问题、核心能力、适合/不适合做什么"
    evidence_refs:
      - source_unit_id: r-...
        artifact: README.md          # 相对 repo_root 的真实文件路径
        locator: "line=12"           # 仓库文件用 line=N（不是 page=N）
        quote: "短逐字片段"           # 脚本校验它逐字存在于该文件（归一化空白后子串）
        summary: "可选一句转述"
  - element: reuse_points       # 哪些模块/脚本/模式可复用、可借鉴、可改造
    claim_type: evaluation
    content: "..."
    evidence_refs: [ ... ]
  - element: entry_map          # 关键入口(训练/推理/eval 命令)+关键配置 key+核心模块位置
    claim_type: inference
    content: "..."
    evidence_refs: [ ... ]
```

落盘映射：capability→`payload.capability.core_capabilities`、reuse_points→`payload.reuse.directly_reusable`、entry_map→`payload.structure.entrypoints`；三要素同时渲染进 `repo-note.md`，每条判断带 `[file:line] "quote"` 引用。

### 证据可达性（repo 太大不宜整个塞进 unit）

脚本不复制整个仓库进 unit。`verify` 阶段从 record 的 source（`backup_paths` / 本地 `original_uri`）解析出 **repo_root**，`evidence_refs.artifact` 是相对该 root 的路径。校验时脚本加载 `repo_root/artifact` 并做逐字子串匹配；文件不可达时报明确 `not found/readable` 错误而非静默过。因此：**只需 record 能定位到本地 repo 快照/checkout 根目录即可**，证据文件按需按路径加载，无需把源码搬进 kb/。`line=N` 只作为人读定位（渲染进 note），硬判据是 quote 逐字存在于所引文件。

源码保持原格式，不批量转换成 Markdown。持久证据身份是 `repo unit id + repo-relative artifact path`；Obsidian 派生页可把它渲染为经过 containment 与存在性检查的本地文件链接，便于打开对应源码文件。该机器本地 URI 只是消费层便利信息，不写回 canonical evidence；当前不承诺由 Obsidian 精确跳到行号。

`scan-structure` 的机械入口候选写入 `payload.structure.entrypoint_candidates`。`payload.structure.entrypoints` 是 runtime agent 经证据验证后的 judgement 字段，机械刷新不得覆盖，更不得使已有 confirmation 失效。

## 符号级 = 按需

入库只做**文件级**能力边界（三要素够了）。若用户进一步要「loss 在哪 / 训练入口怎么走」这类符号级细读，agent 在会话里深入读相关文件，把结论 grounding 到具体 `file:line` 再补进 note——不在入库阶段全做。

## 常用命令

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/repo-analyst/scripts/repo.py scan-structure --repo-id r-example-dadda683
${RESEARCH_PYTHON:-python3} .agents/skills/repo-analyst/scripts/repo.py map-capability --repo-id r-example-dadda683 --phase prepare
# agent 填 kb/units/repos/r-example-dadda683/capability-fill.yaml 后：
${RESEARCH_PYTHON:-python3} .agents/skills/repo-analyst/scripts/repo.py map-capability --repo-id r-example-dadda683 --phase verify
${RESEARCH_PYTHON:-python3} .agents/skills/repo-analyst/scripts/repo.py confirm --repo-id r-example-dadda683 --confirmed-by research-lead --evidence kb/units/repos/r-example-dadda683/repo-note.md
${RESEARCH_PYTHON:-python3} .agents/skills/repo-analyst/scripts/repo.py reject --repo-id r-example-dadda683
```
