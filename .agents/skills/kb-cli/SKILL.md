---
name: kb-cli
description: kb 快捷命令入口（伪 CLI），用于把常用 research 操作统一成 kb 动词形式；当用户运行或对 AI 说 kb help/init/doctor/update/status/next/find/add/ingest/review/reject/recall/resume/undo/restore 时使用。
---

# kb 快捷命令入口（伪 CLI）

`kb-cli` 是 research 系统的薄 dispatcher。用户只接触自然语言和 `kb <verb>`；底层 owner、真实参数、绝对路径和 Agent 下一步都不得出现在公开 stdout。

## 用户交互

用户可以直接说“帮我初始化研究知识库”“把这个 repo 入库”“有哪些判断需要我确认”，也可以使用以下 15 个快捷动词：

- `kb help`
- `kb init`
- `kb doctor`
- `kb update`
- `kb status`
- `kb next`
- `kb find <关键词>`
- `kb add <链接或路径>`
- `kb ingest <链接或路径>`
- `kb review`
- `kb reject <单元 id>`
- `kb recall`
- `kb resume`
- `kb undo`
- `kb restore <操作 id>`

自然语言是第一入口；伪 CLI 只是可预测的快捷入口。

## Agent protocol

- 普通调用只打印 human stdout，并保持只读 verb 真正只读。
- Runtime Agent 调用 dispatcher 时，应显式请求一个位于 `kb/.runtime/` 的私有 JSON protocol 目标；读取 `kb-agent-protocol/v1` 后继续 owner 步骤。该文件是 gitignored runtime state，不进入 checkpoint。
- Protocol 的 `child_results` 保存 owner 的原始 stdout/stderr 与结构化 arguments；`next_actions` 保存待填字段、后续 owner step 和治理闸口。不得把其中的 raw 内容转述给用户。
- `init` 与 `review` 永远不读 TTY、不调用交互式输入。`init` protocol 为 `ready_with_optional_setup` 时，先向用户呈现“现在设置”（推荐）/“先跳过”，不得越过选择直接追问姓名；defer 不产生额外偏好写入并允许立即工作。configure 时在一个紧凑问题里收集真实署名、语言与术语风格、研究方向、资源与重要约束，展示当前版本记录与论文初筛默认值并允许“默认即可”，再以既有 headless 写入落盘。
- 快速设置必须逐项执行 `apply.field_inputs`，不得自行猜 dotted key。资源使用 protocol 指定的 canonical input，保留已有 resource keys；约束 input 可重复，按 append + deduplicate 合并，不覆盖旧约束。旧 persona resource input 仅为兼容，不是 I1 canonical 路径。
- 缺真实署名不阻塞查看 `review` 列表。用户选择确认时，按 protocol 先自然语言询问署名、只 headless 保存该字段且保留其余偏好，再应用确认；拒绝不要求署名。
- judgement 确认必须忠实透传用户原话、`authorization_source=user_message` 和 evidence；不得自签。

## 动词语义

- `help`：打印分组能力菜单；固定文本，不调用 owner。
- `init`：幂等准备知识库和配置；缺真实署名时 KB 仍已可用，并由 Agent 提供可延后的快速设置。重复 init 零 churn，显式补一个字段只改该字段。
- `doctor`：只读说明 runtime、YAML 与 PDF 能力；详细解释只进私有 protocol。
- `update`：只读检查版本；发现更新后先请求用户授权。更新只使用 manifest 记录的来源，不把 fork/local 安装切回默认上游。
- `status` / `find` / `recall`：转发 owner 后过滤内部命令、路径与 flags。
- `next`：读取 durable program 与 canonical unit 状态；完成态不因机械刷新重新打开，program 中持久化的明确 `next_actions` 优先于泛化维护建议。不得从聊天承诺猜下一步。
- `add`：轻量入库；Hugging Face `/datasets/` 链接推断为 dataset，本地目录推断为 repo，本地 PDF 推断为 paper，其余本地文件推断为 blog。
- `ingest`：只自动执行 intake 与第一个 prepare；paper 的第一个 prepare 必须是 quick-screen。Agent 从私有 protocol 依次完成 `screen 填充/verify → 按已验证 paper_type 准备完整笔记 → 笔记填充/verify`；repo/dataset/blog 仍按各自单个分析骨架续跑。判断确认始终停在用户闸口。
- `review`：只列真正 ready-for-review 的 knowledge-unit 判断；prepared shell、ready-to-verify 与 failed-retryable 不进人工 inbox。TTY 与 pipe 语义相同；缺真实署名时仍展示列表，只在确认应用前补署名。
- `reject`：复用 knowledge-base-manager 的拒绝路径，不重实现治理逻辑。
- `resume` / `undo` / `restore`：转发恢复合同并保持公开输出为自然语言。

## 约束

- 不复制业务判断；写入、确认、检索和状态汇总仍由 owner skill 负责。
- 公开 stdout 禁止出现 Python 命令、owner script、内部 flag、环境变量、绝对项目路径、`NEXT FOR AGENT:` 或 `confirm:`。
- 子脚本的完整诊断保存在私有 protocol；公开失败信息简短、可行动，并保留原非零退出码。
- Machine protocol 只能显式 opt-in；`kb help/doctor/update/status` 的普通调用不得创建或修改 KB。
