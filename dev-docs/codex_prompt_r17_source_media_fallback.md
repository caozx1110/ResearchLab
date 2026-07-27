# R17 arXiv media completeness fallback

## STEP 0

从维护者给定 integration HEAD 建独立 worktree；核对 `.agents/lib/research/sources.py`、`source_materials.py`、`test_backup_source.py`。base 不符先报告。完整遵守根 AGENTS.md、SSOT 的 HTML 媒体完整度门和 SCHEMAS。

## 文件所有权

只动 `sources.py`、`source_materials.py`、source/backup/materialization 聚焦测试，必要时 source-intake 的纯 source receipt 测试。不得动 kb-cli/orchestrator/review/updater/installer/journal/version/docs/真实 kb。

## 合同

- materializer 记录 source image/localized/failure count；这只是机械质量事实。
- arXiv HTML 在 source image >=4 且 localization failure ratio >=0.5 时 selection reject，依次试下一 HTML、PDF；普通 blog/显式 HTML 保持 degraded remote fallback。
- 每个 HTML candidate 的 raw+derived bundle 在同盘隔离 staging 完成；rejected candidate 对最终 source root 零残留，只有 chosen candidate 一次发布，conversion 最后。
- source_selection_attempts 只含有界去敏 edition/rationale；显式 arXiv vN 不丢。
- 所有失败保留旧 canonical bundle，不允许先覆盖再 fallback。

## 验收

- 红测：4/4、22/22 missing 会落 PDF；1/3 missing 保留 HTML degraded；普通 blog 仍保留 degraded；第二 HTML 资源完整时选择第二 HTML；PDF 失败再 abstract；rejected staging 零残留；publish I/O failure 原状态不变。
- existing source material/backup tests、Python 3.9 AST/compile、diff check。
- 小步提交，不 push；拿不准原子发布则 STOP-and-report。
