# v2-campaign 最终验收报告

> 施工规格：`dev-docs/PROMPT-full-campaign-2026-07-26.md`
> 代码验收基线：`1f211ad`（`v2-campaign`）
> 日期：2026-07-27
> 发布状态：未发布 RC；未 push、未 tag、未合并主分支

## 结论

本 campaign 已完成规格 §2 的全部功能与质量验收。最终代码基线的完整本地套件为 **2313 passed, 18 skipped**；15 个 discoverable skill 全部通过 validator；Python 3.9 compile 通过；归档副本 cold install / no-change update / uninstall 生命周期通过。真实来源、GOLDEN、A13、恢复、Obsidian 往返与公开输出均在隔离 `/private/tmp` 工作区复验，仓库根真实 `kb/` 未被写入。

本结论只表示当前 RC 的本地 campaign DoD 已满足，不表示 stable/GA，也不外推为平台兼容或响应时限 SLA。Hosted Linux/macOS CI 仍应在打 tag 前运行；本 campaign 没有 push、tag、publish 或 merge。

## DoD 证据

| 项 | 结果 | 主要验收证据 |
|---|---|---|
| A1 | PASS | 冷批量链覆盖真实 arXiv HTML/PDF、真实 repo、网页 blog、本地文件；5 项整批不逐项询问。最终真实 `2607.21670` PDF（45 页、7,772,945 bytes）可从 degraded 摘要壳建立新 revision，旧 raw/derived bytes 不变、旧 unit archived、双向 lineage，随后直达统一深读骨架。 |
| A2 | PASS | `auto_screen` 退役；paper intake 直接生成 `paper_type + 类型分支五要素` 的统一 deep-read scaffold，无“是否值得细读”闸口。 |
| A3 | PASS | 3 个 current confirmed 上游单元生成 canonical concept；定义与关联逐字证据、统一确认、find/Obsidian 可达。 |
| A4 | PASS | 冷验收中文、英文、代码符号检索均返回 locator；代码含 `file:line`，实测约 0.67–0.87 秒。 |
| A5 | PASS | 6 个 current confirmed 单元生成并确认 survey；taxonomy/trends/gaps/claims 全绑定上游与逐字 evidence，confirmed survey 可进入报告。canonical fill、survey、summary 同 checkpoint。 |
| A6 | PASS | idea capture→evidence analysis→corpus link/refresh→discussion→selection→method handoff 全链通过；新增材料与 fill basename 仅靠文档零 help 摸索。 |
| A7 | PASS | 10-run import、幂等重放、diagnose/confirm、audit `error=0 warning=0`；fill/judgement/event/index/output exact checkpoint。 |
| A8 | PASS | 一句话周报生成四区叙事+读者化证据附录；PPT 每页一结论+证据+图引用；与七节 outline 结构明显不同。paper-type wire 与 owner event title 均只在渲染时本地化。 |
| A9 | PASS | 5 篇 current paper 的七节 outline→分节 fill/verify/confirm→原子发布 Markdown、LaTeX、稳定去重 BibTeX 与 publication manifest。 |
| A10 | PASS | 真实 PDF figure index 含 caption/编号、稳定 paper-bound ref key、内容哈希 PNG；find、Obsidian、报告和 draft 可引用，篡改 fail closed。 |
| A11 | PASS | 纠正先形成 observation，任务尾询问；真人 snapshot-bound 确认后进入下次任务。init 两问落盘；`link_autodrive=auto_deep_read` 被实际消费。 |
| A12 | PASS | undo 点名当前 repo-choice 方法选择对象；restore 无参列清单，选历史编号原子回退 X 及其后操作；resume 恢复崩溃前字节并终结 source op。 |
| A13 | PASS | 三场景交互章程 10/10：入库并讨论跟进、idea 陪练、10 分钟周报；无条款系统性缺失。 |
| Q1 | PASS | `/private/tmp/workspace-oss-r3-full-py313/bin/python -m pytest -q`：`2313 passed, 18 skipped, 7 warnings`，632.73 秒；warnings 为既有 SWIG deprecation。 |
| Q2 | PASS | `Validated 15 skills.`；Python 3.9 compile 通过；snapshot cold install 2.15 秒、no-change update 0.51 秒、uninstall 保留 `kb/`。 |
| Q3 | PASS | 冷 GOLDEN G1–G8 全通过；G5–G8 为 0 次 help、0 次源码翻查。一次 archive 与 Git-bound Agent plan 的测试夹具组合被正确零写拒绝，改走正式 snapshot 模式；不属于安装用户主路径。 |
| Q4 | PASS | 固定 `cl100k_base`：公共规则 global 4059 tokens；最坏单任务 `AGENTS + GUIDE + kb-cli` 为 7784/8000；`kb next` 公开候选最多 3 步。 |
| Q5 | PASS | 非零公开路径均有有界可行动中文；历史 restore 漂移、source revision 保护、stale review 均 fail closed。owner warnings 留在 private protocol，不再混入成功 stderr。 |
| Q6 | PASS | 冷验收公开 `kb` stdout/stderr 无 traceback、绝对路径、owner flags、schema、receipt 或 `[root]`；Obsidian sheet 只含自然语言、checkbox 与不透明 marker。 |
| Q7 | PASS | SSOT/SCHEMAS/DESIGN/USER_GUIDE/README/CHANGELOG 与实现同步；版本标识统一为 `0.2.0-rc.7`，动态验收状态只在 CHANGELOG 维护。 |

## 前后指标

| 指标 | campaign 前/首轮 | 最终 |
|---|---:|---:|
| 完整 pytest | 2105 passed / 18 skipped / 5 failed | 2313 passed / 18 skipped / 0 failed |
| discoverable skills | 20 | 15（14 owner + kb-cli） |
| 最坏单任务规则预算 | 8020 tokens（超门） | 7784 / 8000 |
| 公共固定规则文本 | 未单独约束 | 4059 tokens |
| 单次 add 数量 | 1 | 1–20，整批原子 |
| `kb next` 公开候选 | 多来源、未统一封顶 | ≤3 步 |
| 普通检索延迟 | 无 DoD 实测 | 0.67–0.87 秒（冷验收） |
| 冷安装耗时 | 约 2 秒量级 | 2.15 秒（≤60 秒） |
| no-change update | 未单列 | 0.51 秒 |
| A13 章程覆盖 | 未逐条执行 | 10/10 |

全量套件在各里程碑约为 8–10.5 分钟；最终两轮分别为 633.42 秒与 632.73 秒。Campaign 从 2026-07-26 开始，在 2026-07-27 完成 R0–R6 本地闭环。

## 冷验收发现与关闭

冷 agent 报告的问题均先由主线程独立复现，再修改实现：

1. paper-type wire、英文 owner event title 与报告内部术语泄漏：改为 exact canonical claim/event-type 的读者化投影，不改 canonical bytes。
2. idea corpus refresh、fill 名称、实验/周报私有最小调用不可发现：补齐 owner SKILL 合同；最终 G5/G6 零 help 摸索。
3. Obsidian raw frontmatter、良性 inline code、export/apply dirty：sheet 去 schema/kind，安全 code symbol 投影为惰性文本，export 与 processed apply 均 exact checkpoint。
4. 历史 restore 对 shared targets 误 CAS：定义并实现 X 到最新的原子区间恢复，先证明完整 digest 链再写。
5. degraded arXiv 摘要后本地 PDF 被 duplicate 吞掉：另建 source revision、双向 lineage、旧 evidence immutable；已有 judgement 或弱身份继续请求用户决策。
6. 完整真实 PDF 因少量 converter warning 被误拒：保留诚实 degraded/warnings，但用 raw bytes、连续 page locator 与 ≥2 页/≥4000 字符实质 parse 判断 revision 资格。
7. 公共确认成功泄漏 owner `[warn]`：stderr 捕获并有界保存在 private Agent protocol；公共面只显示自然语言结果。

## 红线审计

- 六个真实 `kb/` 保护文件在施工前后 SHA-256 完全一致；所有行为测试只在 `/private/tmp`。
- AI 不可自签、当前消息授权、逐字 evidence、ConfirmationReceipt content/evidence digest、CAS/锁/journal/原子写均未放松。
- source upgrade 从不覆盖旧 raw/derived bytes；verified/confirmed 旧 judgement 不自动迁移。
- checkpoint 始终 exact scope，无 `git add -A` 兜底；historical restore 为单 recovery journal + 单 checkpoint。
- 未 push、未 tag、未 publish、未 merge 主分支。

## 遗留与发布边界

Campaign DoD 无未完成项。唯一剩余的是 **release tag 外部门**：在实际 GitHub 环境观察 hosted Linux/macOS CI matrix 全绿。由于本任务明确禁止 push，本地无法产生这项 hosted 证据；它不阻塞 `v2-campaign` 的本地施工完成，但继续阻止 tag/GA 宣称。

## 合并建议

建议维护者先查看 `v2-campaign` 相对目标主分支的提交序列和本报告，再选择保留里程碑提交的普通 merge；这些提交按 R0–R6 划分，保留可审计的设计 gate、功能 piece、冷修复和文档收口。合并后在主分支再运行一次完整 pytest 与 15-skill validator，随后 push 触发 hosted Linux/macOS CI；只有 matrix 全绿且 CHANGELOG 状态仍准确时，才考虑 tag。若需撤销，可在合并前记录主分支 HEAD，避免压缩掉每轮独立撤销点。
