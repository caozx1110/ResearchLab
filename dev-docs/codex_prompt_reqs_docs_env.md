你在 research workspace 开源仓库工作。基线干净树 HEAD efe2134，160 tests 绿。共享运行库在 .agents/lib/research/（核心 core.py，IO yaml_io.py，通用 common.py）；脚本 PYTHONPATH 靠每个脚本顶部的 walk-up 找 .agents/lib。唯一硬依赖 PyYAML。请完成以下三组改动，全部改完后运行 pytest 与几个手工验证，最后 git add -A && git commit。

============================================================
TASK 1 — requirements 收敛为单文件
============================================================
- 把 requirements.txt 改成单一权威文件：核心依赖 `PyYAML>=6` 顶部不注释；其下用注释段列出可选与开发依赖，例如：
    # 核心（必需，首次运行会自动装入受管 .venv）
    PyYAML>=6
    #
    # 可选：paper-analyst 的 PDF 文本 + 图像抽取（缺失时自动降级）。取消注释启用。
    # pypdf
    # PyMuPDF
    # Pillow
    #
    # 开发/测试：运行 pytest 套件。用 `pip install -r requirements.txt pytest`。
    # pytest>=7
- 删除 requirements-optional.txt 和 requirements-dev.txt。
- 更新所有引用这两个文件的地方：
  - CONTRIBUTING.md：`pip install -r requirements-dev.txt && python -m pytest ...` → `pip install -r requirements.txt pytest && python -m pytest ...`
  - .github/workflows/ci.yml：`python -m pip install -r requirements-dev.txt` → `python -m pip install -r requirements.txt pytest`
- grep 确认仓库内无其它对 requirements-optional / requirements-dev 的引用残留。

============================================================
TASK 2 — 用户面只暴露伪 CLI（禁止任何 scripts/*.py）
============================================================
规则：面向用户的文档与工具输出里，只能出现 `kb <verb>` 形式的伪 CLI（含全路径 `.agents/skills/kb-cli/scripts/kb <verb>`，那是伪 CLI 本体，允许）。任何其它脚本路径（kb.py / config.py / navigate.py / intake.py / repo.py / paper.py / orchestrate.py / learnings.py 等 scripts/*.py）都不得出现在用户文档与用户可见输出中。开发者文档 docs/DESIGN.md 例外（保留 raw 脚本），SKILL.md 例外（agent 面，保留 raw 脚本）。

改动：
- README.md：
  - 删除 English Quickstart 里的 venv 三连块（python -m venv / activate / pip install / export RESEARCH_PYTHON）——环境改由脚本自动受管（见 TASK 3），不再要用户手动装。
  - 把 `${RESEARCH_PYTHON:-python3} .agents/skills/knowledge-base-manager/scripts/kb.py init` 与 `.../research-config-manager/scripts/config.py init` 两行，替换为单行 `kb init`。`kb status` 行保留（改成 `kb status`，去掉全路径）。
  - “发布说明”里提到 RESEARCH_PYTHON 的措辞，改为：首次运行自动创建受管 .venv；高级用户可用 RESEARCH_PYTHON 覆盖。
- docs/USER_GUIDE.md：
  - “安装与首次运行”节：删除 venv 三连块；把初始化两条 raw（kb.py init / config.py init）替换为 `kb init`；把 `kb help`/`kb status` 的全路径 raw 替换为 `kb help` / `kb status`。
  - 把 `${RESEARCH_PYTHON:-python3} .agents/skills/research-navigator/scripts/navigate.py refresh` 这类 raw 块删除，保留其上的自然语言“请刷新 research navigator …”。
  - 把 `kb` 快捷入口示例里 `${RESEARCH_PYTHON:-python3} .agents/skills/kb-cli/scripts/kb find ...` / `... kb review` 简化为 `kb find ...` / `kb review`。
  - `kb init` 相关表述从“规划中/当前先用两条命令”改为“统一初始化入口（已可用）”。
- docs/INSTALL.md：
  - “准备 Python”节：把 venv 三连块替换为说明——脚本首次运行会自动创建并使用受管 .venv（含 PyYAML），用户无需手动 venv/pip/export；高级用户可用 RESEARCH_PYTHON 覆盖，RESEARCH_NO_MANAGED_VENV=1 可关闭自动 venv。安装器 preflight 仍会检查一次。
  - “首次运行 KB”节里 `${RESEARCH_PYTHON:-python3} .agents/skills/kb-cli/scripts/kb init` 可保留（伪 CLI 本体），但也可简化为 `kb init`（若 kb 未上 PATH，提示用 `bash install.sh --kb-on-path` 或全路径调用 kb 本体）。不要暴露 kb.py 等其它脚本。
  - “环境变量”表里 RESEARCH_PYTHON 行描述更新为“可选覆盖；默认自动受管 .venv”；新增一行 `RESEARCH_NO_MANAGED_VENV`（设 1 关闭自动 venv，改用当前解释器，需自备 PyYAML）与 `RESEARCH_VENV`（覆盖受管 venv 路径）。
- docs/DESIGN.md：不改脚本示例（开发者文档）。
- .agents/skills/kb-cli/scripts/kb：把 handle_init 末尾 `print("hint: run \`kb.py git-init\` to initialize the nested kb Git repo.")` 改为 `print("hint: run \`kb init --git-init\` to initialize the nested kb Git repo.")`；把 register_init 里 `--git-init` 的 help 文案中的 “转发执行 kb.py git-init” 改为不提 kb.py（例如“初始化后一并执行 git-init”）。

改完 grep 校验：在 README.md docs/USER_GUIDE.md docs/INSTALL.md 与 .agents/skills/kb-cli/scripts/kb 中，除全路径 `.agents/skills/kb-cli/scripts/kb`（伪CLI本体）外，不得再出现任何 `scripts/*.py` 或 `kb.py`/`config.py`/`navigate.py` 字样。

============================================================
TASK 3 — 受管 .venv 自举（写进共享 lib + SKILL，用户零手动安装）
============================================================
目标：任何 skill 脚本被直接以裸 python3 调用时，若当前解释器缺 PyYAML，自动创建并切换到一个项目内受管 .venv（含 PyYAML），用户永远不用手动跑 venv/pip/export。

3.1 新增 .agents/lib/research/bootstrap.py，导出 `ensure_managed_runtime(home: Path | None = None) -> None`：
  - 常量 READY_FLAG = "_RESEARCH_RUNTIME_READY"。
  - venv 目录解析：env RESEARCH_VENV（若设）→ Path(RESEARCH_VENV)；否则 home/".venv"。home 缺省时用调用方传入（脚本传其 walk-up 得到的仓库根）。venv python：POSIX 为 <venv>/bin/python，Windows 为 <venv>/Scripts/python.exe。
  - 逻辑顺序：
    1) os.environ.get(READY_FLAG)=="1" → return。
    2) RESEARCH_PYTHON 若设且该解释器能 `import yaml`（用 subprocess 探测，或当它等于当前解释器时用 importlib.util.find_spec）→ 若当前解释器已是它则 mark READY return；否则 reexec 到它；无论如何 return。
    3) RESEARCH_NO_MANAGED_VENV=="1" → 若当前 importlib.util.find_spec("yaml") 存在则 mark READY return；否则 raise SystemExit（可执行提示：安装 PyYAML 或取消该开关）。
    4) 计算 venv_py。若 venv_py 存在：当前 sys.executable 解析后 == venv_py 解析后 → mark READY return；否则 reexec 到 venv_py。
    5) venv_py 不存在：尝试创建——用 sys.executable 或 "python3" 跑 `-m venv <dir>`，再 `<venv_py> -m pip install --disable-pip-version-check "pyyaml>=6"`（可读 requirements.txt 的核心行，但只需保证装上 pyyaml）。成功 → reexec 到 venv_py。失败（venv/pip 抛异常或 pip 后仍 import 不到 yaml）→ 若当前 importlib.util.find_spec("yaml") 存在则就地 mark READY return（离线兜底，绝不 brick）；否则 raise SystemExit（一句可执行提示，含手动 `pip install pyyaml` 与 RESEARCH_VENV/RESEARCH_PYTHON 覆盖说明，并带上底层异常摘要）。
  - reexec 实现：`os.execve(str(python_exe), [str(python_exe), *sys.argv], {**os.environ, READY_FLAG: "1"})`。reexec 前打印一行 stderr 进度（例如 "[research] bootstrapping managed runtime at <venv> ..."），避免用户以为卡住。
  - mark READY = 设 os.environ[READY_FLAG]="1"。
  - 硬不变量：本函数只应在脚本 __main__ 流程被显式调用，**绝不能在模块 import 时执行任何 venv 创建或 reexec**。函数体不得有 import 时副作用。

3.2 接线：给下列每个脚本，在其顶部 walk-up 定位块（`for candidate in [...]: ... sys.path.insert(...)` 之后、`from research.core import ...` / 其它 research.* 业务 import 之前）插入：
    from research.bootstrap import ensure_managed_runtime
    ensure_managed_runtime(PROJECT_ROOT)
  其中 PROJECT_ROOT 用该脚本 walk-up 得到的变量名（多数脚本是 PROJECT_ROOT；.agents/skills/kb-cli/scripts/kb 里是 DEFAULT_PROJECT_ROOT，用它）。对全部 17 个做 walk-up 的脚本 + kb dispatcher 统一处理。注意：research.bootstrap 的 import 也要在 sys.path.insert 之后。ensure_managed_runtime 调用要放在任何会触发 yaml 使用的代码之前（放在 import 区顶部即可，因为 yaml_io 是惰性 import yaml，import 本身不炸）。

3.3 .gitignore：新增一行 `.venv/`（放在 “Python/cache noise” 段附近）。

3.4 kb doctor（.agents/skills/kb-cli/scripts/kb 的 handle_doctor）：在现有输出后追加打印受管 venv 信息——venv 路径、是否存在、当前解释器是否就是它。可复用 bootstrap 里的 venv 解析函数（把 managed_venv_dir/managed_venv_python 设计成可被 dispatcher import 复用）。

3.5 SKILL 面文档：
  - .agents/lib/research/SCHEMAS.md：新增一节 `## 运行时 <a id="runtime"></a>`，说明：所有 skill 脚本首次运行会自动创建并使用项目内受管 `.venv`（含 PyYAML），用户无需手动 venv/pip/export；`RESEARCH_PYTHON` 可覆盖解释器，`RESEARCH_VENV` 可覆盖 venv 路径，`RESEARCH_NO_MANAGED_VENV=1` 关闭自动 venv（改用当前解释器，需自备 PyYAML）；受管 venv 位于安装本仓库的目录（`.agents` 同级），不纳入版本控制。
  - 各 SKILL.md 顶部的「> 协议参考：…」行，在末尾追加 ` · #runtime`（指向新锚点）。对所有含该协议参考行的 SKILL.md 统一追加；没有该行的 SKILL 可跳过。保留各 SKILL 里现有的 `${RESEARCH_PYTHON:-python3}` 前缀不动。

============================================================
验证（改完必须自测，全部通过再 commit）
============================================================
1) `python -m compileall .agents/skills .agents/lib` 通过。
2) 在带 yaml 的解释器下 `python -m pytest .agents/lib/research/tests -q` 全绿；确认运行 pytest 过程中**没有**在仓库根新建 `.venv`（导入不触发 bootstrap）。若有请修正为“仅 __main__ 调用”。
3) 找一个不带 PyYAML 的解释器（例如临时 `python3 -m venv /tmp/noyaml && /tmp/noyaml/bin/python`，其无 pyyaml），执行 `/tmp/noyaml/bin/python .agents/skills/kb-cli/scripts/kb doctor`：应自动创建仓库根 `.venv` 并 reexec，最终 doctor 显示 yaml available。第二次执行应不再 pip（快）。测完把生成的 `.venv` 删掉再 commit（不要把 .venv 提交）。
4) `RESEARCH_NO_MANAGED_VENV=1` + 一个带 yaml 的解释器：正常运行、不建 venv。
5) grep 校验 TASK 2 的用户文档无 scripts/*.py 残留。
6) governance 红线不得改动：不要动 confirm/evidence/auto 不自签/learning 默认 pending 等逻辑。

完成后 `git add -A`（确保未加入 .venv 与 __pycache__）并 `git commit -m "reqs: single requirements file; docs: expose only kb pseudo-CLI; runtime: managed .venv auto-bootstrap"`。把改动文件清单与每个验证步骤的实际输出写进你的最终回复。
