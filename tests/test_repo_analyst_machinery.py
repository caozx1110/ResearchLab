"""Repo analyzer tests for `docs/DESIGN.md` "Prepare / fill / verify".

We cannot headless-test "an agent filled *good* understanding" (that needs a real
agent). So these test the MACHINERY the script owns — mirroring the paper-analyst
prepare/verify contract:

  * map-capability --phase prepare emits a 3-element fillable structure
    (capability / reuse_points / entry_map) with NO heuristic capability judgement;
  * feeding synthetic filled content with legit verbatim file:line evidence ->
    validates, clears the substance gate, and persists (capability non-empty,
    repo-note.md written);
  * feeding a fabricated quote OR an unreachable file -> rejected, offending element
    named;
  * feeding empty/template fill -> rejected, and the substance gate blocks confirm.

Evidence for repo units grounds to REAL repo files: artifact = a file relative to
repo_root, locator = line=N, quote = a verbatim line from that file. The synthetic
mini-repo fixture is a handful of .py + README + config so verification is
deterministic and offline; the repo is never copied into the unit — verify resolves
repo_root from the record source and loads cited files by relative path.
"""
from __future__ import annotations

from repo_paths import initialize_test_workspace

import importlib.util
import sys
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest

from research.common import load_yaml, write_yaml_if_changed
from research.confirm import confirm_unit, has_substantive_content
from research.core import default_record, ensure_workspace, record_path, write_record
from research.evidence import attach_claims, build_verification_receipt
from research.judgements import (
    discover_pending_judgements,
    judgement_confirmation_is_current,
    readiness_violations,
)
from research.records import canonical_record_snapshot_for_record, normalize_record_snapshot


def _project_root() -> Path:
    return REPO_ROOT


def _load_repo_module():
    script = _project_root() / "skills" / "unit-analyst" / "scripts" / "repo.py"
    spec = importlib.util.spec_from_file_location("repo_analyst_script_under_test", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# --------------------------------------------------------------------------- #
# Synthetic mini-repo fixture: a few .py + README + config with KNOWN verbatim  #
# lines so evidence verification is deterministic.                              #
# --------------------------------------------------------------------------- #
README = (
    "# MiniVLA\n"
    "MiniVLA is a compact vision-language-action baseline for robot manipulation.\n"
    "Training uses behavior cloning on teleop demonstrations.\n"
)
TRAIN_PY = (
    "def main():\n"
    "    # training entrypoint for the behavior cloning loop\n"
    "    model = build_policy()\n"
    "    trainer.fit(model, dataloader)\n"
)
POLICY_PY = (
    "class Policy:\n"
    "    # reusable policy head module\n"
    "    def act(self, obs):\n"
    "        return self.head(obs)\n"
)
CONFIG_YAML = "lr: 0.0003\nbatch_size: 64\nevidence_required: true\n"


def _make_mini_repo(base: Path) -> Path:
    repo = base / "mini-repo"
    (repo / "configs").mkdir(parents=True)
    (repo / "README.md").write_text(README, encoding="utf-8")
    (repo / "train.py").write_text(TRAIN_PY, encoding="utf-8")
    (repo / "policy.py").write_text(POLICY_PY, encoding="utf-8")
    (repo / "configs" / "default.yaml").write_text(CONFIG_YAML, encoding="utf-8")
    return repo


def _repo_record(repo_id: str, repo_root: Path) -> dict:
    # Match the production constructor so the detached object already carries
    # canonical timestamps/history.  A hand-written sparse record is normalized
    # on write, but is not itself the exact persisted object required by the
    # later strict snapshot-binding assertion.
    record = default_record(
        "repo",
        title="MiniVLA",
        maturity="lightweight",
        # A local repo checkout — verify resolves repo_root from here, no copy into kb/.
        source={"original_uri": str(repo_root), "file_hash": ""},
    )
    record.update(
        {
            "id": repo_id,
            "status": "screened",
            "confirmation_status": "pending_user_confirmation",
            "needs_human_confirmation": True,
            "information_types": ["evaluation", "fact", "inference", "unverified"],
            "topics": ["vision-language-action"],
            "tags": ["manipulation"],
        }
    )
    return record


def _legit_capability_fill(repo_id: str = "r-x") -> dict:
    """A synthetic 3-element fill whose every quote is verbatim from the mini-repo."""
    return {
        "elements": [
            {
                "element": "capability",
                "claim_type": "evaluation",
                "content": "A compact VLA baseline for manipulation; suited to imitation baselines, "
                           "not large-scale pretraining.",
                "evidence_refs": [
                    {"source_unit_id": repo_id, "artifact": "README.md", "locator": "line=2",
                     "quote": "compact vision-language-action baseline for robot manipulation",
                     "summary": "problem + scope"}
                ],
            },
            {
                "element": "reuse_points",
                "claim_type": "evaluation",
                "content": "The policy head module is directly reusable for a new action space.",
                "evidence_refs": [
                    {"source_unit_id": repo_id, "artifact": "policy.py", "locator": "line=2",
                     "quote": "reusable policy head module", "summary": "reusable unit"}
                ],
            },
            {
                "element": "entry_map",
                "claim_type": "inference",
                "content": "Training entry is train.py:main; it runs a behavior-cloning fit loop.",
                "evidence_refs": [
                    {"source_unit_id": repo_id, "artifact": "train.py", "locator": "line=2",
                     "quote": "training entrypoint for the behavior cloning loop", "summary": "train entry"}
                ],
            },
        ]
    }


# --------------------------------------------------------------------------- #
# 1. prepare produces a fillable 3-element structure with NO heuristic judgement.
# --------------------------------------------------------------------------- #
def test_capability_scaffold_has_three_blank_elements(tmp_path: Path) -> None:
    repo = _load_repo_module()
    mini = _make_mini_repo(tmp_path)
    record = _repo_record("r-scaffold-000001", mini)

    structure = repo.scan_structure_payload(tmp_path, record)
    scaffold = repo.build_capability_scaffold(record, structure, mini)

    names = [el["element"] for el in scaffold["elements"]]
    assert names == ["capability", "reuse_points", "entry_map"]
    for el in scaffold["elements"]:
        assert el["content"] == ""          # script authors nothing
        assert el["evidence_refs"] == []     # agent must attach file:line evidence
    assert scaffold["fill_contract"]["required_elements"] == names
    assert "evidence_ref_format" in scaffold["fill_contract"]
    # The evidence format is the file:line family (line=N), not PDF page=N.
    assert "line=N" in scaffold["fill_contract"]["evidence_ref_format"]["locator"]

    # NO heuristic capability judgement leaks into the scaffold: none of the old
    # infer_repo_roles / capability_map judgement fields are present.
    for banned in ("candidate_roles", "supported_tasks", "unsupported_tasks",
                   "core_capabilities", "boundary", "inferred_topics", "inferred_tags",
                   "problem"):
        assert banned not in scaffold, banned
    # README/dirs are handed over ONLY as mechanical orientation, never as a judgement.
    assert "agent_orientation" in scaffold
    assert "top_level_dirs" in scaffold["agent_orientation"]


def test_scan_structure_is_mechanical_only(tmp_path: Path) -> None:
    repo = _load_repo_module()
    mini = _make_mini_repo(tmp_path)
    record = _repo_record("r-scan-000001", mini)

    structure = repo.scan_structure_payload(tmp_path, record)
    # Mechanical facts only.
    assert "train.py" in structure["entrypoints"]
    assert "configs" in structure["top_level_dirs"]
    assert any(lang.startswith(".py") for lang in structure["languages"])
    # No role/topic/capability judgement fields produced by the scan.
    for banned in ("candidate_roles", "training_flow", "inference_flow",
                   "critical_modules", "supported_tasks"):
        assert banned not in structure, banned


def test_repo_source_has_no_capability_heuristic_symbols() -> None:
    """Anti-pattern guard: no infer_repo_roles / capability_map heuristic remains."""
    src = (_project_root() / "skills" / "unit-analyst" / "scripts" / "repo.py").read_text("utf-8")
    assert "infer_repo_roles" not in src
    assert "capability_map" not in src


# --------------------------------------------------------------------------- #
# 2. Legit filled content + verbatim file:line evidence -> validates, persists.
# --------------------------------------------------------------------------- #
def test_capability_fill_legit_evidence_validates_and_clears_substance_gate(tmp_path: Path) -> None:
    repo = _load_repo_module()
    mini = _make_mini_repo(tmp_path)

    violations, claims = repo.verify_capability_fill(_legit_capability_fill(), mini)
    assert violations == [], violations
    assert len(claims) == 3

    record = _repo_record("r-fill-legit-1", mini)
    record["payload"]["structure"]["repo_root"] = mini.resolve().as_posix()
    for claim in claims:
        for ref in claim["evidence_refs"]:
            ref["source_unit_id"] = record["id"]
    assert has_substantive_content(record, "repo") is False  # empty before fill
    repo._apply_capability_fill_to_payload(record, claims)
    attach_claims(record["payload"], claims)
    build_verification_receipt(
        record,
        record_path(tmp_path, "repo", record["id"]).parent,
        external_source={"kind": "repo", "base_root": mini.resolve().as_posix()},
    )

    # The cross-owner review resolver must use the same trusted external-source
    # contract as repo verification and confirmation.  A coarse workflow state
    # alone is not sufficient for the public inbox.
    canonical_path = write_record(tmp_path, record)
    assert load_yaml(canonical_path) == record
    assert readiness_violations(tmp_path, record, canonical_path) == []
    cards = discover_pending_judgements(tmp_path)
    assert [card["subject"]["id"] for card in cards] == [record["id"]]

    cap = record["payload"]["capability"]
    assert cap["core_capabilities"]  # capability -> core_capabilities (clears gate)
    assert record["payload"]["reuse"]["directly_reusable"]      # reuse_points routed
    assert record["payload"]["structure"]["entrypoints"]        # entry_map routed
    assert has_substantive_content(record, "repo") is True

    # repo-note.md renders every element + its file:line evidence citation.
    note_md = repo.render_capability_md(record, claims)
    assert "## Capability" in note_md and "## Entry Map" in note_md
    assert "compact vision-language-action baseline for robot manipulation" in note_md
    assert "[README.md:line=2]" in note_md

    # Substance gate now passes: a real human can confirm the judgement-track repo.
    expected_record_snapshot = canonical_record_snapshot_for_record(tmp_path, record)
    persisted_record = normalize_record_snapshot(expected_record_snapshot, tmp_path)
    assert persisted_record is not None
    confirmed = confirm_unit(persisted_record, "repo", confirmed_by="czx",
                             evidence=["kb/units/repos/r-fill-legit-1/repo-note.md"],
                             user_authorization="I confirm this repo analysis.",
                             authorization_source="user_message", project_root=tmp_path,
                             expected_record_snapshot=expected_record_snapshot)
    assert confirmed["confirmation_status"] == "confirmed"
    canonical_path = record_path(tmp_path, "repo", record["id"])
    write_yaml_if_changed(canonical_path, confirmed)
    assert judgement_confirmation_is_current(tmp_path, confirmed, canonical_path)


def test_capability_fill_accepts_raw_yaml_line_via_external_source_contract(tmp_path: Path) -> None:
    repo = _load_repo_module()
    mini = _make_mini_repo(tmp_path)
    fill = _legit_capability_fill()
    fill["elements"][2]["evidence_refs"] = [
        {
            "source_unit_id": "r-x",
            "artifact": "configs/default.yaml",
            "locator": "line=3",
            "quote": "evidence_required: true",
            "summary": "configuration gate",
        },
    ]

    violations, claims = repo.verify_capability_fill(fill, mini)

    assert violations == [], violations
    assert claims[2]["evidence_refs"][0]["external_source"] == {"kind": "repo"}


# --------------------------------------------------------------------------- #
# 3. Fabricated quote / unreachable file -> rejected, offending element named.
# --------------------------------------------------------------------------- #
def test_capability_fill_fabricated_evidence_is_rejected_by_element(tmp_path: Path) -> None:
    repo = _load_repo_module()
    mini = _make_mini_repo(tmp_path)

    fill = _legit_capability_fill()
    # Corrupt the capability quote so it is not verbatim in README.md.
    fill["elements"][0]["evidence_refs"][0]["quote"] = "a diffusion world model we never wrote"

    violations, _claims = repo.verify_capability_fill(fill, mini)
    assert violations
    assert any("element 'capability'" in v and "not verbatim" in v for v in violations), violations
    # Untouched elements are not falsely blamed.
    assert not any("element 'reuse_points'" in v for v in violations)


def test_capability_fill_unreachable_file_is_rejected(tmp_path: Path) -> None:
    repo = _load_repo_module()
    mini = _make_mini_repo(tmp_path)

    fill = _legit_capability_fill()
    # Point entry_map evidence at a file that does not exist in the repo.
    fill["elements"][2]["evidence_refs"][0]["artifact"] = "ghost/missing_entrypoint.py"

    violations, _claims = repo.verify_capability_fill(fill, mini)
    assert violations
    assert any("element 'entry_map'" in v and "not found/readable" in v for v in violations), violations


# --------------------------------------------------------------------------- #
# 4. Empty / template fill -> rejected, and the substance gate blocks confirm.
# --------------------------------------------------------------------------- #
def test_empty_capability_fill_is_rejected_and_hollow_confirm_is_blocked(tmp_path: Path) -> None:
    repo = _load_repo_module()
    mini = _make_mini_repo(tmp_path)

    # A scaffold-shaped fill with blank content (agent produced nothing).
    record = _repo_record("r-x", mini)
    structure = repo.scan_structure_payload(tmp_path, record)
    empty_fill = repo.build_capability_scaffold(record, structure, mini)
    violations, _claims = repo.verify_capability_fill(empty_fill, mini)
    assert violations
    assert any("empty content" in v for v in violations)
    assert any("no evidence_refs" in v for v in violations)

    # And the confirmation substance gate independently refuses a hollow repo.
    hollow = _repo_record("r-hollow-000001", mini)  # capability untouched == empty
    assert has_substantive_content(hollow, "repo") is False
    with pytest.raises(SystemExit, match="hollow"):
        confirm_unit(hollow, "repo", confirmed_by="czx", evidence=["kb/units/repos/r/log.md"])


# --------------------------------------------------------------------------- #
# 5. End-to-end through the real CLI (main): prepare -> fill -> verify -> persist.
# --------------------------------------------------------------------------- #
def _run_cli(repo, monkeypatch, root: Path, *argv: str) -> int:
    monkeypatch.setattr(sys, "argv", ["repo.py", "--root", str(root), *argv])
    return repo.main()


def test_cli_end_to_end_prepare_fill_verify_persist(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repo = _load_repo_module()
    initialize_test_workspace(tmp_path)
    mini = _make_mini_repo(tmp_path)
    repo_id = "r-e2e-000001"
    record = _repo_record(repo_id, mini)
    write_record(tmp_path, record)
    unit_dir = record_path(tmp_path, "repo", repo_id).parent

    # prepare -> 3-element skeleton; record marked screened but still hollow.
    assert _run_cli(repo, monkeypatch, tmp_path, "map-capability", "--phase", "prepare",
                    "--repo-id", repo_id, "--defer-post-actions") == 0
    fill_path = unit_dir / "capability-fill.yaml"
    assert [el["element"] for el in load_yaml(fill_path)["elements"]] == list(repo.CAP_ELEMENTS)
    reloaded = load_yaml(record_path(tmp_path, "repo", repo_id))
    assert has_substantive_content(reloaded, "repo") is False  # scaffold is not content

    # Agent fills the scaffold; verify persists repo-note.md + capability.
    write_yaml_if_changed(fill_path, _legit_capability_fill(repo_id))
    assert _run_cli(repo, monkeypatch, tmp_path, "map-capability", "--phase", "verify",
                    "--repo-id", repo_id, "--defer-post-actions") == 0
    assert (unit_dir / "repo-note.md").exists()
    filled = load_yaml(record_path(tmp_path, "repo", repo_id))
    assert has_substantive_content(filled, "repo") is True
    assert filled["payload"]["claims"] == load_yaml(unit_dir / "capability-claims.yaml")["claims"]
    assert filled["payload"]["verification"]["artifacts"]
    assert len(filled["payload"]["verification"]["claims_digest"]) == 64

    # Fabricated fill through the CLI is rejected (non-zero exit).
    bad = _legit_capability_fill(repo_id)
    bad["elements"][0]["evidence_refs"][0]["quote"] = "fabricated capability not in any file"
    write_yaml_if_changed(fill_path, bad)
    with pytest.raises(SystemExit):
        _run_cli(repo, monkeypatch, tmp_path, "map-capability", "--phase", "verify",
                 "--repo-id", repo_id, "--defer-post-actions")
