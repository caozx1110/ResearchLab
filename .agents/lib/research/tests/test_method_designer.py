from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

from research.common import load_yaml, write_yaml_if_changed
from research.core import default_record, ensure_workspace, record_path
from research.paths import config_root
from research.preference_selection import eligible_preferences, record_effective_selection


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
    assert choice["proposed_repo_id"] == active_repo_id
    assert "selected_repo_id" not in choice
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
    assert choice["proposed_repo_id"] == repo_id
    assert "selected_repo_id" not in choice
    assert choice["candidate_corpus"]["scope"] == "kb-wide-fallback"
    assert choice["candidate_corpus"]["fallback_used"] is True
    assert "fell back to KB-wide repository units" in capsys.readouterr().out


def test_method_prepares_agent_evidence_slots_instead_of_repo_judgement(tmp_path: Path, monkeypatch) -> None:
    method = _load_method_module()
    root, idea_id, repo_id = _make_workspace(tmp_path)

    assert _run_design(method, monkeypatch, root, idea_id) == 0

    design_root = root / "kb" / "programs" / "p-method" / "design"
    choice = load_yaml(design_root / f"{idea_id}-repo-choice.yaml", default={})
    matrix = load_yaml(design_root / f"{idea_id}-experiment-matrix.yaml", default={})
    method_text = (design_root / f"{idea_id}-method.md").read_text(encoding="utf-8")
    assert choice["proposed_repo_id"] == repo_id
    assert "selected_repo_id" not in choice
    assert choice["payload"]["method_selection"]["selection_reason"] == ""
    assert choice["payload"]["claims"] == []
    assert choice["status"] == "needs_agent_fill"
    assert choice["needs_human_confirmation"] is False
    assert choice["ranking_basis"]["type"] == "deterministic-token-overlap"
    assert matrix["baseline_judgement_claim_id"] == "method-baselines"
    assert matrix["proposal_status"] == "pending_agent_evidence"
    assert all(item["status"] == "proposal" for item in matrix["experiments"])
    assert all("repo_dependency" not in item for item in matrix["experiments"])
    assert "Selected repo:" not in method_text
    assert "Status: proposal only" in method_text
    state = load_yaml(root / "kb" / "programs" / "p-method" / "state.yaml", default={})
    assert state["stage"] == "idea-review"
    assert "selected_repo_id" not in state
    assert not (root / "kb" / "programs" / "p-method" / "workflow" / "reporting-events.yaml").exists()


def test_selected_research_focus_changes_only_bound_design_and_persists_receipt(
    tmp_path: Path,
    monkeypatch,
) -> None:
    method = _load_method_module()
    root, idea_id, default_repo_id = _make_workspace(tmp_path, resources={"gpu_count": 1})
    focused_repo_id = "r-vision-654321"
    focused_repo = default_record(
        "repo",
        title="Vision transformer perception navigation benchmark",
        maturity="lightweight",
        source={"original_uri": "https://example.com/vision"},
    )
    focused_repo["id"] = focused_repo_id
    focused_repo["summary"] = "Vision transformer perception navigation benchmark implementation."
    write_yaml_if_changed(record_path(root, "repo", focused_repo_id), focused_repo)
    write_yaml_if_changed(
        config_root(root) / "user-profile.yaml",
        {
            "personalization": {
                "research_focus": "vision transformer perception navigation benchmark",
            },
            "resources": {"gpu_count": 1},
            "constraints": ["local only"],
        },
    )
    args = method.build_parser().parse_args(
        ["design", "--idea-id", idea_id, "--program-id", "p-method"]
    )
    context = method.method_preference_context(
        load_yaml(record_path(root, "idea", idea_id)),
        program_id="p-method",
        idea_id=idea_id,
    )
    eligible = eligible_preferences(root, skill="method-designer", operation="design")
    selected = []
    excluded = []
    for item in eligible["items"]:
        row = {"preference_id": item["preference_id"], "reason": "bounded method design input"}
        if item["strength"] == "hard" or item["path"] == "profile.personalization.research_focus":
            selected.append({**row, "application": "apply to candidate proposal scoring"})
        else:
            excluded.append({**row, "reason": "not relevant to this method design"})
    record_effective_selection(
        root,
        {
            "selection_id": "prefsel-method-focus",
            "skill": "method-designer",
            "operation": "design",
            "catalog_digest": eligible["catalog_digest"],
            "task_context": context,
            "selected": selected,
            "excluded": excluded,
        },
    )
    monkeypatch.setattr(method, "PROJECT_ROOT", root)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "method.py",
            "--root",
            str(root),
            "design",
            "--idea-id",
            idea_id,
            "--program-id",
            "p-method",
            "--preference-selection-id",
            "prefsel-method-focus",
        ],
    )

    assert method.main() == 0
    choice = load_yaml(
        root / "kb/programs/p-method/design" / f"{idea_id}-repo-choice.yaml"
    )
    assert choice["proposed_repo_id"] == focused_repo_id
    assert choice["proposed_repo_id"] != default_repo_id
    assert choice["preference_context"]["selection_binding"]["selection_id"] == "prefsel-method-focus"
    assert set(choice["preference_context"]["hard_value_digests"]) == {
        "profile.resources",
        "profile.constraints",
    }
