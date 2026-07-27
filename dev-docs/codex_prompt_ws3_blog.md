你在开源 research-workspace 系统做 **Wave 3 · Track Blog-Analyst（3.4 博客分析器，从占位符改成 prepare/verify 机器）**。基线=已完成 paper-analyst 的 main（`a91230c`：refactor + evidence.py + confirm.py 空心门 + sources.py 双源 + paper-analyst prepare/verify，237 测试绿）。独立 git worktree。小步提交，DO NOT push。

**STEP 0 — sync base（关键）**：worktree 可能开在过时旧 commit。先 `git log --oneline -1` + `wc -l .agents/lib/research/core.py`（应 ~56）+ `ls .agents/lib/research/{evidence,confirm,sources}.py`。正确基线 main **a91230c**。若不符 → `git reset --hard a91230c` 再核对。spec/design 从主仓 `/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/temp/` 读（gitignore）。

**⚠️ 最重要（同 paper-analyst 的铁律）**：脚本**绝不理解博客**。它建可填结构 + 验证证据 + 过门；**runtime agent（非你、非 Python 启发式）填理解**。litmus：任何函数给一篇博客+无 agent 就吐"这是入门/原理/工程"判断的，删掉。你建机器，不建理解。**参考已落地的 `.agents/skills/paper-analyst/scripts/paper.py` 的 prepare/verify 范式照搬结构。**

**可用已合并 API（直接调）**：`research.evidence`（verify_claim_evidence/validate_claims/attach_claims/read_claims）、`research.sources`（双源已为 blog 产 parse-cache，HTML 源 locator_kind=section/anchor）、`research.confirm`（has_substantive_content/confirmation_track；`SUBSTANCE_CONTENT_SECTIONS` 里 blog→`content`，落盘要填这个 section 才过实质门）。

**本 track 拥有的文件（只动这些）**：`.agents/skills/blog-analyst/scripts/blog.py`、`.agents/skills/blog-analyst/SKILL.md`、新增测试。**不碰** evidence/confirm/sources/records.py、paper-analyst、intake、其它 skill、kb/。

============================================================
要做的（SSOT 3.4：博客=网页内容，不处理多媒体）
============================================================
1. `summarize`/`complete-note` 改 prepare/verify 两相：
   - **prepare**：从 blog parse-cache（section chunks）抽证据摘要，产**待填结构**——博客四要素留白待 agent 填：
     - `positioning`（内容定位：入门解释/原理分析/经验总结/工程教程）
     - `key_points`（核心知识点/概念）
     - `credibility`（**明确分 事实整理 vs 作者观点**）
     - `reusable_explanation`（可复用的解释/直觉素材）
   - **verify**：agent 填完，脚本用 `validate_claims`+`verify_claim_evidence` 校验每要素的据（逐字 quote 取自 blog parse-cache，locator=section/anchor，B4）；全过才落盘 note.md + 填 `SUBSTANCE_CONTENT_SECTIONS[blog]` 对应 section（使 has_substantive_content=True）。编造/空/无据要素按名拒绝。
2. `confirm` 复用已有 confirm_unit（已被空心门守，勿重实现门控）。
3. SKILL.md 重写为新范式（脚本备料+验证、agent 填理解、四要素、证据绑定、只网页不处理多媒体）。删掉暗示"脚本生成摘要"的措辞 + literal "待确认" 占位。
4. **自动化导航**：prepare 的 stdout 末尾加一句明确导航——"下一步：agent 读 parse-cache 填四要素带证据，再跑 `blog.py --phase verify`"，让会话 agent 知道自动接手（呼应即将加的 AGENTS.md 自动填规则）。

============================================================
你能测的 vs 我（协调者）会做的
============================================================
你测**机器**（headless，合成 fixture）：prepare 产四要素待填结构（无 Python 判断）；合成"已填四要素+逐字合法 quote"→ verify 过+落盘+过实质门；编造 quote→ 按要素名拒；空填充→ 实质门挡 confirm。
我会做（merge 后）：真以 agent 身份填一篇真实博客 + 验证 G5/可用性。别替我做。

============================================================
验证（全绿再交，逐条给实际输出）
============================================================
1. `compileall` + `blog.py --help` 通过。
2. 全量 `pytest`（tmp venv 需 pyyaml+pytest+pymupdf4llm）全绿，新增测试只增。
3. 合成端到端四情形实测（待填/合法落盘/编造拒/空壳门挡）。
4. 反模式自查：`grep -nE "待确认|main_value.*=|positioning.*=.*(入门|原理)" blog.py` 确认无 Python 产判断/占位。
5. kb/ 零改动。

【交付】小步 commit、不 push。附：四情形实测、反模式 grep、pytest 数、你给 agent 的"四要素填充契约"（字段+evidence 格式）。
