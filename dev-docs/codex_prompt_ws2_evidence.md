你在开源 research-workspace 系统做 **Wave 2 · Track Evidence（原则2 证据层）**。基线=已重构并 merge 的 main（`0d67971`）。独立 git worktree 从此 HEAD 分叉。全部改完自测、逐项 commit、**不 push**。

【本 track 拥有的文件（只动这些）】
- `.agents/lib/research/evidence.py`（重构已建的 additive stub：现有 `EVIDENCE_SCHEMA` + `verify_claim_evidence(claim, unit_dir)` 返回 `[]`——你把它做实）
- `.agents/lib/research/SCHEMAS.md`（已有「Evidence / Claims」节，可扩展）
- 新增自己的测试到 `.agents/lib/research/tests/`
**不要碰** `sources.py` / `confirm.py` / `intake.py` / `knowledge-base-manager`（属其它并行 track）。records.py 只读不改（需要复用其 core_content 结构就 import）。

【设计依据（先读，锁定规格）】`temp/SYSTEM_DESIGN_SSOT.md` Part 2 原则2 的 canonical schema 块（claim + evidence_refs + 逐字验证 + judgement 空据不得 confirmed）。**以那段 YAML 为准，一字不差。**

【红线】
1. 绝不碰 kb/。测试在临时目录用合成 fixture。
2. 本 track **不改 confirmation gate 行为**（gate 联动由并行的 Gate track 做）；你只提供 `verify_claim_evidence` 这个可被调用的纯函数 + claim 校验 helper。保持 evidence.py 对现有行为仍是 additive（没有调用方时零影响）。
3. 不 push。

============================================================
要做的
============================================================
1. **把 `verify_claim_evidence(claim, unit_dir)` 做实**：对 claim 的每个 evidence_ref：
   - 加载 `artifact`（unit 内相对路径：parse-cache.yaml / note.md / source 文件）。
   - 校验 `quote` 是该 artifact 文本的**逐字子串**（先做**空白归一化**：连续空白折叠成单空格、strip；大小写敏感保留）。命中=grounded，未命中=返回一条 violation（含 claim id + artifact + 缺失的 quote 摘要）。
   - `locator` 是定位提示（PDF `page=N|section|para` / HTML `section|anchor`）：**至少**校验 quote 存在；若能廉价地按 locator 缩小到对应 page/section 再校验更好（parse-cache 有 per-page 结构时用上），但 quote 逐字命中是硬性判据。
2. **claim 校验 helper**：`validate_claims(claims: list) -> list[str]`：校验每条 claim 结构合法（id/text/claim_type/confirmation_status/evidence_refs 齐全，claim_type ∈ 枚举），且 judgement-class（`inference`/`evaluation`）claim 的 `evidence_refs` **非空**（空 → violation，为 Gate track 的"空据不得 confirmed"提供判据函数，但你不在这里改 gate）。
3. **attach helper（可选但推荐）**：给一个 record 的 note/screening payload 附加 `claims` 列表的读写 helper，保持 schema 与 SSOT 一致。
4. **SCHEMAS.md**：把 evidence/claims 的字段语义、locator 两套（PDF/HTML）、逐字验证规则、空据规则写全（当前节可能只有 YAML）。
5. **不接分析器**（analyzer 集成是 Wave 3，别动 paper.py 等）。本 track 交付的是**可被调用、可测试的证据层基元 + 校验函数**。

============================================================
验证（全绿再交，逐条给实际输出）
============================================================
1. `python -m compileall .agents/lib` 通过。
2. 全量 `pytest` 仍全绿；新增测试覆盖：逐字命中/未命中、空白归一化、judgement 空据被拒、fact-class 空据允许、locator 缩小校验（若实现）。
3. **合成 fixture 演示**：造一个临时 unit（parse-cache 含已知文本），一条 quote 命中的 claim + 一条编造 quote 的 claim，`verify_claim_evidence` 分别返回 []（grounded）和一条 violation。贴实测。
4. `verify_claim_evidence({}, None)` 等退化输入不崩（返回空/合理 violation）。
5. evidence.py 仍是 additive：没有调用方时，全量测试行为与重构后一致（gate/analyzer 零影响）。
6. kb/ 零改动。

【交付】逐项 commit、不 push。附：逐字验证的合成演示（命中 + 未命中 + judgement 空据被拒三例）、SCHEMAS.md evidence 节最终内容、以及你对"逐字太严/太松"边界的实测判断（B3：短逐字片段够不够、要不要容忍标点差异）。
