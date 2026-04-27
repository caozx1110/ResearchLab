# Workspace Skills Guide (v2)

这个工作区现在使用一套 **knowledge-unit-first** 的科研 skill 体系。

核心变化只有一句话：

> 先把对象变成统一知识单元，再围绕这些知识单元做分析、设计、实验和汇报。

## 1. v2 skill 列表

当前主链路 skill：

1. `knowledge-base-manager`
2. `research-config-manager`
3. `research-orchestrator`
4. `source-intake`
5. `paper-analyst`
6. `repo-analyst`
7. `blog-analyst`
8. `literature-synthesizer`
9. `idea-workbench`
10. `method-designer`
11. `experiment-workbench`
12. `report-author`
13. `research-navigator`
14. `discussion-archivist`
15. `wiki-adapter`
16. `skill-evolution-advisor`

## 2. v2 目录心智模型

```text
raw/                 # immutable raw sources
kb/units/            # papers / repos / blogs / ideas / experiments
kb/programs/         # concrete research programs
kb/synthesis/        # surveys / trends / gaps / taxonomy notes
kb/user/             # current-state / navigation / reading lists / report materials
output/              # polished exports
```

最重要的约定：

- 每个知识单元都要有一个 `record.yaml`
- `record.yaml` 负责状态、确认状态、标签、关联关系和历史
- 详细笔记、评估、诊断可以是附属文件，但不能取代 `record.yaml`

## 3. 最常见工作流

### A. 新材料进入系统

`source-intake` -> `paper-analyst` / `repo-analyst` / `blog-analyst` -> `knowledge-base-manager index`

适合：

- 新论文
- 新仓库
- 新博客或技术文章

### B. 做综述 / 趋势 / 空白点

`literature-synthesizer`

适合：

- 整理研究脉络
- 分析发展趋势
- 发现研究空白点
- 看某个方向最前沿是什么

### C. 想法形成与收敛

`idea-workbench` -> `method-designer`

适合：

- 把模糊 idea 变成研究问题
- 做 novelty / feasibility 分析
- 显式选择最值得推进的 idea
- 生成最小验证方法设计

### D. 实验推进

`experiment-workbench` -> `report-author`

适合：

- 记录实验计划
- 记录 run
- 失败分析
- 下一步建议
- 生成周报 / PPT 素材

### E. 人类重开入口

`research-navigator`

适合：

- 我现在该看什么
- 当前最重要的已确认结论是什么
- 当前 reading list 是什么
- 哪些内容还待确认
- 打开带 Workbench、Markdown 预览/编辑和内置 Codex 的本地浏览器

### F. 通用知识库 / 讨论入口

`wiki-adapter` / `discussion-archivist`

适合：

- 用户只说“加到知识库 / 查 wiki / lint wiki”
- 把一次关键技术路线讨论沉淀成 durable note

## 4. 统一确认规则

默认情况下：

- **事实类基础信息**：可自动入库
- **AI 推断 / AI 评价 / 详细笔记 / 创新性判断 / 失败诊断**：默认 `pending_user_confirmation`
- **idea 演化 / 实验历史 / 周报**：保留历史，不直接覆盖

## 5. 常用 CLI

```bash
python3 .agents/skills/knowledge-base-manager/scripts/kb.py init
python3 .agents/skills/knowledge-base-manager/scripts/kb.py lint
python3 .agents/skills/knowledge-base-manager/scripts/kb.py index

python3 .agents/skills/source-intake/scripts/intake.py search --kind paper --query "humanoid vla recovery"
python3 .agents/skills/source-intake/scripts/intake.py add --kind paper --source raw/example.pdf --maturity lightweight
python3 .agents/skills/paper-analyst/scripts/paper.py screen --paper-id paper-foo
python3 .agents/skills/repo-analyst/scripts/repo.py map-capability --repo-id repo-foo
python3 .agents/skills/blog-analyst/scripts/blog.py summarize --blog-id blog-foo

python3 .agents/skills/idea-workbench/scripts/idea.py capture --title "my idea"
python3 .agents/skills/idea-workbench/scripts/idea.py select --idea-id idea-foo
python3 .agents/skills/method-designer/scripts/method.py design --idea-id idea-foo --program-id my-program

python3 .agents/skills/experiment-workbench/scripts/experiment.py plan --title "baseline" --program-id my-program
python3 .agents/skills/report-author/scripts/report.py weekly --program-id my-program
python3 .agents/skills/report-author/scripts/report.py writing-materials --program-id my-program
python3 .agents/skills/research-navigator/scripts/navigate.py refresh
python3 .agents/skills/research-navigator/scripts/navigate.py open-browser
```

## 6. 最短使用建议

如果你只想记住一句：

```text
先用 source-intake 把对象变成知识单元，再按对象类型交给对应 analyst skill。
```

如果你不知道下一步该用哪个：

```text
请用 research-orchestrator 判断我现在最该走哪条 v2 skill 路径。
```
