---
name: dataset-analyst
description: 为 dataset unit 准备数据画像待填结构，并校验 runtime agent 填入的定位、组成、schema/access、适用性与风险判断及逐字证据；当来源是 Hugging Face dataset、数据卡、数据集 manifest，或用户要求分析数据规模、模态、格式、许可、接入方式和使用边界时使用。
---

# Dataset Analyst

把 dataset 当作一等知识单元分析，不把数据卡伪装成代码仓库或博客。

## 工作流

1. 从 source-intake 创建的 dataset unit 读取不可变 `parse-cache.yaml`。
2. 运行 `profile --phase prepare` 生成四要素空白骨架。
3. Runtime agent 阅读数据卡并填写 `positioning / composition / schema_access / suitability_risks`；每项附至少一条短逐字 evidence。
4. 运行 `profile --phase verify`；脚本校验结构、逐字 quote 和 locator，全部通过后写 canonical claims、verification receipt 和 `dataset-note.md`。
5. 把判断呈现给用户；只有真实用户授权才能 confirm。

脚本只搬运、验证和写盘，绝不依据 URL、字段名、规模或平台自动判断“质量高”“适合训练”或“可直接复用”。

## Task-scoped preference consumer（Agent 私有协议）

`profile` prepare 完成后，`dataset-fill.yaml` 的 `preference_consumer.task_context` 提供本次 authoring 的 value-free canonical mapping。Runtime Agent 在阅读材料前从 `dataset-analyst:profile` eligible catalog 选择相关子集；无 selection 时保持 neutral，不得直接读取 soft 总偏好。verify 重新绑定当前 record、独立 immutable orientation、exact `parse-cache.yaml` identity/bytes 与完整 `source/` artifact tree；只修改 elements 的 content/evidence_refs 不会让 receipt stale。

任何 record/orientation/parse-cache/source artifact 漂移，或 leaf/ancestor symlink、non-regular replacement，都在业务写入前拒绝。成功仅在 record 保存 value-free selection binding；偏好只能影响 Agent 的研究重点、术语与表达，不能放松四要素、逐字 evidence、source freshness、substance 或人工确认门。

## 四要素契约

- `positioning`：数据集解决什么研究需要、覆盖边界是什么。
- `composition`：模态、任务、embodiment、场景和规模如何组成。
- `schema_access`：格式、split、schema、下载与 dataloader 接入方式。
- `suitability_risks`：适用任务、不适用边界、许可、质量与已知风险。

每个 element 必须提供非空 `content` 和至少一个 `evidence_ref`：artifact 使用 unit 内 `parse-cache.yaml` 或数据卡文件，locator 使用 `section` / `section:<anchor>`，quote 必须逐字存在。

## 边界

- Dataset 页面不运行 repo `scan-structure`。
- 模型仓、代码仓和论文分别路由 repo-analyst / paper-analyst。
- 数据网页抓取失败先回 source-intake retryable staging，不创建空 canonical unit。
- Judgement verify 后保持 `pending_user_confirmation`；禁止 Agent 自签。

## Owner commands

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/dataset-analyst/scripts/dataset.py profile --dataset-id d-example-12345678 --phase prepare
${RESEARCH_PYTHON:-python3} .agents/skills/dataset-analyst/scripts/dataset.py profile --dataset-id d-example-12345678 --phase verify --input dataset-fill.yaml
${RESEARCH_PYTHON:-python3} .agents/skills/dataset-analyst/scripts/dataset.py confirm --dataset-id d-example-12345678 --confirmed-by research-lead --evidence kb/units/datasets/d-example-12345678/dataset-note.md
```
