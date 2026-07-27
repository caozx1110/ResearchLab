# R2 Track C — public UX / recovery consistency / test isolation

## STEP 0 · base sync

- 隔离 worktree HEAD 必须是 `dffcfe7eba239bc373ee8ed327cd435aeb19e464`；核对 `kb-cli/scripts/kb`、四类 analyzer、`test_bootstrap.py` 存在。
- 不符则只在隔离 worktree `git reset --hard dffcfe7eba239bc373ee8ed327cd435aeb19e464`，再核对。
- 设计依据读取主工作区 `temp/SYSTEM_DESIGN_SSOT.md` 的 2026-07-23 R2 decisions；shipping SKILL 是被测产品源码。

## 目标

关闭冷 UX 已复现的幂等、深化、checkpoint、YAML 与测试隔离问题，并修明确文档漂移。不负责跨-owner judgement schema；公共 review 聚合由集成阶段接 Track A contract。

## 只动这些文件

- `.agents/skills/kb-cli/scripts/kb`
- `.agents/skills/kb-cli/SKILL.md`
- `.agents/skills/paper-analyst/scripts/paper.py`
- `.agents/skills/blog-analyst/scripts/blog.py`
- `.agents/skills/dataset-analyst/scripts/dataset.py`
- `.agents/skills/repo-analyst/scripts/repo.py`（只为四类 checkpoint 一致性测试/小修）
- `.agents/skills/research-navigator/SKILL.md`
- `.agents/skills/knowledge-base-manager/SKILL.md`
- `.agents/lib/research/tests/test_bootstrap.py`
- `README.md`、`CHANGELOG.md`、`CONTRIBUTING.md`
- 对应 kb-cli、paper/blog/dataset/recovery/installed-copy tests；可新增 `test_r2_public_ux.py`

不要动 SCHEMAS、judgements.py、method、orchestrator/experiment/idea/report、真实 `kb/`。

## 行为规格

1. 相同显式 quick setup 重复 `kb init` 是 byte/journal/commit no-op；只对真正变化字段写 history/checkpoint。无参数 init 既有 no-churn 不退化。
2. `kb add` 后同源 `kb ingest` 不能只 duplicate-return：读取既有 unit workflow，若仍 `source_ready/awaiting_agent_fill`，继续安全 analyzer prepare；若已 prepared/verified，给状态感知的内部 next action，绝不覆盖 agent 正在填写或已确认内容。
3. paper/blog/dataset verify 的实际 fill artifact 纳入同一 operation checkpoint/恢复 target；行为与 repo 一致。外部 `--input` 若不在 product unit 内不得越权 stage；只 checkpoint canonical unit-owned fill。
4. `worth_deep_reading` 兼容 YAML 1.1 bool `yes/no` 解析，canonical 写回无歧义字符串；scaffold/文档避免引导用户写会变 bool 的裸值。
5. 修 pytest READY 环境污染，使默认目录顺序和单文件运行等价；测试结束恢复 `_RESEARCH_RUNTIME_READY`，并新增最小顺序回归。不要靠改变产品 bootstrap 语义掩盖 fixture bug，除非能证明 runtime sentinel 本身有产品缺陷。
6. 修 15/16 verbs 漂移；navigator 的 First-time use 只能给自然语言 + `kb <verb>`，内部裸命令移到明确 maintainer/private 区；CONTRIBUTING 使用 `requirements-dev.txt`。
7. 保持 public stdout 过滤/no-TTY；duplicate deepen 的机器导航只进 AgentProtocol。

## 红线

- 不覆盖已有 agent fill/confirmed judgement；不碰真实 `kb/`。
- checkpoint 只收本 operation 路径，不用 `git add -A`。
- 用户可见输出无裸命令、flags、内部路径、环境变量、`NEXT FOR AGENT:`。
- 不 push。

## 验收与提交

- 独立复现并新增回归：重复相同 quick setup、add→ingest、三类 dirty fill、bare YAML yes/no、bootstrap→bundle 顺序。
- 跑相关专项、installed-copy tests、public output contract tests。
- commit-per-piece：init/ingest、checkpoint/YAML、test/docs 至少三个小提交；每步 `git diff --check`。
- 需要改 Track A/B 文件时 STOP-and-report。

