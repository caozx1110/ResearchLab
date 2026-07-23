---
name: knowledge-base-manager
description: 管理 knowledge base 的统一 schema、passage 索引、链接、taxonomy/topic/pool 治理、review classifier 与生命周期推进。
---

# Knowledge Base Manager

> 协议参考：`.agents/lib/research/SCHEMAS.md#discovery-retrieval` · `#ownership` · `#confirmation-gate`

当任务是在维护知识单元协议、索引、治理目录、链接或 lifecycle，而不是深读某一篇 paper / repo / dataset / blog 时，使用这个 skill。

## 所有权

- `kb/units/<kind>/<id>/record.yaml`：canonical unit record。
- `kb/config/candidate-pools.yaml` 与 `kb/config/topic-taxonomy.yaml`：治理 catalog。
- `kb/index.yaml` / `kb/index.md`：派生索引。
- `kb/.runtime/search/passages.sqlite3`：可丢弃的 passage FTS5 cache；不是 canonical evidence。
- `kb/user/` 由 research-navigator 主写；`kb/raw/` 是不可变 source evidence；本 skill 不做材料理解。

任何判断必须保留原 epistemic type。脚本只搬运、验证和过门，不替 Agent 生成结论。

历史上误存为 repo 的 Hugging Face dataset 只能走本 owner 的显式 dataset migration：默认先给 dry-run 计划，确认 apply 后在一个 journaled transaction 内改 ID、目录与引用，并支持 undo。旧 confirmation 只保留为审计记录；因为 subject kind/id 已改变，dataset canonical judgement 必须重新填证据、verify 并由用户确认。更新安装包不得静默迁移真实 KB。

## Review classifier

Knowledge Base Manager 负责 knowledge-unit classifier；公共 `kb review` 还通过 shared judgement discovery 聚合其它 owner 的 ready judgement：

- paper/repo/dataset/blog 的 `source_ready`、`awaiting_agent_fill`、`ready_to_verify`、`failed_retryable` 一律不进入人工 inbox。
- 旧记录没有 classifier 字段时保持兼容，但 prepared shell 仍排除；paper 的 `not_started` 可能承载有效 screening 判断，不能误删。
- `find`、public `kb review` 与 batch confirm 对 knowledge unit 必须消费同一筛选结果。
- experiment diagnosis、program decision、idea discussion conclusion 与 method selection 仍由各自 owner 持有和写入；shared discovery 只接收 non-empty canonical claims + current verification 的 side artifact，并把 owner-specific confirm/reject route 交给 kb-cli 私有 protocol。公共 inbox 默认只展示优先级与陈旧度排序后的 Top 3，并说明剩余数量。

## Passage retrieval

- 显式 index mutation 用 deterministic extractor 建完整临时 FTS5 数据库并原子替换；正文只能切段/切窗，不摘要或解释。
- 每个 passage 保存 unit、kind、title、artifact、locator、原文与 source digest；路径必须 project-relative 且通过 containment，拒绝 symlink escape。
- `find` 是只读消费者。cache 缺失、损坏或 stale 时调用同一 extractor 做内存 fallback，绝不在 query path 重建或修改 KB。
- 公开结果最多五段，只显示短原文、unit 和可复开 locator；BM25/internal score、绝对路径与 cache 诊断只留在私有 protocol。
- lexical search 支持同语种与 CJK/ASCII 混合 token，但不承诺翻译、embedding 或跨语言同义召回。

## 分层机械审计

当用户用自然语言要求“检查知识库健康”“看看有没有结构或恢复问题”时，Agent 私下调用本 owner 的 `audit` 操作。它是确定性、只读、零 LLM 的检查，不是新的公开 `kb` 动词：

- 报告层固定为 `schema / integrity / recovery / security / quality`，状态为 `PASS / WARN / FAIL`；只有 `FAIL` 返回非零。
- 它复用原有 lint，并检查 current verification/confirmation binding、未完成 journal、KB Git 中产品拥有的 dirty 文件、完整 paper 的空 metadata/default taxonomy、重复或可疑 figure label、symlink 越界。
- 审计不得 bootstrap workspace、刷新 index、创建 lock/journal 或更改 Git/mtime；空库、干净库和坏库都必须字节级只读。
- 输出只含相对 subject 与脱敏机械摘要，不含绝对路径、原始 source/evidence、用户消息或 traceback；网络、依赖漏洞与语义结论质量不在 D1 范围，必须如实说明不支持。
- Agent 向用户用自然语言概述数量与建议，不直接倾倒 owner JSON；普通公开命令面仍只有既有 16 个 `kb <verb>`。

## Confirmation

- Fact-track 可以在有明确 evidence 与真实人类 actor 时批量确认。
- Judgement-track 必须有实质内容、current verification receipt、逐字 evidence、用户授权原话和 `authorization_source=user_message`。
- Agent 只能忠实转录用户消息，不得自签，也不得把本地 token 检查描述成不可伪造身份认证。
- Confirmation mutation 使用 journal/lock，并把当前 record 与派生 index/catalog 的 exact target paths 交给 checkpoint；空 path set 必须 fail closed。

## 用户入口

优先自然语言，例如“刷新知识库索引”“把这两个条目关联起来”“有哪些判断已经可以让我确认”。需要稳定快捷入口时，只向用户展示：

- `kb init`
- `kb find <关键词>`
- `kb review`
- `kb reject <单元 id>`
- `kb status`
- `kb resume`
- `kb undo`
- `kb restore <操作 id>`

Owner script、Python 命令、环境变量、内部 flags、绝对路径与 Agent protocol 不得进入公开 stdout；由 kb-cli 的私有结构化 channel 传给 runtime Agent。

## 写入约束

- 所有 unit 写入都经过 canonical record validator 和 revision/CAS；调用方不能通过省略 expected revision 绕过并发检查。
- 所有 load-modify-write 使用原子写、journal 与 lock；operation target paths 在 begin 前解析完整。
- Checkpoint 只 stage 本次 operation 的 literal path set，绝不扫描或提交无关 dirty draft。
- AI inference、evaluation 与 user opinion 在合法 confirmation receipt 生成前保持 pending。
- topic/tag/pool/summary 属于可覆盖治理层；history、links 与确认记录保留变更痕迹。
- storage-sync 只处理 KB 数据范围，不重写分发 skill 或工作区根规则。
