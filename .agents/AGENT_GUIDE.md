# AGENT_GUIDE — runtime Agent 机制速查与交互章程

面向 runtime Agent 的私有速查，会话开始时加载。脚本调用全部是内部操作：不向用户展示脚本路径、flags、协议内容；公开面只有自然语言 + 16 个 `kb <动词>`。治理契约以 `.agents/AGENTS.md` 与各 SKILL.md 为准，本文只讲"怎么调"。

## 1. kb 调度器

- 脚本：`.agents/skills/kb-cli/scripts/kb`（python3 运行；`--root <workspace>` 可选）。
- `--agent-protocol <名>.json` 是全局 flag，**必须放在动词之前**：`kb --agent-protocol r1.json review`。放在动词后会解析失败。
- 协议文件落 `kb/.runtime/`（相对名自动解析到该目录，越界拒绝）。schema `kb-agent-protocol/v1`：verb / status / exit_code / child_results（owner 原始 stdout/stderr）/ next_actions（精确下一步参数）/ details。stdout 只是给用户的脱敏文案，机制信息一律读协议。

## 2. review 确认应用（精确语法）

展示轮：`kb --agent-protocol r1.json review` → `next_actions[0]`=`present_review_items`，含 `review_items`（subject=kind+id）与冻结的 `apply` 合同。快照一次性；`strict` 固定 Top-3 + 24h，`personal` 默认 10 条且批量上限/有效期可配置。应用时只消费展示轮冻结的 profile/limit/expiry，不重读后来变化的配置。

应用轮（用户当前消息拍板后）：

```
kb --agent-protocol r2.json review \
  --apply-snapshot r1.json \
  --confirm-ref paper:p-xxxx-12345678 \
  --user-authorization "<用户原话逐字>" \
  --decision-evidence "<依据，如 note 路径或证据摘要>"
```

- `--apply-snapshot` 传**展示轮协议文件名**（相对 kb/.runtime/），不是 snapshot_token。
- ref 必须 `kind:id`（paper/repo/dataset/blog/idea/experiment/concept/user_preference 等）；只能引用展示轮列出的项。
- `--reject-ref` / `--defer-ref` 同格式，可与 confirm 混批；reject 可附 `--rejection-reason`。
- confirm 要求：真实人类署名已配置（AI 署名拒绝；缺署名先走 headless `init --name`）、当前消息授权、非空 `--decision-evidence`。
- 整批原子：任一项 stale 则零写入。

## 3. Obsidian 批次

- 导出：`kb --agent-protocol e.json review --obsidian-export` → 在 annotations 区生成勾选表，表内 HTML 注释 `<!-- kb-review-batch:<64位hex> -->` 即 batch hash。
- 预览：`kb --agent-protocol p.json review --preview-obsidian-batch <hash>` → 读 `next_actions[0].apply.expected_preview_digest`；向用户复述全部 确认/拒绝/暂缓 草稿并取当前消息授权。
- 应用：`kb --agent-protocol a.json review --apply-obsidian-batch <同 hash> --expected-preview-digest <上述 digest> --user-authorization "…" --decision-evidence "…"`。跨 owner 原子；预览后表被改动 → `authorization_stale`，重新预览。

## 4. analyst fill/verify 惯例

两阶段：`prepare` 出待填骨架 → Agent 读材料填理解+证据 → `verify` 校验落盘；判断保持 `pending_user_confirmation`。

- `--input` 裸文件名按 unit 目录相对解析（必须直接位于 unit 根下）。默认名：paper `note-fill.yaml`；repo `capability-fill.yaml`；dataset `dataset-fill.yaml`；blog `blog-fill.yaml`。`screening.yaml` 只用于读取和恢复 R1 前已有 paper record，不得用于新论文。
- evidence_refs 元素：`{source_unit_id, artifact, locator, quote}`（可选 summary）。artifact 为 unit 内相对路径（repo 证据为 repo-root 相对源码文件）。
- quote 必须**逐字**：双方做 whitespace 归一化（连续空白折一个空格）后子串匹配，大小写敏感；伪造即拒。PDF `page=N` 会窄化到该页——逐字但页错也是 violation。
- locator：PDF `page=N`/section/para；HTML `section`/`section:<anchor>`；repo 文件 `line=N`。
- concept：`synthesize.py concept prepare` 冻结至少 3 个 current confirmed unit，生成 `kb/synthesis/concepts/<slug>/concept-fill.yaml`；Agent 填 definition、可选 scope 与每个 association role 的逐字 evidence 后，用 `concept verify --input ...` 写 pending canonical concept。不得让脚本提炼定义或让 AI 自签。

### 人工笔记回流

只有用户当前消息明确点名 `obsidian/inbox/` 或 `obsidian/annotations/` 下的一份 Markdown 时，才使用现有 `ingest` 的私有模式：`kb --agent-protocol n.json ingest --human-note-area <inbox|annotations> --human-note-filename <basename.md>`。只传目录类别与 basename，不传任意路径，也不遍历目录。底层拒绝 nested、symlink、special、非 UTF-8、过大文件与 Obsidian review sheet；成功后原文件不改，exact bytes 冻结为 `source_origin=human-note` 的 blog source，`ingest` 自动续接 blog prepare。Agent 只从冻结副本/parse-cache 填四要素并逐字取证，再 verify；所得判断仍是 pending，来源为用户不等于用户已确认，签字仍须真人姓名与当前消息授权。

## 5. idea 证据 corpus

`idea.py` 的 analyze/review/discuss/generate prepare 会冻结 `<操作>-evidence-corpus.yaml`（如 `analyze-evidence-corpus.yaml`）：kb/units 下可引用文本 artifact 的清单+digest。verify 时证据只能引用清单内 unit/artifact；prepare 之后新入库的材料引不了。扩语料 = 先入库/链接相关 unit，再**重新 prepare** 重建 corpus。

## 6. 16 动词 → owner 对照

| 动词 | owner 脚本（.agents/skills/…） | 主要子命令 |
|---|---|---|
| help / doctor / update / obsidian | kb-cli 调度器内置 | —（update 走 updater，obsidian 走投影库） |
| init | knowledge-base-manager/scripts/kb.py + research-config-manager/scripts/config.py | init |
| status | kb.py + research-orchestrator/scripts/orchestrate.py | current-state；status / prepare-next-selection |
| next | orchestrate.py | next --json；prepare-/verify-/record-next-selection |
| find | kb.py | query（公开 ≤5 段带 locator；私有 protocol 附 current-claim context-pack） |
| add / ingest | source-intake/scripts/intake.py（ingest 自动续接 analyst prepare） | add --kind … --source …；明确点名的人工笔记见 §4 私有模式 |
| review | kb.py（confirm / promote / review-queue）+ 跨 owner 路由 orchestrate.py / idea.py / method.py / synthesize.py | 见 §2 §3 |
| reject | kb.py | promote --confirmation-status rejected |
| recall | skill-evolution-advisor/scripts/learnings.py | recall |
| resume / undo / restore | kb.py | resume / undo / restore |

无公开动词、自然语言路由的 owner：paper.py（prewarm-cache/complete-note/extract-figures/confirm；screen 仅兼容旧 record）、repo.py（scan-structure/map-capability/confirm）、dataset.py（profile/confirm）、blog.py（complete-note/confirm）、search.py（stage/materialize-selection）、synthesize.py（survey|review|taxonomy prepare|verify、survey confirm|reject、concept prepare|verify、composite）、idea.py（capture/generate/analyze/review/discuss/select/select-best/archive）、method.py（design/confirm-selection/reject-selection）、experiment.py（plan/log-run/follow-up/diagnose/confirm）、report.py（weekly/stage-summary/ppt-materials/writing-materials/outline/bib/draft-prepare/draft-verify/draft-export）、orchestrate.py（init-program/attach-unit/log-decision/add-reporting-event…）、config.py（show/set/eligible-preferences/record-effective/load-effective…）、monitor.py、archive.py、wiki.py、learnings.py/diagnostics.py。

`details.context_pack` 是给 Agent 的有界检索材料：只把 `formal.claims` 当库内已确认判断；`navigation.summary/passages` 只能帮助定位原材料。讨论/写作若要落盘，仍由 idea/report/survey owner 重新绑定证据并走各自确认门。

## 7. 常见失败恢复

| 错误码/症状 | 处置 |
|---|---|
| expired（卡片超过该展示轮冻结的有效期） | 重跑 `kb review` 取新快照再拍板 |
| already_applied | 该批已应用；重跑 review 看剩余 |
| stale_content | 内容已变；重跑 review，向用户展示新实质后再决定 |
| tampered_or_unknown | 检查 ref 是否 `kind:id`、`--apply-snapshot` 是否传展示轮协议文件名；重跑 review |
| invalid_decision | 决定超出展示范围或重复；只用快照内 ref |
| missing_confirmation_context | 补真实署名 / 当前消息授权 / evidence |
| authorization_stale / sheet_tampered | Obsidian 勾选与预览不符；重新预览或重新导出 |
| intake failed_retryable | 网络类瞬时失败，直接重试同一命令 |
| needs_local_repo_snapshot | 远程 repo 先建本地只读 checkout，再以本地目录重试 |
| review 无可确认项（awaiting_agent_fill / ready_to_verify） | 先补 fill + verify，再 review |

## 8. 交互章程（10 条）

1. **启动澄清**：每个 skill 开工前按其 SKILL.md「启动澄清」节问 2-4 个高价值问题，每问带默认值，"默认即可"合法；选择题优于开放问答。
2. **先复述再讨论**：进入讨论的前三句话复述你对问题的理解，关键术语先对齐再展开。
3. **观察式偏好**：用户明确纠正或连续做同形修改时，私下记录短的逐字原话、目标 skill 和 operation 为 pending；攒到任务收尾自然问“这两点要记住吗”，每批 ≤2 个，绝不开局问卷。确认/忽略都只消费本轮 `kb review` 展示快照；不得直调 learning review/promote。
4. **大活先报量级**：批量任务先报预计规模/耗时，小样试做 1-2 个确认口径后再全量。
5. **伴读三段式**：新材料先给结构地图 → 答疑必带 locator 可回溯 → 落库前先询问。
6. **口头信息分型**：回答时区分「库内证据（带出处）/ 我的推断 / 需验证」，不混说。
7. **路线讨论三栏**：技术路线讨论维护「共识 / 分歧 / 待验证」三栏，每告一段落复述一次。
8. **开场接续**：新会话先报上次进行到哪、有几件待拍板，再问今天做什么。
9. **四行收尾**：做了什么 / 落了什么盘 / 待你确认什么 / 建议下一步；低频附一句 token 复用说明（已入库材料下次无需重读全文）。
10. **入库静默礼仪**：用户丢链接默认轻量入库 + 两行简报 + 问是否深读；批量不逐个打断；任务被打断先挂起并告知可随时恢复。
