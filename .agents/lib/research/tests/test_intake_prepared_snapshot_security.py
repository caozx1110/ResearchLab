from __future__ import annotations

import argparse
import importlib.util
import json
import stat
import sys
import time
from pathlib import Path

import pytest

from research.prefs import ensure_workspace


def _load_intake_module():
    root = Path(__file__).resolve().parents[4]
    script = root / ".agents" / "skills" / "source-intake" / "scripts" / "intake.py"
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


def test_consumed_prepared_token_cannot_be_replayed(
    tmp_path: Path,
    monkeypatch,
) -> None:
    intake = _load_intake_module()
    root = tmp_path / "workspace"
    root.mkdir()
    ensure_workspace(root)
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
    ensure_workspace(root)
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
    ensure_workspace(root)
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
    ensure_workspace(root)
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
