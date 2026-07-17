from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from research.common import load_yaml, write_yaml_if_changed
from research.core import default_record, ensure_workspace, record_path


def _project_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _load_method_module():
    script = _project_root() / ".agents" / "skills" / "method-designer" / "scripts" / "method.py"
    spec = importlib.util.spec_from_file_location("method_designer_script_for_tests", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _make_workspace(tmp_path: Path, *, resources: dict | None = None) -> tuple[Path, str, str]:
    root = tmp_path
    (root / ".agents").mkdir()
    (root / "AGENTS.md").write_text("# test\n", encoding="utf-8")
    ensure_workspace(root)
    idea_id = "i-method-123456"
    repo_id = "r-method-123456"
    idea = default_record("idea", title="Resource-aware method", maturity="lightweight", source={"original_uri": "discussion"})
    idea["id"] = idea_id
    idea["status"] = "selected"
    idea["payload"]["hypothesis"]["core_hypothesis"] = "A small adapter improves recovery."
    idea["payload"]["hypothesis"]["key_mechanism"] = "adapter recovery"
    idea["payload"]["analysis"]["minimum_validation_path"] = "Run the adapter against the repo baseline."
    write_yaml_if_changed(record_path(root, "idea", idea_id), idea)
    repo = default_record("repo", title="Adapter recovery repo", maturity="lightweight", source={"original_uri": "https://example.com/repo"})
    repo["id"] = repo_id
    repo["summary"] = "Adapter recovery baseline implementation."
    repo["payload"]["structure"]["entrypoints"] = ["train.py"]
    write_yaml_if_changed(record_path(root, "repo", repo_id), repo)
    if resources is not None:
        write_yaml_if_changed(root / "kb" / "config" / "user-profile.yaml", {"resources": resources})
    return root, idea_id, repo_id


def _run_design(method, monkeypatch, root: Path, idea_id: str, program_id: str = "p-method") -> int:
    monkeypatch.setattr(method, "PROJECT_ROOT", root)
    monkeypatch.setattr(
        sys,
        "argv",
        ["method.py", "--root", str(root), "design", "--idea-id", idea_id, "--program-id", program_id],
    )
    return method.main()


def _matrix(root: Path, idea_id: str, program_id: str = "p-method") -> dict:
    return load_yaml(root / "kb" / "programs" / program_id / "design" / f"{idea_id}-experiment-matrix.yaml", default={})


def test_method_defaults_to_legacy_scale_without_declared_resources(tmp_path: Path, monkeypatch) -> None:
    method = _load_method_module()
    root, idea_id, _ = _make_workspace(tmp_path)

    assert _run_design(method, monkeypatch, root, idea_id) == 0

    matrix = _matrix(root, idea_id)
    scales = {row["kind"]: row["scale"] for row in matrix["experiments"]}
    assert scales == method.DEFAULT_EXPERIMENT_SCALE
    assert all(row["feasibility"] == "unknown" for row in matrix["experiments"])
    assert matrix["resource_requests"] == []


def test_method_scales_down_and_flags_over_budget_row(tmp_path: Path, monkeypatch, capsys) -> None:
    method = _load_method_module()
    resources = {"local_gpu": "1 GPU with 24 GB VRAM"}
    root, idea_id, _ = _make_workspace(tmp_path, resources=resources)

    assert _run_design(method, monkeypatch, root, idea_id) == 0

    matrix = _matrix(root, idea_id)
    rows = {row["kind"]: row for row in matrix["experiments"]}
    assert rows["main"]["scale"]["seed_count"] == 1
    assert rows["main"]["scale"]["model_size_tier"] == "small"
    assert rows["diagnostic"]["feasibility"] == "unrealistic"
    assert rows["diagnostic"]["status_color"] == "red"
    assert "Requires 2 GPUs but profile declares 1" in rows["diagnostic"]["feasibility_reason"]
    assert matrix["resource_requests"]
    assert "Resource request:" in capsys.readouterr().out
    state = load_yaml(root / "kb" / "programs" / "p-method" / "state.yaml", default={})
    assert state["resource_constraints"] == resources


def test_method_scales_up_for_generous_resources(tmp_path: Path, monkeypatch) -> None:
    method = _load_method_module()
    root, idea_id, _ = _make_workspace(tmp_path, resources={"cluster": "8x A100 GPUs with 80 GB each"})

    assert _run_design(method, monkeypatch, root, idea_id) == 0

    matrix = _matrix(root, idea_id)
    rows = {row["kind"]: row for row in matrix["experiments"]}
    assert rows["main"]["scale"] == {"seed_count": 5, "model_size_tier": "large", "parallelism": 4, "required_gpus": 1}
    assert rows["diagnostic"]["scale"]["seed_count"] == 5
    assert all(row["feasibility"] == "feasible" for row in matrix["experiments"])
    assert matrix["resource_requests"] == []


def test_method_prefers_program_active_repo_corpus(tmp_path: Path, monkeypatch) -> None:
    method = _load_method_module()
    root, idea_id, kb_repo_id = _make_workspace(tmp_path)
    active_repo_id = "r-program-654321"
    active_repo = default_record("repo", title="Program attached repo", maturity="lightweight", source={"original_uri": "https://example.com/active"})
    active_repo["id"] = active_repo_id
    active_repo["summary"] = "The program-selected implementation corpus."
    write_yaml_if_changed(record_path(root, "repo", active_repo_id), active_repo)
    write_yaml_if_changed(
        root / "kb" / "programs" / "p-method" / "state.yaml",
        {"program_id": "p-method", "stage": "idea-review", "active_unit_ids": [idea_id, active_repo_id]},
    )

    assert _run_design(method, monkeypatch, root, idea_id) == 0

    choice = load_yaml(root / "kb" / "programs" / "p-method" / "design" / f"{idea_id}-repo-choice.yaml", default={})
    assert choice["selected_repo_id"] == active_repo_id
    assert [item["repo_id"] for item in choice["candidate_repos"]] == [active_repo_id]
    assert kb_repo_id not in choice["candidate_corpus"]["repo_ids"]
    assert choice["candidate_corpus"]["scope"] == "program-active-units"
    assert choice["candidate_corpus"]["fallback_used"] is False


def test_method_falls_back_to_kb_repos_with_note(tmp_path: Path, monkeypatch, capsys) -> None:
    method = _load_method_module()
    root, idea_id, repo_id = _make_workspace(tmp_path)
    write_yaml_if_changed(
        root / "kb" / "programs" / "p-method" / "state.yaml",
        {"program_id": "p-method", "stage": "idea-review", "active_unit_ids": [idea_id]},
    )

    assert _run_design(method, monkeypatch, root, idea_id) == 0

    choice = load_yaml(root / "kb" / "programs" / "p-method" / "design" / f"{idea_id}-repo-choice.yaml", default={})
    assert choice["selected_repo_id"] == repo_id
    assert choice["candidate_corpus"]["scope"] == "kb-wide-fallback"
    assert choice["candidate_corpus"]["fallback_used"] is True
    assert "fell back to KB-wide repository units" in capsys.readouterr().out
