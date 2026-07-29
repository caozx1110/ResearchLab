---
name: kb-cli
description: kb 快捷命令入口（伪 CLI），用于把常用 research 操作统一成 kb 动词形式；当用户运行或对 AI 说 kb help/init/doctor/update/obsidian/status/next/find/add/ingest/review/reject/recall/resume/undo/restore 时使用。
---

# kb 快捷命令入口（伪 CLI）

`kb-cli` 是 research 系统的薄 dispatcher。用户只接触自然语言和 `kb <verb>`；底层 owner、真实参数、绝对路径和 Agent 下一步都不得出现在公开 stdout。

## 用户交互

用户可以直接说“帮我初始化研究知识库”“把这个 repo 入库”“有哪些判断需要我确认”，也可以使用以下 16 个快捷动词：

- `kb help`
- `kb init`
- `kb doctor`
- `kb update`
- `kb obsidian update` / `kb obsidian status`
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
- `init` 与 `review` 永远不读 TTY、不调用交互式输入。standalone terminal 只展示清单并明确要求回到 Agent 对话继续，不能暗示 shell 会自行收集决定。`init` protocol 为 `ready_with_optional_setup` 时，先向用户呈现“现在设置”（推荐）/“先跳过”，不得越过选择直接追问姓名；defer 不产生额外偏好写入并允许立即工作。configure 时在一个紧凑问题里收集真实署名、语言与术语风格、研究方向、资源与重要约束，并在同一回合合并询问丢链接后的自动化档位（`link_autodrive`：先询问再深读 / 自动深读到待确认笔记）与讨论风格（`discussion_style`：挑战 / 打磨 / 自适应）；展示当前默认值并允许“默认即可”整体保留，再以既有 headless 写入落盘。
- 快速设置必须逐项执行 `apply.field_inputs`，不得自行猜 dotted key。资源使用 protocol 指定的 canonical input，保留已有 resource keys；约束 input 可重复，按 append + deduplicate 合并，不覆盖旧约束。旧 persona resource input 仅为兼容，不是 I1 canonical 路径。
- 缺真实署名不阻塞查看 `review` 列表。用户选择确认时，按 protocol 先自然语言询问署名、只 headless 保存该字段且保留其余偏好，再通过 snapshot-bound review adapter 应用确认；拒绝不要求署名。不得绕过 adapter 直接拼 owner 调用。
- judgement 确认必须忠实透传用户原话、`authorization_source=user_message` 和 evidence；不得自签。
- 用户要求在 Obsidian 批量查看时，Agent 可把当前治理档允许的 snapshot 投影成 `annotations/` 中的一次性可编辑待确认表（strict 最多 3 条；personal 默认最多 10 条）。表内 `确认 / 拒绝 / 暂缓` checkbox 只表示意图草稿；不得监听文件或因勾选自动写 canonical KB。用户回到对话要求同步后，先纯读解析并完整复述 diff，再等待当前消息明确授权。除 checkbox 外的任意 sheet 改动、重复/冲突/漏选、过期、重放、symlink 或 current binding 变化都必须整批拒绝。
- 普通对话与 Obsidian batch 的 confirm/reject/defer 共享同一个跨 owner coordinator：先完整纯读预检并合并精确 target scope，再在一个 root transaction 中锁内复验授权、snapshot、current owner plan 与 CAS，并通过无嵌套 lock/checkpoint 的 owner child API 原子应用；所有 canonical 写入成功后才在同一事务内消费 snapshot。任一 validation/owner failure 必须整批零业务写且 snapshot 保持可修正重试；成功后全批只建一个精确 checkpoint，绝不能退化成逐条转发。Obsidian 表须显示安全公共编号、来源/定位与有效期；成功后改成明显的已处理记录且保留人工勾选。

## Agent 调用速查

- `--agent-protocol` 是全局 flag，必须放在动词之前：`kb --agent-protocol r1.json review`。协议文件写在 `kb/.runtime/` 下，传文件名即可。
- review 对话拍板（apply）精确语法：
  `kb --agent-protocol r2.json review --apply-snapshot r1.json --confirm-ref <kind>:<id> --user-authorization "<用户原话>" --decision-evidence "<证据>"`
  - `--apply-snapshot` 传展示这批判断时用的协议文件名（如 `r1.json`），不是 snapshot token。
  - `--confirm-ref` / `--reject-ref` / `--defer-ref` 必须是 `kind:id`（如 `blog:blog-xxxx`），且只能取展示协议 `present_review_items.review_items[].subject`。
  - apply 失败时读新协议 `details.review_apply_failure`：`reason_code`、`expected.valid_confirm_refs`（当前快照合法 confirm-ref 列表）、`expected.apply_snapshot`（正确文件名）与 `ref_suggestions`。
- Obsidian 批次：
  - 导出：`kb --agent-protocol o1.json review --obsidian-export`。
  - 预览：`kb --agent-protocol o2.json review --preview-obsidian-batch <batch_ref>`；`batch_ref` 是 sheet 内 HTML 注释 `<!-- kb-review-batch:<64位hex> -->` 里的 64 位值。
  - 应用：`kb --agent-protocol o3.json review --apply-obsidian-batch <batch_ref> --expected-preview-digest <digest> --user-authorization "<用户原话>" [--decision-evidence "<证据>"]`；digest 取自 preview 协议 `present_obsidian_review_diff.apply.expected_preview_digest`。
- init headless flags：`--name`、`--lang {zh,en}`、`--auto-commit {manual,milestone,aggressive}`、`--auto-ingest-mode {ask_first,auto_deep_read}`、`--discussion-style {challenge,refine,adaptive}`、`--persona-term {keep-en,translate,bilingual}`、`--persona-focus`、`--persona-resources`、`--persona-report`、`--persona-boundaries`、`--quick-resource`、`--quick-constraint`（可重复）、`--git-init`。

## 动词语义

- `help`：打印分组能力菜单；固定文本，不调用 owner。
- `init`：幂等准备知识库和配置；缺真实署名时 KB 仍已可用，并由 Agent 提供可延后的快速设置。重复 init 零 churn；重复提交相同显式设置也是 byte/journal/checkpoint no-op，显式补一个真正变化的字段只改该字段。
- `doctor`：只读说明 runtime、YAML 与 PDF 能力；详细解释只进私有 protocol。
- `update`：只读检查版本；发现更新后先请求用户授权。更新只使用 manifest 记录的来源，不把 fork/local 安装切回默认上游。
- `obsidian update|status`：生成或纯读检查 `kb/obsidian/managed/` 派生视图；不得改 canonical record、人工 `inbox/annotations` 或 `.obsidian/` 配置。详细 finding 只进私有 protocol。
- `status` / `find` / `recall`：转发 owner 后过滤内部命令、路径与 flags。`find` 的私有 protocol 同时给 Agent 一个有界 `context-pack/v1`；formal 只含 current confirmed claims，navigation 摘要/段落不得当成确认结论。
- `next`：读取 durable program 与 canonical unit 状态；完成态不因机械刷新重新打开。program 中持久化的 `next_actions` 与 loose-unit 维护都是完整候选集里的事实，不带固定优先级；Agent 按本次信息增益、成本风险、阻塞与有效偏好比较。不得从聊天承诺猜下一步。
- `add`：按 `link_autodrive` 路由。`ask_first` 只轻量入库并一次询问是否深读；`auto_deep_read` 复用 ingest 管线。Hugging Face `/datasets/` 链接推断为 dataset，本地目录推断为 repo，本地 PDF 推断为 paper，其余本地文件推断为 blog。
- `ingest`：自动执行 intake 与当前安全的 prepare；paper 直接生成统一 deep-read scaffold，由 Agent 在同一份 fill 中填写 `paper_type`、类型理由/逐字证据与对应五要素，再一次 verify。若同源条目来自先前 `kb add`，从 canonical workflow 继续；已有 Agent fill 或已核验内容绝不重铺，只在私有 protocol 给出当前阶段的续接动作。repo/dataset/blog 仍按各自单个分析骨架续跑。判断确认始终停在用户闸口。
- `review`：聚合所有 owner 真正 ready-for-review 的判断，包括 knowledge unit、实验诊断、program decision、idea discussion conclusion 与 method selection；prepared shell、空 claims、stale verification、ready-to-verify 与 failed-retryable 不进人工 inbox。`priority` 是 owner 提供的 canonical impact 等级；先按 priority、同级再按最旧更新时间展示治理档允许的一批并说明剩余数量，不另编 impact 分。strict 固定每批 3 条、24 小时；personal 默认每批 10 条且卡片有效期可配。effective profile、limit 与 expiry 冻结进 snapshot，apply 不重读可变配置。私有 protocol 携带每项真实 confirm/reject owner route 与绑定 subject/status/content/verification 的 snapshot，并引用一次性 runtime snapshot token。Agent 只能把用户决策应用到该 token 中原样登记的已展示 subject；validation failure、缺署名/授权/evidence 或 owner preflight/apply failure 都不得消费，用户可用同一有效清单修正重试。消费或过期后的 tombstone 再保留 24 小时，以便区分重复应用、过期、内容更新和无法验证。review/apply 只对已存在的受控 runtime registry 在直属层做有界清理；fresh empty review 严格零写，首次实际展示才创建 registry。拒绝 symlink、非普通文件与越界路径，不递归删除。内容、证据、owner/path 或状态变化后必须重新展示，未展示的剩余项不能捎带确认。成功反馈只回显经公开 sanitizer 清洗后的判断类型/标题与整批结果；失败按重复、过期、内容更新、无法验证分别给自然语言恢复动作，绝不回显 token、digest、owner 参数或内部路径。TTY 与 pipe 语义相同，缺真实署名时仍展示列表，只在确认应用前补署名。
- `review` 展示前按私有 protocol 中的 task digest 记录并加载 `kb-cli + review-display` effective preferences。选中的 reporting style 只能调节 Agent 对同一已冻结卡片批次的解释密度，不能改变候选集合、priority 顺序、snapshot、owner route、治理档上限或确认门；未选中的软偏好不生效。
- `reject`：复用 knowledge-base-manager 的拒绝路径，不重实现治理逻辑。
- `resume` / `undo` / `restore`：转发恢复合同并保持公开输出为自然语言。`undo` 成功后公开点名被撤销的对象（操作的安全中文描述，如“已撤销：Obsidian 视图更新”）；`restore` 不带编号时只读列出最近约 10 个可恢复操作（公开编号 + 时间 + 中文摘要，不含内部路径），编号可直接用于 `kb restore <编号>`，内部 op id 与编号映射只进私有 protocol。

## 约束

- 不复制业务判断；写入、确认、检索和状态汇总仍由 owner skill 负责。
- 公开 stdout 禁止出现 Python 命令、owner script、内部 flag、环境变量、绝对项目路径、`NEXT FOR AGENT:` 或 `confirm:`。
- 子脚本的完整诊断保存在私有 protocol；公开失败信息简短、可行动，并保留原非零退出码。
- Machine protocol 只能显式 opt-in；`kb help/doctor/update/status` 的普通调用不得创建或修改 KB。
