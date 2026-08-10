"""Ingestion navigation tests for `docs/DESIGN.md` "对话层与 Agent 协议".

These lock the machine-readable `NEXT FOR AGENT:` navigation lines emitted by the
three analyzers' prepare commands and by intake add. The lines are pure navigation
(what artifact to read, which elements to fill, the exact verify command to run);
they author no judgement. We test the builders directly so the assertions are
deterministic and offline.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from repo_paths import REPO_ROOT, initialize_test_workspace


def _project_root() -> Path:
    return REPO_ROOT


def _load(skill: str, script_name: str, mod_name: str):
    script = _project_root() / "skills" / skill / "scripts" / script_name
    spec = importlib.util.spec_from_file_location(mod_name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


def test_paper_next_for_agent_line_is_machine_readable(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    paper = _load("unit-analyst", "paper.py", "paper_nav_under_test")
    cache = tmp_path / "units" / "papers" / "p-demo-1234" / "parse-cache.yaml"
    fill = tmp_path / "units" / "papers" / "p-demo-1234" / "note-fill.yaml"
    cache.parent.mkdir(parents=True, exist_ok=True)

    line = paper.next_for_agent_note(tmp_path, {"id": "p-demo-1234"}, cache, fill)

    assert line.startswith("NEXT FOR AGENT:")
    # artifact path to read
    assert "kb/units/papers/p-demo-1234/parse-cache.yaml" in line
    assert "kb/units/papers/p-demo-1234/note-fill.yaml" in line
    # Common dimensions and all selected-type additions are explicit.
    assert "common [research_problem,contributions,approach,evaluation_design" in line
    assert "method_system=architecture_mechanism,training_inference,baselines_ablations,failure_scenarios" in line
    assert "benchmark=task_data_construction,metrics_protocol,coverage_bias_leakage,benchmark_reliability" in line
    assert "survey=scope_inclusion,taxonomy,trend_evidence,gaps_disagreement,coverage_limits" in line
    # exact verify command carries the real id + phase + input
    assert "complete-note --paper-id p-demo-1234 --phase verify --input note-fill.yaml" in line
    assert "<id>" not in line


def test_blog_next_for_agent_line_is_machine_readable(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    blog = _load("unit-analyst", "blog.py", "blog_nav_under_test")
    cache = tmp_path / "units" / "blogs" / "b-demo-1234" / "parse-cache.yaml"
    fill = tmp_path / "units" / "blogs" / "b-demo-1234" / "blog-fill.yaml"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("chunks: []\n", encoding="utf-8")

    line = blog.next_for_agent_note(tmp_path, {"id": "b-demo-1234"}, cache, fill)

    assert line.startswith("NEXT FOR AGENT:")
    assert "kb/units/blogs/b-demo-1234/blog-fill.yaml" in line
    assert "[positioning,key_points,credibility,reusable_explanation]" in line
    assert "complete-note --blog-id b-demo-1234 --phase verify --input blog-fill.yaml" in line
    # blogs are web pages: section/anchor locators, no page numbers
    assert "section" in line


def test_repo_next_for_agent_line_is_machine_readable(tmp_path: Path) -> None:
    initialize_test_workspace(tmp_path)
    repo = _load("unit-analyst", "repo.py", "repo_nav_under_test")
    fill = tmp_path / "units" / "repos" / "r-demo-1234" / "capability-fill.yaml"
    fill.parent.mkdir(parents=True, exist_ok=True)

    line = repo.next_for_agent_capability(tmp_path, {"id": "r-demo-1234"}, fill)

    assert line.startswith("NEXT FOR AGENT:")
    assert "kb/units/repos/r-demo-1234/capability-fill.yaml" in line
    assert "[capability,reuse_points,entry_map]" in line
    assert "map-capability --repo-id r-demo-1234 --phase verify --input capability-fill.yaml" in line
    # repo evidence cites real files with file:line locators
    assert "file:line" in line


def test_intake_next_line_points_at_analyzer_prepare_when_standalone(monkeypatch, tmp_path: Path) -> None:
    intake = _load("source-intake", "intake.py", "intake_nav_under_test")
    monkeypatch.delenv("RESEARCH_INGEST_CHAIN", raising=False)

    line = intake.next_for_agent_intake(tmp_path, "paper", "p-demo-1234")

    assert line.startswith("NEXT FOR AGENT:")
    assert "complete-note --paper-id p-demo-1234 --phase prepare" in line
    assert " screen " not in line


def test_intake_next_line_defers_to_chain_when_ingesting(monkeypatch, tmp_path: Path) -> None:
    intake = _load("source-intake", "intake.py", "intake_nav_under_test2")
    monkeypatch.setenv("RESEARCH_INGEST_CHAIN", "1")

    line = intake.next_for_agent_intake(tmp_path, "repo", "r-demo-1234")

    assert line.startswith("NEXT FOR AGENT:")
    assert "auto-continues to repo prepare" in line
    # in-chain, it must NOT tell the agent to run prepare itself (chain does it)
    assert "--phase prepare" not in line


def test_intake_next_line_maps_each_kind_to_correct_prepare_verb(monkeypatch, tmp_path: Path) -> None:
    intake = _load("source-intake", "intake.py", "intake_nav_under_test3")
    monkeypatch.delenv("RESEARCH_INGEST_CHAIN", raising=False)

    paper_line = intake.next_for_agent_intake(tmp_path, "paper", "p-x-1")
    repo_line = intake.next_for_agent_intake(tmp_path, "repo", "r-x-1")
    blog_line = intake.next_for_agent_intake(tmp_path, "blog", "b-x-1")

    assert "complete-note --paper-id p-x-1 --phase prepare" in paper_line
    assert "map-capability --repo-id r-x-1 --phase prepare" in repo_line
    assert "complete-note --blog-id b-x-1 --phase prepare" in blog_line
