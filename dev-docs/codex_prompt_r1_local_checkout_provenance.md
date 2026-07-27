# R1 local-checkout provenance handoff

## STEP 0 — base sync

Worktree 必须以 integration HEAD `5d5c7ec4a463e4ef6bf2067df76301d9c3af407a` 为 base。先核对 HEAD/关键模块；若不符 STOP-and-report，不要 reset 用户工作树。

## 目标

修复 fresh copy install 从本地 Git checkout/linked worktree 发起时丢失 `source_checkout`、随后 `kb update` 错走远端的问题。实现 SSOT 的“本地 checkout 仍绑定本地 checkout”，同时保留 origin/branch/commit 的可追溯性和既有 remote-branch 更新能力。

## 文件所有权（只动这些）

- `install.sh`
- `install-lib/ws_sync.py`
- `.agents/lib/research/updater.py`
- `.agents/lib/research/tests/test_installer.py`
- `.agents/lib/research/tests/test_updater.py`
- 如确有必要，`.agents/lib/research/tests/test_bundle_lifecycle.py`

不要改 kb wrapper、records/classifier、evidence、git_ops、文档/SSOT/BACKLOG。

## 锁定设计

1. 从本地 checkout 或 linked worktree 运行 `install.sh` 时，manifest 必须始终记录安装时的 lexical `source_checkout`，无论它有没有 remote；另存 `source_origin/source_branch/source_commit` 供溯源。
2. 新增 additive manifest provenance 字段（建议 `source_strategy`）：fresh local invocation 固定 `local-checkout`。updater 在此策略且 checkout 有效时只读取当前工作树版本/文件，严禁 fetch/pull/network；尚未 push 的分支仍可 check/apply。
3. local checkout 缺失或不再是合法 source 时 fail-closed `needs_source_choice`，不得静默 fallback 到 origin/cache/main。
4. 只有显式 `remote-branch` 策略可 fetch/pull/clone origin+branch。为兼容旧 manifest：已有 `origin+branch` 且无 strategy 的历史语义保持 remote-branch；`origin=local + checkout` 可归为 local-checkout。不要把所有 legacy manifest 猜成本地策略。
5. linked worktree 的 `.git` 是文件，必须被识别为 Git checkout；checkout path 的解析/验证不能误拒绝。
6. update/reinstall 写回 manifest 时保持策略；`ws_sync.py` 的策略参数必须有受限 choices/default，不能接受任意字符串。SemVer 单调门、drift、安全卸载不变。

## 必须新增/强化的回归

- fresh guided/project install 从普通 checkout 与 linked worktree 发起：manifest checkout 是实际源路径，strategy=local-checkout，同时 origin/branch/commit 正确。
- `updater.check/apply` 对 local-checkout remote-origin 的未发布分支零 fetch/pull/clone；读取本地版本并只在版本递增时 sync。
- checkout 消失/失效 → needs_source_choice、零 remote fallback。
- legacy remote manifest 与显式 remote-branch 仍按 origin+branch fetch/pull；无 provenance 仍 fail-closed。
- detached/local/tar-like source 与现有 installer smoke 不回退；若 detached 的更新策略按现有合同需选择，保留该门。

## 红线

- 不碰真实 `kb/`；只 tmp_path。
- 不访问网络；测试用本地 bare remote/monkeypatch。
- 不削弱 SemVer、drift、source containment 或 uninstall 边界。
- 不 push；小步 commit-per-piece；拿不准 STOP-and-report。

## 验收与交付

定向 installer/updater tests、全量 pytest、compileall、bash -n install.sh、`git diff --check`、worktree clean。报告普通 checkout + linked worktree 黑盒 manifest 与零网络 probe、commit SHA 和测试计数。
