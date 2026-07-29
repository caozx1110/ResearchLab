from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from repo_paths import REPO_ROOT


def _load_checker():
    path = REPO_ROOT / "tools" / "check_rule_tokens.py"
    spec = importlib.util.spec_from_file_location("rule_token_budget_checker", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_every_discoverable_skill_rule_bundle_fits_fixed_budget() -> None:
    checker = _load_checker()
    payload = checker.measure_rule_bundles(REPO_ROOT)

    assert payload["encoding"] == "cl100k_base"
    assert payload["limit"] == 8000
    assert payload["discoverable_skill_count"] == 15
    assert payload["passed"] is True, [
        (row["skill"], row["total_tokens"])
        for row in payload["bundles"]
        if not row["within_limit"]
    ]
    assert payload["worst_total_tokens"] <= payload["limit"]


def test_checker_reads_complete_utf8_files(tmp_path: Path, monkeypatch) -> None:
    checker = _load_checker()
    root = tmp_path
    (root / ".agents" / "skills" / "demo").mkdir(parents=True)
    (root / ".agents" / "AGENTS.md").write_text("全局规则\n", encoding="utf-8")
    (root / ".agents" / "AGENT_GUIDE.md").write_text("机制指南\n", encoding="utf-8")
    skill = root / ".agents" / "skills" / "demo" / "SKILL.md"
    skill.write_text("---\nname: demo\n---\n完整代码块 `--flag`。\n", encoding="utf-8")

    class ExactEncoding:
        def encode(self, text: str):
            return list(text.encode("utf-8"))

    monkeypatch.setattr(checker.tiktoken, "get_encoding", lambda name: ExactEncoding())
    payload = checker.measure_rule_bundles(root, limit=10_000)

    expected = sum(
        len(path.read_text(encoding="utf-8").encode("utf-8"))
        for path in (
            root / ".agents" / "AGENTS.md",
            root / ".agents" / "AGENT_GUIDE.md",
            skill,
        )
    )
    assert payload["bundles"][0]["total_tokens"] == expected
