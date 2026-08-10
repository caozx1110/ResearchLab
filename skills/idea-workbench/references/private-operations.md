# Private operations

Load only this reference for scaffold ownership, recovery, preference validation, archive, or internal route selection.

## Scaffold ownership

- Analyze、review、discuss 的 fill 文件分别为 `analyze-fill.yaml`、`review-fill.yaml`、`discussion-fill.yaml`，由 owner 创建；路径和 basename 是内部实现，不向用户展示。
- `idea_context`、identity、status、corpus binding、receipt fields 即使为空也由 owner 管理且只读。
- Agent 只填写明确白名单内的 candidate substance、claim/reviewer/rank 和 evidence refs。
- 传入替代 fill 时只接受 unit 根下的安全 basename；拒绝绝对路径、父目录、symlink 和 special node。

## Private operation catalog

- capture；generate prepare/verify；analyze prepare/verify；review prepare/verify；review-assist。
- discuss/spar prepare/verify/confirm/reject。
- select/select-best proposal 与 current-message confirmation/rejection。
- archive：只在明确归档意图下执行，保留 canonical history，不把 archive 当删除。

Routes 由 runtime Agent 在一次自然语言任务内完成。用户不需要知道脚本名、flags、环境变量、内部路径或下一条私有命令。

## Transaction and recovery

- Prepare/verify/confirmation/archive 各自声明 exact targets 并通过 workspace transaction。
- Verify 前重算 record/request/orientation/corpus/preference；write/commit boundary 再重验 identity 与 bytes。
- 首次创建失败不得泄漏空 unit/bundle；更新失败保留旧 canonical artifacts 与 receipts。
- 任一 stale、tamper、evidence failure 或 incomplete journal 先停止并走统一 recovery，不做部分追加。

## Public output

向用户展示自然语言 idea card、evidence、pending judgement 与需要的人类选择；不输出内部 schema、artifact path、raw command 或可绕过 confirmation 的 instructions。需要继续时只给自然语言或公开 `kb <verb>`。
