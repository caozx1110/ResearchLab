# workspace-oss 优化 plan —— 第 3 轮（skills 审查后重写）

> 更新于 2026-07-04。本轮以 **skills 为核心** 做了一次对抗性审查：**23 个审查单元**（16 个 skill + navigator 拆分 2 + 6 个横切）→ **109 条原始发现** → **逐条派证伪 agent 验证** → **101 条存活、8 条驳回**。全部带 `file:line` + 裁决（CONFIRMED / PLAUSIBLE）。
> 约束（有一处松动，见下）：**skill import 面兼容**（`from research.v2/common import ...` 全部照旧——本轮已核实 **20 个 skill import 面 100% 可解析，零断裂**）。**行为保持** 不再是硬约束——审查查出若干**真实 bug**，修它们是有意的行为变更（见 §1）。
> 面向 Codex/后续施工。

---

## ✅ 本轮已定决策（2026-07-04，用户拍板）

三处原「待决策」已定,下方对应条目措辞已按此固化:

1. **执行范围 = 「修 bug + 快赢批」**：本轮批准执行 = **§1 七个真 bug** + **§3 T-ROUTE 路由补全** + **§4.1 九个 SKILL.md 文档对齐(含防漂移测试)**。**§3 的 god-file 拆分(T-GODFILE-v2)、§4 其余去重/一致性、§5 零散 均不在本轮范围**,留作后续轮次。（注:本文件本次仅更新 plan,不动代码。）
2. **wiki `add` = 保留真入库**：确认 `add`→`intake.py` 是有意行为增强,予以保留;并把 `add` 的参数契约抽成与 intake 共享的一份(消除手抄)。见 §2。
3. **B2 seed 归属 = 重建时保留空种子**：让 `rebuild_governance_catalogs` 保留 config 写的零成员 seed,不再清空;config-manager 继续管 seed 输入。见 §1 B2。

---

## 0. 现状校正（旧 plan 已过期，先纠正事实）

第 2 轮 plan 的多处前提**已被本轮审查证伪**——base 层重构其实已经落地，旧 plan 还当它没做：

| 旧 plan 断言 | 实际（本轮核实） | 裁决 |
|---|---|---|
| 「12 个计划模块一个都不存在」(§2 P0) | **5 个 base 模块已存在且已接线**：`yaml_io.py`(81) `slugs.py`(135) `ids.py`(109) `dedup.py`(43) `pdf_layout.py`(509)；`common.py:21-23` 已 `from .dedup/.slugs/.yaml_io import ...` | CONFIRMED，需改写 |
| 「T3-5 PDF 引擎未搬，paper.py 仍 1297 行」(§2 P1) | **PDF 引擎已全量搬到 `pdf_layout.py`**（`_ensure_layout_backend`/几何/聚类/裁剪/质量都在），paper.py **不再重复**这段，只 `import` | CONFIRMED，T3-5 关闭 |
| 「v2.py 2383 行 / common.py 1220 行」 | v2.py **2292** 行 / common.py **984** 行（tests 目录已建，**35 测试全过**，`retrieval.py` 已删） | 数字刷新 |

**✅ 已达成（勿重做）**：Tier 0 测试基建 + pytest.ini/requirements-dev.txt；Tier 1 死代码删除 + 文档漂移修复；base 层模块拆分（yaml_io/slugs/ids/dedup/pdf_layout）；PDF 引擎抽离。

**❌ 仍欠（本轮重点确认）**：**domain 层拆分一个都没做**——v2.py 仍是 2292 行 god-file（96 个顶层 def，`paths/records/confirm/index/backup/prefs/git_ops` 7 个 domain 模块全缺）；common.py 半重构（base 已抽离并正确 re-export，但 ~665/984 行的 domain 逻辑仍内联）。**skill 层从没被系统审过**——本轮补上，查出 101 条。

**总体健康度**：无 P0 回归、无断裂 import、无 base 符号被重复塞回 v2/common。问题集中在 ①几个真 bug ②大面积 checkpoint/finalize 不一致 ③routing 表与 SKILL.md 承诺对不上 ④SKILL.md 文档漂移 ⑤两个 god-file（v2.py/kb_browser_lib.py）。

---

## ⚠️ 1. 真实 bug —— 允许的行为变更，**优先修**（低成本高价值）

> 这些是审查查出的**正确性缺陷**，修它们必然改变可见行为——这是有意的，提交信息里说明即可。

| # | 位置 | 问题 | 裁决 | 成本 |
|---|---|---|---|---|
| **B1** | `knowledge-base-manager/scripts/kb.py:216` | `promote` 的 commit 触发逻辑**反了**：`trigger = "milestone" if auto_commit_mode != "manual" else "manual"`。而 `maybe_auto_checkpoint`（v2.py:1166）里 `trigger=="manual"` → **无条件 commit**。结果：用户配了 `manual`（不想自动提交）时，`promote` **偏偏强制提交**。修法：像其它写入方一样传 `trigger="milestone"`，让 `maybe_auto_checkpoint` 按 mode 裁决；`"manual"` 只留给显式 `git-checkpoint`。 | **CONFIRMED**（已独立复核） | 低 |
| **B2** | `research-config-manager/scripts/config.py:171-217` | `set-taxonomy-seed`/`set-pool` 写出 `member_ids` 为空的**纯 seed**；而 knowledge-base-manager 的 `rebuild-governance`→`rebuild_governance_catalogs`(v2.py:1586) 会**按 member_ids 重建**，把这些零成员 seed **静默清空**。两个 skill 抢同一份 taxonomy/pool 治理，seed 丢失。**已定修法(用户选)：让 `rebuild_governance_catalogs` 保留零成员 seed（如按 `status: seed` 或"无 record 支撑但已声明"识别并不清空），config-manager 继续管 seed 输入。** | **CONFIRMED** | 中 |
| **B3** | `method-designer/scripts/method.py:43` | 显式 `--repo-id` 被**静默忽略**：仅当该 id 已是一个 v2 repo unit 才生效，否则脚本自行另选一个 repo。用户指定被吞。 | **CONFIRMED** | 低 |
| **B4** | `repo-analyst/scripts/repo.py:363` | `confirm` 命令没清 AI 的 `information_types`，导致 `write_record` 里 `validate_write` 触发 confirmation-gate 告警（本该是「已确认」却被判「待确认」）。 | **CONFIRMED** | 低 |
| **B5** | `method-designer/scripts/method.py:160` | no-repo 分支想渲染 `pending` 占位，但该分支**不可达**，实际渲染成空。 | CONFIRMED | 低 |
| **B6** | `experiment-workbench/scripts/experiment.py:201` | run 文件名按 `glob` 计数派生，**可碰撞/覆盖**已有 run。 | CONFIRMED | 低 |
| **B7** | `discussion-archivist/scripts/archive.py:41` | 讨论文件名只由 title 派生，**同名讨论互相覆盖**。 | PLAUSIBLE | 低 |

---

## 2. wiki.py `add`（决策已定：保留）

**`wiki-adapter/scripts/wiki.py` 的 `add`**：从「只 print 占位桩」改成了**真正 subprocess 调用 `intake.py`**（wiki.py:43-59）。本轮审查复核：routing 合理、SKILL.md 与代码一致、`add` 现在名副其实。
- **已定（用户拍板）：保留**该增强,承认它是有意的行为增强(commit 说明里注明);**并把 `add` 的参数契约(`--kind/--source/--maturity/--title/--pool`)抽成 intake 与 wiki 共享的一份**,消除 wiki.py:34 处对 intake.py 参数的手抄漂移(P2, CONFIRMED)。
- 归属批次:此项属"快赢批"外的一个小改,可与 §3 T-ROUTE 一起在后续执行轮做。

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

### T-ROUTE（✅ 批次 A）：orchestrator 路由表够不到 SKILL.md 承诺的 skill
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

### 4.1 doc↔CLI 漂移（✅ 批次 A）（SKILL.md 与真实 argparse 对不上，用户会踩）
| skill | 位置 | 漂移 |
|---|---|---|
| experiment-workbench | SKILL.md:44-46 | phase 段文档给的 `outcome` 枚举 `{pass,fail}` **被 argparse 拒**（真值是 success/partial/failure）；表里点名的产物 `stats.yaml` 等**脚本从不产出**；叫 executor 把 arm 名塞进 `--classification`（schema-mismatch，实为枚举）。 |
| idea-workbench | SKILL.md:22 | 命令手册**漏 `select` / `archive`**（都是真子命令）。 |
| research-orchestrator | SKILL.md:30 | `attach-unit` / `query-program` 未文档化。 |
| paper-analyst | SKILL.md:29 | `reject` 子命令存在但只文档了 `confirm`。 |
| knowledge-base-manager | SKILL.md:55 | `index` / `git-log` 子命令未列。 |
| method-designer | method.py:105 | `--baseline` / `--risk` flag 未文档。 |
| research-config-manager | config.py:270 | SKILL.md 称 `init` 会初始化 markdown settings，但 `init` **从不写** research-settings。 |
| discussion-archivist | SKILL.md:21 | 文档称 tradeoff/open-question「必填」，CLI **不强制**。 |
| skill-evolution-advisor | SKILL.md:20 | 漏 `--stdout-prompt` / `--root`，且没说明落盘路径。 |

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

## 6. 执行顺序（第 3 轮）

> **本轮范围已定 = 「修 bug + 快赢批」**：只做下面 **批次 A**;批次 B 留后续轮次。（本次仅定 plan,不动代码。）

### ✅ 批次 A —— 本轮批准执行（低风险、当轮可跑测试验证）
1. **§1 真 bug**（B1-B7，尤其 **B1 promote 强制提交 / B2 seed 丢失**——低成本、影响用户数据/git）。每修一个跑 35 测试。B2 按已定修法：rebuild 保留零成员 seed。
2. **§3 T-ROUTE**（补 `ROUTE_HINTS`：source-intake 及其余不可达 skill + 加「值 ⊆ 真实 skill 目录」守卫测试，堵住「新 source 绕过 intake」）。
3. **§2 wiki.py add**（保留真入库 + 抽 intake/wiki 共享参数契约）。
4. **§4.1 doc 漂移 + 防漂移测试**（一次对齐 9 个 SKILL.md，加「SKILL.md 子命令 ⊆ argparse」测试）。

**批次 A 收尾**：给全量 diff + 跑 35 测试全绿 + 24 脚本编译通过。

### ⏭️ 批次 B —— 后续轮次（不在本轮范围）
5. **§3 T-GODFILE-v2 domain 拆分**（核心大重构，7 模块）：`paths→prefs→records→confirm→index→backup→git_ops`，逐模块搬、每步跑测试，v2/common 变 façade；§4.2 的 v2 内部 dup 随对应模块归位。
6. **§3 T-FINALIZE + T-CHECKPOINT**：`finalize_unit_step`/`confirm_unit` 落到 records/confirm，替换 ~26 处复制块，清死赋值 + 收敛 checkpoint 策略。
7. **§4.2-4.5 其余去重/一致性/god-file（kb_browser_lib/paper/orchestrate）+ §5 零散**（非阻塞，穿插做）。

**每个 Tier 完成先给 diff + 跑 35 测试全绿再进下一个。**

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
