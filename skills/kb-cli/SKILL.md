---
name: kb-cli
description: kb 快捷命令入口（伪 CLI），用于把常用 research 操作统一成 kb 动词形式；当用户运行或对 AI 说 kb help/init/doctor/update/obsidian/status/next/find/add/ingest/review/reject/recall/resume/undo/restore 时使用。
---

# kb 快捷命令入口（伪 CLI）

> 协议参考：`.agents/lib/research/SCHEMAS.md#runtime` · `#confirmation-gate` · `#ownership`

`kb-cli` 是 research 系统的薄 dispatcher。自然语言是第一入口；用户也可以使用既有 16 个 `kb <verb>` 快捷形式。底层 owner、真实参数、绝对路径、protocol 与 Agent continuation 永远不进入公开输出。

## Public surface

`help`、`init`、`doctor`、`update`、`obsidian`、`status`、`next`、`find`、`add`、`ingest`、`review`、`reject`、`recall`、`resume`、`undo`、`restore` 是完整公开 verb 集合，不新增别名或公开 flag。

## Operation selector

只加载本次 verb 所需的一项直接参考：

| Operation | Direct reference |
|---|---|
| `help/init/doctor/update/status/next/find/add/ingest/recall` | [Dispatcher, init, and ordinary verbs](references/dispatcher-and-init.md) |
| `review/reject` 与 Obsidian review batch | [Review and confirmation contract](references/review-contract.md) |
| `resume/undo/restore`、失败恢复与公开输出 | [Recovery and public-output contract](references/recovery-and-output.md) |

## Core workflow

1. 识别公开 verb 与 canonical owner；`kb-cli` 不复制 owner 的业务判断或写入逻辑。
2. 普通调用只产生 human stdout。需要跨 owner 续接时，Agent 显式请求私有 `kb-agent-protocol/v1`，读取其中的 `child_results`、`next_actions` 与 `details`，不得转述 raw 内容。
3. 只读 verb 保持真正只读。mutation 必须先加载 routed owner，并继续使用 layout、journal、CAS、confirmation 与 exact checkpoint 机械边界。
4. 一次自然语言请求中自动完成安全的 owner prepare → Agent fill → verify；只在证据不足、当前用户确认或真正的用户选择处暂停。
5. 把结果改写成自然语言；需要用户推进时最多提供既有 `kb <verb>`，不暴露内部 continuation。

## Invariants

- `init` 与 `review` 不读 TTY；terminal 只能展示并要求回到 Agent 对话，不能冒充已收集决定。
- `review` 只展示 verified/current judgement；空壳、stale、ready-to-verify 与 failed-retryable 不进确认 inbox。
- 真实确认要求当前消息授权、真实署名与 evidence；不得自签或绕过 snapshot-bound adapter。
- `add`/`ingest` 根据现有 owner 与 `link_autodrive` 路由；判断确认始终停在用户闸口。
- `help` 与 `doctor` 是缺少完整 runtime 或 workspace rules 时唯一允许的只读救援入口。
- 公开 stdout 禁止脚本、raw command、内部 flag、环境变量、绝对路径、token/digest、owner 参数、`NEXT FOR AGENT:` 或 raw child output。

脚本入口为 `scripts/kb`，只供 runtime Agent 私下执行。
