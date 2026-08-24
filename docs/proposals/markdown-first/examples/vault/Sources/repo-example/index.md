---
title: Example repository snapshot
object_type: material
material_id: r-demo-repo
source_type: repo
readiness: analysis-ready
source_status: complete
reader_path: Sources/repo-example/snapshot/README.md
source_ref: "commit:0123456789abcdef0123456789abcdef01234567"
projects:
  - "[[Projects/Material pipeline demo]]"
needs_review: false
updated: 2026-08-24
tags:
  - material/repo
  - sample/markdown-first
---

# Example repository snapshot

> [!info] 代码仓入口
> - [README](snapshot/README.md)
> - [源码入口：`src/train.py`](snapshot/src/train.py)
> - 固定版本：`0123456789abcdef0123456789abcdef01234567`

## 适配器边界

远程仓库先在受控临时区固定 commit/ref，再作为只读普通文件树入库。这里不把全树复制成 `document.md`，也不执行源码。源码文件和 repo-relative `path + line=N` locator 是证据权威。

## 与项目的关系

[[Projects/Material pipeline demo]]
