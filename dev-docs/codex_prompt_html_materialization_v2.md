# HTML materialization v2 handoff

## STEP 0 · base sync

- 核对当前 HEAD 至少包含 `31e144e` 与 `aafc8a9`，并确认 `.agents/lib/research/source_materials.py` 已存在；若不是，停止并报告，不在未知旧基线施工。

## 文件所有权

- `temp/SYSTEM_DESIGN_SSOT.md`
- `temp/BACKLOG.md`
- `.agents/lib/research/SCHEMAS.md`
- `.agents/lib/research/source_materials.py`
- `.agents/lib/research/sources.py`
- `.agents/lib/research/tests/test_backup_source.py`
- 必要的直接相关投影/schema 测试；不要扩张到真实 `kb/`。

## 施工合同

- 实现 SSOT 3.1 的三层 HTML、候选质量门、PDF fallback、`<base>`、公式占位、Obsidian-safe 图片与内部 fragment、conversion v2 输出验收。
- 脚本绝不理解论文或生成研究判断；只转换、评分来源完整性并验证机械结构。
- raw bytes、Markdown、archive、source map、conversion 与 assets 同内容可幂等，冲突 fail-closed。
- 测试只用临时目录；真实验收也新建临时 KB，不读写 `/Users/czx/Documents/knowledge_base`。
- 面向用户输出只使用自然语言或 `kb <verb>`，不得泄漏内部裸命令合同。

## 提交与逃生口

- 设计/schema、实现、验收记录按关键节点小步 commit。
- 任一质量规则无法从机械事实稳定判定，STOP-and-report，不用论文语义启发式硬编。
