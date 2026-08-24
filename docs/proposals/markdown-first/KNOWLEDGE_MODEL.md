---
title: Markdown-first 最小知识模型
status: proposal
updated: 2026-08-24
tags:
  - proposal
  - knowledge-model
---

# Markdown-first 最小知识模型

## 五类对象

以下路径是目标的人类阅读层示意；当前 development 的物理 canonical 仍是 unit bundle、record 和 evidence contract。

| 对象 | 回答的问题 | 推荐载体 |
|---|---|---|
| Material | 原文是什么？ | `Sources/<id>/index.md` 与按 kind 选择的阅读入口（`document.md`、README、card、manifest 或原始文件） |
| Claim | 我们从材料中理解了什么？ | `Notes/<id>.md` 中带 block ID 的段落 |
| Question | 还不知道什么？ | `Projects/<id>.md` 或 `Notes/<id>.md` |
| Decision | 人决定怎么做，为什么？ | `Decisions/<id>.md` 或项目页中的决定区 |
| Action / Experiment | 做了什么，观察到什么？ | `Experiments/<id>.md` |

这里是**用户词汇层**，不是对现有内部 schema 的静默替换。论文、repo、网页和数据集在用户界面上可以统一称为 Material；当前内部仍有 typed unit、program、synthesis、concept 和 report 合同。若未来要让 Markdown 页面替代这些 canonical artifact，必须另行通过 ADR/Issue 定义映射、迁移和兼容边界。高层体验上，Project 是上下文集合；idea、concept、survey 和 report 可以先作为模板或派生视图，是否保留为内部一等对象不在本 proposal 中决定。

## 页面与 Claim 的粒度

一页承载一个人类可理解的对象。不要为每条 Claim 建一个文件；Claim 是页面中可独立审查的段落，并有稳定 block ID：

```markdown
## 主要限制

该方法的收益依赖固定的检索深度，换用更宽的数据分布后尚未验证。

证据：[[Sources/<paper-unit-id>/document#^evidence-retrieval-depth]]
状态：待审（显示语义；实际确认/版本绑定由系统维护）

^claim-retrieval-boundary
```

这样人读的是连续正文，Agent 仍能复用和发现受影响的判断；证据权威仍属于原始 artifact/locator，只有在阅读层与 source map 当前且唯一时，Markdown block 才提供精确导航。

## 所有权分层

```text
Sources/       原始来源与完整阅读层；raw/revision 不可变，index.md 是机器维护的可重建导航
Notes/         人类理解与批注，canonical、可编辑
Projects/      问题、范围、证据地图和进展，canonical、可编辑
Decisions/     人类选择及理由，canonical、可编辑
Experiments/   运行事实、结果和后续动作，canonical、可编辑
Home.md        人类拥有的首页正文；仅显式 managed 区块可由系统更新
Inbox/         人类捕获区；只有用户点名的文件才进入摄入链
Reviews/       人类 review response sheet；只能在当前对话明确授权后 apply
Views/         全局索引、Review 队列、Bases、报告导航，可重建
_system/       身份、证据绑定、版本、完整性和恢复信息，机器维护
```

系统不得用重建 View 覆盖人类页面，也不得整页重建 `Home.md`。机器需要的 revision、证据定位、确认绑定和恢复记录可以存在 `_system/`，但不形成第二份语义真相。用户可以编辑叙述和链接；受保护的证据定位、身份和确认状态不能靠手改字段绕过治理。

## Reader-facing properties（候选最小词汇）

为了让静态 Markdown 与可选 Bases 对同一批材料说同一种话，目标页面暂采用以下最小词汇；这是下一份 schema ADR 的输入，不是当前 development 的 accepted schema：

`material_id`、`object_type`、`title`、`source_type`、`source_status`、`readiness`、`reader_path`、`projects`、`tags`、`updated`、`needs_review`。

`confirmed`、receipt、evidence digest 和受保护 locator 不属于可手改的升级开关；它们由系统元数据和 Review 合同维护。缺少 Bases 或某个属性时，静态页面仍须能读懂材料状态。

## 两条状态轴

**工作流状态**描述当前工作进度（以下只是人类词汇示例，不是本 proposal 要冻结的统一枚举）：

```text
草稿 → 待读 → 待审 → 已采用 / 已拒绝 / 已暂缓 → 需复核 / 已替代
```

**认识类型**描述内容是什么：

```text
原文事实 | Agent 解释 | 人类确认判断 | 开放问题
```

不要用单一“可信度分数”混淆两条轴。

## 编辑与失效

- 人类编辑是新 revision，不是系统错误；原历史可回看。
- 影响证据、Claim 或 Decision 的编辑会使旧确认进入“需复核”。
- 来源新版本、证据定位变化或上游删除也会让相关判断失效。
- 冲突材料并列保存；系统不自动压成一个“最终真相”。
- 视图过期可以重建；canonical 页面不因视图刷新而被静默改写。

## 可靠性边界

用户不需要了解内部锁、版本回执或操作日志的实现名词，但系统仍需保留同类可靠性能力，确保：

- 多文件动作要么完整提交，要么恢复到上一个完整状态；
- 精确知道哪些文件属于本次操作；
- 失败时不把半份 Source bundle 或半份 Review 结果发布成完成品。

旧版 `record.yaml`、`kb/obsidian/managed/` 等结构在提案接受前继续是当前真相；若接受 Markdown ownership，应把它们定义为只读导入/兼容边界，并通过独立迁移决策避免长期双写两套语义真相。
