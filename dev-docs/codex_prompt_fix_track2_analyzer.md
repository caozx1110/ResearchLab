你在开源 research-workspace 系统做 **验收后修复 · Track 2（analyzer polish：F6/F9/F8）**。基线=main `26e198a`。独立 git worktree。小步提交，DO NOT push。

**STEP 0 — sync base**：`git log --oneline -1` + `wc -l .agents/lib/research/core.py`（~56）+ `ls .agents/lib/research/{evidence,confirm,sources}.py`。正确基线 main **26e198a**（265 测试绿）。不符 → `git reset --hard 26e198a`。spec 从主仓 `/Users/czx/.../temp/` 读（gitignore）。

**⚠️ 重要——不要动 verify 的退出码/拒绝逻辑**：验收曾报"blog/repo verify 拒绝却 exit 0"（F4），**经协调者实测证伪**——blog/repo verify 正确 exit 1 并拒绝（之前是测试污染了 scaffold 示例行而非真实填充 quote）。**F4 不修**。别碰 `verify_note_fill`/`verify_capability_fill`/`raise SystemExit(1)` 那套——它们是对的，改了会引入回归。

**本 track 拥有的文件（只动这些）**：`.agents/skills/blog-analyst/scripts/blog.py`、`.agents/skills/paper-analyst/scripts/paper.py`、新增测试。**不碰** repo.py（Track1 不碰它，但为清晰起见你也别碰）、kb-cli、common.py、evidence/confirm/sources/records.py、kb/。

============================================================
要修的三个（都是确认的真 bug）
============================================================
1. **F6：blog verify 后不 git-checkpoint**（blog 产物没被提交，paper/repo 都会 checkpoint）。
   - blog.py 当前 `from research.core import build_index, write_record, ...` 但**没 import `checkpoint_and_report`**。
   - 修：像 paper.py（:53 import、:660-661 用法）一样，blog complete-note verify 成功持久化后（blog.py:457-459 那段 write_record+build_index+print 之后）调 `checkpoint_and_report(root, trigger="milestone", message=f"milestone: blog note {blog_id}")`。summarize 等其它写入点按 paper/repo 同族惯例决定是否 checkpoint（与它们一致即可）。
   - 验证：blog verify 后 `git -C <kb> log` 有新 checkpoint commit（在临时 kb 里测）。

2. **F9：blog parse-cache header 键名写成 `paper_id`**（应是 blog 语义）。
   - 定位 blog.py 里写 parse-cache 或 header 用到 `paper_id` 的地方，改成 `blog_id`/`unit_id` 语义正确的键。注意别破坏 `_load_cache_chunks` 的读取兼容（若双源 sources.py 产的 cache 用某固定键，读侧要能兼容旧 header；拿不准就读侧同时接受两种键、写侧用正确键）。
   - 验证：blog intake 后 parse-cache header 不再出现 paper_id 语义键。

3. **F8：paper note.md 标题截断（mid-sentence）**。
   - 定位 paper.py 渲染 note.md 标题的地方（title 来源可能是 basic_info.title 或 fill）。当前会中途截断。修成完整标题（或在合理长度处按词边界截断 + 不破坏语义），别硬截。
   - 验证：note.md 顶部标题完整、不 mid-sentence 断。

============================================================
验证（全绿再交，逐条给实际输出）
============================================================
1. `compileall` + `blog.py --help` + `paper.py --help` 通过。
2. 全量 `pytest`（tmp venv：pyyaml+pytest+pymupdf4llm）全绿，新增测试只增。
3. F6：临时 kb 里 blog complete-note verify 后 `git log` 有 checkpoint（贴证据）。
4. F9：blog parse-cache header 键名正确（贴 before/after）。
5. F8：note.md 标题完整（贴 before/after）。
6. **回归护栏**：确认 blog/repo verify **仍正确 exit 1 拒绝**编造 quote（跑一个真实填充 quote 被篡改的用例，断言 exit 1）——证明你没碰坏 F4 那套正确逻辑。
7. kb/ 零改动。

【交付】小步 commit、不 push。附：F6/F9/F8 各 before/after、verify-reject 仍 exit1 的回归证据、pytest 数。
