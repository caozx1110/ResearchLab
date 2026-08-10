# Paper draft contract

Load only this reference when preparing, reviewing, confirming, or exporting the seven-section paper draft.

## Prepare

1. 要求 current `paper-outline.md` 已存在。
2. 冻结 program 当前 exact selection、outline bytes、current confirmed claims、bibliography catalog 与 figure catalog。
3. 只创建 Introduction / Related Work / Method / Experiments / Results / Discussion / Conclusion 七节空白 fill；不得由脚本生成正文。
4. Catalog 中 citation key 和 figure ref 都必须稳定、可重验；缺少可写 section 的 support 时 fail closed。

## Agent fill and verify

- Agent 按段填写 plain-text prose、原 epistemic claim type、至少一个 current confirmed support claim ref、至少一个 stable citation key 与可选 stable figure ref。
- 禁止 raw LaTeX、虚构 citation、任意 artifact path 或 frozen catalog 外引用。
- `draft-verify` 核验单节正文及 support/citation/figure refs，产生带逐字 evidence receipt 的 pending section judgement。
- 完整正文和引用通过统一 `kb review` 展示，等待真人逐节确认；不存在整篇自签或“一键全部确认”的治理降级。
- outline、上游 claim/receipt/evidence、citation metadata、figure index/assets 或 section bytes 的变化会使 pending/confirmation 失效。

## Export

只有七节都具有 current ConfirmationReceipt 时才可发布。Markdown、LaTeX、`references.bib` 与 publication manifest 在同一个事务中一起成功或完整保留旧版本。

渲染器只做稳定排序、plain-text 转义、citation/figure key 投影；正文必须来自 Agent fill。任一上游或 section receipt stale 时禁止覆盖已有发布件。

## Ownership

Draft section 是 `report-author` 拥有的 program-side judgement，不是 source unit。Confirmation 必须绑定 section identity、content/evidence digest 与 current verification receipt；文件名含 `confirmed` 或状态字符串本身不构成信任。
