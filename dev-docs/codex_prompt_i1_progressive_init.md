# I1 handoff — 渐进式 `kb init` onboarding

你在独立 worktree 中实现 I1。只做本 handoff；拿不准就 STOP-and-report，不得扩 scope。

## STEP 0 — base sync（先做，不能省）

目标基线是 PR #2 当前 head：

```text
c6c5e3cc0bc869a91cc7d75cb25cd169cb993350
```

先核对 `git rev-parse HEAD`、`handle_init`、`build_headless_init_pref_commands` 与 detached-HEAD installer regression 是否都在。若 worktree 不是该 commit 且没有你的改动，只能在这个隔离 worktree 内 `git reset --hard c6c5e3cc0bc869a91cc7d75cb25cd169cb993350`；再核对后才施工。绝不能 reset 主工作区或其他 worktree。

## 目标合同

SSOT 已在 `temp/SYSTEM_DESIGN_SSOT.md` 的“渐进式初始化 I1”锁定；完整读取该节再动手。核心行为：

1. `kb init` 先幂等创建/修复结构，缺偏好不阻塞入库、检索、分析。
2. 缺真实署名时，公开输出明确提供“现在设置（推荐）”与“先跳过”，说明约 1 分钟、跳过后可立即使用、以后可说“补充我的研究偏好”。不得再说“还差一项必填”。
3. 真实署名只在首次 judgement confirmation 前强制；跳过不得写 sentinel、AI 名称或伪确认。
4. Runtime Agent 看到 protocol 后先让用户选择 configure/defer，不能直接追问姓名。现在设置时在一个紧凑回合收集：真实署名、语言/术语风格、研究方向、资源与重要约束；显示 commit cadence 与 auto-screen 当前默认值，允许“默认即可”。低频项以后再问。
5. 脚本绝不读 TTY/stdin；Agent 自然语言问答后复用现有 headless args 落盘。不增加第 16 个 verb，不新增 owner，不改配置 schema。
6. 重复 init no-churn；显式补一个字段只改该字段，保留其他偏好。

建议缺署名时只调用一次 `print()`，公开文案语义至少包含：

```text
知识库基础结构已准备好，现在可以开始使用。是否花约 1 分钟完成快速设置？请回复“现在设置”或“先跳过”；以后也可以直接说“补充我的研究偏好”。采用默认设置时使用中文、里程碑版本记录和论文自动初筛；第一次确认研究判断前仍会询问真实署名。
```

可以微调中文，但测试必须锁定上述全部语义，且不得泄漏 flags、路径、owner、machine status。

缺署名时 AgentProtocol 必须不再是单纯 `needs_user_input`，而是明确“KB 已可用 + setup 可延后”。推荐稳定 shape：

```yaml
status: ready_with_optional_setup
next_actions:
  - action: offer_init_preferences
    choices:
      - id: configure_now
        label: 现在设置
        recommended: true
      - id: defer
        label: 先跳过
        writes_preferences: false
    quick_fields:
      - human_name
      - language_and_terminology
      - research_focus
      - resources_and_constraints
    defaults: <现有 current/default snapshot>
    required_before:
      judgement_confirmation:
        - human_name
    apply:
      verb: init
      mode: headless
    defer:
      continue_with_defaults: true
      resume_phrases:
        - 补充我的研究偏好
        - kb init
```

若现有 protocol helper 要求字段名小幅调整，先保持语义完整并在提交总结中说明；不要发明持久化 onboarding schema。

## 文件所有权（只动这些）

- `.agents/skills/kb-cli/scripts/kb`
- `.agents/skills/kb-cli/SKILL.md`
- `.agents/skills/research-config-manager/SKILL.md`
- `.agents/AGENTS.md`
- `.agents/lib/research/tests/test_kb_cli_dispatcher.py`
- `.agents/lib/research/tests/test_r1_conversational_release.py`
- `README.md`
- `docs/USER_GUIDE.md`
- `docs/INSTALL.md`
- `docs/DESIGN.md`

不要修改 `.agents/lib/research/SCHEMAS.md`，除非现有 schema 明确拒绝 additive protocol payload；若遇到这种情况 STOP-and-report。不要修改 `temp/`、版本号、CHANGELOG、CI 或安装器。

## Agent/skill 指令必须落实

- `.agents/AGENTS.md`：init 缺信息时先给 configure/defer 选择；defer 零写并允许立即工作；configure 用一个紧凑问题，headless 落盘；确认门前再补真实署名。
- `kb-cli/SKILL.md`：同步相同流程与 protocol 消费规则，保持精简。
- `research-config-manager/SKILL.md`：说明快速设置只收高价值字段、低频偏好渐进补充、skip 不写 sentinel。
- 检查两个 skill 的 `agents/openai.yaml` 是否仍与 SKILL.md 匹配；若没有 trigger/summary 变化，不要为了 churn 重写。

## 测试要求

至少覆盖并真实运行：

1. TTY 与 pipe 输出字节一致、绝不调用 `input()`。
2. 缺署名输出含“现在可以开始使用 / 现在设置 / 先跳过 / 补充我的研究偏好 / 第一次确认前询问署名”，不含“还需要/必填”、裸命令、flags、内部路径。
3. Protocol `status=ready_with_optional_setup`，同时有 configure/defer choices、4 个 quick fields、confirmation-time identity gate、defer 零写语义与 headless apply。
4. 初次 init 后不执行 apply（模拟 skip），第二次纯 init 前后 workspace tree metadata/digest 与 journal count不变。
5. 现有 headless 全字段保存、partial update preservation、AI signer rejection 全部继续通过。
6. 已有真实署名时仍只输出“知识库和基础偏好已准备好。”并严格 no-churn。
7. installed-copy conversational release 测试同步新语义。
8. 用户跳过后第一次出现 ready review item 时，列表仍可读，但公开面说明确认前需要真实署名；private action 把 `human_name` 标为 apply 前所需，使 Agent 能先 headless 保存再确认，而不是让底层确认命令失败后才补救。

先跑 focused tests，再跑 skill validator；不要声称全量绿，主 agent 会独立跑全量。

## 红线

- 不碰真实 `kb/`；测试只用临时目录。
- 用户可见面只自然语言 + 既有 `kb <verb>`，没有裸命令、`--flag`、`${…}`、内部路径、`NEXT FOR AGENT:`。
- 不允许 TTY 分支、`input()` 或 stdin prompt。
- 治理只加严不放松；不改 confirmation/evidence 判断。
- 脚本不理解研究材料。
- 不 push、不 merge、不 tag。
- 小步提交；至少把代码/测试与文档/skill 指令分成清晰提交，或说明为何单提交更原子。

完成后报告：commit(s)、改动文件、focused test 结果、validator 结果、未解决问题。不要只给总结；保留 worktree 供主 agent 独立 review。

## P2 cold-acceptance correction（2026-07-20，主 agent 已复现）

首轮冷 agent 将 quick setup 值用 config owner 的通用 setter 写入后，磁盘配置存在，但第二次 init protocol 的 focus/resources snapshot 为空；进一步核对发现现有 `--persona-resources` 只写 `personalization.resources`，而 method-designer 锁定读取顶层 `profile.resources`。这不是只改显示即可关闭的问题。

SSOT 已新增第 8 条 canonical mapping，按其施工。仍只修改本 handoff 原列出的产品/测试/文档文件；不改 method-designer 或 config owner，不改 schema。具体要求：

1. 给 init 增加 Agent-only hidden resource/constraint headless 输入：自然语言资源写 `user-profile.resources.quick_setup`；一个或多个重要约束追加、去重到顶层 `user-profile.constraints`，必须保留已有资源键和约束。旧 `--persona-resources` 行为继续兼容，但新 protocol 不再把它当 I1 canonical resource 写法。
2. `runtime_pref_defaults()` 从 canonical `resources` / `constraints` 生成 private snapshot，并兼容旧 `personalization.resources`；focus/term 同样优先 canonical I1 路径并兼容冷测产生的 `preferences.research_focus/terminology_style`。不得把任意这些私有值回显进 public stdout。
3. `offer_init_preferences.apply` 必须给出精确 field-to-hidden-input map，使全新 Agent 无需猜 config 路径；skill/AGENTS 文档同步“遵循 protocol 映射，不自行选 dotted key”。
4. 新增回归：现有顶层 resource/constraint 不丢；quick resource 能被 method-designer 现有 `profile_resources()` 直接读到（可在 dispatcher test 动态加载或检查 canonical on-disk shape，不需要改 method 文件）；constraint append 去重；第二次 protocol 的 focus/resource/constraint snapshot 非空；alternate/legacy path compatibility read；installed-copy 走同一路径。
5. 先跑 focused tests，提交一个独立 P2 fix commit；不 push。主 agent 会重新跑全量和 cold acceptance。
