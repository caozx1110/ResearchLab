from __future__ import annotations

from repo_paths import initialize_test_workspace

from pathlib import Path

from research.common import load_yaml, write_yaml_if_changed
import research.core as core

# build_index moved to research.index in the god-file split; its iter_records and
# utc_now_iso lookups now resolve in that module's namespace, so patch them there.
import research.index as index_mod


def _write_record(root: Path, record: dict) -> None:
    write_yaml_if_changed(core.record_path(root, record["kind"], record["id"]), record)


def _sample_record(unit_id: str, kind: str, title: str) -> dict:
    return {
        "id": unit_id,
        "kind": kind,
        "title": title,
        "status": "active",
        "maturity": "lightweight",
        "confirmation_status": "auto_confirmed",
        "needs_human_confirmation": False,
        "information_types": ["fact"],
        "tags": ["vla"],
        "topics": ["robotics"],
        "candidate_pools": ["current-reading"],
        "summary": title,
        "source": {"original_uri": "", "file_hash": ""},
        "payload": {},
    }


def test_build_index_scans_records_once(tmp_path: Path, monkeypatch) -> None:
    initialize_test_workspace(tmp_path)
    _write_record(tmp_path, _sample_record("p-one-123456", "paper", "One Paper"))

    original_iter_records = core.iter_records
    calls = 0

    def counting_iter_records(project_root: Path, *, kind: str | None = None):
        nonlocal calls
        calls += 1
        return original_iter_records(project_root, kind=kind)

    monkeypatch.setattr(index_mod, "iter_records", counting_iter_records)

    core.build_index(tmp_path)

    assert calls == 1


def test_build_index_output_stays_byte_stable(tmp_path: Path, monkeypatch) -> None:
    initialize_test_workspace(tmp_path)
    _write_record(tmp_path, _sample_record("p-alpha-123456", "paper", "Alpha Paper"))
    _write_record(tmp_path, _sample_record("r-beta-123456", "repo", "Beta Repo"))
    monkeypatch.setattr(index_mod, "utc_now_iso", lambda: "2026-07-04T00:00:00+00:00")

    yaml_path, md_path = core.build_index(tmp_path)

    assert yaml_path.read_text(encoding="utf-8") == (
        "id: kb-index\n"
        "generated_at: '2026-07-04T00:00:00+00:00'\n"
        "items:\n"
        "- id: p-alpha-123456\n"
        "  kind: paper\n"
        "  title: Alpha Paper\n"
        "  status: active\n"
        "  maturity: lightweight\n"
        "  confirmation_status: auto_confirmed\n"
        "  tags:\n"
        "  - vla\n"
        "  topics:\n"
        "  - robotics\n"
        "  candidate_pools:\n"
        "  - current-reading\n"
        "  summary: Alpha Paper\n"
        "  path: kb/units/papers/p-alpha-123456/record.yaml\n"
        "- id: r-beta-123456\n"
        "  kind: repo\n"
        "  title: Beta Repo\n"
        "  status: active\n"
        "  maturity: lightweight\n"
        "  confirmation_status: auto_confirmed\n"
        "  tags:\n"
        "  - vla\n"
        "  topics:\n"
        "  - robotics\n"
        "  candidate_pools:\n"
        "  - current-reading\n"
        "  summary: Beta Repo\n"
        "  path: kb/units/repos/r-beta-123456/record.yaml\n"
        "counts:\n"
            "  paper: 1\n"
            "  repo: 1\n"
            "  dataset: 0\n"
            "  blog: 0\n"
        "  idea: 0\n"
        "  experiment: 0\n"
        "  concept: 0\n"
    )
    assert md_path.read_text(encoding="utf-8") == (
        "# Research KB Index\n\n"
        "## Papers\n\n"
        "- `p-alpha-123456` · Alpha Paper · status=active · maturity=lightweight · confirm=auto_confirmed · pools=current-reading\n\n"
            "## Repos\n\n"
            "- `r-beta-123456` · Beta Repo · status=active · maturity=lightweight · confirm=auto_confirmed · pools=current-reading\n\n"
            "## Datasets\n\n"
            "- 暂无条目\n\n"
            "## Blogs\n\n"
        "- 暂无条目\n\n"
        "## Ideas\n\n"
        "- 暂无条目\n\n"
        "## Experiments\n\n"
        "- 暂无条目\n\n"
        "## Concepts\n\n"
        "- 暂无条目\n"
    )

    index = load_yaml(yaml_path, default={})
    assert index["counts"] == {
        "paper": 1,
        "repo": 1,
        "dataset": 0,
        "blog": 0,
        "idea": 0,
        "experiment": 0,
        "concept": 0,
    }
