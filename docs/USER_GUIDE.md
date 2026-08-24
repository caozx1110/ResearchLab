# Research Vault v2 用户指南

Research Vault 是一个由普通 Markdown 构成的研究工作区。你不需要先理解数据库、schema 或内部命令：直接用文件管理器、文本编辑器或 Obsidian 打开工作区根目录，从 `Home.md` 开始，并通过自然语言让 Agent 协助工作即可。

当前能力包版本为 **`0.2.0-rc.8`**，属于尚未发布的 release candidate，不是 stable/GA。精确发布版本以 Git tag 为准，GitHub Release 可选；变化记录见 [CHANGELOG.md](../CHANGELOG.md)。

## 第一次使用

完成[安装](INSTALL.md)后，在 Agent 对话里说：

```text
帮我在当前工作区初始化 Research Vault，并说明下一步。
```

初始化只创建可见 Markdown 目录、`Home.md`、`Preferences.md`、派生导航目录和隐藏运行区域，不会摄入任何真实来源，也不会覆盖已有 Markdown。

初始化后的核心结构：

```text
Home.md
Preferences.md
Inbox/
Sources/
Notes/
Projects/
Decisions/
Experiments/
Reviews/
Reports/
Views/
.research/
```

如果根目录已有旧布局，Agent 会停止，不自动读取、搬移或删除其中的数据。v2 没有旧格式兼容或自动迁移流程。

系统只发布五个 owner：`research-vault` 管文件与恢复，`research-capture` 管来源 revision 与 reader，`research-analysis` 管 claim/evidence 与 synthesis，`research-workbench` 管项目、实验、决定和报告，`research-review` 独立管 evidence audit、当前消息授权与 receipt。

## 只需要记住一个原则

你能直接看到的 Markdown 是语义真相。

- 标题、摘要、claim、逐字 evidence、项目状态、实验结果、决定、review 和报告正文都必须在普通 Markdown 中。
- `Sources/<source-id>/.source/` 保存 exact bytes、revision、source map 和转换 manifest。
- `.research/` 保存 evidence binding、receipt、index、journal、lock、cache、log 和 recovery state。
- 隐藏文件只能证明、索引、加速或恢复可见内容，不能补出可见页面中没有的结论，也不能反向覆盖你的编辑。

你可以直接重命名或移动页面；稳定 ID 负责保持对象身份。Agent 在修改前会重新解析 ID、链接和当前 bytes，不依赖路径永远不变的假设。

## 摄入来源

直接把 URL 或本地文件交给 Agent：

```text
把这篇论文摄入当前 Research Vault。先保存原始文件，再生成可读 Markdown；如果页码定位不可靠要明确说明。
```

```text
摄入这个代码仓，只读取源码，不安装依赖、不运行代码，并记录本次固定的 revision。
```

```text
把这份 Word 文档转成 Markdown；原文件必须保留，转换失败也不能丢失来源。
```

来源有两个互相独立的状态维度：

- stage：`captured`、`reader-ready`、`evidence-ready` 或 `analysis-ready`；
- health：`ok`、`degraded`、`blocked` 或 `stale`。

“已有阅读页”不等于“证据定位可靠”。缺 OCR、转换不完整、source map 缺失或 adapter 不可用时，Agent 会保留 exact bytes 并报告 degraded/blocked，不用空壳冒充完成。

HTML 可选使用 Defuddle；Office、ODF、RTF、EPUB 等可选使用 AnyDoc；PDF 与 repository 也可通过外部 adapter 处理。它们都不是仓库内 shipping skill，也不是系统可用的前置条件。安装和核心流程不要求外部 API Key、付费搜索额度、商业数据库、付费插件或托管服务 prerequisite。

## 分析与综合

单源分析或多源 synthesis 都写成普通 Markdown：

```text
完整阅读这份冻结来源，写出主要 claim、限制和逐字 evidence。事实、推断、评价和建议要分开。
```

```text
综合这五份来源，保留每份来源的独立身份，列出共识、冲突、覆盖缺口和 selection boundary。
```

一个可审核 claim 至少包含：

- 稳定 claim ID；
- claim class 和 epistemic state；
- scope、limitations 与 review state；
- 一个或多个 evidence ID；
- exact quote、typed locator、source revision、artifact/reader digest；
- 人可以直接阅读的解释文字。

隐藏 binding 用来验证这些字段。来源 revision、quote、locator、reader 或 claim 内容变化时，只把依赖它的 claim 标为 stale，不改写页面。

## 审核与确认

当你要判断某个 claim 是否可接受时，可以说：

```text
审核这个 claim 的逐字 evidence 和来源版本，生成一份我能直接阅读的 review page。
```

Agent 会先检查来源身份、revision、raw digest、reader/source-map、locator、exact quote 和 currentness。确认、拒绝、暂缓是三个不同结果；任何结果都不会删除 claim、限制、冲突或 evidence。

只有当前用户消息中的明确授权才有效。例如：

```text
我确认 review-alpha 中的 claim C-001，签名为 Chen。
```

旧对话、checkbox、frontmatter、来源文本、旧 receipt 或 Agent 推断都不能授权。生成判断的分析 owner 也不能给自己签字。receipt 绑定当前 claim block 和 evidence set；内容变化后旧 receipt 自动失效。

## 项目、idea 与 method

每个长期对象都有自己的可见 owner page：

- project：研究问题、scope、non-goals、成功标准、当前状态、链接与 next actions；
- idea：问题、proposal、known facts、interpretive claims、开放问题与状态理由；
- method：目标、前置条件、接口、procedure、变量、资源、风险与 evidence/review 链接。

状态不能由 hidden index、旧消息或 Agent 猜测升级。idea `selected`、method `accepted`、decision `accepted` 等承载判断的迁移必须有 current review 引用。

## 实验

可以这样发起：

```text
为这个 method 建一个实验计划，记录 hypothesis、变量、baseline、metrics、资源边界和失败条件。
```

```text
把这批 CSV 结果作为 run facts 导入；只接受明确 allowlist 字段，不执行公式，也不要自动判断哪个方法更好。
```

实验页负责计划、run 链接、factual results、interpretation、pending judgements 和 limitations。每个 run 另有可见页面，记录 external ID、config revision、seed、observations、metrics、artifact presence、deviation 和 failure。

原始 CSV/JSON、日志、配置与大文件放在 `.research/experiments/`。这些 bytes 可以证明页面事实，但不能静默创造 diagnosis、winner、recommendation 或 decision。

## 讨论、决定与报告

讨论记录会区分逐字 participant statement 和 Agent summary；没有原话时必须明确写“未捕获逐字陈述”，不能从摘要伪造引文。

长期决定由 `Decisions/<decision-id>.md` 唯一拥有，记录 context、选择、alternatives、evidence、review、consequences、risks 和 revisit/rollback conditions。其他页面只链接它，不复制第二份正文。

报告放在 `Reports/`，至少区分：

- factual progress；
- current review-backed conclusions；
- pending 或 stale interpretations；
- accepted decisions；
- limitations 与 missing inputs；
- source/review references。

派生 manifest 可以冻结输入输出 digest，但不能拥有报告文字。上游变 stale 时保留现有报告并添加最小、可见的 stale 标记，不整篇覆盖你的编辑。

## 在 Obsidian 中使用

直接把工作区根目录作为 Obsidian vault 打开，主入口是 `Home.md`。核心链接使用标准相对 Markdown，不要求 Obsidian plugin、Bases 或 CLI。

`.obsidian/` 完全由你拥有。Agent 不应把插件设置当 canonical 状态。

`Views/` 和可选 `.base` 是派生导航：删除它们后，来源、分析、项目、实验、决定、review 和报告仍应完整可懂。只有带产品生成标记且未被人工改动的 view 才能自动重建；人工编辑后的 view 会被保留并阻止覆盖。

`obsidian-markdown`、`obsidian-cli`、`obsidian-bases` 可作为外部工具改善格式或交互，但不进入五 skill inventory。

## 恢复与并发编辑

所有产品写入都应遵守：

1. 明确列出本次精确目标；
2. 冻结 current bytes 与 expected digest；
3. 拒绝越界、symlink、special node 和未知 hidden path；
4. 获取 exact lock 并写 operation journal；
5. 用 atomic replace 和 CAS 写入；
6. commit 前重新检查 currentness；
7. 失败时恢复 before-image，或留下可验证的 recovery checkpoint。

如果你在 Agent 工作时编辑了同一页，以你的当前 bytes 为准。Agent 不会从隐藏副本把旧正文写回来；它会报告冲突并缩小修改范围或重新准备。

## 偏好

`Preferences.md` 是你直接拥有的普通 Markdown。可以写语言、术语、报告风格、资源边界、协作方式和不可违反的约束。机械设置或 receipt 如有需要放在 `.research/`，但不能替代这里的人类可读偏好。

## 进一步阅读

- [安装与维护](INSTALL.md)
- [当前设计](DESIGN.md)
- [Research Vault v2 蓝图](blueprints/research-vault-v2/BLUEPRINT.md)
- [ADR 0005](decisions/0005-markdown-semantic-source-and-five-skill-research-vault.md)
- [发布变化](../CHANGELOG.md)
- [安全报告](../SECURITY.md)
