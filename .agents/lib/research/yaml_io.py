"""YAML and text IO helpers for the research workspace."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any

try:
    import yaml as _yaml
except ModuleNotFoundError:
    _yaml = None


def load_yaml(path: Path, default: Any | None = None) -> Any:
    if not path.exists():
        return default
    text = path.read_text(encoding="utf-8")
    if not text.strip():
        return default
    if _yaml is not None:
        return _yaml.safe_load(text)
    raise RuntimeError(
        "PyYAML is required to read research workspace YAML safely. "
        f"Current runtime cannot parse {path} without risking corrupted metadata."
    )


def dump_yaml(value: Any) -> str:
    if _yaml is None:
        raise RuntimeError("PyYAML is required to write research workspace YAML safely.")
    return _yaml.safe_dump(value, allow_unicode=True, sort_keys=False)


def write_bytes_atomic(path: Path, data: bytes, *, mode: int | None = None) -> None:
    """Atomically replace *path* with exact bytes and an optional POSIX mode."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        if mode is not None:
            os.chmod(temp_path, mode)
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def write_text_if_changed(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.read_text(encoding="utf-8") == text:
        return
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()


def write_yaml_if_changed(path: Path, value: Any) -> None:
    write_text_if_changed(path, dump_yaml(value))


def yaml_duplicate_key_issues(path: Path) -> list[str]:
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [f"{path.as_posix()}: read error: {exc}"]
    if not text.strip() or _yaml is None:
        return []
    try:
        node = _yaml.compose(text)
    except Exception as exc:  # noqa: BLE001
        return [f"{path.as_posix()}: YAML parse error: {exc}"]
    if node is None:
        return []
    issues: list[str] = []

    def walk(current: Any, prefix: str) -> None:
        node_id = getattr(current, "id", "")
        if node_id == "mapping":
            seen: set[str] = set()
            for key_node, value_node in getattr(current, "value", []):
                key = str(getattr(key_node, "value", "<complex-key>"))
                dotted = f"{prefix}.{key}" if prefix else key
                if key in seen:
                    issues.append(f"{path.as_posix()}: duplicate key `{dotted}`")
                else:
                    seen.add(key)
                walk(value_node, dotted)
            return
        if node_id == "sequence":
            for index, item in enumerate(getattr(current, "value", [])):
                child_prefix = f"{prefix}[{index}]" if prefix else f"[{index}]"
                walk(item, child_prefix)

    walk(node, "")
    return issues
