# Plan: requirements 精简 · 用户面只暴露伪CLI · 受管 .venv 自举

来源：用户三点诉求（2026-07-08）
1. requirements 三个文件 → 精简为一个
2. 面向用户的文档和工具不要暴露除伪 CLI 之外的任何脚本命令行
3. Python 环境规则写进 SKILL 内部，且用户不需要手动安装

基线：HEAD efe2134，160 tests 绿，唯一硬依赖 PyYAML（yaml_io 缺它 RuntimeError，ensure_research_runtime SystemExit，不降级）；PDF 三件套可选优雅降级。

## Task 1 — requirements 收敛为单文件
- `requirements.txt`：核心 `PyYAML>=6` 顶部不注释；下方注释段列 optional（pypdf/PyMuPDF/Pillow）与 dev（pytest>=7），带说明。
- 删除 `requirements-optional.txt`、`requirements-dev.txt`。
- 引用更新：`CONTRIBUTING.md`、`.github/workflows/ci.yml` 由 `-r requirements-dev.txt` → `-r requirements.txt` + 显式 `pytest`。
- install.sh 已引用 requirements.txt，无需改（preflight 保留为兜带）。

## Task 2 — 用户面只暴露伪 CLI
判定线：`kb <verb>`（含全路径 `.agents/skills/kb-cli/scripts/kb`）允许；`kb.py`/`config.py`/`navigate.py`/`intake.py` 等任何 `scripts/*.py` 禁止出现在**用户文档**与**工具输出**。
- README.md：删 venv 三连；quickstart → `kb init` / `kb status`；raw `kb.py init`/`config.py init` → `kb init`。
- docs/USER_GUIDE.md：安装节 venv 块删；raw init/navigate.py/kb 全路径 → `kb ...`/自然语言；`kb init` 表述改为“已可用”。
- docs/INSTALL.md：“准备 Python”节 venv 块 → 说明脚本自动受管 .venv；raw kb 全路径可保留（是伪 CLI 本体）。
- docs/DESIGN.md：开发者文档，保留 raw 脚本。
- kb dispatcher kb:356 hint `kb.py git-init` → `kb init --git-init`；`--git-init` help 文案同改。
- SKILL.md：agent 面，保留 raw 脚本（agent 需要）。不在 task2 范围。

## Task 3 — 受管 .venv 自举（写进共享 lib + SKILL）
新增 `.agents/lib/research/bootstrap.py`：
- `ensure_managed_runtime(home: Path | None = None) -> None`
- venv 位置：`RESEARCH_VENV` 或 `<home>/.venv`，home = 脚本 walk-up 找到的 `.agents` 同级仓库根（可写；随 symlink resolve 回真实 clone）。
- 逻辑：
  1. `_RESEARCH_RUNTIME_READY==1` → return（已重执行过）。
  2. `RESEARCH_PYTHON` 设了且带 yaml → 用它（必要时 reexec），return。
  3. `RESEARCH_NO_MANAGED_VENV==1` → 依赖当前解释器；无 yaml 则 SystemExit（可执行提示）。
  4. venv python 存在：当前即它 → mark ready return；否则 reexec 到它。
  5. venv 不存在：`python -m venv` + `pip install pyyaml>=6`；失败但当前解释器有 yaml → 就地继续（离线兜底）；都不行 → SystemExit 一句可执行提示。
  6. reexec：`os.execve(venv_py, [venv_py, *sys.argv], {**env, READY:1})`。
- 护栏（硬不变量）：
  - 只在脚本 `__main__` 调用；**import 时绝不触发**（pytest 导入 research.* 不得建 venv/reexec）。
  - 幂等：已存在可用 venv → 只 reexec，不 pip。
  - 防死循环：READY flag。
  - 绝不 brick：任何已有 yaml 的解释器可用时不得 SystemExit。
- 接线：17 个脚本 + kb dispatcher 在 walk-up 块之后、`from research.core import` 之前加：
  ```python
  from research.bootstrap import ensure_managed_runtime
  ensure_managed_runtime(PROJECT_ROOT)  # dispatcher 用 DEFAULT_PROJECT_ROOT
  ```
- .gitignore：加 `.venv/`。
- kb doctor：增打印 managed venv 路径 + 是否为当前解释器。
- SKILL 面：SCHEMAS.md 加 `## 运行时 <a id="runtime"></a>` 段（脚本首次运行自动建/用受管 .venv，无需 venv/pip/export；RESEARCH_PYTHON 可覆盖；RESEARCH_NO_MANAGED_VENV 关闭）；各 SKILL「协议参考」行追加 `· #runtime`。

## 验证清单（合并前我亲自跑）
- [ ] 全量 pytest 绿，且运行 pytest **不**在 repo 根产生 `.venv`（import 不触发）。
- [ ] 用 yaml-less 解释器直接 `python3 .agents/skills/.../kb init`：自动建 .venv + 自愈成功。
- [ ] 二次运行不再 pip（幂等、快）。
- [ ] `RESEARCH_NO_MANAGED_VENV=1` 且当前有 yaml → 不建 venv、正常跑。
- [ ] `RESEARCH_PYTHON` 覆盖生效。
- [ ] grep 用户文档无 `scripts/*.py`（DESIGN 除外）。
- [ ] governance 红线未变（confirm 需 evidence、auto 不自签、learning 默认 pending）。
- [ ] requirements 只剩 1 文件，CI/CONTRIBUTING 引用已更新。
