# 旧布局迁移私有流程

仅当 detector 明确返回 `eligible-legacy`，并且用户在当前消息明确授权迁移时，才按需加载本 reference。普通 install、update、reinstall、`kb init` 或其它 runtime operation 都不得调用 apply。

## 顺序与所有权

1. 先调用 owner-only `scripts/migrate_legacy_layout.py detect`，把结果留在私有 protocol；向用户只说明自然语言状态和迁移指南。
2. `plan` 冻结 workspace、legacy tree、Git HEAD/ref/index、canonical byte digest、安装 manifest/rules 与根用户文件 receipt。Plan 只读且不创建 lock、marker 或恢复目录。
3. 展示适用范围、拒绝原因、备份与回滚后，取得当前用户消息中的明确授权。Agent 不得生成、补写或复用旧授权。
4. `apply` 必须消费原 plan，并同时绑定 `authorization_source=user_message`。任何 identity、digest、Git、journal 或 root bytes 漂移都视为 stale preflight，业务写入前停止。
5. 成功时保留 workspace 同级、权限受限的唯一恢复材料；原 HEAD 是普通 migration commit 的直接父提交。不要删除或上传恢复材料。

## 拒绝与恢复

- `root` 表示无需迁移；`no-layout` 只能走普通 fresh init。
- `partial-ambiguous`、`outer-git`、`collision`、`dirty`、`incomplete-journal`、`symlink`、`special-node` 都不得用 force 绕过。先由用户消除对应条件，再重新 detect/plan。
- apply 中断后只使用 receipt-bound rollback。中途失败恢复原 HEAD、原 layout 和原 bytes；无法完整恢复时保留唯一恢复材料并停止。
- 对已成功迁移的 clean workspace，显式 rollback 先创建普通逆向 commit，再把 canonical entries 与 Git metadata 精确移回 legacy wrapper，并恢复根用户 `.gitignore` bytes。它不重写或丢弃 migration history。

私有 JSON、脚本命令、绝对路径、receipt/digest、故障阶段与恢复材料位置不得进入用户可见输出。公共入口仍只有现有 `kb <verb>`，没有 `kb migrate`。
