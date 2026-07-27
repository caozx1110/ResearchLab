你在开源 research-workspace 系统做**文档受众重构**：把 repo 根 `AGENTS.md`/`CLAUDE.md` 从"使用 skill 的 agent 看"改成"**开发/优化 skill 的 agent 看**"，使用规则移进分发树。基线=main 当前 HEAD（先 sync）。独立 git worktree。小步提交，DO NOT push。

**STEP 0 — sync base**：`git log --oneline -1`；确认 repo 根有 `AGENTS.md`（当前=使用规则）、`CLAUDE.md`（当前=开发工作流，我刚写的）、`install.sh`、`install-lib/ws_sync.py`。若 worktree 开在过时 commit → `git reset --hard <当前 main HEAD>`。spec 从主仓 `/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/temp/` 读（gitignore）。

============================================================
目标状态（重构后）
============================================================
- **`.agents/AGENTS.md`** = **使用规则**（现 repo 根 AGENTS.md 的内容，一字不改，只换位置——它随 `.agents/` 分发树走，装到用户 kb 工作区）。
- **repo 根 `AGENTS.md`** = **开发工作流**（现 `CLAUDE.md` 的内容，见下）。面向开发 skill 的 agent（Codex 读 AGENTS.md）。
- **repo 根 `CLAUDE.md`** = **软链 → `AGENTS.md`**（Claude 读 CLAUDE.md，跟随软链读到同一份开发工作流）。
- **installer**：所有分发**源**引用从 `$REPO_ROOT/AGENTS.md` 改成 `$REPO_ROOT/.agents/AGENTS.md`；用户装出来的 `DIR/AGENTS.md` 仍是使用规则、位置不变。

============================================================
本 track 拥有的文件（只动这些）
============================================================
`AGENTS.md`、`.agents/AGENTS.md`（新）、`CLAUDE.md`、`install.sh`、`install-lib/ws_sync.py`、`docs/INSTALL.md`、`docs/DESIGN.md`、`README.md`、`CONTRIBUTING.md`、install/ws_sync 的测试（若有）。**不碰** `.agents/skills/*`、`.agents/lib/*`（除测试）、`kb/`（真实用户数据）。

============================================================
要做的
============================================================
1. **移使用规则**：`git mv AGENTS.md .agents/AGENTS.md`（保历史；内容零改动）。
2. **新 repo 根 AGENTS.md = 开发工作流**：取当前 `CLAUDE.md` 的正文作为新 `AGENTS.md`，但：
   - **删掉首行 `@AGENTS.md`**（现在 AGENTS.md 就是这份文档本身，不能自引用）。
   - 更新它内部的"文档所有权"表：把 `AGENTS.md | 工作区运行规则...面向用 kb 的 agent` 这一行改成 **`.agents/AGENTS.md` | 工作区运行规则/入库自动驱动（分发给用户 kb 工作区）| 面向**用** kb 的 agent**；并说明 **repo 根 `AGENTS.md`（=本文件）+ `CLAUDE.md`（软链）面向开发 skill 的 agent**。
3. **CLAUDE.md → 软链**：`rm CLAUDE.md && ln -s AGENTS.md CLAUDE.md`（相对软链，git 会记为 symlink）。
4. **installer 源重指向（最关键，别搞反 source/dest）**：
   - **只改分发"源"引用**：install.sh 与 ws_sync.py 中所有指向"要被分发的那份 AGENTS.md"的**源路径** `$REPO_ROOT/AGENTS.md`（ws_sync 里是 `source_root / "AGENTS.md"`）→ 改成 `.agents/AGENTS.md`（`$REPO_ROOT/.agents/AGENTS.md` / `source_root / ".agents" / "AGENTS.md"`）。
   - **绝不改"目的地"引用**：用户侧写入路径 `$WORKSPACE_ROOT/AGENTS.md`、`$global_dir/AGENTS.md`、ws_sync 的 `dst_root / "AGENTS.md"`、manifest 里键名 `"AGENTS.md"`——**全部保持不变**（用户的 AGENTS.md 仍在其工作区根、文件名不变）。
   - 具体已知源引用（自己再全量 grep 核对，别漏）：install.sh 的 preflight `:231`、conflict-check `expected=` `:787`、CLAUDE.md 生成的 fallback embed `:1018`、Codex system-scope `link_force ... :1108` 与 remove `:1100/:1125`；ws_sync.py 的 `agents_md_src :96`（+ `:100` die 文案）。**逐个判断它是 source 还是 dest**：source→改，dest→不动。
   - install.sh `:231` preflight：改成检查 `.agents/AGENTS.md` 存在（现在 repo 根 AGENTS.md 是开发文档、不是分发源）。
5. **文档**：更新 README/`docs/INSTALL.md`/`docs/DESIGN.md`/`CONTRIBUTING.md` 中对 AGENTS.md 的描述——区分：**使用规则=`.agents/AGENTS.md`（分发）**，**开发规则=repo 根 `AGENTS.md`+`CLAUDE.md`（软链）**。INSTALL.md 里"拷贝整棵 .agents 和 AGENTS.md"这类描述改成准确的新来源；CONTRIBUTING "编辑规则以 AGENTS.md 为准"现在指 repo 根开发文档（保持或点明）。

============================================================
验证（全绿再交，逐条给实际输出 —— installer 是重点，务必实测）
============================================================
1. `bash -n install.sh` 通过；`python -m compileall install-lib` 通过。
2. `.agents/lib/research/tests` 全量 pytest 仍绿（本改动理应不影响；用 `PYTHONPATH=.agents/lib` + 一个有 pyyaml 的 python）。若有 ws_sync/install 测试，一并绿。
3. **软链正确**：`readlink CLAUDE.md` = `AGENTS.md`；`cat CLAUDE.md` 显示开发工作流；repo 根 `AGENTS.md` 首行不是 `@AGENTS.md`。
4. **分发实测（copy 安装到临时目录，NEVER 真 kb/）**：
   - `bash install.sh --dry-run --claude --project /tmp/inst_test` 无报错。
   - 真装：`bash install.sh --claude --project /tmp/inst_test`（或等价），然后断言：
     - `/tmp/inst_test/AGENTS.md` 内容 == `.agents/AGENTS.md`（使用规则），**!=** repo 根 AGENTS.md（开发工作流）。贴 `diff` 证明。
     - `/tmp/inst_test/CLAUDE.md` 是 `@AGENTS.md` managed block。
     - `/tmp/inst_test/.agents/` 存在。
   - `bash install.sh uninstall --project /tmp/inst_test` 干净反转（AGENTS.md 受管则删、CLAUDE.md block 移除）。
5. **repo 根不被误分发**：确认没有任何路径把 repo 根开发 AGENTS.md 拷/链进用户工作区。
6. `git status` 确认真实 `kb/` 零改动。

【交付】小步 commit、不 push。附：copy 安装后 `/tmp/inst_test/AGENTS.md` vs `.agents/AGENTS.md` 的 diff（应相同）、vs repo 根 AGENTS.md 的 diff（应不同）、`readlink CLAUDE.md`、uninstall 反转结果、pytest 数、你改了哪些 source 引用（列表 + 每个判定 source/dest 的理由）。**若某个 AGENTS.md 引用你拿不准是 source 还是 dest，停下来列出问我，别猜着改——搞反会破坏用户安装。**
