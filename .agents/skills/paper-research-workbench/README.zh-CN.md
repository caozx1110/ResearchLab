# Paper Research Workbench

这个 skill 会把 `raw/` 下的论文 PDF 整理成两套清晰分开的结果：

- 用户阅读区：`doc/papers/user/`
- AI 阅读区：`doc/papers/ai/`

用户阅读区里有本地 HTML 入口、可视化关系图、主题图谱、综合 idea 和每篇论文可直接编辑的 `ideas.md`。  
AI 阅读区里是结构化知识库，给其他 skill 读取。

## 你可以用它做什么

- 处理 `raw/` 下新增的论文 PDF，并自动去重
- 生成单篇论文的中文笔记、单篇 idea、可行性初判
- 生成论文关系图，找联读对象和方法脉络
- 从整个论文库出发，给出综合的、前沿的、可执行的 idea 推荐
- 刷新 AI 可读知识库，方便后续让其他 skill 继续工作

## 怎么使用

### 在 Codex 里直接说

```text
使用 $paper-research-workbench 处理 raw/ 下新增论文，并刷新用户阅读区和 AI 知识库。
```

### 直接运行脚本

处理整个 `raw/`：

```bash
python3 .agents/skills/paper-research-workbench/scripts/refresh_workspace.py --input raw
```

只处理一篇论文：

```bash
python3 .agents/skills/paper-research-workbench/scripts/refresh_workspace.py --input raw/你的论文.pdf
```

强制重建已有论文的解析结果和用户区内容：

```bash
python3 .agents/skills/paper-research-workbench/scripts/refresh_workspace.py --input raw --force
```

## 结果怎么看

推荐直接双击项目根目录下的启动器：

- `打开论文知识工作台.command`

它会自动：

- 在后台启动本地服务
- 复用已启动的同一工作台服务，避免重复起多个实例
- 自动打开浏览器到工作台首页
- 当页面关闭后，若约 90 秒内没有新的请求，服务会自动退出

如果你更习惯命令行，也可以手动运行：

```bash
python3 .agents/skills/paper-research-workbench/scripts/open_user_hub.py
```

如果你想改空闲退出时间，也可以传参：

```bash
python3 .agents/skills/paper-research-workbench/scripts/open_user_hub.py --idle-timeout 180
```

服务启动后，浏览器入口是：

- `http://127.0.0.1:8765/doc/papers/user/index.html`
- `http://127.0.0.1:8765/doc/papers/user/graph.html`

底层服务脚本保留在：

- `.agents/skills/paper-research-workbench/scripts/serve_user_hub.py`

用户阅读区主入口：

- `doc/papers/user/index.html`

关系图：

- `doc/papers/user/graph.html`

单篇论文可编辑文件：

- `doc/papers/user/papers/<paper-id>/note.md`
- `doc/papers/user/papers/<paper-id>/ideas.md`
- `doc/papers/user/papers/<paper-id>/feasibility.md`

主题图谱和综合 idea：

- `doc/papers/user/topic-maps/index.md`
- `doc/papers/user/syntheses/frontier-ideas.md`

AI 阅读区：

- `doc/papers/ai/corpus.yaml`
- `doc/papers/ai/graph.yaml`
- `doc/papers/ai/frontier-ideas.yaml`
- `doc/papers/ai/papers/<paper-id>/node.yaml`

UI 资源固定在 skill 资产目录：

- `.agents/skills/paper-research-workbench/assets/ui/hub-template.html`
- `.agents/skills/paper-research-workbench/assets/ui/hub.css`
- `.agents/skills/paper-research-workbench/assets/ui/hub.js`

## 是否需要 Obsidian

不必须，但推荐作为外置编辑器备用。

- 用户阅读区在本地服务模式下支持内嵌 Markdown 实时编辑（note/ideas/feasibility）。
- 如果你习惯用 Obsidian，也可以继续打开 `doc/papers/user/papers/` 里的 Markdown 文件进行编辑。

## 示例 Prompt

```text
使用 $paper-research-workbench 处理 raw/ 下新增论文，生成中文笔记、关系图和综合 idea。
```

```text
使用 $paper-research-workbench 只处理 raw/2501.09747v1.pdf，并告诉我它在现有论文库里最值得联读的 3 篇论文。
```

```text
使用 $paper-research-workbench 检查 raw/ 里有没有重复论文，避免重复解析，并只增量刷新必要文件。
```

```text
使用 $paper-research-workbench 基于整个论文库给我 5 个前沿且可执行的研究 idea，优先考虑 VLA、open-world generalization 和 learning from experience。
```

```text
使用 $paper-research-workbench 刷新本地 HTML 入口，我要直接在用户阅读区查看论文关系图并编辑每篇论文的 ideas.md。
```

```text
使用 $paper-research-workbench 刷新 AI 阅读区，方便我后续让其他 skill 基于这些论文继续工作。
```
