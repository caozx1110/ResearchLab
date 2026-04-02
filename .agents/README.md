# Workspace Skills Guide

这个目录存放当前工作区的本地 skills 和共享运行库。

- 本地 skill 在 `.agents/skills/`
- 共享脚本库在 `.agents/lib/`
- 科研事实源默认在 `doc/research/`

这些 skill 主要能帮你做 6 类事：

1. 管理科研课题 workflow，包括 program、state、decision、preferences
2. 把论文、网页、代码仓库整理成可复用的共享知识库，并维护论文 topic/tag 体系
3. 为某个具体课题做文献分析、idea 发散、idea 评审和方法设计
4. 解析本地 PDF 论文，搭建持续更新的 paper workspace
5. 分析研究代码仓库结构，生成可读的架构文档
6. 把当前 research workspace 生成人类可读、可自动更新的本地知识库网页

## Theme Profile

research v1.1 现在把“研究主题”从 skill 脚本里拆出来了。

- skill 代码负责通用 workflow、产物格式和 handoff
- 主题相关的短词、tag 规则、taxonomy seed、repo role 词表统一放在 `doc/research/memory/domain-profile.yaml`
- 切换研究方向时，优先更新这份 profile，而不是去 patch 各个 skill 脚本
- 新论文入库时会先用当前 profile 做基础标签，再从标题和摘要里自动补一小组强信号关键词 tag；如果这是一个新主题，这些 tag 会自动出现在 `tag-taxonomy.yaml` 和 `tags.yaml` 里，后续再由 `literature-tagger` 继续清洗

如果你准备从一个方向切到另一个方向，可以直接这样说：

```text
把当前 workspace 的研究主题切到 <your-field>，更新 domain profile，让后续 literature tagging、trend survey、idea generation 和 method design 都按这个新方向工作。
```

这一步通常由 `research-conductor` 协助维护 memory，再由其他 skill 动态读取。

## Typical Flows

常见科研 workflow：

`research-conductor` -> `literature-corpus-builder` -> `literature-tagger` -> `literature-analyst` -> `idea-forge` -> `idea-review-board` -> `method-designer`

选题 guardrail：

- 不要直接从“先做第一个 idea”跳到 `method-designer`
- 先让 `idea-forge` 生成候选，再让 `idea-review-board` 明确写出 `decision.yaml`
- `method-designer` 现在默认只接受显式 `selected` 的 idea

如果你还没决定要做哪个方向：

`research-landscape-analyst` -> `research-conductor` -> `literature-corpus-builder` -> `literature-tagger` -> `literature-analyst`

`repo-cataloger` 可以并行补充可复用代码上下文，再交给 `idea-forge` 或 `method-designer`

如果你想直接把当前 knowledge base 和 program 产物可视化浏览：

`research-kb-browser`

如果需要最新外部信息：

`research-conductor` / `idea-review-board` -> `literature-scout` -> `literature-corpus-builder`

如果要单独深读论文或整理 repo close-reading 笔记：

`research-note-author`

如果要快速摸清代码仓库：

`research-repo-architect`

## Runtime Hygiene

research v1.1 这套 skill 依赖一个稳定的 Python 运行时，至少要能正确读取 YAML，并在需要时解析 PDF。

推荐先让 `research-conductor` 记住一个可用环境：

```text
先检查当前 Python 环境是否满足 research skill 的 YAML 和 PDF 依赖；如果满足，就把它记成默认的 remembered runtime。
```

对应脚本：

```bash
python3 .agents/skills/research-conductor/scripts/manage_workspace.py check-runtime --require-pdf
python3 .agents/skills/research-conductor/scripts/manage_workspace.py remember-runtime --label research-default
python3 .agents/skills/research-conductor/scripts/manage_workspace.py show-runtime
```

如果默认 `python3` 不可靠，也可以通过 remembered runtime 启动别的 skill：

```text
用 remembered runtime 运行 literature-corpus-builder，把 raw/ 里的 PDF 入库。
```

对应脚本：

```bash
python3 .agents/skills/research-conductor/scripts/run_with_runtime.py .agents/skills/literature-corpus-builder/scripts/ingest_literature.py ingest
```

## End-to-End Example

下面给一个完整科研 workflow 示例。假设你的目标是：

`提升 VLA 在 open-world 偏移下的 recovery，同时尽量复用已有仓库。`

这只是一个示例方向；如果你的领域不同，先更新 `doc/research/memory/domain-profile.yaml`，后面的 intake、tagging、trend survey 和 design ranking 会自动跟着新的主题配置走。

### Step 0. 先看领域趋势，决定 program 候选

调用 skill：`research-landscape-analyst`

示例 prompt：

```text
基于当前共享 literature 和 repo library，分析“open-world VLA recovery”这个方向的趋势，给我 3 个候选 program，并尽量区分 broad 和 focused 的做法。
```

生成内容：

- `doc/research/library/landscapes/<survey-id>/landscape-report.yaml`
- `doc/research/library/landscapes/<survey-id>/summary.md`

说明：`summary.md` 里现在会直接带每个 candidate 的 conductor prompt；如果你只是想快速浏览，也可以直接让它列出指定 tag 或方向下的论文 / 仓库及简短总结。

### Step 1. 建立 program

调用 skill：`research-conductor`

示例 prompt：

```text
帮我创建一个新 program，问题是“如何提升 VLA 在 open-world 偏移下的 recovery”，目标是“先找到一个尽量复用现有仓库、可以快速验证的方向”。
```

生成内容：

- `doc/research/programs/<program-id>/charter.yaml`
- `doc/research/programs/<program-id>/workflow/state.yaml`
- `doc/research/programs/<program-id>/workflow/preferences.yaml`
- `doc/research/programs/<program-id>/workflow/open-questions.yaml`

如果你已经在 Step 0 里选中了一个 `candidate program`，也可以这样说：

```text
基于 survey <survey-id> 里的候选 program <program-seed-id>，直接帮我创建真正的 program，并保留它的来源和 seed evidence。
```

### Step 2. 把论文入库

调用 skill：`literature-corpus-builder`

示例 prompt：

```text
把 raw/ 里的新论文入库到共享 literature library，并处理可能的重复项。
```

如果来源先在 `literature-scout` 里：

```text
把这个 search result 里的 shortlisted URL 批量入库，并在过程中打印每条来源的进度和失败项：doc/research/library/search/results/<search-id>.yaml
```

生成内容：

- `doc/research/library/literature/<source-id>/metadata.yaml`
- `doc/research/library/literature/<source-id>/note.md`
- `doc/research/library/literature/<source-id>/claims.yaml`
- `doc/research/library/literature/<source-id>/methods.yaml`
- `doc/research/library/literature/index.yaml`
- `doc/research/library/literature/graph.yaml`

说明：这里的 `claims.yaml` 默认只是 placeholder scaffold，不是已验证 claim。

### Step 3. 整理论文 tag 和 taxonomy

调用 skill：`literature-tagger`

示例 prompt：

```text
把共享 literature library 的 tags 刷新一遍，并把 vision-language-action 统一归到 vla。
```

生成内容：

- `doc/research/library/literature/tags.yaml`
- `doc/research/library/literature/tag-taxonomy.yaml`
- 必要时更新 `doc/research/library/literature/<source-id>/metadata.yaml`

### Step 4. 把候选 repo 入库

调用 skill：`repo-cataloger`

示例 prompt：

```text
把这个本地仓库入库到共享 repo library，并生成可快速判断用途的 summary：/path/to/repo
```

生成内容：

- `doc/research/library/repos/<repo-id>/summary.yaml`
- `doc/research/library/repos/<repo-id>/repo-notes.md`
- `doc/research/library/repos/<repo-id>/entrypoints.yaml`
- `doc/research/library/repos/<repo-id>/modules.yaml`
- `doc/research/library/repos/index.yaml`

### Step 5. 为当前课题生成 literature map

调用 skill：`literature-analyst`

示例 prompt：

```text
基于当前 literature library，为 program <program-id> 生成 literature map，重点关注 open-world recovery、instruction following 和 VLA generalization。
```

生成内容：

- `doc/research/programs/<program-id>/evidence/literature-map.yaml`
- 更新 `doc/research/programs/<program-id>/workflow/state.yaml`

说明：这个阶段会优先参考论文的 `tags`、`topics` 和 `short_summary` 做检索排序。

### Step 6. 生成候选 idea

调用 skill：`idea-forge`

示例 prompt：

```text
基于当前 charter、literature map 和 repo library，为 program <program-id> 生成 4 个候选 idea，优先考虑能复用现有 repo 的方向。
```

生成内容：

- `doc/research/programs/<program-id>/ideas/index.yaml`
- `doc/research/programs/<program-id>/ideas/<idea-id>/proposal.yaml`
- 更新 `doc/research/programs/<program-id>/workflow/state.yaml`

说明：`proposal.yaml` 里会带 `repo_context`，记录 top repo 候选、`short_summary` 和理由。

### Step 7. 评审并选出最值得做的 idea

调用 skill：`idea-review-board`

示例 prompt：

```text
先列出这个 program 下的候选 idea，再协助我审查它们的 novelty、overlap risk 和 evidence gap；先不要自动帮我选。
```

生成内容：

- `doc/research/programs/<program-id>/ideas/<idea-id>/review.yaml`
- `doc/research/programs/<program-id>/ideas/<idea-id>/decision.yaml`
- `doc/research/programs/<program-id>/ideas/<idea-id>/review-assist.md`
- `doc/research/programs/<program-id>/ideas/<idea-id>/revision-assist.md`
- 更新 `doc/research/programs/<program-id>/ideas/index.yaml`
- 必要时更新 `doc/research/programs/<program-id>/workflow/evidence-requests.yaml`
- 更新 `doc/research/programs/<program-id>/workflow/state.yaml`

说明：`idea-review-board` 现在默认是协作式评审，不会自动代替用户选题；只有在你明确要求自动完成选择时，才使用 `select-best` 把某个 idea 标成 `selected`。

### Step 8. 生成 implementation-ready design pack

调用 skill：`method-designer`

示例 prompt：

```text
把已选中的 idea 转成 design pack，优先选择改动最小的宿主 repo，并给出明确的 repo 选择理由、接口改动面和实验矩阵。
```

生成内容：

- `doc/research/programs/<program-id>/design/selected-idea.yaml`
- `doc/research/programs/<program-id>/design/repo-choice.yaml`
- `doc/research/programs/<program-id>/design/interfaces.yaml`
- `doc/research/programs/<program-id>/design/coordination-contracts.yaml`
- `doc/research/programs/<program-id>/design/system-design.md`
- `doc/research/programs/<program-id>/experiments/matrix.yaml`
- `doc/research/programs/<program-id>/experiments/runbook.md`
- 更新 `doc/research/programs/<program-id>/workflow/state.yaml`

### Step 9. 把当前知识库和 program 结果可视化浏览

调用 skill：`research-kb-browser`

示例 prompt：

```text
把当前 doc/research/ 里的共享 literature、repos、tags、landscapes 和 program 产物生成人类可读的本地网页，并在后台静默监听更新。
```

生成内容：

- `doc/research/user/kb/index.html`
- `doc/research/user/kb/snapshot.json`
- `doc/research/user/kb/assets/*`
- `doc/research/user/kb/.runtime/launcher-state.json`
- `doc/research/user/kb/.runtime/build-status.json`

常用入口：

```bash
python3 .agents/skills/research-kb-browser/scripts/open_kb_browser.py
python3 .agents/skills/research-kb-browser/scripts/open_user_hub.py   # legacy alias
python3 .agents/skills/research-kb-browser/scripts/status_kb_browser.py
python3 .agents/skills/research-kb-browser/scripts/stop_kb_browser.py
```

## Minimal Hand-off

如果你想一句话推进整个流程，通常可以先这样说：

```text
帮我围绕“提升 VLA 在 open-world 偏移下的 recovery，同时尽量复用已有仓库”建立一个 program，并告诉我现在最应该先调哪个 skill。
```

如果你连 program 方向都还没定，可以先这样说：

```text
先不要建 program。基于当前共享 literature 和 repo library，帮我分析“open-world VLA recovery”的趋势，并给我 3 个候选 program。
```

然后 agent 一般会按下面顺序继续推进：

`research-conductor` -> `literature-corpus-builder` -> `literature-tagger` -> `repo-cataloger` -> `literature-analyst` -> `idea-forge` -> `idea-review-board` -> `method-designer` -> `research-kb-browser`

## Skill Catalog

### `research-conductor`

作用：创建或恢复一个 research program，必要时直接从 landscape survey 的 `candidate program` 创建真正的 program，维护 `workflow/state.yaml`、decision log、evidence request 和 preferences，并决定下一步该调用哪个 skill。

示例 prompt：

- `帮我创建一个新 program，问题是“如何提升 VLA 的 long-horizon recovery”，目标是先做一个可复现 baseline。`
- `恢复 program open-world-vla，告诉我当前卡在哪一步，下一步最应该做什么。`
- `基于 survey open-world-vla-scan 里的候选 program open-world-vla-recovery-focused，直接创建 program，并保留来源。`

### `literature-corpus-builder`

作用：把 `raw/` 中的 PDF、arXiv/OpenReview/DOI/网页链接规范化进共享文献库，处理去重、review 队列和 canonical 条目，并为每篇论文生成 `short_summary`、`note.md`，以及明确标注为 placeholder 的 `claims.yaml` 脚手架。

示例 prompt：

- `把 raw/ 里的新论文入库，并处理可能的重复项。`
- `把这个 arXiv 链接加入共享 literature library：https://arxiv.org/abs/2501.09747`
- `把 literature library 里现有论文的 short_summary 和 note.md 脚手架刷新一遍。`
- `把 literature library 里现有论文的 claims.yaml 回填成明确的 placeholder 状态，避免误当成已验证 claim。`

### `literature-tagger`

作用：维护共享文献库里的 `topics`、`tags`、`tags.yaml` 和 `tag-taxonomy.yaml`，支持批量重打 tag、人工补 tag、alias 归一化，以及 taxonomy 清理。

示例 prompt：

- `把共享 literature library 的 tags 刷新一遍，并清理明显重复或脏 tag。`
- `给这几篇论文重新打 tag：lit-arxiv-2501-09747v1、lit-arxiv-2502-19417v2。`
- `把 lit-arxiv-2501-09747v1 标成 recovery 和 long-horizon，并保留原来的 tag。`
- `给 literature library 补一个 tag taxonomy，把 vision-language-action 统一归到 vla。`
- `检查当前 tags 有没有别名漂移或不规范命名，并把 taxonomy 应用到全部论文。`

### `literature-scout`

作用：在需要“最新”“外部搜索”“novelty check”时，先把搜索 query、候选 URL 和说明记录到 `library/search/results/`，不直接写入 canonical 文献库。

示例 prompt：

- `帮我搜索最近和 VLA recovery policy 最相关的新论文，先记录搜索结果，不要直接入库。`
- `这个 idea 的 novelty 不确定，帮我做一轮外部文献搜索并保留候选链接。`

### `literature-analyst`

作用：围绕某个 program，从共享文献库中抽取最相关证据，结合 `tags`、`topics` 和 `short_summary` 做检索排序，写出 `evidence/literature-map.yaml`，总结 clusters、gaps、agreements 和 candidate directions。

示例 prompt：

- `基于当前 literature library，为 program open-world-vla 生成 literature map。`
- `帮我总结这个课题最相关的文献脉络、主要空白和可延伸方向。`

### `research-landscape-analyst`

作用：基于当前共享 literature / repo library，对指定领域或方向做趋势总结，生成 candidate program seeds，并支持按 tag 或相关方向列出论文 / 仓库的基本信息和 `short_summary`。生成的 `summary.md` 会直接附带 conductor-ready prompt，方便一键把候选方向变成真正的 program。

示例 prompt：

- `基于当前数据库，分析 open-world VLA recovery 的趋势，并给我 3 个候选 program。`
- `先不要建 program，帮我看看 instruction-following VLA 这个领域现在更适合 broad 方向还是 micro 方向。`
- `列出 tag=reward-learning 的论文，给出基本信息和简短总结。`
- `列出和 open-world recovery 相关的仓库，按相关性排序，并带 short_summary。`

### `research-kb-browser`

作用：把 `doc/research/` 里的共享 literature、repos、tags、landscapes 和 program 级产物生成成本地可视化知识库 UI，并通过后台 daemon 静默监听更新、自动重建、自动刷新已打开页面。

示例 prompt：

- `把当前 research workspace 生成人类可读的本地知识库网页，并在后台自动更新。`
- `打开一个可视化 UI，让我按论文、仓库、tag 和 program 浏览当前 knowledge base。`
- `告诉我 research-kb-browser 当前 daemon 是否在运行；如果没跑就启动它。`

### `repo-cataloger`

作用：把本地 repo 或 GitHub repo 规范化进共享 repo library，处理去重、快照、summary、entrypoints 和 modules，并生成 `short_summary` 与 `repo-notes.md` 快速阅读脚手架。

示例 prompt：

- `把这个本地仓库入库到共享 repo library：/path/to/repo`
- `把这个 GitHub 仓库加入 repo library，并扫描主要入口：https://github.com/example/project`
- `把共享 repo library 里现有仓库的 short_summary 和 repo-notes.md 刷新一遍。`

### `idea-forge`

作用：根据 `charter.yaml`、`literature-map.yaml` 和共享 repo index，生成多个候选 idea 的 `proposal.yaml`。当 repo library 里已经有 canonical repo 时，它会利用 repo 的 `short_summary`、tags、topics 和 entrypoints 给每个 proposal 补一层 `repo_context`，方便后续 method design 直接继承。

示例 prompt：

- `基于当前 charter 和 literature map，为 program recovery-vla 生成 4 个候选 idea。`
- `给我一些更偏落地、尽量复用现有 repo 的 idea proposal。`
- `基于当前 repo library 的 short_summary，给每个候选 idea 推荐最合适的宿主 repo。`

### `idea-review-board`

作用：对候选 idea 做 novelty、overlap risk、evidence gap、kill tests 和 shortlist / park / kill / select 决策。

示例 prompt：

- `评审这个 program 下的所有 idea，并选出最值得进入 method design 的一个。`
- `帮我判断这些 idea 哪些只是换壳复现，哪些真正有新意。`

### `method-designer`

作用：把已选中的 idea 变成 implementation-ready design pack，包括 repo choice、interfaces、system design、experiment matrix 和 runbook。它会优先继承 `proposal.yaml` 里的 `repo_context`，再结合共享 repo library 的 `short_summary`、tags、topics 和 entrypoints 做最终 repo 选择，并把选择理由写回 design 产物。

示例 prompt：

- `把已选 idea 转成 design pack，优先选择改动最小的宿主 repo。`
- `为这个 idea 设计一个最小可证伪的实验矩阵和 runbook。`
- `结合 proposal 里推荐的 repo 和共享 repo 总结，给我一个有明确理由的宿主 repo 选择。`

### `research-note-author`

作用：读取 canonical literature PDF 或 repo 源码快照，生成或刷新 `note.md` / `repo-notes.md`，用于 close reading、证据提炼和后续 idea / design 输入。

示例 prompt：

- `把 lit-arxiv-2501-09747v1 的 note.md 刷新成结构化 close-reading 版本。`
- `帮我重写 repo-nvidia-isaac-gr00t 的 repo-notes.md，强调训练/评测/部署接口。`

### `research-repo-architect`

作用：分析一个或多个研究代码仓库的结构、主流程、配置入口、扩展点和潜在改进方向，输出面向人和 agent 的架构文档。

示例 prompt：

- `帮我分析这个 VLA 仓库的训练、评测和数据流主路径：/path/to/repo`
- `比较这两个 repo 的架构差异，并指出哪个更适合作为我们方法的宿主。`

## How To Ask

你可以直接自然语言提需求，不需要记住脚本命令。下面这几种表达都可以：

- `帮我把这篇论文入库并总结重点`
- `继续推进这个 program 的下一步`
- `用 idea-review-board 评审一下这些 proposal`
- `用 research-repo-architect 看看这个仓库适不适合改`

如果你已经知道想触发哪个 skill，也可以在 prompt 里直接点名它。
