# Research Skills 端到端用户体验模拟报告

> 模拟日期：2026-07-04  
> 模拟用户：人形机器人 VLA 方向博士生  
> 写入策略：真实 `kb/` 只读，所有科研流程产物均写入 `/tmp` sandbox；本报告是唯一写入真实仓库的产物。

## 一句话结论

这套 workspace research skills 已经能支撑“知识库初始化 → 个性化配置 → 材料入库 → 笔记阅读 → idea 讨论 → 方法设计 → 实验迭代 → 报告材料 → 导航复开”的完整闭环。它最大的价值是把研究过程拆成可追溯的 durable artifacts，并且默认把 AI 判断留在 `pending_user_confirmation`。主要短板集中在四处：`idea.py select` 的确认语义、`report-author` 默认输出仍偏事件索引、`literature-synthesizer` 召回偏保守、`research-navigator` 复开页缺少 blocking evidence 与最新报告入口。

## 模拟设置

主 sandbox：

- `/tmp/research-skill-ux-sim-20260704`

三个并行 subagent sandbox：

- `/tmp/research-skill-ux-sim-20260704-agent-materials`
- `/tmp/research-skill-ux-sim-20260704-agent-method`
- `/tmp/research-skill-ux-sim-20260704-agent-report`

从真实 `kb/` 只读复用的材料：

- `p-humanoid-vla-75b79817`：`Humanoid-VLA: Towards Universal Humanoid Control with Visual Integration`
- `p-whole-bodyvla-vla-3ffbb99f`：`WholeBodyVLA: Towards Unified Latent VLA for Whole-Body Loco-Manipulation Control`
- `p-openvla-open-bf86ee46`：`OpenVLA: An Open-Source Vision-Language-Action Model`，作为 staged 背景材料
- `r-wholebodyvla-fec3572d`：`WholebodyVLA` repo unit

隔离注意：

- 一开始尝试用 `/tmp/.../.agents` 软链指向真实仓库，发现脚本使用 `Path(__file__).resolve()` 会解析回真实仓库根目录，导致命令写向真实 `kb/`。
- 已用精确 diff 恢复误触的时间戳/格式变化，并改为在 `/tmp` 复制 `.agents` 实体目录。
- 这说明后续做 sandbox 演练时不能软链 `.agents`，必须复制或让脚本支持显式 `--root` / `KB_ROOT`。

## 覆盖流程

| 阶段 | 使用 skill | 结果 |
|---|---|---|
| 初始化 | `knowledge-base-manager`, `research-config-manager` | 成功初始化 `/tmp` core `kb/`，写入 profile、runtime preferences、topic seed、candidate pools |
| 个性化配置 | `research-config-manager` | 配置中文优先、advisor-ready summary、high novelty bar、humanoid VLA taxonomy seed |
| source staging | `source-intake` | 成功创建 paper/repo search stage，支持先候选后 materialize |
| 材料入库 | `source-intake`, `paper-analyst` | 两篇 paper materialized，并自动 quick-screen；OpenVLA 保持 staged |
| repo 入库 | `source-intake`, `repo-analyst` | WholebodyVLA repo materialized，后续结构扫描显示代码入口不足 |
| 深读笔记 | `paper-analyst`, `repo-analyst` | 生成 note、structure、capability-map、repo-note、repo-context |
| 综合整理 | `literature-synthesizer` | 能生成 summary/survey，但 query 与 pool 召回偏保守 |
| program 编排 | `research-orchestrator` | 成功创建 program、attach units、登记 open question/evidence request、维护 reporting events |
| idea 讨论 | `discussion-archivist`, `idea-workbench` | 生成多候选 idea、review-assist、discussion note 和 decision-log |
| 方法设计 | `method-designer` | 生成 method、repo-choice、interfaces、experiment-matrix |
| 实验迭代 | `experiment-workbench` | 记录 blocked baseline 与 partial mock harness；run-log/follow-up/diagnosis 分离清楚 |
| 报告撰写 | `report-author` | weekly/stage/writing/PPT materials 可生成，但默认更像事件索引 |
| 导航复开 | `research-navigator` | current-state、navigation、reading-list 可复开，但缺少更强 next-entry 指针 |

## 代表性主流程产物

主 sandbox 中的关键产物：

- Program：`/tmp/research-skill-ux-sim-20260704/kb/programs/humanoid-vla-latent-control/`
- Paper notes：`kb/units/papers/p-humanoid-vla-75b79817/note.md`，`kb/units/papers/p-whole-bodyvla-vla-3ffbb99f/note.md`
- Repo note：`kb/units/repos/r-wholebodyvla-fec3572d/repo-note.md`
- Discussion：`kb/programs/humanoid-vla-latent-control/discussions/选择-narrow-scope-latent-interface-作为一周验证路径.md`
- Selected idea：`kb/units/ideas/i-physics-aware-vla-4751b09f/`
- Method design：`kb/programs/humanoid-vla-latent-control/design/i-physics-aware-vla-4751b09f-method.md`
- Experiment unit：`kb/units/experiments/x-baseline-parity-21d3f99a/`
- Weekly report：`kb/programs/humanoid-vla-latent-control/reports/weekly.md`
- Writing materials：`kb/user/report-materials/humanoid-vla-latent-control-writing-materials.md`

Subagent 补充产物：

- 材料阅读报告：`/tmp/research-skill-ux-sim-20260704-agent-materials-report.md`
- 方法实验报告：`/tmp/research-skill-ux-sim-20260704-agent-method/agent-method-ux-report.md`
- 报告导航验收：`/tmp/research-skill-ux-sim-20260704-agent-report/kb/programs/humanoid-vla-reporting-dryrun/reports/report-navigation-assessment.md`
- skill friction retrospective：`/tmp/research-skill-ux-sim-20260704-agent-report/kb/memory/skill-evolution/retrospectives/20260704-233251-report-navigation-dryrun-friction.md`

## 博士生视角体验

最顺手的是“我不用把研究过程留在聊天里”。每一步都会落成 record、note、workflow YAML、decision-log 或 report materials。第二天重新打开时，可以从 `kb/user/current-state.md`、program `state.yaml` 和 `workflow/reporting-events.yaml` 继续推进。

材料阶段的体验比较自然。`source-intake` 支持先 staging，再 materialize，这符合博士生临时收论文的习惯。quick-screen 自动生成，且 AI 判断默认 pending，不会把“看起来相关”直接变成事实。

idea 到方法阶段的分工清楚。`idea-workbench` 负责候选和 review，`discussion-archivist` 保存讨论过程，`research-orchestrator` 记录拍板，`method-designer` 再把 selected idea 变成 repo choice、interfaces 和 experiment matrix。这个链路很适合导师讨论后的路线沉淀。

实验阶段最有科研操作感。`experiment-workbench` 把 run-log、follow-up 和 diagnosis 分开，恰好对应“事实指标、待办、解释判断”三类信息。模拟中第一轮 baseline parity 被 repo 入口不足阻塞，第二轮 mock harness 得到 partial signal，系统没有把 partial signal 自动升级为方法结论。

报告阶段能用，但需要人类编辑。默认 `weekly.md`、`writing-materials.md` 和 `ppt-materials.md` 能保证信息不丢，但更像事件清单。report subagent 手动改写后可以得到自包含导师周报，说明底层事件流足够，缺的是更强的 polished report renderer。

## 主要发现

### P0：`idea.py select` 的确认语义冲突

现象：

- `idea.py select --confirmed-by ...` 会把 idea record 写成 `confirmation_status: confirmed`。
- 但 idea record 本身包含 AI 生成的 novelty、feasibility、review 等 `inference` / `evaluation` / `user_opinion`。
- `validate_write` 因此警告：AI-derived record 不应整体 confirmed。

影响：

- 用户想确认“我选择推进这个 idea”，并不等于确认“AI 对 novelty/feasibility 的判断都是真的”。
- 当前命令把 selection confirmation 和 content confirmation 混在一起，会削弱确认门控的可信度。

建议：

- 将 idea selection 拆成两个字段或命令语义：`status: selected` 可确认，`confirmation_status` 仍保持 `pending_user_confirmation`。
- 增加一等路径，例如 `idea.py select --selection-confirmed-by ... --keep-content-pending`，或默认就保持内容 pending。
- `kb.py review-queue` 应继续列出 selected-but-content-pending 的 idea，提示用户后续确认 novelty/feasibility。

### P1：`report-author` 默认输出不满足 self-contained weekly 目标

现象：

- `report.py weekly` 成功读取 reporting events，但输出主要是事件列表和 reopen pointers。
- `stage-summary`、`writing-materials`、`ppt-materials` 同样偏索引。
- report subagent 手动改写后，才能形成导师可直接阅读的周报。

影响：

- 当前输出适合“复开索引”，不适合“直接交给导师”。
- 这和 `report-author/SKILL.md` 中 weekly report 要自包含的契约存在落差。

建议：

- 增加 polished weekly renderer，把 events 自动聚合为：背景、输入材料、阶段进展、关键证据、阻塞项、风险、下周计划、provenance。
- 对每条结论标注 evidence level：source fact、run fact、AI inference、pending decision。
- 保留 event dump 作为 appendix 或 `weekly-index.md`，不要作为默认周报主体。

### P1：sandbox 隔离容易被 `.agents` 软链破坏

现象：

- 脚本从 `SCRIPT_PATH = Path(__file__).resolve()` 向上找 `.agents/lib`，软链会解析回真实仓库。
- 在 `/tmp` 用软链 `.agents` 运行 `kb.py init` 时，会定位真实 workspace root。

影响：

- 用户以为自己在 `/tmp` 演练，实际可能写入真实 `kb/`。
- 这对测试、教学、回归演练风险较高。

建议：

- 为所有 research scripts 增加显式 `--root` 或 `RESEARCH_PROJECT_ROOT` 支持。
- 启动时打印 resolved project root 与 kb root，尤其是写命令。
- 在 `kb.py init`、`config.py init` 等高影响命令中，如果 `cwd` 与 resolved root 不一致，给出醒目提示。

### P1：`research-navigator` 复开页还不够“下一步导向”

现象：

- `current-state.md` 能显示 active program、stage、open question 数、evidence request 数。
- 但没有直接列出最新报告路径、blocking evidence 内容、top open question、下一步命令。
- report subagent 认为 paper-writing 复开入口没有被提升到页面顶部。

影响：

- 合作者能找到 program，但还需要再打开多个 YAML/MD 才知道今天该做什么。

建议：

- 每个 active program 展示：latest report、top blocking evidence、top open question、next action、pending confirmations。
- `reading-list` 不只列 papers，也列当前 program 关联 repo/idea/experiment。
- 对 `stage=paper-writing` 或 `report-writing` 的 program，优先展示 report materials。

### P2：`literature-synthesizer` 的召回偏保守

现象：

- `survey --field "humanoid VLA whole-body loco-manipulation" --pool current-reading` 在 subagent sandbox 中成功但选中 0 条。
- 主流程中类似 query 只选中 1 条，尽管 current-reading 有两篇相关 paper。

影响：

- 对博士生来说，“命令成功但几乎空结果”容易误判为知识库没材料。
- 需要用户知道 query token 与 pool/tag/topic 的匹配细节。

建议：

- 对 survey/review 增加 “strict / fuzzy” 模式，默认 fuzzy。
- 空结果时自动建议相邻 query 或展示 pool 中未命中的 top items。
- summary 中说明为什么没有选中，列出过滤条件和被排除样例。

### P2：paper note 的 `draft` 期待与实际产物不完全一致

现象：

- `complete-note --mode draft` 生成结构化草稿，但 subagent 观察到正文仍大量待补，未充分消费 PDF 正文。
- 生成 note/structure 后，record 中 `reading_status` 仍可能是 `unread`。

影响：

- 用户会以为 draft 已是“读过 PDF 的笔记”，但实际更像 scaffold。
- reading status 与 artifact 状态不一致，降低状态可信度。

建议：

- 区分 `scaffold`、`extractive-draft`、`analysis-draft`。
- `complete-note` 后同步更新 `reading_status` 为 `noted` 或 `drafted`。
- 在 note 顶部明确列出读取覆盖范围：metadata only、parse-cache pages、full PDF text、manual source excerpt。

### P2：repo capability 需要更明确标注“资源型 repo”

现象：

- WholebodyVLA repo unit 当前只有 README/assets，`repo-analyst` 能生成 note，但 capability 仍写“general-stack”候选。
- 实验阶段很快发现 baseline parity 被阻塞，因为没有可运行训练/评测入口。

影响：

- method-designer 可以继续选择 repo，但用户要到实验阶段才强烈意识到 repo 不足以当 baseline host。

建议：

- `repo-analyst map-capability` 增加 repo type：paper-page / asset-only / code-release / training-ready / eval-ready。
- `method-designer` 选择 repo 时，如果 repo 没有 entrypoints/training_flow/eval_flow，应把 repo-choice 风险提升为 blocking evidence。

## 有价值的设计点

确认门控是正确方向。paper/repo/idea/method/experiment 的 AI 判断默认 pending，让系统在科研语义上比较可信。

durable artifact 链路很完整。即使报告暂时不够 polished，program state、decision-log、reporting-events、run-log 和 diagnosis 已经能还原研究过程。

skill 边界整体清楚。材料入库、单元分析、综合、idea、method、experiment、report、navigator 的责任没有明显混乱，用户可以按阶段自然推进。

实验记忆设计尤其好。把 run fact、follow-up action、diagnosis inference 分开，比普通聊天记录更适合真正迭代。

独立 Git checkpoint 对研究工作有帮助。每个里程碑自动提交让 `/tmp` sandbox 可以复开，也适合真实长期知识库。不过并行 agent 运行时需要更强锁保护。

## 建议优先级

1. 修正 `idea.py select` 的确认语义，把“选择推进”与“确认 AI 内容判断”拆开。
2. 给所有写脚本增加显式 root 参数或环境变量，避免 sandbox 软链误写真实 `kb/`。
3. 增强 `report.py weekly` 的默认输出，让它按导师周报结构聚合 events。
4. 增强 `research-navigator current-state`，显示最新报告、blocking evidence、top open question 和 pending confirmations。
5. 调整 `literature-synthesizer` 默认召回策略，空结果时给解释和候选提示。
6. 明确 paper note 的覆盖范围，并同步 reading status。
7. 给 repo capability 增加 entrypoint/readiness 分级，method design 前暴露 baseline host 风险。

## 对新用户的建议用法

最稳的使用方式不是一次性“自动做完科研”，而是让系统做 durable scaffolding，用户在关键点拍板：

1. 先用 `source-intake search` 把材料 staged，不急着全量入库。
2. materialize 后先看 `paper.py screen` 和 `repo.py map-capability`，确认是否值得深读。
3. 每个 program 都维护 open questions 和 evidence requests，不把未证实判断写成结论。
4. idea 可以多生成，但 select 之后仍要保留 novelty/feasibility pending。
5. method design 之后先跑 baseline parity，不要直接进入复杂改法。
6. experiment run-log 只写事实，diagnosis 保持 pending，等用户确认。
7. weekly report 目前先当素材索引，再由人或后续 renderer 改写为导师版。

## 结论

这套 skills 已经像一个可用的研究操作系统雏形，而不是单个笔记脚本集合。它最适合帮助博士生把分散材料、想法、讨论、实验和汇报变成可复开的证据链。下一步如果把确认语义、报告生成、导航复开和 sandbox root 控制补齐，用户体验会从“能跑通的研究工作台”提升到“可以放心长期依赖的科研助理”。
