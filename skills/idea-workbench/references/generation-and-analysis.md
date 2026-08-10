# Generation and analysis

Load only this reference for capture, candidate generation, evidence-first analysis, or review.

## Capture and generation

`generate` 使用 prepare/verify 两阶段：

1. Prepare 只保存用户原始 title/problem/hypothesis/source/pool context、不可变 orientation、冻结 canonical KB corpus binding 与指定数量的空候选槽位。
2. Runtime Agent 为每个槽位写 title、strategy、problem、hypothesis 和非空 next actions；脚本没有固定策略、语义默认或 winner 规则。
3. Verify 重算 request/orientation/corpus 和可选 preference receipt，核验全部槽位、唯一 identity、字段边界与 distinctness。
4. 全部通过后才在一个 transaction 中创建所有 idea records 与 bundle；任一候选失败时零 candidate/bundle 写入。
5. 用户提供的 title/problem/hypothesis 逐字保留为 generation context，不由脚本扩写成研究判断。

`capture` 只建立一个 canonical idea record；若输入 legacy idea id，只返回 canonical id 和安全的公开说明，不把 legacy identity 当成 current subject。

## Evidence-first analysis and review

1. Prepare 建四条空 judgement claims：`novelty`、`feasibility`、`recommendation`、`killer-question`。
2. Runtime Agent 从冻结 corpus 选择相关 paper/repo/dataset/blog/idea，填写 claim text 与逐字 `evidence_refs`。
3. Verify 先走 shared claim gate，再按 `source_unit_id` 定位 canonical unit，核验 artifact containment、bytes、locator 与 quote。
4. 空 evidence、缺失 unit、不可读 artifact、伪造 quote、错误 PDF page locator 或 corpus 外 source 均 fail closed。
5. `review` 可由 Agent 提供正整数 `selection_rank` 给后续 `select-best` 使用；新 review 不生成 heuristic score。旧持久 score 只作兼容读取，不能成为新 winner 依据。

## Corpus refresh

若新材料不在本轮 frozen corpus，先用 canonical link 将 source 关联到 idea，再明确刷新同一 analyze/review prepare。刷新只保留 owner 白名单内已填字段并重建证据边界；不能把任意路径或未入库材料直接塞入 evidence refs。

内部 link 形态为 `link --from-id <idea-id> --to-id <unit-id> --relation evidence-for`，随后在同一 analysis/review operation 使用 `--refresh-corpus` 重建冻结边界；这些参数不向用户展示。

## Preference binding

`generate/analyze/review` 是 task-scoped preference consumers。Prepare 暴露 value-free task context；Agent 可选择相关 soft preference，verify 重算 current record/request、orientation 与 corpus。无 current receipt 时保持中性。Artifact 只存 selection/task/receipt digests，不复制 preference value。
