你在开源 research-workspace 系统做 **Wave 2 · Track Gate（3.11 确认门验实质 + 分轨道）**。基线=已重构并 merge 的 main（`0d67971`）。独立 git worktree 从此 HEAD 分叉。全部改完自测、逐项 commit、**不 push**。

【本 track 拥有的文件（只动这些）】
- `.agents/lib/research/confirm.py`（重构后新模块：`validate_write`/`promote_record`/`require_confirmation_provenance`/`apply_confirmation` 在这。注意 `_record_needs_gate` 被放在 `records.py`，import 它即可，别搬）
- `.agents/skills/knowledge-base-manager/scripts/kb.py`（review-queue / confirm / batch confirm）
- 新增自己的测试到 `.agents/lib/research/tests/`
**不要碰** `sources.py` / `evidence.py` / `intake.py` / `records.py`（records 只读 import）。

【设计依据 + 现状证据（先读）】
- `temp/SYSTEM_DESIGN_SSOT.md` 3.11 决策（**先做①分轨道**：事实类元数据轻确认 / 判断类实质确认；**②连对降级暂不做**；关键决策/insight 主动询问）+ 原则3。
- 实证：G5 基线证明**当前门是空心的**——core_content 全空的 note 能被 promote 成 confirmed/fact（`kb/eval/research-value/reports/20260709T091601Z-tier1.md`：confirmed=0 但 auto_confirmed 空心=1，64/65 篇 paper 的 core_content 全空）。你要堵这个洞。

【红线（治理，不可破也不可放松）】
1. **禁自签**：AI 身份不能确认自己写的 pending（现有 `require_confirmation_provenance` 逻辑保留）。
2. **judgement 确认必留 evidence**：现有规则不动、不放松。
3. 你**只加严，不放松**：substance-check 是**新增**的拒绝条件，叠加在现有 gate 之上。
4. 绝不碰 kb/（真实数据）。测试用临时 KB。不 push。

============================================================
要做的
============================================================
1. **substance-check（堵空心门）**：在 `promote_record`（promote 到 `confirmed` 的路径）加实质校验——
   - 新增 `has_substantive_content(record, kind) -> bool`（放 confirm.py；需要 core_content 结构就从 records import）。
   - paper：`payload.core_content` 的 8 字段**不得全空** 且 note 正文不得只剩模板占位（如「方法机制：」「可引用表述：」这类空标题行）。其它 kind 给合理的等价判据。
   - promote-to-confirmed 时若 `has_substantive_content` 为假 → **拒绝**（明确报错，指出"内容为空/仅模板，不能确认为事实"）。auto_confirmed 的事实类元数据不受此限（见分轨道）。
2. **分轨道（①）**：把 pending 项按内容性质分两轨——
   - **事实类元数据轨**：`information_types ⊆ {fact}` 且属基本 metadata（标题/作者/arxiv/链接等）→ 可自动/轻确认（不要求 substance 的深校验，但仍禁自签）。
   - **判断类轨**：`information_types` 含 `inference`/`evaluation` → 需实质确认（substance-check + evidence，走现有 provenance 规则）。
   - 用一个 `confirmation_track(record) -> 'fact'|'judgement'` 判定函数收敛。
3. **review-queue 体现分轨道**（kb.py）：`review-queue` 输出把两轨**分组显示**；事实轨支持批量轻确认；判断轨每项标"需 evidence + 实质"，并把可直接跑的 confirm 命令渲染出来。保持现有 `--confirm/--confirmed-by/--evidence` 契约。
4. **关键决策/insight 主动询问的钩子**：不做后台推送；提供一个判据/标记，让上层 agent 知道"这条是判断轨的关键项，应主动请用户确认"（如在 review-queue 输出里高亮判断轨 top 项 + 一句"建议主动请用户拍板"）。不改 orchestrator 行为面，只提供信号。

============================================================
验证（全绿再交，逐条给实际输出）
============================================================
1. `python -m compileall .agents/lib .agents/skills` 通过；kb.py `--help` 通过。
2. 全量 `pytest` 全绿 + 新增测试：
   - **空心门被堵**：造一个 core_content 全空的 paper record，promote-to-confirmed **被拒**（断言 raise/非零 + 盘上仍 pending）。这条是本 track 的核心验收。
   - **有实质可确认**：填了 core_content 的 record 能正常 confirmed。
   - **分轨道**：纯 fact metadata 记录判为 fact 轨、含 inference/evaluation 判为 judgement 轨。
   - **红线回归**：自签仍被拒；judgement 无 evidence 仍被拒（现有护栏不被你破坏）。
3. **G5 门控指标应改善**：改完后，让 `has_substantive_content` 逻辑与 G5 harness 的"空心"判据一致（都认 core_content 全空=空心），这样 G5 的 H1 指标口径统一。（不改 G5 harness，只保证判据语义一致；如需对齐，在交付说明里指出差异。）
4. kb/ 零改动。

【交付】逐项 commit、不 push。附：空心门被堵的实测（promote 被拒 + 盘上仍 pending）、分轨道判定的样例、四条治理红线回归的实测（自签拒/judgement 空 evidence 拒/substance 拒/事实轨轻确认过）。**若 substance 判据对某些 kind 不好定，停下来在交付说明里列出并给建议，别硬编一个会误伤的判据。**
