# AGENTS.md — 开发本 skill 系统的工作流

> 本文件面向**在本仓库开发/演进 skill 系统的 agent**（Codex 读 `AGENTS.md`，Claude 读 `CLAUDE.md`——它是指向本文件的软链，同一份内容）。
> **不是**使用 kb 的 end user——那套工作区使用规则在 `.agents/AGENTS.md`（随 `.agents/` 分发树装到用户工作区根 `AGENTS.md`）。
> 它固化一套已验证有效的循环：**定 SSOT → 写 plan/handoff → codex 施工 → 我 review → 回写 SSOT**。任何对 skill 功能/门控/架构的演进都走这个循环。

## 文档所有权（改任何东西前先认清谁管什么）

| 文档 | 管什么 | 铁律 |
|---|---|---|
| `dev-docs/SYSTEM_DESIGN_SSOT.md` | **意图 / 目标架构 / 功能设计**（维护者本地唯一可信设计源） | 改功能边界/确认门控/架构，**先改它再改代码**；它落后于代码=bug |
| `dev-docs/BACKLOG.md` | 计划 / 待办 / 施工状态 / 时序 | 实时落地状态、逐条进度在这，**不进 SSOT** |
| `.agents/lib/research/SCHEMAS.md` | on-disk 数据模型细节（字段/枚举） | SSOT 下挂；schema 规格写这 |
| `.agents/AGENTS.md` | 工作区运行规则、写作偏好、路由、入库自动驱动（随 `.agents/` 分发给用户 kb 工作区） | SSOT 下挂；面向**用** kb 的 agent |
| `AGENTS.md`（本文件）+ `CLAUDE.md`（软链→`AGENTS.md`） | 本仓库开发/演进 skill 的工作流 | 面向**开发** skill 的 agent（Codex 读 `AGENTS.md` / Claude 读 `CLAUDE.md`） |
| `dev-docs/codex_prompt_*.md` | 单次施工 handoff | 一次性，本地留档，不作为当前产品文档 |
| 记忆 `~/.claude/.../memory/` | 跨会话的项目事实/教训 | 里程碑 + 硬教训写这 |

### Git 与发布边界

- `dev-docs/` 是维护者本地、Git-ignored 的设计/施工工作台：SSOT 草案、backlog、一次性 handoff、审查原始记录和历史验收快照都留在这里，不进入 Git 或安装包。
- 稳定且对贡献者、用户或安装后 Agent 有约束力的结论，必须同步到 tracked 的 `AGENTS.md`、`CONTRIBUTING.md`、`docs/`、`CHANGELOG.md`、`.agents/*.md`、`SKILL.md` 或 `SCHEMAS.md`；公共 clone 不能依赖 `dev-docs/` 才能理解当前产品。
- 历史 handoff/audit 是时间点证据，不机械改写旧 commit、旧路径或旧测试数。审查“所有文档”时只把当前文档当现状声明，同时检查历史材料没有被当前文档链接成运行前置。
- 若本地 clone 没有 `dev-docs/`，先从维护者取得当前 SSOT/handoff；不要根据历史 Git 文档猜测未公开设计。

## 开发态禁止自调用 shipping skills

在本仓库设计、开发、审查或修复 `.agents/skills/` 时，shipping skill 是**被开发/被审查的产品源码**，不是当前开发任务的执行规则：

- 不得加载或调用本仓库 `.agents/skills/*/SKILL.md` 来指导其自身设计、施工、review 或外部调研；否则会形成循环依赖与确认偏差。
- 可以把这些 `SKILL.md`、脚本和协议作为普通代码/设计材料直接阅读、检索和比较，但不得让被测 skill 反向决定自己的需求、架构或验收标准。
- 开发态只服从本文件、`dev-docs/SYSTEM_DESIGN_SSOT.md`、`.agents/lib/research/SCHEMAS.md` 与当前 handoff；外部调研使用通用检索/浏览能力，不借用 shipping skill 编排。
- 只有三类场景允许实际调用 shipping skill：在临时工作区执行明确的行为测试、使用全新上下文做冷 acceptance、或用户明确要求测试某个 skill。调用时必须显式说明这是**测试**而不是设计依据。
- 测试调用必须与开发上下文和真实用户数据隔离：只操作临时目录，不触碰真实 `kb/`，不把被测 skill 的自述或输出当作独立验收证据。
- 只有安装到用户工作区后，才由工作区根 `AGENTS.md` 与已安装 skills 接管正常运行态路由。简言之：**开发态把 skill 当产品源码，运行态才把 skill 当操作说明。**

## 循环工作流（每个演进步骤走一遍）

### 1. 定 SSOT（设计是我的活，不外包）
- 任何功能/门控/架构决策，**先在 `dev-docs/SYSTEM_DESIGN_SSOT.md` 落成锁定的设计**（原则/子系统决策/schema 规格）。这是最高杠杆的一步，别跳。
- 有真开放决策才问用户（AskUserQuestion）；能从设计一致性推断的自己定并说明。
- 需要外部事实（工具选型、领域惯例）先查证再写进 SSOT，别拍脑袋。

### 2. 写 plan / handoff（codex 的施工规格）
每个 `dev-docs/codex_prompt_*.md` 必含：
- **STEP 0 base sync**：worktree 常被开在过时旧 commit（历史上是 4 月的 `19b3dce`）。handoff 第一条永远是：核对 HEAD/关键模块是否在，不符则 `git reset --hard <当前 main HEAD>` 再核对，然后才动手。
- **文件所有权**：明列"只动这些"。并行多 track 时**文件面必须 disjoint**（否则合并地狱）——这也是当初做 god-file 拆分的理由：拆开后各 track 各占一文件才能真并行。
- **红线**：绝不碰真实 `kb/`（用户数据，测试用临时目录）；治理红线只加严不放松（禁自签、判断类必留 evidence）；**不 push**（维护者 merge）。
- **反模式边界**（analyzer 类必写）：脚本**绝不理解材料**，只建可填结构+验证证据+过门；理解来自 runtime agent。litmus："给一篇材料+无 agent 就吐判断的函数，删掉"。
- **commit-per-piece**：小步提交（基建常有瞬时 504/流断，大块编辑易掉线；小步提交+每步提交才不丢进度）。
- **STOP-and-report 逃生口**：拿不准/不适配就停下报告，别硬编。

### 3. codex 施工
- 用 Agent 工具 `isolation: "worktree"` 起后台 agent，指向 handoff 文件。
- 并行 track 走各自 worktree，disjoint 文件。
- 瞬时 API 故障（504/流断/看门狗）是基建问题不是代码问题：先看 worktree committed 了什么，再 resume（强调小步提交）；连挂多次考虑我自己接手小改。

### 4. 我 review（**绝不只信 agent 的总结**）
这是最重要的纪律，已多次救场：
- **独立复现每条承重声明**：自己跑测试套件、自己复现它说的 bug/exploit、diff fixture 改动——不看它的话术。
- **复现每个 finding 再动手**：验收/审查报的问题，先自己复现证实。（历史：F4"verify 拒绝 exit 0"是**假警报**——测试只污染了 scaffold 示例行；若照报告改会破坏正确的 exit-1。）
- **验红线**：`git status` 确认真实 `kb/` 未动；治理逻辑零削弱（确认仍强制 --confirmed-by+--evidence）。
- **merge 带撤销点**：merge 前记下 pre-merge HEAD 或打 tag；merge 后跑全量测试确认绿。
- review 曾抓到：过时 worktree base、`confirm_unit` 门漏洞（handoff 范围写窄了）、F4 假警报。

### 5. 回写 SSOT + BACKLOG + 记忆
- **设计级事实回写 SSOT**（顶部状态、原则、子系统决策、新 invariant）。落后即 bug。
- **状态/进度回写 BACKLOG**（里程碑、分数、待办）。
- **里程碑 + 硬教训写记忆**（跨会话）。
- 若这轮暴露出新架构 invariant（如 F-a → "派生证据不可变"），补进 SSOT 对应原则。

## 验收（UX/行为改动的 gate）
- 用**冷 acceptance agent**（全新上下文、没参与开发）按系统自己的文档端到端驱动真实流程，按目标（易用/聪明/自动化）诚实打分。
- 冷 agent 会跑出单元测试测不到的真实工作流 bug（F-a 就是这么被揪出来的）。
- 它报的 finding 同样**先复现再动手**。

## 不变量（贯穿所有循环）
- 理解来自 agent，脚本只搬运+验证（原则1）。
- 每条判断挂逐字 evidence，脚本机器校验（原则2）；`raw/`+全量 parse-cache 是**不可变派生证据**，再派生步骤只读不覆盖。
- 确认门验实质（拒空壳）+ 禁自签 + 判断类必留 evidence（原则3）。
- 自动驱动：入库后 agent 一回合跑完管线，只在两个治理闸口停（确认 AI 判断 / 用户抉择）（原则7）。
- 用户契约（原则8）：skill 的**用户可见输出**只含自然语言 + `kb <verb>` 伪 CLI，绝无裸命令 / `--flag` / `${…}` / 内部路径 / `NEXT FOR AGENT:`；伪 CLI 交互绝不依赖 TTY（一律 agent 中介问答 + headless 落盘）。**改任何面向用户的输出/交互时，把"是否泄漏裸命令或依赖 TTY"当作必查评审项。**
- 确认锚定版本（原则3 ConfirmationReceipt）：确认绑定内容/evidence digest，内容变更自动失效；判断轨写入门 fail-closed；保留原 epistemic 类型。
- 恢复合同：原子写 + operation journal + 锁 + revision/CAS + resume/undo/restore；checkpoint 只收本 op 路径，绝不 `git add -A`。
