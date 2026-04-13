---
name: research-discussion-archivist
description: Archive important technical route discussions into durable program notes under `doc/research/programs/<program-id>/discussions/`, including decisions, tradeoffs, unresolved questions, next validation actions, and linked artifacts. Use when Codex needs to turn chat-level design discussion into a reusable record instead of leaving it only in thread history.
---

# Research Discussion Archivist

Persist technical discussion outcomes before they disappear into chat history.

## Workflow

1. Read `AGENTS.md` plus `doc/research/memory/user-profile.yaml`.
2. Default to Chinese user-facing prose when the profile prefers Chinese.
3. Read the target program's `charter.yaml` and `workflow/state.yaml` for context.
4. Write one discussion note under `doc/research/programs/<program-id>/discussions/`.
5. Keep sections explicit:
   - background
   - current conclusion
   - tradeoffs
   - open questions
   - next validation actions
   - linked artifacts
6. Refresh `doc/research/programs/<program-id>/discussions/index.md`.
7. Append a concise reporting event so weekly reporting can recover the discussion outcome later.

## Shared Contract

- Do not invent evidence that was not discussed.
- Prefer concrete tradeoffs and next actions over generic meeting prose.
- Keep the note durable and self-contained enough that a future agent can understand why the decision happened.
- If the discussion is still unresolved, make the unresolved parts explicit instead of pretending there was a final choice.

## Commands

```bash
python3 .agents/skills/research-discussion-archivist/scripts/archive_discussion.py archive \
  --program-id my-program \
  --title "是否保留 hierarchical VLA + WBC 分层" \
  --summary "讨论高层语义接口与低层 whole-body control 的分层必要性。" \
  --decision "保留分层，但先做最小接口基线。" \
  --tradeoff "分层可解释性更强，但集成成本更高。" \
  --open-question "latent verb 接口是否真的优于更简单的 skill token 方案？" \
  --next-action "先在 Isaac-GR00T 上做无 memory 的最小分层基线。"

python3 .agents/skills/research-discussion-archivist/scripts/archive_discussion.py preview \
  --program-id my-program \
  --title "路线讨论预览" \
  --summary "只预览，不写文件。"
```

## Boundaries

- Do not replace `method-designer`; archive discussion outcomes, do not generate the full design pack here.
- Do not silently mutate program idea decisions just because the discussion note sounds persuasive.
- Do not keep the only copy of key tradeoffs in chat.
