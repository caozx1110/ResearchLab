# workspace-oss 优化 plan

> 更新于 2026-07-04。两条并行的 track：
>
> - **Part A（第 1-3 轮：收尾与修复）** §0-§7 —— skills 对抗性审查（23 单元 → 109 发现 → 101 存活）。**第 3 轮批次 A 已施工并提交（commit `5de78fb`，40 测试全过）**；批次 B（god-file 拆分等）待后续。
> - **Part B（第 4 轮：前瞻路线图）** §8 —— 8 视角前瞻 review（50 提案 → 28 项），面向**新功能 / UX 优化 / 结构演进**，非 cleanup。含 3 个新核实的真 bug（§8 D 区）。
>
> 约束：**skill import 面兼容**（`from research.v2/common import ...` 全部照旧，已核实零断裂）。**行为保持** 对 bug 修复豁免（有意变更，commit 注明）。面向 Codex/后续施工，全部带 `file:line`。

---

## ✅ 第 3 轮批次 A —— 已施工并提交（commit `5de78fb`）

用户拍板的三处决策已落地施工,**40 测试全过、24 脚本编译通过**:

1. **执行范围 = 「修 bug + 快赢批」**：✅ 完成 = **§1 七个真 bug（B1-B7）** + **§3 T-ROUTE 路由补全** + **§2 wiki add 抽共享参数** + **§4.1 九个 SKILL.md 对齐**。三个防漂移/回归测试已加（route-hints 守卫、SKILL.md↔CLI 漂移、B2 seed 保留）。**批次 B 未动**。
2. **wiki `add` = 保留真入库**：✅ 参数契约抽到 `.agents/lib/research/intake_cli.py`,intake.py 与 wiki.py 共享单一真相源。
3. **B2 seed 归属 = 重建时保留空种子**：✅ `rebuild_governance_catalogs` 新增 `_preserve_empty_governance_seeds`,并补 `test_v2_governance_seeds.py` 回归护栏。

---

## ✅ 第 4 轮 Top 6 —— 已施工 + 对抗性 review（commit `dbf6d7f`..`b5dc066`）

Part B 的 Top 6 已由 Codex 逐项单独提交（6 commits），并经 **7 单元对抗性 review（18 findings，0 blocker，全部 SHIP_WITH_NITS）**。**56 测试全过**。review 查出的 should-fix / cheap 项已就地修复（见下）。

| 项 | commit | 状态 |
|---|---|---|
| **B8** counts + workflow 生命周期命令 | `dbf6d7f` | ✅ 计数 bug 已修（`status=='open'`）+ answer/resolve/drop 命令 |
| **D1** build_index 单次扫描 | `744fd86` | ✅ 零行为变更，输出字节稳定测试 |
| **U1** review-queue + search confirmation 过滤 | `50eef2f` | ✅（sort 改为按真实 instant，见修复③） |
| **U2** program dashboard/next + current-state | `edefcd9` | ✅ |
| **B9** 确认溯源（禁 agent 自签） | `b0f29f6` | ✅ + review 修复①②④⑤ |
| **F1** 全文+排序检索 | `b5dc066` | ⚠️ **部分**：内存版 ranked 全文 + `retrieval.py` 恢复已做；**持久化 `kb/search-index.yaml`(按 file_hash 增量) + query alias 扩展 仍欠**（deferred，见 §9 F1 剩余） |

**review 后已就地修复（未 commit，待一并提交）**：
- ① repo-analyst SKILL.md:25 + ② blog-analyst SKILL.md:30 —— `confirm` 示例补上 B9 新增的必填 `--confirmed-by/--evidence`（原示例会 argparse 报错，should-fix，已核实）。
- ③ `kb.py review_sort_key` —— 改为按 `parsed.timestamp()` 真实 instant 排序（原按 isoformat 字符串，跨时区会错序）。
- ④ `v2.py require_confirmation_provenance` —— bare-string evidence 不再被 `_text_list` 静默判空。
- ⑤ 新增 2 个 provenance 测试：非 confirmed 转移（auto/pending/rejected）**不需** provenance 的回归护栏 + bare-string evidence 接受。
- ⑥ SCHEMAS.md —— 补 `confirmation{by,at,evidence,method}` 字段定义 + gate 段 provenance 规则。

**剩余 review nits（非阻塞，follow-up）**：F1 持久化索引/alias（§9 F1）；测试补强（B8 四个生命周期命令走 CLI dispatch、U1 review-queue CLI、U2 dashboard 加第二个 program 才真验排序、D1 补 taxonomy/pools 字节稳定、F1 补 partial-match/tie-break 用例）；`kb_browser_lib.py:806` program card 计数 all vs state 计 open 的跨面不一致；`orchestrate.py:124` `program_ids()` 与局部变量同名（隐患）。

---

## 0. 现状校正（旧 plan 已过期，先纠正事实）

第 2 轮 plan 的多处前提**已被本轮审查证伪**——base 层重构其实已经落地，旧 plan 还当它没做：

| 旧 plan 断言                                       | 实际（本轮核实）                                                                                                                                                                                        | 裁决                 |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- |
| 「12 个计划模块一个都不存在」(§2 P0)              | **5 个 base 模块已存在且已接线**：`yaml_io.py`(81) `slugs.py`(135) `ids.py`(109) `dedup.py`(43) `pdf_layout.py`(509)；`common.py:21-23` 已 `from .dedup/.slugs/.yaml_io import ...` | CONFIRMED，需改写    |
| 「T3-5 PDF 引擎未搬，paper.py 仍 1297 行」(§2 P1) | **PDF 引擎已全量搬到 `pdf_layout.py`**（`_ensure_layout_backend`/几何/聚类/裁剪/质量都在），paper.py **不再重复**这段，只 `import`                                                    | CONFIRMED，T3-5 关闭 |
| 「v2.py 2383 行 / common.py 1220 行」              | v2.py**2292** 行 / common.py **984** 行（tests 目录已建，**35 测试全过**，`retrieval.py` 已删）                                                                                     | 数字刷新             |

**✅ 已达成（勿重做）**：Tier 0 测试基建 + pytest.ini/requirements-dev.txt；Tier 1 死代码删除 + 文档漂移修复；base 层模块拆分（yaml_io/slugs/ids/dedup/pdf_layout）；PDF 引擎抽离。

**❌ 仍欠（本轮重点确认）**：**domain 层拆分一个都没做**——v2.py 仍是 2292 行 god-file（96 个顶层 def，`paths/records/confirm/index/backup/prefs/git_ops` 7 个 domain 模块全缺）；common.py 半重构（base 已抽离并正确 re-export，但 ~665/984 行的 domain 逻辑仍内联）。**skill 层从没被系统审过**——本轮补上，查出 101 条。

**总体健康度**：无 P0 回归、无断裂 import、无 base 符号被重复塞回 v2/common。问题集中在 ①几个真 bug ②大面积 checkpoint/finalize 不一致 ③routing 表与 SKILL.md 承诺对不上 ④SKILL.md 文档漂移 ⑤两个 god-file（v2.py/kb_browser_lib.py）。

---

## ✅ 1. 真实 bug（B1-B7）—— 已全部修复（commit `5de78fb`）

> 这些是第 3 轮审查查出的正确性缺陷,已作为有意行为修正提交。逐条核实过修复正确性。以下留档。

| #            | 位置                                                  | 问题                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        | 裁决                              | 成本 |
| ------------ | ----------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------------------- | ---- |
| **B1** | `knowledge-base-manager/scripts/kb.py:216`          | `promote` 的 commit 触发逻辑**反了**：`trigger = "milestone" if auto_commit_mode != "manual" else "manual"`。而 `maybe_auto_checkpoint`（v2.py:1166）里 `trigger=="manual"` → **无条件 commit**。结果：用户配了 `manual`（不想自动提交）时，`promote` **偏偏强制提交**。修法：像其它写入方一样传 `trigger="milestone"`，让 `maybe_auto_checkpoint` 按 mode 裁决；`"manual"` 只留给显式 `git-checkpoint`。                                            | **CONFIRMED**（已独立复核） | 低   |
| **B2** | `research-config-manager/scripts/config.py:171-217` | `set-taxonomy-seed`/`set-pool` 写出 `member_ids` 为空的**纯 seed**；而 knowledge-base-manager 的 `rebuild-governance`→`rebuild_governance_catalogs`(v2.py:1586) 会**按 member_ids 重建**，把这些零成员 seed **静默清空**。两个 skill 抢同一份 taxonomy/pool 治理，seed 丢失。**已定修法(用户选)：让 `rebuild_governance_catalogs` 保留零成员 seed（如按 `status: seed` 或"无 record 支撑但已声明"识别并不清空），config-manager 继续管 seed 输入。** | **CONFIRMED**               | 中   |
| **B3** | `method-designer/scripts/method.py:43`              | 显式`--repo-id` 被**静默忽略**：仅当该 id 已是一个 v2 repo unit 才生效，否则脚本自行另选一个 repo。用户指定被吞。                                                                                                                                                                                                                                                                                                                                                                   | **CONFIRMED**               | 低   |
| **B4** | `repo-analyst/scripts/repo.py:363`                  | `confirm` 命令没清 AI 的 `information_types`，导致 `write_record` 里 `validate_write` 触发 confirmation-gate 告警（本该是「已确认」却被判「待确认」）。                                                                                                                                                                                                                                                                                                                             | **CONFIRMED**               | 低   |
| **B5** | `method-designer/scripts/method.py:160`             | no-repo 分支想渲染`pending` 占位，但该分支**不可达**，实际渲染成空。                                                                                                                                                                                                                                                                                                                                                                                                                | CONFIRMED                         | 低   |
| **B6** | `experiment-workbench/scripts/experiment.py:201`    | run 文件名按`glob` 计数派生，**可碰撞/覆盖**已有 run。                                                                                                                                                                                                                                                                                                                                                                                                                              | CONFIRMED                         | 低   |
| **B7** | `discussion-archivist/scripts/archive.py:41`        | 讨论文件名只由 title 派生，**同名讨论互相覆盖**。                                                                                                                                                                                                                                                                                                                                                                                                                                     | PLAUSIBLE                         | 低   |

---

## ✅ 2. wiki.py `add` —— 已保留并抽共享参数（commit `5de78fb`）

`add` 保留真入库(subprocess 调 intake.py),参数契约已抽到 `.agents/lib/research/intake_cli.py`(`add_intake_add_arguments`/`intake_add_argv`),intake.py 与 wiki.py 共享,消除手抄漂移。

---

## 3. 🔴 P1 —— 跨 skill 结构性问题（本轮最大杠杆）

### T-FINALIZE（⏭️ 批次 B）：record 收尾序列 ~26 处复制粘贴 → 抽 `finalize_unit_step()`

审查裁决 **CONFIRMED**（`x:shared-lib-consistency`；paper.py:550 等）。`gate → append_history → write_record → build_index → checkpoint` 这套块在 **5 个 skill（paper/repo/blog/experiment/idea）复制了约 26 次**，无共享 helper。

- **做什么**：建 `confirm_unit(root, record, kind)` + `finalize_unit_step(...)`，替换各 analyst/workbench 的近似块。**落到 domain 层新模块 `records.py`/`confirm.py`（见 §5），别再堆进 v2.py。**
- 附带消灭「`checkpoint = checkpoint_and_report(...)` 赋值后从不读」的**死赋值**——本轮在 **7+ 处** 命中（kb.py:155×4、repo.py:286、config.py:361、orchestrate.py:328、source-intake intake.py:296、idea.py:305、paper.py:664×6），统一走 helper 后自然消失。 `[高杠杆/中]`

### T-CHECKPOINT（⏭️ 批次 B）：checkpoint 调用策略不一致 → 定一条规则

审查裁决 **CONFIRMED**（`x:shared-lib-consistency`：paper/repo/idea 调 checkpoint，blog/experiment 跳过；experiment.py:265、blog.py:19）。

- ⚠️ **验证有分歧需注意**：`literature-synthesizer`（写 `kb/synthesis/`）和 `method-designer`（写 `design/`）的「不 checkpoint」被**证伪**（写入根不在 auto-checkpoint 范围内，属 by-design）。所以**不要**一刀切「所有 skip 都是 bug」。
- **做什么**：在 SCHEMAS.md 明确「哪些写入根走 auto-checkpoint / 由谁触发」，然后 blog/experiment 若确属 milestone 写入则补 checkpoint，其余按 by-design 保留。随 T-FINALIZE 一起收敛。 `[中/中]`

### T-ROUTE（✅ 已完成，commit `5de78fb`）：orchestrator 路由表够不到 SKILL.md 承诺的 skill

审查裁决 **CONFIRMED**（`x:routing-boundaries`；orchestrate.py:37-54）。

- `ROUTE_HINTS` **无 `source-intake` 映射**，但 SKILL.md:17 明写「Route source work to `source-intake`」——新 source 请求要么落 analyst（跳过 staging/去重），要么落默认 print。**5 个 skill（source-intake / method-designer / research-config-manager / knowledge-base-manager / skill-evolution-advisor）从路由完全够不到。**（已独立复核 grep 无 source-intake）
- 「新 paper/repo/blog」被直接路由到 analyst，**绕过 source-intake 的 staging+去重**（与 SCHEMAS.md ownership 矩阵冲突）。
- **做什么**：补全 `ROUTE_HINTS`（intake/source/入库/staging → source-intake，等），并**加一条测试**断言 `ROUTE_HINTS` 值 ⊆ 真实 skill 目录集，防新 skill 静默漏配。 `[中/低]`

### T-GODFILE-v2（⏭️ 批次 B）：domain 层拆分（旧 plan P0，事实刷新后仍是核心）

审查裁决 **CONFIRMED**（`x:v2-godfile` v2.py:1；`x:lib-refactor-audit`）。v2.py 2292 行 / 96 def，仍**定义**全部 domain 关注点。

- **做什么**：纯搬移 + 门面重导出，`v2.py`/`common.py` 瘦成 façade（顶部 `from .records import *` 等），保证 `from research.v2/common import X` 全照旧。目标 domain 模块（base 层已就位）：
  ```
  paths.py     # project_root..record_path（v2:154-236）
  prefs.py     # default/load/write_runtime_preferences（v2:363-524）
  records.py   # _record_template/normalize_record_schema/append_history/kind_payload_skeleton（v2:785-934）+ load_list_document/append_list_item（common）
  confirm.py   # _record_needs_gate/validate_write/promote_record（v2:1430-1480,2273）+ finalize_unit_step（新，见 T-FINALIZE）
  index.py     # build_index/rebuild_governance_catalogs/apply_record_governance（v2:1356-1707）
  backup.py    # backup_source/_copy_dir/_truncate_snapshot_text（v2:1997-2061）+ fetch_url/html_to_text（common）
  git_ops.py   # ensure_kb_git_repo/maybe_auto_checkpoint/checkpoint_and_report/git_checkpoint（v2:1064-1220）
  ```

  另把 `detect_duplicate`（v2:2063）并入既有 `dedup.py` 归位。
- **硬性验收**：① façade 重导出后 `grep -rn "from research" .agents/skills` 每个符号可 import；② 无循环 import（base ← domain ← 编排）；③ 35 测试全过 + 24 脚本编译；④ 逐模块搬、每搬一个跑测试。 `[高/中-高]`

---

## 4. 🟡 P2 —— skill 层收尾（去重 / 一致性 / 文档 / 小 bug 已在 §1）

### 4.1 doc↔CLI 漂移（✅ 已完成，commit `5de78fb`）（SKILL.md 与真实 argparse 对不上，用户会踩）

| skill                   | 位置           | 漂移                                                                                                                                                                                                                                               |
| ----------------------- | -------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| experiment-workbench    | SKILL.md:44-46 | phase 段文档给的`outcome` 枚举 `{pass,fail}` **被 argparse 拒**（真值是 success/partial/failure）；表里点名的产物 `stats.yaml` 等**脚本从不产出**；叫 executor 把 arm 名塞进 `--classification`（schema-mismatch，实为枚举）。 |
| idea-workbench          | SKILL.md:22    | 命令手册**漏 `select` / `archive`**（都是真子命令）。                                                                                                                                                                                    |
| research-orchestrator   | SKILL.md:30    | `attach-unit` / `query-program` 未文档化。                                                                                                                                                                                                     |
| paper-analyst           | SKILL.md:29    | `reject` 子命令存在但只文档了 `confirm`。                                                                                                                                                                                                      |
| knowledge-base-manager  | SKILL.md:55    | `index` / `git-log` 子命令未列。                                                                                                                                                                                                               |
| method-designer         | method.py:105  | `--baseline` / `--risk` flag 未文档。                                                                                                                                                                                                          |
| research-config-manager | config.py:270  | SKILL.md 称`init` 会初始化 markdown settings，但 `init` **从不写** research-settings。                                                                                                                                                   |
| discussion-archivist    | SKILL.md:21    | 文档称 tradeoff/open-question「必填」，CLI**不强制**。                                                                                                                                                                                       |
| skill-evolution-advisor | SKILL.md:20    | 漏`--stdout-prompt` / `--root`，且没说明落盘路径。                                                                                                                                                                                             |

> **建议**：本轮把上表逐条对齐（改 SKILL.md 或补/去 argparse），并**加一个防漂移测试**（对每个 skill：SKILL.md 出现的子命令 ⊆ argparse 定义的子命令），一劳永逸。 `[中/低]`

### 4.2 in-file / 跨 skill 去重

- **orchestrate.py:312** 6 个近似 reporting-event dict + 重复 write_state/print/checkpoint → 抽 `emit_event()` + `finish()`。（CONFIRMED）
- **experiment.py:266** program_id-guard + `append_program_reporting_event` 块在文件内重复 3 次。
- **v2.py 内部**：`_rebuild_taxonomy_block`（normalize_record_schema:920 vs apply_record_governance 重复，且有**潜在 staleness bug**）；`_coerce_num`（load_runtime_preferences 里 8 处 int/float try/except，v2:437）；`_accumulate_catalog`（rebuild_governance_catalogs 3×55 行，v2:1598）。→ **随 §3 T-GODFILE-v2 落到 records/prefs/index**。
- **repo.py:47** `_candidate_repo_roots`/`_pick_repo_root` 与 paper-analyst 的 `_source_paths` 重复 → 提到共享 lib。
- **literature-synthesizer synthesize.py:23** `select_records` 重造了 lib 的 `search_records` token/haystack 匹配 → 复用 lib。
- **navigator**：`stop_kb_browser.py:42` 与 `status_kb_browser.py` 重复端口扫描+健康探测；`kb_browser_lib.py:385 _path_mtime_iso` 与 `serve_kb_browser.py _mtime_iso` 重复。 `[中/中]`

### 4.3 一致性缺口（skill 偏离同族约定）

- `idea-workbench idea.py:345` review-assist 改并持久化 record 却**不 append_history**（异于同族）。
- `research-orchestrator orchestrate.py:156` attach-unit 写 unit record **不 build_index**。
- `knowledge-base-manager kb.py:173` refresh-schema 等命令 checkpoint 与否不一致。
- `research-config-manager config.py:361` 仅 set-runtime-pref 会 checkpoint，其它 kb-变更命令不 checkpoint。
- `repo-analyst repo.py:284,333,346` 无 `--defer-post-actions`/`reject`；complete-note 出 `repo-context.md`（SKILL.md 没提）且不升级 information_types/不跑 governance。
- `blog-analyst blog.py:58,74` summarize 跳 `apply_record_governance`（无 taxonomy 推断 + 对非骨架 record 有潜在 KeyError）；complete-note 不设 information_types/status。
- `skill-evolution-advisor create_retrospective.py:188` 直写 freeform markdown，**刻意**绕开共享 v2 record/index 管道（by-design，仅记录）。

### 4.4 schema / 治理

- `x:schema-alignment v2.py:885`：SCHEMAS.md:41 说 `needs_human_confirmation` 「与 confirmation_status 同步」，但 `normalize_record_schema` **不实现该同步**（仅 validate_write 校验、promote_record 单点设置）。→ 改注释或在 normalizer 实现（~2 行）。（已独立复核）
- `source-intake intake.py:297`：repo/blog 入库却发 **paper-only** config 提示（ux 误导）。

### 4.5 god-file（v2 之外）

- **`research-navigator/scripts/kb_browser_lib.py` 1191 行**（`x:navigator-browser`）：snapshot 数据模型 build 与 daemon/runtime/port 逻辑混在一起（kb_browser_lib.py:487）；`build_tag_items` 的 taxonomy enrichment **完全惰性**（所有 taxonomy 字段恒空，dead，:609）；snapshot 多次重解析整个 KB（:461）。→ 拆 data-model 与 runtime 两层 + 删惰性 stub。
- **`paper-analyst/scripts/paper.py` 804 行**：两个 ~110 行函数（screening 启发式 + note markdown）可抽（paper.py:328）。
- **`research-orchestrator/scripts/orchestrate.py` 558 行**：随 4.2 emit_event/finish 抽取自然瘦身。 `[中/中]`

---

## 5. 🟢 P3 —— 零散清理（非阻塞，可随手做）

- **死代码/死赋值/无用 import**：v2.py 5 个无用 import（:40）+ `figure_extraction_mode` 恒常量 flag（:467）+ compact_unit_ids 冗余守卫（:2184）；common.py `load_yaml` 死参 `allow_simple_fallback` + 2 处 `=True` 调用（:209）+ 4 个孤儿 import（os/shutil/STOPWORDS/slugify_tag，:8）；idea.py:186 恒真 `if not bundle_id`、:305 死赋值；kb_browser_lib.py:7 无用 os/shutil/re；kb.js:846 三个声明未调用的 helper；open_kb_browser.py:8 无用 `import sys`；serve_kb_browser.py:144 无用 `rel`。
- **测试补强**（现有 35 测试是好的，补未覆盖分支）：`validate_write` 默认 `RESEARCH_VALIDATE_STRICT` env 分支（v2:1449）；`detect_duplicate` 返回 None 的否定用例（v2:2099）；`is_canonical_unit_id` 拒绝分支（v2:1797）。
- **error-handling 小改**：experiment.py:37 `parse_metrics` 静默丢弃无 `=` 的 `--metric`；kb.py:90 `promote --status` 无 argparse choices；orchestrate.py:358 status 用无守卫 `['key']`；serve_kb_browser.py:341 PUT /api/file 只 catch ValueError，写入/checkpoint 的 OSError 逃逸。
- **magic-number / 脆弱格式**：report.py:70 空态靠行数魔数、:105 无条件建 reports_root 留空目录；wiki.py:81 空结果判 `len(lines)==4`；method.py:307 硬编码 matrix 行数。
- **triggering 微调**：`knowledge-base-manager` 与 `literature-synthesizer` 的 description **共享 taxonomy/topic/pool 触发词**（SKILL.md:3，双向 CONFIRMED）→ 收窄一方措辞，减少 skill 选择歧义。（注：config-manager↔kb-manager、report-author↔navigator、navigator「report-material」等 description「重叠」经验证**功能上不冲突，已驳回**，不动。）
- `wiki-adapter wiki.py:84` 写 wiki note 后的 `build_index()` 对该 note 是 no-op；`literature-synthesizer synthesize.py:159` 跳 `ensure_v2_workspace`、:143 `survey` 用 `--field` 而同族用 `--query`。

---

## 6. 执行顺序（Part A 剩余）

> **批次 A 已完成并提交（commit `5de78fb`）。** 下面 **批次 B** 是 Part A 的剩余项;Part B 路线图见 §8。

### ✅ 批次 A —— 已完成

1. ~~§1 真 bug B1-B7~~ ✅ 已修并逐条核实。
2. ~~§3 T-ROUTE~~ ✅ 已补 ROUTE_HINTS + 守卫测试。
3. ~~§2 wiki.py add~~ ✅ 已保留 + 抽 `intake_cli.py` 共享参数。
4. ~~§4.1 doc 漂移~~ ✅ 9 个 SKILL.md 已对齐 + 防漂移测试。

### ⏭️ 批次 B —— 后续轮次（Part A 剩余，尚未做）

5. **§3 T-GODFILE-v2 domain 拆分**（核心大重构，7 模块）：`paths→prefs→records→confirm→index→backup→git_ops`，逐模块搬、每步跑测试，v2/common 变 façade；§4.2 的 v2 内部 dup 随对应模块归位。
6. **§3 T-FINALIZE + T-CHECKPOINT**：`finalize_unit_step`/`confirm_unit` 落到 records/confirm，替换 ~26 处复制块，清死赋值 + 收敛 checkpoint 策略。
7. **§4.2-4.5 其余去重/一致性/god-file（kb_browser_lib/paper/orchestrate）+ §5 零散**（非阻塞，穿插做）。

**每个 Tier 完成先给 diff + 跑测试全绿再进下一个。**

---

## 7. 被审查**驳回**、不必做的项（避免重复劳动，8 条）

对抗性验证把下列判为 **not-an-issue**（reason 已核）：

- `literature-synthesizer` / `method-designer` 「不 checkpoint」——写入根不在 auto-checkpoint 范围，**by-design**（≠ blog/experiment 的真缺口）。
- `report-author`↔`research-navigator`、`research-config-manager`↔`knowledge-base-manager` 的 description「重叠」——共享词但**功能不冲突**，非路由歧义。
- `research-navigator` description「report-material pages」——grep 证明**并非未实现**（claim 依据错误）。
- `serve_kb_browser.py:127` GET /api/file 非 UTF-8 500——**驳回**。
- `kb_browser_lib.py:66` `research_root()` doc/research fallback「不可达且与 server 冲突」——**机制判断错误**，驳回。
- `orchestrate.py:53` 「知识库→wiki-adapter 绕过 kb-manager」——route 只是**模糊 hint**，非硬派发，可接受。

> 另：本轮**无 P0**——无断裂 import、无回归、base 层符号未被重复塞回 v2/common。§0「façade 未被消费 / 与 v2 重复」等旧 plan 猜测也被证伪（façade 已被消费、零同名重复）。

---

---

# Part B —— 第 4 轮：前瞻路线图（功能 / 优化 / 结构）

> 2026-07-04。8 视角前瞻 review（lifecycle / search / data-model / orchestration / ux / performance / structure / robustness）→ **50 提案 → 去重合并 28 项**。与 Part A（cleanup/修复）互补：这里是**该长的新能力与结构演进**。已在 Part A 追踪的项不重复。
> **一句话诊断**：研究闭环**只有前向边、没有回边**（gap 不催生 idea、实验结果不回写假设、复用不追踪），而系统赖以运转的**确认门却没有人工入口**——抓住这两点，大半价值就落地。

## 8. 🛡️ D 区 —— 新核实的真 bug（不是功能，是坏了，建议并入修复批）

| #             | 位置                                                            | 问题（已独立核实 ✅）                                                                                                                                                                                                                                                                                                                                                                                                                                          | 成本                               |
| ------------- | --------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------- |
| **B8**  | `research-orchestrator/scripts/orchestrate.py:238`            | **计数哨兵 bug**：`refresh_state_counts` 按 `status != 'closed'` 过滤，但 schema 词表是 `open/answered/dropped`（OQ）与 `open/fulfilled/dropped`（evidence）——字面 `'closed'` **从不出现**，故已 answered/fulfilled/dropped 的项**永远计为 open**，program 计数长期虚高。改：计数改为 `status ∈ 各自的 OPEN 集`；顺带加 `answer-question`/`resolve-evidence`/`drop-*` 生命周期命令 + emit `evidence-fulfilled` 事件。 | 低（哨兵单点）/ 中（生命周期命令） |
| **B9**  | `paper-analyst/scripts/paper.py confirm` 等各 confirm handler | **确认可自签**：`confirm` 只收 `--paper-id`，handler 硬编码 history "confirmed by user" 并 set confirmed——**写 pending 的同一个 AI 能自调 confirm**，`promote_record` stamp `last_human_confirmed_at`（v2:2339）无任何人类证据。信任模型硬伤。改：confirm/promote 强制 `--confirmed-by/--evidence`（或 harness 仅真实用户 turn 注入的一次性 token），持久化 `confirmation{by,at,evidence,method}`，空证据拒绝。                      | 中                                 |
| **B10** | `v2.py backup_source:2068` + `common.py fetch_url`          | **源归档静默失败**：对 URL 仅在 `_is_html_response` 时快照 → arxiv/PDF（VLA 主源）走 non-HTML 分支**什么都不下载**，`except: file_hash=''` 吞掉网络失败且无 warning → "不可变源"被 link rot 静默毁掉（raw/ 被 gitignore 无法找回）。改：URL 解析为 PDF/arxiv 时 `fetch_url(binary=True)` 存 source/ 带真 sha256 + size cap + 重试，返回显式 `backup_status/warning` 由调用方 surface。                                                   | 中                                 |

> B8-B10 与 Part A 的 B1-B7 同性质（真缺陷），建议下一个修复批一起做。B8 的计数修正是单点快赢。

## 9. 🚀 A 区 —— 新功能（researcher-facing）

| id           | 功能                                      | 现状缺口（已核实项标 ✅）                                                                                                                              | 建议                                                                                                                                                                                                                     | impact/effort       |
| ------------ | ----------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------- |
| **F1** ⚠️部分 | 全文 + 排序检索                           | `search_records`(v2:1870) 只匹配 title/summary/tags/topics/pools 5 字段，payload/note markdown 全不可搜；要求全 token 命中，partial 静默返空；无排序 | ✅已做:恢复 `retrieval.py` + 全文抽取 + 加权 `rank_records`（内存版，AND 优先 OR 兜底）。**⏳ 剩余(deferred):** 持久化 `kb/search-index.yaml`(按 file_hash 增量,现在每次搜索重读全部 note) + query alias 扩展                | high / M（剩余 M）            |
| **F2** | 闭合研究回路 gap→idea / experiment→idea | `synthesize` 的 gaps 是占位串；`experiment.py:177` 存 `idea_id` 但 confirm/diagnose **从不回写 idea**                                      | 加`synthesize gaps`(覆盖矩阵)写 `synthesis/gaps/` + emit open-questions；`idea generate --from-gap/--from-open-question`；实验 confirm 后（用户批准）迁移 linked idea → validated/refuted 并建双向 `links[]` 边 | high / M            |
| **F3** | backlink / 引用图                         | `link_records`(v2:2308) 已写正反向边，但 `build_index` **丢弃 links** → 边在盘上不可读                                                      | `neighbors()` + `build_index` 产 `kb/graph.yaml` + `kb.py graph` + navigator 展示 inbound backlinks + flag dangling 边                                                                                           | high / M            |
| **F4** | 复用溯源改类型化边（删死字段）            | `reuse_flags{6 bool}` **零 setter，纯死字段** ✅；真实复用在 `links[]` 但 relation 无受控词表                                                | 删`reuse_flags`；定受控 RELATION 词表（cites/builds_on/tested_by/reported_in…）并在 link_records 校验；下游消费建边；`kb.py reuse-report`（未用单元/最常复用/per-idea 溯源）                                        | high / M            |
| **F5** | dataset/benchmark 一等实体                | LIBERO/Open-X 等只是 payload 自由字符串(v2:527)，"哪些 paper 用 LIBERO"答不了                                                                          | C1 落地后注册`dataset`/`benchmark` kind + `paper --uses--> dataset` 类型化边，给 synthesizer 真实覆盖轴                                                                                                            | high / L（依赖 C1） |
| **F6** | related / more-like-this                  | synthesizer 只做全局 histogram，无 per-unit 相似度；intake 去重无邻居提示                                                                              | `related(unit, k)` = tags/topics Jaccard + 全文 TF-IDF 重叠，缓存 top-k，展示于 navigator/intake                                                                                                                       | med / M（依赖 F1）  |
| **F7** | 结构化过滤 + saved smart-collection       | `wiki query` 一次性不可复跑；`search_records` 只收 kind+pool；`select_records` 重造 substring-AND                                                | 小 query grammar（`kind:/topic:/status:/confirm:/priority:`）喂共享 filter；saved query 存 config 可复跑                                                                                                               | med / M             |
| **F8** | history 时间轴 + activity feed            | record`history[]` 审计丰富，但 snapshot builder(kb_browser_lib:529) **完全丢弃**                                                               | snapshot item 带最近 ~8 条 history + detail pane 时间轴 + dashboard "Recent activity" feed                                                                                                                               | med / M             |

## 10. ⚡ B 区 —— UX & 工作流优化

- **U1 确认收件箱 ★**：系统处处 `pending_user_confirmation`，却**无任何命令枚举 pending**（`search_records` 连 confirmation_status 过滤都没有 ✅）；navigator 只给字母序 `[:12]` 单元切片。→ `kb.py review-queue`/`navigate.py review-inbox` 跨 kind 收集 pending、按 age 排序、每项附可直接跑的 confirm 命令。**CLI 部分是最高杠杆快赢（S）**；进阶做 browser "Review" tab + 受控 `POST /api/confirm`。
- **U2 程序仪表盘 + "下一步"**：`render_current`(navigate.py:31) 只列 confirmed → 因零确认**首页天天渲染"暂无条目"**；`orchestrate route` 静态 dict，从不读 `state.yaml`。→ `orchestrate next/dashboard` 跨 program 排序（blocking evidence→高优 OQ→pending→stale-stage）；`render_current` 改读 program state。 [med-high / M]
- **U3 阅读列表变工作队列**：`render_reading_list`(navigate.py:52) 取 `papers[:12]` 原序；忽略两个现成信号——`priority`（81 record 全有）与 program `evidence-requests`（带 related_unit_ids/blocking）。→ 按"为 program X 补证据 + priority + recency"排序 + triage state。 [high / M]
- **U4 报告变真摘要 + 发布门**：`report.py` 每事件一行 flat dump，忽略 state/OQ/evidence/decision；发布只 checkpoint、**从不跑已存在的 `lint_records`/`lint_workspace_integrity`** → 可把未确认 AI 推断当既定事实 publish。→ report 读 state+workflow 文件、按 event_type 分组、`last_report_at` watermark 增量；发布前跑 lint + pending 扫描，默认阻断或标 `UNCONFIRMED`。 [high / M]
- **U5 browser 快速捕获**：只读+编辑，读 A 时想 queue B 只能手敲 intake。→ `POST /api/capture` 落 staging note 到 `kb/intake/`（非 record，保 canonical-write 纪律）。 [med / S 快赢]

## 11. 🏗️ C 区 —— 架构与代码结构（Part A 的 T-GODFILE 之上的延伸）

- **C1 声明式 KIND_REGISTRY**：一个 kind 散落 **≥6 处**（`UNIT_KIND_DIRS`/`UNIT_KIND_PREFIXES`/250 行 skeleton/`record_summary`/`detect_duplicate` 的 `if kind==`/SCHEMAS enum）→ 一张 `KindSpec` dataclass 表派生。落入 T-GODFILE 的 `records.py`，是 F5 前置。 [high / M]
- **C2 research.cli 脚手架**：15 脚本手抄同款 bootstrap+argparse+dispatch，finalize **三种不一致形状** → `lib/research/cli.py` 的 `bootstrap()`+`@command` 分发 + harness 拥有的 `finalize()`（承接 T-FINALIZE 的 `finalize_unit_step`）。 [high / L，依赖 T-FINALIZE]
- **C3 类型化 UnitRecord/RecordView**：skill 里 **342 处 raw-dict 访问**（241 处无守卫 `record[...]` 会 KeyError）→ `@dataclass UnitRecord`，给确认/信息类型一个集中执行点。 [high / L]
- **C4 schema_version + 迁移表**：record 无版本号，"迁移"= `_deep_fill_missing` 仅补缺键、从不 rename/prune → 改名字段留孤儿键。→ 加 `schema_version` + `MIGRATIONS=[(from_ver, fn)]`，`refresh_record_schemas` 成 driver。 [high / M]
- **C5 拆 index 更新 vs 治理重建**：`build_index` 无条件调全量 `rebuild_governance_catalogs` 且每写一次都调（职责焊死 + O(N)/write）→ 拆 `update_index_entry`（增量，finalize 用）vs `rebuild_index`（显式，归 kb-manager）。是 D1 结构前提，扩展 `index.py`。 [high / M]
- **C6 标准 result envelope**：脚本靠 print `[ok]`+0/1，错误通道不一致 → harness `{status, unit_id, artifacts, warnings}` + `--json` + exit-code 分类。 [med / M]
- **C7 发现式 contract-test**：现有一致性测试只覆盖 9/16 skill 且手维护映射 → `glob .agents/skills/*` 自动发现 + 断言 SKILL.md↔openai.yaml↔argparse↔schema↔kind-registry 不变量。 [med / S 快赢]
- **C8 section 级确认 + sync 那 2 行**：`information_types` 扁平，任一 inference 翻整 record pending，无法确认事实半；且 normalize 不同步 `needs_human_confirmation`↔`confirmation_status`（SCHEMAS.md:41 谎称同步，= Part A §4.4）。→ 先补 sync 2 行；进阶 per-section confirmation map。 [med / S+M]
- **C9 taxonomy 块改派生视图**：canonical_tags/primary_topic 是 tags/topics 纯副本，两处独立重算可 drift（= Part A §4.2）→ 停止持久化可派生字段，读时算。 [med / S]

## 12. ⚡ 性能（写路径去 O(N)）

- **D1 增量/延迟索引**：几乎每个写命令写完立即 `build_index`（~87 处），而它每次全量 `rebuild_governance_catalogs`+自己再全扫，对 4 个 O(N) 产物整体重写 → 单 record promote 触发全 KB 双解析。分层：①(快赢，零行为变更) build_index 接受已物化 records 一次扫；②写入只 append `kb/.runtime/dirty.yaml`，`kb reindex` 是唯一全/增量重建点；③治理目录按单 record diff 增量；④iter_records 加 (path,mtime,size) 缓存。 [high / S→M]
- **D9 git checkpoint 合并 + 收窄 add**：每里程碑写调 `git add -A .`（v2:1138）全树 stat + 碎 commit，debounce 只对 browser-save → 分析 20 篇 = 20 次全树 add。→ debounce 扩到 milestone；`git add <paths>` 取代 `-A .`。 [med / M]

## ⭐ Top 6（✅ 已全部施工，commit `dbf6d7f`..`b5dc066`；F1 部分）

1. ✅ **U1 确认收件箱 `review-queue` CLI**（high/S）— 系统最核心的门 pending 无出口，单点最高杠杆。
2. ✅ **D1 增量索引**（"单次扫描"零行为变更快赢）（high/S→M）— 每次分析的 latency。
3. ✅ **U2 程序仪表盘 + next**（high/M）— 修掉天天可见的空首页，兑现 navigator 承诺。
4. ⚠️ **F1 全文+排序检索**（high/M）— 内存版 ranked 全文已做；**持久化索引 + alias 扩展 deferred**。
5. ✅ **B9 确认溯源（禁 agent 自签）**（high/M）— U1 的正确性对偶。
6. ✅ **B8 计数 bug + workflow 生命周期命令**（high/S）— 真 bug，已修。

> 下一步优先级建议（未做）：**§8 B10 源归档静默失败**（数据安全）→ **§9 F1 剩余**（持久化索引）→ **§9 F2/F3/F4 闭环+图+复用溯源** → 结构性投资三件套（C1/C2/C3，随 T-GODFILE-v2）。

🎯 **最大结构性投资**：**"声明式 skill 平台"三件套 C1（KIND_REGISTRY）+ C2（CLI harness）+ C3（类型化 RecordView）**，叠在 Part A 的 T-GODFILE-v2 之上。effort 大（L），但几乎是所有新功能的前置（F5 需 C1、C6 需 C2、C4 迁移执行点需 typed record），把"加一个 kind = 改 6 处"变成"注册一个对象"。应**紧随 T-GODFILE-v2/T-FINALIZE 之后**做，作为其自然延伸而非并行分叉。

> 丢弃项：本地 embedding 语义检索（82 单元下 lexical 已够，收益随语料增长才显现，低优先 stretch）。
