---
name: discussion-archivist
description: Archive important technical route discussions into durable program notes under `kb/programs/<program-id>/discussions/`, including conclusions, tradeoffs, open questions, and next validation actions.
---

# Discussion Archivist

Use this skill when an important research discussion should become a durable note instead of staying only in chat.

## Commands

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/discussion-archivist/scripts/archive.py archive --program-id my-program --title "是否保留 latent interface" --summary "..." --decision "..."
```
