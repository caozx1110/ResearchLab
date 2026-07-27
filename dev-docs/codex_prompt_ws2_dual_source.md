你在开源 research-workspace 系统做 **Wave 2 · Track Dual-source（3.1 PDF/HTML 双源管线）**。基线=已重构并 merge 的 main（`0d67971`，core.py 已拆成 domain 模块）。在独立 git worktree 从此 HEAD 分叉。全部改完自测、逐项 commit、**不 push**。

【本 track 拥有的文件（只动这些，避免与其它并行 track 冲突）】
- `.agents/lib/research/sources.py`（重构后新模块：`_is_html_response`/`backup_source`/source 解析/search-staging/storage-sync/dedup 都在这）
- `.agents/lib/research/common.py`（仅 `fetch_url`/`html_to_text`，已支持 `binary=True`）
- `.agents/lib/research/bootstrap.py`（managed venv 逻辑）
- `.agents/skills/source-intake/scripts/intake.py`（add 流程调用 backup_source + auto-screen）
- `requirements.txt`
- 新增自己的测试文件到 `.agents/lib/research/tests/`
**不要碰** `evidence.py` / `confirm.py` / `records.py` / `knowledge-base-manager`（属其它并行 track）。

【设计依据（先读）】`temp/SYSTEM_DESIGN_SSOT.md` 的 3.1（决策 A 分层）+ 原则2 的 B4（两套 locator）。以 SSOT 为准。

【红线】
1. **绝不碰 kb/**（真实用户数据）。所有测试在临时目录。
2. 治理红线不动。本 track 不改 confirmation/gate。
3. 不 push。

============================================================
要做的（按 SSOT 3.1 决策 A）
============================================================
1. **arxiv → HTML 优先**：source 是 arxiv（URL 或 id）时，优先取 HTML 版：依次尝试 `arxiv.org/html/<id>` → `ar5iv.org/abs/<id>` → 回退 abs 页。下到的 HTML 存进 raw（真字节 + sha256），解析为文本供人/AI 读。HTML 无页码 → locator 用 **section/anchor**（B4）。
2. **非 arxiv PDF → 真下载 + 轻量默认后端**：下 PDF 真字节存 raw（真 sha256 + size cap，如 50MB + 简单重试）。文本解析默认用 **PyMuPDF4LLM**（纯 PyMuPDF、无 torch）。PDF locator 用 **page=N**（B4）。
3. **修 backup_source 静默失败**（G7）：当前对非 HTML（PDF/arxiv）走 `file_hash=""` 什么都不存。改为：真持久化字节 + 真 sha256，返回**显式 backup_status/warning**（成功/失败都明确，失败不再静默吞）。warning 只走 stderr/返回值，**不写进 record.source**（历史上有过污染，见 SCHEMAS source 契约）。
4. **两套 locator 落地**：parse-cache（或等价产物）记录 `locator_kind: page|section|anchor` 及来源类型，供下游 evidence（原则2）区分 PDF/HTML。
5. **requirements + 环境**：`requirements.txt` 把 **pymupdf4llm 提为默认依赖**（连同它拉的 pymupdf）；注释说明 MinerU/Docling 是可选重后端（要 torch+GPU，不默认装）、Marker 因商用许可不推荐。`bootstrap.py`：managed venv **默认装轻量 PDF 后端**（PyMuPDF4LLM），消除"默认新用户静默降级成空 parse"的冷启动缺口；`kb doctor`/backend 探测如实反映。
6. **intake.py 接线**：add 流程用新的源解析（arxiv→HTML、PDF→真下载+PyMuPDF4LLM），保持现有 auto-screen 等后续动作契约不变（只换"取源+解析"这一段）。

============================================================
验证（全绿再交，逐条给实际输出）
============================================================
1. `python -m compileall .agents/skills .agents/lib` 通过；相关脚本 `--help` 通过。
2. 全量 `pytest .agents/lib/research/tests -q` 仍全绿（新增测试只增不减）。
3. **真下载 arxiv 一篇**（用一个真实 arxiv id，在临时 KB）：HTML 优先命中、raw 存了真字节+真 sha256、parse 出非空文本、locator_kind=section/anchor。贴证据。
4. **真下载一个非 arxiv PDF**：PyMuPDF4LLM 解析出多段文本、locator_kind=page。贴证据。
5. **对照冷启动**：在只有 PyYAML 的干净 venv 里，验证 bootstrap 现在会装上 PyMuPDF4LLM（或明确报错要求），不再静默产空 parse。贴前后对比。
6. backup_source 失败路径：喂一个坏 URL，确认返回**显式 warning**、不写进 record.source、不静默 `file_hash=""`。
7. kb/ 零改动：`git status` 无任何 kb/ 下改动。

【交付】逐项 commit、不 push。附：arxiv-HTML 与 PDF 两条路径的真下载实测、冷启动前后对比、backup_source 失败显式化证据。遇到 arxiv HTML 对某些老论文不存在时的降级策略，如实说明你怎么处理的。
