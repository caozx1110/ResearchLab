# Research Skills 上手指南

这份文档是给“想直接用对话推进科研”的人准备的。

如果你拿到的是这个仓库的开源版本，请先记住一件事：

> 仓库本身可以不带现成的 `kb/` 内容；`.agents/`、`AGENTS.md` 和 `docs/` 提供的是 workflow、schema 和技能系统，知识库内容可以在本地初始化后再生成。

你不需要先记住脚本命令，也不需要先理解整个 `kb/` 的实现细节。大多数时候，你只需要：

1. 说清楚目标
2. 说清楚对象
3. 说清楚约束
4. 让 Codex 直接做

如果你只想一句话记住整套系统，请记这一句：

> 先让 Codex 判断“当前最该做哪一步”，再让它直接执行；你主要负责方向和取舍，不负责文件搬运。

## 1. 先建立正确心智

这套系统不是“聊天后什么都留不下”的问答机器人，而是一个会把高价值结果落进工作区的科研操作系统。

它的基本层次是：

```text
kb/
├── intake/       # 暂存输入、判重、审计
├── library/      # canonical 文献 / 仓库 / landscape
├── programs/     # 具体研究方向
├── wiki/         # 跨 program 的查询、索引、日志
├── user/         # 人类入口页、阅读清单、成果入口
└── memory/       # 长期偏好、历史、运行时记忆
```

建议你把它理解成四句话：

- `library/` 负责“资料规范化入库”
- `programs/` 负责“某个研究方向的全过程”
- `wiki/` 负责“全局索引、查询沉淀、日志”
- `user/` 负责“我现在应该先打开什么”

## 2. 我应该先看哪里

如果你是重新打开仓库，建议按这个顺序看：

1. `kb/user/navigation.md`
2. `kb/wiki/index.md`
3. `kb/wiki/log.md`
4. `kb/user/kb/index.html`

如果你已经知道某个 `program-id`，优先看：

1. `kb/programs/<program-id>/workflow/state.yaml`
2. `kb/programs/<program-id>/workflow/reporting-events.yaml`
3. `kb/programs/<program-id>/weekly/`
4. `kb/programs/<program-id>/design/`

## 3. 最实用的提问模板

最推荐的 prompt 结构是 4 段：

```text
目标：
对象：
约束：
输出偏好：
```

例如：

```text
目标：请直接推进 humanoid-vla-wholebody-control 的下一步关键动作。
对象：program_id=humanoid-vla-wholebody-control
约束：不要只分析，要直接落 durable artifact；默认中文；保守一点，不要跳步骤。
输出偏好：只告诉我结论、改了哪些文件、下一步建议。
```

如果你知道自己想显式调用哪个 skill，也可以直接点名：

```text
请用 $literature-analyst 为 humanoid-vla-wholebody-control 生成新的 literature map，并说明入选 source_id 和原因。
```

两种方式都可以：

- 不点 skill：更自然，Codex 会自己路由
- 点 skill：更可控，适合你已经知道自己要哪一步

## 4. 什么时候用哪个 skill

下面是最常用的 research skills 速查表。

| 场景 | 推荐 skill | 主要产物 |
| --- | --- | --- |
| 创建 / 恢复 program | `research-conductor` | `workflow/*`, `wiki/index.md`, `wiki/log.md` |
| 论文 / 博客 / 项目页入库 | `literature-corpus-builder` | `library/literature/<source-id>/` |
| GitHub / 本地 repo 入库 | `repo-cataloger` | `library/repos/<repo-id>/` |
| 深读单篇论文 / 单个 repo | `research-note-author` | `note.md`, `repo-notes.md` |
| 给已有 program 做证据地图 | `literature-analyst` | `evidence/literature-map.yaml` |
| 方向还没定，先扫全局 | `research-landscape-analyst` | `library/landscapes/<survey-id>/` |
| 外部搜新论文 / 博客 / 项目页 | `literature-scout` | `library/search/results/*.yaml` |
| 清理 tags / taxonomy | `literature-tagger` | `tags.yaml`, `tag-taxonomy.yaml` |
| 生成候选 idea | `idea-forge` | `ideas/*/proposal.yaml` |
| 评审 / 排序 / 选择 idea | `idea-review-board` | `review.yaml`, `decision.yaml` |
| 产出 design pack | `method-designer` | `design/*`, `experiments/*` |
| 归档路线讨论 | `research-discussion-archivist` | `discussions/*.md` |
| 记录实验运行与 follow-up | `research-experiment-tracker` | `experiments/runs/*.md` |
| 整理阅读清单 / 成果入口 | `research-deliverable-curator` | `user/navigation.md`, `reading-lists/*`, `reports/*` |
| 生成周报 / 研究摘要 | `weekly-report-author` | `weekly/*.md` |
| 浏览知识库 | `research-kb-browser` | `user/kb/` |
| 复盘 workflow / 改 skill | `skill-evolution-advisor` | `memory/skill-evolution/retrospectives/*` |

## 5. 按场景给你可直接复制的示例

### A. 我刚打开仓库，不知道先做什么

```text
请读取当前工作区状态，判断我现在最该做的 1 件事，并直接执行。默认中文，把结果落到 durable artifact，不要只停在聊天里。
```

### B. 我已经有 program，要恢复现场

```text
请用 $research-conductor 恢复 humanoid-vla-wholebody-control 的当前状态，告诉我：
1. 当前 stage
2. 当前最重要的 blocker
3. 下一步最关键动作
并直接执行那个动作。
```

### C. 我有一篇论文或 arXiv 链接，想入库

```text
请把这篇论文规范化入库，处理重复检查，保留 provenance，并在需要时补充 note。program_id=humanoid-vla-wholebody-control
来源：https://arxiv.org/abs/2501.09747
```

如果你手里是本地 PDF：

```text
请把 `raw/` 里的这篇 PDF 规范化入库，失败不要污染 canonical 目录，并告诉我新建的 source_id。program_id=humanoid-vla-wholebody-control
```

### D. 我只想认真读一篇论文

```text
请用 $research-note-author 深读 `lit-arxiv-2603-03243`，写一份中文精读笔记。重点讲：
1. 它真正解决了什么问题
2. 方法里最值得复用的部分
3. 对我当前 program 最重要的 caveat
```

### E. 我想知道现有文献证据到底支持什么

```text
请用 $literature-analyst 为 humanoid-vla-wholebody-control 刷新 literature map。
要求：
- 说明检索依据
- 说明入选 source_id
- 写清楚 theme、conflict、gap
- 如果证据不够，明确指出要不要转 literature-scout
```

### F. 我现在方向都没定，先别建 program

```text
请用 $research-landscape-analyst 做一个 focused landscape survey，主题是 humanoid whole-body VLA。
我想看到：
- 当前趋势
- 候选 program seeds
- 哪些方向偏大，哪些适合先小范围验证
```

### G. 我怀疑库里缺最新论文

```text
请用 $literature-scout 搜一下最近值得补进来的 humanoid whole-body VLA / language-conditioned control 相关论文。
要求：
- 先写到 search results
- 不要直接写 canonical library
- 标出高置信和低置信候选
```

### H. 我想生成一些 idea

```text
请用 $idea-forge 基于当前 charter、literature map 和 repo context 生成 3-5 个候选 idea。
每个 idea 都要给：
- 核心假设
- 风险
- 最小验证路径
```

### I. 我想挑一个最值得做的 idea

```text
请用 $idea-review-board 评审当前 ideas。
要求：
- 不要只说哪个好
- 要写证据缺口、重叠风险、可证伪性
- 如果证据不够，明确告诉我先补证据而不是硬选
```

### J. 我已经选了方向，要出设计

```text
请用 $method-designer 把已选 idea 转成 design pack。
我想看到：
- repo 选择理由
- 关键接口
- 初始实验矩阵
- 最小可实现路径
```

### K. 我们刚聊完路线，怕结论丢掉

```text
请用 $research-discussion-archivist 把刚才关于 hierarchical VLA + WBC 的讨论沉淀成 durable note。
重点保留：
- 为什么选
- 为什么不选别的
- 还没解决的问题
- 下一步验证动作
```

### L. 我刚跑完实验，想把结果沉淀下来

```text
请用 $research-experiment-tracker 记录这次实验。
program_id=humanoid-vla-wholebody-control
标题：hierarchical interface baseline v0
结果：成功率没有超过 baseline，低层接口对齐不稳定
下一步：先退回更简单的 skill token 接口做对照
```

### M. 我只想知道“现在该打开什么”

```text
请用 $research-deliverable-curator 刷新当前阅读清单和成果入口。
我希望一打开就知道：
- 先看哪篇论文
- 先看哪个设计文件
- 先看哪份周报或总结
```

### N. 我想生成周报

```text
请用 $weekly-report-author 生成最近 7 天的周报。
要求：
- 基于 reporting-events 和 durable artifacts
- 写进展、阻塞、下周计划
- 如果 discussion 或 experiment run 覆盖不足，要明确说出来
```

### O. 我想可视化浏览整个知识库

```text
请用 $research-kb-browser 刷新并打开知识库浏览器，我想从 UI 里浏览当前 literature / repos / wiki / program 状态。
```

### P. 我觉得现在某个 skill 不顺手

```text
请用 $skill-evolution-advisor 复盘这次任务里 research skills 的路由问题。
重点讲：
- 哪个 skill 过宽或过窄
- 哪些手工胶水步骤重复出现
- 最值得优先修的 1-3 个点
```

## 6. 推荐的组合拳

### 组合 1：从新资料到 idea

适合你刚拿到一批论文 / repo，想尽快变成研究问题。

顺序：

1. `literature-corpus-builder` / `repo-cataloger`
2. `research-note-author`
3. `literature-analyst`
4. `idea-forge`
5. `idea-review-board`

示例：

```text
先把这批资料入库并补最关键的 notes，然后给 humanoid-vla-wholebody-control 刷 literature map，最后生成 3 个候选 idea。
```

### 组合 2：从路线讨论到实验

适合你已经有方向，正在快速试方法。

顺序：

1. `research-discussion-archivist`
2. `method-designer`
3. `research-experiment-tracker`
4. `weekly-report-author`

示例：

```text
请先把刚才的技术路线讨论沉淀下来，再把已选方向转成 design pack，最后给我一个实验记录模板和这周的周报草稿。
```

### 组合 3：从混乱现场到可继续工作

适合你隔了几天回来，完全忘了之前做到哪。

顺序：

1. `research-conductor`
2. `research-deliverable-curator`
3. `research-kb-browser`

示例：

```text
请恢复当前 program 状态，给我一个“现在先打开什么”的入口页，然后刷新 KB browser。
```

## 7. 让 Codex 更好用的 8 个技巧

### 技巧 1：一次只推进一个主要目标

不要在一条 prompt 里同时要求：

- 入库
- 深读
- 评审
- 设计
- 周报

更好的方式是“链式推进”：

```text
先完成入库。
```

然后：

```text
再基于新入库结果生成 literature map。
```

### 技巧 2：总是带上 `program_id`

尤其在这些场景里：

- evidence
- ideas
- design
- experiment
- weekly

这样可以减少 Codex 在多个 program 之间猜测。

### 技巧 3：告诉它你要“直接执行”

如果你只说“帮我想想”，系统往往会偏分析。

如果你希望它落文件，直接加一句：

```text
不要只分析，请直接执行并写入 durable artifact。
```

### 技巧 4：告诉它你要“保守”还是“激进”

例如：

```text
保守一点，不要跳步骤。
```

或者：

```text
可以激进一点，优先生成多个备选方向。
```

### 技巧 5：让它显式说明“为什么选这个 skill”

如果你自己也不确定路由是否合理，可以直接问：

```text
先告诉我你准备调用哪些 research skills，以及为什么，然后直接执行。
```

### 技巧 6：要它输出文件路径

这会让你更容易回看。

```text
最后只告诉我：结论、修改的文件路径、下一步建议。
```

### 技巧 7：需要人类可读结果时，优先要页面，不要要 YAML

例如：

- 想快速打开资料：要 `reading-lists/*.md`
- 想快速看成果：要 `reports/*.md`
- 想回顾一周：要 `weekly/*.md`

不要一上来就只盯 `state.yaml` 或 `decision.yaml`。

### 技巧 8：发现不顺手时，及时复盘 skill

如果你连续两三次都觉得“这一步总是要我自己补一句”，就该让 `skill-evolution-advisor` 出场了。

## 8. 常见坑

### 坑 1：把 program 级任务说成 source 级任务

比如你真正想要的是“当前方向有哪些 gap”，却只说“帮我读这篇论文”。

这会导致结果停在 `note.md`，而不是进入 `evidence/literature-map.yaml`。

### 坑 2：把 landscape 和 program 混在一起

- 方向还没定：用 `research-landscape-analyst`
- 已经有 concrete program：用 `literature-analyst`

### 坑 3：把 discussion / experiment 结果留在聊天里

如果一段讨论或一次实验未来还会回看，最好立刻要求：

```text
请把这段讨论沉淀下来。
```

或者：

```text
请把这次实验结果记录下来。
```

### 坑 4：一上来就想“全自动”

最稳的方式不是“让它一次做完所有事”，而是让它：

1. 先判断当前最关键一步
2. 直接执行这一步
3. 再继续下一步

## 9. 如果你真的只想记住 5 句 prompt

```text
请恢复当前 program 状态，判断下一步最关键动作，并直接执行。
```

```text
请把这些资料规范化入库并处理重复；如果值得，顺手补 note。
```

```text
请基于当前 program 刷 literature map，并说明证据支持、冲突和缺口。
```

```text
请生成 / 评审候选 idea，并明确最小验证路径。
```

```text
请把这次讨论 / 实验 / 周报沉淀成 durable artifact，不要只留在聊天里。
```

## 10. 最后一个建议

如果你不知道该怎么开口，就直接发这一句：

```text
请先读取当前状态，判断我现在最该做哪一步，并直接执行；默认中文，把高价值结果落到 durable artifact。
```

这句基本可以作为整个 research workspace 的万能起手式。
