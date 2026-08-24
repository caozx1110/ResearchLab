"""Markdown-first Research Vault v2 source capture mechanics.

This module saves exact bytes before exposing any derived reader. It deliberately
contains no subprocess, network, macro, formula, or source-code execution path.
Optional converter boundaries are injected callables that return candidate data;
the capture owner validates and records their output without granting them
ownership of source revisions or visible research meaning.
"""

from __future__ import annotations

import argparse
import base64
import csv
import hashlib
import html
import io
import json
import mimetypes
import os
import re
import stat
import tempfile
import threading
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Iterator, Mapping, Optional, Sequence
from urllib.parse import urlsplit

try:
    import fcntl
except ImportError:
    fcntl = None


SCHEMA = "research-capture/v2"
SOURCE_MAP_SCHEMA = "research-capture-source-map/v2"
TRANSACTION_SCHEMA = "research-capture-transaction/v2"
STAGES = ("captured", "reader-ready", "evidence-ready", "analysis-ready")
HEALTH = ("ok", "degraded", "blocked", "stale")
STAGE_RANK = {stage: index for index, stage in enumerate(STAGES)}
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_TREE_FILES = 10_000
MAX_TREE_BYTES = 256 * 1024 * 1024
MAX_READER_BYTES = 32 * 1024 * 1024
MAX_TRANSACTION_JOURNAL_BYTES = 256 * 1024 * 1024
MAX_HTML_BLOCKS = 20_000
MAX_CSV_ROWS = 10_000
MAX_CSV_COLUMNS = 1_000
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,199}$")
SAFE_ASSET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
LEGACY_MARKERS = (
    ("kb",),
    ("record.yaml",),
    ("config", "workspace-layout.yaml"),
    ("obsidian", "managed"),
)
_PROCESS_LOCKS: dict[tuple[str, str], threading.Lock] = {}
_PROCESS_LOCKS_GUARD = threading.Lock()

KIND_ALIASES = {
    "web": "web-html",
    "html": "web-html",
    "web-html": "web-html",
    "markdown": "markdown",
    "md": "markdown",
    "text": "text",
    "txt": "text",
    "pdf": "pdf",
    "repo": "repo",
    "source-tree": "repo",
    "dataset": "dataset",
    "binary": "binary",
    "media": "binary",
    "office": "office",
    "docx": "office",
    "pptx": "office",
    "xlsx": "office",
    "odf": "odf",
    "odt": "odf",
    "ods": "odf",
    "odp": "odf",
    "rtf": "rtf",
    "epub": "epub",
    "csv": "csv",
}
ADAPTER_KINDS = {"pdf", "office", "odf", "rtf", "epub", "binary", "dataset"}
TREE_KINDS = {"repo", "dataset"}
TEXT_SUFFIXES = {
    ".md",
    ".markdown",
    ".txt",
    ".rst",
    ".py",
    ".js",
    ".ts",
    ".java",
    ".go",
    ".rs",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".xml",
    ".html",
    ".css",
    ".sql",
    ".sh",
}


class CaptureError(Exception):
    """Base class for safe capture failures."""


class UnsafeInputError(CaptureError):
    """The explicitly selected input violates a no-follow safety boundary."""


class LegacyWorkspaceError(CaptureError):
    """A v1 workspace marker requires an explicit out-of-band migration."""


class ImmutableRevisionError(CaptureError):
    """An immutable raw or derived revision would be overwritten."""


class AdapterUnavailable(CaptureError):
    """An optional adapter was not provided by the host."""


class AdapterFailure(CaptureError):
    """An optional adapter failed without invalidating the raw revision."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _require_identifier(value: str, label: str) -> str:
    if not isinstance(value, str) or not IDENTIFIER_RE.fullmatch(value) or value in {".", ".."}:
        raise UnsafeInputError(f"{label} must be a safe stable identifier")
    return value


def normalize_kind(source_kind: str) -> str:
    try:
        kind = KIND_ALIASES[source_kind.casefold()]
    except (AttributeError, KeyError) as exc:
        raise CaptureError(f"unsupported source kind: {source_kind!r}") from exc
    return kind


def _safe_filename(filename: str, fallback: str) -> str:
    raw_name = str(filename or fallback)
    if "/" in raw_name or "\\" in raw_name:
        raise UnsafeInputError("source filename must be a safe basename")
    name = Path(raw_name).name
    if name in {"", ".", ".."} or not SAFE_FILENAME_RE.fullmatch(name):
        raise UnsafeInputError("source filename must be a safe basename")
    return name


def _safe_relative_path(value: str) -> str:
    if not isinstance(value, str) or not value or value.startswith(("/", "\\")) or "\\" in value:
        raise UnsafeInputError(f"unsafe relative source path: {value!r}")
    path = PurePosixPath(value)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise UnsafeInputError(f"unsafe relative source path: {value!r}")
    return path.as_posix()


def _media_type(filename: str, explicit: Optional[str]) -> str:
    if explicit and isinstance(explicit, str) and explicit.strip():
        return explicit.split(";", 1)[0].strip().lower()
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"


def _read_regular_file(path: Path, max_bytes: int) -> bytes:
    try:
        info = path.lstat()
    except OSError as exc:
        raise CaptureError(f"cannot stat selected source: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise UnsafeInputError(f"selected source must be a regular non-symlink file: {path}")
    if info.st_size > max_bytes:
        raise CaptureError(f"selected source exceeds byte budget: {path}")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(str(path), flags)
    try:
        current = os.fstat(descriptor)
        if stat.S_ISLNK(current.st_mode) or not stat.S_ISREG(current.st_mode):
            raise UnsafeInputError(f"selected source changed to a non-regular file: {path}")
        if current.st_size > max_bytes:
            raise CaptureError(f"selected source exceeds byte budget: {path}")
        chunks: list[bytes] = []
        total = 0
        while True:
            chunk = os.read(descriptor, min(1024 * 1024, max_bytes - total + 1))
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
            if total > max_bytes:
                raise CaptureError(f"selected source exceeds byte budget: {path}")
        return b"".join(chunks)
    finally:
        os.close(descriptor)


def _read_optional_regular(path: Path, max_bytes: int) -> Optional[bytes]:
    try:
        path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        raise UnsafeInputError(f"cannot inspect capture file: {path}") from exc
    return _read_regular_file(path, max_bytes)


def _legacy_marker_present(root: Path, parts: Sequence[str]) -> bool:
    current = root
    for index, part in enumerate(parts):
        current = current / part
        try:
            info = current.lstat()
        except FileNotFoundError:
            return False
        except OSError as exc:
            raise UnsafeInputError(f"cannot inspect legacy workspace marker: {'/'.join(parts)}") from exc
        if index < len(parts) - 1 and (stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode)):
            return True
    return True


def _assert_no_legacy_workspace(root: Path) -> None:
    try:
        root_info = root.lstat()
    except FileNotFoundError:
        return
    except OSError as exc:
        raise UnsafeInputError(f"cannot inspect workspace root: {root}") from exc
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise UnsafeInputError("capture workspace root must be a real directory")
    found = ["/".join(parts) for parts in LEGACY_MARKERS if _legacy_marker_present(root, parts)]
    if found:
        raise LegacyWorkspaceError(f"legacy workspace markers require explicit migration: {found}")


def _directory_open_flags() -> int:
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise UnsafeInputError("capture requires no-follow directory descriptors")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    return flags


def _open_or_create_directory_at(parent_fd: int, name: str) -> int:
    try:
        os.mkdir(name, 0o700, dir_fd=parent_fd)
    except FileExistsError:
        pass
    except OSError as exc:
        raise UnsafeInputError(f"cannot create capture directory: {name}") from exc
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise UnsafeInputError(f"capture path is not a real directory: {name}")
        return os.open(name, _directory_open_flags(), dir_fd=parent_fd)
    except UnsafeInputError:
        raise
    except OSError as exc:
        raise UnsafeInputError(f"cannot open capture directory without following links: {name}") from exc


@contextmanager
def _object_capture_lock(vault_root: Path, source_id: str) -> Iterator[None]:
    if fcntl is None:
        raise UnsafeInputError("capture requires a no-follow file-lock implementation")
    lock_key = (os.path.abspath(os.fspath(vault_root)), source_id)
    with _PROCESS_LOCKS_GUARD:
        process_lock = _PROCESS_LOCKS.setdefault(lock_key, threading.Lock())
    process_lock.acquire()
    descriptors: list[int] = []
    lock_fd: Optional[int] = None
    try:
        _ensure_directory(vault_root)
        try:
            root_fd = os.open(vault_root, _directory_open_flags())
        except OSError as exc:
            raise UnsafeInputError("cannot open capture workspace without following links") from exc
        descriptors.append(root_fd)
        _assert_no_legacy_workspace(vault_root)
        for component in ("Sources", source_id, ".source"):
            descriptors.append(_open_or_create_directory_at(descriptors[-1], component))
        flags = os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW
        if hasattr(os, "O_CLOEXEC"):
            flags |= os.O_CLOEXEC
        try:
            lock_fd = os.open("capture.lock", flags, 0o600, dir_fd=descriptors[-1])
        except OSError as exc:
            raise UnsafeInputError("capture object lock must be a regular non-symlink file") from exc
        lock_info = os.fstat(lock_fd)
        if not stat.S_ISREG(lock_info.st_mode):
            raise UnsafeInputError("capture object lock must be a regular non-symlink file")
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        yield
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            finally:
                os.close(lock_fd)
        for descriptor in reversed(descriptors):
            os.close(descriptor)
        process_lock.release()


def _safe_asset_name(name: str) -> str:
    raw_name = str(name)
    if "/" in raw_name or "\\" in raw_name:
        raise UnsafeInputError("adapter asset name must be a safe basename")
    value = Path(raw_name).name
    if value in {"", ".", ".."} or not SAFE_ASSET_RE.fullmatch(value):
        raise UnsafeInputError("adapter asset name must be a safe basename")
    return value


def _normalize_output(value: Any, adapter_name: str, adapter_version: str) -> "AdapterOutput":
    if isinstance(value, AdapterOutput):
        return value
    if not isinstance(value, Mapping):
        raise AdapterFailure(f"{adapter_name} returned a non-mapping result")
    text = value.get("markdown")
    if text is None:
        text = value.get("text")
    if text is not None and not isinstance(text, str):
        raise AdapterFailure(f"{adapter_name} returned non-text candidate Markdown")
    raw_assets = value.get("assets", {})
    if raw_assets is None:
        raw_assets = {}
    if not isinstance(raw_assets, Mapping):
        raise AdapterFailure(f"{adapter_name} returned invalid assets")
    assets: dict[str, bytes] = {}
    for name, data in raw_assets.items():
        safe_name = _safe_asset_name(str(name))
        if not isinstance(data, bytes):
            raise AdapterFailure(f"{adapter_name} returned non-byte asset: {name!r}")
        assets[safe_name] = data
    raw_diagnostics = value.get("diagnostics", value.get("warnings", ()))
    if isinstance(raw_diagnostics, str):
        diagnostics = (raw_diagnostics,)
    elif isinstance(raw_diagnostics, Iterable):
        diagnostics = tuple(str(item) for item in raw_diagnostics)
    else:
        diagnostics = (str(raw_diagnostics),)
    status = str(value.get("status", "ok"))
    return AdapterOutput(
        markdown=text,
        source_map=value.get("source_map"),
        assets=assets,
        diagnostics=diagnostics,
        status=status,
        converter=str(value.get("converter", adapter_name)),
        version=str(value.get("version", adapter_version)),
    )


@dataclass(frozen=True)
class AdapterOutput:
    markdown: Optional[str]
    source_map: Optional[Mapping[str, Any]] = None
    assets: Mapping[str, bytes] = field(default_factory=dict)
    diagnostics: Sequence[str] = field(default_factory=tuple)
    status: str = "ok"
    converter: str = "external"
    version: str = "unknown"


class OptionalAdapter:
    name = "optional-adapter"
    version = "interface-v2"

    def __init__(self, converter: Optional[Callable[..., Any]] = None, *, name: Optional[str] = None, version: Optional[str] = None) -> None:
        self.converter = converter
        if name:
            self.name = name
        if version:
            self.version = version

    def convert(self, payload: Any, **context: Any) -> AdapterOutput:
        if self.converter is None:
            raise AdapterUnavailable(f"optional adapter unavailable: {self.name}")
        try:
            result = self.converter(payload, **context)
        except Exception as exc:
            raise AdapterFailure(f"{self.name} failed: {exc}") from exc
        return _normalize_output(result, self.name, self.version)


class DefuddleAdapter(OptionalAdapter):
    name = "defuddle"


class AnyDocAdapter(OptionalAdapter):
    name = "anydoc"


class PdfAdapter(OptionalAdapter):
    name = "pdf-adapter"


class RepoAdapter(OptionalAdapter):
    name = "repo-adapter"


@dataclass(frozen=True)
class CaptureResult:
    source_id: str
    source_kind: str
    revision_id: str
    stage: str
    health: str
    raw_digest: str
    raw_path: Path
    manifest_path: Path
    index_path: Path
    reader_path: Optional[Path]
    source_map_path: Optional[Path]
    diagnostics: tuple[str, ...] = ()
    same_bytes: bool = False
    reader_modified: bool = False

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "source_id": self.source_id,
            "source_kind": self.source_kind,
            "revision_id": self.revision_id,
            "stage": self.stage,
            "health": self.health,
            "raw_digest": self.raw_digest,
            "raw_path": self.raw_path.as_posix(),
            "manifest_path": self.manifest_path.as_posix(),
            "index_path": self.index_path.as_posix(),
            "reader_path": self.reader_path.as_posix() if self.reader_path else None,
            "source_map_path": self.source_map_path.as_posix() if self.source_map_path else None,
            "diagnostics": list(self.diagnostics),
            "same_bytes": self.same_bytes,
            "reader_modified": self.reader_modified,
        }
        return payload


def _normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _decode_text(data: bytes) -> tuple[str, tuple[str, ...]]:
    try:
        return _normalize_newlines(data.decode("utf-8-sig")), ()
    except UnicodeDecodeError:
        return data.decode("utf-8", errors="replace"), ("source is not valid UTF-8; replacement characters used",)


def _line_ranges(text: str) -> list[tuple[int, int, str]]:
    lines = text.splitlines()
    result: list[tuple[int, int, str]] = []
    for index, line in enumerate(lines, start=1):
        result.append((index, index, line))
    if not result and text == "":
        return []
    return result


def _blocks_for_text(text: str, source_kind: str, *, filename: str = "source") -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    for line_start, line_end, line in _line_ranges(text):
        if not line.strip():
            continue
        block_id = f"block-{len(blocks) + 1:05d}"
        locator: dict[str, Any] = {"type": source_kind, "line": line_start}
        heading = re.match(r"^#{1,6}\s+(.+?)\s*#*$", line)
        if heading:
            slug = re.sub(r"[^a-z0-9 -]", "", heading.group(1).casefold()).strip().replace(" ", "-")
            locator["heading"] = slug or f"line-{line_start}"
        if source_kind == "csv":
            locator.update({"file": filename, "row": line_start - 1})
        if source_kind == "repo":
            locator.update({"path": filename, "line_start": line_start, "line_end": line_end})
        blocks.append(
            {
                "id": block_id,
                "reader_line_start": line_start,
                "reader_line_end": line_start,
                "quote": line,
                "locator": locator,
            }
        )
    return blocks


def _source_map(
    source_id: str,
    revision_id: str,
    source_kind: str,
    raw_digest: str,
    reader_bytes: bytes,
    blocks: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    return {
        "schema": SOURCE_MAP_SCHEMA,
        "source_id": source_id,
        "revision_id": revision_id,
        "source_kind": source_kind,
        "raw_sha256": raw_digest,
        "reader_sha256": sha256_bytes(reader_bytes),
        "locator_scope": "typed-source-locator",
        "blocks": [dict(block) for block in blocks],
    }


def _replay_locator_quote(
    locator: Mapping[str, Any],
    quote: str,
    *,
    source_kind: str,
    raw_files: Mapping[str, bytes],
    raw_name: str,
) -> Optional[str]:
    locator_type = locator.get("type")
    if not isinstance(locator_type, str) or not locator_type:
        return "locator type is missing"
    if locator_type == "byte-range":
        relative = locator.get("path", locator.get("file"))
        if len(raw_files) == 1 and relative in {None, raw_name}:
            data = next(iter(raw_files.values()))
        elif isinstance(relative, str) and relative in raw_files:
            data = raw_files[relative]
        else:
            return "byte-range locator does not identify a captured raw object"
        start = locator.get("byte_start")
        end = locator.get("byte_end")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or start < 0
            or end <= start
            or end > len(data)
        ):
            return "byte-range locator is outside the captured raw object"
        try:
            replayed = data[start:end].decode("utf-8")
        except UnicodeDecodeError:
            return "byte-range locator does not identify UTF-8 evidence bytes"
        if replayed != quote:
            return "byte-range locator does not replay the exact reader quote"
        return None
    if len(raw_files) == 1:
        single_data = next(iter(raw_files.values()))
    else:
        single_data = b""
    if source_kind in {"markdown", "text"} and locator_type == source_kind:
        line_number = locator.get("line")
        if not isinstance(line_number, int) or isinstance(line_number, bool) or line_number < 1:
            return "text locator line is invalid"
        text, _ = _decode_text(single_data)
        if source_kind == "markdown":
            text = _passivate_markdown(text)
        lines = text.splitlines()
        if line_number > len(lines) or lines[line_number - 1] != quote:
            return "text locator does not replay the exact source line"
        return None
    if source_kind == "web-html" and locator_type == "html":
        try:
            _, replay_blocks, _ = _passive_html(single_data)
        except CaptureError:
            return "HTML locator cannot be replayed from the captured response"
        for replay_block in replay_blocks:
            replay_locator = replay_block.get("locator", {})
            if replay_block.get("quote") != quote:
                continue
            if locator.get("fragment") and replay_locator.get("fragment") != locator.get("fragment"):
                continue
            return None
        return "HTML locator cannot replay the exact source quote"
    if source_kind == "csv" and locator_type == "csv":
        if locator.get("file") != raw_name:
            return "CSV locator file does not match the captured object"
        row_number = locator.get("row")
        if not isinstance(row_number, int) or isinstance(row_number, bool) or row_number < 1:
            return "CSV locator row is invalid"
        text, _ = _decode_text(single_data)
        try:
            rows = list(csv.reader(io.StringIO(text)))
        except csv.Error:
            return "CSV locator cannot be replayed from the captured object"
        if row_number > len(rows) or ",".join(rows[row_number - 1]) != quote:
            return "CSV locator cannot replay the exact source row"
        return None
    if source_kind == "repo" and locator_type == "repo":
        relative = locator.get("path")
        if not isinstance(relative, str) or relative not in raw_files:
            return "repository locator path is not in the captured tree"
        data = raw_files[relative]
        expected = f"- `{relative}` — {len(data)} bytes — `{sha256_bytes(data)}`"
        if quote != expected:
            return "repository locator cannot replay the exact indexed member"
        return None
    if source_kind == "dataset" and locator_type == "dataset":
        relative = locator.get("file")
        if not isinstance(relative, str) or relative not in raw_files:
            return "dataset locator file is not in the captured selection"
        data = raw_files[relative]
        expected = f"- `{relative}` — {len(data)} bytes — `{sha256_bytes(data)}`"
        if quote != expected:
            return "dataset locator cannot replay the exact indexed member"
        return None
    return "locator cannot be replayed from the captured raw object"


def validate_source_map(
    source_map: Mapping[str, Any],
    *,
    raw_digest: str,
    reader_bytes: bytes,
    source_kind: str,
    raw_files: Mapping[str, bytes],
    raw_name: str,
    source_id: Optional[str] = None,
    revision_id: Optional[str] = None,
) -> list[str]:
    errors: list[str] = []
    if source_map.get("schema") != SOURCE_MAP_SCHEMA:
        errors.append("source map schema is missing or unsupported")
    if source_map.get("raw_sha256") != raw_digest:
        errors.append("source map raw digest does not match revision")
    if source_map.get("reader_sha256") != sha256_bytes(reader_bytes):
        errors.append("source map reader digest does not match candidate reader")
    if source_id and source_map.get("source_id") != source_id:
        errors.append("source map source id does not match revision")
    if revision_id and source_map.get("revision_id") != revision_id:
        errors.append("source map revision id does not match revision")
    blocks = source_map.get("blocks")
    if not isinstance(blocks, list):
        return errors + ["source map blocks must be a list"]
    if not blocks:
        return errors + ["source map must contain at least one replayable block"]
    reader_text = reader_bytes.decode("utf-8", errors="replace")
    lines = reader_text.splitlines()
    for index, block in enumerate(blocks):
        if not isinstance(block, Mapping):
            errors.append(f"source map block {index} is not a mapping")
            continue
        quote = block.get("quote")
        if not isinstance(quote, str) or not quote:
            errors.append(f"source map block {index} has no exact quote")
        start = block.get("reader_line_start")
        end = block.get("reader_line_end")
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start or end > len(lines):
            errors.append(f"source map block {index} has invalid reader line range")
        elif isinstance(quote, str) and quote not in "\n".join(lines[start - 1 : end]):
            errors.append(f"source map block {index} quote is absent from its reader line range")
        locator = block.get("locator")
        if not isinstance(locator, Mapping):
            errors.append(f"source map block {index} has no typed locator")
        elif isinstance(quote, str) and quote:
            replay_error = _replay_locator_quote(
                locator,
                quote,
                source_kind=source_kind,
                raw_files=raw_files,
                raw_name=raw_name,
            )
            if replay_error:
                errors.append(f"source map block {index} {replay_error}")
    return errors


class _PassiveHTML(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self.current: list[str] = []
        self.skip_depth = 0
        self.heading_level: Optional[int] = None
        self.heading_id = ""
        self.blocks: list[dict[str, Any]] = []

    def _flush(self) -> None:
        value = " ".join("".join(self.current).split()).strip()
        self.current = []
        if not value:
            return
        self.lines.append(value)
        line_number = len(self.lines) * 2 - 1
        locator: dict[str, Any] = {"type": "html", "kind": "text-quote"}
        if self.heading_level is not None:
            locator["heading_level"] = self.heading_level
            if self.heading_id:
                locator["fragment"] = self.heading_id
        self.blocks.append(
            {
                "id": f"block-{len(self.blocks) + 1:05d}",
                "reader_line_start": line_number,
                "reader_line_end": line_number,
                "quote": value,
                "locator": locator,
            }
        )
        self.heading_level = None
        self.heading_id = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Optional[str]]]) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "template", "iframe", "object", "embed", "noscript"}:
            self._flush()
            self.skip_depth += 1
            return
        if self.skip_depth:
            return
        attrs_map = {key.casefold(): value or "" for key, value in attrs}
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._flush()
            self.heading_level = int(tag[1])
            self.heading_id = re.sub(r"[^A-Za-z0-9._-]", "", attrs_map.get("id", ""))
        elif tag in {"p", "li", "pre", "blockquote", "br", "tr"}:
            self._flush()
        if tag == "li":
            self.current.append("- ")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.casefold()
        if tag in {"script", "style", "template", "iframe", "object", "embed", "noscript"}:
            if self.skip_depth:
                self.skip_depth -= 1
            return
        if self.skip_depth:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "blockquote", "br", "tr"}:
            self._flush()

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.current.append(data)

    def finish(self) -> tuple[str, list[dict[str, Any]]]:
        self._flush()
        return "\n\n".join(self.lines) + ("\n" if self.lines else ""), self.blocks


def _passive_html(data: bytes) -> tuple[str, list[dict[str, Any]], tuple[str, ...]]:
    text, diagnostics = _decode_text(data)
    parser = _PassiveHTML()
    try:
        parser.feed(text)
        parser.close()
    except Exception as exc:
        raise CaptureError(f"passive HTML reader failed: {exc}") from exc
    output, blocks = parser.finish()
    if not output:
        raise CaptureError("HTML reader found no passive readable blocks")
    return output, blocks, diagnostics


def _passive_csv(data: bytes, filename: str) -> tuple[str, list[dict[str, Any]], tuple[str, ...]]:
    text, diagnostics = _decode_text(data)
    reader = csv.reader(io.StringIO(text))
    rows: list[list[str]] = []
    try:
        for index, row in enumerate(reader):
            if index >= MAX_CSV_ROWS:
                raise CaptureError("CSV exceeds row budget")
            if len(row) > MAX_CSV_COLUMNS:
                raise CaptureError("CSV exceeds column budget")
            rows.append(row)
    except csv.Error as exc:
        raise CaptureError(f"CSV reader failed: {exc}") from exc
    output = "```csv\n" + text.rstrip("\n") + "\n```\n"
    blocks: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        quote = ",".join(row)
        blocks.append(
            {
                "id": f"row-{index:05d}",
                "reader_line_start": index + 1,
                "reader_line_end": index + 1,
                "quote": quote,
                "locator": {"type": "csv", "file": filename, "row": index},
            }
        )
    return output, blocks, diagnostics


def _passivate_markdown(text: str) -> str:
    """Escape active raw HTML and unsafe link schemes outside fenced code."""

    output: list[str] = []
    fence: Optional[str] = None
    raw_tag = re.compile(r"</?[A-Za-z][^>\n]*>")
    unsafe_link = re.compile(r"(\]\()\s*(?:javascript|vbscript|data\s*:\s*text/html)\s*:[^)]*\)", re.IGNORECASE)
    for line in text.splitlines(keepends=True):
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            token = marker.group(1)[0]
            if fence is None:
                fence = token
            elif fence == token:
                fence = None
            output.append(line)
            continue
        if fence is not None:
            output.append(line)
            continue
        passive = raw_tag.sub(lambda match: html.escape(match.group(0)), line)
        passive = unsafe_link.sub(r"\1#blocked-source-link)", passive)
        output.append(passive)
    return "".join(output)


def _literal_reader(text: str, language: str) -> tuple[str, int]:
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", text)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{text.rstrip()}\n{fence}\n", 1


def _shift_block_lines(blocks: Sequence[Mapping[str, Any]], amount: int) -> list[dict[str, Any]]:
    shifted_blocks: list[dict[str, Any]] = []
    for block in blocks:
        shifted = dict(block)
        for field_name in ("reader_line_start", "reader_line_end"):
            if isinstance(shifted.get(field_name), int):
                shifted[field_name] = int(shifted[field_name]) + amount
        shifted_blocks.append(shifted)
    return shifted_blocks


def _repo_reader(entries: Mapping[str, bytes]) -> tuple[str, list[dict[str, Any]], tuple[str, ...]]:
    lines = ["# Captured source tree", "", "The following entries are a passive index; no source was executed.", ""]
    blocks: list[dict[str, Any]] = []
    for relative in sorted(entries):
        data = entries[relative]
        digest = sha256_bytes(data)
        lines.append(f"- `{relative}` — {len(data)} bytes — `{digest}`")
        blocks.append(
            {
                "id": f"file-{len(blocks) + 1:05d}",
                "reader_line_start": len(lines),
                "reader_line_end": len(lines),
                "quote": lines[-1],
                "locator": {"type": "repo", "path": relative, "kind": "file"},
            }
        )
    if len(lines) == 4:
        lines.append("No files were selected.")
    return "\n".join(lines) + "\n", blocks, ()


def _dataset_reader(entries: Mapping[str, bytes]) -> tuple[str, list[dict[str, Any]], tuple[str, ...]]:
    lines = ["# Captured dataset selection", "", "This is a passive member manifest; values were not evaluated.", ""]
    blocks: list[dict[str, Any]] = []
    for relative in sorted(entries):
        data = entries[relative]
        line = f"- `{relative}` — {len(data)} bytes — `{sha256_bytes(data)}`"
        lines.append(line)
        blocks.append(
            {
                "id": f"member-{len(blocks) + 1:05d}",
                "reader_line_start": len(lines),
                "reader_line_end": len(lines),
                "quote": line,
                "locator": {"type": "dataset", "file": relative, "kind": "member"},
            }
        )
    return "\n".join(lines) + "\n", blocks, ()


def _built_in_output(kind: str, data: bytes, filename: str, entries: Optional[Mapping[str, bytes]] = None) -> AdapterOutput:
    if kind in {"markdown", "text"}:
        text, diagnostics = _decode_text(data)
        if kind == "markdown":
            text = _passivate_markdown(text)
            offset = 0
        else:
            text, offset = _literal_reader(text, "text")
        blocks = _blocks_for_text(text, kind, filename=filename)
        if offset:
            raw_text, _ = _decode_text(data)
            blocks = _shift_block_lines(_blocks_for_text(raw_text, kind, filename=filename), offset)
        return AdapterOutput(text, {"blocks": blocks}, diagnostics=diagnostics, converter="identity", version="v2")
    if kind == "web-html":
        text, blocks, diagnostics = _passive_html(data)
        return AdapterOutput(text, {"blocks": blocks}, diagnostics=diagnostics, converter="passive-html", version="v2")
    if kind == "csv":
        text, blocks, diagnostics = _passive_csv(data, filename)
        return AdapterOutput(text, {"blocks": blocks}, diagnostics=diagnostics, converter="passive-csv", version="v2")
    if kind == "repo":
        text, blocks, diagnostics = _repo_reader(entries or {})
        return AdapterOutput(text, {"blocks": blocks}, diagnostics=diagnostics, converter="passive-repo-index", version="v2")
    if kind == "dataset":
        text, blocks, diagnostics = _dataset_reader(entries or {})
        return AdapterOutput(text, {"blocks": blocks}, diagnostics=diagnostics, converter="passive-dataset-manifest", version="v2")
    raise AdapterUnavailable(f"no built-in reader for {kind}")


def _adapter_for(kind: str, adapter: Optional[OptionalAdapter]) -> OptionalAdapter:
    if adapter is not None:
        return adapter
    if kind == "web-html":
        return DefuddleAdapter()
    if kind == "pdf":
        return PdfAdapter()
    if kind == "repo":
        return RepoAdapter()
    return AnyDocAdapter()


def _write_immutable(path: Path, data: bytes) -> None:
    _ensure_directory(path.parent)
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(str(path), flags, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
        return
    except FileExistsError:
        existing = _read_regular_file(path, len(data))
        if existing != data:
            raise ImmutableRevisionError(f"immutable collision: {path}")


def _ensure_directory(path: Path) -> None:
    try:
        info = path.lstat()
    except FileNotFoundError:
        if path.parent == path:
            raise UnsafeInputError(f"cannot create directory root: {path}")
        _ensure_directory(path.parent)
        try:
            path.mkdir()
        except FileExistsError:
            pass
        info = path.lstat()
    except OSError as exc:
        raise UnsafeInputError(f"cannot inspect directory: {path}") from exc
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise UnsafeInputError(f"capture path is not a real directory: {path}")


def _write_atomic(path: Path, data: bytes) -> None:
    _ensure_directory(path.parent)
    if path.exists() or path.is_symlink():
        info = path.lstat()
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise UnsafeInputError(f"capture target is not a regular file: {path}")
    fd, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


@dataclass(frozen=True)
class _FileMutation:
    target: str
    before: Optional[bytes]
    after: Optional[bytes]


def _transaction_target(source_root: Path, target: str) -> Path:
    targets = {
        "reader.md": source_root / "reader.md",
        "index.md": source_root / "index.md",
        ".source/manifest.json": source_root / ".source" / "manifest.json",
    }
    try:
        return targets[target]
    except KeyError as exc:
        raise ImmutableRevisionError(f"capture transaction target is not allowed: {target}") from exc


def _transaction_target_limit(target: str) -> int:
    return 16 * 1024 * 1024 if target == ".source/manifest.json" else MAX_READER_BYTES


def _encoded_state(data: Optional[bytes]) -> dict[str, Any]:
    if data is None:
        return {"exists": False, "sha256": None, "base64": None}
    return {
        "exists": True,
        "sha256": sha256_bytes(data),
        "base64": base64.b64encode(data).decode("ascii"),
    }


def _decoded_state(payload: Any, target: str) -> Optional[bytes]:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("exists"), bool):
        raise ImmutableRevisionError("capture transaction state is invalid")
    if payload["exists"] is False:
        if payload.get("sha256") is not None or payload.get("base64") is not None:
            raise ImmutableRevisionError("capture transaction absent state is invalid")
        return None
    encoded = payload.get("base64")
    if not isinstance(encoded, str):
        raise ImmutableRevisionError("capture transaction state bytes are missing")
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError) as exc:
        raise ImmutableRevisionError("capture transaction state bytes are invalid") from exc
    if len(data) > _transaction_target_limit(target) or payload.get("sha256") != sha256_bytes(data):
        raise ImmutableRevisionError("capture transaction state digest is invalid")
    return data


def _mutation_payload(mutation: _FileMutation) -> dict[str, Any]:
    return {
        "target": mutation.target,
        "before": _encoded_state(mutation.before),
        "after": _encoded_state(mutation.after),
    }


def _mutation_from_payload(payload: Any) -> _FileMutation:
    if not isinstance(payload, Mapping) or not isinstance(payload.get("target"), str):
        raise ImmutableRevisionError("capture transaction mutation is invalid")
    target = str(payload["target"])
    _transaction_target(Path("."), target)
    return _FileMutation(
        target=target,
        before=_decoded_state(payload.get("before"), target),
        after=_decoded_state(payload.get("after"), target),
    )


def _apply_mutation_state(source_root: Path, mutation: _FileMutation, expected: Optional[bytes], desired: Optional[bytes]) -> None:
    path = _transaction_target(source_root, mutation.target)
    current = _read_optional_regular(path, _transaction_target_limit(mutation.target))
    if current == desired:
        return
    if current != expected:
        raise ImmutableRevisionError(f"capture transaction CAS conflict: {mutation.target}")
    if desired is None:
        try:
            info = path.lstat()
        except FileNotFoundError:
            return
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise UnsafeInputError(f"capture transaction target is unsafe: {mutation.target}")
        path.unlink()
    else:
        _write_atomic(path, desired)


def _remove_transaction_journal(journal_path: Path) -> None:
    try:
        info = journal_path.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise UnsafeInputError("capture transaction journal is not a regular file")
    journal_path.unlink()


def _recover_capture_transaction(source_root: Path) -> None:
    journal_path = source_root / ".source" / "transaction.json"
    raw_journal = _read_optional_regular(journal_path, MAX_TRANSACTION_JOURNAL_BYTES)
    if raw_journal is None:
        return
    try:
        payload = json.loads(raw_journal.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ImmutableRevisionError("capture transaction journal is unreadable") from exc
    if (
        not isinstance(payload, Mapping)
        or payload.get("schema") != TRANSACTION_SCHEMA
        or payload.get("source_id") != source_root.name
        or not isinstance(payload.get("mutations"), list)
    ):
        raise ImmutableRevisionError("capture transaction journal identity is invalid")
    mutations = [_mutation_from_payload(item) for item in payload["mutations"]]
    if [mutation.target for mutation in mutations] != ["reader.md", "index.md", ".source/manifest.json"]:
        raise ImmutableRevisionError("capture transaction target order is invalid")
    for mutation in mutations:
        _apply_mutation_state(source_root, mutation, mutation.before, mutation.after)
    _remove_transaction_journal(journal_path)


def _commit_capture_transaction(source_root: Path, mutations: Sequence[_FileMutation]) -> None:
    expected_targets = ["reader.md", "index.md", ".source/manifest.json"]
    if [mutation.target for mutation in mutations] != expected_targets:
        raise ImmutableRevisionError("capture transaction is incomplete or out of order")
    journal_path = source_root / ".source" / "transaction.json"
    if _read_optional_regular(journal_path, MAX_TRANSACTION_JOURNAL_BYTES) is not None:
        raise ImmutableRevisionError("capture transaction recovery is required before commit")
    payload = {
        "schema": TRANSACTION_SCHEMA,
        "source_id": source_root.name,
        "created_at": _utc_now(),
        "mutations": [_mutation_payload(mutation) for mutation in mutations],
    }
    _write_atomic(journal_path, _json_bytes(payload))
    try:
        for mutation in mutations:
            _apply_mutation_state(source_root, mutation, mutation.before, mutation.after)
    except BaseException:
        rollback_error: Optional[BaseException] = None
        for mutation in reversed(mutations):
            try:
                _apply_mutation_state(source_root, mutation, mutation.after, mutation.before)
            except BaseException as exc:
                rollback_error = exc
                break
        if rollback_error is None:
            _remove_transaction_journal(journal_path)
        else:
            raise ImmutableRevisionError("capture transaction rollback requires recovery") from rollback_error
        raise
    _remove_transaction_journal(journal_path)


def _manifest_from_bytes(
    raw_payload: Optional[bytes],
    path: Path,
    source_id: str,
    source_kind: Optional[str] = None,
) -> dict[str, Any]:
    if raw_payload is None:
        payload: dict[str, Any] = {"schema": SCHEMA, "source_id": source_id, "revisions": []}
        if source_kind:
            payload["source_kind"] = source_kind
        return payload
    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except (OSError, ValueError) as exc:
        raise ImmutableRevisionError(f"source manifest is unreadable: {path}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA or payload.get("source_id") != source_id:
        raise ImmutableRevisionError(f"source manifest identity mismatch: {path}")
    if source_kind and payload.get("source_kind") not in {None, source_kind}:
        raise ImmutableRevisionError(f"source manifest kind mismatch: {path}")
    if source_kind:
        payload["source_kind"] = source_kind
    if not isinstance(payload.get("revisions"), list):
        raise ImmutableRevisionError(f"source manifest revisions are invalid: {path}")
    return payload


def _load_manifest_snapshot(
    path: Path,
    source_id: str,
    source_kind: Optional[str] = None,
) -> tuple[dict[str, Any], Optional[bytes]]:
    raw_payload = _read_optional_regular(path, 16 * 1024 * 1024)
    return _manifest_from_bytes(raw_payload, path, source_id, source_kind), raw_payload


def _reader_document(source_id: str, filename: str, revision_id: str, text: str) -> bytes:
    header = (
        f"# Reader: {filename}\n\n"
        f"> Mechanically derived from source `{source_id}`, revision `{revision_id}`.\n\n"
    )
    return (header + text).encode("utf-8")


def _index_document(source_id: str, kind: str, revision_id: str, stage: str, health: str, raw_name: str, has_reader: bool) -> bytes:
    reader_link = "reader.md" if has_reader else "(reader unavailable; inspect the captured original)"
    return (
        f"---\nid: {source_id}\nkind: source\nstatus: {health}\n---\n\n"
        f"# Source: {source_id}\n\n"
        f"- Capture kind: `{kind}`\n"
        f"- Current revision: `{revision_id}`\n"
        f"- Stage: `{stage}`\n"
        f"- Health: `{health}`\n"
        f"- Reader: {reader_link}\n"
        f"- Original: [.source revision](.source/revisions/{revision_id}/{raw_name})\n\n"
        "This page contains capture provenance only; source meaning belongs in visible Markdown.\n"
    ).encode("utf-8")


def _find_revision(manifest: Mapping[str, Any], raw_digest: str) -> Optional[Mapping[str, Any]]:
    for revision in manifest.get("revisions", []):
        if isinstance(revision, Mapping) and revision.get("raw", {}).get("sha256") == raw_digest:
            return revision
    return None


def _load_unpublished_revision(path: Path, revision_id: str, raw_digest: str) -> Optional[dict[str, Any]]:
    raw_payload = _read_optional_regular(path, 16 * 1024 * 1024)
    if raw_payload is None:
        return None
    try:
        payload = json.loads(raw_payload.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ImmutableRevisionError("unpublished revision record is unreadable") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("revision_id") != revision_id
        or not isinstance(payload.get("raw"), Mapping)
        or payload["raw"].get("sha256") != raw_digest
        or not isinstance(payload.get("processing"), Mapping)
    ):
        raise ImmutableRevisionError("unpublished revision identity is invalid")
    return payload


def _verify_revision_raw(vault_root: Path, revision: Mapping[str, Any], raw_files: Mapping[str, bytes], tree_snapshot: bool) -> None:
    raw = revision.get("raw")
    if not isinstance(raw, Mapping):
        raise ImmutableRevisionError("revision raw record is missing")
    if tree_snapshot:
        entries = raw.get("entries")
        if not isinstance(entries, list):
            raise ImmutableRevisionError("tree revision member manifest is missing")
        recorded = {str(item.get("path")): item for item in entries if isinstance(item, Mapping)}
        if set(recorded) != set(raw_files):
            raise ImmutableRevisionError("immutable tree revision member set changed")
        for relative, expected in raw_files.items():
            path = vault_root / str(recorded[relative].get("raw_path"))
            if _read_regular_file(path, len(expected)) != expected:
                raise ImmutableRevisionError(f"immutable tree revision collision: {relative}")
        return
    expected = next(iter(raw_files.values()))
    if _read_regular_file(vault_root / str(raw.get("path")), len(expected)) != expected:
        raise ImmutableRevisionError("immutable source revision collision")


def _result_from_revision(
    vault_root: Path,
    source_id: str,
    kind: str,
    source_root: Path,
    manifest_path: Path,
    index_path: Path,
    revision: Mapping[str, Any],
    *,
    same_bytes: bool,
) -> CaptureResult:
    revision_id = str(revision["revision_id"])
    raw = revision["raw"]
    processing = revision.get("processing", {})
    reader_relative = processing.get("reader_path")
    map_relative = processing.get("source_map_path")
    return CaptureResult(
        source_id=source_id,
        source_kind=kind,
        revision_id=revision_id,
        stage=str(processing.get("stage", "captured")),
        health=str(processing.get("health", "degraded")),
        raw_digest=str(raw["sha256"]),
        raw_path=vault_root / str(raw["path"]),
        manifest_path=manifest_path,
        index_path=index_path,
        reader_path=vault_root / str(reader_relative) if reader_relative else None,
        source_map_path=vault_root / str(map_relative) if map_relative else None,
        diagnostics=tuple(str(item) for item in processing.get("diagnostics", [])),
        same_bytes=same_bytes,
        reader_modified=bool(processing.get("reader_modified", False)),
    )


def _capture_revision(
    vault_root: Path,
    source_id: str,
    kind: str,
    raw_files: Mapping[str, bytes],
    *,
    raw_name: str,
    requested_uri: Optional[str],
    final_uri: Optional[str],
    external_identity: Optional[str],
    media_type: Optional[str],
    adapter: Optional[OptionalAdapter],
    ocr_available: Optional[bool],
) -> CaptureResult:
    source_id = _require_identifier(source_id, "source_id")
    kind = normalize_kind(kind)
    if not raw_files:
        raise CaptureError("capture requires at least one exact source file")
    if any(not isinstance(data, bytes) for data in raw_files.values()):
        raise CaptureError("source snapshot values must be bytes")
    total_bytes = sum(len(data) for data in raw_files.values())
    if total_bytes > MAX_TREE_BYTES:
        raise CaptureError("source snapshot exceeds byte budget")
    raw_name = _safe_filename(raw_name, "original.bin")
    vault_root = Path(vault_root)
    _assert_no_legacy_workspace(vault_root)
    with _object_capture_lock(vault_root, source_id):
        _assert_no_legacy_workspace(vault_root)
        source_root = vault_root / "Sources" / source_id
        _recover_capture_transaction(source_root)
        return _capture_revision_locked(
            vault_root,
            source_id,
            kind,
            raw_files,
            raw_name=raw_name,
            requested_uri=requested_uri,
            final_uri=final_uri,
            external_identity=external_identity,
            media_type=media_type,
            adapter=adapter,
            ocr_available=ocr_available,
        )


def _capture_revision_locked(
    vault_root: Path,
    source_id: str,
    kind: str,
    raw_files: Mapping[str, bytes],
    *,
    raw_name: str,
    requested_uri: Optional[str],
    final_uri: Optional[str],
    external_identity: Optional[str],
    media_type: Optional[str],
    adapter: Optional[OptionalAdapter],
    ocr_available: Optional[bool],
) -> CaptureResult:
    total_bytes = sum(len(data) for data in raw_files.values())
    tree_snapshot = kind in TREE_KINDS
    if len(raw_files) == 1 and not tree_snapshot:
        single_data = next(iter(raw_files.values()))
        raw_digest = sha256_bytes(single_data)
    else:
        digest_input = b"".join(
            _json_bytes({"path": path, "sha256": sha256_bytes(raw_files[path]), "bytes": len(raw_files[path])})
            for path in sorted(raw_files)
        )
        raw_digest = sha256_bytes(digest_input)
    revision_id = f"rev-{raw_digest[:24]}"
    source_root = vault_root / "Sources" / source_id
    hidden_root = source_root / ".source"
    revision_root = hidden_root / "revisions" / revision_id
    manifest_path = hidden_root / "manifest.json"
    index_path = source_root / "index.md"
    manifest, manifest_before = _load_manifest_snapshot(manifest_path, source_id, kind)
    previous = _find_revision(manifest, raw_digest)
    unpublished = None if previous is not None else _load_unpublished_revision(revision_root / "revision.json", revision_id, raw_digest)
    capture_event: dict[str, Any] = {"captured_at": _utc_now()}
    for key, value in (("requested_uri", requested_uri), ("final_uri", final_uri), ("external_identity", external_identity)):
        if value:
            capture_event[key] = value
    if previous is not None or unpublished is not None:
        prior_revision = previous if previous is not None else unpublished
        if prior_revision is None:
            raise ImmutableRevisionError("capture revision recovery state is invalid")
        _verify_revision_raw(vault_root, prior_revision, raw_files, tree_snapshot)
        revision = dict(prior_revision)
        revision["capture_events"] = [*list(prior_revision.get("capture_events", [])), capture_event]
        revision["processing"] = dict(prior_revision.get("processing", {}))
        revision["raw"] = dict(prior_revision.get("raw", {}))
        same_bytes = True
    else:
        raw_paths: dict[str, str] = {}
        if len(raw_files) == 1 and not tree_snapshot:
            original_path = revision_root / raw_name
            _write_immutable(original_path, next(iter(raw_files.values())))
            raw_paths[raw_name] = original_path.relative_to(vault_root).as_posix()
        else:
            for relative, data in sorted(raw_files.items()):
                safe_relative = _safe_relative_path(relative)
                target = revision_root / "tree" / safe_relative
                _write_immutable(target, data)
                raw_paths[safe_relative] = target.relative_to(vault_root).as_posix()
        raw_record: dict[str, Any] = {
            "path": next(iter(raw_paths.values())) if len(raw_paths) == 1 and not tree_snapshot else f"Sources/{source_id}/.source/revisions/{revision_id}/tree",
            "filename": raw_name,
            "bytes": total_bytes,
            "sha256": raw_digest,
            "media_type": _media_type(raw_name, media_type),
        }
        if tree_snapshot:
            raw_record["entries"] = [
                {"path": path, "raw_path": raw_paths[path], "bytes": len(raw_files[path]), "sha256": sha256_bytes(raw_files[path])}
                for path in sorted(raw_files)
            ]
        if external_identity:
            raw_record["external_identity"] = external_identity
        diagnostics: list[str] = []
        output: Optional[AdapterOutput] = None
        try:
            if kind == "repo":
                if adapter is not None and adapter.converter is not None:
                    output = adapter.convert(raw_files, source_id=source_id, revision_id=revision_id, raw_digest=raw_digest, raw_paths=raw_paths)
                else:
                    output = _built_in_output(kind, b"", raw_name, raw_files)
            elif kind == "dataset":
                if adapter is not None and adapter.converter is not None:
                    output = adapter.convert(raw_files, source_id=source_id, revision_id=revision_id, raw_digest=raw_digest, raw_paths=raw_paths)
                else:
                    output = _built_in_output(kind, b"", raw_name, raw_files)
            elif kind in {"markdown", "text", "web-html", "csv"}:
                data = next(iter(raw_files.values()))
                if kind == "web-html" and adapter is not None and adapter.converter is not None:
                    output = adapter.convert(data, source_id=source_id, revision_id=revision_id, filename=raw_name, raw_digest=raw_digest, raw_paths=raw_paths)
                else:
                    output = _built_in_output(kind, data, raw_name)
                    if kind == "web-html" and adapter is not None and adapter.converter is None:
                        diagnostics.append("optional Defuddle adapter unavailable; used passive HTML reader")
            else:
                selected = next(iter(raw_files.values()))
                selected_adapter = _adapter_for(kind, adapter)
                output = selected_adapter.convert(selected, source_id=source_id, revision_id=revision_id, filename=raw_name, raw_digest=raw_digest, raw_paths=raw_paths)
        except AdapterUnavailable as exc:
            diagnostics.append(str(exc))
            output = None
        except (AdapterFailure, CaptureError) as exc:
            diagnostics.append(str(exc))
            output = None
        if ocr_available is False and kind == "pdf":
            diagnostics.append("OCR adapter unavailable; image-only pages are not readable")
        if output is not None:
            diagnostics.extend(str(item) for item in output.diagnostics)
        stage = "captured"
        health = "ok"
        source_map_path: Optional[Path] = None
        map_digest = ""
        normalized_relative = ""
        if output is None or not output.markdown or not output.markdown.strip():
            health = "degraded"
            diagnostics.append("stored-unparsed")
        else:
            candidate_text = _passivate_markdown(_normalize_newlines(output.markdown))
            if len(candidate_text.encode("utf-8")) > MAX_READER_BYTES:
                health = "degraded"
                diagnostics.append("candidate reader exceeds byte budget; stored-unparsed")
            else:
                reader_candidate = _reader_document(source_id, raw_name, revision_id, candidate_text)
                candidate_line_count = len(candidate_text.splitlines())
                reader_line_offset = len(reader_candidate.decode("utf-8").splitlines()) - candidate_line_count
                map_payload: Optional[dict[str, Any]] = None
                if output.source_map is not None:
                    raw_map = dict(output.source_map)
                    raw_blocks = raw_map.get("blocks")
                    if isinstance(raw_blocks, list):
                        shifted_blocks: list[dict[str, Any]] = []
                        for raw_block in raw_blocks:
                            if not isinstance(raw_block, Mapping):
                                shifted_blocks.append({"invalid": True})
                                continue
                            shifted = dict(raw_block)
                            for field_name in ("reader_line_start", "reader_line_end"):
                                if isinstance(shifted.get(field_name), int):
                                    shifted[field_name] = int(shifted[field_name]) + reader_line_offset
                            shifted_blocks.append(shifted)
                        map_payload = _source_map(source_id, revision_id, kind, raw_digest, reader_candidate, shifted_blocks)
                        map_errors = validate_source_map(
                            map_payload,
                            raw_digest=raw_digest,
                            reader_bytes=reader_candidate,
                            source_kind=kind,
                            raw_files=raw_files,
                            raw_name=raw_name,
                            source_id=source_id,
                            revision_id=revision_id,
                        )
                        if map_errors:
                            diagnostics.extend(f"invalid source map: {error}" for error in map_errors)
                            map_payload = None
                    else:
                        diagnostics.append("invalid source map: blocks must be a list")
                normalized_path = revision_root / "normalized.md"
                _write_immutable(normalized_path, reader_candidate)
                normalized_relative = normalized_path.relative_to(vault_root).as_posix()
                if map_payload is not None:
                    map_path = revision_root / "source-map.json"
                    map_bytes = _json_bytes(map_payload)
                    _write_immutable(map_path, map_bytes)
                    source_map_path = map_path
                    map_digest = sha256_bytes(map_bytes)
                    stage = "evidence-ready"
                else:
                    stage = "reader-ready"
                    diagnostics.append("missing-source-map")
                if output.status != "ok" or diagnostics or (ocr_available is False and kind == "pdf"):
                    health = "degraded"
        asset_paths: list[str] = []
        if output is not None:
            for name, data in sorted(output.assets.items()):
                asset_path = revision_root / "assets" / _safe_asset_name(name)
                _write_immutable(asset_path, data)
                asset_paths.append(asset_path.relative_to(vault_root).as_posix())
        processing = {
            "adapter": output.converter if output is not None else "none",
            "adapter_version": output.version if output is not None else "unknown",
            "status": output.status if output is not None else "unparsed",
            "stage": stage,
            "health": health,
            "diagnostics": list(dict.fromkeys(diagnostics)),
            "normalized_path": normalized_relative or None,
            "reader_path": None,
            "source_map_path": source_map_path.relative_to(vault_root).as_posix() if source_map_path else None,
            "reader_sha256": None,
            "source_map_sha256": map_digest or None,
            "asset_paths": asset_paths,
            "reader_modified": False,
        }
        revision = {
            "revision_id": revision_id,
            "capture_events": [capture_event],
            "raw": raw_record,
            "processing": processing,
            "currency": "current",
        }
        same_bytes = False

    processing = dict(revision.get("processing", {}))
    diagnostics = [str(item) for item in processing.get("diagnostics", [])]
    health = str(processing.get("health", "degraded"))
    stage = str(processing.get("stage", "captured"))
    normalized_relative = processing.get("normalized_path")
    reader_candidate: Optional[bytes] = None
    if isinstance(normalized_relative, str) and normalized_relative:
        reader_candidate = _read_regular_file(vault_root / normalized_relative, MAX_READER_BYTES)
    reader_path = source_root / "reader.md"
    reader_before = _read_optional_regular(reader_path, MAX_READER_BYTES)
    prior_reader_digest = manifest.get("current_reader_sha256")
    reader_modified = False
    if reader_candidate is not None:
        if reader_before is not None and (not isinstance(prior_reader_digest, str) or sha256_bytes(reader_before) != prior_reader_digest):
            reader_after = reader_before
            reader_modified = True
            health = "stale"
            diagnostics.append("reader.md has user edits; generated candidate was preserved in revision normalized.md")
        else:
            reader_after = reader_candidate
    elif reader_before is not None and (not isinstance(prior_reader_digest, str) or sha256_bytes(reader_before) != prior_reader_digest):
        reader_after = reader_before
        reader_modified = True
        health = "stale"
        diagnostics.append("reader.md has user edits; no generated reader was substituted")
    else:
        reader_after = None
    reader_digest = sha256_bytes(reader_after) if reader_after is not None else None
    processing["health"] = health
    processing["diagnostics"] = list(dict.fromkeys(diagnostics))
    processing["reader_path"] = reader_path.relative_to(vault_root).as_posix() if reader_after is not None else None
    processing["reader_sha256"] = reader_digest
    processing["reader_modified"] = reader_modified

    raw_record = revision.get("raw", {})
    index_raw_target = "tree" if tree_snapshot else str(raw_record.get("filename", raw_name))
    index_candidate = _index_document(source_id, kind, revision_id, stage, health, index_raw_target, reader_after is not None)
    index_before = _read_optional_regular(index_path, MAX_READER_BYTES)
    prior_index_digest = manifest.get("current_index_sha256")
    if index_before is not None and (not isinstance(prior_index_digest, str) or sha256_bytes(index_before) != prior_index_digest):
        index_after = index_before
        health = "stale"
        diagnostics.append("index.md has user edits; generated provenance page was preserved")
        processing["health"] = health
        processing["diagnostics"] = list(dict.fromkeys(diagnostics))
    else:
        index_after = index_candidate
    index_digest = sha256_bytes(index_after)
    revision["processing"] = processing
    revision["currency"] = "current"
    if not same_bytes:
        _write_immutable(revision_root / "revision.json", _json_bytes(revision))

    revisions: list[dict[str, Any]] = []
    replaced = False
    for item in manifest.get("revisions", []):
        if not isinstance(item, Mapping):
            raise ImmutableRevisionError("source manifest revision entry is invalid")
        if item.get("revision_id") == revision_id:
            current_item = dict(revision)
            replaced = True
        else:
            current_item = dict(item)
        current_item["currency"] = "current" if current_item.get("revision_id") == revision_id else "stale"
        revisions.append(current_item)
    if not replaced:
        revisions.append(dict(revision))
    manifest["revisions"] = revisions
    manifest["current_revision_id"] = revision_id
    if requested_uri:
        manifest["requested_uri"] = requested_uri
    if final_uri:
        manifest["final_uri"] = final_uri
    if external_identity:
        manifest["external_identity"] = external_identity
    manifest["current_reader_sha256"] = reader_digest
    manifest["current_index_sha256"] = index_digest
    manifest["updated_at"] = _utc_now()
    manifest_after = _json_bytes(manifest)
    _commit_capture_transaction(
        source_root,
        (
            _FileMutation("reader.md", reader_before, reader_after),
            _FileMutation("index.md", index_before, index_after),
            _FileMutation(".source/manifest.json", manifest_before, manifest_after),
        ),
    )
    committed_revision = next(item for item in revisions if item.get("revision_id") == revision_id)
    return _result_from_revision(
        vault_root,
        source_id,
        kind,
        source_root,
        manifest_path,
        index_path,
        committed_revision,
        same_bytes=same_bytes,
    )


def capture_bytes(
    vault_root: Path,
    source_id: str,
    source_kind: str,
    data: bytes,
    *,
    filename: str = "original.bin",
    requested_uri: Optional[str] = None,
    final_uri: Optional[str] = None,
    external_identity: Optional[str] = None,
    media_type: Optional[str] = None,
    adapter: Optional[OptionalAdapter] = None,
    ocr_available: Optional[bool] = None,
    max_bytes: int = MAX_SOURCE_BYTES,
) -> CaptureResult:
    if not isinstance(data, bytes):
        raise CaptureError("capture_bytes requires exact bytes")
    if len(data) > max_bytes:
        raise CaptureError("source exceeds byte budget")
    kind = normalize_kind(source_kind)
    uri = final_uri or requested_uri or ""
    if kind == "web-html" and PurePosixPath(urlsplit(uri).path).suffix.casefold() in {".md", ".markdown"}:
        kind = "markdown"
        adapter = None
    if kind in TREE_KINDS:
        raise CaptureError(f"{kind} capture requires capture_tree or capture_dataset")
    return _capture_revision(
        Path(vault_root),
        source_id,
        kind,
        {"original": data},
        raw_name=_safe_filename(filename, "original.bin"),
        requested_uri=requested_uri,
        final_uri=final_uri,
        external_identity=external_identity,
        media_type=media_type,
        adapter=adapter,
        ocr_available=ocr_available,
    )


def capture_file(
    vault_root: Path,
    source_id: str,
    source_kind: str,
    selected_file: Path,
    **kwargs: Any,
) -> CaptureResult:
    selected = Path(selected_file)
    filename = kwargs.pop("filename", selected.name)
    data = _read_regular_file(selected, int(kwargs.pop("max_bytes", MAX_SOURCE_BYTES)))
    return capture_bytes(vault_root, source_id, source_kind, data, filename=filename, **kwargs)


def capture_tree(
    vault_root: Path,
    source_id: str,
    source_kind: str,
    selected_root: Path,
    *,
    commit_identity: Optional[str] = None,
    archive_identity: Optional[str] = None,
    adapter: Optional[OptionalAdapter] = None,
    max_files: int = MAX_TREE_FILES,
    max_bytes: int = MAX_TREE_BYTES,
) -> CaptureResult:
    kind = normalize_kind(source_kind)
    if kind not in TREE_KINDS:
        raise CaptureError("capture_tree supports only repo or dataset sources")
    entries = _tree_files(selected_root, max_files, max_bytes)
    if kind == "repo" and not (commit_identity or archive_identity):
        raise CaptureError("repo capture requires a commit or archive identity")
    result = _capture_revision(
        Path(vault_root),
        source_id,
        kind,
        entries,
        raw_name="source-tree",
        requested_uri=None,
        final_uri=None,
        external_identity=commit_identity or archive_identity,
        media_type="application/x-directory",
        adapter=adapter,
        ocr_available=None,
    )
    return result


def capture_dataset(
    vault_root: Path,
    source_id: str,
    selected_members: Mapping[str, bytes],
    *,
    immutable_identity: Optional[str] = None,
    adapter: Optional[OptionalAdapter] = None,
) -> CaptureResult:
    if not isinstance(selected_members, Mapping) or not selected_members:
        raise CaptureError("capture_dataset requires explicitly selected members")
    safe_members = {_safe_relative_path(name): data for name, data in selected_members.items()}
    return capture_tree(
        vault_root,
        source_id,
        "dataset",
        _BytesTree(safe_members),
        archive_identity=immutable_identity,
        adapter=adapter,
    )


class _BytesTree:
    def __init__(self, entries: Mapping[str, bytes]) -> None:
        self.entries = dict(entries)

    def lstat(self) -> os.stat_result:
        mode = stat.S_IFDIR | 0o700
        return os.stat_result((mode, 0, 0, 0, 0, 0, 0, 0, 0, 0))


def _tree_files(root: Path, max_files: int, max_bytes: int) -> dict[str, bytes]:
    if isinstance(root, _BytesTree):
        entries = dict(root.entries)
        if len(entries) > max_files or sum(len(data) for data in entries.values()) > max_bytes:
            raise CaptureError("source tree exceeds budget")
        return entries
    try:
        root_info = root.lstat()
    except OSError as exc:
        raise CaptureError(f"cannot stat selected source tree: {root}") from exc
    if stat.S_ISLNK(root_info.st_mode) or not stat.S_ISDIR(root_info.st_mode):
        raise UnsafeInputError("selected source tree must be a real directory")
    collected: dict[str, bytes] = {}
    total_bytes = 0

    def visit(directory: Path, relative: str = "") -> None:
        nonlocal total_bytes
        try:
            entries = sorted(os.scandir(directory), key=lambda item: item.name)
        except OSError as exc:
            raise CaptureError(f"cannot enumerate selected source tree: {directory}") from exc
        for entry in entries:
            name = entry.name
            child_relative = f"{relative}/{name}" if relative else name
            safe_relative = _safe_relative_path(child_relative)
            child = directory / name
            info = child.lstat()
            if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
                raise UnsafeInputError(f"source tree contains unsafe node: {safe_relative}")
            if stat.S_ISDIR(info.st_mode):
                visit(child, safe_relative)
                continue
            if len(collected) >= max_files:
                raise CaptureError("source tree exceeds file-count budget")
            data = _read_regular_file(child, max_bytes - total_bytes)
            total_bytes += len(data)
            collected[safe_relative] = data

    visit(root)
    return collected


def inspect_manifest(manifest_path: Path) -> Mapping[str, Any]:
    payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping) or payload.get("schema") != SCHEMA:
        raise CaptureError("unsupported capture manifest")
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show-contract", action="store_true", help="print the mechanical stage and health contract")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    if args.show_contract:
        print(json.dumps({"schema": SCHEMA, "stages": STAGES, "health": HEALTH}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
