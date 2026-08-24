# Evidence audit and review packets

仅在执行 evidence audit 或建立/刷新 review packet 时加载本 reference。这里定义审查输入和可见输出；它不授权决定，也不生成 claim。

## Frozen inputs

开始时解析并冻结以下窄引用：

- `review_id`；
- subject 的 vault-relative Markdown path 与 `claim_id`；
- claim block 当前 bytes/semantic payload；
- 该 claim 明确列出的 evidence IDs；
- 每条 evidence 的可见 block、隐藏 binding、source ID/revision；
- 对应 raw artifact、reader、source map 和 manifest 的当前 digest；
- subject/review 页的 expected digest。

路径必须是 vault 内的普通文件，不跟随 symlink，不接受目录扫描或“最新一个”猜测。ID 缺失、重复、path/ID 不一致或 source revision 无法唯一解析时，audit 为 `blocked`。

## Claim substance and semantic digest

Substantive 由 Agent 对可见 claim 判断，并由结构门拒绝明显空壳：claim ID、非空 claim 文本、class 和至少一个实际陈述必须存在；placeholder、TODO、只有标题、只有状态或只有 evidence 链接不够。脚本不得用字数、关键词或引用数替代语义判断。

`claim-block semantic digest` 的规范 payload 只含：

```text
schema
claim_id
normalized claim text
class
scope
limitations
```

由 Markdown parser 输出 Unicode-normalized、换行/空白稳定的语义值，再以 UTF-8 canonical JSON（sorted keys、无无意义空白）计算 SHA-256。排除 review status、路径、标题层级、链接位置和文件中无关段落；这些排除项不能改变判断含义。claim 文本、class、scope 或 limitations 的语义变化必须改变 digest。

## Evidence audit

对 claim 声明的每个 evidence ID 逐项验证：

1. 可见 Markdown 有非空逐字 quote、source link、人类可读 locator、source ID/revision 和 evidence ID。
2. 隐藏 binding 的 subject path、claim ID、claim digest、evidence ID 和 evidence-block digest 与当前 Markdown 一致。
3. Binding 指向不可变 raw artifact，并且 raw path/digest、reader digest、source-map digest 与该 revision manifest 一致。
4. Typed locator 与来源类型相容；精度不足时只能显式使用 `whole-document`，不得猜 page、line、cell 或 bbox。
5. Exact quote 在绑定 revision 的可信 artifact 中逐字成立；visible quote、binding proof copy 和 quote digest 一致。
6. Evidence integrity 为 `verified`。缺原件、digest mismatch、无法定位或 quote mismatch 均为 `invalid`。
7. Evidence currency 单独检查。出现更新 revision 不销毁旧 integrity，但将需要当前来源的审查标为 `stale`。
8. Evidence IDs 唯一，membership 与 claim 声明完全相等；不允许隐藏 binding 私自添加可见 claim 未引用的证据。

`evidence-set digest` 对按 evidence ID 排序的 canonical items 计算 SHA-256。每个 item 至少包含 evidence-block digest、source ID/revision、raw digest、reader/source-map digest、typed locator、exact-quote digest、integrity 和 currency。quote、locator、revision、membership 或任一承重 digest/state 变化都必须改变结果。

## Audit outcomes

| Outcome | Meaning | Confirm eligible |
|---|---|---|
| `pass` | substantive；所有 evidence integrity verified 且 current | yes |
| `pass-with-limitations` | 机械证据 current；可见 limitations/conflicts 完整保留 | yes，用户必须看到限制 |
| `stale` | 旧 revision 仍可验证，但不满足当前性 | no |
| `invalid` | quote/locator/artifact/binding/digest 不成立 | no |
| `blocked` | subject、ID、文件身份或依赖无法安全解析 | no |

Audit 失败不得删除或修补 claim/evidence。把 finding 写入 review packet，并把修复责任交回 `research-analysis`、`research-capture` 或 `research-vault` 的对应 owner。

## Visible review packet

`Reviews/<review-id>.md` 是普通 Markdown，也是 review 的唯一语义记录。至少包含：

```markdown
---
id: review-example-c001
kind: review
status: awaiting-decision
---

# Review: example C-001

## Subject

- Subject link and Claim C-001
- Class and scope

## Claim under review

Exact visible claim text.

## Evidence under review

> Exact quote

- Evidence ID, source/revision and typed locator

## Audit

- Integrity and currency
- Claim digest and evidence-set digest
- Limitations and conflicts

## Requested decision

Confirm, reject, or defer this claim.

## Current decision

Awaiting an explicit user decision in the current interaction.
```

Packet 必须从当前 subject/evidence 渲染；不得让旧 packet 副本取代源 Markdown。刷新 packet 使用 expected digest/CAS，只改明确目标。用户编辑 packet 后发生冲突时保留用户 bytes 并停止。

## Hidden proof boundary

- `.research/evidence/` 可以重复 exact quote 作为验证 proof，但不得独占 claim text、评价、限制、冲突或决定理由。
- Review packet 不需要隐藏 canonical record；索引/cache 删除后仍可从可见 Markdown 和 source proof 重建。
- 可见 quote 与隐藏 proof 冲突时报告 invalid/stale；不从隐藏副本回填或覆盖可见页面。
- Packet 中的 checkbox 仅是文本，不是当前消息授权。
