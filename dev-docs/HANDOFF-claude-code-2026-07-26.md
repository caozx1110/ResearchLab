# HANDOFF：workspace-oss Wave 1 收尾（交给 Claude Code）

日期：2026-07-26。你在用户本机的 workspace-oss 仓库根目录工作（`~/Documents/rl2lab/projects/vla/workspace-oss`）。

## 0. 背景（30 秒版）

这是一套 20-skill 的中文优先研究知识库系统（`.agents/` 能力包 + `kb/` 用户数据，公开面=自然语言+16 个 `kb <verb>`）。刚完成一轮 6 agent 并行重构（Wave 1），**42 个文件的改动已直接写入本仓库工作树，未 commit**；改动在云沙箱经过合并后全链行为冒烟，但**完整 pytest 套件（约 1,900 项）因沙箱装不了 pytest 未跑**——这就是你的首要任务。

- 完整施工报告：`dev-docs/reviews/wave1-refactor-2026-07-26.md`
- 审阅与蓝图：`dev-docs/reviews/skill-review-2026-07-26.md`、`skill-refactor-blueprint-2026-07-26.md`（蓝图 v2 = 需求基线与决定的 SSOT）
- 另有 M0 结构调整已做：原 `temp/` 开发文档已移入 `dev-docs/`（待 git add），`.learnings/` 移入 `dev-docs/legacy-learnings/`，旧 `tmp/`（4.7GB 施工残渣）已移到 `_to_delete/tmp-20260726`（等用户手动删，你不要碰）。

## 1. 你的任务（按序）

### T1 跑套件并分诊修复
```bash
source .venv/bin/activate
python -m pytest .agents/lib/research/tests -x -q     # 先快速失败
python -m pytest .agents/lib/research/tests -q        # 再全量拿清单
```
对每个失败，先对照 §2"本轮有意的行为变更"分诊：
- **属有意变更** → 更新测试断言（这是预期的主要失败类型）；
- **属真回归** → 修代码，并在最终报告里单列。
**红线：严禁通过回退 §2 中的新行为来"修"测试。** 拿不准的先按测试意图（保护什么不变量）判断，仍不确定就在报告里标注让用户裁决。

已预告的断言漂移点（各 agent 自查发现）：
- `test_kb_cli_dispatcher.py`：①doctor 旧文案"论文解析能力已就绪"相关断言；②其 monkeypatch 的 capabilities 缺 `modules` 键（新 doctor 逻辑会读）；③约 L1093–1140 init 的 `quick_fields` / `apply.field_inputs` / `defaults` 精确相等断言需补两个新字段（`link_autodrive` 档位与 `discussion_style`）。
- `test_bootstrap.py`：PDF 后端探测/venv 准备/1 小时节流新分支需要覆盖或断言更新。
- `test_installer.py` / `test_r1_*`：ws_sync 旧英文错误文案与失败分支输出格式的断言。
- undo/restore 公开输出：undo 现在点名对象、restore 无参列最近 10 个操作（restore not-found 旧句被刻意保留）。
- `prepare-next-selection --json` 新增键为 additive，理论不破坏；如有精确相等断言需放宽。

### T2 修完后的回归验证
```bash
python -m pytest .agents/lib/research/tests -q                     # 必须全绿
python3 .agents/lib/research/skill_validator.py .agents/skills     # 期望 Validated 20 skills.
# 冷启动安装 + 黄金冒烟（一律在 /tmp 的 scratch 工作区，不许碰本仓库的 kb/）
mkdir -p /tmp/ws-ho && bash install.sh --claude --project /tmp/ws-ho && cd /tmp/ws-ho
KB=.agents/skills/kb-cli/scripts/kb
$KB --agent-protocol p1.json init --name t --lang zh --persona-term keep-en --persona-focus 测试 --auto-ingest-mode ask_first --discussion-style adaptive
$KB help | head -8          # 每行应带动词本名
$KB doctor                  # 本机有网：PDF 环境应能真正自动准备成功（沙箱里只能测失败路径）
```
**本机专属加测（沙箱做不了，价值最高）**：
1. `kb ingest` 一个真实本地 PDF → managed venv 自动装 pymupdf4llm → 深读骨架生成（验证 A1 幸福路径，沙箱只验证过失败降级）；
2. `kb ingest https://arxiv.org/abs/<任一论文>` 真实来源线（对应 release gate 的"真实来源验收"）；
3. `kb find <代码符号>` 在含真实 repo unit 的库上验证代码检索与索引重建耗时。
黄金对话全集见 `docs/GOLDEN_SUITE.md`（8 条，含步数/失败/耗时指标），时间允许跑完记录基线。

### T3 文档同步（小、明确）
1. `SCHEMAS.md` 增补三段：
   - runtime-preferences.yaml：可选顶层 `governance_profile: strict|personal`（缺省 strict）。personal 时 research-orchestrator `plan` 的 procedural_planning 决策可无 `preference_selection_id`；脚本以 canonical 硬约束（profile.resources / profile.constraints / runtime.autonomy.auto_execute_scope）兜底，`preference_selection_binding` 记 `{selection_id:"", governance_profile:"personal", task_context_digest, hard_value_digests}`；硬约束变化→决策 stale。
   - `kb/.runtime/portfolio-selection-draft.yaml`：非 canonical 的 Agent 填写草稿；`kind/scope/candidate_reference/preference_context` 为只读参考，verify/record 忽略额外字段。
   - Passage cache 节：extractor 范围现含 repo 源码树；代码段 `artifact` 为仓库相对路径、locator `path#L起-止`、FTS 新增 `code_terms` 辅助列、revision=`passages-v3`；monitor `apply --input` 同时接受 JSON 与 YAML，新增只读 `template` 子命令。
2. `docs/DESIGN.md` 约 L169："四类快速字段"→六类（加自动化档位、讨论风格），提及 config 的 `set-interaction`。
3. `CHANGELOG.md` Unreleased 下加 Wave 1 条目（按 A1–A6 分组，见施工报告）；**不要**升 rc 版本号（真实来源/Obsidian 验收未重跑）。
4. `.gitignore`：追加 `_to_delete/`；`temp/`、`.learnings/` 条目可保留（目录已空）。

### T4 提交
套件绿 + 冒烟过后才提交。建议分组 commit（安装链路 / 对话面 / owner 脚本 / lib 校验 / 代码检索 / 文档与 dev-docs / 测试同步），全部 `git add` 时注意新文件：`.agents/AGENT_GUIDE.md`、`docs/GOLDEN_SUITE.md`、`dev-docs/**`、`.gitignore` 改动。不 push、不打 tag。

## 2. 本轮有意的行为变更（分诊依据，不得回退）

**安装与依赖（A1 + 主控）**：ws_sync 失败保留中文首行并向 stderr 追加子进程输出末 ≤8 行；非 git 源→稳定 token `source-not-git-worktree` + 三条出路中文指引 + `--allow-snapshot-source`（install.sh `--from-snapshot`）确定性快照打包（警告前缀 `snapshot-source:`，刻意避开 `warn:`）；bootstrap"当前解释器可用"判定需 pymupdf4llm+fitz，缺则准备 managed venv，pip 失败优雅降级且 **1 小时节流**（marker `.venv/.pdf-backend-prep-last-attempt`）；venv 移交前补装 PDF 后端；doctor 公开话术诚实分支（未就绪→"论文 PDF 深读能力未就绪，首次需要时将自动准备运行环境；文本和网页资料仍可正常使用。"；`RESEARCH_NO_PDF_BACKEND`/`RESEARCH_NO_MANAGED_VENV`/显式 `RESEARCH_PYTHON` 时如实说明自动准备已关闭）；私有协议新增 `pdf_deep_read_ready`；sources.py 的 PDF 失败 backup_warning 带"下次 kb 命令自动准备后重试"提示；agent_plan `CONDITIONAL_RUNTIME_CONDITION` 文案同步。
**对话面（A2）**：help 带动词本名；undo 点名（op_type→中文标签，未映射兜底"知识库操作"）；restore 无参列最近 10 个（最新在前，编号执行时重解析，成功输出点名实际对象）；apply 失败协议 `details.review_apply_failure`（reason_code / expected.valid_confirm_refs / expected.apply_snapshot / token 误传检测 / ref_suggestions）；init 新 flags `--auto-ingest-mode ask_first|auto_deep_read`、`--discussion-style challenge|refine|adaptive` → `runtime.autonomy.link_autodrive` 与 `profile.personalization.discussion_style`，`apply.field_inputs` 含两项 canonical mapping，重复 init 零 churn；config 新增 `set-interaction`；`record-effective --selection-json` 兼容文件路径；eligible-preferences 错误一行化非零退出；BrokenPipeError 静默 rc=1。注意：`link_autodrive` 本轮只落偏好，ingest 尚未消费（Wave 2）。
**owner 脚本（A3）**：idea verify 全链无静默失败（`[reject] idea <op> 验证失败：<原因>`）；`--input` 三级解析（unit 相对→仓库相对→绝对，找不到列出尝试位置，工作区外拒绝）；corpus 违规列出可引用 source_unit_id 全集+扩语料方法；orchestrate `prepare-next-selection` 产 `kb/.runtime/portfolio-selection-draft.yaml` 预填草稿（personal+唯一候选连 selected 一起预填；已编辑未过期不覆盖；过期备份 `*.stale.yaml` 单槽）；`governance_profile: personal` 语义如 §T3-1 所述，**缺省 strict 行为逐字不变**；monitor `template` 子命令 + apply 收 YAML。
**lib 校验（A4）**：evidence 位置校验——`line=N`/`line=N-M` 与 quote 实际起始行核对、`section:<anchor>` 需 label 存在且 quote 在该 chunk 内，失败附实际位置；**告警放行（不 reject）清单**：`line:` 冒号形、`file:line` 散文形、裸 `section/page/anchor/para`、`section=X`、section 指 page-only PDF 缓存、无 chunks 结构的 YAML 消费者、仅 YAML 解码视图可匹配的 line=N、其余自由文本/URL；reject 后 `record.status=rejected`（显式 archived 保留）；audit 的 INTEGRITY_PROGRAM_LINK 只报三种真错误（引用不存在 unit / 引用已 rejected unit / unit 声称属于不存在 program），正向边+读时反链不算错；experiment plan/log-run 中文结果行+checkpoint。
**代码检索（A5）**：repo unit 源码进 FTS5（.py 按 def/class 符号切块带符号名，其余 40 行窗/8 行重叠；跳二进制/>200KB/VCS 目录；2000 文件/24MB 预算，超限显式告警）；FTS 新增 `code_terms` 拆词列（Markdown 段恒空串）；`PASSAGE_INDEX_REVISION=passages-v3`（旧缓存判 stale 自动回退内存检索——**首次 find 会走内存路径，重建索引后恢复，属预期**）；调度器零改动。
**文档（A6）**：`.agents/AGENT_GUIDE.md`（机制速查+交互章程 10 条，≈2.4k tokens）；19 份 SKILL.md 追加"启动澄清（Agent 用）"；AGENTS.md/README/USER_GUIDE 加引用；`docs/GOLDEN_SUITE.md`。

## 3. 约束与红线

- 公开 stdout：中文自然语言，无 traceback/绝对路径/内部 flag（owner 脚本 `[ok]/[reject]` 行允许）。已知遗留：lib/common.py 的 `[root] project:` 绝对路径行**本轮刻意未动**（大量测试依赖其输出），如要改属 Wave 2 且需同步测试。
- 不新增第三方依赖；Python 3.9 兼容语法。
- strict 治理档语义不得变；确认门（AI 不可自签、当前消息授权）不得动。
- 本仓库根的 `kb/` 是用户真实研究数据：**只读，勿写勿删**；一切冒烟用 /tmp scratch 工作区。
- `_to_delete/` 留给用户处理；`dev-docs/` 是开发史（原 temp/），只增不删。

## 4. 完成后输出

给用户一份简报：套件结果（改了哪些测试断言、为什么）、发现并修复的真回归（如有）、本机加测结果（真实 PDF/arXiv 线）、提交清单、遗留项。

## 5. Wave 2 待办（本次不做，除非用户明确说开工）

测试断言同步之外：G13 概念页（一等公民概念层）、G1 bib 引用导出、G4 实验导入（wandb/log）、周报编辑层+PPT 差异化、快筛移除（入库即深读，蓝图 §11 决定 3）、`link_autodrive=auto_deep_read` 的 ingest 消费、analyst 四合一/navigator+wiki 摘除/tests 搬迁（大手术）、common.py 根路径输出治理、index.py 共享 lint 反链语义与 audit 对齐。优先级与细节见蓝图 v2 §12 与 wave1 报告"建议的下一步"。
