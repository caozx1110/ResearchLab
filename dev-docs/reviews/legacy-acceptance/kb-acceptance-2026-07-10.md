# KB 系统验收报告 #2（fix-batch 复测，全新端到端使用）

日期：2026-07-10
测试者：research assistant agent（本轮把自己当作 AGENTS.md「Ingestion auto-drive」里的 runtime agent，从零驱动全链）
KB 根：`tmp/accept-test-2/kb-workspace`（全新空库，`kb --root <path>` 指向此处）
运行时：`tmp/rvenv/bin/python` + `PYTHONPATH=.agents/lib`（Python 3.9.6, yaml OK, pdf=pypdf）
对照基线：上一轮 聪明 9 / 易用 7 / 自动化 5，F1–F10 遗留问题。**本轮盲测、不预设已修。**
红线核查：`git -C <repo> status --short kb/ .agents/` 全程为空 —— 真实 `kb/` 与 `.agents/` 一字未改，所有写入都在 `tmp/accept-test-2/` 下（见文末）。

---

## 本轮实际跑通了什么

三条 source 全部驱动到 grounded + verified，并正确停在治理确认门（confirm gate，未自签）：

| 单元 | id | 链路（真实执行） | 终态 |
|---|---|---|---|
| 论文 arXiv 2412.04368 | `p-finer-behavioral-66846131` | `kb ingest paper.pdf` → 填 5 要素 note-fill → `complete-note verify`（写 note.md）→ `extract-figures` → `refresh-structure` → 填 screening 判断 → `screen verify`（worth_deep_reading=yes） | screened / pending_user_confirmation |
| repo LangWBC | `r-langwbc-repo-78d111a4` | `kb ingest <dir>`（**自动识别为 repo**）→ 填 capability/reuse_points/entry_map → `map-capability verify`（写 repo-note.md） | screened / pending_user_confirmation |
| 博客 Lilian Weng, LLM Powered Autonomous Agents | `b-2023-06-23-e9bdaad7` | `kb ingest <url> --kind blog`（真实 web fetch，17 chunks）→ 填 positioning/key_points/credibility/reusable_explanation → `complete-note verify`（写 blog-note.md） | active / pending_user_confirmation |

三条笔记的每个要素都带 ≥1 条**逐字**原文引用 + locator（论文 `page=N`、repo `file line=N`、博客 `section:<anchor>`），全部一次性通过 verify（screening 因 claim schema 报错重试一次，见易用 F-b）。`kb review` 末态干净列出 3 条 judgement-track 待确认，各带正确 confirm 命令。

---

## 聪明（Real understanding? 证据门有效吗？）—— 9/10（持平，仍是最硬的一环）

**证据逐字门真能拦编造。** 我在 motivation 证据里故意塞一句改写引文，verify 立刻拒绝并逐条点名：
```
[reject] note fill failed verification:
  - element 'motivation': claim claim-motivation evidence_refs[0]: quote
    'This paper single-handedly solves all of reinforcement lear…' not verbatim in artifact 'parse-cache.yaml'
```
机制干净：`normalize_ws` 折叠空白后做子串校验，按 `page=N` 收窄。**且这次退出码是 1（上轮 F4 是 0）—— 见自动化，脚本化可判成败了。**

**笔记是真理解不是模板。** 脚本「从不代写内容」，5 要素是我读完 ~17 页后自己的归纳。例如论文 limitation 抓到了作者自陈的反直觉结论「auto-regressive 理论表达力大增、实测收益 modest → 表达力可能不是关键瓶颈」，用 page=16 两句原文佐证；insight 进一步把它和「reward-free BFM 打平单任务 agent」的正结果对照。repo 笔记诚实写「Policy Training 代码 *(coming soon)* 尚未释出，现在不适合直接跑」，没硬凑复用点。博客 credibility 要素既肯定作者权威+引用规范，也点出「这是综述/inference 而非一手实验、2023-06 时效需注意」。

**判断轨/事实轨分离到位**：worth-reading 判断强制 `pending_user_confirmation`，且判断必须挂带证据的 claim（`validate_claims` 对 `inference`/`evaluation` 类 claim 强制非空 evidence_refs）。

**扣分点（且是本轮新发现的脆弱性）**：见自动化里的 **F-a：`refresh-structure` 会把 parse-cache 从 38 页截成 8 页**。系统「懂得逐字校验」，却又在链条后半段亲手把自己赖以校验的证据 artifact 削掉 —— 这是「smart 但 self-inconsistent」，所以聪明维持 9 而非升到 10。

---

## 易用（下一步清楚吗？NEXT 行能跑吗？）—— 8/10（+1，上轮 7）

**大幅好转的地方（对照上轮 friction 逐条核）**

- **F5 已修（两套 confirm 命令 → 统一）**：`kb next` / `kb review` / `kb find` 现在给的是**同一条** per-kind 命令：
  ```
  command: ...paper-analyst/scripts/paper.py confirm --paper-id p-finer-behavioral-66846131 \
           --confirmed-by ${RESEARCH_CONFIRMED_BY:?...} --evidence ${RESEARCH_CONFIRM_EVIDENCE:?...}
  ```
  上轮 `kb next` 走的是另一条 `knowledge-base-manager/.../kb.py confirm --id ...`，现已消失。
- **F1 已修（repo 不再被误判为 blog）**：`kb ingest <本地目录>` 无需 `--kind` 就得到 `source_type=directory` → `kb/units/repos/...`，骨架是 `[capability,reuse_points,entry_map]`。上轮必须显式 `--kind repo` 才对，还留孤儿 blog 单元。且 `kb reject` 现已是一个正式动词（回收路径存在）。
- **F3 部分修（--root 顺序）**：`kb ingest --help` 现在**专门用一段**说明 `--root` 是顶层 flag、必须放动词前，并给出反例。文档层面修好了。
- **F2 已修（screening 第二轮填写不再是暗坑）**：`kb ingest` 输出把**整条剩余链**当 runbook 打印出来（下详），screening 是明确的 step C，不会漏。

**仍扎脚 / 新扎脚**

- **F7 仍在（`kb find` 的 next 提示过期）**：论文已 screened，`kb find "forward-backward"` 仍提示
  `next: ...paper.py screen`；博客已成文仍提示 `next: ...blog.py complete-note`；repo 已 map 仍提示
  `next: ...repo.py scan-structure`。真正下一步是 confirm（同一行下方的 `confirm:` 才对）。误导首次用户。
- **F8 仍在（note.md 标题被截断）**：`# Finer Behavioral Foundation Models via`（在 "via" 处断）。
- **F-b 新（screening 的 claim schema 未在 fill_contract 里说明）**：screening.yaml 的 `fill_contract` 只写
  `claims: agent attaches judgement claims backing worth_deep_reading` + 一个 `evidence_ref_format`，**没说 claim 对象本身需要 `id/text/claim_type/confirmation_status/evidence_refs`**。我照 note-fill 的直觉用了 `claim:`/`claim_type` 就被拒：
  ```
  [reject] screening fill failed verification:
    - claims[0]: missing required field 'id'
    - claims[0]: missing required field 'text'
    - claims[0]: missing required field 'confirmation_status'
  ```
  对比 note-fill 给了完整 per-element 结构，screening 的 claim 结构要靠去 `research/evidence.py` 翻 `REQUIRED_CLAIM_FIELDS` 才知道。一次可恢复的往返，但首次用户必踩。
- **F3 残留（运行期报错仍是裸 argparse）**：`kb status --root <path>`（--root 放动词后）报
  `kb: error: unrecognized arguments: --root`，没有「你是不是想 `kb --root <path> status`」的定向提示。help 修了，报错没修。

**依旧优秀**：`kb doctor` 一眼给出 python/yaml/pdf 后端；每个 fill 文件自带 `fill_contract` + `evidence_ref_format` + `evidence_digest`（预抽好的每页/每段原文），就地取证不用回翻源文件。

---

## 自动化（几步手动？链条是被告知还是自己发现？在哪该停？）—— 6.5/10（+1.5，上轮 5）

**最大进步：`kb ingest` 把「整条剩余链」当 runbook 一次打印，我全程没有『自己发现』过任何一步。** 论文那次 ingest 的尾部直接列出 A/B/C/D：
```
[ingest] full chain remaining for p-finer-behavioral-66846131:
  chain: fill note -> verify note -> [safe auto] extract-figures + refresh-structure
         -> fill screening -> verify screening -> [gate] confirm judgement
  step A (fill + verify note): ...complete-note --phase verify (never auto-run: a script cannot fill understanding).
  step B (safe auto ...): ...extract-figures ...  ...refresh-structure ...
  step C (screening SECOND-fill ...): fill screening.yaml ... then screen --phase verify
  step D (confirm gate — AI judgement, never self-signed): present ... user confirms with: ...
```
这正是上轮 F2 要的东西 —— screening 第二轮填写被明确串进来了，每条都给可复制的完整命令（含 `--root`/`--input`/要填的 element 列表/locator 格式）。**「省 attention」这块从 5 分档跳到了 8 分档。**

**但「省 steps」没同步跟上 —— 手敲脚本数和上轮一样。** 从 `kb ingest` 到 grounded+verified（不含 confirm 门）的真实计数：

| 步骤 | 谁做 | 本可自动？ |
|---|---|---|
| `kb ingest`（intake+screen-prepare+note-prepare 三合一） | 1 条命令 ✓ | — |
| 填 note-fill.yaml | agent 手填 | 否，正确（需理解） |
| `complete-note --phase verify` | **手敲** | fill 后可引导，可接受 |
| `extract-figures` | **手敲** | 系统自称 "safe auto"，却仍手敲 |
| `refresh-structure` | **手敲** | 同上（且见 F-a，反而危险） |
| 填 screening.yaml | agent 手填 | 判断需人确认，填由 agent |
| `screen --phase verify` | **手敲**（+1 次重试） | — |

**净：1 条 ingest + 4 次手敲脚本 + 2 次填写 —— 步数与上轮持平。** step B 明说 extract-figures/refresh-structure 是「safe auto，在你的 auto_execute_scope 内」，却还是让 agent 逐条敲，没有一条命令把 verify→figures→refresh 串起来。这就是「机械胶水仍手动」。

**修好的自动化管线**
- **F4 已修**：verify 拒绝现在返回**退出码 1**（实测 `REJECTED-verify exit code = 1`），上轮是 0。脚本化终于能判成败。
- **F6 已修**：blog `complete-note verify` 现在也 `[ok] git checkpoint: 5cd83be`，与 paper/repo 一致（上轮 blog 不 checkpoint、留脏树）。
- **F9 已修**：blog parse-cache 头字段现在是 `blog_id`（上轮误用 `paper_id`）。

**正确地停在了人类决策门**：三条链都停在 confirm gate，`record.confirmation_status=pending_user_confirmation`，`kb review` 主动提示「⚑ 建议主动请用户拍板」。没有自签 —— 这是对的治理边界。

### F-a（本轮最重要的新缺陷）— `refresh-structure` 重写并**截断** parse-cache，破坏 re-verify 幂等 + 限制 screening 取证范围

`kb ingest` 时 intake 生成的 parse-cache 是 **38 页 / per_page_char_limit=8000 / 3301 行**。链条 step B 的 `refresh-structure`（checkpoint b6e19a7）**原地重写** parse-cache，换成 `front_limit=8, back_limit=0, per_page_char_limit=3000` 的小策略，只剩前 8 页 / 1427 行，**page 9–38 被删**。证据（git 内对比同一文件）：
```
$ git show --stat b6e19a7   # milestone: refresh paper structure
 .../parse-cache.yaml | 3374 +++++--------------- (833 insertions, 2632 deletions)
$ git show 1bbbc0b:.../parse-cache.yaml | grep -c 'label: paper.pdf:page'   # intake
38
$ git show b6e19a7:.../parse-cache.yaml | grep -c 'label: paper.pdf:page'   # after refresh
16     # 实际末尾 label 到 page-8
```
后果：
1. **note re-verify 幂等被破坏**：note.md 是在 refresh 前（cache 还是 38 页）填+verify 的，成品没问题；但 refresh 后我重跑同一份 note-fill 的 verify，experiment(page12)/limitation(page16)/insight(page16,17) 全部报 `not verbatim in artifact` —— 因为那些页已从 cache 里消失。若 verify 当初拒了某个后页 quote、要我修完再跑，refresh 之后就**永远修不过**了。
2. **screening（step C，在 refresh 之后）取证被压到前 8 页**：我这次 screening 恰好引 page-1，侥幸过；若判断需要 page-15 的证据，post-refresh 就无从逐字落地。screening 的 evidence_digest 本身也只喂前几段，等于把「判断取证」限制在开头。
3. 与设计自相矛盾：AGENTS.md 把 refresh 列为「safe auto step」，但它其实**有损**地改写了下游/上游都依赖的 grounding artifact。若真按建议自动执行，这个损耗会更隐蔽。

**建议**：refresh-structure 不要覆盖 intake 的全量 parse-cache（另存 `structure-cache.yaml`，或 verify 阶段固定读 intake 版），保证 parse-cache 是「immutable 派生证据」。

---

## Δ vs 上轮（9 / 7 / 5）

- **聪明 9 → 9（持平）**。证据门依旧真拦编造，且退出码修好后更可脚本化；笔记有真实理解。**未升 10** 是因为 F-a：系统逐字校验很严，却又亲手截断校验所依赖的 parse-cache，自洽性有裂缝。
- **易用 7 → 8（+1）**。F5（confirm 统一）、F1（repo 不再误分类 + 有 reject 出口）、F2（screening 串进 runbook）、F3 文档修好，都是首次用户会直接受益的。扣分留给 F7（find 过期提示）、F8（标题截断）、F-b（screening claim schema 没写进 contract）、F3 报错未定向。
- **自动化 5 → 6.5（+1.5）**。质变在**引导**：ingest 把整条链（含 figures/refresh/screening/confirm）一次讲清，我 0 次「自己发现步骤」；加上 F4 退出码、F6 blog checkpoint、F9 header 三处管线修复。**未到 7+** 是因为**执行**没省步：figures/refresh/screen 仍是 4 次手敲机械胶水，且 F-a 让「自动跑 refresh」反而有风险。

---

## Remaining friction（按恼人程度排序，附真实命令/输出）

1. **F-a（最该修）— `refresh-structure` 有损截断 parse-cache（38→8 页），破坏 note re-verify 幂等 + 压缩 screening 取证**。命令/证据见上。这是本轮唯一的**正确性级**问题（成品没坏，但链条脆）。
2. **F-b — screening 的 claim schema 未文档化**。fill_contract 没列 `id/text/claim_type/confirmation_status/evidence_refs`，首次填必被拒一次。修法：把 note-fill 那样的完整 claim 结构样例写进 screening 的 fill_contract。
3. **F7（仍在）— `kb find` 的 `next:` 提示过期**：对 screened/mapped/summarized 完的单元仍提示回去 `screen/scan-structure/complete-note`。应指向 confirm（或直接复用同行的 `confirm:`）。
4. **执行胶水仍手动**：`extract-figures` + `refresh-structure` 被标 "safe auto" 却要逐条手敲；缺一条「verify 通过后自动接 figures+refresh」的串联（若修 F-a 后再自动化）。
5. **F3 残留 — `--root` 放动词后仍是裸 argparse 报错**（`unrecognized arguments: --root`），无定向提示。
6. **F8（轻微，仍在）— note.md 标题在 "via" 处截断**。

---

## 结论：对研究者「够易用 + 够聪明 + 够自动化」了吗？

**够聪明 + 基本够易用；自动化过了及格线但还没到「省 steps」。**

- **聪明**：稳，且是护城河。逐字证据门 + 脚本不代写 + 判断轨强制确认，这套组合本轮再次证明能拦编造、能逼出真理解。唯一要补的是别让 refresh 破坏自己的证据基座（F-a）。
- **易用**：这批 fix 命中了上轮几乎所有「首次必踩」的坑（confirm 统一、repo 不误判、screening 串进引导、--root 文档化），体感明显顺。剩下的是 F7/F8/F-b 这类打磨项。
- **自动化**：`kb ingest` 现在会把**整条剩余链**告诉你，这是相对上轮最实的进步 —— 我从头到尾没有一次需要猜下一步。但它省的是 attention 不是 steps：figures/refresh/screen 仍是 4 次手敲。要真正到 8 分，得在修掉 F-a 之后，把「verify→figures→refresh」这段无判断胶水自动串起来。

### 最该先修的 3 件事
1. **修 F-a**：refresh-structure 不再覆盖 intake 全量 parse-cache（另存结构缓存 / verify 固定读 intake 版），恢复「parse-cache 是不可变证据」的契约。
2. **把 note-fill→verify→extract-figures→refresh-structure 这段无判断胶水真正自动串起来**（F-a 修好后），让 `kb ingest` 后半段名副其实地 "safe auto"，省下 3~4 次手敲。
3. **补 screening 的 claim schema 文档（F-b）+ 修 `kb find` 过期 next 提示（F7）**：两处都是「照着提示做却被拒/被误导」的一次性往返，成本低收益高。

（红线复核：`git -C <repo> status --short kb/ .agents/` 为空 —— 真实 `kb/` 与 `.agents/` 全程未改；所有产物在 `tmp/accept-test-2/kb-workspace/` 下，已原样保留供检查。）
