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

---
---

# Part C —— 第 5 轮：UX / 易用性（"用户手动操作太多"专项）

> 2026-07-04。7 个真实用户旅程的友好度审计（onboarding / add-source / idea / experiment / confirmation / input / nl-driven）→ 49 friction + 50 提案。用户直觉「对用户还不是特别友好，手动操作太多」**成立且可精确定位**——根因不是"步骤本身多"，而是**没默认值、没模糊解析、没批量、没成链、没执行环**，把本可省略的输入和往返压给了用户/agent。

## 13. 诊断（已核实的硬证据）

- **确认无批量**：全系统零 batch/bulk confirm（`--all` 只在 `govern`，✅核实）。一周 ~18 待确认单元 = 18 次调用 × 3 个无默认必填（exact-id + `--confirmed-by` + `--evidence`）= **54 个必填项**。更糟：paper 有 4 个写点（screen/complete-note/extract-figures/refresh-structure，`paper.py:658,686,730,759`）每步都把 record 翻回 pending → 确认数是 **units × steps**。
- **exact hash id 必须手抄跨 skill**：`locate_record`(v2.py:1534) **只接受精确 id**（✅核实，`p-openvla-open` 缺 hash 直接 not found，`last` 也失败）；`intake add` 只 print 路径、不 print 裸 id/confirm 命令 → agent 每次抠 hash 粘到另一个 skill。
- **最推荐的"起手式"对空 kb 瞎**：README/GETTING_STARTED 主推「判断我该做哪步」→ `orchestrate next/dashboard`，但空 kb 只 print「暂无」（只遍历 program 的 active_unit_ids，无视散落单元）。且 **onboarding 文档从不提 `kb.py init`**（✅核实 0 命中），首次用户撞空页。
- **"就直接说话"断在最后一公里**：`next/dashboard/route` 都只 print、不执行、不给可运行命令；agent 每推进一步要 5-6 次往返（读状态→解析→查 id→映射 skill/subcommand/flags→执行）。
- **已经做对的（不要动）**：`review-queue` 方向对（但只列不清、留占位符）；`orchestrate next` 入口设计对；**确认门控本身（不许自签、必留 evidence）是正确治理红线**——问题是它把"人的一次授权"变成"N 次重复输入"。

## 14. 改进（按 userValue↓/effort↑，分 4 类负担；⚡=quick-win）

**(B) 输入负担**
- **B1 `locate_record` 模糊解析（exact→唯一 prefix→title 子串→`last`/`current`）**[high/M]——单点改动惠及**所有** per-unit 命令，消灭"先查 id"往返。**最高杠杆。**
- **B2 ⚡ 所有输出 print 可直接运行的命令**（query/review-queue/next/intake 把建议渲染成已填真实 id 的整行）[high/S]。
- **B3 ⚡ `intake add` 末尾 print 现成 confirm 命令**（id 已在 record，复用 kb.py confirm_command）[high/S]。
- **B4 ⚡ confirm 的 `--evidence`/`--confirmed-by` 走默认**（evidence 默认单元 canonical note；confirmed-by 默认 config 身份）[high/S]。
- **B5 top-level dispatcher + 位置参数 id**（`research paper confirm openvla`，砍 52 字符前缀）[high/M]；**B6 ⚡ 从 URL/扩展名推断 `--kind`**[med/S]；**B7 缺必填 flag 时 TTY 交互补全**[med/M]。

**(A) 决策/确认负担**
- **A1 批量确认 `kb.py confirm --all-reviewed`**（遍历 review-queue 各调 apply_confirmation，N→1）[high/M]。
- **A2 `review-queue --confirm` 就地清空**（列出的同一命令加 `--confirm` 即清，而非 print 占位再重打）[high/M]。
- **A3 ⚡ confirmed-by 走 config 默认**（`identity.default_confirmed_by`；evidence 仍强制留溯源）[med/S]。
- **A4 ⚡ `select/select-best` 与事实门控解耦**（轻量选择记 `status=selected` 免 provenance，只在 promote-to-method 边界要 evidence）[high/S]。
- **A5 ⚡ confirm 幂等**（仿 repo：复位 AI info_types + 清子状态，止住每次后续写的 validate_write WARN 噪音）[med/S]；**A6 分段/诊断级确认粒度**（gate 落到 diagnosis/section 而非整条 record）[med/L]。

**(C) 步骤/编排负担**
- **C1 `orchestrate auto` 真正的 status→recommend→execute 执行环**（读 dashboard→解析成 skill+subcommand+已解析 id→执行→循环；**遇 pending 即停交回用户，绝不自签**）[high/L]——把"万能起手式"从愿望变成一条命令。
- **C2 `next/dashboard` 覆盖 loose unit + 输出可运行命令**（无 program 时也扫散落单元）[high/M]。
- **C3 一命令 intake→confirm 链**（`intake add --confirm`，人决策仍显式但零 id 往返）[high/M]。
- **C4 `idea iterate` 一命令多候选**（串 generate→analyze→review，停在评审卡片让人挑，~9→1）[high/M]。
- **C5 让 experiment matrix 可执行**（`experiment plan --from-matrix`，预填 title/goal/metrics/gate，死数据复活）[high/M]。
- **C6 ⚡ plan 携带 metric schema，log-run 只填值**（`--metric success_rate=0.91`）[high/S]；**C7 ⚡ log-run/diagnose 缺省继承 hypothesis/program-id**[med/S]；**C9 ⚡ 合并 analyze 进 review**[med/S]；**C11 让排名变真或不假装排名**（当前候选恒 total=6，select-best 实为 hash 字典序）[high/L]；**C12 ⚡ `select --rank N` + `idea list`**[med/S]；**C10 `orchestrate apply-feedback` 一命令一 cycle**[high/L]；**C13 repo/blog 纳入 intake 自动分析链**[med/M]。

**(D) 认知负担**
- **D1 ⚡ 已修**：GETTING_STARTED 补「第 0 步：先 `kb.py init`」（本轮已做）。
- **D2 ⚡ 空 kb 时 next/dashboard 给 onboarding 建议**（"KB 为空，第一步 intake add 一篇论文"而非"暂无"）[high/S]。
- **D3 `kb.py quickstart` 一命令零配置**（workspace+config+profile+index+页面，6 命令 4 skill→1）[high/M]；**D4 ⚡ 把 config bootstrap 折进 kb init**（顺带建 user-profile）[med/S]。
- **D5 环境 doctor + 真实 requirements**（`config.py doctor` 查 python/yaml/pdf 后端 + 补 pypdf；intake 缺后端一行告警而非静默空笔记）[high/M]。
- **D6 ⚡ navigate/browser 自愈 index 链接**（refresh 先 build_index 保证 `kb/index.md` 存在，去死链）[med/S]；**D7 ⚡ confirm 传播到子产物状态**[med/S]；**D8 URL paper 源抓取并解析 PDF**[med/M]。

## 15. ⭐ Top 5「最能让用户省事」+ 北极星

1. **B1 `locate_record` 模糊/last/title 解析** —— 全系统每条 per-unit 命令不再"先查 id"、不再拼错 hash 硬失败。所有 lens 反复指向的同一根因，杠杆最高。
2. **A1+A2 批量确认 / review-queue 就地清** —— 兑现"把我刚看的这几篇都确认了"，一周 18 次授权压成 1 次。
3. **B4+A3 confirm evidence/confirmed-by 走默认** —— 保留"显式确认+不自签"治理，同时每次确认必填从 3→最多 1。
4. **C1+C2 `orchestrate auto` 执行环 + 覆盖 loose unit** —— 让"判断我该做哪步并直接执行"真的成链，遇确认即停；单次推进从 5-6 往返降到 1。
5. **B2+B3 处处输出可直接运行的命令** —— 低成本 quick-win，把"眼看-抠 hash-重打"变成复制即跑。

🎯 **北极星**：**让"下一步"成为系统第一等公民，而不是让用户拼命令。** 打通一条 **读状态→推荐一步→用模糊/默认解析好一切参数→执行→只在需要人拍板处（确认 AI judgement）停下来问** 的闭环：`orchestrate auto` 作执行引擎、`locate_record` 模糊解析消灭 id 转抄、config 默认值 + 批量确认把"一次授权"从"N 次输入"里解放。**治理红线（不自签、必留 evidence）不动——它恰应是这条流水线上唯一需要用户亲自介入的闸口。**

> 建议施工顺序（都低耦合、可独立落地）：先 quick-win 批（B2/B3/B4/A3/A4/A5/C6/C7/D2/D4/D6，多为 S）→ 再 B1（模糊解析，中杠杆最高）→ 再 A1/A2（批量确认）→ 再 C1/C2（执行环）。

---
---

## 16. Top 5 已实现 + review 修复 + UX 模拟采纳项（交 Codex）

> Top 5（B1/B2B3/B4A3/A1A2/C1C2）已由 Codex 实现（commit `85a8df9`..`89ebd43`，74 测试过）。对抗性 review（5/6 单元 + 人工核验）结论：**治理红线守住**（`--evidence` 全路径仍强制；`orchestrate auto --execute` 双闸门永不自动 confirm/select）。以下是 review 查出的**必修项**（R 组）+ 一次端到端**用户模拟**（`docs/RESEARCH_SKILLS_UX_SIMULATION_2026-07-04.md`）采纳的改进（S 组）。

### R 组 —— 修 Top-5 实现的缺陷（本批交 Codex）
- **R1（回归，should-fix）** `_wikilink_target_exists`(v2.py:1700) 现在走了 B1 加宽后的模糊 `locate_record` → doctor/lint 查断链会把**部分/子串匹配**误判为"存在"。修：给 `locate_record` 加 `fuzzy: bool = True` 形参，wikilink/doctor 路径用 `fuzzy=False`（只走 exact + legacy）。已人工坐实。
- **R2（一致性，should-fix）** `apply_batch_confirmation`(kb.py:150) 与 5 个 analyst 单确认不一致：**没清 AI `information_types`→fact、没设 `status=active`、没 `append_history`**，且 `confirm --id`/`--all-reviewed` **无 pending 守卫**（能误翻 `rejected`/已确认 record）。修：抽一个共享 `confirm_unit(record, kind, ...)`（收敛 info_types 复位 + status + history + apply_confirmation），单/批量都走它；批量只对 `pending_user_confirmation` 生效，非 pending 跳过并提示。
- **R3（B1 nits）** `last`/`current` 分支被 prefix/title 抢先（title 含 "last" 即不可达）→ 应在 prefix/title 之前先解析保留字；id 前缀匹配大小写不一致（应统一 casefold）；删死参 `mode`（`_resolve_unique_record_reference`）。
- **R4（去重）** `confirm_command`/`shell_command` 在 kb.py:71,91 / orchestrate.py:101,118 / intake.py:54,64 **复制了 3 份** → 抽到 `research.common`/`research.v2` 单一 helper。
- **R5（doc）** SCHEMAS.md:26 仍写"确认必须提供非空 `--confirmed-by`"——B4/A3 后 confirmer 可来自 `identity.default_confirmed_by`；更新措辞（`--confirmed-by` 或 config 默认二选一，`--evidence` 仍强制）。
- **R6（nit）** `--all-reviewed` 实际只确认 review-queue 前 `--limit`(默认 50) 条，">50 pending" 时名不副实 → 默认 unbounded 或打印 "已确认 X / 剩 Y，请重跑"。

### S 组 —— 用户模拟采纳项（P0/P1 本批交 Codex；P2 记录为下一批）
- **S1（P0，本批）** `idea.py select`/`select-best` 把 idea 整条写成 `confirmation_status=confirmed`，但 idea 含 AI novelty/feasibility（inference/evaluation）→ validate_write 警告，且**混淆"选择推进"与"确认 AI 判断"**。修：selection 只置 `status=selected`（记 selection provenance），**内容 `confirmation_status` 保持 `pending_user_confirmation`**；`review-queue` 继续列出 selected-but-content-pending 的 idea 提示后续确认。（= 早前 roadmap A4。）
- **S2（P1 安全，本批）** 所有写脚本靠 `Path(__file__).resolve()` 找 root，`/tmp` 软链 `.agents` 会解析回真实仓库 → **误写真实 `kb/`**。修：所有 v2 脚本支持显式 `--root` / `RESEARCH_PROJECT_ROOT`；写命令启动时打印 resolved project root + kb root；`kb.py init`/`config.py init` 等高影响命令在 `cwd` 与 resolved root 不一致时醒目提示。
- **S3（P1，下一批）** `report.py weekly` 默认输出偏事件索引，非自包含周报。→ polished renderer：按 背景/输入材料/阶段进展/关键证据/阻塞/风险/下周计划/provenance 聚合，每条标 evidence level（source fact / run fact / AI inference / pending decision），event dump 降为 appendix。（= roadmap U4，模拟证实，升级。）
- **S4（P1，下一批）** `research-navigator current-state` 不够"下一步导向"。→ 每个 active program 展示 latest report / top blocking evidence / top open question / next action / pending confirmations；reading-list 也列关联 repo/idea/experiment；`paper-writing` stage 优先展示 report materials。（= roadmap U2/U3。）
- **S5（P2，下一批）** `literature-synthesizer` 召回偏保守（成功但 0/1 命中）→ survey/review 加 strict/fuzzy（默认 fuzzy，复用已恢复的 `rank_records`），空结果时解释过滤条件 + 列 pool 内未命中 top items。
- **S6（P2，下一批）** paper note `draft` 名实不符 + `reading_status` 不同步 → 区分 `scaffold`/`extractive-draft`/`analysis-draft`；`complete-note` 后同步 `reading_status`；note 顶部标读取覆盖范围（metadata / parse-cache / full PDF / manual excerpt）。
- **S7（P2，下一批）** repo capability 缺"资源型 repo"标注 → `repo-analyst map-capability` 加 repo type（paper-page/asset-only/code-release/training-ready/eval-ready）；`method-designer` 选到无 entrypoints/training/eval 的 repo 时把 repo-choice 风险升为 blocking evidence（避免"到实验阶段才发现 repo 当不了 baseline host"）。

> **本批交 Codex 范围** = R1-R6 + S1 + S2（review 必修 + 两个 P0/P1-安全）。S3-S7 已采纳，作为下一批。**约束**：治理红线不动（`--evidence` 强制、auto 不自签、S1 保持内容 pending）；import 面兼容；每项加测试、每步跑 `pytest -q`；逐项单独 commit。

---

## 17. 修复批 review 结论 + 收尾项（F 组，交 Codex）

> R1-R6+S1+S2 已实现（commit `ca40b87`..`a6ac697`，90 测试过）。对抗性 review（7 单元 + 逐条验证）：**11 findings，0 blocker，治理红线经验证守住**（`--evidence` 全路径强制含批量、auto 不自签、idea select 保持内容 pending 均已核实）。R1/R3 clean SHIP，其余 SHIP_WITH_NITS。以下收尾项：

- **F1（should-fix，安全，CONFIRMED）** `orchestrate auto` 的 S2 root 安全**未覆盖自身子进程**：`execute_auto_plan`(orchestrate.py:317) `subprocess.run(..., cwd=root)` 既不带 `--root` 也不设 `RESEARCH_PROJECT_ROOT` env → 子脚本各自从 `Path(__file__).resolve()` 重算 root，故 `auto --root /sandbox --execute` 会把 writing safe-step 写到**真实仓库**（除非另外 export env）。非红线破坏（safe steps 无 confirm/select），但 S2 沙箱安全在自己的 fan-out 上漏了。修：给 command_parts 追加 `--root <root>` 且/或 `subprocess.run(..., env={**os.environ, "RESEARCH_PROJECT_ROOT": str(root)})`。加子进程 root 传递测试。
- **F2（should-fix，一致性，PLAUSIBLE）** 6 个 kb-browser 写脚本（build/open/serve/status/stop_kb_browser.py）暴露的是 `--project-root` 而非 `--root`，走并行 helper `kb_browser_lib.project_root_from_script`。env 覆盖已生效（fall through 到共享 `find_project_root`），但 `--root` flag 会 argparse 报错 → 用户照搬 `--root` 会踩空回落到脆弱默认。修：给这些脚本加 `--root`（alias `--project-root`）走 `add_project_root_argument`，或文档统一说明 env 是 navigator 子系统的覆盖入口。
- **F3（should-fix，治理测试，CONFIRMED）** 治理红线「`kb.py review-queue --confirm` 无 `--evidence` 时在任何写入前被拒」**无端到端测试**（其 argparse `--evidence` 是 `default=[]` 而非 required，仅靠 `confirm_unit→apply_confirmation→require_confirmation_provenance` 运行时拦截；行为经验证正确但无护栏）。修：加测试——写一个 pending record，`apply_batch_confirmation(root, [rec], confirmed_by='x', evidence=[])`（及 CLI `review-queue --confirm` 无 evidence）断言 raise `--evidence` 且盘上 record 仍 `pending_user_confirmation`（无半写）。
- **F4（nit，测试补强）** ①R4 的 3 个 shared-helper 测试是同义反复（`wrapper(record)==shared(record)`）→ 改为断言**具体渲染的命令串**（脚本路径+id flag+`${RESEARCH_CONFIRM_EVIDENCE:?...}` 占位符）以真正锁字节输出；②S1 的 `test_review_queue_lists_selected_ideas_with_pending_content` 手写 record、没驱动 `idea.py select` → 改为端到端跑 select 再断言进 review-queue（或删，因 `test_idea_selection.py` 已覆盖核心）；③S2 加"符号链接威胁模型"测试（`.agents` symlink 指向另一 fake repo，断言 `--root`/env 写到 sandbox 而非 symlink 目标，且覆盖 write 命令而非仅 init）。

> **交 Codex 范围** = F1+F2+F3（should-fix：补全 S2 安全的 fan-out + flag 一致性 + 锁治理红线测试）+ F4（测试补强）。约束同上：治理红线不动、import 面兼容、每项跑测试、逐项 commit。被 review 驳回 2 条（不做）。

---
---

# Part D —— 第 6 轮：经验/skill-演化记忆机制（§18，已与用户敲定）

## 18. learnings 记忆机制（扩展 skill-evolution-advisor）

> 目标：出错/走弯路/被用户纠正的**当下轻量记一笔**，服务两件事——① 帮 skill 后续迭代；② 让 agent 记住用户习惯与曾经的坑。与用户讨论敲定的方案（2026-07-05）。**核心边界：agent 绝不据此自动改 skill——skill 问题只记录，由用户阅读后决定是否优化。**

### 归属
扩展现有 `skill-evolution-advisor`（**保留目录名/skill 名**，避免牵动 openai.yaml/路由/文档；只拓宽 SKILL.md description 为"经验 + skill 演化记忆"）。已有的 `create_retrospective.py`（深度事后复盘）保留不动，新增轻量 capture/recall/promote。

### 存储
`kb/memory/learnings.yaml`（append-only）。条目：
```yaml
- id: lrn-<YYYYMMDD>-NNN
  created_at: ''                 # UTC iso
  category: skill-defect | user-preference | recurring-issue
  text: ""                       # 自由文本，一句话
  source: agent | user           # agent 自省 vs 用户指出
  skill: ""                      # 可选，涉及的 skill
  context: ""                    # 可选
  status: pending | confirmed | dismissed   # 沿用确认门控
  occurrences: 1                 # 相似条目命中则 +1，不新增行
  last_seen_at: ''
```
（既有 `kb/memory/skill-evolution/retrospectives/` 不变。）

### 命令（加到 skill-evolution-advisor 脚本，或同目录新脚本 `learnings.py`）
- `log --category <c> --text "..." [--source agent|user] [--skill X] [--context ...]`：轻量捕获；对已有相似条目（同 category + 文本近似）**bump occurrences + last_seen_at**，否则新增，默认 `status=pending`。
- `recall [--kind prefs|gotchas|defects|all] [--limit N]`：打印**确认过的** user-preference（习惯）+ recurring-issue（坑）摘要；`--kind defects` 列**待你审的 skill 问题**（按 occurrences 降序，复发的顶到前面）。供会话开始读一眼。
- `promote --id <id>`：**由用户确认**把一条 user-preference 提升进 `runtime-preferences.yaml` 的 `learned_preferences` 块（agent 已会读的结构化配置，自动生效），并把该 learning 置 `confirmed`。
- `review --id <id> --status confirmed|dismissed`：用户对 pending 条目拍板。

### 分流（两类受众）
- **`skill-defect` → 只记录、给用户审**。⚠️ **agent 不得据此改 skill**。`occurrences` 只提升可见度（"坑了你 N 次"），仍只供用户决定。用户可 `recall --kind defects` 阅读；需要时**用户**自己决定导入 OPTIMIZATION_PLAN 优化——agent 不自动导。
- **`user-preference` / `recurring-issue` → agent 记忆**：确认后进结构化配置（习惯）或作为"已知坑"在 recall 摘要出现。

### 召回半环（补上系统当前完全缺失的一半）
1. **提升进结构化配置**：确认的 user-preference → `runtime-preferences.yaml: learned_preferences`。
2. **会话开始 recall 摘要**：`navigate refresh` / `current-state` 读 `recall --kind all` 的紧凑摘要（已知习惯 + 已知坑 + 待审 skill 问题计数）；AGENTS.md 加一条：会话开始读一眼 recall。
3. ❌ **不自动升级、不自动动 skill**（用户明确要求）。

### 触发
手动 + agent 自判。AGENTS.md 加一条习惯指令：**走弯路 / 被用户纠正时 `log` 一笔；skill 问题只记不改**。**无 hook**（"什么算错"难定义，易噪）。

### 确认门控（与系统一致）
捕获的是 AI 对"用户/系统"的**推断** → 默认 `pending`；用户 `review --confirmed` / `promote` 后才生效/被 agent 遵守，`dismissed` 归档。防止 agent 把错误假设当真。

### 验收
新增 capture/recall/promote/review 各带测试；`kb/memory/learnings.yaml` schema 写进 SCHEMAS.md；`navigate` 读 recall 的接线有测试；AGENTS.md + skill-evolution-advisor/SKILL.md 更新。import 面兼容、逐项 commit。

---

## 19. 遗留工作 necessity 分诊（2026-07-05，本轮只做 DO-NOW，其余留用户确认）

> 用户指示：布置前先审必要性；只做**必须修**或**纯正向收益低风险**；不确定的留给用户。以下是对 plan 全部遗留项的分诊。

### ✅ DO-NOW（本轮交 Codex：must-fix + 纯正向、零/低行为变更）
- **§18 记忆机制**（用户明确要做）。
- **§5 死代码清理**（纯负 diff、零行为变更）：v2.py 无用 import（:40）+ `figure_extraction_mode` 恒常量 flag（:467）+ compact_unit_ids 冗余守卫（:2184）；common.py `load_yaml` 死参 `allow_simple_fallback` + 2 处 `=True` 调用 + 孤儿 import；idea.py 恒真 `if not bundle_id`；kb_browser_lib.py 无用 os/shutil/re；open_kb_browser.py 无用 `import sys`；serve_kb_browser.py 无用 `rel`。**（先核实仍存在再删。）**
- **§5 测试补强**（纯新增）：`validate_write` 默认 env 分支、`detect_duplicate` 返回 None、`is_canonical_unit_id` 拒绝分支——**若尚未覆盖**。
- **§4.4 needs_human_confirmation 同步**（= C8 的 2 行）：`normalize_record_schema` 同步该字段与 confirmation_status（或改 SCHEMAS 注释）——纯一致性，低风险。
- **B10 的"不再静默"半边**（must-fix 的安全子集）：`backup_source` 对无法归档的 binary/PDF 源**返回/打印显式 warning**，不再 `except: file_hash=''` 吞掉。⚠️ **只做"停止静默"，不做"实际下载 PDF"**（下载有网络/磁盘副作用，属 HOLD）。
- **§5 error-handling 小修**（低风险）：experiment.py `parse_metrics` 丢弃无 `=` 的 `--metric` 时告警；orchestrate.py status 无守卫 `['key']`；serve_kb_browser.py PUT /api/file 捕获 OSError。

### ⏸️ HOLD（留用户确认——大重构 / 新功能 / 有争议的行为变更）
- **T-GODFILE-v2**（v2.py 7 模块拆分）、**T-FINALIZE**（finalize_unit_step——且刚硬化过确认流，改动有回归风险）、**T-CHECKPOINT**：大重构，留确认。
- **C1/C2/C3**（KIND_REGISTRY / CLI harness / 类型化 RecordView）：结构性大投资，留确认。
- **F2-F5**（gap→idea 闭环 / backlink 图 / reuse_flags→类型化边 / dataset kind）：新功能、改 schema，留确认。
- **S3-S7**（周报 renderer / navigator 下一步 / synthesizer 召回 / paper note 覆盖 / repo readiness）：功能增强，留确认。
- **D3 quickstart / D5 doctor / D8 URL PDF 抓取 / B10 下载半边**：新命令或网络/磁盘副作用，留确认。
- **§4.5 god-file 拆分（kb_browser_lib/paper/orchestrate）**：结构重构，留确认。
- **B8 workflow 生命周期命令的"补 answer/resolve/drop"**（若上一轮只修了计数、未加命令）：功能新增，留确认核实。
