"""Record schema: templates, payload skeletons, normalization, history, and store access (iter/locate)."""
from __future__ import annotations

import copy
import hashlib
import os
import re
import stat
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence

from .common import (
    load_yaml,
    parse_iso_datetime,
    utc_now_iso,
)
from .evidence import (
    EvidenceArtifactSnapshot,
    EvidenceSourceSnapshot,
    JUDGEMENT_CLAIM_TYPES,
    UNCONFIRMABLE_CLAIM_TYPES,
    confirmation_claims,
    confirmation_content_digest,
    record_external_source_contract,
    validate_claims,
    verification_receipt_violations,
)
from .ids import (
    build_unit_id,
)
from .journal import mutation_transaction
from .relations import normalize_links
from .paths import (
    UNIT_KIND_DIRS,
    _artifact_list,
    _deep_fill_missing,
    _slug_list,
    _text_list,
    _unique_text_list,
    kind_dir,
    record_path,
    unit_root,
    units_root,
)
from .yaml_io import StrictYamlError, load_yaml_mapping_bytes_strict

INFORMATION_TYPES = {"fact", "inference", "evaluation", "user_opinion", "unverified"}


MATURITY_LEVELS = {"lightweight", "complete"}


DEFAULT_REUSE_FLAGS = {
    "review": False,
    "idea": False,
    "experiment_design": False,
    "paper_writing": False,
    "weekly_report": False,
    "ppt": False,
}


AI_INFORMATION_TYPES = {"inference", "evaluation", "user_opinion"}
WORKFLOW_STATES = {
    "source_ready",
    "awaiting_agent_fill",
    "ready_to_verify",
    "ready_for_review",
    "done",
    "failed_retryable",
}

_RECORD_MAX_BYTES = 8 * 1024 * 1024
_ARTIFACT_MAX_BYTES = 50 * 1024 * 1024
_UNIT_ARTIFACT_TOTAL_MAX_BYTES = 64 * 1024 * 1024
_UNIT_TREE_MAX_ENTRIES = 4096
_UNIT_TREE_MAX_DEPTH = 16
_SAFE_UNIT_DIRECTORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,254}")
_SAFE_EVIDENCE_SOURCE_KIND = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}")


@dataclass(frozen=True)
class CanonicalRecordSnapshot:
    """One record parsed from the same anchored, immutable byte snapshot."""

    kind: str
    unit_id: str
    path: Path
    raw_bytes: bytes
    modified_time_ns: int
    record: dict[str, Any]
    file_identity: tuple[int, int, int, int, int, int]
    directory_capabilities: tuple[tuple[int, int, int], ...]


@dataclass(frozen=True)
class CanonicalUnitSnapshot:
    """One record and selected artifacts captured under the same unit dirfd."""

    record: CanonicalRecordSnapshot
    artifacts: tuple[EvidenceArtifactSnapshot, ...]
    validate_current: Callable[[], bool]

    def is_current(self) -> bool:
        try:
            return bool(self.validate_current())
        except (OSError, ValueError):
            return False


@dataclass(frozen=True)
class ProjectFileSnapshot:
    """Immutable bytes read through one anchored workspace-relative path."""

    project_root: Path
    relative_path: str
    path: Path
    raw_bytes: bytes
    byte_sha256: str
    modified_time_ns: int
    file_identity: tuple[int, int, int, int, int, int]
    directory_capabilities: tuple[tuple[int, int, int], ...]
    validate_current: Callable[[], bool] = field(repr=False, compare=False)

    def is_current(self) -> bool:
        try:
            return bool(self.validate_current())
        except (OSError, ValueError):
            return False


@dataclass(frozen=True)
class ProjectYamlMappingSnapshot:
    """A strict YAML mapping parsed from one exact project-file snapshot."""

    file: ProjectFileSnapshot
    payload: dict[str, Any]

    @property
    def path(self) -> Path:
        return self.file.path

    @property
    def raw_bytes(self) -> bytes:
        return self.file.raw_bytes

    def is_current(self) -> bool:
        return self.file.is_current()


@dataclass(frozen=True)
class _AnchoredDirectory:
    fd: int
    identity: tuple[int, int, int, int, int, int]
    parent_fd: int | None
    name: str | None


def _record_stat_identity(metadata: os.stat_result) -> tuple[int, int, int, int, int, int]:
    return (
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_mode,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def _open_root_directory(path: Path) -> _AnchoredDirectory | None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        lexical = os.lstat(path)
        if not stat.S_ISDIR(lexical.st_mode):
            return None
        fd = os.open(path, flags)
    except OSError:
        return None
    try:
        opened = os.fstat(fd)
    except OSError:
        os.close(fd)
        return None
    if _record_stat_identity(opened) != _record_stat_identity(lexical):
        os.close(fd)
        return None
    return _AnchoredDirectory(fd, _record_stat_identity(opened), None, None)


def _open_child_directory(parent: _AnchoredDirectory, name: str) -> _AnchoredDirectory | None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        lexical = os.stat(name, dir_fd=parent.fd, follow_symlinks=False)
        if not stat.S_ISDIR(lexical.st_mode):
            return None
        fd = os.open(name, flags, dir_fd=parent.fd)
    except OSError:
        return None
    try:
        opened = os.fstat(fd)
    except OSError:
        os.close(fd)
        return None
    if _record_stat_identity(opened) != _record_stat_identity(lexical):
        os.close(fd)
        return None
    return _AnchoredDirectory(fd, _record_stat_identity(opened), parent.fd, name)


def _anchored_chain_is_current(root_path: Path, chain: Sequence[_AnchoredDirectory]) -> bool:
    for index, directory in enumerate(chain):
        try:
            opened = os.fstat(directory.fd)
            if _record_stat_identity(opened) != directory.identity:
                return False
            if index == 0:
                visible = os.lstat(root_path)
            else:
                if directory.parent_fd is None or directory.name is None:
                    return False
                visible = os.stat(
                    directory.name,
                    dir_fd=directory.parent_fd,
                    follow_symlinks=False,
                )
        except OSError:
            return False
        if _record_stat_identity(visible) != directory.identity:
            return False
    return True


def _read_record_snapshot(
    root_path: Path,
    chain: Sequence[_AnchoredDirectory],
    *,
    kind: str,
    unit_id: str,
) -> CanonicalRecordSnapshot | None:
    unit_directory = chain[-1]
    file_flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        lexical_before = os.stat("record.yaml", dir_fd=unit_directory.fd, follow_symlinks=False)
        if not stat.S_ISREG(lexical_before.st_mode) or lexical_before.st_size > _RECORD_MAX_BYTES:
            return None
        leaf_fd = os.open("record.yaml", file_flags, dir_fd=unit_directory.fd)
    except OSError:
        return None
    try:
        opened_before = os.fstat(leaf_fd)
        expected = _record_stat_identity(lexical_before)
        if not stat.S_ISREG(opened_before.st_mode) or _record_stat_identity(opened_before) != expected:
            return None
        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = _RECORD_MAX_BYTES + 1 - total
            if remaining <= 0:
                return None
            chunk = os.read(leaf_fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > _RECORD_MAX_BYTES:
                return None
        opened_after = os.fstat(leaf_fd)
    except OSError:
        return None
    finally:
        os.close(leaf_fd)
    try:
        lexical_after = os.stat("record.yaml", dir_fd=unit_directory.fd, follow_symlinks=False)
    except OSError:
        return None
    if (
        _record_stat_identity(opened_after) != expected
        or _record_stat_identity(lexical_after) != expected
        or total != opened_after.st_size
        or not _anchored_chain_is_current(root_path, chain)
    ):
        return None
    raw_bytes = b"".join(chunks)
    try:
        payload = load_yaml_mapping_bytes_strict(raw_bytes)
    except (RuntimeError, StrictYamlError):
        return None
    if (
        not isinstance(payload.get("kind"), str)
        or not isinstance(payload.get("id"), str)
        or payload["kind"] != kind
        or payload["id"] != unit_id
    ):
        return None
    if not _anchored_chain_is_current(root_path, chain):
        return None
    return CanonicalRecordSnapshot(
        kind=kind,
        unit_id=unit_id,
        path=root_path / "kb" / "units" / UNIT_KIND_DIRS[kind] / unit_id / "record.yaml",
        raw_bytes=raw_bytes,
        modified_time_ns=opened_after.st_mtime_ns,
        record=payload,
        file_identity=expected,
        directory_capabilities=_directory_capability_chain(chain),
    )


def _canonical_artifact_parts(artifact: str) -> tuple[str, tuple[str, ...]]:
    value = str(artifact or "").strip()
    if (
        not value
        or "\x00" in value
        or Path(value).is_absolute()
        or value.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:[\\/]", value) is not None
    ):
        raise ValueError("artifact is not a canonical relative path")
    parts = Path(value).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("artifact is not a canonical relative path")
    return Path(*parts).as_posix(), tuple(parts)


def _read_anchored_leaf(
    root_path: Path,
    chain: Sequence[_AnchoredDirectory],
    name: str,
    *,
    max_bytes: int,
) -> tuple[bytes, tuple[int, int, int, int, int, int]] | None:
    directory = chain[-1]
    flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        lexical_before = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
        if not stat.S_ISREG(lexical_before.st_mode) or lexical_before.st_size > max_bytes:
            return None
        leaf_fd = os.open(name, flags, dir_fd=directory.fd)
    except OSError:
        return None
    expected = _record_stat_identity(lexical_before)
    try:
        opened_before = os.fstat(leaf_fd)
        if not stat.S_ISREG(opened_before.st_mode) or _record_stat_identity(opened_before) != expected:
            return None
        chunks: list[bytes] = []
        total = 0
        while True:
            remaining = max_bytes + 1 - total
            if remaining <= 0:
                return None
            chunk = os.read(leaf_fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                return None
        opened_after = os.fstat(leaf_fd)
    except OSError:
        return None
    finally:
        os.close(leaf_fd)
    try:
        lexical_after = os.stat(name, dir_fd=directory.fd, follow_symlinks=False)
    except OSError:
        return None
    if (
        _record_stat_identity(opened_after) != expected
        or _record_stat_identity(lexical_after) != expected
        or total != opened_after.st_size
        or not _anchored_chain_is_current(root_path, chain)
    ):
        return None
    return b"".join(chunks), expected


def _open_exact_unit_chain(
    project_root: Path,
    kind: str,
    unit_id: str,
) -> tuple[Path, list[_AnchoredDirectory]] | None:
    if kind not in UNIT_KIND_DIRS or _SAFE_UNIT_DIRECTORY.fullmatch(unit_id) is None:
        return None
    root_path = project_root.absolute()
    root_directory = _open_root_directory(root_path)
    if root_directory is None:
        return None
    chain = [root_directory]
    for component in ("kb", "units", UNIT_KIND_DIRS[kind], unit_id):
        child = _open_child_directory(chain[-1], component)
        if child is None:
            for directory in reversed(chain):
                os.close(directory.fd)
            return None
        chain.append(child)
    return root_path, chain


def _close_anchored_chain(chain: Sequence[_AnchoredDirectory]) -> None:
    for directory in reversed(chain):
        os.close(directory.fd)


def _directory_capability_chain(
    chain: Sequence[_AnchoredDirectory],
) -> tuple[tuple[int, int, int], ...]:
    """Bind directory objects without making sibling mtime changes semantic."""
    return tuple(
        (directory.identity[0], directory.identity[1], directory.identity[2])
        for directory in chain
    )


def _canonical_project_parts(relative_path: str | Path) -> tuple[str, tuple[str, ...]]:
    value = str(relative_path or "").strip()
    if (
        not value
        or "\x00" in value
        or Path(value).is_absolute()
        or value.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:[\\/]", value) is not None
    ):
        raise ValueError("project path is not canonical and relative")
    parts = Path(value).parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise ValueError("project path contains an unsafe component")
    return Path(*parts).as_posix(), tuple(parts)


def _open_project_directory_chain(
    project_root: Path,
    relative_parts: Sequence[str],
) -> tuple[Path, list[_AnchoredDirectory]] | None:
    root_path = project_root.absolute()
    root_directory = _open_root_directory(root_path)
    if root_directory is None:
        return None
    chain = [root_directory]
    for component in relative_parts:
        child = _open_child_directory(chain[-1], component)
        if child is None:
            _close_anchored_chain(chain)
            return None
        chain.append(child)
    return root_path, chain


def snapshot_project_file(
    project_root: Path,
    relative_path: str | Path,
    *,
    max_bytes: int = _RECORD_MAX_BYTES,
) -> ProjectFileSnapshot | None:
    """Capture one bounded ordinary file without reopening a validated path."""
    if not isinstance(max_bytes, int) or max_bytes < 0 or max_bytes > _ARTIFACT_MAX_BYTES:
        raise ValueError("project file byte ceiling is outside the supported bound")
    try:
        canonical, parts = _canonical_project_parts(relative_path)
    except ValueError:
        return None
    opened = _open_project_directory_chain(project_root, parts[:-1])
    if opened is None:
        return None
    root_path, chain = opened
    try:
        payload = _read_anchored_leaf(
            root_path,
            chain,
            parts[-1],
            max_bytes=max_bytes,
        )
        if payload is None:
            return None
        raw_bytes, file_identity = payload
        directory_capabilities = _directory_capability_chain(chain)

        def validate_current() -> bool:
            current = _open_project_directory_chain(root_path, parts[:-1])
            if current is None:
                return False
            current_root, current_chain = current
            try:
                if _directory_capability_chain(current_chain) != directory_capabilities:
                    return False
                current_payload = _read_anchored_leaf(
                    current_root,
                    current_chain,
                    parts[-1],
                    max_bytes=max_bytes,
                )
                return current_payload == (raw_bytes, file_identity)
            finally:
                _close_anchored_chain(current_chain)

        return ProjectFileSnapshot(
            project_root=root_path,
            relative_path=canonical,
            path=root_path / canonical,
            raw_bytes=raw_bytes,
            byte_sha256=hashlib.sha256(raw_bytes).hexdigest(),
            modified_time_ns=file_identity[4],
            file_identity=file_identity,
            directory_capabilities=directory_capabilities,
            validate_current=validate_current,
        )
    finally:
        _close_anchored_chain(chain)


def snapshot_project_yaml_mapping(
    project_root: Path,
    relative_path: str | Path,
    *,
    max_bytes: int = _RECORD_MAX_BYTES,
) -> ProjectYamlMappingSnapshot | None:
    """Capture and strict-parse one bounded project-local YAML mapping."""
    snapshot = snapshot_project_file(
        project_root,
        relative_path,
        max_bytes=max_bytes,
    )
    if snapshot is None:
        return None
    try:
        payload = load_yaml_mapping_bytes_strict(snapshot.raw_bytes)
    except (RuntimeError, StrictYamlError):
        return None
    if not snapshot.is_current():
        return None
    return ProjectYamlMappingSnapshot(file=snapshot, payload=payload)


def _read_project_artifact_from_chain(
    root_path: Path,
    base_chain: Sequence[_AnchoredDirectory],
    *,
    base_parts: Sequence[str],
    source_unit_id: str,
    artifact: str,
) -> EvidenceArtifactSnapshot | None:
    try:
        canonical, parts = _canonical_artifact_parts(artifact)
    except ValueError:
        return None
    chain = list(base_chain)
    opened_children: list[_AnchoredDirectory] = []
    try:
        for component in parts[:-1]:
            child = _open_child_directory(chain[-1], component)
            if child is None:
                return None
            opened_children.append(child)
            chain.append(child)
        payload = _read_anchored_leaf(
            root_path,
            chain,
            parts[-1],
            max_bytes=_ARTIFACT_MAX_BYTES,
        )
        if payload is None:
            return None
        raw_bytes, file_identity = payload
        return EvidenceArtifactSnapshot(
            source_unit_id=source_unit_id,
            artifact=canonical,
            raw_bytes=raw_bytes,
            byte_sha256=hashlib.sha256(raw_bytes).hexdigest(),
            path=root_path / Path(*base_parts) / canonical,
            directory_identities=tuple(item.identity for item in opened_children),
            file_identity=file_identity,
        )
    finally:
        for directory in reversed(opened_children):
            os.close(directory.fd)


def snapshot_project_evidence_source(
    project_root: Path,
    base_relative_path: str | Path,
    *,
    source_unit_id: str,
    kind: str,
    artifacts: Sequence[str],
) -> EvidenceSourceSnapshot | None:
    """Capture selected artifacts beneath one shared anchored project directory."""
    if (
        not isinstance(source_unit_id, str)
        or not source_unit_id
        or source_unit_id != source_unit_id.strip()
        or not isinstance(kind, str)
        or _SAFE_EVIDENCE_SOURCE_KIND.fullmatch(kind) is None
        or isinstance(artifacts, (str, bytes, bytearray))
        or not isinstance(artifacts, Sequence)
        or not artifacts
        or any(not isinstance(item, str) for item in artifacts)
    ):
        return None
    identity_parts = source_unit_id.split(":")
    if not 1 <= len(identity_parts) <= 2 or any(
        _SAFE_UNIT_DIRECTORY.fullmatch(part) is None for part in identity_parts
    ):
        return None
    try:
        canonical_base, base_parts = _canonical_project_parts(base_relative_path)
        requested = sorted({_canonical_artifact_parts(item)[0] for item in artifacts})
    except ValueError:
        return None
    if len(requested) > _UNIT_TREE_MAX_ENTRIES:
        return None
    opened = _open_project_directory_chain(project_root, base_parts)
    if opened is None:
        return None
    root_path, chain = opened
    try:
        base_capabilities = _directory_capability_chain(chain)
        snapshots: list[EvidenceArtifactSnapshot] = []
        total = 0
        for artifact in requested:
            snapshot = _read_project_artifact_from_chain(
                root_path,
                chain,
                base_parts=base_parts,
                source_unit_id=source_unit_id,
                artifact=artifact,
            )
            if snapshot is None:
                return None
            total += len(snapshot.raw_bytes)
            if total > _UNIT_ARTIFACT_TOTAL_MAX_BYTES:
                return None
            snapshots.append(snapshot)
        captured = tuple(snapshots)

        def recapture_artifacts(
            current_root: Path,
            current_chain: Sequence[_AnchoredDirectory],
        ) -> tuple[EvidenceArtifactSnapshot, ...] | None:
            current_snapshots: list[EvidenceArtifactSnapshot] = []
            for item in captured:
                current_snapshot = _read_project_artifact_from_chain(
                    current_root,
                    current_chain,
                    base_parts=base_parts,
                    source_unit_id=source_unit_id,
                    artifact=item.artifact,
                )
                if current_snapshot is None:
                    return None
                current_snapshots.append(current_snapshot)
            return tuple(current_snapshots)

        def artifacts_match(
            current: tuple[EvidenceArtifactSnapshot, ...] | None,
        ) -> bool:
            if current is None or len(current) != len(captured):
                return False
            return all(
                (
                    current_item.source_unit_id,
                    current_item.artifact,
                    current_item.raw_bytes,
                    current_item.byte_sha256,
                    current_item.path,
                    tuple(identity[:3] for identity in current_item.directory_identities),
                    current_item.file_identity,
                )
                == (
                    captured_item.source_unit_id,
                    captured_item.artifact,
                    captured_item.raw_bytes,
                    captured_item.byte_sha256,
                    captured_item.path,
                    tuple(identity[:3] for identity in captured_item.directory_identities),
                    captured_item.file_identity,
                )
                for current_item, captured_item in zip(current, captured)
            )

        if (
            not artifacts_match(recapture_artifacts(root_path, chain))
            or not _anchored_chain_is_current(root_path, chain)
        ):
            return None

        def validate_current() -> bool:
            current = _open_project_directory_chain(root_path, base_parts)
            if current is None:
                return False
            current_root, current_chain = current
            try:
                return (
                    _directory_capability_chain(current_chain) == base_capabilities
                    and artifacts_match(recapture_artifacts(current_root, current_chain))
                    and _anchored_chain_is_current(current_root, current_chain)
                )
            finally:
                _close_anchored_chain(current_chain)

        return EvidenceSourceSnapshot(
            source_unit_id=source_unit_id,
            kind=kind,
            artifacts=captured,
            path=root_path / canonical_base,
            validate_current=validate_current,
        )
    finally:
        _close_anchored_chain(chain)


def _record_snapshot_is_current(
    root_path: Path,
    chain: Sequence[_AnchoredDirectory],
    snapshot: CanonicalRecordSnapshot,
) -> bool:
    try:
        visible = os.stat("record.yaml", dir_fd=chain[-1].fd, follow_symlinks=False)
    except OSError:
        return False
    return (
        _record_stat_identity(visible) == snapshot.file_identity
        and _anchored_chain_is_current(root_path, chain)
    )


def _read_artifact_from_unit_chain(
    root_path: Path,
    unit_chain: Sequence[_AnchoredDirectory],
    *,
    kind: str,
    unit_id: str,
    artifact: str,
) -> EvidenceArtifactSnapshot | None:
    try:
        canonical, parts = _canonical_artifact_parts(artifact)
    except ValueError:
        return None
    chain = list(unit_chain)
    opened_children: list[_AnchoredDirectory] = []
    try:
        for component in parts[:-1]:
            child = _open_child_directory(chain[-1], component)
            if child is None:
                return None
            opened_children.append(child)
            chain.append(child)
        payload = _read_anchored_leaf(
            root_path,
            chain,
            parts[-1],
            max_bytes=_ARTIFACT_MAX_BYTES,
        )
        if payload is None:
            return None
        raw_bytes, file_identity = payload
        return EvidenceArtifactSnapshot(
            source_unit_id=unit_id,
            artifact=canonical,
            raw_bytes=raw_bytes,
            byte_sha256=hashlib.sha256(raw_bytes).hexdigest(),
            path=(root_path / "kb" / "units" / UNIT_KIND_DIRS[kind] / unit_id / canonical),
            directory_identities=tuple(item.identity for item in opened_children),
            file_identity=file_identity,
        )
    finally:
        for directory in reversed(opened_children):
            os.close(directory.fd)


def _artifact_snapshot_is_current(
    root_path: Path,
    unit_chain: Sequence[_AnchoredDirectory],
    snapshot: EvidenceArtifactSnapshot,
) -> bool:
    try:
        _canonical, parts = _canonical_artifact_parts(snapshot.artifact)
    except ValueError:
        return False
    chain = list(unit_chain)
    opened_children: list[_AnchoredDirectory] = []
    try:
        for index, component in enumerate(parts[:-1]):
            child = _open_child_directory(chain[-1], component)
            if child is None:
                return False
            opened_children.append(child)
            chain.append(child)
            if index >= len(snapshot.directory_identities) or child.identity != snapshot.directory_identities[index]:
                return False
        if len(opened_children) != len(snapshot.directory_identities):
            return False
        try:
            visible = os.stat(parts[-1], dir_fd=chain[-1].fd, follow_symlinks=False)
        except OSError:
            return False
        return (
            _record_stat_identity(visible) == snapshot.file_identity
            and _anchored_chain_is_current(root_path, chain)
        )
    finally:
        for directory in reversed(opened_children):
            os.close(directory.fd)


def _snapshot_unit_tree_artifacts(
    root_path: Path,
    unit_chain: Sequence[_AnchoredDirectory],
    *,
    kind: str,
    unit_id: str,
) -> tuple[EvidenceArtifactSnapshot, ...] | None:
    """Recursively capture one closed ordinary-file tree through anchored dirfds."""
    snapshots: list[EvidenceArtifactSnapshot] = []
    entries_seen = 0
    total_bytes = 0

    def walk(
        chain: list[_AnchoredDirectory],
        relative_parts: tuple[str, ...],
    ) -> bool:
        nonlocal entries_seen, total_bytes
        names: list[str] = []
        try:
            with os.scandir(chain[-1].fd) as entries:
                for entry in entries:
                    entries_seen += 1
                    if entries_seen > _UNIT_TREE_MAX_ENTRIES:
                        return False
                    names.append(entry.name)
        except OSError:
            return False

        for name in sorted(names):
            if not name or name in {".", ".."} or Path(name).name != name:
                return False
            artifact_parts = (*relative_parts, name)
            if len(artifact_parts) > _UNIT_TREE_MAX_DEPTH:
                return False
            try:
                metadata = os.stat(name, dir_fd=chain[-1].fd, follow_symlinks=False)
            except OSError:
                return False
            if stat.S_ISDIR(metadata.st_mode):
                child = _open_child_directory(chain[-1], name)
                if child is None:
                    return False
                try:
                    if not walk([*chain, child], artifact_parts):
                        return False
                finally:
                    os.close(child.fd)
                continue
            if not stat.S_ISREG(metadata.st_mode):
                return False
            if not relative_parts and name == "record.yaml":
                continue
            if metadata.st_size > _ARTIFACT_MAX_BYTES:
                return False
            artifact = Path(*artifact_parts).as_posix()
            payload = _read_anchored_leaf(
                root_path,
                chain,
                name,
                max_bytes=_ARTIFACT_MAX_BYTES,
            )
            if payload is None:
                return False
            raw_bytes, file_identity = payload
            total_bytes += len(raw_bytes)
            if total_bytes > _UNIT_ARTIFACT_TOTAL_MAX_BYTES:
                return False
            snapshots.append(
                EvidenceArtifactSnapshot(
                    source_unit_id=unit_id,
                    artifact=artifact,
                    raw_bytes=raw_bytes,
                    byte_sha256=hashlib.sha256(raw_bytes).hexdigest(),
                    path=(
                        root_path
                        / "kb"
                        / "units"
                        / UNIT_KIND_DIRS[kind]
                        / unit_id
                        / artifact
                    ),
                    directory_identities=tuple(
                        item.identity for item in chain[len(unit_chain) :]
                    ),
                    file_identity=file_identity,
                )
            )
        return _anchored_chain_is_current(root_path, chain)

    if not walk(list(unit_chain), ()):
        return None
    return tuple(sorted(snapshots, key=lambda item: item.artifact))


def snapshot_canonical_unit_artifacts(
    project_root: Path,
    kind: str,
    unit_id: str,
    artifacts: Sequence[str],
) -> CanonicalUnitSnapshot | None:
    """Capture requested artifacts and their record through one anchored unit fd."""
    opened = _open_exact_unit_chain(project_root, kind, unit_id)
    if opened is None:
        return None
    root_path, chain = opened
    try:
        record = _read_record_snapshot(root_path, chain, kind=kind, unit_id=unit_id)
        if record is None:
            return None
        canonical_artifacts: list[str] = []
        try:
            canonical_artifacts = sorted({_canonical_artifact_parts(item)[0] for item in artifacts})
        except ValueError:
            return None
        snapshots: list[EvidenceArtifactSnapshot] = []
        total = 0
        for artifact in canonical_artifacts:
            snapshot = _read_artifact_from_unit_chain(
                root_path,
                chain,
                kind=kind,
                unit_id=unit_id,
                artifact=artifact,
            )
            if snapshot is None:
                return None
            total += len(snapshot.raw_bytes)
            if total > _UNIT_ARTIFACT_TOTAL_MAX_BYTES:
                return None
            snapshots.append(snapshot)
        if (
            not _record_snapshot_is_current(root_path, chain, record)
            or not all(_artifact_snapshot_is_current(root_path, chain, item) for item in snapshots)
        ):
            return None
        captured_artifacts = tuple(snapshots)

        def validate_current() -> bool:
            current = _open_exact_unit_chain(project_root, kind, unit_id)
            if current is None:
                return False
            current_root, current_chain = current
            try:
                return (
                    _record_snapshot_is_current(current_root, current_chain, record)
                    and all(
                        _artifact_snapshot_is_current(current_root, current_chain, item)
                        for item in captured_artifacts
                    )
                )
            finally:
                _close_anchored_chain(current_chain)

        return CanonicalUnitSnapshot(
            record=record,
            artifacts=captured_artifacts,
            validate_current=validate_current,
        )
    finally:
        _close_anchored_chain(chain)


def snapshot_canonical_unit_tree(
    project_root: Path,
    kind: str,
    unit_id: str,
) -> CanonicalUnitSnapshot | None:
    """Capture a canonical record and every ordinary artifact under one dirfd tree.

    The artifact tree is closed: symlinks, special nodes, unsafe depth/count, and
    byte-budget overflow reject the whole snapshot instead of being skipped.
    """
    opened = _open_exact_unit_chain(project_root, kind, unit_id)
    if opened is None:
        return None
    root_path, chain = opened
    try:
        record = _read_record_snapshot(root_path, chain, kind=kind, unit_id=unit_id)
        if record is None:
            return None
        artifacts = _snapshot_unit_tree_artifacts(
            root_path,
            chain,
            kind=kind,
            unit_id=unit_id,
        )
        if artifacts is None or not _record_snapshot_is_current(root_path, chain, record):
            return None
        directory_capabilities = _directory_capability_chain(chain)
        captured_artifacts = artifacts

        def validate_current() -> bool:
            current = _open_exact_unit_chain(project_root, kind, unit_id)
            if current is None:
                return False
            current_root, current_chain = current
            try:
                if _directory_capability_chain(current_chain) != directory_capabilities:
                    return False
                current_artifacts = _snapshot_unit_tree_artifacts(
                    current_root,
                    current_chain,
                    kind=kind,
                    unit_id=unit_id,
                )
                return (
                    _record_snapshot_is_current(current_root, current_chain, record)
                    and current_artifacts is not None
                    and current_artifacts == captured_artifacts
                )
            finally:
                _close_anchored_chain(current_chain)

        return CanonicalUnitSnapshot(
            record=record,
            artifacts=captured_artifacts,
            validate_current=validate_current,
        )
    finally:
        _close_anchored_chain(chain)


def snapshot_unique_canonical_unit_tree(
    project_root: Path,
    unit_id: str,
    *,
    expected_kind: str | None = None,
) -> CanonicalUnitSnapshot | None:
    """Return one safe canonical tree only when its unit id is globally unique."""
    identifier = str(unit_id or "").strip()
    if (
        not identifier
        or Path(identifier).name != identifier
        or identifier in {".", ".."}
        or (expected_kind is not None and expected_kind not in UNIT_KIND_DIRS)
    ):
        return None
    record_matches = [
        snapshot
        for snapshot in iter_canonical_record_snapshots(project_root)
        if snapshot.unit_id == identifier
    ]
    if len(record_matches) != 1:
        return None
    selected_record = record_matches[0]
    if expected_kind is not None and selected_record.kind != expected_kind:
        return None
    snapshot = snapshot_canonical_unit_tree(
        project_root,
        selected_record.kind,
        identifier,
    )
    if snapshot is None or (
        snapshot.record.raw_bytes != selected_record.raw_bytes
        or snapshot.record.file_identity != selected_record.file_identity
    ):
        return None

    def validate_unique_current() -> bool:
        if not snapshot.is_current():
            return False
        current_matches = [
            current
            for current in iter_canonical_record_snapshots(project_root)
            if current.unit_id == identifier
        ]
        return len(current_matches) == 1 and (
            current_matches[0].kind == snapshot.record.kind
            and current_matches[0].raw_bytes == snapshot.record.raw_bytes
            and current_matches[0].file_identity == snapshot.record.file_identity
        )

    return CanonicalUnitSnapshot(
        record=snapshot.record,
        artifacts=snapshot.artifacts,
        validate_current=validate_unique_current,
    )


def _snapshot_precanonical_unit_evidence(
    project_root: Path,
    kind: str,
    unit_id: str,
    artifacts: Sequence[str],
) -> EvidenceSourceSnapshot | None:
    """Capture self-unit evidence while an in-memory record is not yet written."""
    opened = _open_exact_unit_chain(project_root, kind, unit_id)
    if opened is None:
        return None
    root_path, chain = opened
    try:
        try:
            os.stat("record.yaml", dir_fd=chain[-1].fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        except OSError:
            return None
        else:
            return None
        try:
            requested = sorted({_canonical_artifact_parts(item)[0] for item in artifacts})
        except ValueError:
            return None
        snapshots: list[EvidenceArtifactSnapshot] = []
        total = 0
        for artifact in requested:
            snapshot = _read_artifact_from_unit_chain(
                root_path,
                chain,
                kind=kind,
                unit_id=unit_id,
                artifact=artifact,
            )
            if snapshot is None:
                return None
            total += len(snapshot.raw_bytes)
            if total > _UNIT_ARTIFACT_TOTAL_MAX_BYTES:
                return None
            snapshots.append(snapshot)
        captured_artifacts = tuple(snapshots)
        if (
            not _anchored_chain_is_current(root_path, chain)
            or not all(_artifact_snapshot_is_current(root_path, chain, item) for item in captured_artifacts)
        ):
            return None

        def validate_current() -> bool:
            current = _open_exact_unit_chain(project_root, kind, unit_id)
            if current is None:
                return False
            current_root, current_chain = current
            try:
                try:
                    os.stat("record.yaml", dir_fd=current_chain[-1].fd, follow_symlinks=False)
                except FileNotFoundError:
                    record_absent = True
                except OSError:
                    record_absent = False
                else:
                    record_absent = False
                return (
                    record_absent
                    and _anchored_chain_is_current(current_root, current_chain)
                    and all(
                        _artifact_snapshot_is_current(current_root, current_chain, item)
                        for item in captured_artifacts
                    )
                )
            finally:
                _close_anchored_chain(current_chain)

        return EvidenceSourceSnapshot(
            source_unit_id=unit_id,
            kind=kind,
            artifacts=captured_artifacts,
            path=root_path / "kb" / "units" / UNIT_KIND_DIRS[kind] / unit_id,
            validate_current=validate_current,
        )
    finally:
        _close_anchored_chain(chain)


def iter_canonical_record_snapshots(
    project_root: Path,
    *,
    kind: str | None = None,
) -> list[CanonicalRecordSnapshot]:
    """Return only canonical records proven safe from one anchored read."""
    kinds = [kind] if kind else list(UNIT_KIND_DIRS)
    if any(item_kind not in UNIT_KIND_DIRS for item_kind in kinds):
        raise SystemExit(f"Unsupported unit kind: {kind}")
    root_path = project_root.absolute()
    root_directory = _open_root_directory(root_path)
    if root_directory is None:
        return []
    base_chain = [root_directory]
    try:
        for component in ("kb", "units"):
            child = _open_child_directory(base_chain[-1], component)
            if child is None:
                return []
            base_chain.append(child)
        snapshots: list[CanonicalRecordSnapshot] = []
        for item_kind in kinds:
            kind_directory = _open_child_directory(base_chain[-1], UNIT_KIND_DIRS[item_kind])
            if kind_directory is None:
                continue
            try:
                try:
                    names = sorted(os.listdir(kind_directory.fd))
                except OSError:
                    continue
                for unit_id in names:
                    if _SAFE_UNIT_DIRECTORY.fullmatch(unit_id) is None:
                        continue
                    unit_directory = _open_child_directory(kind_directory, unit_id)
                    if unit_directory is None:
                        continue
                    try:
                        snapshot = _read_record_snapshot(
                            root_path,
                            [*base_chain, kind_directory, unit_directory],
                            kind=item_kind,
                            unit_id=unit_id,
                        )
                        if snapshot is not None:
                            snapshots.append(snapshot)
                    finally:
                        os.close(unit_directory.fd)
            finally:
                os.close(kind_directory.fd)
        return snapshots
    finally:
        for directory in reversed(base_chain):
            os.close(directory.fd)


def _canonical_record_slot_exists(project_root: Path, kind: str, unit_id: str) -> bool:
    """Return whether the exact record slot exists or cannot be proven absent."""
    candidate = record_path(project_root, kind, unit_id)
    try:
        candidate.lstat()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    return True


def _snapshot_matches_detached_record(
    project_root: Path,
    snapshot: CanonicalRecordSnapshot,
    record: dict[str, Any],
) -> bool:
    if snapshot.record == record:
        return True
    normalized = normalize_record_snapshot(snapshot, project_root)
    try:
        supplied = normalize_record_schema(
            record,
            project_root=project_root,
            canonical_snapshot=snapshot,
        )
    except (SystemExit, TypeError, ValueError, AttributeError, KeyError, IndexError):
        return False
    return normalized is not None and normalized == supplied


def canonical_record_snapshot_if_present(
    project_root: Path,
    record: dict[str, Any],
) -> CanonicalRecordSnapshot | None:
    """Bind a detached unit record to its one safe persisted canonical object.

    ``None`` means the record slot is genuinely absent and may be used by a
    pre-write flow.  An unsafe, malformed, duplicate, or different detached
    record is an error rather than being confused with absence.
    """
    kind = str(record.get("kind") or "").strip()
    unit_id = str(record.get("id") or "").strip()
    if kind not in UNIT_KIND_DIRS or _SAFE_UNIT_DIRECTORY.fullmatch(unit_id) is None:
        raise ValueError("record has no canonical unit identity")
    snapshot = canonical_record_snapshot_for_identity(
        project_root,
        kind,
        unit_id,
        allow_absent=True,
    )
    if snapshot is None:
        return None
    if not _snapshot_matches_detached_record(project_root, snapshot, record):
        raise ValueError("detached record does not match the current canonical snapshot")
    return snapshot


def canonical_record_snapshot_for_identity(
    project_root: Path,
    kind: str,
    unit_id: str,
    *,
    allow_absent: bool = False,
) -> CanonicalRecordSnapshot | None:
    """Resolve one identity without accepting malformed or duplicate slots."""
    if kind not in UNIT_KIND_DIRS or _SAFE_UNIT_DIRECTORY.fullmatch(unit_id) is None:
        raise ValueError("record has no canonical unit identity")
    matches = [
        snapshot
        for snapshot in iter_canonical_record_snapshots(project_root)
        if snapshot.unit_id == unit_id
    ]
    occupied_slots = [
        candidate_kind
        for candidate_kind in UNIT_KIND_DIRS
        if _canonical_record_slot_exists(project_root, candidate_kind, unit_id)
    ]
    if not matches:
        if occupied_slots:
            raise ValueError("canonical record slot exists but is not safely readable")
        if allow_absent:
            return None
        raise ValueError("record has no persisted canonical snapshot")
    if len(matches) != 1 or occupied_slots != [matches[0].kind]:
        raise ValueError("record id does not resolve to one unique canonical record")
    snapshot = matches[0]
    if snapshot.kind != kind:
        raise ValueError("canonical record kind does not match requested identity")
    return snapshot


def canonical_record_snapshot_for_record(
    project_root: Path,
    record: dict[str, Any],
) -> CanonicalRecordSnapshot:
    """Return the exact persisted snapshot represented by a detached record."""
    snapshot = canonical_record_snapshot_if_present(project_root, record)
    if snapshot is None:
        raise ValueError("record has no persisted canonical snapshot")
    return snapshot


def require_current_record_snapshot(
    project_root: Path,
    expected: CanonicalRecordSnapshot,
) -> CanonicalRecordSnapshot:
    """Fail unless the exact record object and all of its ancestors are current."""
    matches = [
        snapshot
        for snapshot in iter_canonical_record_snapshots(project_root)
        if snapshot.unit_id == expected.unit_id
    ]
    occupied_slots = [
        candidate_kind
        for candidate_kind in UNIT_KIND_DIRS
        if _canonical_record_slot_exists(project_root, candidate_kind, expected.unit_id)
    ]
    if len(matches) != 1 or occupied_slots != [expected.kind]:
        raise ValueError("expected record snapshot is no longer uniquely current")
    current = matches[0]
    if (
        current.kind != expected.kind
        or current.path != expected.path
        or current.raw_bytes != expected.raw_bytes
        or current.file_identity != expected.file_identity
        or current.directory_capabilities != expected.directory_capabilities
    ):
        raise ValueError("expected record snapshot changed before commit")
    return current


@contextmanager
def command_mutation(
    project_root: Path,
    op_type: str,
    target_paths: Sequence[Path],
    *,
    commit_guard: Callable[[], None] | None = None,
) -> Iterator[None]:
    """Delegate command-scoped recovery and locking to the canonical transaction."""
    with mutation_transaction(
        project_root,
        op_type,
        target_paths,
        commit_guard=commit_guard,
    ):
        yield


def trusted_project_path(
    project_root: Path,
    path: Path,
    *,
    allowed_root: Path,
    require: str,
) -> Path:
    """Return an existing canonical path only when no component is a symlink."""
    project = project_root.resolve()
    candidate = path if path.is_absolute() else project / path
    try:
        relative = candidate.relative_to(project)
    except ValueError as exc:
        raise ValueError("canonical path escapes the project root") from exc
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError("canonical path contains an unsafe component")
    cursor = project
    for part in relative.parts:
        cursor = cursor / part
        if cursor.is_symlink():
            raise ValueError("canonical path contains a symlink component")
    resolved = candidate.resolve()
    allowed = allowed_root.resolve()
    try:
        resolved.relative_to(allowed)
    except ValueError as exc:
        raise ValueError("canonical path escapes its allowed root") from exc
    if require == "file" and not resolved.is_file():
        raise ValueError("canonical file is missing or not a regular file")
    if require == "dir" and not resolved.is_dir():
        raise ValueError("canonical directory is missing or not a directory")
    if require not in {"file", "dir"}:
        raise ValueError("unsupported canonical path requirement")
    return resolved


def trusted_unit_record_path(project_root: Path, unit_id: str) -> Path:
    """Return an informational path after proving one canonical record exists.

    Callers that need bytes must use a canonical snapshot API; the returned
    lexical path is deliberately not a trusted read capability.
    """
    identifier = str(unit_id or "").strip()
    if not identifier or Path(identifier).name != identifier or identifier in {".", ".."}:
        raise ValueError("source unit id is not a canonical path component")
    matches = [
        snapshot.path
        for snapshot in iter_canonical_record_snapshots(project_root)
        if snapshot.unit_id == identifier
    ]
    if len(matches) != 1:
        raise ValueError("source unit does not resolve to one canonical safe record")
    return matches[0]


def trusted_program_root(project_root: Path, program_id: str) -> Path:
    identifier = str(program_id or "").strip()
    if not identifier or Path(identifier).name != identifier or identifier in {".", ".."}:
        raise ValueError("program id is not a canonical path component")
    program_root = project_root / "kb" / "programs" / identifier
    return trusted_project_path(
        project_root,
        program_root,
        allowed_root=project_root / "kb" / "programs",
        require="dir",
    )


def trusted_claim_source_roots(
    project_root: Path,
    record: dict[str, Any],
    *,
    verification_root: Path | None = None,
    expected_record_snapshot: CanonicalRecordSnapshot | None = None,
) -> dict[str, Path | EvidenceSourceSnapshot]:
    """Capture canonical unit evidence bytes and resolve non-unit roots safely."""
    roots: dict[str, Path | EvidenceSourceSnapshot] = {}
    record_id = str(record.get("id") or "").strip()
    record_kind = str(record.get("kind") or "").strip()
    artifacts_by_source: dict[str, set[str]] = {}
    for claim in confirmation_claims(record):
        for ref in claim.get("evidence_refs") or []:
            if not isinstance(ref, dict):
                continue
            if isinstance(ref.get("external_source"), dict):
                # Repo evidence is rooted by the separately trusted external_source
                # contract; the canonical unit directory is not its byte root.
                continue
            source_unit_id = str(ref.get("source_unit_id") or "").strip()
            if not source_unit_id:
                continue
            artifacts_by_source.setdefault(source_unit_id, set()).add(str(ref.get("artifact") or ""))

    for source_unit_id in sorted(artifacts_by_source):
        requested_artifacts = sorted(artifacts_by_source[source_unit_id])
        if source_unit_id in roots:
            continue
        if source_unit_id == record_id and record_kind in UNIT_KIND_DIRS:
            unit_snapshot = snapshot_canonical_unit_artifacts(
                project_root,
                record_kind,
                record_id,
                requested_artifacts,
            )
            if unit_snapshot is None:
                if expected_record_snapshot is not None:
                    raise ValueError("source unit evidence cannot be captured canonically")
                precanonical = _snapshot_precanonical_unit_evidence(
                    project_root,
                    record_kind,
                    record_id,
                    requested_artifacts,
                )
                if precanonical is None:
                    raise ValueError("source unit evidence cannot be captured canonically")
                roots[source_unit_id] = precanonical
                continue
            if expected_record_snapshot is not None and (
                unit_snapshot.record.raw_bytes != expected_record_snapshot.raw_bytes
                or unit_snapshot.record.file_identity != expected_record_snapshot.file_identity
            ):
                raise ValueError("source unit record changed before evidence capture")
            roots[source_unit_id] = EvidenceSourceSnapshot(
                source_unit_id=source_unit_id,
                kind=record_kind,
                artifacts=unit_snapshot.artifacts,
                path=unit_snapshot.record.path.parent,
                validate_current=unit_snapshot.is_current,
            )
            continue
        if source_unit_id.startswith("program:"):
            program_id = source_unit_id.split(":", 1)[1]
            if _SAFE_UNIT_DIRECTORY.fullmatch(program_id) is None:
                raise ValueError("program evidence source id is not canonical")
            program_snapshot = snapshot_project_evidence_source(
                project_root,
                Path("kb") / "programs" / program_id,
                source_unit_id=source_unit_id,
                kind="program",
                artifacts=requested_artifacts,
            )
            if program_snapshot is None:
                raise ValueError("program evidence cannot be captured canonically")
            roots[source_unit_id] = program_snapshot
            continue
        matches: list[CanonicalUnitSnapshot] = []
        for source_kind in UNIT_KIND_DIRS:
            unit_snapshot = snapshot_canonical_unit_artifacts(
                project_root,
                source_kind,
                source_unit_id,
                requested_artifacts,
            )
            if unit_snapshot is not None:
                matches.append(unit_snapshot)
        if len(matches) != 1:
            raise ValueError("source unit does not resolve to one canonical artifact snapshot")
        unit_snapshot = matches[0]
        roots[source_unit_id] = EvidenceSourceSnapshot(
            source_unit_id=source_unit_id,
            kind=unit_snapshot.record.kind,
            artifacts=unit_snapshot.artifacts,
            path=unit_snapshot.record.path.parent,
            validate_current=unit_snapshot.is_current,
        )
    return roots


def kind_payload_skeleton(kind: str, title: str = "") -> dict[str, Any]:
    if kind == "paper":
        return {
            "basic_info": {
                "title": title,
                "authors": [],
                "institutions": [],
                "venue": "",
                "year": "",
                "source_url": "",
                "code_url": "",
                "project_url": "",
                "abstract": "",
                "arxiv_id": "",
                "doi": "",
            },
            "source_search": {
                "stage_ids": [],
                "candidate_ids": [],
                "queries": [],
            },
            "quick_screen": {
                "paper_type": "",
                "worth_deep_reading": "unknown",
                "judgement_reason": [],
                "backing_strength": "",
                "result_strength": "",
                "experiment_quality": "",
                "reliability": "",
                "novelty": "",
                "relevance_to_current_research": "",
                "screening_mode": "",
                "screening_evidence_pages": [],
                "risks": [],
                "keyword_hits": {},
                "takeaways": [],
                "recommended_next_action": "",
            },
            "core_content": {
                "research_problem": "",
                "motivation": "",
                "story": "",
                "method": "",
                "innovations": [],
                "changes_and_effects": [],
                "mechanism": "",
                "why_it_might_work": "",
            },
            "structure": {
                "refresh_status": "not_started",
                "detected_sections": [],
                "paper_outline": [],
                "open_questions": [],
            },
            "figures": {
                "extraction_status": "not_started",
                "candidate_figures": [],
                "key_figures": [],
            },
            "critique": {
                "assumptions": [],
                "weak_spots": [],
                "experiment_gaps": [],
                "reliability_risks": [],
                "failure_scenarios": [],
                "improvements": [],
                "key_insights": [],
            },
            "state": {
                "reading_status": "unread",
                "needs_reread": False,
                "useful_for_review": False,
                "useful_for_experiment": False,
                "useful_for_writing": False,
                "full_note_status": "not_started",
                "note_generation_mode": "scaffold",
            },
        }
    if kind == "repo":
        return {
            "basic_info": {
                "name": title,
                "owner": "",
                "url": "",
                "paper_url": "",
                "license": "",
                "last_activity": "",
                "environment": [],
            },
            "source_search": {
                "stage_ids": [],
                "candidate_ids": [],
                "queries": [],
            },
            "capability": {
                "problem": "",
                "core_capabilities": [],
                "inputs": [],
                "outputs": [],
                "supported_tasks": [],
                "unsupported_tasks": [],
                "boundary": "",
                "candidate_roles": [],
            },
            "structure": {
                "scan_status": "not_started",
                "scan_applicability": "unknown",
                "scan_reason": "",
                "repo_root": "",
                "top_level_dirs": [],
                "top_level_files": [],
                "languages": [],
                "core_modules": [],
                "entrypoint_candidates": [],
                "entrypoints": [],
                "training_flow": [],
                "inference_flow": [],
                "config_system": [],
                "data_flow": [],
                "critical_modules": [],
            },
            "reuse": {
                "directly_reusable": [],
                "worth_borrowing": [],
                "worth_modifying": [],
                "modification_difficulty": [],
                "pipeline_value": [],
            },
            "risk": {
                "engineering_complexity": "",
                "dependency_weight": "",
                "reproduction_barrier": "",
                "performance_boundary": "",
                "constraints": [],
                "not_suitable_for": [],
            },
        }
    if kind == "dataset":
        return {
            "basic_info": {
                "name": title,
                "owner": "",
                "url": "",
                "platform": "",
                "license": "",
                "version": "",
                "last_updated": "",
            },
            "source_search": {
                "stage_ids": [],
                "candidate_ids": [],
                "queries": [],
            },
            "profile": {
                "positioning": "",
                "scale": "",
                "platform": "",
                "license": "",
            },
            "composition": {
                "summary": "",
                "modalities": [],
                "tasks": [],
                "embodiment": [],
                "scenes": [],
            },
            "access": {
                "schema_access": "",
                "formats": [],
                "splits": [],
                "schema": [],
                "entrypoints": [],
            },
            "quality": {
                "suitability_risks": "",
                "known_issues": [],
                "constraints": [],
                "risks": [],
            },
            "reuse": {
                "supported_uses": [],
                "unsupported_uses": [],
            },
            "state": {
                "profile_status": "not_started",
            },
        }
    if kind == "blog":
        return {
            "basic_info": {
                "title": title,
                "author": "",
                "platform": "",
                "year": "",
                "url": "",
            },
            "source_search": {
                "stage_ids": [],
                "candidate_ids": [],
                "queries": [],
            },
            "positioning": {
                "content_type": "",
                "best_reading_stage": "",
                "main_value": "",
            },
            "content": {
                "key_points": [],
                "hard_parts_explained": [],
                "intuitions": [],
                "supports": [],
            },
            "credibility": {
                "reference_mode": "",
                "good_for_reference": [],
                "needs_verification": [],
                "best_use": "",
            },
        }
    if kind == "idea":
        return {
            "origin": {
                "title": title,
                "source": "",
                "theme": "",
            },
            "candidate": {
                "bundle_id": "",
                "strategy": "",
                "pool": "",
            },
            "problem": {
                "problem_definition": "",
                "pain_point": "",
                "target_improvement": "",
                "scope": "",
            },
            "hypothesis": {
                "core_hypothesis": "",
                "why_it_might_work": "",
                "key_mechanism": "",
                "difference_from_prior_work": "",
            },
            "analysis": {
                "related_work": [],
                "novelty": "",
                "incremental_or_new_direction": "",
                "feasibility": "",
                "minimum_validation_path": "",
                "risks": [],
                "next_actions": [],
            },
            "review": {
                "review_status": "not_started",
                "recommendation": "pending_confirmation",
                "score_breakdown": {},
                "evidence_gaps": [],
                "killer_questions": [],
            },
            "selection": {
                "selected_rank": "",
                "selected_reason": "",
                "selected_by": "",
                "selected_at": "",
                "selection_evidence": [],
                "selection_method": "",
            },
            "state": {
                "progress_state": "spark",
                "worth_pursuing": "unknown",
            },
        }
    if kind == "experiment":
        return {
            "basic_info": {
                "title": title,
                "program_id": "",
                "idea_id": "",
                "goal": "",
                "owner": "",
            },
            "setup": {
                "data": [],
                "model": "",
                "hyperparameters": {},
                "runtime": {},
                "hardware": [],
                "environment": [],
            },
            "process": {
                "change_summary": [],
                "delta_from_previous": [],
                "why_this_run": "",
                "tested_hypothesis": "",
            },
            "results": {
                "metrics": {},
                "metric_contract": {
                    "shape": "name -> {name, value, unit, direction}",
                    "directions": ["higher-better", "lower-better", "neutral", "unknown"],
                },
                "comparison": [],
                "met_expectation": "unknown",
                "abnormalities": [],
                "artifacts": [],
            },
            "diagnosis": {
                "failure_modes": [],
                "likely_causes": [],
                "ruled_out_causes": [],
                "unknowns": [],
                "next_actions": [],
                "comparison_context": {},
            },
        }
    raise SystemExit(f"Unsupported unit kind: {kind}")


def _extract_unit_id_hash(unit_id: str) -> str:
    match = re.search(r"-([0-9a-f]{6,16})$", unit_id.strip().lower())
    return match.group(1) if match else ""


def _record_template(kind: str, *, title: str, maturity: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    unit_id = build_unit_id(kind, title, str(source.get("original_uri") if source else ""))
    now = utc_now_iso()
    return {
        "id": unit_id,
        "legacy_ids": [],
        "kind": kind,
        "title": title,
        "status": "draft",
        "maturity": maturity if maturity in MATURITY_LEVELS else "lightweight",
        "confirmation_status": "auto_confirmed",
        "needs_human_confirmation": False,
        "information_types": ["fact"],
        "confidence": 0.9,
        "created_at": now,
        "first_ingested_at": now,
        "updated_at": now,
        "last_human_confirmed_at": "",
        "tags": [],
        "topics": [],
        "candidate_pools": [],
        "program_ids": [],
        "priority": "normal",
        "summary": "",
        "links": [],
        "reuse_flags": dict(DEFAULT_REUSE_FLAGS),
        "taxonomy": {
            "primary_topic": "",
            "secondary_topics": [],
            "canonical_tags": [],
            "topic_sources": [],
            "tag_sources": [],
            "pool_sources": [],
        },
        "artifacts": [],
        "source": source or {},
        "payload": kind_payload_skeleton(kind, title),
        "history": [],
    }


def record_summary(record: dict[str, Any]) -> str:
    summary = str(record.get("summary") or "").strip()
    if summary:
        return summary
    payload = record.get("payload", {})
    if record.get("kind") == "paper":
        reason = payload.get("quick_screen", {}).get("judgement_reason", [])
        if reason:
            return str(reason[0])
        takeaways = payload.get("quick_screen", {}).get("takeaways", [])
        if takeaways:
            return str(takeaways[0])
    if record.get("kind") == "repo":
        boundary = payload.get("capability", {}).get("boundary")
        if boundary:
            return str(boundary)
        capabilities = payload.get("capability", {}).get("core_capabilities", [])
        if capabilities:
            return str(capabilities[0])
    if record.get("kind") == "dataset":
        positioning = payload.get("profile", {}).get("positioning")
        if positioning:
            return str(positioning)
        composition = payload.get("composition", {}).get("summary")
        if composition:
            return str(composition)
    if record.get("kind") == "idea":
        problem = payload.get("problem", {}).get("problem_definition")
        if problem:
            return str(problem)
        hypothesis = payload.get("hypothesis", {}).get("core_hypothesis")
        if hypothesis:
            return str(hypothesis)
    if record.get("kind") == "experiment":
        goal = payload.get("basic_info", {}).get("goal")
        if goal:
            return str(goal)
    return ""


def append_history(
    record: dict[str, Any],
    *,
    action: str,
    summary: str,
    information_types: list[str] | None = None,
    artifacts: list[str] | None = None,
) -> None:
    record.setdefault("history", []).append(
        {
            "timestamp": utc_now_iso(),
            "action": action,
            "summary": summary,
            "information_types": information_types or ["fact"],
            "artifacts": artifacts or [],
        }
    )
    record["updated_at"] = utc_now_iso()


def default_record(kind: str, *, title: str, maturity: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    record = _record_template(kind, title=title, maturity=maturity, source=source)
    append_history(record, action="created", summary=f"Created {kind} record.")
    return record


def normalize_record_schema(
    record: dict[str, Any],
    *,
    project_root: Path | None = None,
    canonical_snapshot: CanonicalRecordSnapshot | None = None,
) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise SystemExit("Invalid record payload")
    kind = str(record.get("kind") or "")
    if kind not in UNIT_KIND_DIRS:
        raise SystemExit(f"Unsupported unit kind: {kind}")
    title = str(record.get("title") or "")
    maturity = str(record.get("maturity") or "lightweight")
    source = record.get("source", {})
    if isinstance(source, dict):
        source = {key: value for key, value in source.items() if key != "backup_warning"}
        record = {**record, "source": source}
    else:
        source = {}
    template = _record_template(kind, title=title, maturity=maturity, source=source)
    normalized = _deep_fill_missing(record, template)
    normalized["title"] = title or str(normalized.get("title") or normalized["id"])
    normalized["status"] = str(normalized.get("status") or "draft")
    normalized["maturity"] = str(normalized.get("maturity") or "lightweight")
    normalized["confirmation_status"] = str(normalized.get("confirmation_status") or "auto_confirmed")
    try:
        normalized["revision"] = max(0, int(normalized.get("revision", 0)))
    except (TypeError, ValueError) as exc:
        raise SystemExit("Invalid record revision: expected a non-negative integer") from exc
    normalized["legacy_ids"] = [
        item
        for item in _unique_text_list(normalized.get("legacy_ids"))
        if item and item != str(normalized.get("id") or "")
    ]
    normalized["information_types"] = sorted(
        item for item in {str(value) for value in normalized.get("information_types", [])} if item in INFORMATION_TYPES
    ) or ["fact"]
    confirmation_invalidated = False
    verification = normalized.get("payload", {}).get("verification") if isinstance(normalized.get("payload"), dict) else None
    if isinstance(verification, dict):
        evidence_root = None
        source_roots = None
        source_root_violations: list[str] = []
        if project_root is not None:
            evidence_root = unit_root(
                project_root,
                str(normalized.get("kind") or ""),
                str(normalized.get("id") or ""),
            )
            try:
                source_roots = trusted_claim_source_roots(
                    project_root,
                    normalized,
                    verification_root=evidence_root,
                    expected_record_snapshot=canonical_snapshot,
                )
            except ValueError:
                source_root_violations.append("verification evidence source is not canonically contained")
        verification_violations = source_root_violations or verification_receipt_violations(
            normalized,
            evidence_root,
            external_source=record_external_source_contract(normalized),
            source_roots=source_roots,
            check_artifacts=project_root is not None,
        )
        if verification_violations:
            verification["invalidation"] = {
                "reason": "verification_stale",
                "violations": verification_violations,
            }
            if normalized.get("confirmation_status") == "confirmed":
                confirmation_invalidated = True
                normalized["confirmation_status"] = "pending_user_confirmation"
                normalized["needs_human_confirmation"] = True
    confirmation = normalized.get("confirmation")
    if isinstance(confirmation, dict) and confirmation.get("content_digest"):
        stored_digest = str(confirmation.get("content_digest") or "")
        current_digest = confirmation_content_digest(normalized)
        if current_digest != stored_digest:
            confirmation_invalidated = True
            normalized["confirmation_status"] = "pending_user_confirmation"
            normalized["needs_human_confirmation"] = True
            confirmation["invalidation"] = {
                "reason": "confirmable_content_changed",
                "stored_content_digest": stored_digest,
                "current_content_digest": current_digest,
            }
    normalized["needs_human_confirmation"] = (
        confirmation_invalidated
        or (
            (
                _record_needs_gate(normalized)[0]
                or bool(
                    {
                        str(claim.get("claim_type") or "")
                        for claim in confirmation_claims(normalized)
                        if isinstance(claim, dict)
                    }
                    & (JUDGEMENT_CLAIM_TYPES | UNCONFIRMABLE_CLAIM_TYPES)
                )
            )
            and normalized["confirmation_status"] != "confirmed"
        )
    )
    if (
        str(normalized.get("confirmation_status") or "") == "rejected"
        and str(normalized.get("status") or "") not in {"rejected", "archived"}
    ):
        # A rejected unit leaves the active lifecycle: align the canonical
        # lifecycle status with the rejection decision (STATUS_VALUES already
        # contains "rejected").  confirmation_status, the rejection payload and
        # history are kept untouched; an explicit terminal "archived" status is
        # preserved.  Counting/filter surfaces (status / review / next) key off
        # confirmation_status and are unaffected by this alignment.
        normalized["status"] = "rejected"
    normalized["tags"] = _slug_list(normalized.get("tags"))
    normalized["topics"] = _slug_list(normalized.get("topics"))
    normalized["candidate_pools"] = _slug_list(normalized.get("candidate_pools"))
    normalized["program_ids"] = _slug_list(normalized.get("program_ids"))
    normalized["artifacts"] = _artifact_list(normalized.get("artifacts"))
    normalized["links"] = normalize_links(normalized.get("links", []))
    normalized["history"] = [dict(item) for item in normalized.get("history", []) if isinstance(item, dict)]
    if not normalized["history"]:
        append_history(normalized, action="created", summary=f"Backfilled history for {kind} record.")
    taxonomy = normalized.get("taxonomy", {})
    if not isinstance(taxonomy, dict):
        taxonomy = {}
    taxonomy.setdefault("primary_topic", normalized["topics"][0] if normalized["topics"] else "")
    taxonomy["secondary_topics"] = [topic for topic in normalized["topics"] if topic != taxonomy["primary_topic"]]
    taxonomy["canonical_tags"] = list(normalized["tags"])
    taxonomy["topic_sources"] = _text_list(taxonomy.get("topic_sources"))
    taxonomy["tag_sources"] = _text_list(taxonomy.get("tag_sources"))
    taxonomy["pool_sources"] = _text_list(taxonomy.get("pool_sources"))
    normalized["taxonomy"] = taxonomy
    payload = normalized.get("payload", {})
    if not isinstance(payload, dict):
        payload = {}
    normalized["payload"] = _deep_fill_missing(payload, kind_payload_skeleton(kind, normalized["title"]))
    return normalized


def _record_needs_gate(record: dict[str, Any]) -> tuple[bool, set[str], bool]:
    info_types = {str(value) for value in record.get("information_types") or []}
    ai_info_types = info_types & AI_INFORMATION_TYPES
    source = record.get("source") or {}
    source_is_ai = isinstance(source, dict) and str(source.get("kind") or "").lower() == "ai"
    return bool(ai_info_types) or source_is_ai, ai_info_types, source_is_ai


def _workflow_marker(record: dict[str, Any]) -> str:
    kind = str(record.get("kind") or "")
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    state = payload.get("state")
    state = state if isinstance(state, dict) else {}
    if kind in {"paper", "blog"}:
        return str(state.get("full_note_status") or "")
    if kind == "repo":
        return str(state.get("capability_fill_status") or "")
    if kind == "dataset":
        return str(state.get("profile_status") or "")
    if kind == "idea":
        review = payload.get("review")
        analysis = payload.get("analysis")
        review = review if isinstance(review, dict) else {}
        analysis = analysis if isinstance(analysis, dict) else {}
        return str(review.get("review_status") or analysis.get("analysis_status") or "")
    if kind == "experiment":
        diagnosis = payload.get("diagnosis")
        diagnosis = diagnosis if isinstance(diagnosis, dict) else {}
        return str(diagnosis.get("verification_status") or state.get("diagnosis_status") or "")
    return ""


def _has_unverified_judgement_signal(record: dict[str, Any]) -> bool:
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    quick_screen = payload.get("quick_screen")
    quick_screen = quick_screen if isinstance(quick_screen, dict) else {}
    for key in (
        "worth_deep_reading",
        "judgement_reason",
        "backing_strength",
        "result_strength",
        "experiment_quality",
        "reliability",
        "novelty",
        "relevance_to_current_research",
        "screening_mode",
        "risks",
        "takeaways",
        "recommended_next_action",
    ):
        value = quick_screen.get(key)
        if value not in (None, "", "unknown", False, [], {}):
            return True
    return False


def _has_substantive_judgement_content(record: dict[str, Any]) -> bool:
    """Reuse the confirmation gate's substance criterion without import cycling."""
    from .confirm import has_substantive_content

    return has_substantive_content(record, str(record.get("kind") or ""))


def record_workflow_state(record: dict[str, Any]) -> str:
    """Single pure classifier shared by next/review/status/auto callers."""
    status = str(record.get("status") or "").strip().lower()
    confirmation_status = str(record.get("confirmation_status") or "")
    payload = record.get("payload")
    payload = payload if isinstance(payload, dict) else {}
    source = record.get("source")
    source = source if isinstance(source, dict) else {}
    marker = _workflow_marker(record).strip().lower()
    claims = confirmation_claims(record)
    information_types = {str(value) for value in record.get("information_types") or []}
    claim_types = {str(claim.get("claim_type") or "") for claim in claims}
    unconfirmable_claims = bool(claim_types & UNCONFIRMABLE_CLAIM_TYPES)
    judgement_claims_present = bool(claim_types & JUDGEMENT_CLAIM_TYPES)
    judgement_record = bool(
        _record_needs_gate(record)[0]
        or "unverified" in information_types
        or judgement_claims_present
        or _has_unverified_judgement_signal(record)
    )
    needs_gate = (
        _record_needs_gate(record)[0]
        or "unverified" in information_types
        or bool(claim_types & (JUDGEMENT_CLAIM_TYPES | UNCONFIRMABLE_CLAIM_TYPES))
        or _has_unverified_judgement_signal(record)
    )
    failure_markers = {
        status,
        marker,
        str(source.get("status") or "").strip().lower(),
        str(payload.get("workflow_status") or "").strip().lower(),
    }
    if confirmation_status == "rejected":
        return "done"
    if failure_markers & {"failed_retryable", "retryable_failure", "failed-retryable"}:
        return "failed_retryable"
    if status in {"archived", "completed"}:
        return "done"

    verification = payload.get("verification")
    verification = verification if isinstance(verification, dict) else {}
    claims_structurally_complete = (
        bool(claims)
        and not unconfirmable_claims
        and not validate_claims(claims)
    )
    judgement_material_complete = (
        claims_structurally_complete
        and judgement_claims_present
        and _has_substantive_judgement_content(record)
    )
    receipt_violations = verification_receipt_violations(
        record,
        None,
        check_artifacts=False,
    )
    verification_current = (
        claims_structurally_complete
        and not verification.get("invalidation")
        and not receipt_violations
        and (not judgement_record or judgement_material_complete)
    )
    requires_reverification = (
        judgement_record
        and not verification_current
        and (
            confirmation_status == "confirmed"
            or bool(verification)
        )
    )
    if requires_reverification:
        return "ready_to_verify" if judgement_material_complete else "awaiting_agent_fill"
    if confirmation_status == "confirmed":
        return "done"
    if marker in {"awaiting_agent_fill", "agent_fill_required"}:
        return "awaiting_agent_fill"
    if marker in {"ready_to_verify", "agent_fill_complete"}:
        if judgement_record and not judgement_material_complete:
            return "awaiting_agent_fill"
        return "ready_to_verify"
    if confirmation_status == "pending_user_confirmation":
        if verification_current:
            return "ready_for_review"
        if marker in {"pending_user_confirmation", "ready_for_review"}:
            return "awaiting_agent_fill" if needs_gate else "ready_for_review"
        if marker == "not_started":
            return "source_ready" if needs_gate else "ready_for_review"
        if not marker and str(record.get("kind") or "") in {"paper", "blog", "repo", "dataset", "idea"}:
            return "source_ready" if needs_gate else "ready_for_review"
        if needs_gate or marker:
            return "awaiting_agent_fill"
        return "ready_for_review"
    return "source_ready"


def is_ready_for_human_review(record: dict[str, Any]) -> bool:
    return record_workflow_state(record) == "ready_for_review"


def iter_records(project_root: Path, *, kind: str | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for snapshot in iter_canonical_record_snapshots(project_root, kind=kind):
        record = normalize_record_snapshot(snapshot, project_root)
        if record is not None:
            items.append(record)
    return items


def _normalized_snapshot_record(
    snapshot: CanonicalRecordSnapshot,
    project_root: Path,
) -> dict[str, Any] | None:
    payload = copy.deepcopy(snapshot.record)
    try:
        stable_timestamp = datetime.fromtimestamp(
            snapshot.modified_time_ns / 1_000_000_000,
            timezone.utc,
        ).replace(microsecond=0).isoformat()
    except (OSError, OverflowError, ValueError):
        stable_timestamp = "1970-01-01T00:00:00+00:00"
    for field in ("created_at", "first_ingested_at", "updated_at"):
        if field not in payload:
            payload[field] = stable_timestamp
    raw_history = payload.get("history")
    valid_history = (
        [item for item in raw_history if isinstance(item, dict)]
        if isinstance(raw_history, list)
        else []
    )
    if not valid_history:
        payload["history"] = [
            {
                "timestamp": stable_timestamp,
                "action": "created",
                "summary": f"Backfilled history for {snapshot.kind} record.",
                "information_types": ["fact"],
                "artifacts": [],
            }
        ]
    try:
        return normalize_record_schema(
            payload,
            project_root=project_root,
            canonical_snapshot=snapshot,
        )
    except (
        SystemExit,
        TypeError,
        ValueError,
        AttributeError,
        KeyError,
        IndexError,
        RecursionError,
        OverflowError,
    ):
        # This is the per-record quarantine boundary.  Strict YAML establishes
        # only a mapping shape; arbitrary legacy field types must not abort the
        # valid siblings in a bulk status/find/survey/intake scan.
        return None


def normalize_record_snapshot(
    snapshot: CanonicalRecordSnapshot,
    project_root: Path,
) -> dict[str, Any] | None:
    """Normalize one strict snapshot, quarantining only that malformed record."""
    return _normalized_snapshot_record(snapshot, project_root)


def _record_lookup_path(project_root: Path, record: dict[str, Any]) -> Path | None:
    kind = str(record.get("kind") or "")
    unit_id = str(record.get("id") or "")
    if kind not in UNIT_KIND_DIRS or not unit_id:
        return None
    return record_path(project_root, kind, unit_id)


def _record_hash_suffix(unit_id: str) -> str:
    suffix = unit_id.rsplit("-", 1)[-1].lower()
    if re.fullmatch(r"[0-9a-f]{6,40}", suffix):
        return suffix
    return ""


def _ambiguous_record_reference(reference: str, records: list[dict[str, Any]]) -> None:
    candidate_ids = sorted({str(record.get("id") or "") for record in records if str(record.get("id") or "")})
    if candidate_ids:
        raise SystemExit(f"Ambiguous record reference: {reference}\nCandidates:\n- " + "\n- ".join(candidate_ids))
    raise SystemExit(f"Ambiguous record reference: {reference}")


def _resolve_unique_record_reference(reference: str, records: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not records:
        return None
    if len(records) == 1:
        return records[0]
    _ambiguous_record_reference(reference, records)
    return None


def _record_modified_sort_key(
    project_root: Path,
    record: dict[str, Any],
    *,
    safe_modified_time_ns: int = 0,
) -> tuple[int, float, str]:
    timestamp = str(record.get("updated_at") or record.get("created_at") or record.get("first_ingested_at") or "")
    parsed = parse_iso_datetime(timestamp)
    return (
        safe_modified_time_ns,
        parsed.timestamp() if parsed else 0.0,
        str(record.get("id") or ""),
    )


def locate_record(project_root: Path, unit_id: str, *, kind: str | None = None, fuzzy: bool = True) -> tuple[dict[str, Any], Path]:
    exact_reference = str(unit_id)
    reference = exact_reference.strip()
    search_kinds = [kind] if kind else list(UNIT_KIND_DIRS)
    for search_kind in search_kinds:
        if search_kind not in UNIT_KIND_DIRS:
            raise SystemExit(f"Unsupported unit kind: {search_kind}")
    snapshots = iter_canonical_record_snapshots(project_root, kind=kind)
    records = [
        record
        for snapshot in snapshots
        if (record := normalize_record_snapshot(snapshot, project_root)) is not None
    ]
    safe_mtime_by_identity = {
        (snapshot.kind, snapshot.unit_id): snapshot.modified_time_ns
        for snapshot in snapshots
    }
    exact_matches = [record for record in records if str(record.get("id") or "") == exact_reference]
    resolved_exact = _resolve_unique_record_reference(exact_reference, exact_matches)
    if resolved_exact:
        resolved_kind = str(resolved_exact.get("kind") or "")
        return resolved_exact, record_path(project_root, resolved_kind, exact_reference)
    for record in records:
        if exact_reference in _unique_text_list(record.get("legacy_ids")):
            current_kind = str(record.get("kind") or "")
            current_id = str(record.get("id") or "")
            if current_kind in UNIT_KIND_DIRS and current_id:
                return record, record_path(project_root, current_kind, current_id)
    if not fuzzy:
        raise SystemExit(f"Record not found: {unit_id}")
    folded = reference.casefold()
    if folded in {"last", "current"}:
        modified_records = [record for record in records if _record_lookup_path(project_root, record)]
        if modified_records:
            resolved = max(
                modified_records,
                key=lambda record: _record_modified_sort_key(
                    project_root,
                    record,
                    safe_modified_time_ns=safe_mtime_by_identity.get(
                        (str(record.get("kind") or ""), str(record.get("id") or "")),
                        0,
                    ),
                ),
            )
            path = _record_lookup_path(project_root, resolved)
            if path:
                return resolved, path
    if folded:
        prefix_matches = [
            record
            for record in records
            if str(record.get("id") or "").casefold().startswith(folded)
            or bool(_record_hash_suffix(str(record.get("id") or "")).casefold().startswith(folded))
        ]
        resolved = _resolve_unique_record_reference(reference, prefix_matches)
        if resolved:
            path = _record_lookup_path(project_root, resolved)
            if path:
                return resolved, path
        title_reference = folded
        title_matches = [
            record
            for record in records
            if title_reference in str(record.get("title") or "").casefold()
        ]
        resolved = _resolve_unique_record_reference(reference, title_matches)
        if resolved:
            path = _record_lookup_path(project_root, resolved)
            if path:
                return resolved, path
    raise SystemExit(f"Record not found: {unit_id}")


__all__ = [
    "INFORMATION_TYPES",
    "MATURITY_LEVELS",
    "DEFAULT_REUSE_FLAGS",
    "AI_INFORMATION_TYPES",
    "WORKFLOW_STATES",
    "CanonicalRecordSnapshot",
    "CanonicalUnitSnapshot",
    "ProjectFileSnapshot",
    "ProjectYamlMappingSnapshot",
    "iter_canonical_record_snapshots",
    "canonical_record_snapshot_if_present",
    "canonical_record_snapshot_for_identity",
    "canonical_record_snapshot_for_record",
    "require_current_record_snapshot",
    "normalize_record_snapshot",
    "snapshot_canonical_unit_artifacts",
    "snapshot_canonical_unit_tree",
    "snapshot_unique_canonical_unit_tree",
    "snapshot_project_file",
    "snapshot_project_yaml_mapping",
    "snapshot_project_evidence_source",
    "command_mutation",
    "trusted_project_path",
    "trusted_unit_record_path",
    "trusted_program_root",
    "trusted_claim_source_roots",
    "kind_payload_skeleton",
    "_extract_unit_id_hash",
    "_record_template",
    "record_summary",
    "append_history",
    "default_record",
    "normalize_record_schema",
    "_record_needs_gate",
    "record_workflow_state",
    "is_ready_for_human_review",
    "iter_records",
    "_record_lookup_path",
    "_record_hash_suffix",
    "_ambiguous_record_reference",
    "_resolve_unique_record_reference",
    "_record_modified_sort_key",
    "locate_record",
]
