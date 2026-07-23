---
name: idea-workbench
description: 负责 core idea unit 的生成、evidence-first analysis、陪练讨论、多候选管理、显式选择与归档。
---

# Idea Workbench

> 协议参考：`.agents/lib/research/SCHEMAS.md#unit-record` · `#config-files` · `#confirmation-gate` · `#runtime`

当任务是把研究方向收敛成可评审、可比较、可显式选择的 idea unit 时，使用这个 skill。

## 负责范围

1. 捕获单个 idea，或围绕一个主题生成多个候选 idea。
2. 用 prepare / verify 做 evidence-first novelty、feasibility、recommendation 与 killer-question 分析；判断由 runtime agent 产出，脚本只建空结构并验证逐字证据。
3. 提供 idea 内建的「陪练 / sparring」模式：以领域专家 / reviewer 身份 challenge、probe、从 KB 拉 counter-example、追踪论证链，并给 constructive suggestion。
4. 生成 evidence-backed review-ready idea card 与 review-assist。
5. 仅在显式命令下执行 `select-best` 或 `select`；selection 仍保持 `pending_user_confirmation`，不会被脚本自签为 confirmed。
6. 若传入 legacy idea id，脚本会显式提示 canonical id 与 canonical record 路径。

## 核心边界

- 理解、论证、novelty verdict、counter-example 与建议都来自 runtime agent；脚本不得从字段数、链接数或固定阈值生成判断。
- prepare 只提供 idea context、描述性计数提示、空白 judgement claims 与 `evidence_ref` 格式；描述性计数明确不是 score / verdict。
- verify 对每条 judgement claim 运行 `validate_claims`，再按 `source_unit_id` 定位 canonical KB unit，并用 `verify_claim_evidence` 对该 unit 内 artifact 做逐字 quote 校验。
- retrieval 使用 agent 原生检索能力；本 skill 不建 semantic index。
- 判断仍是 `pending_user_confirmation`。证据校验通过只代表 grounded，不等于用户确认判断。

## Evidence-first analysis

`analyze` 与 `review` 都采用 `prepare|verify` 两阶段合同：

1. `prepare` 生成四条空白 judgement claims：`novelty`、`feasibility`、`recommendation`、`killer-question`。
2. runtime agent 从 KB 检索相关 paper / repo / dataset / blog / idea，填入 claim 文本与逐字 `evidence_refs`。
3. `verify` 拒绝空证据、找不到的 source unit、不可读 artifact、伪造 quote 或错误 PDF page locator；全部通过才持久化。
4. `review` 可由 agent 填正整数 `selection_rank`，供 `select-best` 消费。新 review 不生成 heuristic `score_breakdown`；旧记录中已持久化的 score 仅作兼容读取。

## 陪练模式

`discuss`（别名 `spar`）采用 `prepare|verify|confirm` 三阶段合同，并按 conclusion 粒度持久化：

1. `prepare` 生成一份空白 conclusion，包含 `challenge`、`probe`、`counter-example`、`constructive-suggestion` 与 `conclusion` 五条 judgement claims。
2. runtime agent 填 reviewer、总结性 conclusion、五条 claim，以及每条 claim 的 KB 逐字证据；canonical conclusion claim 的 text 必须与总结性 conclusion 完全一致。
3. `verify` 对每个 evidence ref 到其 `source_unit_id` 的 canonical unit 中核验；例如 counter-example 引用 paper 时，quote 必须逐字存在于该 paper unit 的 artifact。
4. 每次 verify 向 `discussion-judgements.yaml` 追加独立 `idea_discussion_conclusion` subject，包含 canonical `payload.claims + payload.verification`；nested conclusion 只是人类可读 projection。
5. `confirm` 只确认指定 conclusion subject 的当前 receipt；多轮 spar 互不覆盖既有讨论历史或已确认 analysis/review claims。

### `payload.discussion.conclusions[]` schema

```yaml
payload:
  discussion:
    conclusions:
      - id: discussion-<digest>
        conclusion: agent-authored synthesis
        reviewer: runtime-agent-or-human-id
        verified_at: ISO-8601 timestamp
        verification: evidence_verified
        judgement_id: discussion-<digest>
        confirmation_status: pending_user_confirmation|confirmed
        claims:
          - id: challenge|probe|counter-example|constructive-suggestion|conclusion
            role: challenge|probe|counter-example|constructive-suggestion|conclusion
            text: agent-authored judgement
            claim_type: inference|evaluation
            confirmation_status: pending_user_confirmation
            evidence_refs:
              - source_unit_id: canonical KB unit id
                artifact: unit-relative artifact path
                locator: page=N|section|anchor|file:line
                quote: short verbatim span
                summary: optional relevance note
```

`verified_at` / verification 只代表证据核验；claim 的 epistemic type 与 `pending_user_confirmation` 保持不变，直到显式用户确认。

## Agent 内部调用

以下命令只供 agent 内部执行，不直接展示给 end user；面向用户只输出自然语言或 `kb <verb>`。

```bash
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py capture --title "retrieval-aware code assistant"
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py generate --title "adaptive retrieval policy" --count 4 --pool current-ideas
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py analyze --idea-id i-example-f7e91d86 --phase prepare
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py analyze --idea-id i-example-f7e91d86 --phase verify
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py review --idea-id i-example-f7e91d86 --phase prepare
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py review --idea-id i-example-f7e91d86 --phase verify
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py discuss --id i-example-f7e91d86 --phase prepare
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py discuss --id i-example-f7e91d86 --phase verify
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py review-assist --pool current-ideas
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py select --idea-id i-example-f7e91d86 --confirmed-by research-lead --evidence kb/programs/example-program/decision-log.md
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py select-best --pool current-ideas --confirmed-by research-lead --evidence kb/programs/example-program/decision-log.md
${RESEARCH_PYTHON:-python3} .agents/skills/idea-workbench/scripts/idea.py archive --idea-id i-example-f7e91d86
```
