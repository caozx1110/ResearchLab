# Research Skills 上手指南

这份文档只回答三个问题：

1. 先看哪里
2. 怎么开口
3. 什么时候点名 skill

先说结论：

> 你不需要复杂 prompt。大多数时候，一两句话就够了。

## 1. 这套系统是干什么的

它不是普通聊天机器人，而是一个会把高价值结果写回工作区的 research workspace。

默认目录大概是这样：

```text
kb/
├── intake/    # 暂存输入、判重、审计
├── library/   # canonical 文献 / 仓库 / landscape
├── programs/  # 具体研究方向
├── wiki/      # 全局查询、索引、日志
├── user/      # 给人看的入口页
└── memory/    # 偏好和运行时记忆
```

最实用的理解方式只有四句：

- `library/` 管资料入库
- `programs/` 管某个课题的全过程
- `wiki/` 管全局索引和沉淀
- `user/` 管“我现在先看什么”

## 2. 重新打开仓库时先看哪里

如果 `kb/` 已经存在，优先看这几个入口：

1. `kb/user/navigation.md`
2. `kb/wiki/index.md`
3. `kb/wiki/log.md`
4. `kb/user/kb/index.html`

如果你已经知道某个 `program-id`，优先看：

1. `kb/programs/<program-id>/workflow/state.yaml`
2. `kb/programs/<program-id>/workflow/reporting-events.yaml`
3. `kb/programs/<program-id>/weekly/`
4. `kb/programs/<program-id>/design/`

## 3. 怎么开口最省力

最推荐的是短 prompt。

例如：

```text
请先读取当前状态，判断我现在最该做哪一步，并直接执行。
```

如果你想再明确一点，补一个对象就够了：

```text
请恢复 humanoid-vla-wholebody-control 的当前状态，并直接推进下一步。
```

如果你有明确约束，再多补一行：

```text
默认中文，结果尽量落到 durable artifact，不要只停在聊天里。
```

也就是说，最常见的结构其实只有三块：

- 目标
- 对象
- 约束

不是每次都要写完整模板。

## 4. 什么时候要点名 skill

默认可以不点名，让 Codex 自己判断。

只有下面几种情况，建议直接点名：

- 你已经知道自己要哪一步
- 你想控制产物落点
- 你想避免路由歧义

比如：

```text
请用 $literature-analyst 为 <program-id> 刷新 literature map。
```

```text
请用 $idea-review-board 评审当前 ideas。
```

```text
请用 $research-kb-browser 刷新并打开知识库浏览器。
```

## 5. 最常见的 6 句 prompt

不知道先做什么：

```text
请先读取当前状态，判断我现在最该做哪一步，并直接执行。
```

恢复某个 program：

```text
请恢复 <program-id> 的当前状态，并直接推进下一步。
```

把论文或 PDF 入库：

```text
请把这篇论文规范化入库，并处理重复。
```

刷新证据地图：

```text
请用 $literature-analyst 为 <program-id> 刷新 literature map。
```

生成或评审 idea：

```text
请基于当前 program 生成候选 idea，并给出最小验证路径。
```

沉淀讨论、实验或周报：

```text
请把这次讨论 / 实验 / 周报沉淀成 durable artifact，不要只留在聊天里。
```

## 6. 常用 skill 速查

只记这些最常用的就够了：

- `research-conductor`：创建或恢复 program，判断下一步
- `literature-corpus-builder`：论文、网页、项目页入库
- `repo-cataloger`：本地或 GitHub 仓库入库
- `research-note-author`：深读单篇论文或单个 repo
- `literature-analyst`：为已有 program 生成 literature map
- `research-landscape-analyst`：方向还没定时先做趋势扫描
- `idea-forge`：生成候选 idea
- `idea-review-board`：评审和筛选 idea
- `method-designer`：把已选 idea 变成 design pack
- `research-kb-browser`：可视化浏览整个知识库

更完整的列表看 [Skills Guide](SKILLS_GUIDE.md)。

## 7. 两个最常见的误区

误区一：一上来就把 prompt 写得很长。

更好的做法是先说清“你要什么”，其余细节让 Codex 在当前工作区里补上下文。短 prompt 往往更稳，也更容易反复迭代。

误区二：把高价值结果留在聊天里。

如果某段讨论、某次实验、某份总结之后还会回看，就直接要求它沉淀成文件。

## 8. 万能起手式

如果你真的不知道怎么开口，就发这一句：

```text
请先读取当前状态，判断我现在最该做哪一步，并直接执行；默认中文，把高价值结果落到 durable artifact。
```
