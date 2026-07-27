你在开源 research-workspace 系统做 **Wave 1 · lib 结构重构（god-file 拆分）**。这是一个**行为保持**的大重构，目的是把 2300 行的 `core.py` 拆成 domain 模块，让后续多个 feature track 能各占一个文件并行开发。**它是"毒丸"——必须先单独做、跑绿、单独 merge 进 main，其余 track 才从新 HEAD 分叉。** 在独立 git worktree 里做。

【红线（不可破）】
1. **行为零变更**。这是纯搬移 + façade 重导出。任何函数的输入输出/副作用都不能变。confirmation gate / provenance / validate_write / 索引 / checkpoint 逻辑一字不改，只换位置。
2. **import 面 100% 兼容**。全仓 `from research.core import X`、`import research.core as core`、`from research.common import Y` 必须全部照旧可用。靠 façade 重导出实现。
3. **绝不碰 kb/**。这是真实用户数据。只动 `.agents/lib/research/` + 必要时 skill 脚本的 import 行。测试在临时目录。
4. **治理红线不动**：禁自签、必留 evidence、AI 判断默认 pending——这些逻辑搬到 confirm.py 后行为必须完全一致。
5. **不 push**。逐模块单独 commit，最后交给维护者 merge。

先读真实文件确认现状：
- `.agents/lib/research/core.py`（2300 行，96 个顶层 def）——通读，标出每个 def 属于哪个 domain。
- `.agents/lib/research/common.py`（root discovery + 工具 + fetch_url/html_to_text）。
- 已存在的 base 模块（**不动，只可被新模块 import**）：`yaml_io.py` `slugs.py` `ids.py` `dedup.py` `pdf_layout.py` `retrieval.py` `bootstrap.py`。
- `.agents/lib/research/tests/`（现有测试，必须全绿）；`pytest.ini`。
- 参考老计划 `temp/OPTIMIZATION_PLAN.md` 的 §3 T-GODFILE-v2（模块划分建议，但以本 handoff 为准）。

============================================================
目标模块结构（从 core.py 切出，flat 模块 + façade）
============================================================
> flat（不建子文件夹）：façade 让内部结构对 importer 不可见，folder 只增 import 路径 churn 无收益；将来某模块过大再拆 folder。

创建以下模块，把 core.py 对应函数**原样搬入**（保留 docstring/注释/行为）：

- `paths.py`   ← project_root / kb roots / record_path / unit dir 解析（core.py:154-236 区）
- `prefs.py`   ← default/load/write_runtime_preferences（含 autonomy 段，core.py:363-543 区）
- `records.py` ← `_record_template`(820) / `normalize_record_schema`(920) / append_history / kind payload skeleton / core_content 定义（593 区）
- `confirm.py` ← `require_confirmation_provenance`(1488) / `_record_needs_gate`(1578) / `validate_write`(1586) / `promote_record`(2561) / apply_confirmation 及相关 gate helper
- `index.py`   ← `build_index`(1938) / rebuild_governance_catalogs / apply_record_governance
- `sources.py` ← `_is_html_response`(2280) / `backup_source`(2295) / source 解析（Wave 2 的 dual-source track 会扩展它，此处只搬原逻辑）
- `git_ops.py` ← ensure_kb_git_repo / maybe_auto_checkpoint / checkpoint_and_report / git_checkpoint
- `evidence.py` ← **新建**（不是搬移）：只放 Wave 2 要用的 schema 骨架——evidence_refs 的常量/dataclass + 一个 `verify_claim_evidence(claim, unit_dir) -> list[str]` **stub（先返回 []，不做真校验）** + `EVIDENCE_SCHEMA` 说明。**行为上是 no-op 附加模块**，给 Wave 2 evidence track 一个落点。schema 规格见 SSOT Part 2 原则 2 的锁定 YAML 块，一字不差落进 SCHEMAS.md 的新「Evidence / Claims」节。

`core.py` **瘦成 façade**：顶部 `from .paths import *` / `from .records import *` / `from .confirm import *` / `from .index import *` / `from .sources import *` / `from .prefs import *` / `from .git_ops import *` / `from .evidence import *`（按依赖序），保证所有旧 import 符号可达。`common.py` 同理，若有 domain 逻辑外移则 façade 重导出。

============================================================
硬性执行纪律
============================================================
- **逐模块搬**：搬一个模块 → 跑全量 pytest 绿 → `python -m compileall .agents/skills .agents/lib` 过 → commit（如 `refactor(lib): extract paths.py from core`）→ 再搬下一个。不要一次全搬完才测。
- **无循环 import**：分层 base(yaml_io/slugs/ids/dedup) ← domain(paths/prefs/records/confirm/index/sources/git_ops/evidence) ← façade(core/common)。若出现循环，把共享的小工具下沉到 base 或 paths，不要靠延迟 import 糊。
- **evidence.py 是纯附加**：它的存在不改变任何现有行为；只有 SCHEMAS.md 加一节 + 新模块文件 + 一个 no-op stub + 一个 stub 的单元测试。
- 每搬一个模块，若该模块内部有老计划 §4.2 提到的重复（如 `_accumulate_catalog` 3×55 行、`_coerce_num` 8 处），**可顺手合并，但前提是行为字节级不变**（有测试锁）；拿不准就先纯搬、不动内部。

============================================================
验证（全绿再交，逐条给实际输出）
============================================================
1. 全量 `pytest .agents/lib/research/tests -q` 与重构前**同样绿**（数量不减；若因文件移动需改测试 import 路径，改到新路径，但断言不放宽）。
2. `python -m compileall .agents/skills .agents/lib install-lib` 通过。
3. import 面回归：`grep -rnE "from research\.(core|common) import|import research\.(core|common)" .agents/skills` 列出的每个符号，起一个 python 进程实测 `from research.core import <symbol>` 成功（脚本化跑一遍，贴结果）。
4. 无循环 import：`python -c "import research.core, research.common"` 干净通过。
5. 行为保持抽样：对一个临时 KB 跑 `kb init` + 一次 intake add + screen + review-queue，输出与重构前一致（贴 diff 证明无行为变化）。
6. evidence.py：`from research.evidence import verify_claim_evidence, EVIDENCE_SCHEMA` 成功；stub 返回 []；SCHEMAS.md 有「Evidence / Claims」节且 YAML 与 SSOT 锁定块一致。
7. kb/ 零改动：`git status` 显示无任何 kb/ 下改动。

【交付】逐模块 commit、不 push。交付说明附：最终 core.py 行数（应大幅下降）、各新模块行数、pytest 前后数量、import 面回归实测结果、行为保持抽样 diff。**若某个函数跨 domain 难以干净归类，停下来在交付说明里列出并给出你的建议，不要硬塞。**
