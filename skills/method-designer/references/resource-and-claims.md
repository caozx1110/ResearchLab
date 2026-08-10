# Resources and claims

Load only this reference for candidate corpus, resource scaling, preference binding, interfaces, or canonical evidence requirements.

## Candidate and preference context

Canonical task context 绑定 program、selected idea 与 idea substance digest。`method-designer + design` 的 soft research focus 只有被 Agent 选入 current task 时才影响 proposal；脚本可将其用于候选 token ordering，但不能据此做方法判断。

Resources 与 constraints 是 hard boundary；无 preference receipt 时仍从 canonical profile 读取并保存 value digests。Artifacts 不复制 soft preference 正文，verify 会拒绝 wrong/stale selection binding。

## Resource profile and deterministic scaling

`resources` 可包含 structured scalars 或 free-form statements，例如 GPU count/model/memory、cluster 或 time budget。Designer 只保守识别显式 GPU 数、常见 `Nx model`、GPU memory 与 CPU-only/no-GPU 声明；未识别内容逐字保存为 constraints，不猜容量。

每个 experiment row 包含 seed count、model-size tier、parallelism、required GPUs、`unknown|feasible|unrealistic` feasibility、status color、reason 与 request。无可解析资源时保留 legacy 四行 scale 并标 unknown。

Resource scaling 是 structural arithmetic：脚本可决定 seed 数、tier、parallelism 与 capacity feasibility；Agent 提供 method rationale 和 evidence。

## Proposal shape

- Candidate corpus 记录 scope、repo ids、fallback flag 与人类可读 note。
- Interfaces 显式列出 edit surfaces、config keys、metrics 与 artifact expectations。
- Experiment matrix 覆盖 baseline parity、minimal variant、ablation 与 stress/failure slices。
- Run grid 只是 proposal，confirmation 前不可被执行 owner 当成 accepted method。

## Canonical claims and evidence

四条 claims 直接写入 canonical `payload.claims`，不允许 sidecar 充当 confirmation source。每条含稳定 id、Agent-authored text、`inference|evaluation`、`pending_user_confirmation` 和至少一个 current evidence ref。

Evidence ref 必须声明 canonical source unit、artifact、locator 与逐字 quote。Repo-selection claim 的 source unit 必须是 proposed repo。Interface/baseline/risk 的结构槽位不是 substantive rationale；实质判断只存在于四条 claims，verify 与用户 confirmation 前不能宣称完成。

## Safety boundary

Script 只组装 paths、interfaces、candidate order、run-grid scale 与 capacity checks。Agent 才能判断 repo、baseline、mechanism 或 experiment 是否方法上合适。任何基于 idea 文本、lexical overlap 或资源数字自动得出的 method verdict 都无效。
