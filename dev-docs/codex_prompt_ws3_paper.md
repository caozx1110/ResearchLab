你在开源 research-workspace 系统做 **Wave 3 · Track Paper-Analyst（3.2 论文分析器重定位）**。基线=已完成三地基的 main（`362dcb2`：重构 + evidence.py + confirm.py 空心门 + sources.py 双源，228 测试绿）。独立 git worktree。**commit-per-piece（小步提交，本任务前序 track 曾遇瞬时基建故障，小步提交保命）**，DO NOT push。

**STEP 0 — sync base（关键）**：worktree 可能开在过时旧 commit。先 `git log --oneline -1` + `wc -l .agents/lib/research/core.py`（应 ~56）+ `ls .agents/lib/research/{evidence,confirm,sources}.py`。正确基线是 main **362dcb2**（core.py 56 行 façade；evidence/confirm/sources 都在；228 测试）。若不符 → `git reset --hard 362dcb2` 再核对，然后才动手。spec/design 文档 gitignore，从主仓 `/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/temp/` 读。

============================================================
⚠️ 最重要：你在建"机器"，不是建"理解"（读三遍）
============================================================
这套系统的第一性原理（SSOT 原则1）：**理解来自 agent，脚本只搬运 + 验证。** 当前 `paper.py` 的病根就是它试图用 Python "理解"论文——`screening_payload` 用关键词命中数打分（`_grade(len(result_hits))` 附近）、`note_template` 生成模板占位。**你绝不能把它换成"更聪明的 Python 启发式"——那是同一个病。**

你的产物是**脚手架 + 证据验证 + 门控接线**，让一个 **runtime agent**（在会话里）填入真正的理解。脚本负责：解析源、产出"待填结构"、校验 agent 填入的每条判断带合法 evidence、过实质门、落盘。**脚本不产出任何"论文说了什么"的判断。**

一个判据：你写的任何函数，如果换一篇论文喂进去、不经过 agent，就能吐出"novelty=strong"这类判断——那就是错的，删掉。

============================================================
可用的已合并 API（直接调，别重造）
============================================================
- `research.evidence`：`verify_claim_evidence(claim, unit_dir)->list[str]`（逐字校验 quote 在 artifact 里）、`validate_claims(claims)->list[str]`（结构+judgement空据拒）、`attach_claims(payload, claims)`、`read_claims(payload)`、`as_claim_dict(claim)`。
- `research.sources`：`write_parse_cache(unit_dir, unit_id, source_info)`、`source_record_fields(...)`（双源已产 parse-cache，含 `locator_kind` = page（PDF）/ section|anchor（HTML））。
- `research.confirm`：`has_substantive_content(record, kind)`、`confirmation_track(record)`（论文 core_content 全空=hollow=判断轨→需实质确认）。

============================================================
本 track 拥有的文件（只动这些）
============================================================
- `.agents/skills/paper-analyst/scripts/paper.py`
- `.agents/skills/paper-analyst/SKILL.md`
- 新增测试到 `.agents/lib/research/tests/`
**不碰** evidence.py/confirm.py/sources.py/records.py（只读 import）、intake.py（source-intake track 的，双源已接好）、其它 skill。**绝不碰 kb/。**

============================================================
要做的（把 analyzer 从"填模板"改成"备料+验证"）
============================================================
1. **`screen`（初筛）改为 agent-driven（SSOT 3.2：完全交 agent）**：
   - 删除关键词命中数打分（`_grade`/`_match_keywords` 驱动的 result/experiment/novelty/reliability 评级）。不要用 Python 算"值不值得读"。
   - 改为：脚本从 parse-cache 抽出**初筛所需的证据摘要**（title/abstract/首几页关键段，带 page/section locator），产出一个 `screening.yaml` 的**待填结构**：`worth_deep_reading`（agent 填 yes/no/maybe）、`judgement_reason`（agent 填，需带 evidence_refs）、`relevance_to_current_research` 等字段留空待 agent 填。
   - 提供一个校验入口：agent 填完后，脚本用 `verify_claim_evidence` 校验 judgement 的据、`validate_claims` 校验结构；不合法则拒绝落盘为"已筛"。
   - 保留 keyword_hits 作为**给 agent 的线索**（标注清楚这是提示不是判断），但它不再驱动任何评级字段。
2. **`complete-note` 改为五要素待填结构 + 证据验证（SSOT 3.2 + B1 两阶段）**：
   - `note_template` 不再作为最终笔记。改为产出**待填结构**，必含五要素：**motivation / method / experiment / limitation / insight**（对应写进 `record.payload.core_content` 的字段 + note.md 章节）。
   - 定义一个**填充契约**：runtime agent 读 parse-cache，为每个要素写内容 + 附 `evidence_refs`（短逐字 quote + page/section locator，按 B4 分 PDF/HTML）。
   - 脚本的 `complete-note` 支持两种调用：(a)**产出待填骨架**（headless，给 agent）；(b)**校验+落盘 agent 已填内容**（用 `validate_claims`+`verify_claim_evidence` 校验每要素的据，全过才写 core_content + note.md；任一要素据不实/为空则拒绝并指出哪条）。
   - 落盘后 core_content 非空 → 过 `has_substantive_content` → 可被确认（不再是空壳）。
3. **确认路径**：`confirm` 复用已有 confirm_unit（已被空心门守，Wave2 已改）；不重复实现门控。
4. **SKILL.md**：更新为新范式——明确"脚本备料+验证、agent 填理解"、五要素必填、证据绑定、两阶段。删掉暗示"脚本生成笔记"的措辞。
5. **保留**：prewarm-cache / extract-figures / refresh-structure 的现有机械功能（它们是纯搬运，符合原则1，不用重写；若依赖被重构移动的符号，改 import 即可）。

============================================================
你能测的 vs 我（协调者）会做的
============================================================
你**不能**headless 测"agent 填了好理解"——理解需要真 agent。所以：
- **你测机器**：screen 产出待填结构（无关键词评级）；complete-note 产出五要素骨架；喂一份**合成的已填内容 + 合法 evidence**（quote 逐字取自合成 parse-cache）→ 校验通过 + 过实质门 + 落盘；喂**编造 evidence** → 被拒并指出哪条；喂**空/模板填充** → 实质门挡住 confirm。
- **我会做**（merge 后，别替我做）：真正以 runtime agent 身份对 AR-FB 论文填五要素带真实证据，然后重跑 G5 看接地率/core_content 填充率/门控是否真改善。

============================================================
验证（全绿再交，逐条给实际输出）
============================================================
1. `python -m compileall .agents/skills/paper-analyst .agents/lib` 通过；`paper.py --help` 通过。
2. 全量 `pytest .agents/lib/research/tests -q` 全绿（新增测试只增；注意 tmp venv 需有 pyyaml+pymupdf4llm，`python3 -m venv .venv && .venv/bin/pip install pyyaml pytest pymupdf4llm`）。
3. **关键证明——合成端到端**：造一个临时 paper unit（parse-cache 含已知文本）：
   - screen 产出待填 screening（**grep 证明无关键词驱动的评级**）；
   - complete-note 产出含五要素的待填骨架；
   - 用合成"已填五要素 + 逐字合法 quote"跑校验落盘 → core_content 非空、`has_substantive_content`=True；
   - 用"编造 quote"跑校验 → 被拒且指出违规要素；
   - 用"空填充"→ confirm 被实质门拒。
4. **反模式自查**：`grep -nE "_grade|len\(.*hits\)" paper.py` 确认不再有"命中数→评级"逻辑驱动判断字段（keyword_hits 可留作线索但不评级）。
5. kb/ 零改动。

【交付】小步 commit、不 push。附：合成端到端四情形实测（待填结构/合法落盘/编造拒/空壳门挡）、反模式自查 grep 结果、pytest 数、以及你给 runtime agent 的"五要素填充契约"长什么样（字段+evidence 格式），方便我 merge 后照它填 AR-FB。**若五要素对某些论文类型（如纯 benchmark/survey 论文）不完全适配，停下来说明，别硬编。**
