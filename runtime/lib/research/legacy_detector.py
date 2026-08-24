"""Read-only detector for layouts that Research Vault v2 must not touch."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path


LEGACY_MIGRATION_GUIDANCE = (
    "检测到旧版知识库布局；Research Vault v2 已停止写入。"
    "请保留原数据并在新的空工作区中初始化 v2。"
)


class LegacyLayoutState(str, Enum):
    NO_LAYOUT = "no-layout"
    LEGACY = "legacy"
    UNSAFE = "unsafe"


@dataclass(frozen=True)
class LegacyLayoutDetection:
    state: LegacyLayoutState
    marker: str = ""


def _kind(path: Path) -> str | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError:
        return "unsafe"
    if stat.S_ISLNK(metadata.st_mode):
        return "symlink"
    if stat.S_ISDIR(metadata.st_mode):
        return "directory"
    if stat.S_ISREG(metadata.st_mode):
        return "file"
    return "special"


def detect_legacy_layout(workspace: Path) -> LegacyLayoutDetection:
    """Classify only known v1 markers, without opening or traversing their data."""

    root = Path(os.path.abspath(os.fspath(workspace)))
    root_kind = _kind(root)
    if root_kind != "directory":
        return LegacyLayoutDetection(LegacyLayoutState.UNSAFE, "workspace-root")

    for relative in (Path("kb"), Path("record.yaml"), Path("config/workspace-layout.yaml")):
        kind = _kind(root / relative)
        if kind is not None:
            return LegacyLayoutDetection(LegacyLayoutState.LEGACY, relative.as_posix())

    obsidian = root / "obsidian"
    obsidian_kind = _kind(obsidian)
    if obsidian_kind not in {None, "directory"}:
        return LegacyLayoutDetection(LegacyLayoutState.UNSAFE, "obsidian")
    if obsidian_kind == "directory" and _kind(obsidian / "managed") is not None:
        return LegacyLayoutDetection(LegacyLayoutState.LEGACY, "obsidian/managed")

    return LegacyLayoutDetection(LegacyLayoutState.NO_LAYOUT)


__all__ = [
    "LEGACY_MIGRATION_GUIDANCE",
    "LegacyLayoutDetection",
    "LegacyLayoutState",
    "detect_legacy_layout",
]
