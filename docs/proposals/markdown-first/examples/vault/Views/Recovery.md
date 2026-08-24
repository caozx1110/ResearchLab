---
title: Recovery
object_type: view-fallback
status: generated
updated: 2026-08-24
tags:
  - view/recovery
---

# Recovery

如果一次入库中断：

1. 先检查 `Sources/<id>/index.md` 中的 readiness 和 source status。
2. 原件完整但阅读层失败时，回到 `source.*` 或 `snapshot/`，不要把 degraded 当完成。
3. Base、CLI 或插件缺失时，继续使用本页、`Home.md` 和 `Views/*.md`。
