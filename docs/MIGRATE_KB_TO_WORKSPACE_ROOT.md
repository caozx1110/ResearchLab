# 旧知识库迁移已退役

本页保留为旧 ADR 和历史链接的稳定落点，不再描述可执行流程。

Research Vault v2 是不兼容 hard cutover。当前产品不读取、迁移、移动、改写或删除旧 `kb/`、`record.yaml` canonical、旧 workspace-root marker 或 `obsidian/managed/` 数据，也不发布旧 migration runtime。

安装器或 v2 runtime 检测到旧布局时会在写入前停止。请保留并备份原工作区，在新的空目录中初始化 v2；不要手工移动旧目录、修改安装 manifest 或寻找未发布的迁移命令。当前产品不发布迁移工具，也不在源码树中保留可调用的 v1 migration 实现。

未来若需要一次性导入，必须通过新的 Blueprint、ADR 和 Atomic Issue 重新定义 selection boundary、只读解析、备份、dry-run、current-message authorization、rollback 和 clean-vault acceptance。该未来合同不得恢复 v1/v2 dual-read、dual-write 或长期兼容路径。
