# AGENTS.md — 开发本 skill 系统的工作流

> 本文件面向**在本仓库开发/演进 skill 系统的 agent**（Codex 读 `AGENTS.md`，Claude 读 `CLAUDE.md`——它是指向本文件的软链，同一份内容）。
> **不是**使用 kb 的 end user——那套工作区使用规则在 `.agents/AGENTS.md`（随 `.agents/` 分发树装到用户工作区根 `AGENTS.md`）。
> 它固化一套已验证有效的循环：**定 SSOT → 写 plan/handoff → codex 施工 → 我 review → 回写 SSOT**。任何对 skill 功能/门控/架构的演进都走这个循环。

## 文档所有权（改任何东西前先认清谁管什么）

| 文档 | 管什么 | 铁律 |
|---|---|---|
| `temp/SYSTEM_DESIGN_SSOT.md` | **意图 / 目标架构 / 功能设计**（唯一可信设计源） | 改功能边界/确认门控/架构，**先改它再改代码**；它落后于代码=bug |
| `temp/BACKLOG.md` | 计划 / 待办 / 施工状态 / 时序 | 实时落地状态、逐条进度在这，**不进 SSOT** |
| `.agents/lib/research/SCHEMAS.md` | on-disk 数据模型细节（字段/枚举） | SSOT 下挂；schema 规格写这 |
| `.agents/AGENTS.md` | 工作区运行规则、写作偏好、路由、入库自动驱动（随 `.agents/` 分发给用户 kb 工作区） | SSOT 下挂；面向**用** kb 的 agent |
| `AGENTS.md`（本文件）+ `CLAUDE.md`（软链→`AGENTS.md`） | 本仓库开发/演进 skill 的工作流 | 面向**开发** skill 的 agent（Codex 读 `AGENTS.md` / Claude 读 `CLAUDE.md`） |
| `temp/codex_prompt_*.md` | 单次施工 handoff | 一次性，用完留档 |
| 记忆 `~/.claude/.../memory/` | 跨会话的项目事实/教训 | 里程碑 + 硬教训写这 |

## 循环工作流（每个演进步骤走一遍）

### 1. 定 SSOT（设计是我的活，不外包）
- 任何功能/门控/架构决策，**先在 `temp/SYSTEM_DESIGN_SSOT.md` 落成锁定的设计**（原则/子系统决策/schema 规格）。这是最高杠杆的一步，别跳。
- 有真开放决策才问用户（AskUserQuestion）；能从设计一致性推断的自己定并说明。
- 需要外部事实（工具选型、领域惯例）先查证再写进 SSOT，别拍脑袋。

### 2. 写 plan / handoff（codex 的施工规格）
每个 `temp/codex_prompt_*.md` 必含：
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
