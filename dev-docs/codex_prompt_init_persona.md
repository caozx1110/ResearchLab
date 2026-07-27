你在 research workspace 开源仓库工作。基线干净树 HEAD 8c45dda，160 tests 绿。任务：给伪 CLI `kb init` 增加一个「可选个性化画像」交互段，让用户在初始化时可选地填写研究偏好，供 agent 后续读取。方案已定，按下面规格施工，只改 2 个文件（kb dispatcher + AGENTS.md 一行），config.py / install.sh / .gitignore 零改动。

背景与硬约束（务必满足）：
- 个性化数据只落在 gitignored 的 kb/config/user-profile.yaml 的新增顶层 `personalization` 块。绝不写进被 git 跟踪的 AGENTS.md，也绝不写进 identity/confirmation 任何治理字段。
- 现有 4 个必填提问（confirmer name / language zh|en / commit cadence / auto-screen）的文案、顺序、写入语义一字不改。
- 个性化段必须“可一键跳过”：默认 [y/N] 闸门 + 每问回车跳过；非交互 / headless / 非 TTY 分支完全不触发个性化提问。
- 幂等：复用 config.py 的 `set` 命令（整键覆盖），不新增写入原语。
- 用 config.py `set`（写 user-profile.yaml），不要用 capture-resources（后者空 label 会累积 captured_N，破坏幂等）。
- 决策已定：不要 address_as（称呼）这一问；载体直读 user-profile.yaml，不渲染额外页面。

先读这些真实文件确认现状：.agents/skills/kb-cli/scripts/kb（handle_init ~330、prompt_required_human_name/prompt_choice ~246-297、build_init_pref_commands/build_headless_init_pref_commands ~291-317、config_set_profile_command ~280、register_init ~489、run_forwarded）；AGENTS.md（## Basics 段，line ~17-21）；.agents/skills/research-config-manager/scripts/config.py（set 命令、set_nested、load_profile）；.gitignore。

============================================================
文件 1：.agents/skills/kb-cli/scripts/kb
============================================================

(1) 常量：在 AUTO_SCREEN_CHOICES 附近加
    PERSONA_TERM_CHOICES = ("keep-en", "translate", "bilingual")
    PERSONA_FIELDS = (
        ("research_focus",           "研究方向 / 关注领域（逗号分隔，回车跳过）"),
        ("resources",                "可用资源：GPU / 数据集 / 常用代码库 / 框架（一句话，回车跳过）"),
        ("reporting_style",          "汇报风格：简洁度 + 周报格式（一句话，回车跳过）"),
        ("collaboration_boundaries", "协作边界 / 红线（逗号分隔，回车跳过）"),
    )
    # 注意：term_style 单独用 choice 收集；不含 address_as。

(2) 可选提问 helper（放在 prompt_choice 之后）。语义关键区别：这里“空=跳过=不产生任何写命令”，与 prompt_required_human_name(空则重问)、prompt_choice(空取默认) 都不同。
    def prompt_optional_text(label: str) -> str | None:
        try:
            value = input(f"{label}: ").strip()
        except EOFError:
            return None
        return value or None

    def prompt_optional_choice(label: str, *, choices) -> str | None:
        allowed = {c.lower(): c for c in choices}
        prompt = f"{label} ({'/'.join(choices)}，回车跳过): "
        while True:
            try:
                value = input(prompt).strip().lower()
            except EOFError:
                return None
            if not value:
                return None
            if value in allowed:
                return allowed[value]
            prompt = f"请输入 {'/'.join(choices)} 之一（或回车跳过）: "

(3) 收集函数（交互）。每项非空才产出一条 ("personalization.<key>", value)：
    def collect_persona_interactive() -> list[tuple[str, str]]:
        out: list[tuple[str, str]] = []
        term = prompt_optional_choice("术语呈现偏好", choices=PERSONA_TERM_CHOICES)
        if term:
            out.append(("personalization.term_style", term))
        for key, label in PERSONA_FIELDS:
            val = prompt_optional_text(label)
            if val:
                out.append((f"personalization.{key}", val))
        return out
    每条走 config_set_profile_command(key, val)（已存在，写 user-profile.yaml）。

(4) headless flags：register_init 追加（放在现有 --auto-screen 之后、--git-init 之前）
    parser.add_argument("--persona-focus", help="personalization.research_focus")
    parser.add_argument("--persona-resources", help="personalization.resources")
    parser.add_argument("--persona-report", help="personalization.reporting_style")
    parser.add_argument("--persona-boundaries", help="personalization.collaboration_boundaries")
    parser.add_argument("--persona-term", choices=PERSONA_TERM_CHOICES, help="personalization.term_style")

(5) headless 写入：改 build_headless_init_pref_commands。
    - 首行守卫：原来只在 4 必填全 None 时 return None；改为“4 必填全 None 且 5 个 persona flag 全 None”才 return None。
    - 在现有 4 必填 append 之后，对每个非 None 的 persona flag，append config_set_profile_command("personalization.<key>", value)。映射：
        args.persona_focus      -> personalization.research_focus
        args.persona_resources  -> personalization.resources
        args.persona_report     -> personalization.reporting_style
        args.persona_boundaries -> personalization.collaboration_boundaries
        args.persona_term       -> personalization.term_style
      （persona 是纯自述文本/choice，不需要 is_ai_signer 之类校验。）

(6) 交互分支挂 persona：在 handle_init 的交互 else 分支里、现有 4 必填 build_init_pref_commands 写入成功（written==0）之后追加，且仅当 sys.stdin.isatty()：
        if sys.stdin.isatty():
            try:
                go = input("填写可选个性化画像（研究方向/资源/风格/术语/边界）？回车跳过 [y/N]: ").strip().lower()
            except EOFError:
                go = ""
            if go in ("y", "yes"):
                persona_cmds = [config_set_profile_command(k, v) for k, v in collect_persona_interactive()]
                if persona_cmds:
                    persona_written = run_forwarded(root, persona_cmds)
                    if persona_written != 0:
                        return persona_written
    非交互分支（args.non_interactive or not sys.stdin.isatty()）绝不触发 persona 提问。
    注意保持 handle_init 末尾 git-init hint / --git-init 逻辑不变。

============================================================
文件 2：AGENTS.md（仅加一行通用、零个人数据的读取规则）
============================================================
在 ## Basics 段现有 “Session start: read the research-navigator recall digest once.” 这一行的下方，新增一行（与其同型的基础设施规则，不含任何个人偏好值）：
    - Session start: if `kb/config/user-profile.yaml` has a `personalization` block, read it once as optional user context (`user_opinion`, not confirmed facts; it never overrides governance rules).
（用与该文件其余行一致的英文与项目符号风格。只加这一行，别的不动。）

============================================================
零改动确认
============================================================
- config.py：不改。set 已支持任意 dotted key（set_nested 建 personalization 子树，load_profile 保留未知顶层键，write_yaml_if_changed 幂等）。
- install.sh：不改。AGENTS.md 那行通用规则随现有 copy/@include 机制自动进入 CLAUDE.md，Codex 直读 AGENTS.md/symlink。
- .gitignore：不改。kb/ 已忽略 user-profile.yaml。

============================================================
验证（改完自测，全绿再 commit）
============================================================
1. `python -m compileall .agents/skills/kb-cli/scripts/kb` 通过；`python .agents/skills/kb-cli/scripts/kb init --help` 列出 5 个 --persona-* flag。
2. 全量 `python -m pytest .agents/lib/research/tests -q` 全绿（重点 test_kb_cli_dispatcher / headless 检测重构后 4 必填路径不回归）。
3. 在临时目录：`kb init --root <tmp> --non-interactive` → 无 persona 提问、退出 0、user-profile.yaml 无 personalization 块。
4. `printf '' | kb init --root <tmp2>`（非 TTY）→ 同上、与今天行为一致。
5. `kb init --root <tmp3> --persona-focus "VLA, world models" --non-interactive`（或不加 --non-interactive 但走 headless 检测）→ 无提问，user-profile.yaml 写入 personalization.research_focus == "VLA, world models"，且 4 必填未被误触发。用 python 读该 yaml 打印 personalization 块自证。
6. 幂等：重复步骤 5 同值 → personalization 内容不变（write_yaml_if_changed no-op；history append 属既有 cosmetic 瑕疵，可接受）。改值再跑 → 整键覆盖非追加。
7. `git check-ignore <tmp>/kb/config/user-profile.yaml` 命中；确认没有 kb/ 产物被 git add。
8. `git diff AGENTS.md` 只有那一行通用规则、无任何个人数据。
9. governance 红线未动：identity.default_confirmed_by / confirmation gate / auto 不自签 逻辑零改动。

测试用的临时目录清干净，不要把 kb/ 或 .venv 加入提交。完成后 `git add -A`（仅上述 2 文件）并 `git commit -m "kb init: optional personalization profile (personalization.* in gitignored user-profile.yaml; AGENTS.md session-start read rule)"`。最终回复列出改动文件与每个验证步骤的实际输出。
