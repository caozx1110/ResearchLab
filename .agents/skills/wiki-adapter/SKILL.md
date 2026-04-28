---
name: wiki-adapter
description: Provide a thin wiki-style entrypoint for v2, routing generic “add/query/lint wiki” requests to the correct owner skills and saving reusable query notes under `kb/synthesis/wiki/`.
---

# Wiki Adapter

Use this skill when the user speaks in generic wiki or knowledge-base terms rather than naming the owner skill directly.

## Commands

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/wiki-adapter/scripts/wiki.py query --question "哪些 paper 最适合当前方向？"
${RESEARCH_PYTHON:-python3} .agents/skills/wiki-adapter/scripts/wiki.py add --kind paper --source kb/raw/paper.pdf
${RESEARCH_PYTHON:-python3} .agents/skills/wiki-adapter/scripts/wiki.py lint
```
