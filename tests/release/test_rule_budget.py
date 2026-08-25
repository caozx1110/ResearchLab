from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from repo_paths import REPO_ROOT


def _load_checker():
    path = REPO_ROOT / "tools" / "check_rule_tokens.py"
    spec = importlib.util.spec_from_file_location("v2_rule_budget_checker", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_each_of_five_rule_bundles_fits_the_release_budget() -> None:
    payload = _load_checker().measure_rule_bundles(REPO_ROOT)

    assert payload["encoding"] == "cl100k_base"
    assert payload["limit"] == 8000
    assert payload["discoverable_skill_count"] == 5
    assert payload["passed"] is True
    assert payload["worst_total_tokens"] <= payload["limit"]
