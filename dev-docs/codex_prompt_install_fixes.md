你在开源 research-workspace 安装器上修 6 个已确认缺陷（对抗性审查 + 实测确认）。当前在 worktree，HEAD 83b9ca1（project scope 拷贝 + ws_sync.py + update/uninstall 子命令）。改 install.sh、install-lib/ws_sync.py，必要时 docs。全部修完跑自测再 commit。安全合同最高优先：install/update/uninstall 只能碰 DIR/.agents 子树 + 受管 CLAUDE.md block + DIR 本地软链 + DIR/AGENTS.md(仅本器 artifact)，绝不写/删 DIR/kb、DIR/.venv、非本器文件。

先读真实文件确认现状：install.sh（run_smoke ~782、主 dispatch install/update/uninstall ~800-860、guard_* ~415-449、ws_sync ~451、install_claude_project/install_codex_project、CONFIG_CLAUDE/CODEX/AGENT_FLAG_SET ~126-192、manifest_field ~400、manifest_is_ours ~378）、install-lib/ws_sync.py（should_exclude 78-85、source_items 92-112、path_for_rel 134-142、is_under_agents 153-159、assert_delete_target 162-166、write_file_if_needed 183-199、detect_drift 270-285、install 296-327、update 330-393、uninstall 396-430）。

============================================================
FIX 1 (HIGH) — run_smoke 越界写 DIR/kb
============================================================
现状：run_smoke(install.sh:782-793) 在 COPY_PROJECT 分支跑 `"$WS_KB_SCRIPT" --root "$WORKSPACE_ROOT" status`，经 navigate current-state 无条件 write_text_if_changed 落 DIR/kb/user/current-state.md，安装阶段就创建了 DIR/kb（违反 kb 绝不触碰），且 uninstall 把这个安装器自造的 kb/ 当用户数据永久保留。
修法：把 run_smoke 里两处 `status` 冒烟都改成只读、不落盘的 `doctor`（handle_doctor 只打印能力，不写文件）。即：
- COPY_PROJECT 分支：`"$WS_KB_SCRIPT" --root "$WORKSPACE_ROOT" doctor >/dev/null`
- 非 COPY 分支：`RESEARCH_SKILLS_HOME="$REPO_ROOT" "$WS_KB_SCRIPT" --root "$WORKSPACE_ROOT" doctor >/dev/null`
保留 `"$WS_KB_SCRIPT" help >/dev/null` 那行。改 info 文案里的 "status" 为 "doctor"。核心：安装/更新/卸载阶段的任何冒烟都不得触发 DIR/kb 的 mkdir/write。

============================================================
FIX 2 (MEDIUM) — 写入路径缺 is_under_agents 物理约束（与删除侧不对称）
============================================================
现状：write_file_if_needed(ws_sync.py:183-199) 的目标由 path_for_rel 生成，只做 .. /绝对/前缀字符串校验，从不 resolve()。若 DIR/.agents 内某子目录是指向外部的软链，mkdir/os.replace 会顺软链把文件写到 .agents 子树外。删除侧 remove_file→assert_delete_target→is_under_agents 已用 resolve 防住，写侧遗漏。
修法：在 ws_sync.py 新增 assert_write_target(path, dst_root)：
- rel=="AGENTS.md" 对应的 dst（即 dst_root/AGENTS.md）单独放行。
- 否则校验 path 自身与其 parent 的 resolve(strict=False) 仍在 agents_root(dst_root).resolve() 之内（复用/对齐 is_under_agents 的判定；parent 也要查，因为写发生在 parent 目录里）。任一逃逸即 die("refusing to write outside .agents: <path>")。
在 write_file_if_needed 的 mkdir/写 tmp/os.replace 之前调用 assert_write_target(dst, dst_root)。install()305-306 与 update()365-366 两条写循环都会经过它。为提前失败并覆盖“子软链但无文件写”场景，update() 在写循环前对 .agents 内子目录做一次软链探测：os.walk agents_root 时对每个子目录 is_symlink() 为真即 die("managed .agents contains a symlinked subdirectory: <dir>; refuse to sync")。（install() 因 guard_copy_install_target 已挡顶层 symlink 且是全新拷贝，可不加探测，但写侧 assert_write_target 仍要调用作为统一防护。）

============================================================
FIX 3 (MEDIUM) — should_exclude 匹配祖先路径段，仓库在 .venv/__pycache__ 下会塌缩整棵树
============================================================
现状：should_exclude(ws_sync.py:78-85) 用 `any(part in EXCLUDED_DIRS for part in path.parts)`，而 source_items 传的是绝对路径。若 source/repo 路径的某个祖先段名为 .venv 或 __pycache__（如 /opt/checkouts/.venv/mirror/.agents/...），则每个文件都被判排除，source_items 只剩 items["AGENTS.md"]（111 行无条件加）。对已装 DIR 跑 update：new_files 塌缩成 {AGENTS.md}，removed=全部 .agents/* 条目，detect_drift 只查 old_files（磁盘未动、哈希匹配）故 drift=[]，无 --force 即删光整棵受管子树。--source 用户可控（install.sh:456-458 原样透传）直达此路径。
修法：
(a) 排除判断改为按“相对 agents_src 的树内路径”而非绝对路径。在 source_items(102-110)：dirs 过滤用 `should_exclude((root_path/name).relative_to(agents_src))`；files 过滤用 `should_exclude(path.relative_to(agents_src))`。这样只在受管树内部裁剪 __pycache__/.venv，忽略树外祖先目录名。
(b) update() 加防御性塌缩兜底：若 new_files 只剩 AGENTS.md（或 removed 覆盖了几乎全部 old_files 的 .agents 条目）而 source 的 .agents 目录实际非空，则 die（除非 --force）提示“source enumeration produced near-empty tree; refusing mass deletion”。这挡住枚举/过滤失败被当成“源删除”。

============================================================
FIX 4 (MEDIUM) — 漂移门只查 manifest 基线，源新增文件撞上本地同名文件时无 --force 静默覆盖
============================================================
现状：detect_drift(270-285) 只遍历 old_files。若源新增一个文件 rel（不在 old_files），而 DIR 本地已存在同名真实文件且内容是用户的，写循环(365-366) 无条件 write_file_if_needed 覆盖它，drift 为空不触发 gate，无需 --force。
修法：漂移检测覆盖“实际将写入且会破坏本地内容”的路径。具体：在 update() 写循环前，除现有 old_files 漂移外，对每个 rel in new_files 满足「dst 已存在为真实文件 且 rel 不在 old_files 且 dst 当前字节 != 源将写入内容」的，加入 drift 列表（标注为 collides-with-local）。等价实现：detect_drift 改为对 old_files ∪ new_files 计算，但对 new_files-only 的项只有在“dst 已存在且内容不同”时才算漂移（dst 不存在的真正新增文件仍免 --force 直接创建）。gate 逻辑(354-358)不变。

============================================================
FIX 5 (LOW) — manifest 损坏时 uninstall 硬 die，遗留 CLAUDE.md block + .claude/skills
============================================================
现状：install.sh 主 dispatch uninstall 分支，manifest 损坏(present-but-invalid)时硬 die(约 836-838)，导致受管 CLAUDE.md block 与 .claude/skills 软链未清理，与 no-manifest(foreign) 分支不一致。
修法：把该硬 die 降级为 warn+继续：manifest 损坏时跳过 uninstall_workspace_copy（不动 .agents 内容）与 remove_agents_md_if_managed，但仍执行 per-agent 卸载（uninstall_claude_project=remove_symlink_if_matches .claude/skills + remove_managed_block CLAUDE.md；uninstall_codex_project 保持安全 no-op；AGENTS.md 为真实文件时 remove_symlink_if_matches 直接 return 不动）。末尾 warn 提示：因 manifest 损坏，.agents 被保留、需用户手动处理；kb/.venv 不受影响。与 no-manifest 分支行为对齐（合同#8：拒删 .agents 但仍清 block+软链）。

============================================================
FIX 6 (LOW) — update 无视 agent 选择，无条件重写 CLAUDE.md block
============================================================
现状：update 分派(install.sh:823-828)无条件 install_claude_project + install_codex_project，无视 --claude/--codex，且不带 flag 的 update 因 AGENT_FLAG_SET=0 默认双开(276-277)，可能与初装选择不符。
修法（manifest 记录初装选择，update 复现）：
- ws_sync.py install：manifest 增加字段 agents（如 {"claude":bool,"codex":bool}），由 install.sh 通过新参数传入（给 ws_sync.py 加 --agents-claude/--agents-codex 或一个 --agents "claude,codex" 参数；install() 写入 manifest；update() 保留该字段不覆盖，若旧 manifest 无该字段则视为 {claude:true,codex:false} 向后兼容）。
- install.sh ws_sync() 调 install 时把当前 CONFIG_CLAUDE/CONFIG_CODEX 传进去。
- update 分派改为读 manifest 的 agents（manifest_field），据此有条件调用 install_claude_project / install_codex_project；读不到则回退只刷 claude（保持今日可用性）。
保持实现简单、稳妥；不要为此破坏 install 首装语义或 dry-run。

============================================================
验证（改完自测，全绿再 commit）
============================================================
1. python -m compileall install-lib/ws_sync.py 通过；install.sh 语法 `bash -n install.sh` 通过。
2. 全量 python -m pytest .agents/lib/research/tests -q 仍 160 绿。
3. FIX1：全新 DIR real install（RESEARCH_PYTHON=当前带 yaml 的 python），安装后 DIR 下【不得】出现 kb/ 目录（ls -a DIR）；仅 .agents/.claude/AGENTS.md。
4. FIX2：构造 DIR 已装后，把 DIR/.agents/lib 换成指向 /tmp/outside 的软链，跑 update → 必须 die（symlinked subdirectory 探测或 assert_write_target），/tmp/outside 内不得被写入。
5. FIX3：把整个 REPO 拷到一个祖先名为 .venv 的路径(如 /tmp/x/.venv/mirror)，从那里 install 到新 DIR → DIR/.agents 必须是完整树(文件数 >100)，不是只剩 AGENTS.md；再对已正常安装的 DIR 用 --source 指向该 .venv/mirror 跑 update → 不得删光（塌缩兜底 die 或正确枚举）。
6. FIX4：DIR 已装，向 source 新增一个文件 X（不在旧 manifest），同时在 DIR/.agents 预置同名 X 且内容不同 → update 无 --force 必须因 collides-with-local abort(exit 3)；--force 才覆盖。真正全新文件(dst 不存在)仍免 --force 创建。
7. FIX5：DIR 已装，破坏 manifest（写入非法 JSON），uninstall → 不硬 die；CLAUDE.md managed block 与 .claude/skills 被清理；.agents 保留并 warn；DIR/kb、DIR/.venv 不动。
8. FIX6：DIR 用 --codex 单独安装(如支持)或检查 manifest.agents；update 时只刷新初装选择的 agent 的 CLAUDE.md/接线，不无条件双写。
9. 回归：重跑我之前的核心场景——dry-run 零写；update no-op 0/0/0；漂移门 exit3 + --force；源删文件精确删；uninstall 保留 kb/.venv sentinel 恒等；四道守卫(重装/foreign/legacy symlink/AGENTS 冲突)仍拒绝；单仓 --project . 无 copy/manifest；update/uninstall 在 system/单仓 die。
10. 源仓库 .agents 全程 git status clean（测试用临时 DIR，勿污染 REPO）。

清理所有测试临时目录与 /tmp/outside、/tmp/x。commit：install: fix 6 review findings (smoke no longer writes kb/; write-path containment; ancestor-exclusion; drift covers source-added collisions; corrupt-manifest uninstall cleans wiring; update honors installed agents)。最终回复列改动文件与每个验证步骤实际输出。
