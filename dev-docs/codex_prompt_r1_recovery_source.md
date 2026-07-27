# R1 Track R — recovery / source transaction handoff

## STEP 0 · base sync（必须先做）

1. 在独立 worktree 先核对 `pwd`、clean status、HEAD。
2. 基线必须是 `4a857327f7e3d989bfbd604f6879c3350ea3a6e3`；关键模块 `git_ops.py/journal.py/sources.py/intake.py` 存在。不符 STOP-and-report。
3. 完整阅读根 `AGENTS.md`、主工作区 `temp/SYSTEM_DESIGN_SSOT.md` 的“发布闭环 R1”和本 handoff。

测试解释器用主工作区 `/Users/czx/Documents/rl2lab/projects/vla/workspace-oss/tmp/rvenv/bin/python`；worktree 自身没有 `tmp/rvenv`。

## 目标

把恢复合同从“有 helper”升级为真实 load-modify-write 合同，并修复 source 失败仍建 unit、本地文本无 parse-cache、parse-cache header 错、doctor runtime 假阴性。

## 文件所有权（只动这些）

- `.agents/lib/research/git_ops.py`
- `.agents/lib/research/journal.py`
- `.agents/lib/research/yaml_io.py`
- `.agents/lib/research/common.py`
- `.agents/lib/research/sources.py`
- `.agents/skills/source-intake/scripts/intake.py`
- `.agents/skills/research-config-manager/scripts/config.py`
- `.agents/skills/research-navigator/scripts/serve_kb_browser.py`
- 上述行为专属测试；优先新建 `test_r1_recovery_source.py`。

禁止碰：confirm/evidence/records/analyzers/report/orchestrator、kb-cli/knowledge-base-manager、README/USER_GUIDE/DESIGN、installer/updater/CI/VERSION。

## 必做行为

1. **Scoped checkpoints fail-closed**
   - `git_checkpoint`/`checkpoint_and_report` 对缺失或空 `target_paths` 必须拒绝，不得 `git add -A .`。
   - 手动 checkpoint 若要提交多文件，也必须先解析为明确 dirty path list，再逐 literal pathspec；禁止 broad root。
   - 本轨所有 caller（intake/config/browser-save）传本 operation 的精确 path set。目录可作为该 op 新建的 unit 目录，但不得用整个 `kb/`。

2. **Journal rollback / resume**
   - begin 时为每个 target 保存 before snapshot（存在性 + bytes + mode 或可等价恢复的信息）和 digest。
   - Python 异常触发 abort 时原子恢复 snapshot，再标 abort；进程崩溃留下 begin 时 resume/restore 使用同一恢复 primitive。
   - 新文件在回滚时删除，旧文件恢复原 bytes；失败恢复必须显式报错，不能假成功。
   - snapshots 位于 ignored journal area，绝不进 checkpoint。

3. **共享文件并发安全**
   - `append_program_reporting_event` 等本轨拥有的共享 list load-modify-write 用稳定 file lock，在锁内重新 load、append、atomic write，并 journal。
   - 独立复现 200 concurrent append 全保留；不要靠全局进程内 mutex（多进程也要安全）。

4. **Source transaction / retry**
   - backup/download/parse 成功且 raw/parse-cache ready 后才创建 canonical record。
   - 失败返回非零或显式 failure result；不得创建 active/pending record、不得占 canonical dedup identity。若保留 staging failure，必须置于 intake staging 而非 units，并可用同一 source 重试。
   - rejected/failed legacy unit 不应永久 poison retry；只对有效 canonical unit 判 duplicate。

5. **Local text parse**
   - `.html/.htm/.md/.markdown/.txt` 本地文件生成非空 section parse chunks；HTML 做可靠的文本/section extraction，Markdown/text 至少稳定分段。
   - unsupported binary/file type 明确非零失败。
   - parse-cache 初写统一 header `unit_id`，不要写 `paper_id`；兼容读旧 header 可以，但本轨不得改 analyzer 文件。

6. **Runtime truthfulness**
   - `current_runtime_capabilities/inspect_python_runtime/pdf_backend` 识别默认依赖 `pymupdf4llm`/`fitz`，与 requirements/bootstrap 一致；有默认 backend 时 doctor 数据不得报 `pdf: missing`。

7. **CAS 支撑**
   - 本轨不改 `write_record`（G track 所有），但 journal/lock API 要支持 G track 把 record revision 默认 CAS 接上；避免破坏现有调用面。

## 红线

- 不碰真实 `kb/`；所有写测试 `/tmp`/pytest tmp_path。
- 绝不 `git add -A`，绝不把无关草稿纳入 checkpoint。
- 不用 journal “状态变了”冒充回滚；必须 byte-for-byte 恢复。
- 不吞 source error 后 exit 0。
- 脚本只解析/搬运，不生成材料理解。
- 不 push；commit-per-piece；拿不准跨轨 caller 立即 STOP-and-report。

## 最低测试 / 承重复现

- unrelated dirty draft + op checkpoint：只提交 op paths，draft 保持 untracked/modified。
- empty target paths fail，代码库无 `git add -A .` fallback。
- journaled op 在第 2 个文件写后模拟异常：两文件均恢复 before bytes；新文件被删。
- 多进程/线程 200 reporting events 全保留且 YAML 可读。
- unreachable URL 首次不建 unit；来源恢复后同 URL 可成功重试。
- 本地 HTML/MD/TXT ingest 生成非空 parse-cache 且 header=`unit_id`。
- 实际存在 `pymupdf4llm/fitz` 时 runtime capabilities 报 PDF available。
- 跑定向测试与相关既有恢复/source/installer runtime tests。

## 交付

建议 commits：scoped checkpoint → snapshot rollback/locks → source transaction/local parse/header → runtime truthfulness → tests。最后报告跨轨仍需显式 target_paths 的 caller 列表；不要替其它轨改文件，不 merge/push。
