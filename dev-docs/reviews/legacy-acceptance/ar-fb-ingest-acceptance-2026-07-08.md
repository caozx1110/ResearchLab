# AR-FB Paper Ingestion — Honest Test Report

Test date: 2026-07-08. Workspace: `/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/codex-test-ws`.
Paper: "Finer Behavioral Foundation Models via Auto-Regressive Features and Advantage Weighting" (arXiv 2412.04368), copied to `inbox/ar-fb-2412.04368.pdf`.
Role: brand-new user following `docs/INSTALL.md` + `docs/USER_GUIDE.md`.

---

## TL;DR (the blunt version)

- The install itself is smooth. `bash install.sh --claude --project <ws>` copies `.agents/` + `AGENTS.md`, wires `.claude/skills`, writes a manifest. `kb init` builds the whole `kb/` skeleton and even a nested git repo. No friction.
- **The default new-user experience is broken for PDFs.** The managed venv ships PyYAML only. On this machine the managed venv was never even created — system `python3` (3.9.6) already has `yaml`, so the bootstrap short-circuits and runs on a Python with **no PDF backend at all**. Result: the PDF is "ingested" but **zero text is extracted**. Screening, note, and structure all get produced anyway, full of placeholders, and the paper is judged `worth_deep_reading: no` purely because there was no text. `extract-figures` is the only step that hard-errors.
- After manually installing `pypdf` + `PyMuPDF` + `Pillow` into `<ws>/.venv` and re-running, text extraction and figure extraction both work well: 16 real text chunks, 14 real cropped figure PNGs with real captions.
- **BUT even in the good case, the "understanding" is not there.** The scripts produce a *fillable scaffold* plus *keyword-count heuristics*. `note.md` is a template whose only paper-derived content is a raw copy-paste of the first ~900 chars of page 1 pasted under "Problem / Motivation". `core_content` (research_problem, method, innovations, mechanism) is **all empty strings**. The screening's grades (novelty=strong, etc.) are literal counts of hardcoded keywords, not comprehension. The system expects **an AI agent to hand-write the real note** into the scaffold. The Python scripts do not and cannot understand the paper.
- **A metadata bug for new users:** because `kb add` ran under the no-PDF-backend default, the record's `basic_info` (title, authors, year, abstract) was populated as blanks / filename-stem — and it **never self-heals** even after backends are installed, because re-`add` is blocked by dedup. So `title: ar-fb-2412.04368`, `authors: []`, `abstract: ''` are permanently baked into `record.yaml` unless a human/agent hand-edits it.

---

## 1. Install experience

### Commands run (verbatim)

```bash
# fresh workspace
rm -rf tmp/codex-test-ws && mkdir -p tmp/codex-test-ws

# dry-run (clean, exit 0)
bash install.sh --dry-run --claude --project /abs/tmp/codex-test-ws

# real install (exit 0)
bash install.sh --claude --project /abs/tmp/codex-test-ws
```

Install output (trimmed):

```
Preflight
• Checking PyYAML with 'python3'
• No active VIRTUAL_ENV detected.
copy-project install complete: .../tmp/codex-test-ws
Smoke: kb help
Smoke: kb --root '.../tmp/codex-test-ws' doctor
✓ Install complete.
✓ Workspace: .../tmp/codex-test-ws (解耦拷贝)
✓ Claude wiring is configured.
```

Created at workspace top level: `.agents/` (full copy, real dir), `.agents/.install-manifest.json`, `AGENTS.md`, `CLAUDE.md` (managed block), `.claude/skills -> ../.agents/skills`. Matches the docs exactly. No friction.

### PDF backends present by default? NO.

`kb doctor` right after install (default env, before any manual pip):

```
python: /Applications/Xcode.app/Contents/Developer/usr/bin/python3
version: 3.9.6
yaml: available
pdf: missing
module.yaml: available
module.PyPDF2: missing
module.pypdf: missing
managed_venv: .../tmp/codex-test-ws/.venv
managed_venv.exists: no
managed_venv.python: .../tmp/codex-test-ws/.venv/bin/python
managed_venv.current: no
```

Key facts:
- **`pdf: missing`** — no PyPDF2/pypdf, and PyMuPDF/Pillow (needed for figures) are not even probed by doctor.
- **`managed_venv.exists: no`** — and it stayed `no` through `kb init` and `kb add` too. The managed venv is only created when the current interpreter *can't* import yaml (`bootstrap.py: ensure_managed_runtime` → `_current_has_yaml()` short-circuit). Here system python3 has yaml, so **no venv is ever built** and everything runs on bare 3.9.6 with no PDF support. `docs/INSTALL.md` says "首次运行会自动创建并使用项目内受管 .venv（含 PyYAML）" — that is misleading on any machine whose default python3 already has PyYAML: the venv is silently skipped, and the user gets a yaml-capable but PDF-incapable runtime with no warning at ingestion time.

### `kb init` (headless)

```bash
.agents/skills/kb-cli/scripts/kb --root <ws> init --name codex-test-user --lang zh --auto-commit manual --auto-screen true
```

Worked, exit 0. Built `kb/` skeleton (config, units/{papers,repos,blogs,ideas,experiments}, programs, synthesis, user, output, .runtime), initialized a **nested git repo under `kb/`** and made checkpoint commit `87f429a`. Ends with hint `run kb init --git-init`.

---

## 2. File tree of everything created for this one paper

Under `kb/units/papers/p-ar-fb-2412-cc9a83e8/` (final, backends installed, maturity=complete):

```
figures.yaml
figures/figure-001.png ... figure-014.png   (14 real cropped PNGs)
note.md
parse-cache.yaml
record.yaml            (943 lines — 856 lines are figure-caption payload + history)
screening.yaml
source/ar-fb-2412.04368.pdf   (backup copy of the source)
structure.yaml
```

Rest of kb touched by the flow:

```
kb/index.yaml          (1 paper indexed)
kb/index.md
kb/config/{candidate-pools,runtime-preferences,topic-taxonomy,user-profile}.yaml
kb/config/research-settings.md
kb/user/current-state.md
kb/user/navigation.md
kb/.runtime/versioning-state.yaml
```

Note: `kb/raw/` is **empty** — the source backup lives at `kb/units/papers/<id>/source/`, not `kb/raw/`, despite the USER_GUIDE mental model saying `raw/` holds source bytes. Minor doc/impl mismatch.

Managed venv after manual backend install (`<ws>/.venv`):

```
pillow 11.3.0 · PyMuPDF 1.26.5 · pypdf 6.14.2 · PyYAML 6.0.3
```

---

## 3. Verbatim contents of key artifacts

### 3a. `record.yaml` — head (the load-bearing fields)

```yaml
id: p-ar-fb-2412-cc9a83e8
kind: paper
title: ar-fb-2412.04368                      # <-- filename stem, NOT the real title
status: active
maturity: complete
confirmation_status: confirmed
needs_human_confirmation: false
information_types: [fact]
summary: '`ar-fb-2412.04368` 的相关性信号为 strong，当前 topic/tag 为：uncategorized。'
tags: [research]                             # <-- generic seed tag, not paper-derived
topics: [uncategorized]                      # <-- never classified
source:
  original_uri: .../tmp/codex-test-ws/inbox/ar-fb-2412.04368.pdf
  backup_paths: [kb/units/papers/p-ar-fb-2412-cc9a83e8/source/ar-fb-2412.04368.pdf]
  backup_kind: file
  file_hash: 1cd089482bd7d07f4f4c263bd33efac93339278543d8086b204890fbb3761113
payload:
  basic_info:
    title: ar-fb-2412.04368                  # <-- STALE: still filename stem
    authors: []                              # <-- STALE: empty (set at no-backend intake)
    institutions: []
    venue: ''
    year: ''                                 # <-- STALE: empty
    source_url: https://arxiv.org/abs/2412.04368   # correct (parsed from filename)
    abstract: ''                             # <-- STALE: empty
    arxiv_id: '2412.04368'                   # correct (parsed from filename)
    doi: ''
  quick_screen:
    worth_deep_reading: 'yes'
    judgement_reason:
    - '`ar-fb-2412.04368` 的相关性信号为 strong，当前 topic/tag 为：uncategorized。'
    - 实验信号=moderate，创新信号=strong，结果信号=moderate。
    backing_strength: moderate
    result_strength: moderate
    experiment_quality: moderate
    reliability: strong
    novelty: strong
    relevance_to_current_research: strong
    screening_mode: heuristic_structured
    keyword_hits:
      result: [improvement]
      experiment: [benchmark, dataset]
      reliability: [limitation, failure, appendix]
      novelty: [first, introduce]
      relevance: [policy, humanoid]
    recommended_next_action: complete-note
  core_content:                              # <-- ENTIRELY EMPTY. never populated by any script.
    research_problem: ''
    motivation: ''
    story: ''
    method: ''
    innovations: []
    changes_and_effects: []
    mechanism: ''
    why_it_might_work: ''
  structure: { ...see structure.yaml, includes false-positive headings... }
  figures: { extraction_status: pending_user_confirmation, candidate_figures: [14], key_figures: [14] }
  state:
    reading_status: unread
    full_note_status: pending_user_confirmation
    note_generation_mode: draft
# history: 9 entries (created, paper-screened x2, paper-note-created x2,
#   paper-structure-refreshed x2, paper-figures-extracted, paper-confirmed)
```

Full file is 943 lines; ~700 of those are the verbatim figure-caption text embedded under `payload.figures.candidate_figures[].caption` (real captions, quoted below in 3e).

### 3b. `screening.yaml` (FULL, final run with pypdf)

```yaml
paper_id: p-ar-fb-2412-cc9a83e8
status: pending_user_confirmation
information_types: [evaluation, inference, unverified]
screening_mode_requested: heuristic_structured
screening_mode_effective: heuristic_structured
screening_mode_warning: ''
worth_deep_reading: 'yes'
judgement_reason:
- '`ar-fb-2412.04368` 的相关性信号为 strong，当前 topic/tag 为：uncategorized。'
- 实验信号=moderate，创新信号=strong，结果信号=moderate。
evidence_snapshot: 'Finer Behavioral Foundation Models via Auto-Regressive Features and Advantage
  Weighting Edoardo Cetin, Ahmed Touati, Yann Ollivier December 6, 2024 Abstract
  The forward-backward representation (FB) is a recently proposed framework (Touati
  et al., 2023; Touati & Ollivier, 2021) to train behavior foundation models(BFMs)
  that aim at providing zero-shot efficient policies for any new task ... [~900 chars
  of raw page-1 text, truncated at "often requires specific techniqu"]'
evidence_pages: [1, 2, 3, 4, 5]
backing_strength: moderate
result_strength: moderate
novelty_signal: strong
experiment_signal: moderate
reliability_signal: strong
relevance_signal: strong
keyword_hits:
  result: [improvement]
  experiment: [benchmark, dataset]
  reliability: [limitation, failure, appendix]
  novelty: [first, introduce]
  relevance: [policy, humanoid]
risks:
- quick screen 基于局部页面与启发式信号，仍需人工确认。
- 当前缺少摘要级上下文，方法与实验判断可能偏粗。
takeaways:
- 建议先看摘要、方法总览与实验章节，当前 worth-deep-reading=yes。
- 确认 benchmark、ablation、real-world / real-robot 证据是否真的支撑标题承诺。
- 如果与你当前 program 强相关，再进入完整笔记与 Figure 资产整理。
recommended_next_action: complete-note
```

### 3c. `note.md` (FULL, final run with pypdf, mode=draft)

```markdown
# ar-fb-2412.04368

## 快速判断

- 生成模式：draft（AI 草稿，待人工确认）
- 是否值得细读：yes
- 创新性：strong
- 实验扎实度：moderate
- 可靠性：strong
- 相关性：strong
- 当前 topics：uncategorized
- 当前 tags：research

## Problem / Motivation

Finer Behavioral Foundation Models via
Auto-Regressive Features and Advantage
Weighting
Edoardo Cetin, Ahmed Touati, Yann Ollivier
December 6, 2024
Abstract
The forward-backward representation (FB) is a recently proposed
framework (Touati et al., 2023; Touati & Ollivier, 2021) to train behav-
ior foundation models(BFMs) that aim at providing zero-shot efficient
policies for any new task specified in a given reinforcement learning (RL)
environment, without training for each new task. Here we address two
core limitations of FB model training.
First, FB, like all successor-feature-based methods, relies on a linear
encoding of tasks: at test time, each new reward function is linearly
projected onto a fixed set of pre-trained features. This limits expressivity
as well as precision of the task representation. We break the linearity
limitation by introducing auto-regressive featuresfor FB, whic

## 故事线 / 论文结构

- 快速判断
- Problem / Motivation
- 故事线 / 论文结构
- 核心方法与关键机制
- 关键实验与结果
- Figure 级线索
- 可靠性 / 薄弱点 / Failure Case
- 与我当前 program / idea 的关系
- 可复用结论
- 待确认问题

## 核心方法与关键机制

- 先抓方法主张、核心模块、信息流和关键训练 / 推理机制。
当前 quick-screen 理由：
- `ar-fb-2412.04368` 的相关性信号为 strong，当前 topic/tag 为：uncategorized。
- 实验信号=moderate，创新信号=strong，结果信号=moderate。

## 关键实验与结果

- 当前实验信号：moderate
- 当前结果信号：moderate
- 重点核对 benchmark、baseline、ablation、real-world 结果是否齐全。

## Figure 级线索

待提取 Figure / Table 资产后补全。

## 可靠性 / 薄弱点 / Failure Case

- 当前可靠性信号：strong
风险：
- quick screen 基于局部页面与启发式信号，仍需人工确认。
- 当前缺少摘要级上下文，方法与实验判断可能偏粗。

## 与我当前 program / idea 的关系

- 结合当前 topics/tags 判断其是否能提供方法线索、实验设计线索或引用价值。

## 可复用结论

- 方法机制：
- 实验套路：
- 可引用表述：

## 待确认问题

- 哪个 claim 最值得二次核对？
- 是否需要补读 appendix / project page / code repo？
```

### 3d. `parse-cache.yaml` (first ~40 lines; 16 chunks total)

```yaml
paper_id: p-ar-fb-2412-cc9a83e8
generated_at: '2026-07-09T11:19:11'
cache_policy:
  front_limit: 8
  back_limit: 0
  per_page_char_limit: 3000
chunks:
- label: ar-fb-2412.04368.pdf:page-1
  text: 'Finer Behavioral Foundation Models via
    Auto-Regressive Features and Advantage
    Weighting
    Edoardo Cetin, Ahmed Touati, Yann Ollivier
    December 6, 2024
    Abstract
    The forward-backward representation (FB) is a recently proposed
    framework (Touati et al., 2023; Touati & Ollivier, 2021) to train behav-
    ior foundation models(BFMs) that aim at providing zero-shot efficient
    policies for any new task specified in a given reinforcement learning (RL)
    environment, without training for each new task. Here we address two
    core limitations of FB model training.
    First, FB, like all successor-feature-based methods, relies on a linear
    encoding of tasks: at test time, each new reward function is linearly
    projected onto a fixed set of pre-trained features. This limits expressivity
    as well as precision of the task representation. We break the linearity
    limitation by introducing auto-regressive featuresfor FB, which let fine-
    ...'
# (16 chunks: pages 1-8 front + more; real extracted PDF text)
```

### 3e. `figures.yaml` (structure + representative real captions)

```yaml
status: pending_user_confirmation
information_types: [fact, inference, unverified]
candidate_figures:        # 14 entries, each with real caption text pulled from the PDF
- figure: figure-001
  kind: figure
  label: '1'
  source: caption-region
  page: 6
  caption: 'Figure 1: An auto-regressive architecture for B(s, z). The i-th block of the
    output B only depends on blocks z1, . . . , zi−1 of the input z. ...'
  status: pending_user_confirmation
- figure: figure-002
  page: 12
  caption: 'Figure 2: Average cumulative reward achieved by the algorithms, trained on RND
    dataset for different representation dimensions ... in the Jaco arm environment.'
- figure: figure-005
  label: unknown          # <-- FALSE POSITIVE: this is body text "Figures 3 and 4 report..."
  page: 13                #     ~2 paragraphs of prose captured as a "figure caption"
  caption: 'Figures 3 and 4 report the results for the Cheetah, Quadruped, Walker and
    Humanoid environments, using MOOD data for training ...'
# ...figure-006 (p34), etc.
key_figures: [14 items — same as candidate_figures, with crop_bbox + path to PNG]
asset_counts: {kept: 14, filtered: 7}
filter_policy:
  mode: caption-region
  captions_detected: 21
  discard_filtered_files: true
open_questions:
- caption 裁剪是否已经覆盖了论文里真正需要复用的整张 Figure / Table？
- 是否仍有极少数跨栏或无 caption 的对象需要人工补裁？
```

Figure PNGs are genuine cropped page regions (e.g. figure-001 358x350px 24KB, figure-002 903x363px 28KB, figure-006 878x250px 98KB). 14 kept, 7 filtered as blank/mask-like.

### 3f. `structure.yaml` (FULL, final run with pypdf)

```yaml
status: pending_user_confirmation
information_types: [fact, inference, unverified]
detected_sections:
- {heading: 快速判断, source: note.md}                    # <-- these 10 are the NOTE'S OWN
- {heading: Problem / Motivation, source: note.md}         #     template headings, not the
- {heading: 故事线 / 论文结构, source: note.md}            #     paper's sections
- {heading: 核心方法与关键机制, source: note.md}
- {heading: 关键实验与结果, source: note.md}
- {heading: Figure 级线索, source: note.md}
- {heading: 可靠性 / 薄弱点 / Failure Case, source: note.md}
- {heading: 与我当前 program / idea 的关系, source: note.md}
- {heading: 可复用结论, source: note.md}
- {heading: 待确认问题, source: note.md}
- {heading: abstract, source: 'ar-fb-2412.04368.pdf:page-1', page: 1}   # real
- {heading: 'limitation by introducing auto-regressive featuresfor fb, which let fine-',
   source: 'ar-fb-2412.04368.pdf:page-1', page: 1}          # <-- FALSE POSITIVE (mid-sentence)
- {heading: appendix a., source: 'ar-fb-2412.04368.pdf:page-5', page: 5}   # real-ish
paper_outline: [ ...same 13 headings, incl. the false positive... ]
open_questions:
- 章节结构是否因 PDF 文本抽取而漏掉子节？
```

Only 3 of 13 "detected sections" come from the PDF, and one of those 3 is a false positive (a wrapped sentence fragment, not a heading). The paper's actual sections (Introduction, Auto-Regressive Features, Advantage Weighting, Experiments, Related Work, etc.) are NOT captured — the `SECTION_PATTERNS` matcher only fires on lines that *equal* or *start with* a known English keyword, and this PDF's headings did not survive text extraction as clean standalone lines.

---

## 4. THE KEY JUDGMENT — real content vs template/heuristic scaffolding

### `screening.yaml` / `quick_screen`

**Real, paper-derived (thin but genuine):**
- `evidence_snapshot` — a verbatim ~900-char slice of the real page-1 text (title, authors, abstract opening). This is a real extract.
- `evidence_pages: [1,2,3,4,5]` — real page numbers that had extractable text.
- `keyword_hits` — real in the sense that these exact tokens *do* appear in the extracted text: `novelty:[first, introduce]`, `experiment:[benchmark, dataset]`, `reliability:[limitation, failure, appendix]`, `relevance:[policy, humanoid]`, `result:[improvement]`.

**Template / heuristic / would-read-the-same-for-any-paper:**
- Every `*_signal` grade is a **count of hardcoded keywords**, not comprehension. `novelty_signal: strong` only means "≥2 words from the list `[novel, first, we propose, introduce, unified, generalist, open-world]` appeared." A paper that merely says "we introduce the first..." scores `novelty: strong` regardless of whether the idea is novel. (See `screening_payload()` / `_grade()` / `_match_keywords()` in `paper.py`.)
- `worth_deep_reading: yes` is a threshold on the summed keyword grades — pure arithmetic.
- `judgement_reason` is an f-string template: "`{title}` 的相关性信号为 {relevance}，当前 topic/tag 为：{topics}." + "实验信号={x}，创新信号={y}，结果信号={z}." — identical shape for every paper.
- `risks` and `takeaways` are **fixed constant strings** hardcoded in the script ("quick screen 基于局部页面与启发式信号，仍需人工确认。" / "建议先看摘要、方法总览与实验章节..."). They never vary by paper content.
- `relevance_signal: strong` here is an artifact: with no real topics/tags, the code falls back to matching a hardcoded VLA/robotics term list `[vision-language-action, vla, robot, policy, control, manipulation, humanoid]`. This paper is an offline-RL/behavior-foundation-model paper; "policy" and "humanoid" (a DMC benchmark env) happened to match, so it's flagged `strong` relevance to a research direction it isn't really about.

### `note.md`

**Real, paper-derived:**
- Exactly ONE block: the text under `## Problem / Motivation`, which is a raw dump of `_source_preview()` = first ~900 chars of page 1 (title + authors + abstract opening). It is real, but it is unprocessed copy-paste, not a written "problem/motivation."

**Template / placeholder / heuristic:**
- `## 快速判断` bullets = the keyword-heuristic grades from screening.
- `## 故事线 / 论文结构` = a bulleted echo of the note's own section headings (via `structure.paper_outline`), i.e. self-referential, not the paper's storyline.
- `## 核心方法与关键机制` = one constant instruction line + the templated `judgement_reason`. No actual method.
- `## 关键实验与结果` = the two heuristic signal grades + a constant "重点核对 benchmark…" line. No actual results.
- `## Figure 级线索` = literal string "待提取 Figure / Table 资产后补全。" (this draft was written before figures were extracted; it does not back-fill).
- `## 可靠性 / 薄弱点`, `## 与我当前 program 的关系`, `## 可复用结论` (方法机制/实验套路/可引用表述), `## 待确认问题` = **all empty scaffolding or constant prompt strings.** These read identically for any paper on earth.

So of ~10 note sections, **1 has real (raw, unsynthesized) paper text; the rest are scaffold.**

### Bottom line on "intelligence"

The Python does: parse PDF text → cache it → count keywords → grade → drop the raw text and constant strings into a Markdown template. There is **no summarization, no method extraction, no comprehension.** The empty `payload.core_content` block (`research_problem/method/innovations/mechanism` all `''`) is the smoking gun: the canonical "what is this paper about" fields are never written by any script.

---

## 5. Did the flow rely on the agent to hand-write the understanding? YES.

This is by design, and the docs are honest about it. `docs/USER_GUIDE.md` states the division: "这个系统不是一个预装好的知识库... AI 负责提取、整理，你负责判断" and "AI 做重复劳动，你做判断." The scripts are deterministic scaffolding tools. The `note_template()` function literally emits placeholder prompts ("待结合摘要和引言补全。", "方法机制：", "可引用表述：") that are **instructions to a human or an AI agent** to fill in.

Where the intelligence is *supposed* to come from: the LLM agent (Claude/Codex) driving the skills is expected to read `parse-cache.yaml` (or the PDF) and **hand-write** the real note body, then set `full_note_status`. The `screen` step even carries `screening_mode_requested` with a fallback warning "no LLM screening backend is configured; fell back to heuristic_structured" — confirming the heuristic path is a *degraded stand-in* for real LLM screening that isn't wired into the script at all.

In other words: run the scripts alone (as I did) and you get a **fillable form with keyword-count grades and one raw text dump**. The actual understanding only exists if an agent subsequently writes it in. Nothing in the confirm step checks that the note was actually filled — I confirmed a scaffold-only note to `maturity: complete, confirmation_status: confirmed` with a one-line evidence string and zero real content. The confirmation gate is procedural (needs a human name + evidence string), not substantive.

---

## 6. Default new-user experience (NO backends) vs after backends — side by side

I ran the whole flow twice: first on the default runtime (no PDF backend), then after `pip install pypdf PyMuPDF Pillow` into `<ws>/.venv`.

| Step | DEFAULT (no PDF backend, system py3.9) | AFTER pypdf+PyMuPDF+Pillow |
|---|---|---|
| `kb add` | exit 0, "created record". **Silent degrade.** | (blocked by dedup on re-add) |
| PDF text parse | `parse-cache.yaml` → **`chunks: []`** (empty) | 16 real chunks, real text |
| `basic_info` | title=filename, authors=[], year='', abstract='' | **still stale** (set at intake; never re-derived) |
| `screen` worth | **`worth_deep_reading: no`**, all signals weak, `keyword_hits` all empty, `evidence_snapshot: ''` | `worth: yes`, real keyword hits, real snapshot |
| screen honesty | adds reason line: "当前没有稳定抽取到 PDF / 源文本，快速判断可信度较低。" (good — it flags it) | (line drops out) |
| `complete-note` | exit 0. note body under Problem/Motivation = literal "待结合摘要和引言补全。" | real page-1 text dump |
| `refresh-structure` | exit 0. structure = only the 10 note-template headings, no PDF sections | + 3 PDF-derived (1 false positive) |
| `extract-figures` | **HARD ERROR, exit 1:** `PyMuPDF is required for caption-region figure extraction. Install it into the research runtime first.` No figures. | 14 real cropped PNGs, 7 filtered |

**How the default degrades:** not a crash for text — it **silently produces empty/placeholder artifacts**. `extract_pdf_context_pages` needs a backend (`pdf_backend()` raises `ModuleNotFoundError`), but `_load_source_chunks` swallows it in a bare `except Exception: payload = {"pages": []}`, so you get `chunks: []` with no warning in the `add`/`screen` output. The only user-visible signal is (a) `kb doctor` saying `pdf: missing` if you happen to run it, and (b) the screening reason line noting text wasn't extracted. A new user who trusts `kb add` would get a paper judged "not worth reading" and a hollow note, with no error telling them to install a backend.

**`extract-figures` is the one honest hard-fail** — it refuses with a clear actionable message. Text extraction should arguably do the same instead of silently emptying.

---

## 7. Errors, silent failures, confusing UX

1. **Silent PDF-text degradation (the big one).** Default runtime has no PDF backend, yet `kb add`/`screen`/`complete-note` all return exit 0 and produce artifacts from empty text. The failure is buried; only `kb doctor` reveals it. See §6.
2. **Managed venv never created on this machine.** Docs promise an auto `.venv`; because system python3 already has PyYAML, bootstrap short-circuits and the `.venv` promise silently doesn't happen — and the runtime it lands on lacks PDF support. The doc's "含 PyYAML" venv also wouldn't have fixed PDFs anyway (PyYAML only).
3. **`--root` arg position gotcha.** `paper.py <subcommand> --root <ws>` fails with "unrecognized arguments: --root"; it must be `paper.py --root <ws> <subcommand>`. The `kb` dispatcher gets this right, but a user copy-pasting the SKILL.md examples and appending `--root` will hit it.
4. **Stale metadata never self-heals.** `basic_info` (title/authors/abstract) is only derived during `kb add`. If that first add ran without a PDF backend (the default!), the record is permanently wrong: re-`add` is refused as a duplicate, and no other command re-extracts metadata. Final record still says `title: ar-fb-2412.04368`, `authors: []` even though the parse-cache and screening now have the true title and authors.
5. **Heuristic false positives.** structure.yaml has a mid-sentence fragment as a "section heading"; figures.yaml has 2 paragraphs of body prose captured as a "Figure caption" (figure-005, label: unknown). Both are flagged `pending_user_confirmation`, so a human is expected to catch them — consistent with the design, but noisy.
6. **`kb/raw/` empty.** USER_GUIDE says raw source bytes live in `kb/raw/`; actual backup lands in `kb/units/papers/<id>/source/`. Doc/impl drift.
7. **Confirmation is procedural, not substantive.** A scaffold-only note with empty `core_content` was promoted to `confirmed`/`complete` with a trivial evidence string. Nothing verifies real content exists.

---

## 8. What this system actually produces for one paper (verdict)

A **deterministic scaffold + PDF asset extractor**, not an understanding engine:
- Reliable & real when backends are present: PDF text cache (16 chunks), figure crops (14 real PNGs + captions), arxiv_id/source_url from filename, dedup, provenance/history, confirmation gating, index.
- Fake-ish / templated: all quick-screen "quality" grades (keyword counts), the note body (1 raw text dump + constant scaffolding), structure detection (mostly the note's own headings).
- Never produced by scripts: any synthesized problem/method/innovation/result summary (`core_content` stays empty), correct title/authors/abstract when the first add lacked a PDF backend.

The "intelligence" is explicitly outsourced to the driving AI agent, which must read the cache/PDF and hand-write the note. Run the pipeline headless (no agent), and you get a confident-looking but hollow unit: graded, figured, indexed, confirmed — and almost entirely devoid of real comprehension of the paper.
