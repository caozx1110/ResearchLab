# 黄金对话套件（GOLDEN SUITE）

8 条端到端"黄金对话"规格，用于回归验收与体验度量。每条都从真实用户话术出发，走公开面（自然语言 + `kb <动词>`），Agent 内部按 `.agents/AGENT_GUIDE.md` 调用 owner 脚本。

**统一记录指标**（每条每轮采集）：

| 指标 | 定义 |
|---|---|
| 操作步数 | Agent 实际发起的脚本/工具调用次数（含重试） |
| 失败次数 | 非零返回或需要更换调用方式的次数；单列"机制摸索"（因不知道语法/flag 而失败或翻源码的次数） |
| 耗时 | 从用户消息到最终回复的墙钟时间 |
| 加载规则 token 估算 | 本条对话为掌握机制而加载的文档 token（AGENT_GUIDE ≈2.4k；对照：翻散落源码摸索 ≥8k） |

**基线口径**：改进前实测一次完整链路（安装→ingest→确认）约 **20 次调用，其中 9 次为机制摸索**（协议文件名 vs token、flag 位置、ref 格式等）。引入 AGENT_GUIDE 后的目标：机制摸索 →0，总步数逼近"最小必要步数"列。下表各条未单测项标"待采集"。

---

## G1 安装 → init

- **步骤**：①运行 install.sh 装入目标目录；②用户说"初始化我的知识库"；③Agent 跑 `kb init`；④用户对设置问题答"默认即可"或"先跳过"。
- **期望**：kb/ 布局与索引建立；跳过设置不写偏好/sentinel、不阻塞后续；不向用户暴露内部路径。
- **最小必要步数**：2-3 次调用（init + doctor 自检）。
- **基线**：待采集（首测混在全链 20 次中）。失败数目标 0。

## G2 ingest 本地 Markdown → fill/verify → review 确认

- **步骤**：①用户丢一个本地 md 文件"帮我入库并整理"；②`kb ingest <路径>`（intake+prepare 自动）；③Agent 读 document.md 填 fill（逐字 evidence）；④owner verify；⑤`kb --agent-protocol r1.json review` 展示；⑥用户说"第一条确认"；⑦按 AGENT_GUIDE §2 语法 apply。
- **期望**：unit 落库、judgement 经逐字校验、确认带用户原话与 evidence，一次 apply 成功。
- **最小必要步数**：约 6-7 次调用。
- **基线**：全链首测约 20 次调用、其中 9 次机制摸索（本条为主要来源）。目标 ≤8 次、摸索 0。

## G3 ingest repo → 能力图

- **步骤**：①用户给 GitHub URL；②Agent 先本地只读 checkout（远程 repo 直接入库会被拒）；③`kb ingest <本地目录>`；④scan-structure + map-capability prepare；⑤Agent 读关键文件填三要素（file + line=N 逐字证据）；⑥verify；⑦review 确认。
- **期望**：capability/reuse_points/entry_map 全部带可达 file:line 证据；`needs_local_repo_snapshot` 路径被正确处理而非报错给用户。
- **最小必要步数**：约 8 次调用。
- **基线**：待采集。已知坑：跳过本地化会浪费 1-2 次调用。

## G4 find 中英混合 + 代码符号

- **步骤**：①先入库一中一英材料与一个 repo；②用户分别用中文词、英文术语、代码符号（如函数名）`kb find`；③Agent 复述 ≤5 段结果并给 locator。
- **期望**：同语种与 CJK/ASCII 混合 token 命中；不承诺跨语言语义等价（需要时 Agent 原生阅读补充）；rejected unit 不出现。
- **最小必要步数**：每查询 1 次调用。
- **基线**：待采集。失败数目标 0（cache stale 时自动走内存 fallback，不算失败）。

## G5 idea capture → analyze → 讨论归档

- **步骤**：①用户"把这个想法记下来"→ `idea.py capture`；②"分析一下 novelty/可行性"→ analyze prepare，Agent 从冻结 corpus 引证填四条 claim，verify；③陪练讨论一轮（discuss prepare/fill/verify）；④重要路线讨论用 discussion-archivist 归档；⑤review 确认结论。
- **期望**：证据全部来自 `analyze-evidence-corpus.yaml` 清单内 unit；引用清单外材料被拒并触发"链接 unit 后重新 prepare"路径；讨论结论按 conclusion 粒度落库。
- **最小必要步数**：约 8-10 次调用。
- **基线**：待采集。已知坑：corpus 外引用返工一次 ≈ +2 次调用。

## G6 program + 实验两 run → 周报

- **步骤**：①init-program 并挂 idea/unit；②experiment plan（明确本轮假设）；③log-run 两次（不同 seed，构成 repeat group）；④diagnose（可选）；⑤"给我生成周报"→ report weekly；⑥Agent 改写为面向导师的叙事。
- **期望**：两 run 同 fingerprint 不同 seed 记为 repeat 而非重复拒绝；周报含 decisions/claims+evidence/events 三段，未确认判断进隔离区，缺失项显式标注。
- **最小必要步数**：约 7 次调用。
- **基线**：待采集。失败数目标 0（同 seed 重跑需显式 rerun 理由，属预期门而非失败）。

## G7 Obsidian 导出勾选 → 预览 → 原子应用

- **步骤**：①`kb review --obsidian-export` 生成勾选表（含 `kb-review-batch:<hash>` 注释）；②用户在 Obsidian 勾选后回来说"按我勾的处理"；③`--preview-obsidian-batch <hash>` 并向用户复述草稿；④用户当前消息授权；⑤`--apply-obsidian-batch <hash> --expected-preview-digest <digest> …` 原子应用。
- **期望**：勾选只是草稿；预览后表被改动触发 `authorization_stale` 且零写入；应用跨 owner 原子成功。
- **最小必要步数**：3-4 次调用。
- **基线**：待采集。摸索风险点：hash 与 digest 的取值来源（AGENT_GUIDE §3 已固化）。
- **注**：Obsidian 阅读视图人工验收另行按发布门执行，本条只测协议链路。

## G8 undo / restore

- **步骤**：①做一次可逆变更（如 G2 的确认或一次 reject）；②用户"撤销刚才那步"→ `kb undo`；③再连续做两次操作后"回到操作 X 之前"→ `kb restore <操作编号>`；④`kb status` 核对。
- **期望**：恢复只作用于记录的 operation target paths；runtime/投影文件不被误动；undo 后 review 队列与索引一致。
- **最小必要步数**：每恢复 1 次调用 + 1 次核对。
- **基线**：待采集。失败数目标 0。

---

## 采集方法

每轮发布验收跑 G1→G8 各一次（新会话、干净工作区），按统一指标记入下表模板；与上一轮对比"总步数 / 机制摸索 / 耗时"三条曲线。机制摸索连续两轮为 0 时，可将 AGENT_GUIDE 对应小节视为已固化。

| 用例 | 步数 | 失败(其中摸索) | 耗时 | 规则 token | 备注 |
|---|---|---|---|---|---|
| G1… | | | | | |
