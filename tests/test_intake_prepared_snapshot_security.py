from __future__ import annotations

from repo_paths import initialize_test_workspace

import argparse
import importlib.util
import json
import os
import stat
import sys
import time
from pathlib import Path

from repo_paths import REPO_ROOT

import pytest

from research.prefs import ensure_workspace
from research.path_contract import CANONICAL_ARTIFACT_TOP_LEVEL, OPERATIONAL_STATE_TOP_LEVEL


def _load_intake_module():
    root = REPO_ROOT
    script = root / "skills" / "source-intake" / "scripts" / "intake.py"
    spec = importlib.util.spec_from_file_location("source_intake_prepared_security", script)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _args(root: Path) -> argparse.Namespace:
    source = root / "blog.md"
    source.write_text("# Blog\n\nFrozen source bytes.\n", encoding="utf-8")
    return argparse.Namespace(
        command="prepare-add",
        kind="blog",
        source=str(source),
        maturity="lightweight",
        title="Frozen Blog",
        stage_id="",
        candidate_id="",
        pool=[],
        user_authorization="",
        authorization_source="",
    )


def _argv(root: Path, args: argparse.Namespace, token: str) -> list[str]:
    return [
        "intake.py",
        "--root",
        str(root),
        "add",
        "--kind",
        args.kind,
        "--source",
        args.source,
        "--title",
        args.title,
        "--prepared-intake-token",
        token,
    ]


def _snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def _owned_snapshot(root: Path) -> dict[str, bytes]:
    owned = set(CANONICAL_ARTIFACT_TOP_LEVEL) | set(OPERATIONAL_STATE_TOP_LEVEL)
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
        and path.relative_to(root).parts
        and path.relative_to(root).parts[0] in owned
    }


def test_consumed_prepared_token_cannot_be_replayed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    intake = _load_intake_module()
    root = tmp_path / "workspace"
    root.mkdir()
    initialize_test_workspace(root)
    args = _args(root)
    prepared = intake._prepare_intake_snapshot(root, args)
    token = str(prepared["token"])
    prepared_root = intake._prepared_dir(root, token)
    assert stat.S_IMODE(prepared_root.stat().st_mode) == 0o700
    monkeypatch.setattr(intake, "checkpoint_and_report", lambda *_args, **_kwargs: {})
    monkeypatch.setattr(sys, "argv", _argv(root, args, token))

    assert intake.main() == 0
    assert not prepared_root.exists()
    after_success = _snapshot(root)
    monkeypatch.setattr(sys, "argv", _argv(root, args, token))

    with pytest.raises(SystemExit, match="unavailable"):
        intake.main()

    assert _snapshot(root) == after_success


def test_expired_prepared_snapshot_rejects_without_workspace_write_and_cleans_up(
    tmp_path: Path,
    monkeypatch,
) -> None:
    intake = _load_intake_module()
    root = tmp_path / "workspace"
    root.mkdir()
    initialize_test_workspace(root)
    args = _args(root)
    prepared = intake._prepare_intake_snapshot(root, args)
    token = str(prepared["token"])
    prepared_root = intake._prepared_dir(root, token)
    manifest_path = prepared_root / "prepared.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["created_at_epoch"] = int(time.time()) - intake.PREPARED_INTAKE_TTL_SECONDS - 1
    manifest.pop("manifest_digest")
    manifest["manifest_digest"] = intake._canonical_digest(manifest)
    intake._write_prepared_manifest(manifest_path, manifest)
    before = _snapshot(root)
    monkeypatch.setattr(sys, "argv", _argv(root, args, token))

    with pytest.raises(SystemExit, match="expired"):
        intake.main()

    assert _snapshot(root) == before
    assert not prepared_root.exists()


def test_symlink_swap_inside_prepared_stage_is_nofollow_and_zero_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    intake = _load_intake_module()
    root = tmp_path / "workspace"
    root.mkdir()
    initialize_test_workspace(root)
    args = _args(root)
    prepared = intake._prepare_intake_snapshot(root, args)
    token = str(prepared["token"])
    prepared_root = intake._prepared_dir(root, token)
    stage_dir = prepared_root / str(prepared["stage_relative"])
    archived = next(path for path in (stage_dir / "source").iterdir() if path.is_file())
    outside = tmp_path / "outside-secret.txt"
    outside.write_text("must remain unread and unchanged", encoding="utf-8")
    archived.unlink()
    archived.symlink_to(outside)
    before = _snapshot(root)
    monkeypatch.setattr(sys, "argv", _argv(root, args, token))

    with pytest.raises(ValueError, match="symlink"):
        intake.main()

    assert _snapshot(root) == before
    assert outside.read_text(encoding="utf-8") == "must remain unread and unchanged"
    assert not prepared_root.exists()


def test_prepare_failure_leaves_no_workspace_or_external_stage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    intake = _load_intake_module()
    root = tmp_path / "workspace"
    root.mkdir()
    initialize_test_workspace(root)
    args = _args(root)
    before = _snapshot(root)
    monkeypatch.setattr(
        intake,
        "backup_source",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("injected parse failure")),
    )
    monkeypatch.setattr(sys, "argv", _argv(root, args, "")[:-2])

    with pytest.raises(SystemExit, match="retry is safe: injected parse failure"):
        intake.main()

    assert _snapshot(root) == before
    assert not list(root.parent.glob(f".research-intake-{intake._prepared_scope(root)}-*"))


def test_uninitialized_workspace_refuses_before_write(
    tmp_path: Path,
    monkeypatch,
) -> None:
    intake = _load_intake_module()
    root = tmp_path / "workspace"
    root.mkdir()
    args = _args(root)
    before = _snapshot(root)
    argv = _argv(root, args, "")[:-2]
    argv.extend(["--preference-selection-id", "prefsel-does-not-exist"])
    monkeypatch.setattr(sys, "argv", argv)

    with pytest.raises(SystemExit, match="kb init"):
        intake.main()

    assert _snapshot(root) == before
    assert not (root / "kb").exists()
    assert not list(root.parent.glob(f".research-intake-{intake._prepared_scope(root)}-*"))


def test_source_mutation_during_preference_resolution_is_caught_by_second_revalidation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    intake = _load_intake_module()
    root = tmp_path / "workspace"
    root.mkdir()
    initialize_test_workspace(root)
    args = _args(root)
    source = Path(args.source)
    prepared = intake._prepare_intake_snapshot(root, args)
    token = str(prepared["token"])
    before_kb = _owned_snapshot(root)
    original = intake.resolve_intake_preferences

    def mutate_after_resolution(*call_args, **call_kwargs):
        result = original(*call_args, **call_kwargs)
        source.write_text("# Blog\n\nMutated during resolution.\n", encoding="utf-8")
        return result

    monkeypatch.setattr(intake, "resolve_intake_preferences", mutate_after_resolution)
    monkeypatch.setattr(sys, "argv", _argv(root, args, token))

    with pytest.raises(SystemExit, match="changed after preparation"):
        intake.main()

    assert _owned_snapshot(root) == before_kb
    assert not intake._prepared_dir(root, token).exists()
    assert not list((root / "units/blogs").glob("*/record.yaml"))


def test_snapshot_digest_enforces_file_entry_and_total_byte_budgets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake_module()
    large = tmp_path / "large.bin"
    large.write_bytes(b"x" * 9)
    monkeypatch.setattr(intake, "PREPARED_MAX_FILE_BYTES", 8)
    with pytest.raises(ValueError, match="byte budget"):
        intake._path_snapshot_digest(large)

    entries = tmp_path / "entries"
    entries.mkdir()
    for name in ("a", "b", "c"):
        (entries / name).write_text(name, encoding="utf-8")
    monkeypatch.setattr(intake, "PREPARED_MAX_FILE_BYTES", 64)
    monkeypatch.setattr(intake, "PREPARED_MAX_ENTRIES", 2)
    with pytest.raises(ValueError, match="entry budget"):
        intake._path_snapshot_digest(entries)

    total = tmp_path / "total"
    total.mkdir()
    (total / "a").write_bytes(b"a" * 6)
    (total / "b").write_bytes(b"b" * 6)
    monkeypatch.setattr(intake, "PREPARED_MAX_ENTRIES", 20)
    monkeypatch.setattr(intake, "PREPARED_MAX_TOTAL_BYTES", 10)
    with pytest.raises(ValueError, match="byte budget"):
        intake._path_snapshot_digest(total)


def test_snapshot_digest_rejects_root_inode_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    intake = _load_intake_module()
    source = tmp_path / "source.bin"
    source.write_bytes(b"old")
    original_stream = intake._stream_regular_file
    replaced = False

    def replacing_stream(*args: object, **kwargs: object) -> tuple[dict[str, object], str]:
        nonlocal replaced
        result = original_stream(*args, **kwargs)
        if not replaced:
            replacement = tmp_path / "replacement.bin"
            replacement.write_bytes(b"new")
            os.replace(replacement, source)
            replaced = True
        return result

    monkeypatch.setattr(intake, "_stream_regular_file", replacing_stream)
    with pytest.raises(ValueError, match="changed while it was read"):
        intake._path_snapshot_digest(source)
