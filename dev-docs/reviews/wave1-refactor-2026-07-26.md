# Wave 1 重构施工报告（2026-07-26）

6 个并行 subagent（各自独立 git worktree track 分支）+ 主控合并与全局冒烟。**42 个文件变更，+2686/−152 行**，全部已写回工作区（未 git commit——请先跑完整测试套件再提交）。

## 各轨完成内容

**A1 安装与依赖（M1 两个阻断）**
- ws_sync 失败不再吞错：中文首行 + stderr 追加子进程输出末 8 行；非 git 源给出定向指引（git clone / git init 三步 / `--from-snapshot` 快照打包 opt-in，快照与 git 安装 tree_checksum 一致）。
- PDF 依赖三方对齐：bootstrap 兼容性探测纳入 pymupdf4llm+fitz，缺失时走 managed venv 准备（失败优雅降级）；doctor 诚实播报"论文 PDF 深读能力未就绪，首次需要时自动准备"；intake 失败消息带自动准备提示。主控追加：**准备失败 1 小时节流**，避免每次 kb 调用重试刷屏。

**A2 对话面（M2）**
- kb help 每行带动词本名；kb undo 点名撤销对象；kb restore 无参列出最近 10 个操作（编号可直接用于 restore）。
- review apply 失败时私有协议携带 `review_apply_failure`：原因码、当前快照合法 confirm-ref 列表、正确文件名、token 误传检测、精确语法——Agent 可自修复。
- kb init 新增两问：`--auto-ingest-mode ask_first|auto_deep_read`（链接自动化档位）与 `--discussion-style challenge|refine|adaptive`（讨论风格），落 canonical 配置，重复 init 零 churn；config.py 新增 set-interaction。
- config.py：record-effective 接受 JSON 文件路径；eligible-preferences 错误一行化（不再裸 traceback）。
- kb-cli SKILL.md 增"Agent 调用速查"。

**A3 owner 脚本（M2）**
- idea.py 静默失败清零：所有 verify 失败带一行中文原因；`--input` 三级解析（unit 相对/仓库相对/绝对）+ 找不到列出尝试位置；corpus 违规列出全部可引用 unit + 扩语料方法。
- orchestrate.py：prepare-next-selection 产出预填草稿（digest/scope/候选/偏好上下文全现成，Agent 只填 3 个理由字段）；新增 `governance_profile: personal|strict`（缺省 strict 完全不变）——personal 档 procedural 决策免偏好回执，脚本兜底强制硬约束。kb next 决策循环从 9 步降到 2-3 步。
- monitor.py 新增 template 子命令（带注释订阅模板）；apply 兼容 YAML。

**A4 校验强度（M3）**
- **locator 位置校验落地**：line=N 必须与 quote 实际行匹配、section:<anchor> 必须存在且 quote 在该 chunk 内，失败提示实际位置；未知形态告警放行（不炸老数据）。对抗用例全部拦截。
- kb reject 后 record.status=rejected（语义一致）。
- audit 修 INTEGRITY_PROGRAM_LINK 误报（正向边设计对齐）；正常流程 audit 由 FAIL 转 PASS。
- experiment plan/log-run：中文结果行 + checkpoint（dirty 警告清零）。

**A5 代码检索（G14）**
- repo 源码进 FTS5：.py 按 def/class 符号切块（带符号名），其他 40 行窗口；跳二进制/超大/VCS 目录，超限显式告警；驼峰/下划线拆词辅助列。
- `kb find ConsistencyRefiner` → 返回"src/m.py · class ConsistencyRefiner，第 1–2 行"式代码段与 Markdown 混排；缓存损坏只读回退不变；调度器零改动。

**A6 接口层文档（M2）**
- 新建 `.agents/AGENT_GUIDE.md`（8.3KB ≈2.4k tokens）：全部机制速查（协议 flag 位置、apply 语法、batch_ref/digest 来源、fill/verify 惯例、corpus 规则、16 动词→脚本对照、失败恢复表）+ 交互章程 10 条。
- 19 份 SKILL.md 各加"启动澄清（Agent 用）"（每份 ≤600B）；AGENTS.md/README/USER_GUIDE 引用；新建 docs/GOLDEN_SUITE.md（8 条黄金对话规格+基线指标）。skill_validator 20/20 通过。

## 全局冒烟（合并后干净环境实测通过）

安装→init（新两问落盘）→help 带动词→ingest blog+repo→错误 locator 被拦截并提示实际位置→修正后通过→find 命中符号级代码段→review 错误 ref 时协议给出合法 ref 清单→正确 apply→personal 档草稿式 kb next 决策→experiment 双 run 带 checkpoint→audit 0 errors→weekly→undo 点名→restore 列表→idea corpus 违规消息列出可引用清单。

## 已知未尽（下一轮）

- **测试套件未跑**（沙箱装不上 pytest）：请在本机 `source .venv/bin/activate && python -m pytest .agents/lib/research/tests -x -q`。各轨报告已列出需同步的旧断言：test_kb_cli_dispatcher（doctor 旧文案、init quick_fields 精确相等断言需加两个新字段）、test_bootstrap、test_installer 等。
- A1 doctor 话术改动物理上落在 kb 调度器（约 20 行，越界已声明）；`[root] project:` 绝对路径行仍在（等测试套件同步时统一改）。
- 未动：快筛移除、analyst 合并、navigator/wiki 摘除、tests 搬迁（都需要测试套件护航）；G13 概念页、G1 bib、G4 实验导入、周报编辑层（Wave 2）。
- SCHEMAS.md 需按 A3/A5 报告增补三段（governance_profile、选择草稿、代码 passage 说明）——建议随 Wave 2 一起。

## 建议的下一步

1. 本机跑完整测试套件，把失败清单发我（预期主要是文案断言漂移，我来同步）；
2. 套件绿后 git commit（42 文件 + dev-docs/）；
3. Wave 2：G13 概念页、G1 bib、G4 实验导入、周报编辑层 + 测试断言同步。
