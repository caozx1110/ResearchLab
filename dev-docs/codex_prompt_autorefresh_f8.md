你在开源 research-workspace 系统做**自动化打磨批**（A: note verify 后自动跑安全后续步；B: F8 PDF 标题截断）。基线=main 当前 HEAD（先 sync）。独立 git worktree。小步提交，DO NOT push。

**STEP 0 — sync base**：`git log --oneline -1` + `wc -l .agents/lib/research/core.py`（~56）+ `ls .agents/lib/research/{evidence,confirm,sources,prefs}.py`。正确基线 main **f865802**（含 F-a 修复、doc 重构；285 测试绿）。不符 → `git reset --hard f865802` 再核对。spec/design 从主仓 `/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/temp/` 读（gitignore）。设计依据：`temp/SYSTEM_DESIGN_SSOT.md` §3.2 的"✅ 决策（自动化打磨，2026-07-11）"那条。

**本 track 拥有的文件（只动这些）**：`.agents/skills/paper-analyst/scripts/paper.py`（A）、`.agents/lib/research/sources.py`（B，仅 PDF 标题抽取那段）、新增测试。**不碰** evidence/confirm/records.py、其它 skill、kb/（真实用户数据，测试用临时目录/合成 fixture）。

============================================================
A — note verify 后自动跑安全后续步（自动化，功能变更，SSOT 已锁）
============================================================
现状：`complete-note --phase verify` 成功持久化后只调 `_finalize_post_actions`（build_index + checkpoint），**不跑** refresh-structure / extract-figures，用户得手敲。prefs 已存在（`prefs.py`：`auto_refresh_structure_after_note` 默认 True、`auto_extract_figures_after_note` 默认 False），只是没被消费。

要做（在 paper.py 的 complete-note verify 成功分支，`_finalize_post_actions` 前后）：
1. 读 paper preferences（该文件已有获取 pref 的方式，复用）。
2. 若 `auto_refresh_structure_after_note` 为 true → **自动执行 refresh-structure 的逻辑**（复用现有 refresh-structure 的实现：从**现有 cache** detect_structure 写 structure.yaml；**绝不重解析/覆盖 cache**——F-a 不变量：raw+全量 parse-cache 不可变，见 SSOT 原则2）。
3. 若 `auto_extract_figures_after_note` 为 true → 自动执行 extract-figures 逻辑（需 PDF backend；缺 backend 或非 PDF 源 → **跳过 + stdout 提示，不报错、不中断**）。
4. **受 autonomy 阀门约束**：读 `autonomy.auto_execute_scope`（∩ GOVERNANCE_MAX_AUTO_STEPS）；refresh 对应 `refresh`、figures 对应 `generate-note`/相应安全步 token——只有在有效 scope 内才自动跑；不在 scope 内 → 不自动，改在 stdout 输出 NEXT FOR AGENT 导航让 agent 决定。
5. **仍不自动**：不自动 verify（本就是 verify 分支）、不自动 confirm。`--defer-post-actions` 传入时，这些自动后续步也一并 defer（与现有 defer 语义一致）。
6. stdout 如实反映做了什么：`[auto] refresh-structure 已跑`、`[skip] extract-figures：无 PDF backend` 之类。

**实现取向**：优先复用已有的 refresh-structure / extract-figures 命令实现（抽成可内部调用的函数，或在 verify 成功后 dispatch 到同逻辑），别复制粘贴整段。别改 refresh/figures 本身的行为。

============================================================
B — F8：PDF 标题被截断（只取首行）
============================================================
现状：`sources.py:446-452`，当 PDF 元数据无嵌入标题时，从 first_page 逐行找第一个 3-20 词的行当标题就 `break`——多行标题只取首行（AR-FB："Finer Behavioral Foundation Models via" 截断，丢了"Auto-Regressive Features and Advantage Weighting"）。

修法：不要取第一符合行就 break。**收集开头连续的标题行**（从首个合格行起，继续并入后续行，直到遇到：作者行/机构行/含 http/arxiv:/以 abstract 开头/空行/明显非标题的短行），再 `" ".join(...)` 成完整标题。可参考 `common.py` 的 `_title_lines_from_pdf` 的多行收集思路（但别 import 跨层耦合，就地实现一个小 helper）。保留"嵌入元数据标题 ≥3 词则优先用"的现有逻辑不动。

============================================================
验证（全绿再交，逐条给实际输出）
============================================================
1. `compileall` + `paper.py --help` 通过。
2. 全量 `pytest`（tmp venv：`python3 -m venv .venv && .venv/bin/pip install pyyaml pytest pymupdf4llm`）全绿，新增测试只增。**注意 F-a 回归**：跑 `test_refresh_preserves_cache.py` 确认仍绿（你自动跑 refresh 后 cache 不能被截断）。
3. **A 端到端（临时 kb + 真 PDF，NEVER 真 kb/）**：`kb ingest` + 填 note + `complete-note --phase verify`，观察 verify 成功后**自动跑了 refresh-structure**（structure.yaml 生成/更新）、**parse-cache 页数不变**（F-a 不变量）；default pref 下 figures 不自动（auto_extract 默认 false）。贴 stdout + cache 页数 before/after。
4. **autonomy 收窄**：把 auto_execute_scope 去掉 refresh → verify 后不自动 refresh、改出 NEXT FOR AGENT 导航。贴证据。
5. **B（F8）**：对 AR-FB PDF 跑入库，record `title` 是完整多行标题（"...Advantage Weighting"），不再截断于"via"。贴 before/after。
6. kb/ 零改动（`git status`）。

【交付】小步 commit、不 push。附：A 的 verify-后-自动-refresh stdout + cache 页数不变证据 + autonomy 收窄证据、B 的标题 before/after、F-a 回归测试仍绿、pytest 数。**若 autonomy token 到 refresh/figures 的映射不确定，停下说明，别乱放行**（安全自动步范围别扩到 verify/confirm）。
