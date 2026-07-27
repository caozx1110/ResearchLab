# R25 handoff — Agent plan 绑定 PATH runtime 前置条件

## STEP 0 — base sync

在独立 worktree 开始；先核对 base 必须是主分支当前 `b704c23`（或开始时更新的主分支 HEAD），并确认 `a9c4b72` 的 PATH runtime discovery 已存在。若不符，停止并报告，不得在旧 base 施工。

## 目标

修复已复现 P2：Agent plan 在后置 PATH Python 可用时输出 `conditional_runtime_changes=[]`，但 apply 环境 PATH 漂移后仍通过计划验证，随后先复制 `.agents`/manifest，再尝试未列入计划的 `.venv` 并失败。计划必须绑定 runtime 前置条件；apply 在任何写入前重验，不一致零写并要求重做计划。

## 文件所有权

只允许修改：

- `install.sh`
- `install-lib/agent_plan.py`（确有需要时）
- `.agents/lib/research/tests/test_agent_install_plan.py`
- `.agents/lib/research/tests/test_installer.py`（确有需要时）
- `docs/INSTALL.md`
- `.agents/lib/research/SCHEMAS.md`（若计划机器字段需正式规格）

不得修改其他文件；与主代理 version/docs track 保持 disjoint。

## 锁定合同

- Agent plan 因复用 PATH Python 而不声明 managed runtime 时，必须保存 canonical interpreter path、稳定 regular/executable identity（dev/inode/mode/uid/gid/size/mtime_ns/ctime_ns）和 core runtime readiness，并纳入 plan digest/byte-bound apply contract。
- apply 在首个 workspace/HOME/runtime 写入前，按同一选择规则重验 invocation 仍可发现、exact interpreter/managed chain identity 与能力；PATH 不再包含 current/later-PATH entry、explicit override 漂移、managed leaf/chain 或 target/capability 漂移均零写 fail closed并提示 Agent 自动重做计划。不能只让本次 apply 复用一个 installed `kb` 后续不会记住的 absolute target。
- 不能在受管 copy/manifest 已落盘后才把 plan 外 `.venv` 当 fallback。
- human install 保持可自动复用后置 PATH runtime或声明/创建 managed venv；显式 `RESEARCH_PYTHON` 优先，不被替换。
- 计划/普通公开输出不得泄漏内部命令、flag、绝对路径、环境变量或 Agent marker；机器 JSON 可以包含审计字段。
- 不引入外部 API Key、付费服务、订阅、商业数据库、插件或网络依赖。

## 必须先红后绿

新增确定性回归：

1. plan 环境为 deficient first Python + later compatible Python，得到零 conditional runtime targets；apply 前从 PATH 移除 later entry，保持 `PIP_NO_INDEX=1`。期望 apply 首写前非零，workspace tree byte/type/mode 完全一致，无 `.agents`、manifest、`.venv` 或其他写入；Agent 可在新环境自动重做计划。
2. bound runtime 消失、same-bytes new inode、mode/identity 变化、core modules 探测失败，以及 ready-managed invocation leaf/chain 漂移，均在首写前拒绝。
3. plan/apply 稳定环境仍成功，零 `.venv`，installed `kb help` 成功。
4. 既有显式 override、managed venv conditional plan、plan byte/source/target precondition tests 不回归。

## 红线

- 不触碰真实 `kb/`；测试只用临时目录。
- 脚本不理解研究材料。
- 不削弱 manifest/source/target/managed-block/plan byte 现有门。
- 不 push/tag/publish。
- commit-per-piece；拿不准立即 STOP-and-report。

## 验收与提交

至少跑 Agent plan、installer、bootstrap、bundle lifecycle 定向套件，`bash -n install.sh`、Python 3.9 AST、`git diff --check`。独立复现每条承重声明。提交清晰 commit，回报 hash、测试结果、worktree 状态。
