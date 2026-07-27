# R24 冷产品验收：安装后完整用户流程

- 验收日期：2026-07-25
- 被测版本：`0.2.0-rc.6`
- 被测提交：`e2a35e5c4c10f48bda3cd99e435dee543c4b73c1`
- 验收方式：把当前主线当作用户粘贴 GitHub 链接后 Agent 已完成安全 checkout 的源码，在 `/tmp` 下建立全新安装目标；只依据 README、`docs/INSTALL.md`、`docs/USER_GUIDE.md` 与安装后的 `AGENTS.md` 操作产品。
- 隔离约束：未使用真实 `kb/`、联网、API Key、付费服务或 Obsidian 插件；shipping skills 只作为被测产品与行为合同，不作为需求或设计依据。

## 结论

当前版本已经是**可实际使用的 release candidate**，不是空壳，也不是依赖固定检索 provider 的演示。安装、首次初始化、空状态导航、Agent 主导的下一步选择、完整 survey 恢复链、批量确认、偏好选择性分发和报告生成都有真实持久化路径。

本轮没有复现 P1。复现了 2 个 P2：无搜索工具时的用户恢复提示不够可操作；自定义 factual/operational reporting event 会被报告误归为待确认判断。两项都不破坏 canonical 数据或确认门，但会让用户在常见边界场景中得到错误或不完整的下一步。因此建议修完再把候选提升为 stable。

## 评分

| 维度 | 分数 | 判断 |
|---|---:|---|
| 成熟度 | 8.4 / 10 | 主要工作流、治理、恢复和原子批处理齐全；仍有两处跨 owner 的产品语义缝隙。 |
| 易用性 | 8.2 / 10 | 普通用户只需自然语言和 16 个 `kb` 动词；安装可由 Agent 全程代办。无工具恢复仍需要 Agent 自己补全产品未提供的选项。 |
| 智能性（辅助评分） | 8.7 / 10 | `kb next` 会把全部合法候选交给 Agent 比较并要求 task-bound 偏好选择，不再用固定优先级冒充决策。 |

分项观察：安装 9.0、init/status/next 9.0、literature-search 7.6、批量 review/Obsidian 9.2、survey 路由 8.8、偏好分发 8.9、report 7.8。

## 已验证用户流程

### 1. “只粘贴 GitHub 链接给 Agent”的安装合同

使用当前 checkout 代替被本轮禁止的联网 clone，记录了 origin、branch 与 commit，然后执行文档规定的 Agent JSON plan 流程：

1. 计划文件位于目标 workspace 与 HOME 之外；计划阶段显示 189 个目标、0 个冲突，并声明未写 workspace、HOME 或 runtime。
2. 计划绑定 source commit、source tree digest、semantic plan digest 和逐目标前置状态。
3. 在计划审阅后从文件原始字节计算 SHA-256，再按 JSON 中的 apply contract 无交互应用。
4. 正式安装成功；目标中有 20 个 skill，版本为 `0.2.0-rc.6`，`kb` 快捷入口存在。
5. 安装目标原有的普通根规则 `existing user rule` 被保留，managed block 之外没有被覆盖。

结论：从 Agent 角度，安装合同足够明确、可审计、可自动执行；用户无需知道 digest、内部参数或安装路径。由于本轮明确禁止联网，GitHub clone/fetch 本身只列为未覆盖项，不作为 finding。

### 2. init、status 与 next

在安装副本直接走公开入口：

- `kb help` 展示恰好 16 个公开动词，并把 literature search、survey、偏好、Obsidian 批量 review 与 report 放在自然语言能力区。
- 首次 `kb init` 先建立可用 KB，再只询问“现在设置 / 先跳过”；输出没有内部命令、flag 或路径。
- 空 KB 的 `kb status` 正确报告 0 个计划与各类待办计数。
- 空 KB 的 `kb next` 邀请用户发送论文、repo、文章或使用 `kb ingest`。
- 用私有 quick-setup 协议填写署名、语言、研究方向、资源与约束后，公开输出仅为“知识库和基础偏好已准备好”，私有回执保留结构化设置与可选版本历史动作。

给临时 KB 增加 program、被阻塞的 literature stage 和 survey composite 后，`kb next` 没有按固定顺序直接选赢家，而是返回 3 个事实候选和同一个 snapshot digest，要求 runtime Agent 比较信息增益、成本/风险、阻塞与偏好，再记录选择。这满足“下一步交给 Agent 判断”的产品目标。

### 3. literature-search 在没有外部搜索工具时

在当前会话明确没有 search/browser/connector 的条件下，向安装副本提交一个 `blocked_no_search_tool` stage：

- stage 写入成功，候选数为 0，且没有把空结果标为成功；
- `kb status` 显示 1 个可继续文献检索；
- `kb next` 的私有候选包含 `resume-literature-search`、原 stage digest 与 `blocked_no_search_tool` 原因；
- 没有 OpenAlex 或其他固定 provider/API key 前置条件。

持久化和恢复性通过，但立即面向用户的恢复说明存在 P2-1。

### 4. 批量 review 与 Obsidian 对话回写

同一提交上的隔离临时测试覆盖了实际公开 `kb review` 入口：

- 导出当前 review snapshot 到 `obsidian/annotations` 的可编辑表；表内只允许每项选择确认、拒绝或暂缓；
- 用户只改 checkbox 后，preview 是纯读，canonical bytes 不变；
- Agent 会复述整批选择，并且必须取得当前消息授权和精确 preview digest；
- apply 通过一个 root transaction 跨 owner 原子应用，成功后同时消费 batch 与 source snapshot；
- sheet 保留人工勾选并明显标记“已处理”；
- replay 被拒绝；preview 后偷偷改选择、缺少当前授权或改动非 checkbox 内容时全部零业务写。

定向验证结果：

```text
test_kb_cli_exports_previews_and_atomically_applies_once              PASS
test_apply_is_bound_to_previewed_choices_and_current_user_authorization PASS
```

另外，真实安装副本的 `kb obsidian update` / `status` 均成功，生成 Home、program 页面与三个原生 Bases 面板，且未创建插件配置。当前行为满足“Obsidian 负责看和勾选，回到对话后由 Agent 复述并应用”的要求。

### 5. survey 完整路由

在没有已确认输入的安装副本执行 survey prepare，产品没有伪造 survey，而是返回结构化 evidence gap，并持久化：

```text
search → selection → source_intake → unit_analysis → synthesis
       → review_confirmation → report_consumption
```

composite 从 `search` 阶段开始，进入 `kb status` 与 `kb next` 的可恢复候选。针对同一提交的隔离测试进一步完成了七阶段逐阶段绑定，验证了：假 stage/unit/survey ref 被拒绝，selection 需要当前用户授权，unit analysis 必须绑定真实 confirmed unit，synthesis 必须是 verified survey，review confirmation 必须有当前确认回执，最后 report consumption 必须覆盖全部关联 program 或明确 not applicable。

定向验证结果：

```text
test_prepare_zero_current_inputs_returns_structured_gap_without_scaffold PASS
test_composite_all_seven_stages_bind_current_canonical_artifacts       PASS
test_confirmed_program_survey_emits_a_current_reportable_event         PASS
```

### 6. 总偏好与选择性分发

在安装副本保存统一 profile 后，三个实际 consumer 得到的 eligible view 不同：

| Consumer | 可见偏好 |
|---|---|
| `literature-search/search` | 语言、研究方向、术语风格、hard constraints |
| `report-author/weekly` | 报告风格、语言 |
| `research-orchestrator/plan` | 研究方向、hard constraints、资源、autonomy ceiling |

这验证了“规则决定能不能给，Agent 决定本次用不用”的两段式模型，而不是把完整总偏好广播给所有 skill。定向测试还验证：receipt 只保存 ID/digest/reason，不复制偏好正文；所有 eligible 项必须被 selected 或 excluded 明确记账；hard 偏好不能遗漏；canonical profile 变化会让旧 selection stale。

### 7. report

真实安装副本中创建 program、写 reporting events 并生成 weekly report：

- 提取了 program-created 事件；
- 缺少 decision 和 confirmed claim 时明确写“缺少”，没有补造内容；
- judgement-like 内容进入单独的“待确认 / 未核验”区；
- 同提交的定向测试验证 weekly/stage report 同时消费 claims、verbatim evidence、events 与 decisions，并检查生成文档不泄漏裸命令。

基础报告链通过，但自定义事实事件分类存在 P2-2。

## 可复现缺口

### P1

无。没有复现数据破坏、治理绕过、确认自签、越界写入或核心流程不可用。

### P2-1：无搜索工具时只记录阻塞，没有给用户可操作的恢复选择

复现条件：初始化一个空 KB，当前 Agent 会话没有 search、browser 或 connector，发起自然语言文献检索。

实际行为：stage 正确记录 `blocked_no_search_tool`，公开输出只有：

```text
当前没有可用的文献检索工具；已记录阻塞原因，没有把空结果当作成功。
```

随后 `kb status` 能看到 1 个可继续检索，`kb next` 只说 Agent 需要比较候选。安装后 `AGENTS.md` 和 `literature-search` 行为合同要求记录阻塞与恢复 stage，但没有要求 Agent 向用户给出具体恢复菜单。

期望行为：同一回合自然语言说明至少三种可执行选择，并保留原 stage：

1. 若宿主可启用搜索/浏览能力，启用后继续同一 stage；
2. 用户直接提供已知 URL、DOI、PDF 或文献清单，先进入候选/入库流程；
3. 暂时保留，之后用 `kb next` 恢复。

影响：数据层是安全且可恢复的，但普通用户不知道现在能做什么，容易把“无需 API Key”误解为“离线也会自动发现外部论文”。这是必需 UX 的缺口，故为 P2。

### P2-2：显式 `factual` / `operational` reporting event 被误归为待确认判断

复现步骤：

1. 在临时 KB 创建 program；
2. 通过 research-orchestrator 的 reporting-event 入口分别写入 `event_type=operational` 与 `event_type=factual`；
3. 生成 weekly report。

实际行为：两条都进入“待确认 / 未核验的判断”，并提示缺少 confirmation receipt。对照组 `event_type=phase-completed` 正常进入正式“报告事件”。

根因证据：report-author 只在 `epistemic_type` 为 `fact/factual/operational` 时直接走事实轨；event type 则仅接受固定 `OPERATIONAL_EVENT_TYPES` 白名单。research-orchestrator 的公开内部 adapter 允许任意 `--event-type`，但没有 `epistemic_type` 输入，因此调用方明确给出的 `factual` 或 `operational` 无法表达成 report-author 所承认的事实类型。

期望行为：二选一即可：

- report-author 把 event type 的精确值 `factual` / `operational` 也识别为事实轨；或
- orchestrator 将受控的事实分类写入独立 `epistemic_type`，并校验 event type 与该分类的组合。

影响：不会把未确认判断提升为事实，安全侧 fail-closed；但真实事实会被错误降级，周报出现不必要的“待确认”噪声，削弱 report 的可信度与可用性。因此为 P2。

### P3

无新增可复现 P3。界面文案与文档中观察到的轻微摩擦不足以单独构成有证据的产品缺口。

## 回归证据

除安装副本上的真实命令流外，使用配置好的维护者测试解释器在临时目录运行 12 个与本轮范围直接相关的定向测试：

```text
12 passed in 2.83s
```

覆盖 Obsidian batch 导出/预览/授权/原子应用、survey evidence gap 与七阶段完成、survey→program report event、skill-scoped preference eligibility、receipt 最小披露、hard preference 强制记账、profile 变化失效、weekly/stage report 内容、缺失输入显式标记与公开文档命令泄漏。

第一次尝试误用了系统 Python（缺 `bs4`），第二次误用了不含 pytest 的仓库 runtime；两次都在测试收集前终止，不作为产品证据，也不计为 finding。

## 未覆盖但不构成 finding 的边界

- 本轮按要求禁用联网，因此没有重新 clone GitHub，也没有验证远端 tag/release；本地 checkout 之后的完整 Agent-plan/apply 已验证。
- 没有启动 Obsidian GUI，故未做 Reading view 的视觉验收；Markdown sheet、Bases 产物、checkbox 语义和 canonical round-trip 已验证。
- 没有调用真实外部检索 provider、商业数据库、付费服务或 API Key；这正是本轮需要验证的无前置依赖边界。

## 发布建议

保持 `0.2.0-rc.6` 的 RC 定位合理。先修 P2-1 与 P2-2，各补一个公开行为回归，再重跑本报告中的定向集与完整 release gate。修复后，这套系统可以进入 stable 候选；当前已经足以让愿意接受 RC 边界的真实用户安装和使用。
