---
name: source-intake
description: 把 paper / repo / dataset / blog source 先做 staging，再做去重与轻量 record 入库，不直接替代深分析。
---

# Source Intake

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#discovery-retrieval` · `#ownership` · `#runtime`

当一个 source 第一次进入系统，或者需要 review/materialize 已有检索候选时，使用这个 skill。外部文献发现由 `literature-search` 负责。

## 负责范围

1. 备份 raw source，不原地改写；对 paper、HTML、Markdown 和文本同时生成完整 `source/document.md` 阅读层、`source-map.yaml`、`conversion.yaml` 与本地图片资产。
2. review 已有 source-search staging，并只把用户在当前对话中明确接受的候选 materialize 为 canonical unit。
3. 去重、轻量 record 创建、topic / tag / pool 初始归档。
   paper 同时从已归档 HTML/PDF、staged DOI/arXiv identity 与 source URI 机械合并 citation metadata，并写稳定 citation key；不联网补全、不保存 raw BibTeX，强 identity 冲突零写入拒绝。
4. 把 paper / repo / dataset / blog 的深分析统一路由给 `unit-analyst`；facade 再按 kind 调用保持历史身份的内部 implementation。
   用户当前消息明确点名 `kb/obsidian/inbox/` 或 `annotations/` 下一层的一份 Markdown 时，私有 human-note intake 只接收 area+basename，strict UTF-8/no-follow/有界读取后冻结 exact bytes，原文件不改；review sheet、nested、symlink 与 special 一律拒绝。canonical unit 固定为 `blog` 且 `source_origin=human-note`，随后仍由 Agent 填写、逐字核验并保持 pending，不能把“用户写的”当作确认。
5. 新建 unit 默认使用紧凑型 id，例如 `p-example-bf86ee46`、`r-example-dadda683`。
6. 所有 kind 的 add 都先冻结 workspace 外的 exact source/parse snapshot，再解析当前 `source-intake:add` preference。需要 soft preference 时，Agent 先通过私有 `prepare-add` 取得 opaque token 与闭合 canonical context，生成 receipt 后用同一 token 提升；没有 receipt 时自动只执行 hard-only fallback。token、JSON、flags 和内部路径绝不展示给用户。只有明确选入的 `runtime.paper` 才能改变 paper 解析预热等机械行为；record 只保存 task/selection/hard-value digests，不复制偏好原值。receipt、授权、containment 或解析失败对 workspace 零写入，外部 snapshot 必须清理。source-intake 不准备或判断论文内容；`kb ingest` 在 intake 提交后直接进入 paper 的统一 deep-read prepare，由 runtime Agent 填 `paper_type`、类型证据和对应五要素后一次 verify。

`literature-search` 是本 skill 之前的外部文献发现 owner：runtime Agent 使用当前可用的 search/browser/connector 能力做有界、多轮检索，本 skill 不替它选 provider。它只把候选、query/discovery provenance、初筛证据、coverage/frontier 与停止依据写入同一 source-search staging，不创建 canonical paper。收到 search stage 后，本 skill 继续拥有候选 review、去重与正式 materialization；stage id/source kind/normalized original request 不可混用，候选按 DOI、arXiv ID/PMID、canonical URL 跨重跑折叠，并保留人工 status/note、screening history 和全部发现路径。

`document.md` 是人和 agent 的首选完整阅读材料，图片使用相对链接指向 hash-addressed `source/assets/`。已有 Markdown 的 front matter、跨行/块代码、标题与图片按语法上下文保留或本地化，非代码 raw HTML 被动化，纯文本按字面显示；HTML 的公式、复杂表格和多图结构不得为追求统一语法而静默丢失。整套 document/map/conversion/archive/assets 先完成冲突与格式检查再发布。`parse-cache.yaml` 继续承担兼容的逐字证据与 locator 协议；Markdown 转换降级或细节缺失时回退到保存的原格式。转换只搬运和保真，不解释文字、公式或图片，也不产生研究判断。Repository 源码保持为可验证的本地源码树，不批量转写成 Markdown。

收到远程代码仓库 URL 时，不要直接把 URL 交给 repo intake。Agent 先在安全临时目录建立范围明确的只读本地 checkout/snapshot，确认它是可遍历的普通文件树，再以该本地根目录入库；对用户只说明正在本地化代码来源，不泄漏内部命令。底层若拒绝未本地化的远程 repo，agent 应继续完成本地化和重试，不得留下只有网页快照、无法扫描源码的 repo unit。

## 常用内部命令

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/source-intake/scripts/intake.py show-stage --stage-id paper-search-retrieval-augmented-generation-xxxxxxx
${RESEARCH_PYTHON:-python3} .agents/skills/source-intake/scripts/intake.py add --kind paper --source kb/raw/paper.pdf --maturity lightweight
${RESEARCH_PYTHON:-python3} .agents/skills/source-intake/scripts/intake.py add --kind paper --source kb/raw/paper.pdf --maturity complete
${RESEARCH_PYTHON:-python3} .agents/skills/source-intake/scripts/intake.py add --kind repo --stage-id repo-search-example-xxxxxxx --candidate-id repo-search-example-xxxxxxx-ab12cd --pool candidate-tools
```

## 启动澄清（Agent 用）

- 资料类型不明时问 kind（论文/代码仓/数据集/文章）；默认按 URL/目录推断。
- 轻量 add 还是完整 ingest？默认 ingest 链到可确认笔记。
- 批量来源逐条深读吗？默认全部轻量入库+汇总，再挑重点深读。
