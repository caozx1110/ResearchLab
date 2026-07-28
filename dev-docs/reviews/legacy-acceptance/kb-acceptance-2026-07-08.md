# KB 系统验收报告（首次端到端使用）

日期：2026-07-08
测试者：research assistant agent（首次使用本系统）
KB 根：`tmp/accept-test/kb-workspace`（全新空库，`--root` 指向此处）
运行时：`tmp/rvenv/bin/python` + `PYTHONPATH=.agents/lib`
红线核查：仓库根 `git status` 干净、真实 `kb/` 无任何新写入 —— 未触碰用户实时数据（见文末）。

## 我实际跑通了什么

三条 source 全部驱动到 grounded + verified，并正确停在治理确认门：

1. **论文** `p-finer-behavioral-66846131`（arXiv 2412.04368）
   intake → screen-prepare → note-prepare（`kb ingest` 一条命令链完成）→ 我填 5 要素 note-fill → complete-note verify（写出 note.md）→ extract-figures（7+ 张图）→ refresh-structure → 我填 screening 判断 → screen verify（`worth_deep_reading=yes`，pending_user_confirmation）。
2. **repo** `r-langwbc-repo-78d111a4`（LangWBC）
   `kb ingest ... --kind repo` → 我填 capability/reuse_points/entry_map → map-capability verify（写出 repo-note.md）。
3. **博客** `b-2018-06-24-01ef992b`（Lilian Weng, Attention? Attention!）
   `kb ingest <url> --kind blog`（真实 web fetch 成功，23 chunks）→ 我填 positioning/key_points/credibility/reusable_explanation → complete-note verify（写出 blog-note.md）。

外加一个**误分类遗留单元** `b-langwbc-repo-78d111a4`（repo 被当成 blog，见 F1），孤儿态。

---

## 易用（Could I tell what to do next?）—— 7/10

**好的地方**
- `kb help` 中文动词菜单一目了然，`kb doctor` 直接给出 python/yaml/pdf 后端可用性。
- 每一步的 `NEXT FOR AGENT:` 行是**可直接复制运行的完整命令**（含 `--root`、`--input`、要填的 element 列表、locator 格式），这是全流程最亮的设计。例：
  ```
  NEXT FOR AGENT: read kb/units/papers/.../parse-cache.yaml (source quotes) then fill ...
  note-fill.yaml elements [motivation,method,experiment,limitation,insight] — each needs
  content + >=1 verbatim quote+locator (PDF page=N / HTML section:<anchor>), then run:
  ${RESEARCH_PYTHON:-python3} .../paper.py --root ... complete-note --paper-id ... --phase verify --input note-fill.yaml
  ```
- fill 文件里的 `fill_contract` + `evidence_ref_format` + `evidence_digest`（预抽好的每页原文）让我不用回头翻 PDF 就能就地取证。

**扎脚的地方**
- **`--root` 的参数顺序陷阱（F3）**：`--root` 是顶层全局参数，对非 `init` 动词必须写在动词**之前**（`kb --root <path> ingest ...`）。但 `kb ingest --help` 根本不列 `--root`，`kb init --help` 却列了 —— 首次用户几乎必然会写成 `kb ingest --root ...` 而踩坑。
- **verify 拒绝却返回退出码 0（F4）**：我故意放了一句改写引文，verify 正确判为 not-verbatim，但 `EXIT=0`。脚本级自动化无法靠退出码判断成败。
- **两套确认命令面（F5）**：`kb review`/`kb find` 给的确认命令是 per-kind 脚本（`paper.py confirm --paper-id X --confirmed-by ... --evidence ...`），`kb next` 给的却是另一条路径（`knowledge-base-manager/scripts/kb.py confirm --id X --evidence ...`）。同一件事两种命令，首次用户会懵。
- **`kb find` 的 next 提示是过期的（F7）**：论文已 screened，`kb find` 仍提示 `next: paper.py screen`；博客已成文，仍提示 `next: blog.py summarize`。

---

## 聪明（Real understanding vs templated? Did the gate catch anything?）—— 9/10

**证据门是真的有效，这是系统最硬的一点。** 我在 experiment 要素里故意填了一句改写引文
`"FB-AW significantly outperforms vanilla FB, roughly doubling the score"`（原文是
`"FB-AW significantly outperforms FB, more than doubling the score for the"`）。verify 直接拒绝：
```
[reject] note fill failed verification:
  - element 'experiment': claim claim-experiment evidence_refs[0]: quote
    'FB-AW significantly outperforms vanilla FB, roughly doublin…' not verbatim in artifact 'parse-cache.yaml'
```
改回逐字原文后即通过。机制干净：`normalize_ws` 折叠空白后做子串校验，还能按 `page=N` 做定位收窄。这意味着笔记里每一条判断都被钉在原文上，无法蒙混。

**产出的笔记是有真实理解的，不是模板套话。** 因为脚本本身「从不代写内容」（`the script never authors content`），5 个要素都是我读完 25 页后自己的归纳，且每条都带原文锚点。例如论文 limitation 我抓到了作者自陈的反直觉结论「auto-regressive 理论表达力大增但实测收益温和 → 表达力不是关键瓶颈」，并用 page=16 的两句原文佐证。repo 笔记诚实地写出「代码 *(coming soon)* 尚未释出、当前不适合直接跑」，没有硬凑复用点。

**判断轨与事实轨分离得当**：worth-reading 判断被强制 `pending_user_confirmation`，且要求判断必须挂 ≥1 条带证据的 claim（我填 `yes` 时必须给 claim，否则拒绝）。

扣 1 分：paper 的判断 fill（screening.yaml）是一次**独立于笔记的第二轮填写**，容易被忽略（见 F2/自动化）。

---

## 自动化（How many manual steps? Where did it stop correctly vs make me do glue?）—— 5/10

**`kb ingest` 确实链了一段**：一条命令完成 intake → screen-prepare → note-prepare，并明确「stopped before verify (agent must fill elements first)」。停在需要我填内容处是**对的**。

**但 AGENTS.md 承诺的「一个 turn 驱动整条链」并没有兑现。** AGENTS.md「Ingestion auto-drive」把 extract-figures + refresh-structure 列为链条第 5 步（安全自动步），但 `kb ingest` 之后我仍要**手工敲 4 次脚本 + 2 次填写**：

| 步骤 | 谁做 | 是否应自动 |
|---|---|---|
| `kb ingest`（intake+screen-prepare+note-prepare） | 一条命令 ✓ | — |
| 填 note-fill.yaml | agent（应当手填） | 否，正确 |
| `complete-note --phase verify` | **我手敲** | 本可在 fill 后引导，可接受 |
| `extract-figures` | **我手敲** | **应自动**（AGENTS.md 第5步，纯机械无判断） |
| `refresh-structure` | **我手敲** | **应自动**（同上） |
| 填 screening.yaml（worth-reading 判断） | **我手敲 + 手填** | 判断需人确认，但「该我填判断」这件事没有在 `kb ingest` 输出里被提示 |
| `screen --phase verify` | **我手敲** | — |

extract-figures / refresh-structure 是**零人类判断的机械胶水**，却要我逐条手敲，这正是 AGENTS.md 说「automation 应替用户省下的 steps 和 attention」的部分，却没省。

**其它自动化缺口**
- **blog verify 不做 checkpoint（F6）**：`blog.py` 只 import 了 `build_index`、没 import `checkpoint_and_report`；paper.py/repo.py 两者都有。结果博客 verify 后 `blog-note.md`/`blog-fill.yaml`/`blog-claims.yaml` + 脏 index/config 全部未提交，而论文/repo 每步都自动 `git checkpoint`。同一动作三种 kind 行为不一致。
- **误分类没有回收路径（F1）**：目录被判成 blog 后，`blog.py` 只有 `complete-note`/`confirm` 两个子命令，**没有 reject/remove**，孤儿单元 `b-langwbc-repo-78d111a4` 只能手工删目录。

---

## 具体 friction 清单（按恼人程度排序，附真实命令/输出）

**F1（最恼人）— `kb ingest` 把本地 repo 目录误判为 blog，且无回收路径**
```
$ kb --root $ROOT ingest .../langwbc-repo
[ok] created kb/units/blogs/b-langwbc-repo-78d111a4/record.yaml       # ← 应是 repos/
... elements [positioning,key_points,credibility,reusable_explanation]  # ← blog 骨架
```
必须显式 `--kind repo` 才对：
```
$ kb --root $ROOT ingest .../langwbc-repo --kind repo
[ok] created kb/units/repos/r-langwbc-repo-78d111a4/record.yaml
... elements [capability,reuse_points,entry_map]                        # ← 正确
```
本地目录（含 `.git/`、`README.md`）应能强推为 repo；即便判错，也该给 `reject`/`supersede`。现在留下一个 awaiting_agent_fill 的孤儿 blog 单元。

**F2 — 论文判断（screening）需要第二轮独立填写，但 `kb ingest` 没提示「现在轮到你填判断」**
`kb ingest` 只把我导向 note-fill；screening.yaml 的 `worth_deep_reading` 是 intake 时静默 scaffold 的（`[auto] ... 下一步：runtime agent 填 worth_deep_reading`），埋在一长串输出里，很容易漏掉。两个 fill（note + screening）本应在一次引导里串起来。

**F3 — `--root` 参数顺序陷阱 + help 不一致**
`kb ingest --help` 不显示 `--root`；实际必须 `kb --root <path> ingest ...`（全局参数在动词前）。`kb init` 却又能吃动词后的 `--root`。首次用户极易写错。

**F4 — verify 拒绝时退出码为 0**
```
[reject] note fill failed verification:
  - element 'experiment': ... not verbatim ...
EXIT=0        # ← 拒绝也返回 0，脚本化无法判断
```

**F5 — 两套不一致的 confirm 命令**
`kb review`/`kb find`：`paper.py confirm --paper-id X --confirmed-by ${...} --evidence ${...}`
`kb next`：`knowledge-base-manager/scripts/kb.py confirm --id X --evidence ${...}`（无 `--confirmed-by`，脚本路径也不同）

**F6 — blog `complete-note` verify 不 checkpoint（与 paper/repo 不一致）**
```
$ git -C kb-workspace/kb status --short
 M index.yaml
 M units/blogs/b-2018-06-24-01ef992b/record.yaml
?? units/blogs/b-2018-06-24-01ef992b/blog-note.md      # ← 未提交
?? units/blogs/b-2018-06-24-01ef992b/blog-fill.yaml
```
根因：`blog.py` 未 import/调用 `checkpoint_and_report`（paper.py 有）。

**F7 — `kb find` 的 next 提示过期**
论文已 screened 仍提示 `next: paper.py screen`；博客已成文仍提示 `next: blog.py summarize`。

**F8（轻微）— note.md 标题被截断**
```
# Finer Behavioral Foundation Models via     # ← 从 "via Auto-Regressive..." 处断掉
```

**F9（轻微，cosmetic）— blog 的 parse-cache 头字段仍叫 `paper_id`**
```
paper_id: b-2018-06-24-01ef992b     # blog 单元却用 paper_id 键
```

**F10（我方环境，非系统问题）— macOS 无 `timeout`**，与 KB 无关，仅记录。

---

## 结论：对研究者「够易用 + 够聪明 + 够自动化」了吗？

**聪明：够，且是亮点。** 证据逐字门真能拦住编造/改写，笔记被钉死在原文上，判断轨强制人工确认。这套「脚本不代写、只校验 + 逐字核验」的设计值得保留。

**易用：基本够，但有几处首次用户必踩的坑**（`--root` 顺序、误分类、两套 confirm 命令）。`NEXT FOR AGENT` 行是好设计，把它贯彻到每一处（尤其是 screening 该我填、确认命令统一）就好。

**自动化：还不够。** `kb ingest` 只链了前半段，AGENTS.md 明确列为自动步的 extract-figures/refresh-structure 仍要手敲，加上 screening 第二轮填写没被串进来，实际「ingest → grounded note」是 **1 条 ingest + 4 次手敲脚本 + 2 次填写**。对「省 steps 和 attention」的承诺打了折。

### 最该先修的 3 件事
1. **把 `kb ingest` 的链条补齐到 AGENTS.md 承诺的范围**：verify 通过后自动接 extract-figures + refresh-structure（纯机械步），并在一次引导里把「填笔记」和「填 worth-reading 判断」串起来提示。（针对 F2、自动化缺口）
2. **修 repo 误分类 + 给回收路径**：本地目录默认识别为 repo；无论如何都提供 `reject`/`supersede` 收拾误建单元。（F1）
3. **统一并修正接口一致性**：verify 拒绝返回非零退出码（F4）；`kb review`/`find`/`next` 用同一条 confirm 命令（F5）；blog verify 与 paper/repo 一样自动 checkpoint（F6）。

（红线复核：仓库根 `git status` 干净、`find kb -newermt <测试开始>` 为空 —— 真实 `kb/` 与 `.agents/` 全程未被修改。测试库 `tmp/accept-test/kb-workspace` 已原样保留供检查。）
