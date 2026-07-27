你在开源 research-workspace 系统做 **验收后修复 · Track 1（kb-cli + 自动化补全：A + F1 + F3 + F5 + F7）**。基线=main `26e198a`。独立 git worktree。小步提交，DO NOT push。

**STEP 0 — sync base**：`git log --oneline -1` + `wc -l .agents/lib/research/core.py`（~56）。正确基线 main **26e198a**（265 测试绿）。不符 → `git reset --hard 26e198a`。spec 从主仓 `/Users/czx/.../temp/` 读（gitignore）。

**背景**：验收测试（cold agent 端到端 paper+repo+blog）打分 自动化 5/10 是最大短板：`kb ingest` 只链了前半段（intake→prepare 停），填完 verify 后剩余安全自动步（extract-figures/refresh-structure）+ 初筛填充 全压给 agent 手动穿。你补齐后半条链的**导航**（不是替 agent 填内容，是让 agent 无歧义知道剩余自动步）。SSOT 原则7 + AGENTS.md「Ingestion auto-drive」是依据。

**⚠️ 不要碰 verify 退出码**：验收报的 F4（verify 拒绝 exit 0）经协调者实测**证伪**（是测试污染了 scaffold 示例行）。别改任何 analyzer 的 verify 逻辑。你的活在 kb-cli + common.py 的命令渲染。

**本 track 拥有的文件（只动这些）**：`.agents/skills/kb-cli/scripts/kb`、`.agents/skills/kb-cli/SKILL.md`、`.agents/lib/research/common.py`（**仅** confirm_command/shell_command 相关，F5）、`.agents/skills/source-intake/scripts/intake.py`（仅 F1 reject 路径若需要）、新增测试。**不碰** paper/blog/repo analyzer 脚本（Track2 的）、evidence/confirm/sources/records.py、kb/。

============================================================
要做的
============================================================
1. **A — 自动化补全（最重要）**：`kb ingest` 后半链导航。paper 走 complete-note verify 成功后，agent 应被明确导航去跑剩余安全自动步。两种实现二选一（倾向前者，改动集中在 kb-cli）：
   - `kb ingest` 的 stdout 除了现在的"填 note 元素"NEXT 行，**再补一段说明整条链**：填 note→verify 后还需 extract-figures + refresh-structure（paper 安全自动步）+ 初筛填充（screen --phase verify），最后呈现判断待确认。让 agent 一眼看到"填完之后还有哪几步自动做"。
   - **初筛第二次填充要被 ingest surface**：当前 ingest 只提 note 元素，漏了 screening worth-reading 填充。把它纳入同一引导（screen prepare 已在 kb ingest 链里跑过，fill 文件已生成——导航要指向它）。
   - 尊重 autonomy 阀门（auto_execute_scope∩GOVERNANCE_MAX_AUTO_STEPS）：extract-figures/refresh-structure 属安全自动步范畴的按配置放行导航；verify/confirm 永不自动。
   - 不替 agent 跑 verify（verify 需 agent 先填）——你只补"填之后该干嘛"的清晰链式导航。

2. **F1 — repo 被误判为 blog + 无 reject 路径**：
   - `infer_add_kind`（kb:206）：本地路径是**目录**（或含 `.git`、含 `README` + 源码结构）→ 判 `repo`，别落 else→blog。保留 arxiv/pdf→paper、github/git→repo。给一个清晰的本地-目录→repo 规则。
   - **加 reject/supersede 路径**：验收留下孤儿 `b-langwbc-repo-*`（错判产生的 blog 单元）无法清理。加一个 `kb` 侧的路径能把误建单元标记 rejected/superseded（复用底层已有的 promote --confirmation-status rejected 或 analyst reject；dispatcher 转发即可，别重实现）。
   - 验证：`kb ingest <本地 repo 目录>` 推断成 repo；误建单元有清理出口。

3. **F3 — `--root` arg-order 陷阱**：`kb ingest --help`（及其它 verb 的 help/usage）说明 `--root` 是顶层 flag，需放 verb 前。至少 help 文本/usage 提示清楚，避免用户 `kb ingest <src> --root X` 撞 argparse 错误。

4. **F5 — 两套 confirm 命令不一致**：验收发现 `kb review`/`find` 与 `kb next` 渲染的 confirm 命令路径不同。统一到 `research.common` 的单一 `confirm_command`/`shell_command`（common.py:47/59 已有），所有渲染 confirm 命令处复用它，消除手抄分叉。

5. **F7 — `kb find` stale `next:` 提示**：find 输出里的 next-step 提示已过时（指向旧流程）。改成与当前主线一致的导航（或移除误导项）。

============================================================
验证（全绿再交，逐条给实际输出）
============================================================
1. `compileall` + `kb help` + `kb ingest --help` + `intake.py --help` 通过。
2. 全量 `pytest`（tmp venv：pyyaml+pytest+pymupdf4llm）全绿，新增测试只增。
3. **A 端到端（临时 kb，NEVER kb/）**：`kb ingest <本地 pdf>` → stdout 现在清楚列出**整条链**（填 note→verify→figures→structure→初筛填充→待确认），不只前半。贴 stdout。
4. **F1**：`kb ingest <本地 repo 目录>` 推断成 repo（非 blog）；误建单元有 reject/supersede 出口（贴命令+结果）。
5. **F3**：`kb ingest --help` 显示 --root 用法/位置。
6. **F5**：全仓 confirm 命令渲染走单一 helper（grep 证明无第二处手抄）。
7. **F7**：find 输出无 stale next 提示。
8. kb/ 零改动。

【交付】小步 commit、不 push。附：A 的 kb ingest 整链 stdout、F1 repo 推断+reject 实测、F3/F5/F7 各证据、pytest 数。**若 A 的链式导航在某处需要 analyzer 侧配合（跨 Track2 文件），停下说明、别越权改 analyzer**——只在 kb-cli 侧做导航，analyzer 的 stdout 已由前一轮加了 NEXT FOR AGENT 行可复用。
