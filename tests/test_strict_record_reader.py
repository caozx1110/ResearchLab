from __future__ import annotations

import errno
import argparse
import hashlib
import importlib.machinery
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest

from research.common import write_yaml_if_changed
from research.evidence import (
    EvidenceSourceSnapshot,
    build_verification_receipt,
    verification_receipt_violations,
)
from research.judgements import discover_pending_judgements
from research.index import search_records
from research.paths import record_path
from research.records import default_record, iter_records, locate_record, trusted_claim_source_roots
from research.sources import detect_duplicate
from research.surveys import select_current_confirmed_survey_records
import research.records as records_module
import research.judgements as judgements_module


ROOT = REPO_ROOT


def _write_record(root: Path, kind: str, unit_id: str, *, title: str) -> Path:
    record = default_record(kind, title=title, maturity="lightweight")
    record["id"] = unit_id
    path = record_path(root, kind, unit_id)
    write_yaml_if_changed(path, record)
    return path


def _write_ready_unit(root: Path, kind: str, unit_id: str) -> Path:
    record = default_record(
        kind,
        title="Strict reader review fixture",
        maturity="complete",
        source={"original_uri": "fixture"},
    )
    record.update(
        id=unit_id,
        status="screened",
        confirmation_status="pending_user_confirmation",
        needs_human_confirmation=True,
        information_types=["evaluation", "unverified"],
    )
    if kind == "paper":
        record["payload"]["core_content"]["research_problem"] = "A reviewable claim."
    elif kind == "repo":
        record["payload"]["capability"]["core_capabilities"] = ["A reviewable claim."]
    elif kind == "dataset":
        record["payload"]["profile"]["positioning"] = "A reviewable claim."
    elif kind == "blog":
        record["payload"]["content"]["key_points"] = ["A reviewable claim."]
    unit_root = record_path(root, kind, unit_id).parent
    external_source = None
    if kind == "repo":
        repo_root = root / "repo-fixtures" / unit_id
        repo_root.mkdir(parents=True)
        evidence = repo_root / "README.md"
        evidence.write_text("Verified evidence for the strict reader.", encoding="utf-8")
        record["source"]["original_uri"] = repo_root.as_posix()
        record["payload"]["structure"]["repo_root"] = repo_root.resolve().as_posix()
        evidence_ref = {
            "source_unit_id": unit_id,
            "artifact": "README.md",
            "locator": "line=1",
            "quote": "Verified evidence for the strict reader.",
            "external_source": {"kind": "repo"},
        }
        external_source = {"kind": "repo", "base_root": repo_root.resolve().as_posix()}
    else:
        evidence = unit_root / "raw" / "source.txt"
        evidence.parent.mkdir(parents=True, exist_ok=True)
        evidence.write_text("Verified evidence for the strict reader.", encoding="utf-8")
        evidence_ref = {
            "source_unit_id": unit_id,
            "artifact": "raw/source.txt",
            "locator": "line:1",
            "quote": "Verified evidence for the strict reader.",
        }
    record["payload"]["claims"] = [
        {
            "id": f"claim-{unit_id}",
            "text": "A reviewable claim.",
            "claim_type": "evaluation",
            "confirmation_status": "pending_user_confirmation",
            "evidence_refs": [evidence_ref],
        }
    ]
    build_verification_receipt(
        record,
        unit_root,
        external_source=external_source,
        source_roots={unit_id: unit_root},
    )
    path = record_path(root, kind, unit_id)
    write_yaml_if_changed(path, record)
    return path


def _load_orchestrator():
    script = ROOT / ".agents" / "skills" / "research-orchestrator" / "scripts" / "orchestrate.py"
    name = "strict_record_reader_orchestrator"
    spec = importlib.util.spec_from_file_location(name, script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _load_kb_cli():
    script = ROOT / ".agents" / "skills" / "kb-cli" / "scripts" / "kb"
    loader = importlib.machinery.SourceFileLoader("strict_record_reader_kb", str(script))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[loader.name] = module
    spec.loader.exec_module(module)
    return module


def _tree_digest(root: Path) -> str:
    if not root.exists():
        return "absent"
    digest = hashlib.sha256()
    for path in [root, *sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix())]:
        relative = "." if path == root else path.relative_to(root).as_posix()
        metadata = path.lstat()
        digest.update(f"{relative}\0{metadata.st_mode}\0{metadata.st_size}\0{metadata.st_mtime_ns}\0".encode())
        if path.is_symlink():
            digest.update(path.readlink().as_posix().encode())
        elif path.is_file():
            digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def test_project_file_snapshot_binds_bytes_inode_and_ancestor_chain(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    artifact = root / "kb" / "programs" / "program-a" / "workflow" / "decisions.yaml"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("schema: decisions/v1\nitems: []\n", encoding="utf-8")

    snapshot = records_module.snapshot_project_file(
        root,
        "kb/programs/program-a/workflow/decisions.yaml",
    )

    assert snapshot is not None
    assert snapshot.raw_bytes == artifact.read_bytes()
    assert snapshot.is_current()
    replacement = artifact.parent / "replacement.yaml"
    replacement.write_bytes(artifact.read_bytes())
    replacement.replace(artifact)
    assert not snapshot.is_current()

    rebound = records_module.snapshot_project_file(root, snapshot.relative_path)
    assert rebound is not None and rebound.is_current()
    programs = root / "kb" / "programs"
    parked = root / "kb" / "programs-parked"
    programs.rename(parked)
    programs.mkdir()
    (parked / "program-a").rename(programs / "program-a")
    assert not rebound.is_current()


def test_project_yaml_snapshot_is_strict_and_current(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    artifact = root / "kb" / "programs" / "program-a" / "workflow" / "decisions.yaml"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("schema: decisions/v1\nitems: []\n", encoding="utf-8")

    snapshot = records_module.snapshot_project_yaml_mapping(
        root,
        "kb/programs/program-a/workflow/decisions.yaml",
    )

    assert snapshot is not None
    assert snapshot.payload == {"schema": "decisions/v1", "items": []}
    assert snapshot.is_current()
    artifact.write_text("schema: one\nschema: two\n", encoding="utf-8")
    assert records_module.snapshot_project_yaml_mapping(root, snapshot.file.relative_path) is None
    assert not snapshot.is_current()


def test_project_evidence_source_uses_one_base_capability(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    program = root / "kb" / "programs" / "program-a"
    first = program / "evidence" / "first.md"
    second = program / "workflow" / "second.yaml"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("first evidence\n", encoding="utf-8")
    second.write_text("text: second evidence\n", encoding="utf-8")

    snapshot = records_module.snapshot_project_evidence_source(
        root,
        "kb/programs/program-a",
        source_unit_id="program:program-a",
        kind="program",
        artifacts=["workflow/second.yaml", "evidence/first.md"],
    )

    assert snapshot is not None
    assert [item.artifact for item in snapshot.artifacts] == [
        "evidence/first.md",
        "workflow/second.yaml",
    ]
    assert snapshot.is_current()
    parked = root / "kb" / "program-a-parked"
    program.rename(parked)
    shutil.copytree(parked, program)
    assert not snapshot.is_current()


def test_project_snapshots_keep_capture_root_after_chdir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    capture_parent = tmp_path / "capture-parent"
    root = capture_parent / "workspace"
    program = root / "kb" / "programs" / "program-a"
    artifact = program / "evidence" / "first.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("stable evidence\n", encoding="utf-8")
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    monkeypatch.chdir(capture_parent)
    file_snapshot = records_module.snapshot_project_file(
        Path("workspace"),
        "kb/programs/program-a/evidence/first.md",
    )
    source_snapshot = records_module.snapshot_project_evidence_source(
        Path("workspace"),
        "kb/programs/program-a",
        source_unit_id="program:program-a",
        kind="program",
        artifacts=["evidence/first.md"],
    )

    assert file_snapshot is not None
    assert source_snapshot is not None
    monkeypatch.chdir(elsewhere)
    assert file_snapshot.is_current()
    assert source_snapshot.is_current()
    artifact.write_text("changed evidence\n", encoding="utf-8")
    assert not file_snapshot.is_current()
    assert not source_snapshot.is_current()


@pytest.mark.parametrize(
    "overrides",
    [
        {"artifacts": "evidence/first.md"},
        {"artifacts": b"evidence/first.md"},
        {"artifacts": []},
        {"artifacts": [123]},
        {"source_unit_id": ""},
        {"source_unit_id": " program:program-a"},
        {"source_unit_id": "program::program-a"},
        {"source_unit_id": "program:program/a"},
        {"kind": ""},
        {"kind": " program"},
        {"kind": "program/other"},
    ],
)
def test_project_evidence_source_rejects_noncanonical_inputs(
    tmp_path: Path,
    overrides: dict[str, object],
) -> None:
    root = tmp_path / "workspace"
    artifact = root / "kb" / "programs" / "program-a" / "evidence" / "first.md"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("stable evidence\n", encoding="utf-8")
    arguments: dict[str, object] = {
        "source_unit_id": "program:program-a",
        "kind": "program",
        "artifacts": ["evidence/first.md"],
    }
    arguments.update(overrides)

    assert records_module.snapshot_project_evidence_source(
        root,
        "kb/programs/program-a",
        **arguments,
    ) is None


def _program_evidence_consumer(
    source_unit_id: str,
    artifacts: list[tuple[str, str]],
) -> dict[str, object]:
    return {
        "id": "program-decision-consumer",
        "kind": "program_decision",
        "payload": {
            "claims": [
                {
                    "id": f"claim-{index}",
                    "text": quote,
                    "claim_type": "evaluation",
                    "evidence_refs": [
                        {
                            "source_unit_id": source_unit_id,
                            "artifact": artifact,
                            "locator": "line:1",
                            "quote": quote,
                        }
                    ],
                }
                for index, (artifact, quote) in enumerate(artifacts, start=1)
            ]
        },
    }


def test_trusted_program_evidence_captures_all_requested_artifacts_once(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    program = root / "kb" / "programs" / "program-a"
    first = program / "evidence" / "first.md"
    second = program / "workflow" / "second.yaml"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_text("first stable evidence\n", encoding="utf-8")
    second.write_text("text: second stable evidence\n", encoding="utf-8")
    consumer = _program_evidence_consumer(
        "program:program-a",
        [
            ("workflow/second.yaml", "second stable evidence"),
            ("evidence/first.md", "first stable evidence"),
        ],
    )

    roots = trusted_claim_source_roots(root, consumer)

    assert set(roots) == {"program:program-a"}
    snapshot = roots["program:program-a"]
    assert isinstance(snapshot, EvidenceSourceSnapshot)
    assert snapshot.path == program
    assert [item.artifact for item in snapshot.artifacts] == [
        "evidence/first.md",
        "workflow/second.yaml",
    ]
    assert [item.raw_bytes for item in snapshot.artifacts] == [
        b"first stable evidence\n",
        b"text: second stable evidence\n",
    ]
    assert snapshot.is_current()
    (program / "workflow" / "unrelated.yaml").write_text("status: new\n", encoding="utf-8")
    assert snapshot.is_current()


@pytest.mark.parametrize(
    ("source_unit_id", "artifact"),
    [
        ("program:program-a", "../program-b/evidence/secret.md"),
        ("program:program-a/../program-b", "evidence/secret.md"),
    ],
)
def test_trusted_program_evidence_rejects_cross_program_paths(
    tmp_path: Path,
    source_unit_id: str,
    artifact: str,
) -> None:
    root = tmp_path / "workspace"
    first = root / "kb" / "programs" / "program-a" / "evidence" / "first.md"
    secret = root / "kb" / "programs" / "program-b" / "evidence" / "secret.md"
    first.parent.mkdir(parents=True)
    secret.parent.mkdir(parents=True)
    first.write_text("program A evidence\n", encoding="utf-8")
    secret.write_text("program B secret\n", encoding="utf-8")
    consumer = _program_evidence_consumer(
        source_unit_id,
        [(artifact, "program B secret")],
    )

    with pytest.raises(ValueError, match="program evidence"):
        trusted_claim_source_roots(root, consumer)


def test_trusted_program_evidence_directory_swap_cannot_mix_versions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    program = root / "kb" / "programs" / "program-a"
    evidence = program / "evidence"
    evidence.mkdir(parents=True)
    (evidence / "first.md").write_text("version A first\n", encoding="utf-8")
    (evidence / "second.md").write_text("version A second\n", encoding="utf-8")
    replacement = tmp_path / "replacement-program"
    replacement_evidence = replacement / "evidence"
    replacement_evidence.mkdir(parents=True)
    (replacement_evidence / "first.md").write_text("version B first\n", encoding="utf-8")
    (replacement_evidence / "second.md").write_text("version B second\n", encoding="utf-8")
    parked = tmp_path / "parked-program"
    consumer = _program_evidence_consumer(
        "program:program-a",
        [
            ("evidence/first.md", "version A first"),
            ("evidence/second.md", "version A second"),
        ],
    )
    original_open = records_module.os.open
    swapped = False

    def racing_open(name, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if name == "second.md" and dir_fd is not None and not swapped:
            swapped = True
            program.rename(parked)
            replacement.rename(program)
        return original_open(name, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(records_module.os, "open", racing_open)

    with pytest.raises(ValueError, match="program evidence cannot be captured canonically"):
        trusted_claim_source_roots(root, consumer)
    assert swapped
    assert (parked / "evidence" / "first.md").read_text(encoding="utf-8") == "version A first\n"
    assert (program / "evidence" / "second.md").read_text(encoding="utf-8") == "version B second\n"


def test_project_file_snapshot_rejects_unsafe_special_and_oversize_inputs(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    parent = root / "kb" / "programs" / "program-a"
    parent.mkdir(parents=True)
    outside = tmp_path / "outside.yaml"
    outside.write_text("sentinel: outside\n", encoding="utf-8")
    (parent / "link.yaml").symlink_to(outside)
    (parent / "oversize.yaml").write_bytes(b"x" * 33)
    assert records_module.snapshot_project_file(root, "../outside.yaml") is None
    assert records_module.snapshot_project_file(root, "kb/programs/program-a/link.yaml") is None
    assert records_module.snapshot_project_file(
        root,
        "kb/programs/program-a/oversize.yaml",
        max_bytes=32,
    ) is None

    if hasattr(os, "mkfifo"):
        os.mkfifo(parent / "fifo.yaml")
        assert records_module.snapshot_project_file(
            root,
            "kb/programs/program-a/fifo.yaml",
        ) is None
    socket_root = Path(tempfile.mkdtemp(prefix="r23-socket-", dir="/tmp"))
    socket_parent = socket_root / "kb" / "p"
    socket_parent.mkdir(parents=True)
    socket_path = socket_parent / "socket"
    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        try:
            server.bind(str(socket_path))
        except OSError as exc:
            if exc.errno in {
                errno.EPERM,
                errno.EACCES,
                errno.EAFNOSUPPORT,
                errno.EPROTONOSUPPORT,
            }:
                pytest.skip("Unix-domain socket bind is unavailable in this environment")
            raise
        assert records_module.snapshot_project_file(
            socket_root,
            "kb/p/socket",
        ) is None
    finally:
        server.close()
        shutil.rmtree(socket_root)


def test_canonical_unit_tree_snapshot_hashes_recursive_artifacts_in_name_order(
    tmp_path: Path,
) -> None:
    root = tmp_path / "workspace"
    record = _write_record(root, "paper", "p-tree-123456", title="Tree snapshot")
    unit = record.parent
    nested = unit / "a"
    nested.mkdir()
    expected = {
        "a/deep.md": b"nested evidence\n",
        "a.txt": b"root evidence a\n",
        "z.txt": b"root evidence z\n",
    }
    for artifact, raw_bytes in expected.items():
        path = unit / artifact
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw_bytes)

    snapshot = records_module.snapshot_unique_canonical_unit_tree(
        root,
        "p-tree-123456",
        expected_kind="paper",
    )

    assert snapshot is not None
    assert [item.artifact for item in snapshot.artifacts] == sorted(expected)
    assert {
        item.artifact: item.byte_sha256 for item in snapshot.artifacts
    } == {
        artifact: hashlib.sha256(raw_bytes).hexdigest()
        for artifact, raw_bytes in expected.items()
    }
    assert snapshot.is_current()
    (unit / "new-after-capture.md").write_text("new evidence\n", encoding="utf-8")
    assert not snapshot.is_current()


@pytest.mark.parametrize(
    "unsafe_case",
    ["symlink", "per_file_limit", "total_limit", "entry_limit", "depth_limit"],
)
def test_canonical_unit_tree_snapshot_fails_closed_on_unsafe_or_over_limit_nodes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    unsafe_case: str,
) -> None:
    root = tmp_path / "workspace"
    record = _write_record(root, "paper", "p-tree-unsafe-123456", title="Unsafe tree")
    unit = record.parent
    if unsafe_case == "symlink":
        outside = tmp_path / "outside-only.md"
        outside.write_text("outside bytes\n", encoding="utf-8")
        (unit / "linked.md").symlink_to(outside)
    elif unsafe_case == "per_file_limit":
        monkeypatch.setattr(records_module, "_ARTIFACT_MAX_BYTES", 4)
        (unit / "large.md").write_bytes(b"12345")
    elif unsafe_case == "total_limit":
        monkeypatch.setattr(records_module, "_UNIT_ARTIFACT_TOTAL_MAX_BYTES", 5)
        (unit / "one.md").write_bytes(b"123")
        (unit / "two.md").write_bytes(b"456")
    elif unsafe_case == "entry_limit":
        monkeypatch.setattr(records_module, "_UNIT_TREE_MAX_ENTRIES", 1)
        (unit / "extra.md").write_text("entry\n", encoding="utf-8")
    else:
        monkeypatch.setattr(records_module, "_UNIT_TREE_MAX_DEPTH", 1)
        nested = unit / "nested"
        nested.mkdir()
        (nested / "too-deep.md").write_text("deep\n", encoding="utf-8")

    assert records_module.snapshot_canonical_unit_tree(
        root,
        "paper",
        "p-tree-unsafe-123456",
    ) is None


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_canonical_unit_tree_snapshot_rejects_fifo_without_opening_it(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    record = _write_record(root, "paper", "p-tree-fifo-123456", title="FIFO tree")
    os.mkfifo(record.parent / "blocked.pipe")

    assert records_module.snapshot_canonical_unit_tree(
        root,
        "paper",
        "p-tree-fifo-123456",
    ) is None


def test_iter_records_rejects_external_record_symlink(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    outside = tmp_path / "outside-record.yaml"
    outside_record = default_record("paper", title="Outside", maturity="lightweight")
    outside_record["id"] = "p-outside-123456"
    write_yaml_if_changed(outside, outside_record)
    linked = record_path(root, "paper", outside_record["id"])
    linked.parent.mkdir(parents=True)
    linked.symlink_to(outside)

    assert iter_records(root) == []
    assert outside.read_bytes()


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_iter_records_skips_fifo_promptly_without_hiding_valid_sibling(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_record(root, "paper", "p-valid-123456", title="Valid sibling")
    fifo = record_path(root, "paper", "p-fifo-123456")
    fifo.parent.mkdir(parents=True)
    os.mkfifo(fifo)
    code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from research.records import iter_records
items = iter_records(Path(sys.argv[2]))
assert [item['id'] for item in items] == ['p-valid-123456']
"""

    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT / ".agents" / "lib"), str(root)],
        capture_output=True,
        text=True,
        timeout=3,
    )

    assert result.returncode == 0, result.stderr


def test_duplicate_record_mapping_key_is_excluded_from_review(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    path = _write_ready_unit(root, "blog", "b-duplicate-123456")
    assert len(discover_pending_judgements(root)) == 1
    path.write_text(path.read_text(encoding="utf-8") + "status: screened\n", encoding="utf-8")

    assert discover_pending_judgements(root) == []


def test_iter_records_rejects_dangling_record_symlink(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    linked = record_path(root, "paper", "p-dangling-123456")
    linked.parent.mkdir(parents=True)
    linked.symlink_to(tmp_path / "missing-record.yaml")

    assert iter_records(root) == []


def test_leaf_swap_to_symlink_is_excluded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    path = _write_record(root, "paper", "p-swap-123456", title="Original")
    outside = tmp_path / "outside.yaml"
    outside_record = default_record("paper", title="Outside", maturity="lightweight")
    outside_record["id"] = "p-swap-123456"
    write_yaml_if_changed(outside, outside_record)
    original_open = os.open
    swapped = False

    def racing_open(name, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if name == "record.yaml" and dir_fd is not None and not swapped:
            swapped = True
            path.rename(path.with_name("record.parked"))
            path.symlink_to(outside)
        return original_open(name, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", racing_open)

    assert iter_records(root) == []
    assert swapped
    assert outside.read_bytes()


def test_leaf_swap_after_open_is_excluded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    path = _write_record(root, "paper", "p-read-swap-123456", title="Original")
    outside = tmp_path / "outside-after-open.yaml"
    outside_record = default_record("paper", title="Outside", maturity="lightweight")
    outside_record["id"] = "p-read-swap-123456"
    write_yaml_if_changed(outside, outside_record)
    original_read = os.read
    swapped = False

    def racing_read(fd, count):
        nonlocal swapped
        data = original_read(fd, count)
        if data and not swapped:
            swapped = True
            path.rename(path.with_name("record.parked"))
            path.symlink_to(outside)
        return data

    monkeypatch.setattr(os, "read", racing_read)

    assert iter_records(root) == []
    assert swapped
    assert outside.read_bytes()


@pytest.mark.parametrize("ancestor", ["unit", "kind", "units", "kb", "root"])
def test_ancestor_replacement_during_read_excludes_candidate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    ancestor: str,
) -> None:
    root = tmp_path / "workspace"
    path = _write_record(root, "paper", "p-ancestor-123456", title="Original")
    targets = {
        "unit": path.parent,
        "kind": path.parent.parent,
        "units": path.parent.parent.parent,
        "kb": path.parent.parent.parent.parent,
        "root": root,
    }
    target = targets[ancestor]
    parked = target.with_name(f"{target.name}-parked")
    outside = tmp_path / f"outside-{ancestor}"
    outside.mkdir()
    original_open = os.open
    swapped = False

    def racing_open(name, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if name == "record.yaml" and dir_fd is not None and not swapped:
            swapped = True
            target.rename(parked)
            target.symlink_to(outside, target_is_directory=True)
        return original_open(name, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", racing_open)

    assert iter_records(root) == []
    assert swapped
    assert target.is_symlink()


@pytest.mark.parametrize("node_kind", ["directory", "socket", "oversized"])
def test_special_or_oversized_record_does_not_hide_valid_sibling(
    tmp_path: Path,
    node_kind: str,
) -> None:
    short_directory = tempfile.TemporaryDirectory(prefix="rr-", dir="/tmp") if node_kind == "socket" else None
    root = Path(short_directory.name) if short_directory is not None else tmp_path / "workspace"
    _write_record(root, "paper", "p-valid-123456", title="Valid sibling")
    unsafe = record_path(root, "paper", f"p-{node_kind}-123456")
    unsafe.parent.mkdir(parents=True)
    bound_socket = None
    if node_kind == "directory":
        unsafe.mkdir()
    elif node_kind == "socket":
        if not hasattr(socket, "AF_UNIX"):
            pytest.skip("Unix sockets are unavailable")
        bound_socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            bound_socket.bind(str(unsafe))
        except OSError as exc:
            bound_socket.close()
            bound_socket = None
            if exc.errno in {
                errno.EPERM,
                errno.EACCES,
                errno.EAFNOSUPPORT,
                errno.EPROTONOSUPPORT,
            }:
                pytest.skip("Unix-domain socket bind is unavailable in this environment")
            raise
    else:
        record = default_record("paper", title="Oversized", maturity="lightweight")
        record["id"] = "p-oversized-123456"
        write_yaml_if_changed(unsafe, record)
        with unsafe.open("ab") as handle:
            handle.write(b"\n#" + b"x" * records_module._RECORD_MAX_BYTES)
    try:
        assert [record["id"] for record in iter_records(root)] == ["p-valid-123456"]
    finally:
        if bound_socket is not None:
            bound_socket.close()
        if short_directory is not None:
            short_directory.cleanup()


@pytest.mark.parametrize(
    ("directory_kind", "record_kind", "directory_id", "record_id"),
    [
        ("paper", "blog", "p-kind-mismatch-123456", "p-kind-mismatch-123456"),
        ("paper", "paper", "p-id-mismatch-123456", "p-other-123456"),
        ("paper", "paper", "123", 123),
    ],
)
def test_record_identity_must_match_lexical_directories(
    tmp_path: Path,
    directory_kind: str,
    record_kind: str,
    directory_id: str,
    record_id: object,
) -> None:
    root = tmp_path / "workspace"
    record = default_record(record_kind, title="Mismatch", maturity="lightweight")
    record["id"] = record_id
    write_yaml_if_changed(record_path(root, directory_kind, directory_id), record)

    assert iter_records(root) == []


def test_nested_duplicate_verification_key_is_excluded_from_review(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    path = _write_ready_unit(root, "blog", "b-nested-duplicate-123456")
    assert len(discover_pending_judgements(root)) == 1
    text = path.read_text(encoding="utf-8")
    marker = "  verification:\n"
    start = text.index(marker) + len(marker)
    end = text.index("\n", start) + 1
    first_verification_line = text[start:end]
    path.write_text(text[:end] + first_verification_line + text[end:], encoding="utf-8")

    assert iter_records(root) == []
    assert discover_pending_judgements(root) == []


def test_duplicate_record_is_excluded_from_status_portfolio_and_find(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "workspace"
    path = _write_record(root, "paper", "p-shared-set-123456", title="Hidden corrupt record")
    path.write_text(path.read_text(encoding="utf-8") + "title: Hidden corrupt record\n", encoding="utf-8")

    assert iter_records(root) == []
    with pytest.raises(SystemExit, match="not found"):
        locate_record(root, "p-shared-set-123456", fuzzy=False)
    orchestrate = _load_orchestrator()
    assert orchestrate.portfolio_candidate_snapshot(root)["candidate_count"] == 0

    kb = _load_kb_cli()

    def fake_forward(_root, _script, args, *, stream):
        assert stream is False
        stdout = ""
        if "prepare-next-selection" in args:
            stdout = json.dumps(
                {"candidate_snapshot": {"candidates": [], "program_contexts": []}},
                ensure_ascii=False,
            )
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(kb, "forward_command", fake_forward)
    assert kb.handle_status(argparse.Namespace(program=""), root) == 0
    output = capsys.readouterr().out
    assert "知识库尚未收录资料" in output
    assert "Hidden corrupt record" not in output


@pytest.mark.parametrize(
    ("kind", "unit_id"),
    [
        ("paper", "p-ready-123456"),
        ("repo", "r-ready-123456"),
        ("dataset", "d-ready-123456"),
        ("blog", "b-ready-123456"),
    ],
)
def test_existing_verified_unit_review_cards_remain_discoverable(
    tmp_path: Path,
    kind: str,
    unit_id: str,
) -> None:
    root = tmp_path / "workspace"
    _write_ready_unit(root, kind, unit_id)

    cards = discover_pending_judgements(root)

    assert [(card["subject"]["kind"], card["subject"]["id"]) for card in cards] == [(kind, unit_id)]


def test_empty_and_corrupt_bulk_reads_are_pure(tmp_path: Path) -> None:
    empty_root = tmp_path / "empty"
    assert iter_records(empty_root) == []
    assert discover_pending_judgements(empty_root) == []
    assert not empty_root.exists()

    root = tmp_path / "workspace"
    _write_record(root, "paper", "p-valid-123456", title="Valid")
    corrupt = record_path(root, "paper", "p-corrupt-123456")
    corrupt.parent.mkdir(parents=True)
    corrupt.write_text("id: p-corrupt-123456\nkind: paper\npayload:\n  x: 1\n  x: 2\n", encoding="utf-8")
    before = _tree_digest(root)

    assert [record["id"] for record in iter_records(root)] == ["p-valid-123456"]
    assert discover_pending_judgements(root) == []

    assert _tree_digest(root) == before


def test_locate_last_uses_safe_snapshot_mtime_for_legacy_records(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    older = _write_record(root, "paper", "p-older-123456", title="Older")
    newer = _write_record(root, "paper", "p-newer-123456", title="Newer")
    for path, seconds in ((older, 1_700_000_000), (newer, 1_800_000_000)):
        record = records_module.load_yaml(path)
        record["created_at"] = ""
        record["updated_at"] = ""
        record["first_ingested_at"] = ""
        write_yaml_if_changed(path, record)
        os.utime(path, ns=(seconds * 1_000_000_000, seconds * 1_000_000_000))

    record, path = locate_record(root, "last")

    assert record["id"] == "p-newer-123456"
    assert path.name == "record.yaml"


def test_legacy_snapshot_normalization_is_stable_across_runtime_clock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    path = record_path(root, "paper", "p-legacy-123456")
    write_yaml_if_changed(
        path,
        {
            "id": "p-legacy-123456",
            "kind": "paper",
            "title": "Legacy prepared duplicate",
            "status": "active",
            "source": {"original_uri": "https://example.test/legacy"},
            "confirmation_status": "pending_user_confirmation",
            "needs_human_confirmation": True,
            "information_types": ["fact"],
            "payload": {},
        },
    )
    stable_seconds = 1_700_000_000
    os.utime(path, ns=(stable_seconds * 1_000_000_000, stable_seconds * 1_000_000_000))
    monkeypatch.setattr(records_module, "utc_now_iso", lambda: "2026-01-01T00:00:00+00:00")
    prepared, _ = locate_record(root, "p-legacy-123456", kind="paper", fuzzy=False)
    monkeypatch.setattr(records_module, "utc_now_iso", lambda: "2026-01-01T00:00:01+00:00")
    current, _ = locate_record(root, "p-legacy-123456", kind="paper", fuzzy=False)

    assert current == prepared


def test_wrong_field_type_quarantines_only_that_record_across_bulk_consumers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    root = tmp_path / "workspace"
    _write_record(root, "paper", "p-good-123456", title="Usable sibling")
    malformed = default_record("paper", title="Malformed", maturity="lightweight")
    malformed["id"] = "p-bad-123456"
    malformed["information_types"] = 7
    write_yaml_if_changed(record_path(root, "paper", malformed["id"]), malformed)

    records = iter_records(root)

    assert [record["id"] for record in records] == ["p-good-123456"]
    assert [record["id"] for record in search_records(root, "Usable sibling")] == ["p-good-123456"]
    eligible, excluded = select_current_confirmed_survey_records(root, records)
    assert {item["id"] for item in eligible} | {item["id"] for item in excluded} == {"p-good-123456"}
    assert detect_duplicate(root, "paper", "https://example.test/new-paper.pdf") is None

    kb = _load_kb_cli()

    def fake_forward(_root, _script, args, *, stream):
        assert stream is False
        stdout = ""
        if "prepare-next-selection" in args:
            stdout = json.dumps(
                {"candidate_snapshot": {"candidates": [], "program_contexts": []}},
                ensure_ascii=False,
            )
        return subprocess.CompletedProcess(args, 0, stdout=stdout, stderr="")

    monkeypatch.setattr(kb, "forward_command", fake_forward)
    assert kb.handle_status(argparse.Namespace(program=""), root) == 0
    output = capsys.readouterr().out
    assert "知识库目前收录 1 条资料" in output
    assert "Malformed" not in output
    assert "TypeError" not in output


def test_review_discovery_quarantines_malformed_record_without_hiding_ready_sibling(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    _write_ready_unit(root, "blog", "b-ready-sibling-123456")
    malformed = default_record("paper", title="Malformed review candidate", maturity="lightweight")
    malformed["id"] = "p-bad-review-123456"
    malformed["information_types"] = 7
    write_yaml_if_changed(record_path(root, "paper", malformed["id"]), malformed)

    cards = discover_pending_judgements(root)

    assert [card["subject"]["id"] for card in cards] == ["b-ready-sibling-123456"]


@pytest.mark.parametrize("interrupt", [MemoryError("oom"), KeyboardInterrupt(), GeneratorExit()])
def test_record_quarantine_does_not_swallow_process_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    interrupt: BaseException,
) -> None:
    root = tmp_path / "workspace"
    _write_record(root, "paper", "p-interrupt-123456", title="Interrupt")

    def fail_normalization(*args, **kwargs):
        raise interrupt

    monkeypatch.setattr(records_module, "normalize_record_schema", fail_normalization)

    with pytest.raises(type(interrupt)):
        iter_records(root)


def test_locate_last_preserves_one_nanosecond_mtime_order(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    older = _write_record(root, "paper", "p-zolder-123456", title="Older")
    newer = _write_record(root, "paper", "p-anewer-123456", title="Newer")
    for path in (older, newer):
        record = records_module.load_yaml(path)
        record["created_at"] = "2026-01-01T00:00:00+00:00"
        record["first_ingested_at"] = "2026-01-01T00:00:00+00:00"
        record["updated_at"] = "2026-01-01T00:00:00+00:00"
        write_yaml_if_changed(path, record)
    older_ns = 1_800_000_000_000_000_000
    newer_ns = older_ns + 1
    os.utime(older, ns=(older_ns, older_ns))
    os.utime(newer, ns=(newer_ns, newer_ns))

    record, _path = locate_record(root, "last")

    assert record["id"] == "p-anewer-123456"


def test_same_unit_record_replacement_between_discovery_and_evidence_capture_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    path = _write_ready_unit(root, "paper", "p-self-race-123456")
    unit = path.parent
    parked = tmp_path / "parked-self-unit"
    replacement = tmp_path / "replacement-self-unit"
    shutil.copytree(unit, replacement)
    original_capture = records_module.snapshot_canonical_unit_artifacts
    swapped = False

    def racing_capture(project_root, kind, unit_id, artifacts):
        nonlocal swapped
        if unit_id == "p-self-race-123456" and not swapped:
            swapped = True
            unit.rename(parked)
            replacement.rename(unit)
        return original_capture(project_root, kind, unit_id, artifacts)

    monkeypatch.setattr(records_module, "snapshot_canonical_unit_artifacts", racing_capture)

    assert discover_pending_judgements(root) == []
    assert swapped


def test_cross_unit_evidence_rejects_source_symlink_swap_after_candidate_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    source_id = "p-source-race-123456"
    source_path = _write_record(root, "paper", source_id, title="Source")
    source_artifact = source_path.parent / "raw" / "source.txt"
    source_artifact.parent.mkdir()
    source_artifact.write_text("Stable cross-unit evidence.", encoding="utf-8")
    consumer_id = "b-consumer-race-123456"
    consumer_path = _write_ready_unit(root, "blog", consumer_id)
    consumer = records_module.load_yaml(consumer_path)
    consumer["payload"]["claims"][0]["evidence_refs"] = [
        {
            "source_unit_id": source_id,
            "artifact": "raw/source.txt",
            "locator": "line:1",
            "quote": "Stable cross-unit evidence.",
        }
    ]
    build_verification_receipt(
        consumer,
        consumer_path.parent,
        source_roots={source_id: source_path.parent},
    )
    write_yaml_if_changed(consumer_path, consumer)
    outside = tmp_path / "outside-source-unit"
    shutil.copytree(source_path.parent, outside)
    parked = tmp_path / "parked-source-unit"
    original_iter = judgements_module.iter_canonical_record_snapshots
    swapped = False

    def racing_iter(project_root, *, kind=None):
        nonlocal swapped
        snapshots = original_iter(project_root, kind=kind)
        if not swapped:
            swapped = True
            source_path.parent.rename(parked)
            source_path.parent.symlink_to(outside, target_is_directory=True)
        return snapshots

    monkeypatch.setattr(judgements_module, "iter_canonical_record_snapshots", racing_iter)

    assert discover_pending_judgements(root) == []
    assert swapped


def test_cross_unit_snapshot_detects_source_replacement_before_verifier_returns(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    source_id = "p-source-current-123456"
    source_path = _write_record(root, "paper", source_id, title="Source")
    source_artifact = source_path.parent / "raw" / "source.txt"
    source_artifact.parent.mkdir()
    source_artifact.write_text("Bound evidence bytes.", encoding="utf-8")
    consumer_id = "b-consumer-current-123456"
    consumer_path = _write_ready_unit(root, "blog", consumer_id)
    consumer = records_module.load_yaml(consumer_path)
    consumer["payload"]["claims"][0]["evidence_refs"] = [
        {
            "source_unit_id": source_id,
            "artifact": "raw/source.txt",
            "locator": "line:1",
            "quote": "Bound evidence bytes.",
        }
    ]
    build_verification_receipt(
        consumer,
        consumer_path.parent,
        source_roots={source_id: source_path.parent},
    )
    source_roots = trusted_claim_source_roots(root, consumer, verification_root=consumer_path.parent)
    outside = tmp_path / "outside-current-source"
    shutil.copytree(source_path.parent, outside)
    parked = tmp_path / "parked-current-source"
    source_path.parent.rename(parked)
    source_path.parent.symlink_to(outside, target_is_directory=True)

    violations = verification_receipt_violations(
        consumer,
        consumer_path.parent,
        source_roots=source_roots,
    )

    assert any("no longer current" in violation for violation in violations)


def test_cross_unit_artifact_parent_swap_during_open_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "workspace"
    source_id = "p-source-parent-race-123456"
    source_path = _write_record(root, "paper", source_id, title="Source")
    raw = source_path.parent / "raw"
    raw.mkdir()
    (raw / "source.txt").write_text("Original anchored evidence.", encoding="utf-8")
    consumer_path = _write_ready_unit(root, "blog", "b-consumer-parent-race-123456")
    consumer = records_module.load_yaml(consumer_path)
    consumer["payload"]["claims"][0]["evidence_refs"] = [
        {
            "source_unit_id": source_id,
            "artifact": "raw/source.txt",
            "locator": "line:1",
            "quote": "Original anchored evidence.",
        }
    ]
    outside = tmp_path / "outside-raw"
    outside.mkdir()
    (outside / "source.txt").write_text("EXTERNAL_SECRET", encoding="utf-8")
    parked = source_path.parent / "raw-parked"
    original_open = records_module.os.open
    swapped = False

    def racing_open(name, flags, mode=0o777, *, dir_fd=None):
        nonlocal swapped
        if name == "source.txt" and dir_fd is not None and not swapped:
            swapped = True
            raw.rename(parked)
            raw.symlink_to(outside, target_is_directory=True)
        return original_open(name, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(records_module.os, "open", racing_open)

    with pytest.raises(ValueError, match="artifact snapshot"):
        trusted_claim_source_roots(root, consumer, verification_root=consumer_path.parent)
    assert swapped


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO creation is unavailable")
def test_cross_unit_evidence_fifo_is_rejected_without_blocking(tmp_path: Path) -> None:
    root = tmp_path / "workspace"
    source_id = "p-source-fifo-123456"
    source_path = _write_record(root, "paper", source_id, title="FIFO source")
    fifo = source_path.parent / "raw" / "source.txt"
    fifo.parent.mkdir()
    os.mkfifo(fifo)
    code = """
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from research.records import trusted_claim_source_roots
record = {
    'id': 'b-consumer-fifo-123456',
    'kind': 'blog',
    'payload': {'claims': [{
        'evidence_refs': [{
            'source_unit_id': 'p-source-fifo-123456',
            'artifact': 'raw/source.txt',
        }],
    }]},
}
try:
    trusted_claim_source_roots(Path(sys.argv[2]), record)
except ValueError:
    pass
else:
    raise AssertionError('FIFO evidence was accepted')
"""

    result = subprocess.run(
        [sys.executable, "-c", code, str(ROOT / ".agents" / "lib"), str(root)],
        capture_output=True,
        text=True,
        timeout=3,
    )

    assert result.returncode == 0, result.stderr
