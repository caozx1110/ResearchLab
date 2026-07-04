# Research Skills 上手指南（v2）

这份文档只回答三个问题：

1. 先看哪里
2. 怎么开口
3. 什么时候点名 skill

## 0. 第一次用：先初始化（没有 `kb/` 时）

如果当前目录还没有 `kb/`，先跑一次初始化，再做别的：

```bash
python3 .agents/skills/knowledge-base-manager/scripts/kb.py init          # 建 kb/ 骨架 + 索引
python3 .agents/skills/research-config-manager/scripts/config.py init     # 建 user-profile（语言/资源画像）
```

> 只跑第一条也能用，但语言/资源偏好不会被记录——建议两条都跑一次。跑完再看下面的入口页。

## 1. 先看哪里

如果 `kb/` 已经存在，优先看：

1. `kb/index.md`
2. `kb/user/current-state.md`
3. `kb/user/navigation.md`
4. `kb/user/reading-lists/current-reading.md`
5. `kb/user/kb/index.html`

如果你已经知道 `program-id`，再看：

1. `kb/programs/<program-id>/state.yaml`
2. `kb/programs/<program-id>/design/`
3. `kb/programs/<program-id>/reports/`

## 2. 怎么开口最省力

最推荐的是短 prompt。

例如：

```text
请读取当前 v2 knowledge base，判断我现在最该做哪一步，并直接执行。
```

如果你有明确对象：

```text
请把这篇论文先按 v2 流程做轻量入库，再判断是否值得细读。
```

如果你有明确阶段：

```text
请把当前 idea 收敛成可验证问题，并给出最小验证路径。
```

## 3. 什么时候点名 skill

默认可以不点名。

只有在下面几种情况建议点名：

- 你已经知道自己要哪一步
- 你想控制产物落点
- 你想避免路由歧义

例如：

```text
请用 $source-intake 把这篇论文变成 v2 paper unit。
```

```text
请用 $paper-analyst 先做 quick screen，不要直接写完整笔记。
```

```text
请用 $idea-workbench 帮我把这个想法变成可评审的 idea 卡片。
```

```text
请用 $report-author 为 my-program 生成周报和 PPT 素材。
```

```text
请用 $research-navigator 打开本地知识库浏览器，我要在 Workbench 里预览和编辑 Markdown。
```

## 4. 最常见的 6 句 prompt

不知道先做什么：

```text
请用 research-orchestrator 判断我现在最该走哪条 v2 skill 路径，并直接执行。
```

把新论文纳入系统：

```text
请按 v2 流程把这篇论文轻量入库，然后判断是否值得细读。
```

分析一个仓库：

```text
请把这个 repo 变成知识单元，并给出能力边界、训练/推理流程和复用价值。
```

做综述：

```text
请基于当前已入库知识单元，为这个方向生成趋势、方法分类和空白点总结。
```

推进 idea：

```text
请把这个模糊想法变成一个可评审的 idea，并分析新意、可行性和最小验证路径。
```

沉淀实验和报告：

```text
请把这轮实验记录成结构化知识单元，并生成下一步建议和可进入周报的素材。
```

## 5. 常用 skill 速查

- `knowledge-base-manager`：初始化、lint、索引、查询、关联、promotion
- `research-config-manager`：配置、资源边界、自动化开关
- `research-orchestrator`：program 生命周期与路由
- `source-intake`：轻量入库与 source backup
- `paper-analyst`：论文 quick screen 与完整笔记
- `repo-analyst`：仓库能力边界与复用分析
- `blog-analyst`：博客总结与可信度判断
- `literature-synthesizer`：综述、趋势、方法分类、空白点
- `idea-workbench`：idea capture / analyze / review / select
- `method-designer`：selected idea -> method design
- `experiment-workbench`：实验计划、run、诊断、next steps
- `report-author`：周报、阶段总结、PPT 素材
- `research-navigator`：current-state、navigation、reading list、浏览器 Workbench
- `discussion-archivist`：把关键路线讨论沉淀成 durable note
- `wiki-adapter`：通用 wiki / knowledge base 入口

## 6. 一个万能起手式

```text
请读取当前 v2 knowledge base，判断我现在最该做哪一步；默认中文，把高价值结果落到 durable artifact，并且不要自动确认 AI judgement。
```
