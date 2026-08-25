"""Small test-only loaders for the active v2 interfaces."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path
from types import ModuleType


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise AssertionError(f"cannot load test module: {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def load_skill_validator() -> ModuleType:
    path = REPO_ROOT / "tools" / "skill_validator.py"
    if not path.is_file():
        raise AssertionError("the v2 skill validator is missing")
    return load_module("v2_test_skill_validator", path)


def load_ws_sync() -> ModuleType:
    return load_module("v2_test_ws_sync", REPO_ROOT / "install-lib" / "ws_sync.py")


def load_runtime_module(name: str) -> ModuleType:
    allowed = {
        "legacy_detector",
        "updater",
        "v2_bootstrap",
    }
    if name not in allowed:
        raise ValueError(f"not an active v2 runtime module: {name}")
    return load_module(
        f"v2_test_{name}",
        REPO_ROOT / "runtime" / "lib" / "research" / f"{name}.py",
    )


def tree_snapshot(root: Path) -> tuple[tuple[str, int, bytes | str | None], ...]:
    """Record a workspace lexically, without following symlinks."""

    result: list[tuple[str, int, bytes | str | None]] = []
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        directories[:] = sorted(
            name for name in directories if not (current_path / name).is_symlink()
        )
        for name in sorted(files):
            path = current_path / name
            metadata = path.lstat()
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                payload: bytes | str | None = os.readlink(path)
            elif path.is_file():
                payload = path.read_bytes()
            else:
                payload = None
            result.append((relative, metadata.st_mode, payload))
    return tuple(result)
