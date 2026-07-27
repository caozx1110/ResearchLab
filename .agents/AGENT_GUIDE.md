# AGENT_GUIDE — runtime Agent 机制速查

本文件只给 runtime Agent 说明“怎么调”。治理以 `.agents/AGENTS.md`、相关 `SKILL.md` 和 `SCHEMAS.md` 为准。所有命令/flags/protocol 都是私有操作；用户只看中文自然语言与 16 个 `kb <动词>`。

## 1. Dispatcher 与 protocol

- 入口：`.agents/skills/kb-cli/scripts/kb`。`--root <workspace>` 可选。
- `--agent-protocol <name>.json` 必须放在动词前，例如 `kb --agent-protocol r1.json review`。相对名只写入 `kb/.runtime/`。
- `kb-agent-protocol/v1` 的 `child_results` 保存 owner 原始结果，`next_actions` 保存精确后续参数，`details` 保存诊断。stdout 只是脱敏用户文案；机制信息读 protocol，绝不转述 raw 内容。
- `init`/`review` 不读 TTY。缺 setup 时先呈现“现在设置/先跳过”；按 protocol 的 `apply.field_inputs` headless 落盘，不猜 dotted key。缺真人署名不妨碍列 review，只在确认前补。

## 2. Review 精确闭环

展示：

```text
kb --agent-protocol r1.json review
```

从 `present_review_items.review_items[].subject` 取展示项。用户当前消息拍板后应用：

```text
kb --agent-protocol r2.json review --apply-snapshot r1.json \
  --confirm-ref <kind>:<id> --user-authorization "<用户原话>" \
  --decision-evidence "<依据>"
```

- `--apply-snapshot` 是展示 protocol 文件名，不是 token。ref 只能取本轮已展示 `kind:id`；reject/defer 分别用 `--reject-ref` / `--defer-ref`，可混批。
- confirm 要求真人署名、当前消息授权和 evidence；reject 可带 reason。整批原子。
- `expired` / `already_applied` / `stale_content` / `tampered_or_unknown` / `invalid_decision`：解释对应原因并重跑 review；内容变了必须重新展示。`missing_confirmation_context`：补署名/授权/evidence。snapshot 未成功应用前保持可重试。

Obsidian 批次：

```text
kb --agent-protocol o1.json review --obsidian-export
kb --agent-protocol o2.json review --preview-obsidian-batch <batch_ref>
kb --agent-protocol o3.json review --apply-obsidian-batch <batch_ref> \
  --expected-preview-digest <digest> --user-authorization "<用户原话>" \
  --decision-evidence "<依据>"
```

`batch_ref` 来自 sheet 的 `kb-review-batch:<64 hex>` marker；digest 来自 preview protocol 的 apply 合同。先复述完整 diff，再取授权。`authorization_stale` / `sheet_tampered` 时重新 preview/export。

## 3. Analyzer fill / verify

统一两阶段：owner `prepare` 写空白 scaffold → Agent 读冻结材料、填理解与 evidence → owner `verify`。脚本不填判断，verify 后仍 pending。

- 默认 fill：paper `note-fill.yaml`；repo `capability-fill.yaml`；dataset `dataset-fill.yaml`；blog `blog-fill.yaml`。`--input` 只接 unit 根下 basename。
- evidence ref：`{source_unit_id, artifact, locator, quote}`，可选 summary。quote 经 whitespace 归一化后仍须大小写/标点敏感地逐字存在；artifact/identity/current bytes 都会复验。
- locator：PDF `page=N`/section/para；HTML/Markdown `section:<anchor>`；repo `line=N`。repo 真正根目录读 `capability-fill.yaml` 的 `agent_orientation.repo_root`，basename 不固定；artifact 相对该根。
- concept：至少 3 个 current confirmed unit；prepare 冻结语料，Agent 填 definition/associations + evidence，verify 后走普通 review。
- idea analyze/review/discuss/generate 只能引用本次 prepare 的 evidence-corpus；要扩语料，先入库/链接 unit，再以同一 analyze/review prepare 加 `--refresh-corpus`，它保留 Agent 可填字段并刷新 corpus/context，随后改正引用再 verify。

人工笔记只在用户明确点名一份时调用：

```text
kb --agent-protocol n.json ingest \
  --human-note-area <inbox|annotations> \
  --human-note-filename <basename.md>
```

只传 area + basename，不传路径或遍历目录。成功后从 frozen source/parse-cache 填 blog 四要素并 verify；`source_origin=human-note` 不等于确认。

## 4. 动词与 owner

| 动词 | owner / 语义 |
|---|---|
| help / doctor / update / obsidian | kb-cli 内置；doctor/update/status 类检查保持只读 |
| init | knowledge-base-manager + research-config-manager |
| status / next | knowledge-base-manager + research-orchestrator；公开 next ≤3 步 |
| find | knowledge-base-manager；公开 ≤5 段，私有 formal/navigation 分 lane |
| add / ingest | source-intake；ingest 自动续接相应 analyst prepare |
| review / reject | kb-cli 跨 owner coordinator / knowledge-base-manager；见 §2 |
| recall | skill-evolution-advisor |
| resume / undo / restore | knowledge-base-manager recovery |

无新公开动词。深分析统一发现入口是 `unit-analyst`，内部仍调用 paper/repo/dataset/blog 历史 implementation；survey/concept 用 literature-synthesizer；idea/method/experiment/report/monitor/discussion 各归同名 owner。远程 repo 先在安全临时目录做只读 local snapshot；`needs_local_repo_snapshot` 后自动本地化并重试。`failed_retryable` 可安全重试；review 若还在 awaiting fill/ready-to-verify，则先 fill+verify。

## 5. 恢复与偏好

- `kb resume` 只恢复 journal 中断操作；`kb undo` 撤最近可逆操作并公开点名安全对象；`kb restore` 无编号只读列最近编号，有编号恢复到该操作前。随后用 `kb status` 核对。
- 用户明确纠正或连续同形修改时，私下记录短逐字 observation + exact skill/operation 为 pending；任务尾最多问 2 条“要记住吗”。确认/忽略只走 §2 snapshot，禁止直调 learning review/promote。

## 6. 交互章程（10 条）

1. **启动澄清**：只问 2–4 个高价值问题，给推荐默认；“默认即可”有效。
2. **先复述再讨论**：前三句话复述理解并对齐关键术语。
3. **观察式偏好**：任务尾攒批问，≤2；不开局问卷。
4. **大活先报量级**：先报规模/耗时，试做 1–2 个再全量。
5. **伴读三段式**：结构地图 → 带 locator 答疑 → 落库前询问。
6. **口头分型**：明确区分“库内证据 / 我的推断 / 需验证”。
7. **路线三栏**：维护“共识 / 分歧 / 待验证”，阶段末复述。
8. **开场接续**：先报上次进度与待拍板项，再问今天做什么。
9. **四行收尾**：做了什么 / 落盘什么 / 待确认什么 / 建议下一步。
10. **入库静默礼仪**：链接默认按 link_autodrive；批量不逐项打断；中断说明可恢复。
