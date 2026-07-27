# Skill Issues Observed on 2026-04-27

> 本记录来自 `physics-aware-fb-z-space` program 创建与 idea review 过程中暴露的问题。目标是为后续 skill / script 改进提供可复用问题清单。

## 1. `idea-workbench` ID canonicalization 提示不足

### 现象

创建 idea 时生成了长 ID：

```text
idea-physics-aware-fb-compatible-z-space-large-human-motion-data-f7e91d86
```

后续 `analyze` / `review` 过程中，实际写入路径变成了短 ID：

```text
i-physics-aware-fb-compatible-f7e91d86
```

脚本输出只提示写入了新路径，没有明确说明发生了 ID 规范化或迁移。

### 影响

- 容易误以为生成了两个 idea unit。
- 后续 program attach / link 时容易引用旧 ID。
- 人工排查时需要额外查找 `legacy_ids`。

### 建议

- 当脚本发生 ID canonicalization 时，显式输出：

```text
normalized idea id: <old-id> -> <new-id>
```

- 在 `capture` 阶段直接生成 canonical ID，避免后续命令才迁移。
- 如果保留 legacy ID，应在命令输出中提示 canonical record 路径。

## 2. `research-orchestrator` 并行写入会丢更新

### 现象

并行执行多个写操作时出现覆盖：

- `attach-unit` 并行执行后，`r-bfm-zero-cc8aa3c3` 一开始没有保留在 `active_unit_ids`。
- 多个 `request-evidence` 并行执行后，3 个 evidence request 一开始只留下了 1 个。
- `set-stage` 与其他写操作并行后，`state.yaml` 一度回到 `stage: init`。

### 影响

- program state 和 workflow 文件可能丢失真实操作。
- reporting-events / evidence-requests / active-unit 计数可能不可信。
- 需要人工二次检查和补写，容易造成隐性数据错漏。

### 建议

- 对会写同一文件的命令加文件锁。
- 对 list append 类操作使用 append-only / read-latest-then-merge 写法。
- 写回前检查文件 revision / mtime，如果期间被修改则重新读取合并。
- 对 `attach-unit`、`add-open-question`、`request-evidence`、`add-reporting-event` 这类命令禁止并行写入同一 program，或在脚本层内部串行化。

## 3. `state.yaml` 容易出现重复 YAML key

### 现象

人工 patch 时曾出现两个 `next_actions` key：

```yaml
next_actions: []
next_actions:
- ...
```

YAML parser 仍能读取，但语义依赖 parser 对重复 key 的处理，存在隐患。

### 影响

- 后续工具可能读到非预期值。
- 不同 YAML parser 对重复 key 的行为可能不同。
- 人眼检查时容易漏掉。

### 建议

- 增加 workspace lint：检测 `record.yaml`、`state.yaml`、workflow yaml 的重复 key。
- `write_yaml_if_changed` 写入前使用安全 dump，尽量避免手工 patch 造成重复 key。
- 增加 program status / kb lint 的 schema 检查。

## 4. `attach-unit` 不会同步反写 unit record 的 `program_ids`

### 现象

`orchestrate.py attach-unit` 只更新 program 的 `active_unit_ids`，不会同步把 program id 写入对应 unit 的 `program_ids`。

本次需要手工 patch：

- idea record
- BFM-Zero repo record
- BFM-Zero paper record

### 影响

- program 能看到 unit，但 unit 侧不一定能反查 program。
- 导航、索引、query 时可能出现单向链接。

### 建议

- `attach-unit` 应同时定位 unit record 并追加 `program_ids`。
- 如果 unit record 不存在，应给出 warning。
- 如果反写失败，应在命令输出中提示需要人工处理。

## 5. 时间戳策略不统一

### 现象

脚本生成的 `updated_at` / reporting event 多为 UTC，人工记录时常使用 Asia/Shanghai 时间。

### 影响

- 同一 record history 中时间顺序不直观。
- 人工阅读和脚本排序可能产生轻微混乱。

### 建议

- 统一规定 v2 records 全部使用 UTC，human-facing markdown 可显示本地时间。
- 或在 schema 中显式记录 timezone policy。
- 脚本输出中标注时间戳时区。

## 6. 操作建议

短期规避：

- 不并行执行会写同一 program / unit 的 skill command。
- 每次 program 创建后运行 `orchestrate.py status`。
- 每次批量写入后用 Python YAML parser 验证核心 YAML。

中期修复：

- 给 `research-orchestrator` 增加文件锁和 merge-safe append。
- 给 `idea-workbench` 增加 canonical ID 输出。
- 给 `knowledge-base-manager` 增加 duplicate-key lint 和 program/unit 双向链接检查。

