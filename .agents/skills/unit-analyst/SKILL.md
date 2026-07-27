---
name: unit-analyst
description: 统一分析 paper、repo、dataset、blog 与技术笔记 unit；按 kind 路由到既有 evidence-first prepare/Agent-fill/verify 实现，保持历史 owner、偏好与确认回执身份不变。
---

# Unit Analyst

当用户要深读或分析一个 paper、repo、dataset、blog 或人工技术笔记 unit，而不只是把来源入库时，使用这个 facade。

## 共同契约

- 理解来自 runtime Agent；脚本只准备空白结构、搬运 Agent fill、逐字核验证据、检查 currentness/substance 并落盘。没有 Agent 阅读与填写，不得自动产生分类、能力、适用性、可信度、偏好或结论。
- Agent 先读完整材料，再按 implementation 给出的 locator 协议挂短逐字 evidence。图片、文件名、alt text、目录关键词、规模、平台字段与机械摘要都不能自动变成判断。
- prepare 后按旧 implementation operation 获取 task-scoped eligible preferences；无 current selection 使用 neutral defaults。facade 不改写 preference skill/operation、record owner、provenance、diagnostic 或 ConfirmationReceipt 身份。
- verify 后的 judgement 仍为 `pending_user_confirmation`。只有真实用户当前消息授权、真实 signer 与 current evidence 才能确认；不得把“我”、Agent 或来源为用户当作签字。
- source/parse-cache/repo tree、fill binding、record 或 evidence 漂移时 fail closed，旧确认自动失效；不得用兼容路径降低 evidence、substance、containment、CAS、journal 或 checkpoint 门。

## Kind 路由

| kind | 内部 implementation | Agent 填写契约 |
|---|---|---|
| `paper` | `.agents/skills/paper-analyst/scripts/paper.py` | Agent 选择 `method_system / benchmark / survey`，填写类型理由与对应五要素；类型和每个要素都需逐字 evidence。未选分支保持空。 |
| `repo` | `.agents/skills/repo-analyst/scripts/repo.py` | 机械 structure scan 后，Agent 填 `capability / reuse_points / entry_map`；每项引用本地冻结源码的真实 `file:line`。 |
| `dataset` | `.agents/skills/dataset-analyst/scripts/dataset.py` | Agent 填 `positioning / composition / schema_access / suitability_risks`；每项引用冻结数据卡或 parse-cache。 |
| `blog` / human note | `.agents/skills/blog-analyst/scripts/blog.py` | Agent 填 `positioning / key_points / credibility / reusable_explanation`；每项引用冻结 HTML、Markdown 或 parse-cache。 |

四个 implementation namespace 是持久协议身份，不是可发现 skill。不要把它们迁名为 `unit-analyst`，也不要复制一层 facade receipt。

## Agent 流程

1. 确认 canonical unit 已有可用的冻结 source；没有则交 `source-intake`，不要创建空分析。
2. 按 kind 调用上表 implementation 的 prepare。repo 可先执行纯机械 structure scan；paper 的 figure/structure 操作也只能产生机械索引。
3. Runtime Agent 阅读完整材料，只填写该 kind 的必需槽位，并逐条挂合法 evidence。
4. 用同一 implementation verify；失败时修正 fill 或重新 prepare，不能绕过验证直接写 record。
5. 用 `kb review` 向用户呈现已经 verified 且 current 的判断；确认与拒绝仍由统一 public review adapter 执行。

## 路由边界

- 新来源或仅入库：`source-intake`。
- 多来源 survey、taxonomy、趋势与研究缺口：`literature-synthesizer`。
- 只查现有知识库、术语或治理状态：`kb-cli` / `knowledge-base-manager`。
- 需要符号级 repo 深读或图表解释时，Agent 可按需扩展当前 note，但仍须引用真实源码或 source evidence。

默认完整填写当前 kind 的全部要素；只有用户明确要求时才调整阅读侧重，不能因此省略必需槽位。
