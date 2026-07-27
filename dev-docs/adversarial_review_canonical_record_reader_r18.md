# Canonical record reader 独立对抗性审查（R18）

## 范围与结论

- 审查对象：`056fa5b fix(records): harden canonical record reads` 与 `cb3efd2 fix(records): stabilize legacy snapshot normalization`，以及它们和 review/status/find/survey/intake 的交互。
- 审查起点：集成分支 `codex/review-remediation-integration` 的 `a1ebee6`。完成审查时共享分支已前进到 `4bfb9c2`；`a1ebee6..4bfb9c2` 仅改 installer/schema 相关文件，没有改本报告涉及的 `records.py`、`index.py`、`judgements.py`、`surveys.py`、`sources.py`。
- 所有攻击复现均在 Python `TemporaryDirectory` 中完成；没有读取或修改真实 `kb/`。
- 没有调用 shipping skill 作为设计或验收依据；没有编辑产品文件。
- 结论：确认 4 个问题（3 个 P1，1 个 P2）。严格 YAML、FIFO、已覆盖的 ancestor replacement 和 legacy clock 稳定性测试均通过，但当前实现还不能宣称完成“单坏记录隔离”和“从 record 到下游 artifact 的端到端路径锚定”。

## Findings

### [P1] `trusted_unit_record_path()` 把已验证 snapshot 降级成可被祖先替换的普通路径

**位置**

- `.agents/lib/research/records.py:347-359`：`trusted_unit_record_path()` 从安全 snapshot 中取出 `snapshot.path`，随后只返回普通 `Path`。
- `.agents/lib/research/records.py:375-412`：`trusted_claim_source_roots()` 的跨 unit 分支直接使用 `trusted_unit_record_path(...).parent`。
- `.agents/lib/research/judgements.py:183`：review/evidence 验证消费这些 source roots。

**影响**

严格 reader 验证过的是某一时刻 descriptor 指向的 record 字节；返回的 lexical `Path` 不是能力句柄。攻击者可在 snapshot 枚举完成后、调用方使用 `.parent` 前，把原 unit 目录改名并在同一路径放入指向工作区外目录的 symlink。`trusted_claim_source_roots()` 会把这个工作区外目录当成可信 evidence root，后续 review/evidence 校验可能读取外部字节。函数的“without aliases or symlink traversal”契约因此不成立。

**临时目录复现**

1. 在临时 workspace 创建合法 source unit `p-source-123456` 及 `raw/source.txt`。
2. 在 workspace 外创建另一目录，放入同名 `record.yaml`，并令 `raw/source.txt` 内容为 `EXTERNAL_SECRET`。
3. 包装 `iter_canonical_record_snapshots()`：先调用原实现取得 snapshot；在返回给 `trusted_unit_record_path()` 前，把合法 unit 目录移走，并在原 lexical 位置创建指向 outside 的 symlink。
4. 调用 `trusted_claim_source_roots()` 解析 consumer record 的 cross-unit evidence ref。

观察值：

```text
ROOT .../ws/kb/units/papers/p-source-123456
RESOLVED .../outside
BYTES EXTERNAL_SECRET
```

**修复建议**

不要把 `Path` 当作安全读取能力返回。review/evidence 层应消费由 anchored directory descriptors 读取出来的 artifact snapshot（bytes + digest + canonical identity），或持有已锚定目录句柄直到 artifact 读取完成，并在发布判断前复核完整 root→unit chain。单独再做一次 `Path.resolve()` 仍有下一次 TOCTOU 窗口，不能作为完整修复。

### [P1] public find 在 record 安全读取后会重新用未锚定祖先读取 Markdown，可泄漏工作区外内容

**位置**

- `.agents/lib/research/index.py:293-312`：`_unit_markdown_paths()` 从 record 字段重新构造 lexical unit path。
- `.agents/lib/research/index.py:520-538`：`_safe_files_below()` 先做路径/类型检查，再返回普通路径。
- `.agents/lib/research/index.py:541-564`：`_read_regular_bytes()` 的 `O_NOFOLLOW` 只保护最终文件分量，不保护祖先目录。
- `.agents/lib/research/index.py:593-669`：`passage_corpus()` 分阶段枚举并重新读取 record/Markdown/parse-cache。
- `.agents/lib/research/index.py:1525-1560`：`search_passages()` 将上述 corpus 用于公开查询回退。

**影响**

record 虽然先由 `iter_records()` 的 strict snapshot 安全读取，但 passage 构建没有继承该 snapshot 的锚定能力。在 `_path_has_symlink_component()` / 枚举完成后、`os.open(path, O_NOFOLLOW)` 前替换 unit 祖先目录，最终文件本身不是 symlink，因而仍会沿祖先 symlink 打开 workspace 外 Markdown。公开 `kb find`/query UX 会显示外部内容。

**临时目录复现**

1. 创建合法 paper `p-race-123456`，unit 内 `note.md` 为 benign 内容。
2. 创建 workspace 外目录，放同名合法 record 与 `note.md`，外部笔记含 `TOPSECRET_PUBLIC_TOKEN`。
3. 包装 `research.index._read_regular_bytes()`：当目标第一次为 `note.md` 时，把 unit 目录改名，然后在原路径建立指向 outside 的 symlink，再调用原 reader。
4. 调用 `search_passages()`，并通过公开 find handler 输出结果。

观察值：

```text
RC 0
找到 1 段相关内容：
- 论文「Safe title」（p-race-123456）
  定位：External，第 2–2 行
  摘录：TOPSECRET_PUBLIC_TOKEN
```

**修复建议**

让 passage 构建从 canonical record snapshot 获得同一条已锚定 unit 能力，并用逐级 `openat`/dirfd 读取 Markdown 与 parse-cache；将字节、digest、artifact identity 一次性封装成不可变 snapshot 后再交给检索/展示。发布结果前复核完整祖先链。不能只给 leaf 加 `O_NOFOLLOW`。

### [P1] 一个类型错误的合法 YAML record 会让 status/find/survey/intake 全部崩溃，未实现单坏记录隔离

**位置**

- `.agents/lib/research/records.py:1133-1137`：`iter_records()` 无 per-record 异常隔离。
- `.agents/lib/research/records.py:1140-1174`：`_normalized_snapshot_record()` 只捕获 `SystemExit`；`normalize_record_schema()` 的普通类型异常会向外传播。
- `.agents/lib/research/index.py:1515-1522,1535`：find/status/index 消费全量 `iter_records()`。
- `.agents/lib/research/surveys.py:1219`：survey 路由消费 `iter_records()`。
- `.agents/lib/research/sources.py:4764`：intake duplicate detection 消费 `iter_records()`。

**影响**

严格 YAML loader 只保证语法/唯一 key，不保证字段类型。一个 record 写成 `information_types: 7` 会让 normalize 执行 `list/int` 相关逻辑时报 `TypeError: 'int' object is not iterable`。异常中止整次枚举，合法 sibling 也消失；status、find、survey 选材、intake 去重均不可用。公开 status 路径还会直接泄漏 Python `TypeError`，没有恢复性中文提示。

**临时目录复现**

在同一临时 workspace 创建：

- 合法 sibling：`p-good-123456`；
- 坏 record：`p-bad-123456`，其余结构合法，仅把 `information_types` 设为整数 `7`。

分别调用 `iter_records()`、`search_records()`、`select_current_confirmed_survey_records(root, iter_records(root))`、`detect_duplicate()`，以及公开 status handler。观察值：

```text
iter/status EXC TypeError 'int' object is not iterable
find EXC TypeError 'int' object is not iterable
survey EXC TypeError 'int' object is not iterable
intake_duplicate EXC TypeError 'int' object is not iterable
STATUS_EXC TypeError 'int' object is not iterable
```

**修复建议**

将 schema normalization 做成对任意 YAML mapping 都是 total 的边界，或在每个 snapshot 周围捕获明确的可恢复 schema/type 异常并只隔离该 record，同时产生私有诊断。不要吞掉 `KeyboardInterrupt`/`GeneratorExit`。也不应在 normalize 失败时把任意 raw malformed payload 当作正常 record 返回；下游依赖的是 canonical normalized schema。

建议新增一组参数化 malformed-type fixture，分别断言 review/status/find/survey/intake：合法 sibling 仍可见、坏 record 被隔离、公共输出没有 traceback/内部路径。

### [P2] mtime 纳秒被转成 epoch float，`locate_record("last")` 可能选中较旧记录

**位置**

- `.agents/lib/research/records.py:1208-1220`：`safe_modified_time_ns / 1_000_000_000` 被作为 `float` 排序键。

**影响**

当前 epoch 量级的 IEEE-754 float 无法区分 1ns 差异。当多个 record 的 canonical timestamps 相同，mtime 第一排序键发生碰撞，最终由 ID 字典序决胜，`last` 可能返回更旧记录。这是 legacy normalize 稳定化后暴露出的确定性精度错误。

**临时目录复现**

创建两个 timestamps 完全相同的 paper，并精确设置：

```text
p-zolder-123456 mtime_ns=1800000000000000000
p-anewer-123456 mtime_ns=1800000000000000001
```

观察值：

```text
[('p-anewer-123456', 1800000000000000001, 1800000000.0),
 ('p-zolder-123456', 1800000000000000000, 1800000000.0)]
LOCATED p-zolder-123456
```

**修复建议**

排序键第一项直接保留整数 `safe_modified_time_ns`，类型改为 `tuple[int, float, str]`；不要先缩放成 float。补 1ns 差异回归测试。

## 已撤销的假警报 / 通过项

- strict unique-key loader 能拒绝顶层、嵌套以及 YAML merge-key 展开后的重复 key；没有报告 duplicate-YAML 漏洞。
- FIFO 读取能及时返回；socket、directory、oversize sibling 被隔离。
- 现有 root/kb/units/kind/unit ancestor replacement 测试全部通过。这里的两个路径 finding 是“snapshot 返回之后、下游重新把 lexical path 当能力使用”的新窗口，不与既有测试结论矛盾。
- legacy record 在 mock `utc_now_iso` 改变时仍得到稳定 normalization；没有报告 clock 漂移回归。
- 简单 cyclic YAML payload 被隔离为无记录，未复现全局崩溃，故撤销。
- kind 目录扫描期间发生变动只复现到 partial scan，没有形成可证明的安全/治理破坏，故不报告。

## 独立回归

```text
$ pytest -q .agents/lib/research/tests/test_strict_record_reader.py
..........................                                               [100%]
26 passed in 0.77s
```

上述通过说明 `056fa5b`/`cb3efd2` 已覆盖的 happy path 与显式 race fixture 仍然有效；它不覆盖本报告的 downstream capability handoff、malformed-type isolation 与 1ns ordering cases。
