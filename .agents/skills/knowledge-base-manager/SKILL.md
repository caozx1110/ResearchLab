---
name: knowledge-base-manager
description: 管理 knowledge base 的统一 schema、索引、链接、taxonomy/topic/pool 治理、review classifier 与生命周期推进。
---

# Knowledge Base Manager

当任务是在维护知识单元协议、索引、治理目录、链接或 lifecycle，而不是深读某一篇 paper / repo / blog 时，使用这个 skill。

## 所有权

- `kb/units/<kind>/<id>/record.yaml`：canonical unit record。
- `kb/config/candidate-pools.yaml` 与 `kb/config/topic-taxonomy.yaml`：治理 catalog。
- `kb/index.yaml` / `kb/index.md`：派生索引。
- `kb/user/` 由 research-navigator 主写；`kb/raw/` 是不可变 source evidence；本 skill 不做材料理解。

任何判断必须保留原 epistemic type。脚本只搬运、验证和过门，不替 Agent 生成结论。

## Review classifier

Public review inbox 只包含真正 `ready_for_review` 且仍待用户确认的 knowledge-unit 判断：

- paper/blog/repo 的 `source_ready`、`awaiting_agent_fill`、`ready_to_verify`、`failed_retryable` 一律不进入人工 inbox。
- 旧记录没有 classifier 字段时保持兼容，但 prepared shell 仍排除；paper 的 `not_started` 可能承载有效 screening 判断，不能误删。
- `find`、public `kb review` 与 batch confirm 必须消费同一筛选结果。
- 当前 inbox 只覆盖 knowledge units；experiment diagnosis、program decision 与 learning 的待确认项由各自 owner 管理，公开说明必须诚实。

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
