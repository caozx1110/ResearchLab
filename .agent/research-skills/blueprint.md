# Research Skills V1.1 Blueprint

## Goals

这套系统服务于科研全流程中的 6 类任务：
- 需求澄清与问题定义
- 方向探索与候选 program 选择
- 文献与仓库知识入库
- idea 生成、评审、筛选
- 技术路线与实现方式确定
- 人类可读的知识库可视化浏览

系统采用 `program-centered` 设计：
- 长期共享知识存放在 `doc/research/library/`
- 某个具体课题存放在 `doc/research/programs/<program-id>/`
- 长期偏好与记忆存放在 `doc/research/memory/`
- intake 与重复确认存放在 `doc/research/intake/`

主题解耦原则：
- skill 脚本负责通用 workflow 和产物契约
- 研究主题相关的短词、tag 推断规则、taxonomy seed、repo role 词表放到 `doc/research/memory/domain-profile.yaml`
- 切换研究方向时，优先改 `domain-profile.yaml`，不要把新主题关键词直接补进 skill 代码

## Skill Set

### `research-conductor`
- 角色：对话总控
- 负责：创建或恢复 program、从 landscape candidate seed 实例化 program、维护 workflow state、记录 decision log、维护 memory 与 preferences、发起 evidence request
- 不负责：深度文献解析、repo 扫描、方法设计

### `literature-corpus-builder`
- 角色：文献入库层
- 负责：接收 `raw/` PDF、本地文件路径、arXiv/OpenReview/DOI/网页链接；下载或搬运原始材料；做精确与模糊去重；写入 canonical literature library
- 不负责：program 级推理与选题决策

### `literature-tagger`
- 角色：文献标签维护层
- 负责：维护 canonical literature 的 `topics`、`tags`、`tags.yaml` 与 `tag-taxonomy.yaml`；支持规则重打 tag、人工补 tag、alias 归一化和 taxonomy lint
- 不负责：下载原始来源、创建 intake、解决重复入库

### `literature-scout`
- 角色：外部知识注入层
- 负责：在需要最新信息时记录外网检索 query、候选来源与筛选结果
- 不负责：直接改写 canonical literature library

### `literature-analyst`
- 角色：program 级文献证据整理
- 负责：从 literature library 中抽取与当前课题最相关的证据，优先利用 `tags`、`topics`、`short_summary` 做检索排序，并形成 `literature-map.yaml`
- 不负责：直接批准或淘汰 idea

### `research-landscape-analyst`
- 角色：shared-library 方向分析层
- 负责：基于当前 literature/repo library 对指定领域做趋势总结、列出相关论文与仓库、并生成 candidate program seeds 供 `research-conductor` 继续落地
- 不负责：直接创建 program、替代 program 级 literature map、或改写 canonical library

### `research-kb-browser`
- 角色：知识库可视化浏览层
- 负责：把 `doc/research/` 里的 shared library、tag taxonomy、landscape survey 和 program 级产物整理成只读、本地可视化知识浏览 UI；支持后台监听更新和自动刷新
- 不负责：改写 canonical metadata、在网页里直接编辑研究 YAML、替代现有 skill 的分析或决策职责

### `repo-cataloger`
- 角色：仓库入库层
- 负责：接收本地 repo 路径或 GitHub URL；下载或复制 repo 到共享 repo library；做去重与基础扫描
- 不负责：最终 repo 选型决策

### `idea-forge`
- 角色：idea 发散层
- 负责：基于 charter、literature map、repo context 生成多个候选 `proposal.yaml`；当 repo library 已具备 `short_summary` 时，应把最相关 repo 的简短理由写入 proposal 级 `repo_context`
- 不负责：替 idea 辩护或做最终选择

### `idea-review-board`
- 角色：idea 评审层
- 负责：novelty check、overlap risk、evidence gap、kill tests、shortlist / park / kill / select 决策
- 不负责：重写 proposal 或偷偷注入外部知识

### `method-designer`
- 角色：实现规划层
- 负责：repo choice、interfaces、system design、experiment matrix、runbook；优先复用 proposal 已推荐的 repo，并结合 canonical repo `short_summary` 做最终排序与理由落盘；当设计天然跨两个 repo 时，还要把 host/supporting split 和 coordination contracts 明确写出来
- 不负责：直接改代码仓库或执行实验

## Shared Data Contracts

共享事实源采用文件系统：
- `doc/research/library/`: 长期共享知识层
- `doc/research/programs/`: 具体课题的工作区
- `doc/research/memory/`: 全局偏好与长期记忆
- `doc/research/intake/`: intake 缓冲与重复确认队列

统一约束：
- 所有 YAML 顶层包含：`id`、`status`、`generated_by`、`generated_at`、`inputs`、`confidence`
- 所有跨文件引用使用稳定 ID：`lit:<source-id>#...`、`repo:<repo-id>#...`、`idea:<idea-id>`
- 所有推理型内容优先写成：`Observed`、`Inferred`、`Suggested`、`OpenQuestions`
- 偏好解析顺序：program preferences > global skill preferences > skill 默认行为
- research v1.1 的共享 YAML 默认要求 `PyYAML` 读取；不得再用简化解析 silently 兜底并继续写入下游产物

详细 schema 参考：
- `doc/research/shared/schemas/shared-data-model.md`
- `doc/research/shared/schemas/workflow-state-schema.md`

## Operational Contracts

为了让 workflow 可恢复、可审计、可交接，所有 research skill 额外遵守下面约束：

- 每次写新的 YAML 产物时，除非确实没有来源，都应把 `inputs` 填成实际使用的文件路径、稳定 ID 或 URL，而不是长期留空。
- 需要推理的 YAML 产物应显式使用 `Observed`、`Inferred`、`Suggested`、`OpenQuestions`，避免把事实、判断和建议混写。
- 稳定引用优先使用 `lit:<source-id>`、`repo:<repo-id>`、`idea:<idea-id>`；若引用具体文件，再补文件路径。
- specialist skill 完成其主产物后，应同步把 `workflow/state.yaml` 推到对应阶段；`research-conductor` 保留手动覆盖与纠偏权。

`workflow/state.yaml` 的字段语义收紧如下：

- `stage`: 当前 program 正在推进的主阶段，而不是最近执行过的任意命令
- `active_idea_id`: 当前正在被生成、评审或实现规划的焦点 idea；如果还在发散多个候选，可以留空
- `selected_idea_id`: 已经被 `idea-review-board` 明确选中的 idea
- `selected_repo_id`: 已被 `method-designer` 选为当前实现宿主 repo 的 canonical ID

阶段推进默认按下面顺序发生：

- `research-conductor`: `problem-framing`
- `literature-analyst`: `literature-analysis`
- `idea-forge`: `idea-generation`
- `idea-review-board`: `idea-review`，选定后推进到 `method-design`
- `method-designer`: 设计包写完后推进到 `implementation-planning`

选题 guardrail 额外明确：

- 不要因为聊天里一句“先做第一个”就跳过 `idea-forge` 和 `idea-review-board`
- `method-designer` 默认只吃显式 `selected` 的 `decision.yaml`

运行时约束也明确下来：

- `research-conductor` 负责记住已验证可用的 Python 解释器到 `doc/research/memory/runtime-environments.yaml`
- 任何读取共享 YAML 的 research v1.1 skill，都应先做运行时预检；涉及 PDF 解析的 skill 还必须验证 `PyPDF2` 或 `pypdf`
- 如果当前 `python3` 缺少这些依赖，skill 应尽早失败并提示使用 remembered runtime，而不是静默降级

## Intake And Canonicalization Rules

### Literature
- `raw/` 只是 PDF 缓冲区，不是知识库
- 成功入库后，源 PDF 必须移动到 `library/literature/<source-id>/source/`
- 文献 library 应维护可刷新的 `index.yaml`、`graph.yaml`、`tags.yaml` 与 `tag-taxonomy.yaml`
- `literature-corpus-builder` 负责 canonical entry 和基础 index/graph；`literature-tagger` 负责持续 tag 维护、alias 规则与 taxonomy 规范
- canonical 文献 metadata 与 `index.yaml` 应保留可快速检索的 `short_summary`；`note.md` 应使用稳定模板，至少包含 quick summary、retrieval cues 和 abstract
- ingest 默认生成的 `claims.yaml` 仅是 placeholder scaffold：应显式标成 `placeholder` / `unverified`，并说明其来源只是 abstract snippet，不能冒充已验证 claim extraction
- 去重分三步：精确匹配 -> 模糊匹配 -> 人工确认
- 模糊命中写入 `intake/papers/review/pending.yaml`
- 已确认重复的来源应并入 canonical 条目，不能创建新的 `source-id`

### Repos
- workspace 内 `raw/` 下的 repo 也视为缓冲区；成功入库后应被消费到 intake/library，而不是继续留在 `raw/`
- 本地 repo 和 GitHub repo 都需要标准化进入 `library/repos/<repo-id>/source/`
- canonical repo `summary.yaml` 与 `index.yaml` 应保留可快速检索的 `short_summary`；`repo-notes.md` 应使用稳定模板，至少包含 quick summary、retrieval cues、structure cues 与 entrypoints
- 去重优先依据 canonical remote、owner/name、git remote 指纹
- 模糊冲突写入 `intake/repos/review/pending.yaml`
- 默认不下载大型数据集、checkpoint 或 release 资产

## Memory And Preferences

双层记忆：
- 全局：`doc/research/memory/user-profile.yaml` 与 `skill-preferences.yaml`
- 运行时：`doc/research/memory/runtime-environments.yaml`
- 主题配置：`doc/research/memory/domain-profile.yaml`
- program 局部：`doc/research/programs/<program-id>/workflow/preferences.yaml`

典型偏好包括：
- 更偏 novelty 还是更偏落地
- 默认是否优先复用已有 repo
- 是否在评审阶段默认要求最新外部文献检查
- 可接受的工程复杂度、算力和数据约束

执行时的读取优先级保持为：

1. program `workflow/preferences.yaml`
2. global `memory/skill-preferences.yaml`
3. skill 默认行为

如果 skill 因缺少偏好而做了关键假设，应在产物的 `OpenQuestions` 或 decision log 中留下痕迹。

## Current Boundaries

V1.1 明确不覆盖：
- 自动实验执行
- 自动论文写作
- 大规模外网抓取与长时间在线爬取
- 浏览器内直接编辑 canonical research YAML

## Next Expansion Options

下一阶段可以扩展：
- `experiment-analyst`: 实验结果复盘与下一轮建议
- `paper-writer`: 论文 outline、related work、method、discussion
- 更严格的 token-efficient 运行规范，例如 top-k evidence loading 和更紧凑的中间产物
