你在开源 research-workspace 系统做 **Wave 3 · Track Repo-Analyst（3.3 仓库分析器，从 README/目录启发式改成 prepare/verify 机器）**。基线=main `a91230c`（237 测试绿）。独立 git worktree。小步提交，DO NOT push。

**STEP 0 — sync base（关键）**：先 `git log --oneline -1` + `wc -l .agents/lib/research/core.py`（~56）+ `ls .agents/lib/research/{evidence,confirm,sources}.py`。正确基线 main **a91230c**。不符 → `git reset --hard a91230c`。spec/design 从主仓 `/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/temp/` 读。

**⚠️ 最重要（铁律）**：脚本**绝不理解仓库**。它建可填结构 + 验证证据 + 过门；**runtime agent 填理解**（能力边界/复用点/改哪）。litmus：任何函数给一个 repo+无 agent 就吐"核心能力是 X / 适合做 baseline"判断的，删掉（现在的 `capability_map`/`infer_repo_roles` 就是这种，要改）。**参考已落地的 `paper-analyst/scripts/paper.py` 的 prepare/verify 范式。**

**可用已合并 API**：`research.evidence`（verify_claim_evidence/validate_claims）、`research.confirm`（has_substantive_content/confirmation_track；`SUBSTANCE_CONTENT_SECTIONS` 里 repo→`capability`，落盘填这个才过实质门）。

**本 track 拥有的文件**：`.agents/skills/repo-analyst/scripts/repo.py`、`.agents/skills/repo-analyst/SKILL.md`、新增测试。**不碰** evidence/confirm/sources/records.py、其它 skill、kb/。

============================================================
要做的（SSOT 3.3：入库文件级=能力边界；按需符号级）
============================================================
1. `scan-structure` **保留机械部分**（列关键文件/目录/入口/配置文件——纯搬运，符合原则1）。但**去掉启发式"能力推断"**（`capability_map`/`infer_repo_roles` 产的 roles/topics/tags 判断）。
2. `map-capability` 改 prepare/verify 两相：
   - **prepare**：产**待填结构**——repo 三要素留白待 agent 填：
     - `capability`（这个 repo 解决什么问题、核心能力、功能边界=适合/不适合做什么）
     - `reuse_points`（哪些模块可复用/借鉴/改造）
     - `entry_map`（关键入口：训练/推理/eval 命令 + 关键配置 key + 核心模块位置）
   - **verify**：agent 填完，脚本 `validate_claims`+`verify_claim_evidence` 校验每要素的据——**证据 artifact = repo 内真实文件，locator=`file:line` 或文件路径，quote=该文件里的逐字片段**（如 README 一句、某入口文件一行）。全过才落盘 + 填 `SUBSTANCE_CONTENT_SECTIONS[repo]=capability` section。编造/无据要素按名拒。
   - **证据可达性**：确保 verify 能加载被引用的 repo 文件（在 unit 的 source/ 下或可解析的 repo root）；若某文件不可达，verify 应报明确错误而非静默过。
3. **符号级=按需**：入库只做文件级（能力边界够了）。加一个可选 `inspect --query "loss 在哪/训练入口"` 的入口（或在 SKILL.md 说明"用户进一步要求时 agent 深入符号级细读并 grounding 到 file:line"）——不在入库时全做。
4. `confirm` 复用 confirm_unit（勿重实现门控）。
5. SKILL.md 重写为新范式。**自动化导航**：prepare stdout 末尾加导航——"下一步：agent 读关键文件填三要素带 file:line 证据，再跑 verify"。

============================================================
你能测的 vs 我会做的
============================================================
你测**机器**（headless，合成一个 mini repo fixture：几个 .py + README + config）：prepare 产三要素待填（无启发式能力判断）；合成"已填+file:line 逐字合法 quote"→ verify 过+落盘+过实质门；编造 quote/不可达文件→ 拒；空→ 门挡。
我会做（merge 后）：真以 agent 身份分析一个真实 repo。别替我做。

============================================================
验证（全绿再交，逐条给实际输出）
============================================================
1. `compileall` + `repo.py --help` 通过。
2. 全量 `pytest`（tmp venv：pyyaml+pytest+pymupdf4llm）全绿。
3. 合成 mini-repo 端到端四情形实测（待填/file:line 合法落盘/编造或不可达拒/空壳门挡）。
4. 反模式自查：确认 `map-capability` 不再用 `infer_repo_roles`/README 摘录产能力判断（可留作给 agent 的 orientation hint，但不落成判断字段）。
5. kb/ 零改动。

【交付】小步 commit、不 push。附：四情形实测、反模式说明（capability 判断已交 agent）、pytest 数、你给 agent 的"三要素填充契约"（含 file:line 证据格式）、以及 repo 证据文件可达性怎么解析的。**若 repo 代码太大不宜全放进 unit source/，说明你的证据可达性方案（如只 ground 到 README+入口文件，或记录 repo root 路径），别硬塞。**
