# R18 literature-search 本地产品验收（2026-07-25）

范围：当前集成分支 `773939e`；所有操作均在 `/tmp/r18-literature-acceptance.*` 的隔离副本，未读取或写入真实 `kb/`。shipping skill 只作为被测产品源码。

## 已实际跑通

1. 聚焦回归：`test_literature_search`、`test_literature_selection_adapter`、`test_agent_next_selection`、`test_intake_commands`、`test_intake_prepared_snapshot_security`、`test_find_next_hint_mainline`，共 **229 passed**。
2. 单独兼容/恢复回归：旧 OpenAlex 只读 DOI 形态可继续并规范化、旧 stage 在 orchestrator 枚举中可生成选择项、真实 `source-intake` duplicate owner 路径、重复 selection 不重跑 owner，合计 **5 passed**。
3. 隔离副本的真实子进程路径（非 mock）：构造一项完整的 terminal literature stage 与已经存在的 canonical paper，再调用 `materialize_selection`。
   - 首次选择：`新入库 0、关联已有条目 1、此前已完成 0`；stage 候选写成 `duplicate`，并准确绑定既有 record。
   - 同一 display binding 用新 protocol 名重复提交：`新入库 0、关联已有条目 0、此前已完成 1`；未重复 materialize。
   - 两次用户可见消息均为中文自然语言，只包含允许的 `kb next`，未含路径、参数、`NEXT FOR AGENT` 或 owner 输出。
4. 隔离副本 `kb status` 与 `kb next` 也可执行，且旧 DOI 兼容测试确认该兼容仅作为历史 stage 的只读身份迁移，不会重新引入 OpenAlex 检索源。

## 可复现 UX 问题

### P2：`kb status` 与 `kb next` 对同一工作区给出表面矛盾的工作量判断

复现：完成上述一项 candidate → existing-record 的选择后，在同一隔离根依次执行 `kb status`、`kb next`。

实际公共输出：

```
待处理事项：0 条待确认判断、0 个到期监控、0 组文献候选待选择、0 个可继续文献检索、0 个可恢复综述流程、0 个失败后可重试事项。
Agent 需要比较当前 1 项可行行动，再说明为什么选择下一步。
```

前一句把所有“待处理事项”报为 0，后一句却说明当前有 1 项可行行动。实现上，`status` 的分类计数不覆盖“刚入库资料需要后续分析”的 portfolio action，而 `next` 正确发现了该 action；机器协议仍有完整私有候选信息，因此不是数据丢失或恢复失败。

影响：对用户而言，“已没有待处理事项”紧接着“有 1 个下一步”不易理解；选择成功消息又明确建议继续 `kb next`，会放大这种困惑。

建议：在 status 的事实摘要中单列一个不泄漏 ID 的计数，例如“1 项资料后续分析/研究规划待 Agent 推进”，或把该句改为“治理闸口待处理事项：0 …；另有 1 项可由 Agent 继续推进的工作”。同时把 `kb next` 的通用句补成“Agent 将比较 1 项可行行动，并继续推进资料分析”，仍不暴露内部候选或决策协议。

## 结论

候选展示绑定→用户授权→source-intake owner→重复恢复、旧 DOI stage 兼容均通过；没有发现阻断文献选择、中文输出、恢复或来源入库的功能问题。上述 P2 是可独立修复的公共 UX 一致性问题。
