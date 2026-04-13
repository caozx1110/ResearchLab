---
name: paper-research-workbench
description: Legacy compatibility shim for historical prompts or command aliases that still reference the old workbench flow. Use only to route those legacy requests to `research-kb-browser`; do not use for new browsing, query, or wiki-maintenance tasks.
---

# paper-research-workbench (Legacy Shim)

This skill is a strict compatibility shim and should not be selected for new workflows.

## LLM-Wiki Role Boundary (ingest/query/lint/index/log)

- `ingest`: none (delegated).
- `query`: none (delegated).
- `lint`: none (delegated).
- `index`: none (delegated).
- `log`: none (delegated).
- Canonical replacement owner: `research-kb-browser`.

## Shim Rules

1. Prefer `research-kb-browser` for all new browsing, query, and wiki navigation tasks.
2. Keep this shim only for legacy command compatibility and historical prompts.
3. If invoked, immediately route to replacement commands and state the shim behavior explicitly.
4. Do not add new product logic to this shim.
5. If a legacy path returns high-value query findings, require the replacement flow to write them into durable wiki pages instead of chat-only output.

Canonical replacement:

- `research-kb-browser`
- `python3 .agents/skills/research-kb-browser/scripts/open_kb_browser.py`

Legacy command still supported:

```bash
python3 .agents/skills/paper-research-workbench/scripts/open_user_hub.py
```
