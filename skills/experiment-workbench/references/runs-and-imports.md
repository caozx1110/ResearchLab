# Runs and imports

Load only this reference for experiment planning, individual run logging, repeat detection, artifacts, or bounded batch import.

## Run facts

- 每个 run 记录 observed outcome 与 explicit classification tags；outcome 可为 success/partial/failed/blocked/inconclusive。
- Metrics 使用 `{name, value, unit, direction}`；typed input 语义为 `name=value[unit]:direction`，方向限 higher-better/lower-better/neutral/unknown。
- Legacy bare name/value 可兼容：numeric 转 float，non-numeric 保留 string 并 warning。
- 每个声明 artifact 在锁内检查，持久项含 project-relative path、present/missing、generated 与可选 kind；缺失仍可见并 warning。
- Baseline/milestone tags 形成 persistent anchors；后续 run 保存相对最近 run/window/anchors 的 per-metric delta 与 direction-aware better/worse factual comparison。

## Configuration identity and repeats

每个 run 必须显式绑定 config/input revision。Fingerprint 包含 experiment id、normalized hypothesis、sorted normalized changes、metric schema（不含 observed values）、contained artifact identities 与 config revision。

Result prose、timestamps、observed values 和 seed 不改变 configuration fingerprint。不同 seed 共享一个 repeat group；相同 fingerprint+seed 的第二次 run 默认拒绝，只有 Agent 明确 rerun mode 与非空 reason 时允许。Run log/Markdown 同时保存 fingerprint、repeat group/id/index、seed、config revision 与 rerun reason。

Run id allocation、collision check、artifact revalidation 与 write 都在 workspace transaction lock 后完成。禁止 absolute/outside/symlink/special identity。

## Bounded batch import

私有 import 接受 project-contained W&B JSON、stable-header CSV 或 flat `run-*.json` directory。

1. 完整批次先只读 preflight，无 business write。
2. 保存 exact source bytes 到 experiment digest-addressed archive，但 durable provenance 只存 project-relative identity、byte/item/batch digests、source row/file 与可选 external run id。
3. Parsing 只是 factual ETL：显式字段直接映射；numeric summary 变 typed metrics；缺 config revision 时用 canonical config digest；fixed external-state map 只映 observed outcome。
4. 不推断 diagnosis、winner、cause、significance 或 recommendation。
5. Identical item digest 是 idempotent skip；external id 或 fingerprint+seed/config 与不同 bytes 冲突时拒绝整批。
6. Raw archive、所有 run files、shared log/record/event/index 和唯一 checkpoint 必须 all-or-nothing。

用户可见导入结果只总结 imported/skipped/conflict counts 和仍不确定的事实，不输出内部 archive/path/command。
