---
name: paper-analyst
description: 负责 v2 paper unit 的 quick-screen、full note、figure extraction、structure refresh 与确认门控。
---

# Paper Analyst

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#unit-payload` · `#confirmation-gate`

当任务是在分析某个 paper knowledge unit，而不是只做入库时，使用这个 skill。

## 负责范围

1. 从 `source-intake` 创建的 paper unit 出发。
2. 先做 quick-screen，再决定是否进入完整 note。
3. 提供 parse cache 预热、quick-screen、`scaffold | draft` 两档完整 note、figure extraction 与 structure refresh，不再生成额外的 `note-context.md`。
4. `extract-figures` 默认按 caption 做整块 Figure / Table page-region 裁切，而不是抽 PDF 内部的小图片对象。
5. 图片导出默认直接过滤纯白图、极低颜色图和 mask-like 图，不保留完整原始导出。
6. AI judgement 默认保持 `pending_user_confirmation`。

## 常用命令

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py prewarm-cache --paper-id p-openvla-bf86ee46
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py screen --paper-id p-openvla-bf86ee46
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py complete-note --paper-id p-openvla-bf86ee46 --mode draft
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py extract-figures --paper-id p-openvla-bf86ee46
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py refresh-structure --paper-id p-openvla-bf86ee46
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py confirm --paper-id p-openvla-bf86ee46
${RESEARCH_PYTHON:-python3} .agents/skills/paper-analyst/scripts/paper.py reject --paper-id p-openvla-bf86ee46
```
