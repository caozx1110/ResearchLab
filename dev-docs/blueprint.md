# workspace-oss Skills 功能蓝图与待办拆分

生成时间：2026-07-08  
扫描范围：`.agents/skills/*/SKILL.md`、`.agents/skills/*/scripts/*`、`.agents/skills/*/agents/openai.yaml`、`kb/config/*`

## 0. 系统总览

- 这是一个中文优先的 research operating system，核心资产落在 `kb/`。
- 主要设计原则：
  - durable artifacts 优先于 chat-only answer。
  - source 先 staging / lightweight intake，再进入深分析。
  - AI judgement / evaluation 默认 `pending_user_confirmation`。
  - topic / tag / candidate pool / runtime preferences 走配置化治理。
- canonical 数据层：
  - `kb/units/{papers,repos,blogs,ideas,experiments}/<unit-id>/record.yaml`
  - `kb/programs/<program-id>/state.yaml` 与 `workflow/*`
  - `kb/config/{runtime-preferences,user-profile,topic-taxonomy,candidate-pools}`
  - `kb/synthesis/*`、`kb/user/*`、`kb/output/*`
- 通用 root 机制：
  - 大多数脚本支持 `--root <project-root>`。
  - 同时支持 `RESEARCH_PROJECT_ROOT`。
  - `kb-cli` 与 `research-orchestrator auto --execute` 会给子进程传递 root。

## 1. 当前个性化与配置能力

### 1.1 用户画像：`kb/config/user-profile.yaml`

- `preferences.language_preference`
  - 当前：`zh-CN`
  - 影响人面向 markdown / 输出语言。
- `preferences.summary_style`
  - 当前：`concise`
  - 用于摘要风格偏好。
- `preferences.novelty_bar`
  - 当前：`balanced`
  - 用于 idea / paper 评价的创新性阈值。
- `resources`
  - 可存 GPU、数据、平台、常用代码库等资源画像。
  - 命令：`config.py capture-resources --statement ... --label ...`
- `constraints`
  - 可存合作边界、不能动的目录、资源限制等。
- `governance.default_candidate_pools`
  - 默认候选池。
- `governance.topic_overrides` / `tag_overrides`
  - topic / tag 覆盖规则。
- `personalization.*`
  - `kb init` 已支持写入：
    - `personalization.research_focus`
    - `personalization.resources`
    - `personalization.reporting_style`
    - `personalization.collaboration_boundaries`
    - `personalization.term_style`：`keep-en | translate | bilingual`

### 1.2 Runtime Preferences：`kb/config/runtime-preferences.yaml`

- `browser`
  - `default_workbench_mode`: 当前 `preview`
  - `default_terminal_mode`: 当前 `codex`
  - `auto_open_recent_file`: 当前 `true`
- `paper`
  - `auto_screen_on_intake`: 当前 `true`
  - `auto_complete_note`: 当前 `false`
  - `auto_complete_note_condition`: 当前 `suggested_worth_reading`
  - `complete_note_mode`: 当前 `scaffold`
  - `auto_extract_figures_after_note`: 当前 `false`
  - `auto_refresh_structure_after_note`: 当前 `true`
  - `parse_cache_prewarm_on_intake`: 当前 `true`
  - `parse_cache_front_limit`: 当前 `8`
  - `parse_cache_back_limit`: 当前 `0`
  - `parse_cache_per_page_char_limit`: 当前 `3000`
  - `screening_mode`: 当前 `heuristic_structured`
  - `screening_context_pages`: 当前 `6`
  - `screening_max_chars`: 当前 `12000`
  - `prompt_for_preference_updates`: 当前 `true`
- `pdf`
  - `prefer_structured_source`: 当前 `true`
  - `auto_extract_figures`: 当前 `false`
  - `reuse_cached_parse`: 当前 `true`
  - `filter_blank_and_mask_images`: 当前 `true`
  - `figure_extraction_mode`: 当前 `caption-region`
  - `figure_include_tables`: 当前 `true`
  - `figure_render_scale`: 当前 `2.5`
  - `figure_crop_padding_pt`: 当前 `12.0`
- `versioning`
  - `enabled`: 当前 `true`
  - `separate_repo`: 当前 `true`
  - `auto_init_repo`: 当前 `true`
  - `auto_commit_mode`: 当前 `milestone`
  - `commit_on_browser_save`: 当前 `false`
  - `debounce_seconds`: 当前 `30`
  - `ignored_paths`: `raw/`, `output/`, `user/kb/`, `.runtime/`
- `identity`
  - 支持通过 `config.py set-runtime-pref --section identity --key default_confirmed_by --value <human>` 写入。
  - `kb init` 会要求 human confirmer，拒绝 AI signer。

### 1.3 Markdown Settings：`kb/config/research-settings.md`

- 可通过 `config.py toggle --key <中文条目> --state on|off` 更新。
- 当前条目覆盖：
  - 自动入库事实类基础信息。
  - 维护 topic / tag / candidate pool。
  - source search 先 staging。
  - 新论文入库后自动 quick-screen。
  - intake 阶段预热 PDF parse cache。
  - 自动完整论文笔记。
  - 完整笔记后自动提取 Figure / Table。
  - 完整笔记后自动刷新结构。
  - 自动生成周报素材。
  - 自动提炼 PPT 表述。
  - 自动记录中间讨论。
  - PDF Figure/Table caption-region 裁切。
  - 过滤空白 / mask-like 图。
  - AI 推断 / 评价等待人工确认。
  - paper structure / figure extraction 等待确认。
  - idea review / select-best 保留显式决策痕迹。

### 1.4 Topic / Tag / Pool 个性化

- `research-config-manager`
  - 写 seed / policy 输入。
  - `set-taxonomy-seed --topic ... --tag ... --alias ...`
  - `set-pool --pool ... --topic ... --tag ... --description ...`
- `knowledge-base-manager`
  - 实际治理 `topic-taxonomy.yaml` 与 `candidate-pools.yaml`。
  - `govern --id/--kind/--all --topic --tag --pool`
  - `rebuild-governance`
- 当前 candidate pools 样例：
  - `current-reading`
  - `current-ideas`
  - `candidate-baselines`
  - `legacy-library-papers`

## 2. Skill 功能面扫描

### 2.1 `source-intake`

- 定位：paper / repo / blog 的入口层，先 staging、去重、备份 raw，再创建 lightweight canonical unit。
- 功能点：
  - `search` / `stage-search`
    - 记录外部搜索候选。
    - 参数：`--kind paper|repo|blog`、`--query`、`--stage-id`、`--candidate-url`、`--candidate-title`、`--note`
    - 产出：source-search staging 文档，候选带 candidate id / status。
  - `show-stage`
    - 查看 staging 详情。
    - 输出 candidate id、status、title、url。
  - `add`
    - 从 `--source` 或 `--stage-id + --candidate-id` materialize。
    - 参数：`--kind paper|repo|blog`、`--source`、`--maturity lightweight|complete`、`--title`、`--pool`
    - 检测重复 source/title，重复则不新建 record。
    - 备份 source 到 `kb/raw/` 或记录 remote source。
    - 生成 compact unit id。
    - 应用 topic/tag/pool governance。
    - 对 paper 抽取 basic metadata：title/authors/year/source_url/abstract/arxiv_id/doi。
  - paper intake 自动后续动作：
    - 若 `parse_cache_prewarm_on_intake=true` 且不 auto screen，则预热 parse cache。
    - 若 `auto_screen_on_intake=true` 或 `--maturity complete`，自动 `paper.py screen`。
    - 若 `--maturity complete`，自动 `complete-note`。
    - 若 quick-screen 后满足 `auto_complete_note_condition`，可自动 `complete-note`。
    - 若完整笔记生成且 `auto_extract_figures_after_note=true`，自动 `extract-figures`。
    - 若完整笔记生成且 `auto_refresh_structure_after_note=true`，自动 `refresh-structure`。
  - guidance hints：
    - 提醒 `config.py guide --focus paper-intake`。
    - 提醒开启 `auto_complete_note`。
    - 提醒把 `complete_note_mode` 改为 `draft`。
    - 提醒开启 figure/table extraction。
- 个性化入口：
  - `paper.*` runtime preferences。
  - `--pool` 与 staging candidate hints。
  - taxonomy seed / pool policy。

### 2.2 `paper-analyst`

- 定位：已有 paper unit 的深分析 owner。
- 功能点：
  - `prewarm-cache`
    - 参数：`--paper-id`、`--force`、`--defer-post-actions`
    - 读取 PDF / markdown / text source，生成 `parse-cache.yaml`。
    - parse 范围由 `parse_cache_front_limit`、`parse_cache_back_limit`、`parse_cache_per_page_char_limit` 控制。
  - `screen`
    - 参数：`--paper-id`、`--mode auto|...`、`--defer-post-actions`
    - 生成 `screening.yaml`。
    - 写入 quick_screen：
      - worth_deep_reading
      - judgement_reason
      - takeaways
      - backing_strength
      - result_strength
      - novelty
      - experiment_quality
      - reliability
      - relevance_to_current_research
      - evidence_pages
      - risks
      - keyword_hits
      - recommended_next_action
    - 将 record 置为 `screened` / `lightweight`。
    - `confirmation_status=pending_user_confirmation`。
  - `complete-note`
    - 参数：`--paper-id`、`--mode auto|scaffold|draft`、`--defer-post-actions`
    - 生成 `note.md`。
    - 更新 maturity 为 `complete`。
    - `payload.state.full_note_status=pending_user_confirmation`。
    - `payload.state.note_generation_mode=scaffold|draft`。
  - `extract-figures`
    - 生成 `figures.yaml` 与 assets。
    - caption-region 优先，支持 table。
    - 过滤纯白、低颜色、mask-like 图片。
    - 写入 candidate_figures / key_figures / filtered_assets / asset_counts / filter_policy。
  - `refresh-structure`
    - 生成 `structure.yaml`。
    - 从 parse cache 与 note 检测论文结构。
  - `confirm`
    - 参数：`--paper-id`、`--confirmed-by`、`--evidence`。
    - 需要 human provenance。
  - `reject`
    - 将 paper judgement 标为 rejected。
- 个性化入口：
  - `paper.screening_mode`
  - `paper.screening_context_pages`
  - `paper.screening_max_chars`
  - `paper.complete_note_mode`
  - `pdf.figure_*`
  - `pdf.filter_blank_and_mask_images`

### 2.3 `repo-analyst`

- 定位：repo unit 的结构扫描、能力映射、复用判断。
- 功能点：
  - `scan-structure`
    - 参数：`--repo-id`
    - 搜索 repo root 候选。
    - 读取 README / 目录 / 配置线索。
    - 生成 structure payload。
  - `map-capability`
    - 参数：`--repo-id`
    - 推断 candidate roles。
    - 写入 inferred topics / tags。
    - 写入 reuse candidates。
  - `complete-note`
    - 参数：`--repo-id`
    - 生成完整 repo note scaffold。
  - `confirm`
    - 参数：`--repo-id`、`--confirmed-by`、`--evidence`
    - 确认 AI reuse judgement。
- 个性化入口：
  - topic/tag/pool governance。
  - candidate pool 例如 `candidate-baselines`。

### 2.4 `blog-analyst`

- 定位：blog / technical article unit 的摘要、可信度、复用解释材料。
- 功能点：
  - `summarize`
    - 参数：`--blog-id`
    - 轻量摘要。
    - positioning：postface / walkthrough / opinion / tutorial。
  - `complete-note`
    - 参数：`--blog-id`
    - 完整 note：
      - key concepts
      - credibility
      - 作者背景
      - 出版平台
      - 是否引用同行评议来源
      - 可复现要素
      - reusable explanation material
  - `confirm`
    - 参数：`--blog-id`、`--confirmed-by`、`--evidence`
- 个性化入口：
  - report / weekly 是否复用 explanation material。
  - topic/tag/pool governance。

### 2.5 `idea-workbench`

- 定位：idea unit 捕获、多候选、分析、review、显式选择。
- 功能点：
  - `capture`
    - 参数：`--title`、`--source`、`--problem`、`--hypothesis`、`--pool`
    - 生成 draft idea。
    - `information_types=user_opinion,inference,unverified`。
  - `generate`
    - 参数：`--title`、`--source`、`--problem`、`--hypothesis`、`--count`、`--pool`、`--bundle-id`
    - 生成多候选 idea bundle。
    - 产出 `kb/synthesis/idea-pools/<bundle-id>/...`。
    - 每个候选包含 candidate strategy / problem / hypothesis / next_actions。
  - `analyze`
    - 参数：`--idea-id`
    - 生成 `analysis.yaml`。
    - novelty / feasibility / evidence gaps / next actions。
    - status 进入 `pending`。
  - `review`
    - 参数：`--idea-id`
    - 生成 `review.yaml` 与 `idea-card.md`。
    - score_breakdown、recommendation、evidence_gaps、killer_questions。
    - maturity 进入 `complete`。
  - `review-assist`
    - 参数：`--idea-id` 可重复、`--pool`、`--bundle-id`
    - 对一组 idea 生成 review-assist 文档。
    - 会补齐未开始的 review payload。
  - `select`
    - 参数：`--idea-id`、`--confirmed-by`、`--evidence`
    - 显式选择单个 idea。
    - status 变 `selected`。
    - selection provenance 落盘。
  - `select-best`
    - 参数：`--idea-id` 可重复、`--pool`、`--bundle-id`、`--confirmed-by`、`--evidence`
    - 按 review score 排序并选择最高分。
    - 写 `selection.yaml`。
  - `archive`
    - 参数：`--idea-id`
    - 归档 idea。
  - legacy id 支持：
    - 若传入 legacy id，会提示 canonical id 与 canonical path。
- 个性化入口：
  - `user-profile.preferences.novelty_bar`
  - candidate pool。
  - topic/tag governance。
  - human confirmation identity。

### 2.6 `experiment-workbench`

- 定位：experiment unit、run log、follow-up、diagnosis、phase feedback 支撑。
- 功能点：
  - `plan`
    - 参数：`--title`、`--program-id`、`--goal`、`--idea-id`、`--hypothesis`
    - 创建 experiment record。
    - status=`planned`，confirmation auto_confirmed。
    - 向 program `reporting-events.yaml` 写 `experiment-planned`。
  - `log-run`
    - 参数：
      - `--experiment-id`
      - `--change` 可重复
      - `--metric` 可重复，形如 key=value
      - `--result-summary`
      - `--next-action` 可重复
      - `--artifact` 可重复
      - `--outcome success|partial|failed|blocked|inconclusive`
      - `--classification method|implementation|data|evaluation|resource|environment|process|unknown`
      - `--why-this-run`
      - `--tested-hypothesis`
    - 写 `runs/run-*.md`。
    - 追加 `run-log.yaml`。
    - 同步 `run-log.md`。
    - 更新 record results / process / diagnosis.next_actions。
    - 写 program reporting event `experiment-run`。
  - `follow-up`
    - 参数：`--experiment-id`、`--action`、`--category`、`--priority low|normal|high|critical`、`--status open|doing|blocked|done|dropped`、`--evidence-needed`
    - 追加 `follow-ups.yaml`。
    - 同步 `follow-ups.md`。
    - 写 program reporting event。
  - `diagnose`
    - 参数：`--experiment-id`、`--summary`、`--category`、`--likely-cause`、`--ruled-out`、`--unknown`、`--next-action`
    - 追加 `diagnoses.yaml`。
    - 同步 `diagnosis.md`。
    - diagnosis 是 inference/evaluation，默认 pending。
    - 写 program reporting event。
  - `confirm`
    - 参数：`--experiment-id`、`--confirmed-by`、`--evidence`
    - 确认 experiment findings。
- phase workflow：
  - 推荐每个 phase 创建 parent experiment。
  - 每个 arm × seed 记录 run-log。
  - metrics 用 `--metric key=value`。
  - surprises 走 `diagnose`。
  - implementation issues 走 `follow-up`。
  - feedback report 路径约定：`runs/{phase-id}/feedback-to-main-agent-{YYYY-MM-DD}.md`
- 个性化入口：
  - program id / idea id。
  - classification vocabulary 当前固定。
  - reporting-events 影响 report-author。

### 2.7 `knowledge-base-manager`

- 定位：KB schema、index、topic/tag/pool、links、lifecycle、nested git。
- 功能点：
  - `init`
    - 初始化目录、config、index。
  - `lint`
    - 检查 record schema、lifecycle、confirmation gate。
    - 检查 program/unit 双向链接与 YAML duplicate-key 风险。
  - `index`
    - 重建 `kb/index.yaml` 与 `kb/index.md`。
  - `storage-sync`
    - 把 legacy raw/output 收口到 `kb/`。
    - 重写旧 storage references。
    - 清理 nested repo metadata。
  - `git-init`
    - 参数：`--no-initial-commit`、`--message`
    - 初始化 `kb/` nested Git repo。
  - `git-status` / `git-log` / `git-checkpoint`
    - 查询或提交 kb repo。
  - `compact-ids`
    - 参数：`--kind`、`--apply`
    - dry-run 或实际缩短/规范 unit id。
    - apply 后重建 governance/index 并 checkpoint。
  - `rebuild-governance`
    - 重建 topic taxonomy 与 candidate pool catalogs。
  - `query`
    - 参数：`--query`、`--kind`、`--pool`、`--confirmation-status`
    - 输出命中 unit、score、next command、confirm command。
  - `review-queue`
    - 参数：`--kind`、`--confirmation-status`、`--limit`、`--confirm`、`--confirmed-by`、`--evidence`
    - 列待确认项或批量确认。
  - `confirm`
    - 参数：`--id` 可重复或 `--all-reviewed`、`--kind`、`--limit`、`--confirmed-by`、`--evidence`
    - 批量确认 pending records。
  - `refresh-schema`
    - 参数：`--id` 可重复、`--kind`
    - 回填最新 record schema。
  - `govern`
    - 参数：`--id` 可重复、`--kind`、`--topic`、`--tag`、`--pool`、`--all`、`--no-infer`、`--source-label`
    - 应用 topic/tag/pool 治理。
  - `link`
    - 参数：`--from-id`、`--to-id`、`--relation`、`--note`
    - 建立 unit 间 links。
  - `promote`
    - 参数：`--id`、`--status`、`--maturity`、`--confirmation-status`、`--confirmed-by`、`--evidence`
    - 推进 lifecycle 或 confirmation。
- 个性化入口：
  - `RESEARCH_VALIDATE_STRICT=1` 严格校验。
  - `versioning.*`。
  - taxonomy/pool catalogs。

### 2.8 `research-config-manager`

- 定位：配置 owner，管理 user profile、settings、runtime preferences、taxonomy seed、pool policy。
- 功能点：
  - `init`
    - 初始化 profile、taxonomy、candidate pools、runtime preferences。
  - `show`
    - 参数：`--section all|profile|settings|taxonomy|pools|runtime`、`--dump`
    - 展示路径或 dump 内容。
  - `set`
    - 参数：`--key dotted.path`、`--value`
    - 写 user profile。
  - `toggle`
    - 参数：`--key <中文设置项>`、`--state on|off`
    - 更新 `research-settings.md`，并同步相关 runtime preferences。
  - `capture-resources`
    - 参数：`--statement`、`--label`
    - 存自然语言资源画像。
  - `set-taxonomy-seed`
    - 参数：`--topic`、`--alias`、`--tag`、`--note`、`--status`
    - 写 taxonomy seed。
  - `set-pool`
    - 参数：`--pool`、`--topic`、`--tag`、`--description`、`--status`
    - 写 candidate pool metadata/policy。
  - `guide`
    - 参数：`--focus all|paper-intake`
    - 输出当前 runtime 模式说明与改法。
  - `set-runtime-pref`
    - 参数：`--section browser|identity|paper|pdf|versioning`、`--key`、`--value`
    - 持久化 runtime preferences。

### 2.9 `research-orchestrator`

- 定位：program state、open questions、evidence requests、decision log、reporting events、skill routing。
- 功能点：
  - `init-program`
    - 参数：`--program-id`、`--question`、`--goal`
    - 创建 `kb/programs/<program-id>/`。
    - 写 state/workflow files/reporting event。
  - `set-stage`
    - 参数：`--program-id`、`--stage`
    - 更新 stage，写 reporting event。
  - `status`
    - 展示 program_id、stage、question、goal、active_unit_ids、counts、workflow_files。
  - `dashboard`
    - 参数：`--limit`
    - 优先级 dashboard。
  - `next`
    - 参数：`--limit`
    - 跨 program next actions。
  - `auto`
    - 参数：`--max-steps`、`--execute`
    - 计划或执行安全下一步。
    - safe steps：screen、build-index、refresh、generate-note。
    - 执行时给 child env / argv 传 root。
  - `route`
    - 参数：`--task`
    - 根据关键词路由到 owner skill。
  - `attach-unit`
    - 参数：`--program-id`、`--unit-id`
    - 绑定 unit 到 program，并回填 unit-side `program_ids`。
  - `query-program`
    - 参数：`--program-id`、`--question`
    - 写 durable query note。
  - `add-open-question`
    - 参数：`--program-id`、`--question`、`--context`、`--priority`、`--owner`、`--related-unit`
  - `answer-question`
    - 参数：`--program-id`、`--question-id`、`--answer`
  - `drop-question`
    - 参数：`--program-id`、`--question-id`、`--reason`
  - `request-evidence`
    - 参数：`--program-id`、`--question`、`--needed`、`--source-type paper|repo|blog|experiment|benchmark|user|unknown`、`--priority`、`--blocking`、`--related-unit`
  - `resolve-evidence`
    - 参数：`--program-id`、`--evidence-id`、`--result`、`--artifact`
  - `drop-evidence`
    - 参数：`--program-id`、`--evidence-id`、`--reason`
  - `log-decision`
    - 参数：`--program-id`、`--decision`、`--rationale`、`--stage`、`--evidence`、`--alternative`、`--confirmation-status`
  - `add-reporting-event`
    - 参数：`--program-id`、`--title`、`--summary`、`--event-type`、`--stage`、`--artifact`、`--tag`
- phase-by-phase workflow：
  - phase plan 必须包含 12 节：goal、inputs、outputs、methodology、arms、evaluation、criteria、budget、failure handling、run grid、feedback protocol、out of scope。
  - executor 反馈 report 必须包含 8 节：status、metrics、ablation decisions、surprises、open issues、new OQs、artifacts、recommendation。
  - main agent 必须验证 feedback vs artifacts，更新 state/decision/OQ/reporting events。

### 2.10 `method-designer`

- 定位：把 selected idea 转成 method handoff。
- 功能点：
  - `design`
    - 参数：`--idea-id`、`--program-id`、`--repo-id` 可重复、`--interface` 可重复、`--baseline`、`--metric` 可重复、`--risk` 可重复。
    - 拒绝未 selected idea。
    - 生成 repo choice。
    - 写 interfaces。
    - 写 expanded experiment matrix。
    - 覆盖 baseline parity、minimal variant、ablation、stress/failure slices。
    - 写 program reporting event。
- 个性化入口：
  - repo candidate pool。
  - preferred metrics。
  - risk vocabulary 可通过参数传入。

### 2.11 `literature-synthesizer`

- 定位：跨 unit 的 survey、review、taxonomy。
- 功能点：
  - `survey`
    - 参数：`--field` / 实现侧也支持 query 类筛选。
    - 可按 pool 选证据集。
  - `review`
    - 参数：`--query`、`--kind`、`--topic`、`--tag`、`--pool`
    - 生成 review 视图。
  - `taxonomy`
    - 参数：`--topic`
    - 生成 topic taxonomy 视图。
  - 核心要求：
    - 明确区分 Observed 与 Inferred。
    - 产物落到 `kb/synthesis/`。
- 个性化入口：
  - topic/tag/pool。
  - language/style profile。

### 2.12 `report-author`

- 定位：从 program reporting-events 生成周报、PPT 素材、阶段总结、写作素材。
- 功能点：
  - `weekly`
    - 参数：`--program-id`、`--limit`
    - drafting/indexing aid，需要后续 polish。
    - 输出应是 advisor-facing standalone report。
  - `ppt-materials`
    - 参数：`--program-id`、`--stage`
    - 产出适合 slides 的事件标题、one-line summary、artifact pointers。
  - `stage-summary`
    - 参数：`--program-id`、`--stage`
    - 按阶段过滤 reporting events。
  - `writing-materials`
    - 参数：`--program-id`
    - 写作素材综合。
  - 约束：
    - reporting-events 是主源。
    - 不凭空补 milestone。
    - local links 只能作 optional provenance。
    - common terms 不强制 glossary。
- 个性化入口：
  - `user-profile.preferences.summary_style`
  - `personalization.reporting_style`
  - stage / time window。

### 2.13 `research-navigator`

- 定位：人面向入口页与本地 browser/workbench。
- 功能点：
  - `navigate.py refresh`
    - 刷新 `kb/user/` 下入口页。
  - `navigate.py current-state`
    - 输出 active program 状态、stage、next-actions。
  - `navigate.py reading-list`
    - 输出阅读列表。
  - `build_kb_browser.py`
    - 构建 `kb/user/kb/` browser snapshot。
  - `open_kb_browser.py`
    - 参数：`--host`、`--port`、`--root/--project-root`、`--no-browser`、`--print-url`、`--ready-timeout`
    - 启动或复用 daemon。
  - `serve_kb_browser.py`
    - 参数：`--host`、`--port`、`--root/--project-root`、`--debounce-seconds`
    - 依赖 `watchdog`。
    - watch `kb/units`、`programs`、`synthesis`、`user`、`config`、`intake` 与 index。
    - 文件变化后 debounce rebuild。
  - Browser APIs：
    - `GET /api/healthz`
    - `GET /api/version`
    - `POST /api/rebuild`
    - `GET /api/file?path=...`
    - `PUT /api/file`
    - `POST /api/terminal/open`
    - `POST /api/terminal/input`
    - `POST /api/terminal/resize`
    - `GET /api/terminal/poll`
    - `GET /api/system-terminal/targets`
    - `POST /api/system-terminal/open`
  - Workbench 文件限制：
    - 可读：`.md`, `.markdown`, `.yaml`, `.yml`, `.txt`, `.log`, `.json`, `.py`, `.sh`, `.toml`
    - 可写：`.md`, `.markdown`, `.txt`
    - 禁写：`.git`, `node_modules`, `kb/user/kb`, `kb/user/navigator`
    - 单文件大小限制：约 1.5MB。
  - Terminal：
    - bottom terminal。
    - Codex CLI launch。
    - macOS system terminal API。
  - `status_kb_browser.py`
    - 参数：`--json`
  - `stop_kb_browser.py`
    - 停止 daemon。
  - `open_user_hub.py`
    - compatibility alias。
- 个性化入口：
  - `browser.default_workbench_mode`
  - `browser.default_terminal_mode`
  - `browser.auto_open_recent_file`
  - `versioning.commit_on_browser_save`

### 2.14 `discussion-archivist`

- 定位：把重要技术路线讨论归档到 program discussions。
- 功能点：
  - `archive`
    - 参数：`--program-id`、`--title`、`--summary`、`--decision`、`--tradeoff` 可重复、`--open-question` 可重复、`--next-action` 可重复。
    - 产出：`kb/programs/<program-id>/discussions/<slug>.md`
    - decision 留空时写“待确认”。
    - tradeoff / open question / next action 可为空，模板写占位。
    - 写 program reporting event，stage=`discussion`。
  - 与 orchestrator decision-log 边界：
    - discussion 记录过程、权衡、未决问题。
    - decision-log 记录已拍板的单点决策。

### 2.15 `wiki-adapter`

- 定位：用户说 wiki / 知识库 / 词条时的薄路由。
- 功能点：
  - `query`
    - 参数：`--question`
    - 查询结果写入 `kb/synthesis/wiki/`，作为可复用笔记。
  - `add`
    - 参数：`--kind paper|repo|blog`、`--source`
    - 转发 `source-intake add`。
  - `lint`
    - 转发 `knowledge-base-manager lint`。
  - 路由规则：
    - add paper/repo/blog → source-intake。
    - query survey/taxonomy → literature-synthesizer。
    - 单条查找 → knowledge-base-manager query。
    - schema/lint/index → knowledge-base-manager。
    - topic/tag/pool → config-manager + kb-manager。
    - 新用户起步 → research-navigator。
    - program 状态 → research-orchestrator。

### 2.16 `skill-evolution-advisor`

- 定位：workflow friction、用户纠错、习惯/坑/skill defect 的演化记忆。
- 功能点：
  - `learnings.py log`
    - 参数：`--category`、`--text`、`--source`、`--skill`、`--context`
    - 记录 lightweight learning，默认 pending。
  - `learnings.py recall`
    - 参数：`--kind all|defects|...`、`--limit`
    - 回忆 confirmed habits / gotchas / defects。
  - `learnings.py review`
    - 参数：`--id`、`--status`
    - 用户审阅 learning。
  - `learnings.py promote`
    - 参数：`--id`
    - 将 learning 推进为更正式记忆/配置。
  - `create_retrospective.py`
    - 参数：`--slug`、`--skill`、`--target-skill`、`--task-summary`、`--observed-issue`、`--suggestion`、`--stdout-prompt`、`--root`
    - 写 `kb/memory/skill-evolution/retrospectives/<timestamp>-<slug>.md`
    - 可打印 AI-ready patch prompt。
  - policy：
    - `allow_implicit_invocation: true`
- 个性化入口：
  - confirmed habits / gotchas。
  - skill defects 不自动改代码，只记录待审。

### 2.17 `kb-cli`

- 定位：薄 dispatcher，把高频 research 操作转成 `kb` 动词。
- 功能点：
  - `help`
    - 固定菜单。
  - `init`
    - 转发 `kb.py init` 与 `config.py init`。
    - TTY 下询问：
      - confirmer name
      - Language：`zh|en`
      - Commit cadence：`manual|milestone|aggressive`
      - Auto-screen on intake：`true|false`
      - 可选 persona：term style / research focus / resources / reporting style / collaboration boundaries
    - 非 TTY 自动降级。
    - 支持 headless 参数：
      - `--name`
      - `--lang`
      - `--auto-commit`
      - `--auto-screen`
      - `--persona-focus`
      - `--persona-resources`
      - `--persona-report`
      - `--persona-boundaries`
      - `--persona-term`
      - `--git-init`
  - `doctor`
    - 输出 Python、YAML、PDF 后端、managed venv 状态。
  - `status [program]`
    - 转发 navigator current-state。
    - 带 program 时追加 orchestrator status。
  - `next [program]`
    - 转发 orchestrator next。
  - `find <keywords...>`
    - 转发 kb query。
  - `recall [kind]`
    - 转发 learnings recall。
  - `add <src> [--kind]`
    - 根据 arxiv/pdf/github/git 推断 paper/repo/blog。
    - 转发 source-intake add。
  - `review [fuzzy]`
    - 列 pending confirmations。
    - TTY 下逐条确认/拒绝/跳过/退出。
    - 写入前统一要求 evidence。
- 个性化入口：
  - 是当前最适合做“初始化向导”的位置。
  - 可把更多 persona 字段接入 user-profile。

## 3. 交叉流程图

### 3.1 新材料进入系统

1. `source-intake search/stage-search`
2. `source-intake add`
3. `knowledge-base-manager govern/index`
4. 按 kind 路由：
   - paper → `paper-analyst screen/complete-note/extract-figures/refresh-structure`
   - repo → `repo-analyst scan-structure/map-capability/complete-note`
   - blog → `blog-analyst summarize/complete-note`
5. AI judgement 进入 review queue。
6. `knowledge-base-manager review-queue/confirm` 或 kind analyst `confirm`。

### 3.2 idea 到实验

1. `idea-workbench capture/generate`
2. `idea-workbench analyze`
3. `idea-workbench review` 或 `review-assist`
4. 用户显式 `select` / `select-best`
5. `method-designer design`
6. `experiment-workbench plan/log-run/follow-up/diagnose/confirm`
7. `research-orchestrator` 更新 decision/open questions/evidence/reporting events。

### 3.3 program 到报告

1. `research-orchestrator init-program`
2. `attach-unit` / `request-evidence` / `add-open-question`
3. 各 owner skill 写 reporting-events。
4. `report-author weekly/stage-summary/ppt-materials/writing-materials`
5. `research-navigator refresh` 提供人面向入口。

## 4. 待办层级结构

### A. 功能清单与文档一致性

- [ ] A1. 给每个 skill 建立 machine-readable capability manifest。
  - [ ] A1.1 从 `SKILL.md` 抽取 scope / workflow / commands。
  - [ ] A1.2 从脚本 argparse 抽取 subcommands / flags / choices。
  - [ ] A1.3 从 `agents/openai.yaml` 抽取 display_name / short_description / default_prompt / policy。
  - [ ] A1.4 输出到 `kb/config/skill-capabilities.yaml` 或 `.agents/skills/index.yaml`。
- [ ] A2. 校验 `SKILL.md` 与脚本命令是否 drift。
  - [ ] A2.1 检查文档列出的命令真实存在。
  - [ ] A2.2 检查脚本新增命令是否写入 SKILL.md。
  - [ ] A2.3 接入 pytest 或 `kb doctor`。
- [ ] A3. 为每个 skill 增加“支持的个性化设置”章节。
  - [ ] A3.1 source-intake / paper-analyst 明确 paper/pdf runtime keys。
  - [ ] A3.2 research-navigator 明确 browser/versioning runtime keys。
  - [ ] A3.3 report-author 明确 profile/reporting_style keys。

### B. 个性化配置体系

- [ ] B1. 梳理 persona schema。
  - [ ] B1.1 明确定义 `personalization.term_style`。
  - [ ] B1.2 明确定义 `personalization.research_focus`。
  - [ ] B1.3 明确定义 `personalization.resources`。
  - [ ] B1.4 明确定义 `personalization.reporting_style`。
  - [ ] B1.5 明确定义 `personalization.collaboration_boundaries`。
- [ ] B2. 让更多 skill 读取 persona。
  - [ ] B2.1 report-author 读取 `reporting_style`。
  - [ ] B2.2 literature-synthesizer 读取 language / term style。
  - [ ] B2.3 idea-workbench 读取 novelty_bar / research_focus。
  - [ ] B2.4 method-designer 读取 resources / constraints。
- [ ] B3. 扩展 `config.py guide`。
  - [ ] B3.1 `--focus paper-intake` 已有，补 `idea-review`。
  - [ ] B3.2 补 `browser-workbench`。
  - [ ] B3.3 补 `reporting`。
  - [ ] B3.4 补 `versioning`。
- [ ] B4. runtime preference 类型校验。
  - [ ] B4.1 browser keys 校验枚举/布尔。
  - [ ] B4.2 paper keys 校验枚举/整数。
  - [ ] B4.3 pdf keys 校验浮点/布尔。
  - [ ] B4.4 versioning keys 校验枚举/路径列表。

### C. Intake 与分析自动化

- [ ] C1. 修正 source-intake 中 figure extraction 被调用两次的风险。
  - [ ] C1.1 检查 `auto_extract_figures_after_note` 分支。
  - [ ] C1.2 添加回归测试。
- [ ] C2. paper auto complete 条件更细化。
  - [ ] C2.1 支持 `strong_relevance`。
  - [ ] C2.2 支持 `suggested_worth_reading`。
  - [ ] C2.3 支持 `after_screen`。
  - [ ] C2.4 支持 `manual_only`。
- [ ] C3. search staging 候选增强。
  - [ ] C3.1 候选支持 topic/tag/pool hints。
  - [ ] C3.2 候选支持 source confidence。
  - [ ] C3.3 候选支持 rejection reason。
- [ ] C4. blog/repo intake 自动后续动作。
  - [ ] C4.1 blog add 后可选 auto summarize。
  - [ ] C4.2 repo add 后可选 auto scan-structure。
  - [ ] C4.3 runtime preferences 增加 blog/repo section。

### D. Confirmation 与 review queue

- [ ] D1. 统一所有 confirm/reject 命令的 provenance。
  - [ ] D1.1 paper/repo/blog/experiment confirm 要求 human signer。
  - [ ] D1.2 idea select/select-best 要求 evidence。
  - [ ] D1.3 kb promote confirmed 时要求 confirmed_by/evidence。
- [ ] D2. review queue UX。
  - [ ] D2.1 显示 information_types。
  - [ ] D2.2 显示 artifact path。
  - [ ] D2.3 支持按 program 过滤。
  - [ ] D2.4 支持批量 reject with reason。
- [ ] D3. confirmation dashboard。
  - [ ] D3.1 navigator current-state 增加 pending confirmations 摘要。
  - [ ] D3.2 browser 增加 review queue tab。

### E. Program 编排

- [ ] E1. `orchestrate auto` 扩展 safe steps。
  - [ ] E1.1 blog summarize。
  - [ ] E1.2 repo scan-structure。
  - [ ] E1.3 idea review scaffold。
  - [ ] E1.4 仍保持 pending gates。
- [ ] E2. dashboard 排序透明化。
  - [ ] E2.1 输出 priority score breakdown。
  - [ ] E2.2 显示 blocking evidence count。
  - [ ] E2.3 显示 stale stage / stale next-action。
- [ ] E3. phase workflow 自动检查。
  - [ ] E3.1 检查 phase plan 12 节是否完整。
  - [ ] E3.2 检查 feedback report 8 节是否完整。
  - [ ] E3.3 检查 metrics 是否有 artifact backing。
  - [ ] E3.4 不完整时拒绝推进 state。

### F. Navigator / Browser

- [ ] F1. Browser 个性化设置接入 UI。
  - [ ] F1.1 默认 mode 从 `browser.default_workbench_mode` 读取。
  - [ ] F1.2 terminal 默认从 `browser.default_terminal_mode` 读取。
  - [ ] F1.3 最近文件从 `auto_open_recent_file` 读取。
- [ ] F2. Browser 安全边界文档化。
  - [ ] F2.1 明确可读 suffix。
  - [ ] F2.2 明确可写 suffix。
  - [ ] F2.3 明确 blocked roots。
- [ ] F3. Workbench 编辑后 checkpoint。
  - [ ] F3.1 `versioning.commit_on_browser_save=true` 时提交。
  - [ ] F3.2 提交信息包含相对 path。
  - [ ] F3.3 debounce 与 manual save 交互测试。

### G. Reporting

- [ ] G1. weekly report polish pipeline。
  - [ ] G1.1 `report.py weekly` 只做 draft。
  - [ ] G1.2 增加 final polish checklist。
  - [ ] G1.3 检查 standalone completeness。
- [ ] G2. reporting-events coverage。
  - [ ] G2.1 method design 完成必须发 event。
  - [ ] G2.2 experiment run/follow-up/diagnosis 已发 event，补测试。
  - [ ] G2.3 discussion archive 发 event，补索引。
- [ ] G3. 输出类型拆分。
  - [ ] G3.1 weekly。
  - [ ] G3.2 stage-summary。
  - [ ] G3.3 ppt-materials。
  - [ ] G3.4 writing-materials。
  - [ ] G3.5 advisor email brief。

### H. Skill 演化闭环

- [ ] H1. 自动 recall confirmed learnings。
  - [ ] H1.1 session start 时可读 confirmed habits。
  - [ ] H1.2 routing 相关 gotchas 注入对应 skill。
- [ ] H2. skill defect 生命周期。
  - [ ] H2.1 log defect。
  - [ ] H2.2 user review。
  - [ ] H2.3 create retrospective。
  - [ ] H2.4 生成 patch prompt。
  - [ ] H2.5 修复后关闭 defect。
- [ ] H3. retrospective 聚合报告。
  - [ ] H3.1 按 skill 聚合 recurring friction。
  - [ ] H3.2 按类型聚合：routing/schema/scripts/handoff/docs。
  - [ ] H3.3 输出月度 skill improvement plan。

### I. 安装与多 Agent 支持

- [ ] I1. Claude / Codex 安装路径说明。
  - [ ] I1.1 Claude project：`.claude/skills -> .agents/skills`。
  - [ ] I1.2 Claude system：`~/.claude/skills/<name>` symlink。
  - [ ] I1.3 Codex project：`.agents/skills` + `AGENTS.md`。
  - [ ] I1.4 Codex system：当前 best-effort，说明限制。
- [ ] I2. `install-lib/ws_sync.py` 能力文档化。
  - [ ] I2.1 只管理 `.agents/` 与 `AGENTS.md`。
  - [ ] I2.2 不碰 `kb/` / `.venv/`。
  - [ ] I2.3 manifest / drift / force 行为写入 install docs。
- [ ] I3. copy-project update 安全测试。
  - [ ] I3.1 local drift 阻断。
  - [ ] I3.2 near-empty source 防 mass deletion。
  - [ ] I3.3 AGENTS.md user-managed preservation。

## 5. 建议优先级

- P0：
  - C1 修正 source-intake figure extraction 双调用风险。
  - D1 confirmation provenance 统一。
  - E3 phase plan / feedback 完整性检查。
  - A2 docs/CLI drift 测试。
- P1：
  - B1/B2 persona schema 与跨 skill 读取。
  - E1 orchestrate auto 覆盖 blog/repo/idea 安全步骤。
  - F1 Browser runtime preferences 接入 UI。
  - G1 weekly report polish pipeline。
- P2：
  - A1 machine-readable capability manifest。
  - C3 staging 候选增强。
  - H3 skill improvement 聚合报告。
  - I1/I2 安装文档完善。

