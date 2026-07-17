---
name: kb-cli
description: kb 快捷命令入口（伪 CLI），用于把常用 research 操作统一成 kb 动词形式；当用户在终端运行 kb help/init/doctor/update/status/next/find/recall，或对 AI 说 kb 动词希望代跑对应查询时使用。
---

# kb 快捷命令入口（伪 CLI）

`kb-cli` 是 research 系统的薄 dispatcher。它只做短命令解析、项目 root 解析和参数转译，底层能力继续由既有 skill 脚本负责。

## 使用方式

在终端运行：

```bash
python3 .agents/skills/kb-cli/scripts/kb help
python3 .agents/skills/kb-cli/scripts/kb init
python3 .agents/skills/kb-cli/scripts/kb doctor
python3 .agents/skills/kb-cli/scripts/kb status
python3 .agents/skills/kb-cli/scripts/kb find policy gradient
```

也可以直接对 AI 说：

```text
kb help
kb init
kb doctor
kb update
kb status
kb next
kb find policy gradient
kb recall gotchas
```

## 动词

- `help`：打印分组能力菜单；固定文本，不调用任何 skill。
- `init`：已完成；先转发 `knowledge-base-manager/scripts/kb.py init` 与 `research-config-manager/scripts/config.py init`，TTY 下询问 4 个基础偏好，非 TTY 自动降级。
- `doctor`：已完成；只读打印当前 Python、YAML 与 PDF 后端能力。
- `update`：默认只检查当前与远端 skill 版本；发现更新时先由 agent 请求用户确认，确认后才执行更新。下载缓存位于用户目录下的 `.cache/research-skills/`，离线时只报告暂时无法检查，不修改安装。
- `status [program]`：转发到 `research-navigator/scripts/navigate.py current-state`；带 program 时追加转发到 `research-orchestrator/scripts/orchestrate.py status --program-id <program>`。
- `next [program]`：转发到 `research-orchestrator/scripts/orchestrate.py next`；当前底层脚本按全局 program 优先级给建议。
- `find <keywords...>`：转发到 `knowledge-base-manager/scripts/kb.py query --query "<keywords>"`。
- `recall [kind]`：转发到 `skill-evolution-advisor/scripts/learnings.py recall --kind <kind|all>`。
- `add <src> [--kind paper|repo|blog]`：按 arxiv/pdf/github/git URL 推断 kind，**本地目录（git 检出 / 源码树）判为 `repo`**、本地 `.pdf` 判为 `paper`、其它本地文件判为 `blog`，转发到 source-intake 快速入库。
- `ingest <src> [--kind paper|repo|blog]`：一条命令把 source 拉进来并备好待填骨架，agent 随后自动填 grounded 笔记。链式跑 `intake add → analyzer prepare` 并**停在 prepare**（脚本不能替 agent 填理解，绝不自动 verify），先打印聚合的 `NEXT FOR AGENT:` 行（含 parse-cache 路径 + 待填要素 + 真实 verify 命令），再打印**整条剩余链路导航**（SSOT 原则 7）：paper 为 `填 note → verify → [安全自动] extract-figures + refresh-structure → 初筛第二次填充（screen --phase verify，骨架已在 intake 备好）→ [闸口] 确认判断`；repo/blog 为 `填要素 → verify → [闸口] 确认判断`。安全自动步（figures/structure）受 `runtime-preferences.autonomy.auto_execute_scope`（被 `GOVERNANCE_MAX_AUTO_STEPS` 封顶）的 `refresh` 位约束：收窄时改标注为“超出 scope，仅按需手动”，并从链路摘要里去掉该段；verify/confirm 永不自动。确认闸口命令统一由 `research.common.confirm_command` 渲染。
- `review [fuzzy]`：转发确认收件箱列表；TTY 下逐条确认 / 拒绝 / 跳过 / 退出，并在写入前统一要求 evidence。
- `reject <id> [--reason <text>]`：把误建 / 不采纳的知识单元标记为 `rejected`（清理出口，例如被误判成 blog 的 repo 单元）。纯转发到 `knowledge-base-manager/scripts/kb.py promote --confirmation-status rejected`（`kb review` 拒绝走的同一路径），不重实现拒绝逻辑。

## 约束

- 不复制业务逻辑；写入、确认、检索、状态汇总都留在底层脚本。
- Root 解析复用 `research.common.find_project_root` 和 `add_project_root_argument`，支持 `--root` / `RESEARCH_PROJECT_ROOT`。**`--root` 是顶层 flag，必须放在动词之前**：`kb --root <PROJECT_ROOT> ingest <src>`（放到动词及其参数之后会被 argparse 拒绝）。`kb --help` 与 `kb ingest --help` 均有说明。
- 子脚本失败时保留 stderr，并以非零退出码返回。
