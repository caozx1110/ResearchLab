# Markdown-first source materialization handoff

## STEP 0 · base sync

- 以当前 `codex/markdown-source-materialization` HEAD 为唯一 base；先确认 `cd40859` 的 Obsidian projector、relation registry 与测试存在。若不符，停止并报告，不猜测 base。

## 文件所有权

- 设计/schema：`temp/SYSTEM_DESIGN_SSOT.md`、`temp/BACKLOG.md`、`.agents/lib/research/SCHEMAS.md`、`.agents/AGENTS.md`。
- 实现：新增共享 materialization 模块；修改 `sources.py`、`obsidian.py` 及必要 facade/requirements。
- skills/docs：只更新 source-intake、paper/blog/repo 使用说明和公开设计/指南中与材料阅读相关的部分。
- 测试：只在 pytest 临时目录或 `/private/tmp` 新建 KB；禁止读写真实 `/Users/czx/Documents/knowledge_base`。

## 红线

- 原 PDF/HTML/本地文件、既有 parse-cache 与 verification receipt 不覆盖；新增 `document.md` 是完整派生阅读层，不是原始事实替代品。
- analyzer 脚本不理解论文/图片；只转换、搬运、定位、验证。AI 图像理解只能另行 annotation。
- repo 只保存 `repo_id + relative_path`；本地 URI 是可重建投影，不进入 canonical identity。
- 用户可见输出仍只允许自然语言和既有 `kb <verb>`；不得泄漏内部命令/flags/路径协议。
- 不 push；关键 piece 小步 commit。拿不准或遇到 receipt/不可变性冲突时 STOP-and-report。

## 验收

- PDF：完整 `document.md`、逐页稳定块、本地图片相对链接、raw fallback、conversion/source-map hashes。
- HTML：标题/段落/表格/公式基础结构可读；远程/data URI/SVG 图片本地化并 hash 去重；失败显式 degraded。
- Text/Markdown：统一 `document.md` 且无截断；reserved filename 不覆盖。
- Repo：不生成源码 Markdown 镜像；Obsidian 只为 containment 内存在的 artifact 生成本地文件链接。
- 兼容：旧 record/parse-cache/receipt 测试不变；新 materialization additive。
- 门禁：专项测试、完整 release suite、AST/quick_validate、`git diff --check`。
