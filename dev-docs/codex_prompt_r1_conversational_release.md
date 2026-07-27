# R1 Track U — conversational UX / distribution / release handoff

## STEP 0 · base sync（必须先做）

1. 在独立 worktree 核对 clean status 与 HEAD。
2. 基线必须是 `4a857327f7e3d989bfbd604f6879c3350ea3a6e3`；关键模块 kb dispatcher、knowledge-base-manager、updater、ws_sync 均存在。不符 STOP-and-report。
3. 完整阅读根 `AGENTS.md`、主工作区 `temp/SYSTEM_DESIGN_SSOT.md` 的“发布闭环 R1”和本 handoff。

测试解释器用主工作区 `/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python`；worktree 自身没有 `tmp/rvenv`。

## 目标

让最终用户真正只通过自然语言和 `kb <verb>` 交互；公开 stdout 与 agent 内部 protocol 分离且完全不依赖 TTY。同时修复 update source provenance、公开文档/verb/门控漂移和发布工程缺口。

## 文件所有权（只动这些）

- `.agents/skills/kb-cli/scripts/kb`
- `.agents/skills/kb-cli/SKILL.md`
- `.agents/skills/knowledge-base-manager/scripts/kb.py`
- `.agents/skills/knowledge-base-manager/SKILL.md`
- `.agents/lib/research/updater.py`
- `.agents/lib/research/bootstrap.py`
- `install-lib/ws_sync.py`
- `install.sh`
- `.agents/AGENTS.md`
- `README.md`
- `docs/USER_GUIDE.md`
- `docs/DESIGN.md`
- `.github/workflows/ci.yml`
- `.agents/VERSION`
- `CHANGELOG.md`（可新建）
- `SECURITY.md`
- 上述行为专属测试；优先新建 `test_r1_conversational_release.py`，installer/updater 既有测试可按契约更新。

禁止碰：evidence/confirm/records/SCHEMAS/analyzers/report/orchestrator、git_ops/journal/common/sources/intake/config/navigator。

## 必做行为

1. **Public stdout 与 agent protocol 分离**
   - 所有 `kb help/init/doctor/update/status/next/find/add/ingest/review/reject/recall/resume/undo/restore` 公共输出只能自然语言和 `kb <verb>`。
   - 过滤/重写子脚本输出中的 absolute/internal paths、`.agents/skills/.../*.py`、环境变量、裸 flags、`NEXT FOR AGENT:`、`confirm:` 等 agent-only 内容。
   - agent 下一步改为结构化 protocol（JSON/专用结果/内部状态文件均可）；不要简单删除到 Agent 无法继续。默认 human stdout 与 machine channel 必须可分别测试。

2. **No TTY contract**
   - 删除 init/review 的 `isatty()` + `input()` 行为分叉。TTY/非 TTY 对相同参数必须同语义。
   - 需要用户信息/确认时，human stdout 简洁说明需要什么；machine protocol 给 Agent 字段；Agent 自然语言问答后 headless 落盘。

3. **Unified review classifier（kb-manager 半边）**
   - 不再只排 paper hollow；paper/blog/repo 的 awaiting-agent-fill、ready-to-verify、failed-retryable 都不进人工 inbox。
   - public review 只显示真正 ready-for-review 的判断；非 unit judgement 的公开承诺要诚实，若 inbox 仍未统一则文档明确边界，不得声称“所有 pending”。

4. **Updater provenance / fork safety**
   - manifest 记录 `source_origin` 与可选 `source_checkout`；fresh install/update/reinstall 保持来源。
   - updater 优先该 provenance；fork/local 安装绝不静默切回硬编码 canonical origin。旧 manifest 缺 provenance 时明确提示/返回需要选择，不得悄悄换源。
   - 保持只 fetch/pull --ff-only/clone，绝不 push；local drift 检测不弱化。

5. **Runtime/install isolation**
   - bootstrap 不应在普通 `kb` 调用中静默向任意共享 Python pip install；优先受管项目 runtime。若已有安全的显式 opt-out，保留兼容并让 doctor 如实说明。
   - 与 R track 的 common runtime capability 接口兼容；本轨不改 common.py。

6. **Docs / release metadata**
   - 以实际 HELP_MENU 为单源或加 drift test：公开文档列全 15 verbs（含 update/resume/undo/restore），门控默认 fail-closed 语义一致。
   - README/USER_GUIDE 第一入口优先自然语言示例，伪 CLI 是快捷入口；不鼓励内部 skill/script/flag。
   - DESIGN 删除 stale god-file/runtime/manual-venv/default-warning 叙述；能力矩阵与实现一致。
   - CI 加 macOS 支持（至少一组受支持 Python + installer smoke）；保留 Ubuntu matrix。
   - 新建 CHANGELOG，更新 SECURITY 为私下报告入口/支持版本策略（若仓库无真实私密邮箱，可用 GitHub private vulnerability reporting 文案，不伪造地址）。
   - 版本可在 branch 更新到下一候选 semver，但**不要创建 tag**；最终 tag 由主 agent验收后决定。若 updater 不支持 prerelease，不写非法 VERSION。

7. **本轨 checkpoint callers**
   - 若本轨文件有 checkpoint caller，显式传 operation paths；不得依赖 R track 的旧 fallback。

## 红线

- 用户可见输出绝无裸命令/flags/env/internal path/NEXT；`--help` 的显式技术参数页可展示伪 CLI 自身参数，但不得泄漏 owner scripts。
- 不以 TTY 作为交互前提。
- 不让 Agent 失去推进信息；用内部结构化 channel 代替文本泄漏。
- 不触碰真实 `kb/`；不 push；commit-per-piece。
- 不提前打 release tag，不宣称 stable；拿不准版本号则保留并在报告中建议。

## 最低测试 / 承重复现

- installed-copy 逐 verb human stdout forbidden-token scan：`python3`、`.py`、`--<internal>`、`${`、`.agents/`、绝对项目路径、`NEXT FOR AGENT:` 均为 0。
- 同一 init/review 在 PTY 与 pipe 输出/状态语义一致；无 input prompt。
- hollow blog/repo 不进 review，ready-for-review 才进。
- fork/local manifest update 保持 source origin；旧 manifest 明确 need-user-choice。
- install 普通 smoke 不污染共享 interpreter；managed runtime path 可解释。
- README/USER_GUIDE/DESIGN verb/menu drift test；CI YAML 有 macOS job；CHANGELOG/SECURITY/VERSION 一致。
- 跑定向测试、既有 kb dispatcher/docs/updater/installer tests。

## 交付

建议 commits：protocol/output+TTY → review classifier → provenance/runtime isolation → docs/CI/release metadata → tests。最后报告 machine protocol 形态、兼容性和需主 agent 集成的接口；不要 merge/push。
