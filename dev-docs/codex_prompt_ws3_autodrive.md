你在开源 research-workspace 系统做 **Wave 3 · 自动驱动胶水（SSOT 原则7："足够自动化"的机械管线）**。基线=main `617885c`（重构 + evidence + 空心门 + 双源 + paper/blog/repo 三 analyzer 全 prepare/verify，252 测试绿）。独立 git worktree。小步提交，DO NOT push。

**STEP 0 — sync base**：`git log --oneline -1` + `wc -l .agents/lib/research/core.py`（~56）+ `ls .agents/lib/research/{evidence,confirm,sources}.py`。正确基线 main **617885c**。不符 → `git reset --hard 617885c`。spec/design 从主仓 `/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/temp/` 读（gitignore）。

**背景（先读）**：SSOT 原则7（自动驱动）+ AGENTS.md 新增的「Ingestion auto-drive」节（会话规则已由协调者写好）。你做的是让**脚本 stdout 给出机读的下一步导航** + **一条 `kb ingest` 链式命令**，好让会话 agent 无歧义自动接手。**你不改 analyzer 的判断逻辑**（那些已完成），只加导航 + 编排。

============================================================
你拥有的文件（只动这些）
============================================================
- `.agents/skills/source-intake/scripts/intake.py`（`guidance_hints` + add 流程 stdout）
- `.agents/skills/paper-analyst/scripts/paper.py` / `blog-analyst/scripts/blog.py` / `repo-analyst/scripts/repo.py`（**仅** prepare 命令的 stdout 尾部导航；不碰判断/verify 逻辑）
- `.agents/skills/kb-cli/scripts/kb`（加 `ingest` 动词）
- `.agents/skills/kb-cli/SKILL.md`（记 ingest）
- 新增测试
**不碰** evidence/confirm/sources/records.py、analyzer 的 verify/prepare 核心逻辑、AGENTS.md（协调者已写）、kb/。

============================================================
要做的
============================================================
1. **机读导航行 `NEXT FOR AGENT:`**（三个 analyzer 的 prepare stdout 尾部 + intake add 后）：
   - 格式统一、单行、机读友好，含：**该读哪个 artifact**（parse-cache 路径）、**填哪些要素**（该 kind 的要素名列表）、**填完跑哪条命令**（含已解析的 paper-id + `--phase verify --input <fill 路径约定>`）。
   - 例（paper prepare 尾部）：`NEXT FOR AGENT: read kb/units/papers/<id>/parse-cache.yaml, fill elements [motivation,method,experiment,limitation,insight] each with verbatim quote+locator, then run: paper.py --root <ROOT> complete-note --paper-id <id> --phase verify --input <fill.yaml>`
   - intake add 后的导航（替换现在含糊的"让 AI 判断"）：指明"下一步 agent 跑 <analyzer> prepare"，或若走 `kb ingest` 则说明链已自动继续。
   - blog/repo 同理，要素名分别是 positioning/key_points/credibility/reusable_explanation 与 capability/reuse_points/entry_map；locator 分别 section/anchor 与 file:line。
2. **`kb ingest <src>` 链式命令**（kb dispatcher）：
   - 把**能脚本化的段**串起来：`intake add`（推断 kind：arxiv/pdf→paper, github/git→repo, else→blog，复用现有 add 的推断）→ 对应 analyzer `prepare`。
   - **在 prepare 后停下**，打印聚合的 `NEXT FOR AGENT:`（告诉会话 agent：现在读 parse-cache 填要素、跑 verify；verify 通过后再 extract-figures/refresh-structure/screen）。**不自动跑 verify**（verify 需要 agent 先填内容——脚本不能替 agent 填）。
   - 即：`kb ingest` 自动化"填之前"和给出"填之后该干嘛"的清晰指令；中间的"填理解"是 agent 的活（由 AGENTS.md 规则驱动），末尾确认是用户的活。
   - 尊重 autonomy 阀门：若 `runtime-preferences.autonomy.auto_execute_scope` 收窄，ingest 只跑被允许的安全步骤（intake/prepare 属安全；verify/confirm 不自动）。
3. **`kb help` 菜单 + SKILL.md**：加 ingest 一行说明（"一条命令把 source 拉进来并备好待填骨架，agent 随后自动填 grounded 笔记"）。

============================================================
验证（全绿再交，逐条给实际输出）
============================================================
1. `compileall` + `kb help` + 三 analyzer `--help` + `intake.py --help` 通过。
2. 全量 `pytest`（tmp venv：pyyaml+pytest+pymupdf4llm）全绿，新增测试只增。
3. **`kb ingest` 端到端（临时 KB + 一个本地小 PDF 或合成源，NEVER kb/）**：跑 `kb ingest <src>` → 实测它 intake+prepare 到位、停在 prepare、打印含真实 paper-id 的 `NEXT FOR AGENT:` 行、**未**自动 verify。贴 stdout。
4. **导航行机读性**：三个 analyzer prepare 的 `NEXT FOR AGENT:` 行都含 artifact 路径 + 要素列表 + verify 命令。贴三条实例。
5. autonomy 收窄测试：把 auto_execute_scope 设成不含 prepare 的值，`kb ingest` 相应缩减（或明确提示），不越权。
6. kb/ 零改动。

【交付】小步 commit、不 push。附：`kb ingest` 端到端 stdout、三条 `NEXT FOR AGENT:` 实例、autonomy 收窄实测、pytest 数。**若 `kb ingest` 的 kind 推断或链式在某源类型上不确定，停下说明，别硬跑。**
