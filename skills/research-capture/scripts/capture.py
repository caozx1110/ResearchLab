"""Markdown-first Research Vault v2 source capture mechanics.

This module saves exact bytes before exposing any derived reader. It deliberately
contains no subprocess, network, macro, formula, or source-code execution path.
Optional converter boundaries are injected callables that return candidate data;
the capture owner validates and records their output without granting them
ownership of source revisions or visible research meaning.
"""

from __future__ import annotations

import argparse
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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping, Optional, Sequence
from urllib.parse import urlsplit


SCHEMA = "research-capture/v2"
SOURCE_MAP_SCHEMA = "research-capture-source-map/v2"
STAGES = ("captured", "reader-ready", "evidence-ready", "analysis-ready")
HEALTH = ("ok", "degraded", "blocked", "stale")
STAGE_RANK = {stage: index for index, stage in enumerate(STAGES)}
MAX_SOURCE_BYTES = 64 * 1024 * 1024
MAX_TREE_FILES = 10_000
MAX_TREE_BYTES = 256 * 1024 * 1024
MAX_READER_BYTES = 32 * 1024 * 1024
MAX_HTML_BLOCKS = 20_000
MAX_CSV_ROWS = 10_000
MAX_CSV_COLUMNS = 1_000
IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
SAFE_FILENAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,199}$")
SAFE_ASSET_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")

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


def validate_source_map(
    source_map: Mapping[str, Any],
    *,
    raw_digest: str,
    reader_bytes: bytes,
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
    lines = reader_bytes.decode("utf-8", errors="replace").splitlines()
    for index, block in enumerate(blocks):
        if not isinstance(block, Mapping):
            errors.append(f"source map block {index} is not a mapping")
            continue
        quote = block.get("quote")
        if not isinstance(quote, str) or not quote:
            errors.append(f"source map block {index} has no exact quote")
        elif quote not in reader_bytes.decode("utf-8", errors="replace"):
            errors.append(f"source map block {index} quote is absent from reader")
        start = block.get("reader_line_start")
        end = block.get("reader_line_end")
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start or end > len(lines):
            errors.append(f"source map block {index} has invalid reader line range")
        if not isinstance(block.get("locator"), Mapping):
            errors.append(f"source map block {index} has no typed locator")
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


def _load_manifest(path: Path, source_id: str, source_kind: Optional[str] = None) -> dict[str, Any]:
    raw_payload = _read_optional_regular(path, 16 * 1024 * 1024)
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


def _write_manifest(path: Path, payload: Mapping[str, Any]) -> None:
    _write_atomic(path, _json_bytes(payload))


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
    manifest = _load_manifest(manifest_path, source_id, kind)
    previous = _find_revision(manifest, raw_digest)
    if previous is not None:
        _verify_revision_raw(vault_root, previous, raw_files, tree_snapshot)
        events = list(previous.get("capture_events", []))
        event = {"captured_at": _utc_now()}
        if requested_uri:
            event["requested_uri"] = requested_uri
        if final_uri:
            event["final_uri"] = final_uri
        if external_identity:
            event["external_identity"] = external_identity
        events.append(event)
        for item in manifest["revisions"]:
            if isinstance(item, dict) and item.get("revision_id") == previous.get("revision_id"):
                item["capture_events"] = events
        manifest["current_revision_id"] = previous["revision_id"]
        _write_manifest(manifest_path, manifest)
        return _result_from_revision(vault_root, source_id, kind, source_root, manifest_path, index_path, previous, same_bytes=True)

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
    reader_path: Optional[Path] = None
    source_map_path: Optional[Path] = None
    reader_modified = False
    reader_digest = ""
    map_digest = ""
    normalized_relative = ""
    if output is None or not output.markdown or not output.markdown.strip():
        stage = "captured"
        health = "degraded"
        diagnostics.append("stored-unparsed")
    else:
        candidate_text = _passivate_markdown(_normalize_newlines(output.markdown))
        if len(candidate_text.encode("utf-8")) > MAX_READER_BYTES:
            stage = "captured"
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
                _write_immutable(map_path, _json_bytes(map_payload))
                source_map_path = map_path
                map_digest = sha256_bytes(_json_bytes(map_payload))
                stage = "evidence-ready"
            else:
                stage = "reader-ready"
                diagnostics.append("missing-source-map")
            if output.status != "ok":
                health = "degraded"
            if diagnostics:
                health = "degraded"
            if ocr_available is False and kind == "pdf":
                health = "degraded"
            reader_path = source_root / "reader.md"
            existing_reader = _read_optional_regular(reader_path, MAX_READER_BYTES)
            prior_reader_digest = manifest.get("current_reader_sha256")
            if existing_reader is not None and (prior_reader_digest is None or sha256_bytes(existing_reader) != prior_reader_digest):
                reader_modified = True
                health = "stale"
                diagnostics.append("reader.md has user edits; generated candidate was preserved in revision normalized.md")
                reader_digest = sha256_bytes(existing_reader)
            else:
                _write_atomic(reader_path, reader_candidate)
                reader_digest = sha256_bytes(reader_candidate)
    asset_paths: list[str] = []
    if output is not None:
        for name, data in sorted(output.assets.items()):
            asset_path = revision_root / "assets" / _safe_asset_name(name)
            _write_immutable(asset_path, data)
            asset_paths.append(asset_path.relative_to(vault_root).as_posix())
    index_raw_target = "tree" if tree_snapshot else raw_name
    index_candidate = _index_document(source_id, kind, revision_id, stage, health, index_raw_target, reader_path is not None)
    existing_index = _read_optional_regular(index_path, MAX_READER_BYTES)
    prior_index_digest = manifest.get("current_index_sha256")
    if existing_index is None:
        _write_immutable(index_path, index_candidate)
        index_digest = sha256_bytes(index_candidate)
    elif prior_index_digest is not None and sha256_bytes(existing_index) == prior_index_digest:
        _write_atomic(index_path, index_candidate)
        index_digest = sha256_bytes(index_candidate)
    else:
        index_digest = sha256_bytes(existing_index)
        health = "stale"
        diagnostics.append("index.md has user edits; generated provenance page was preserved")
    processing: dict[str, Any] = {
        "adapter": output.converter if output is not None else "none",
        "adapter_version": output.version if output is not None else "unknown",
        "status": output.status if output is not None else "unparsed",
        "stage": stage,
        "health": health,
        "diagnostics": list(dict.fromkeys(diagnostics)),
        "normalized_path": normalized_relative or None,
        "reader_path": reader_path.relative_to(vault_root).as_posix() if reader_path else None,
        "source_map_path": source_map_path.relative_to(vault_root).as_posix() if source_map_path else None,
        "reader_sha256": reader_digest or None,
        "source_map_sha256": map_digest or None,
        "asset_paths": asset_paths,
        "reader_modified": reader_modified,
    }
    capture_event: dict[str, Any] = {"captured_at": _utc_now()}
    for key, value in (("requested_uri", requested_uri), ("final_uri", final_uri), ("external_identity", external_identity)):
        if value:
            capture_event[key] = value
    revision: dict[str, Any] = {
        "revision_id": revision_id,
        "capture_events": [capture_event],
        "raw": raw_record,
        "processing": processing,
        "currency": "current",
    }
    _write_immutable(revision_root / "revision.json", _json_bytes(revision))
    previous_current = manifest.get("current_revision_id")
    for item in manifest.get("revisions", []):
        if isinstance(item, dict) and item.get("revision_id") == previous_current:
            item["currency"] = "stale"
    manifest["current_revision_id"] = revision_id
    manifest["revisions"].append(revision)
    if requested_uri:
        manifest["requested_uri"] = requested_uri
    if final_uri:
        manifest["final_uri"] = final_uri
    if external_identity:
        manifest["external_identity"] = external_identity
    manifest["current_reader_sha256"] = reader_digest or None
    manifest["current_index_sha256"] = index_digest
    manifest["updated_at"] = _utc_now()
    _write_manifest(manifest_path, manifest)
    result = _result_from_revision(vault_root, source_id, kind, source_root, manifest_path, index_path, revision, same_bytes=False)
    return result


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
