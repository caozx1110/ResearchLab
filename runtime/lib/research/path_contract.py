"""Pure workspace/data-root and logical artifact path contracts.

This module defines the typed roots and path vocabulary shared by the active
workspace-root runtime and the explicit legacy-layout migration boundary.  Its
helpers deliberately perform no mutation and have no dependency on the
high-level ``research.core`` facade.  Layout activation/currentness belongs to
``workspace_layout``; legacy moves belong to ``legacy_migration``.

The no-follow helper is a precondition, not a replacement for descriptor-based
mutation.  A writer must repeat identity checks at its commit boundary so a
successful inspection cannot be reused across a filesystem race.
"""
from __future__ import annotations

import os
import stat
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath
from typing import Collection


LOGICAL_ARTIFACT_PREFIX = "kb"

# These names are the canonical knowledge/artifact surface currently owned by
# the product.  Root-layout integration must extend this inventory deliberately;
# an unknown sibling at workspace root is a collision, never implicit KB data.
CANONICAL_ROOT_FILES = frozenset({".gitignore", "index.md", "index.yaml"})
CANONICAL_ARTIFACT_DIRECTORIES = frozenset(
    {
        "config",
        "eval",
        "memory",
        "monitoring",
        "obsidian",
        "output",
        "programs",
        "raw",
        "synthesis",
        "units",
        "user",
    }
)
CANONICAL_ARTIFACT_TOP_LEVEL = (
    CANONICAL_ROOT_FILES | CANONICAL_ARTIFACT_DIRECTORIES
)

# Operational state has a stable logical identity but is not a business target.
# Downstream journal/runtime owners must opt in explicitly when checking it.
OPERATIONAL_STATE_TOP_LEVEL = frozenset({".journal", ".runtime"})

# Root-layout Git ownership is deliberately narrower than the physical
# workspace.  Keep the anchored ignore contract in this lowest-level module so
# migration and the ordinary runtime share one byte vocabulary without making
# the read-only migration detector import the high-level ``paths`` facade.
PRIVATE_DIAGNOSTIC_PREFIX = "memory/skill-evolution/.private"
WORKSPACE_GITIGNORE_LINES = (
    "# Installed workspace integrations",
    "/.agents/",
    "/.venv/",
    "/.claude/",
    "/bin/",
    "/CLAUDE.md",
    "",
    "# Runtime state",
    "/.runtime/",
    "",
    "# Operation recovery journal",
    "/.journal/",
    "",
    "# Raw and exported artifacts",
    "/raw/",
    "/output/",
    "",
    "# Generated browser workspace",
    "/user/kb/",
    "",
    "# Private local diagnostics",
    f"/{PRIVATE_DIAGNOSTIC_PREFIX}/",
    "",
    "# Generated Obsidian projection",
    "/obsidian/managed/",
    "",
    "# Local noise",
    "/.DS_Store",
)

# These workspace integrations must never become a canonical business,
# transaction, strict-reader, or checkpoint target after the physical root is
# widened.  Case-folded comparison also fails closed on case-insensitive hosts.
RESERVED_WORKSPACE_TOP_LEVEL = frozenset(
    {
        ".agents",
        ".claude",
        ".git",
        ".venv",
        "AGENTS.md",
        "CLAUDE.md",
        "bin",
    }
)
_RESERVED_CASEFOLDED = frozenset(name.casefold() for name in RESERVED_WORKSPACE_TOP_LEVEL)


class PathContractError(ValueError):
    """A path is ambiguous, outside the data root, reserved, or unsafe."""


class DataLayout(str, Enum):
    """Supported physical data-root layouts during the explicit transition."""

    LEGACY_KB_DIRECTORY = "legacy-kb-directory"
    WORKSPACE_ROOT = "workspace-root"


class TargetClass(str, Enum):
    """Lexical ownership class for a data-root-relative target."""

    CANONICAL_ARTIFACT = "canonical-artifact"
    OPERATIONAL_STATE = "operational-state"
    RESERVED = "reserved"
    UNKNOWN = "unknown"


def _absolute_lexical_path(value: str | Path, *, label: str) -> Path:
    text = os.fspath(value)
    if not text or "\x00" in text or "\\" in text:
        raise PathContractError(f"{label} must use an unambiguous native absolute path")
    path = Path(text)
    if not path.is_absolute() or any(part in {".", ".."} for part in path.parts):
        raise PathContractError(f"{label} must be absolute and traversal-free")
    return Path(os.path.normpath(text))


@dataclass(frozen=True)
class RootRoles:
    """Explicit workspace, canonical-data, and product-bundle root roles."""

    workspace_root: Path
    data_root: Path
    product_bundle_root: Path
    layout: DataLayout

    def __post_init__(self) -> None:
        if not isinstance(self.layout, DataLayout):
            raise PathContractError("physical data layout must be a DataLayout value")
        workspace = _absolute_lexical_path(self.workspace_root, label="workspace root")
        data = _absolute_lexical_path(self.data_root, label="canonical data root")
        bundle = _absolute_lexical_path(
            self.product_bundle_root, label="product bundle root"
        )
        expected_data = (
            workspace / "kb"
            if self.layout is DataLayout.LEGACY_KB_DIRECTORY
            else workspace
        )
        if data != expected_data:
            raise PathContractError(
                "canonical data root does not match the declared physical layout"
            )
        object.__setattr__(self, "workspace_root", workspace)
        object.__setattr__(self, "data_root", data)
        object.__setattr__(self, "product_bundle_root", bundle)

    @classmethod
    def for_layout(
        cls,
        workspace_root: str | Path,
        product_bundle_root: str | Path,
        layout: DataLayout,
    ) -> "RootRoles":
        workspace = _absolute_lexical_path(workspace_root, label="workspace root")
        data = (
            workspace / "kb"
            if layout is DataLayout.LEGACY_KB_DIRECTORY
            else workspace
        )
        return cls(
            workspace_root=workspace,
            data_root=data,
            product_bundle_root=Path(product_bundle_root),
            layout=layout,
        )


def _validated_relative_parts(value: str | PurePosixPath) -> tuple[str, ...]:
    text = str(value)
    if (
        not text
        or text != text.strip()
        or "\x00" in text
        or "\\" in text
        or text.startswith("/")
        or text.endswith("/")
    ):
        raise PathContractError("artifact path must be a clean relative POSIX path")
    parts = tuple(text.split("/"))
    if any(part in {"", ".", ".."} for part in parts):
        raise PathContractError("artifact path contains an empty or traversal segment")
    return parts


def classify_data_relative_path(value: str | PurePosixPath) -> TargetClass:
    """Classify one validated data-root-relative lexical path."""

    parts = _validated_relative_parts(value)
    top_level = parts[0]
    if top_level.casefold() in _RESERVED_CASEFOLDED:
        return TargetClass.RESERVED
    if top_level in CANONICAL_ROOT_FILES and len(parts) != 1:
        raise PathContractError("canonical root file cannot have descendants")
    if top_level in CANONICAL_ARTIFACT_TOP_LEVEL:
        return TargetClass.CANONICAL_ARTIFACT
    if top_level in OPERATIONAL_STATE_TOP_LEVEL:
        return TargetClass.OPERATIONAL_STATE
    return TargetClass.UNKNOWN


def validate_logical_artifact_ref(value: str) -> str:
    """Validate and return an unchanged stable ``kb/...`` artifact identity."""

    parts = _validated_relative_parts(value)
    if len(parts) < 2 or parts[0] != LOGICAL_ARTIFACT_PREFIX:
        raise PathContractError("logical artifact reference must start with 'kb/'")
    relative = PurePosixPath(*parts[1:])
    target_class = classify_data_relative_path(relative)
    if target_class is TargetClass.RESERVED:
        raise PathContractError("logical artifact reference names a reserved workspace path")
    if target_class is TargetClass.UNKNOWN:
        raise PathContractError("logical artifact reference has an unknown top-level name")
    return value


def logical_ref_to_physical_path(roots: RootRoles, value: str) -> Path:
    """Map a stable logical reference onto the declared physical data root."""

    validated = validate_logical_artifact_ref(value)
    parts = validated.split("/")[1:]
    return roots.data_root.joinpath(*parts)


def _physical_relative_path(roots: RootRoles, value: str | Path) -> PurePosixPath:
    target = _absolute_lexical_path(value, label="physical artifact path")
    try:
        relative = target.relative_to(roots.data_root)
    except ValueError as exc:
        raise PathContractError("physical artifact path escaped the canonical data root") from exc
    if relative == Path("."):
        raise PathContractError("the canonical data root itself is not an artifact")
    return PurePosixPath(*relative.parts)


def physical_path_to_logical_ref(roots: RootRoles, value: str | Path) -> str:
    """Map a contained physical artifact path to its stable logical identity."""

    relative = _physical_relative_path(roots, value)
    logical = f"{LOGICAL_ARTIFACT_PREFIX}/{relative.as_posix()}"
    return validate_logical_artifact_ref(logical)


@dataclass(frozen=True)
class TargetAssessment:
    """Result of a successful lexical and no-follow target precondition."""

    physical_path: Path
    data_relative_path: PurePosixPath
    logical_ref: str
    target_class: TargetClass


def _assert_existing_chain_no_follow(data_root: Path, relative: PurePosixPath) -> None:
    chain = (
        data_root,
        *(
            data_root.joinpath(*relative.parts[:index])
            for index in range(1, len(relative.parts) + 1)
        ),
    )
    for index, candidate in enumerate(chain):
        try:
            metadata = candidate.lstat()
        except FileNotFoundError:
            if index == 0:
                raise PathContractError("canonical data root does not exist")
            # Once an ancestor is missing, no deeper component can currently
            # exist.  Descriptor-based writers must still create/recheck it.
            return
        except OSError as exc:
            raise PathContractError("could not inspect artifact target without following links") from exc
        if stat.S_ISLNK(metadata.st_mode):
            raise PathContractError("artifact target has a symlink root, ancestor, or leaf")
        is_leaf = index == len(chain) - 1
        if not is_leaf and not stat.S_ISDIR(metadata.st_mode):
            raise PathContractError("artifact target ancestor is not a directory")
        if is_leaf and not (
            stat.S_ISDIR(metadata.st_mode) or stat.S_ISREG(metadata.st_mode)
        ):
            raise PathContractError("artifact target leaf is a special filesystem node")


def assert_no_follow_target(
    roots: RootRoles,
    value: str | Path,
    *,
    allowed_classes: Collection[TargetClass] = (TargetClass.CANONICAL_ARTIFACT,),
) -> TargetAssessment:
    """Fail closed on containment, ownership, symlinks, and special nodes.

    The function is read-only.  Callers that mutate must use the returned exact
    identity only inside an atomic/no-follow operation that revalidates it.
    """

    relative = _physical_relative_path(roots, value)
    target_class = classify_data_relative_path(relative)
    if target_class is TargetClass.RESERVED:
        raise PathContractError("artifact target is reserved for workspace integration")
    if target_class is TargetClass.UNKNOWN:
        raise PathContractError("artifact target has an unknown top-level name")
    if target_class not in frozenset(allowed_classes):
        raise PathContractError("artifact target class is not allowed for this owner")
    _assert_existing_chain_no_follow(roots.data_root, relative)
    physical = roots.data_root.joinpath(*relative.parts)
    return TargetAssessment(
        physical_path=physical,
        data_relative_path=relative,
        logical_ref=physical_path_to_logical_ref(roots, physical),
        target_class=target_class,
    )


__all__ = [
    "CANONICAL_ARTIFACT_DIRECTORIES",
    "CANONICAL_ARTIFACT_TOP_LEVEL",
    "CANONICAL_ROOT_FILES",
    "DataLayout",
    "LOGICAL_ARTIFACT_PREFIX",
    "OPERATIONAL_STATE_TOP_LEVEL",
    "PathContractError",
    "PRIVATE_DIAGNOSTIC_PREFIX",
    "RESERVED_WORKSPACE_TOP_LEVEL",
    "RootRoles",
    "TargetAssessment",
    "TargetClass",
    "assert_no_follow_target",
    "classify_data_relative_path",
    "logical_ref_to_physical_path",
    "physical_path_to_logical_ref",
    "validate_logical_artifact_ref",
    "WORKSPACE_GITIGNORE_LINES",
]
