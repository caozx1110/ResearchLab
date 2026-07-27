你在开源 research-workspace skill 系统改造安装器。基线干净树 HEAD a4e7b97，160 tests 绿。任务：把 install.sh 的 project scope 从「软链」改成「拷贝」，并新增显式 update / uninstall 子命令 + manifest + clean-sync 安全合同。方案已定，按规格施工。python3 是硬依赖（bootstrap.py / preflight），允许引入一个 stdlib-only python 助手。

先用工具读真实文件确认现状：install.sh（608 行，重点 118-196 参数解析、231 prompt_scope、301-329 link_force/remove_symlink_if_matches、399 build_claude_block、416 install_claude_project/434 uninstall、445 install_claude_system、472 install_codex_project(含过时注释 Do not copy .agents)/489 uninstall、530 install_kb_on_path、555 run_smoke、565-608 主 dispatch）；.agents/lib/research/bootstrap.py（managed_venv_dir/ensure_managed_runtime，venv 落在 walk-up 根）；.agents/lib/research/common.py（find_project_root）；.agents/skills/kb-cli/scripts/kb；docs/INSTALL.md；README.md；.gitignore。

============================================================
总体模型
============================================================
- SELF_CONTAINED 谓词 = same_dir(WORKSPACE_ROOT,REPO_ROOT)  OR  外部拷贝安装（DIR≠repo 的 project 安装）。Claude 接线的 include+相对软链分支改由 SELF_CONTAINED 选择（今天只由 same_dir 选），单仓行为字节级不变。
- 拷贝触发：仅当 SCOPE=project 且 ACTION=install 且 !same_dir(DIR,repo)。共享函数只跑一次（放主 dispatch 里、在 per-agent 安装器之前），--all 不会重复拷。
- 拷什么：整棵 REPO_ROOT/.agents（skills+lib+README 等，无内部软链）→ DIR/.agents；REPO_ROOT/AGENTS.md → DIR/AGENTS.md。排除 __pycache__/ *.pyc *.pyo .venv/ .DS_Store 和 .install-manifest.json 本身。
- 拷贝后：DIR/.claude/skills -> ../.agents/skills（DIR 内相对软链）；CLAUDE.md 用 include 模式（@AGENTS.md 指向 DIR 自己的 AGENTS.md 拷贝）；DIR/.venv 由首次运行时 bootstrap 自建（安装器绝不建 venv）。RESEARCH_SKILLS_HOME 对拷贝 workspace 不再需要。
- 效果（设计已实测）：经 DIR/.claude/skills/... 或 DIR/.agents/... 调起脚本，Path(__file__).resolve() 落在 DIR/.agents，walk-up 返回 DIR，venv->DIR/.venv，find_project_root 经 DIR/AGENTS.md 命中 DIR，零 env。

============================================================
新增 python 助手：install-lib/ws_sync.py（放 .agents 外，故不被拷）
============================================================
stdlib-only（os/sys/json/hashlib/shutil/argparse/pathlib）。用法：
  python3 install-lib/ws_sync.py {install|update|uninstall} --repo REPO --dir DIR --source-commit HASH [--source SRC] [--force] [--dry-run]
一趟完成 walk + sha256 + 按需写（dst 缺失或字节不同才写）+ 按 manifest 精确删 + 写/更新 manifest。核心不变量（结构性安全，非约定）：
- 读写删范围硬编码限定 DIR/.agents 子树 + 单个 DIR/AGENTS.md。DIR/kb、DIR/.venv 是 .agents 的兄弟目录，永不进入可达集、永不枚举。
- 每个删除目标 unlink 前重新断言 resolve() 落在 DIR/.agents 内（containment guard）。
- 删除只删「manifest.files 里记录过、且 source 已不再提供、且仍在 .agents 下」的文件；用户自行加进 .agents 的新文件一律保留。
- 绝不 rm -rf，绝不 rsync --delete。rmdir 仅删空目录。

manifest：DIR/.agents/.install-manifest.json（助手对该文件名始终排除于 hash/copy/delete）。字段：
  schema:1, install_name:"workspace-oss", install_mode:"copy-project",
  source_repo(绝对 REPO), source_commit(git -C REPO rev-parse HEAD 或 ""), installed_at(不可变, date -u %Y-%m-%dT%H:%M:%SZ 由 install.sh 传入或助手内取), updated_at(仅真实变更时更新),
  agents_md("managed"|"user") + agents_md_sha(写入时 DIR/AGENTS.md 的 sha256),
  files:{DIR 相对路径 -> sha256hex}（含 ".agents/..." 与根级 "AGENTS.md"）, 可选 tree_checksum。
写时机：install/update 拷贝成功后写（dry-run 打印不写）；update 仅当文件集或校验和变化才改写（installed_at 保留，updated_at=now，真 no-op 时字节不变）。
读时机：install 预检只读存在性；update 读 source_repo/source_commit/files（漂移基线+差异报告）；uninstall 读 files（精确删）+agents_md/agents_md_sha+install_mode。
manifest 损坏/schema 不符：update/uninstall 拒绝（不误删）。

各模式：
- install：DIR/.agents 不存在→全量拷+写 manifest。
- update：要求 DIR/.agents 真实目录+我们的 manifest，否则 die 带指引。source 权威取「正在运行的脚本的 REPO_ROOT」（脚本本身即活仓库，健壮于原仓移动）；manifest.source_repo 仅参考，不一致则告警；--source 覆盖。clean-sync 算法：
  (1) 枚举 source 侧 S_new(应用排除)+sha；读 manifest.files 得 S_old。
  (2) 漂移门：对现有 dst 文件 hash 比 manifest 基线——MODIFIED(改过)阻断；MISSING(用户删了)非阻断，从 source 恢复；用户 ADDED 保留。若有 MODIFIED 且无 --force：打印逐文件漂移列表并 abort exit 3。
  (3) 差异报告(只读，dry-run 也打印)：added=S_new-S_old；changed=同名 hash 不同；removed=(.agents 下的 S_old)-S_new；加 old_commit->new_commit。
  (4) 应用：逐个 S_new，dst 缺失或字节不同才写。
  (5) 删除：对 removed 精确 rm（每个再校验落在 DIR/.agents 且非 manifest），prune 空目录。
  (6) 刷新 CLAUDE.md managed block + 确保相对 .claude/skills 软链（这两步由 install.sh 侧做，不在助手内）。
  (7) 有变化才改写 manifest。
  --force 仅绕过漂移门，绝不扩大删除集、绝不碰 kb/.venv。幂等：源不变的第二次 update → added/changed/removed 全空、无写、manifest 不变、exit 0。
- uninstall（copy 模式）：精确 rm manifest.files 里 .agents 下的项、prune 空目录、删 manifest、DIR/.agents 若空才 rmdir（有用户新增文件则保留+告警）；不删 AGENTS.md（AGENTS.md 由 install.sh 侧判断）。

漂移/差异/删除都要支持 --dry-run（打印 [dry-run] copy/overwrite/delete/write manifest，零写）。

============================================================
install.sh 改动
============================================================
1) ACTION dispatch：while 解析前 peek $1，若为 install|update|uninstall 则设 ACTION 并 shift；默认 ACTION=install；保留 --uninstall flag 仍设 ACTION=uninstall（向后兼容，bash install.sh --claude --project . 不回归）。update/uninstall 若 SCOPE=system 或 same_dir(DIR,repo)→die 带指引（system 用重跑 install；单仓用 git pull）。

2) 新增 sync_workspace_copy()（主 dispatch install 分支、agent 安装器之前，仅 !same_dir 且 SCOPE=project 时跑）：
   - 防误(guard E)：DIR/.agents 已存在且是我们的 manifest→die "use update"；真实 .agents 无 manifest→die "foreign .agents, not overwriting"；遗留 symlink 安装(DIR/.agents 是软链)→die 提示先 uninstall 再 install（拒绝+文档，不自动转换）。
   - AGENTS.md 冲突：若 DIR/AGENTS.md 已存在且非本器 artifact（无 manifest 或 sha 不符）→【拒绝安装】die，提示用户先处理 AGENTS.md 冲突（用户已选拒绝，不做 embed 回退）。仅当 DIR 无 AGENTS.md 或为本器旧 artifact 时才写。
   - 调 ws_sync.py install（传 --dry-run 当 DRY_RUN=1，传 --source-commit "$(git -C "$REPO_ROOT" rev-parse HEAD 2>/dev/null || echo '')"）。

3) install_claude_project：改由 SELF_CONTAINED 选 include+相对软链分支（外部拷贝也走这条：link_target=../.agents/skills，include block）。删掉今天对外部走 copy-block+绝对软链的旧分支。

4) install_codex_project：外部拷贝下 DIR 已有真实 .agents+AGENTS.md 拷贝，改成 info no-op（不再软链）。重写 472/477-478 与 420-421 的过时注释为新不变量（拷整棵树安全；只有孤立单个 skill 目录才破坏 import）。

5) update 分支：主 dispatch 加 ACTION=update 处理——调 ws_sync.py update（含 --force/--source 透传），成功后刷新 CLAUDE.md managed block + 确保相对 .claude/skills 软链。

6) uninstall（ACTION=uninstall, project）：按 DIR/.agents 形态分支——
   - copy 安装(真实目录+我们 manifest)：remove_symlink_if_matches DIR/.claude/skills（接受 ../.agents/skills 新相对 与 旧绝对 $SKILLS_SRC 两种）；remove_managed_block CLAUDE.md；ws_sync.py uninstall 精确删 .agents；AGENTS.md 仅当 agents_md=managed 且 sha 仍匹配才删，否则保留+告警；绝不删 DIR/kb、DIR/.venv（打印已保留、workspace 现为 unmanaged 但数据完好）；DIR/bin/kb 指向 WS_KB_SCRIPT 才删。
   - 遗留 symlink 安装(DIR/.agents 是软链)：保持今天行为（remove_symlink_if_matches .agents/AGENTS.md + block/skills 清理，无 manifest）。
   - foreign(真实目录无 manifest)：拒绝删 .agents+告警，但仍清理明确属我们的 CLAUDE.md block 与 .claude/skills 软链。
   全程走 DRY_RUN 与 containment guard。

7) kb-on-path copy 模式：DIR/bin/kb 链到 DIR 内拷贝 WS_KB_SCRIPT=DIR/.agents/skills/kb-cli/scripts/kb（使其 resolve 也 walk-up 到 DIR）。

8) run_smoke：copy 模式下 smoke 用 DIR 内的 kb、且不再需要 RESEARCH_SKILLS_HOME（kb --root DIR status 或直接 DIR 内 kb status）。保持 DRY_RUN||UNINSTALL 早退。

============================================================
docs/README
============================================================
- docs/INSTALL.md：重写「硬不变量：symlink，不能 copy」段为双模型（system+单仓=symlink 跟随 resolve 回 REPO；外部 --project DIR=拷整棵树，walk-up 命中 DIR 的兄弟 lib；明确反向不变量：整棵一起拷安全，只有孤立单个 skill 才破坏 import）。更新 Claude/Codex project scope 段（外部 DIR 得真实 .agents+manifest+AGENTS.md+相对 .claude/skills+include CLAUDE.md+首次自建 .venv；AGENTS.md 冲突则拒绝安装需用户处理；copy workspace 不需要 RESEARCH_SKILLS_HOME）。新增「更新 (update)」段（install.sh update --project DIR、clean-sync、漂移 abort+--force、差异报告、kb/.venv 永不碰）。新增 uninstall 说明（copy vs 遗留 symlink、精确删、kb/.venv 保留）。env 表标注 RESEARCH_SKILLS_HOME 仅 system/legacy 需要。加非强制建议：DIR 可作独立 git 仓 或 gitignore DIR/.agents。
- README.md：把 symlink 硬不变量措辞放软为「system/同仓用 symlink，外部 project 用 copy」，指向 update 子命令。

============================================================
关键护栏（务必守住）
============================================================
- 绝不触碰 DIR/kb、DIR/.venv（读写删都不）。删除只在 .agents 子树 + 单 AGENTS.md，且 manifest 驱动 + containment 重校验。
- __pycache__/*.pyc 必须排除（源 .agents 已含 10+ __pycache__），否则字节码再生会误报漂移、破坏幂等。
- 单仓 --project .、system scope 行为不回归。
- 所有新增写/删/写 manifest 走 DRY_RUN；助手绝不建 .venv。
- governance 与 skill 逻辑零改动（本任务只碰安装器/文档/新 helper）。

============================================================
验证（改完自测，全绿再 commit）——逐条给实际输出
============================================================
1. Fresh external install：DIR 得 .agents 拷贝+AGENTS.md+.install-manifest.json+.claude/skills->../.agents/skills+include CLAUDE.md block；未设 RESEARCH_SKILLS_HOME 下 kb --root DIR status（或 DIR 内 kb status）可跑。
2. Walk-up 证明：调 DIR/.claude/skills/kb-cli/scripts/kb 与 DIR/.agents/skills/kb-cli/scripts/kb，二者 DEFAULT_PROJECT_ROOT 都解析为 DIR。
3. 首次运行脚本后受管 venv 落在 DIR/.venv 而非 REPO/.venv。
4. 已装 DIR 重跑 install --project DIR→拒绝(use update)；foreign 真实 .agents→拒绝；遗留 symlink→拒绝带迁移提示。
5. update no-op：装后 update→added/changed/removed 全 0、.agents 字节不变、manifest 不变、exit 0；跑两次验幂等。
6. 改一个 DIR/.agents 内 skill 文件后 update→漂移告警+abort(exit 3)；--force 重跑覆盖它；全程 DIR/kb 不动。
7. 模拟从 REPO/.agents 删一个文件后 update→DIR/.agents 下恰好删该文件、别处不动；DIR/.agents 下用户新增文件在 update 后存活。
8. 建 DIR/kb/data.txt 与 DIR/.venv/marker，跑 update 与 uninstall→两者原样保留。
9. dry-run install 与 dry-run update：文件系统零写(前后 stat DIR)，dry install 不建 manifest，但差异/漂移/old->new commit 报告照常真实打印。
10. uninstall copy 安装：manifest 列出的 .agents 文件删除、.claude/skills 消失、CLAUDE.md block 消失、AGENTS.md 仅未改时删(先改它→保留+告警)、DIR/kb 与 DIR/.venv 保留。
11. uninstall 遗留 symlink 外部安装(改动前接线)仍能干净移除软链。
12. 单仓 install --project .(在 REPO)不变：无拷贝、无 manifest、include block、相对 skills 软链。
13. system scope install/uninstall 不变(逐 skill 软链、RESEARCH_SKILLS_HOME 提示)。
14. AGENTS.md 冲突：DIR 已有用户 AGENTS.md 时 install→拒绝 die 带指引(不覆盖、不 embed)。
15. 全量 pytest 仍 160 绿（本任务不碰 skill 逻辑）。
16. update/uninstall 在 SCOPE=system 或单仓 DIR 上→die 带指引。

清理测试临时目录，勿把 kb/ .venv 或临时 DIR 加入提交。完成 git add -A（install.sh + install-lib/ws_sync.py + docs/INSTALL.md + README.md + install.sh 注释）并 commit：install.sh: project-scope copy install + update/uninstall subcommands + manifest clean-sync (kb/ never touched)。最终回复列改动文件与每个验证步骤实际输出。
