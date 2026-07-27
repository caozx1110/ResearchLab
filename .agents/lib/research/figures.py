"""Pure, mechanical helpers for stable paper figure references.

The module intentionally does not decide which figures are important.  It only
normalizes caption facts, binds immutable source/crop bytes, builds a
deterministic ``figure-index/v1`` document, and rejects stale consumers.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from .yaml_io import StrictYamlError, load_yaml_mapping_bytes_strict


FIGURE_INDEX_SCHEMA = "figure-index/v1"

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_PAPER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_ROMAN_RE = re.compile(r"^[ivxlcdm]+$", re.IGNORECASE)
_LABEL_RE = re.compile(
    r"^(?P<number>(?:[a-z]+)?(?:[0-9]+(?:[.]?[0-9]+)*|[ivxlcdm]+))"
    r"(?:[(._-]?(?P<panel>[a-z])[)]?)?$",
    re.IGNORECASE,
)
_CAPTION_PREFIX_RE = re.compile(
    r"^\s*(?:figure|fig[.]?|table)\s*"
    r"(?:[a-z]*[0-9ivxlcdm]+(?:[.][0-9]+)*"
    r"(?:[a-z]|\s*[(]\s*[a-z]\s*[)]|\s*[-_]\s*[a-z])?)?"
    r"\s*(?:[(]\s*continued\s*[)])?\s*[:.\-]?\s*",
    re.IGNORECASE,
)
_LEADING_PANEL_RE = re.compile(r"^\s*[(]\s*[a-z]\s*[)]\s*[:.\-]?\s*", re.IGNORECASE)
_CONTINUED_RE = re.compile(r"\s*[(]?\s*continued\s*[)]?\s*", re.IGNORECASE)

_INDEX_KEYS = {"schema", "paper_id", "source", "extraction", "entries", "index_digest"}
_SOURCE_KEYS = {"artifact", "sha256"}
_EXTRACTION_KEYS = {"settings"}
_ENTRY_KEYS = {"ref_key", "kind", "number", "caption", "caption_digest", "page", "pages", "assets"}
_ASSET_KEYS = {"path", "sha256", "page", "caption_bbox", "crop_bbox", "source_mode"}


class FigureIndexError(ValueError):
    """Raised when a figure index or reference is structurally unsafe/stale."""

    def __init__(self, violations: str | Sequence[str]):
        if isinstance(violations, str):
            items = (violations,)
        else:
            items = tuple(str(item) for item in violations if str(item).strip())
        self.violations = items or ("invalid figure index",)
        super().__init__("; ".join(self.violations))


def _clean_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.split())


def _canonical_json(value: Any) -> str:
    try:
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError) as exc:
        raise FigureIndexError(f"figure index contains a non-canonical value: {exc}") from exc


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha256(value: Any, *, where: str) -> str:
    digest = _clean_text(value).lower()
    if _SHA256_RE.fullmatch(digest) is None:
        raise FigureIndexError(f"{where} must be a lowercase sha256")
    return digest


def _positive_page(value: Any, *, where: str = "page") -> int:
    if isinstance(value, bool):
        raise FigureIndexError(f"{where} must be a positive integer")
    try:
        page = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise FigureIndexError(f"{where} must be a positive integer") from exc
    if page < 1 or str(value).strip() not in {str(page), f"{page}.0"}:
        raise FigureIndexError(f"{where} must be a positive integer")
    return page


def _roman_to_int(value: str) -> int:
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total = 0
    previous = 0
    for token in reversed(value.lower()):
        current = values[token]
        if current < previous:
            total -= current
        else:
            total += current
            previous = current
    # Reject non-canonical spellings rather than assigning two labels one number.
    canonical = _int_to_roman(total)
    if not canonical or canonical.lower() != value.lower():
        raise FigureIndexError(f"invalid roman caption number: {value}")
    return total


def _int_to_roman(value: int) -> str:
    if value < 1 or value > 3999:
        return ""
    pairs = (
        (1000, "M"),
        (900, "CM"),
        (500, "D"),
        (400, "CD"),
        (100, "C"),
        (90, "XC"),
        (50, "L"),
        (40, "XL"),
        (10, "X"),
        (9, "IX"),
        (5, "V"),
        (4, "IV"),
        (1, "I"),
    )
    remaining = value
    rendered: list[str] = []
    for number, token in pairs:
        while remaining >= number:
            rendered.append(token)
            remaining -= number
    return "".join(rendered)


def normalize_figure_kind(value: Any) -> str:
    """Normalize a mechanical caption kind to the ref-key token ``fig``/``tbl``."""
    normalized = _clean_text(value).casefold().rstrip(".")
    if normalized in {"fig", "figure"}:
        return "fig"
    if normalized in {"tbl", "table"}:
        return "tbl"
    raise FigureIndexError(f"unsupported figure kind: {value}")


def normalize_caption_number(value: Any) -> str:
    """Return a logical caption number, dropping a panel suffix mechanically.

    ``01a``, ``1(a)`` and ``1-b`` therefore bind the logical Figure 1.  Roman
    numerals are converted to decimal, and supplementary prefixes are retained
    (``S01a`` -> ``s1``).  Missing/unknown labels return an empty string so the
    caller can use the explicit unnumbered fallback.
    """
    raw = _clean_text(value).casefold()
    raw = re.sub(r"^(?:figure|fig[.]?|table)\s*", "", raw).strip()
    raw = _CONTINUED_RE.sub("", raw).strip(" :.-_()")
    if not raw or raw in {"unknown", "unnumbered", "none", "n/a"}:
        return ""
    compact = re.sub(r"\s+", "", raw)
    if _ROMAN_RE.fullmatch(compact):
        return str(_roman_to_int(compact))
    match = _LABEL_RE.fullmatch(compact)
    if match is None:
        raise FigureIndexError(f"invalid caption number: {value}")
    number = match.group("number").casefold()
    prefix_match = re.fullmatch(r"([a-z]+)([0-9]+(?:[.]?[0-9]+)*)", number)
    if prefix_match:
        prefix, numeric = prefix_match.groups()
        parts = numeric.split(".") if "." in numeric else re.findall(r"[0-9]+", numeric)
        normalized_numeric = ".".join(str(int(part)) for part in parts)
        return f"{prefix}{normalized_numeric}"
    if _ROMAN_RE.fullmatch(number):
        return str(_roman_to_int(number))
    parts = number.split(".") if "." in number else re.findall(r"[0-9]+", number)
    return ".".join(str(int(part)) for part in parts)


def normalize_caption_text(value: Any) -> str:
    """Return the comparison form of a caption, ignoring label/panel/continued."""
    text = _clean_text(value)
    text = _CAPTION_PREFIX_RE.sub("", text, count=1)
    text = _LEADING_PANEL_RE.sub("", text, count=1)
    text = _CONTINUED_RE.sub(" ", text)
    text = _clean_text(text).strip(" :.-")
    return text.casefold()


def caption_digest(value: Any) -> str:
    normalized = normalize_caption_text(value)
    if not normalized:
        raise FigureIndexError("caption must contain text beyond its label")
    return _sha256_bytes(normalized.encode("utf-8"))


def stable_figure_ref_key(
    paper_id: str,
    kind: Any,
    number: Any,
    *,
    caption: Any,
    page: Any,
) -> str:
    """Build the stable numbered key or explicit page+caption fallback."""
    paper = _clean_text(paper_id)
    if _PAPER_ID_RE.fullmatch(paper) is None:
        raise FigureIndexError("paper_id is not safe for a figure reference key")
    kind_token = normalize_figure_kind(kind)
    logical_number = normalize_caption_number(number)
    if logical_number:
        suffix = logical_number
    else:
        suffix = f"u-p{_positive_page(page)}-{caption_digest(caption)[:8]}"
    return f"fig:{paper}:{kind_token}:{suffix}"


def asset_sha256(data: bytes | bytearray | memoryview | Path) -> str:
    """Return the exact byte digest for a PNG byte buffer or regular file."""
    if isinstance(data, Path):
        if data.is_symlink() or not data.is_file():
            raise FigureIndexError("asset source must be a regular non-symlink file")
        return _file_sha256(data)
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise FigureIndexError("asset source must be bytes or Path")
    return _sha256_bytes(bytes(data))


def asset_relative_path(digest: Any) -> str:
    return f"figures/assets/{_require_sha256(digest, where='asset digest')}.png"


def _normalize_bbox(value: Any, *, where: str) -> list[float] | None:
    if value in (None, []):
        return None
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        raise FigureIndexError(f"{where} must contain four finite numbers")
    result: list[float] = []
    for item in value:
        if isinstance(item, bool):
            raise FigureIndexError(f"{where} must contain four finite numbers")
        try:
            number = float(item)
        except (TypeError, ValueError, OverflowError) as exc:
            raise FigureIndexError(f"{where} must contain four finite numbers") from exc
        if not math.isfinite(number):
            raise FigureIndexError(f"{where} must contain four finite numbers")
        result.append(round(number, 4))
    if result[2] <= result[0] or result[3] <= result[1]:
        raise FigureIndexError(f"{where} must have positive area")
    return result


def build_asset_binding(
    data: bytes | bytearray | memoryview | Path,
    *,
    page: Any,
    caption_bbox: Any = None,
    crop_bbox: Any = None,
    source_mode: Any = "",
) -> dict[str, Any]:
    """Create the canonical content-addressed binding for one crop occurrence."""
    digest = asset_sha256(data)
    binding: dict[str, Any] = {
        "path": asset_relative_path(digest),
        "sha256": digest,
        "page": _positive_page(page, where="asset page"),
    }
    normalized_caption_bbox = _normalize_bbox(caption_bbox, where="caption_bbox")
    normalized_crop_bbox = _normalize_bbox(crop_bbox, where="crop_bbox")
    if normalized_caption_bbox is not None:
        binding["caption_bbox"] = normalized_caption_bbox
    if normalized_crop_bbox is not None:
        binding["crop_bbox"] = normalized_crop_bbox
    mode = _clean_text(source_mode)
    if mode:
        binding["source_mode"] = mode
    return binding


def _entry_caption(kind: str, number: str, caption: Any) -> str:
    original = _clean_text(caption)
    normalized_body = normalize_caption_text(original)
    if not normalized_body:
        raise FigureIndexError("caption must contain text beyond its label")
    # Preserve the source's body casing while removing only mechanical wrappers.
    body = _CAPTION_PREFIX_RE.sub("", original, count=1)
    body = _LEADING_PANEL_RE.sub("", body, count=1)
    body = _CONTINUED_RE.sub(" ", body)
    body = _clean_text(body).strip(" :.-")
    prefix = "Figure" if kind == "fig" else "Table"
    return f"{prefix}{f' {number}' if number else ''}. {body}"


def _normalize_asset_mapping(asset: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(asset) - _ASSET_KEYS
    if unknown:
        raise FigureIndexError(f"unsupported asset binding fields: {', '.join(sorted(str(item) for item in unknown))}")
    digest = _require_sha256(asset.get("sha256"), where="asset sha256")
    expected_path = asset_relative_path(digest)
    if _clean_text(asset.get("path")) != expected_path:
        raise FigureIndexError(f"asset path must be content-addressed as {expected_path}")
    normalized: dict[str, Any] = {
        "path": expected_path,
        "sha256": digest,
        "page": _positive_page(asset.get("page"), where="asset page"),
    }
    for field in ("caption_bbox", "crop_bbox"):
        bbox = _normalize_bbox(asset.get(field), where=field)
        if bbox is not None:
            normalized[field] = bbox
    mode = _clean_text(asset.get("source_mode"))
    if mode:
        normalized["source_mode"] = mode
    return normalized


def build_figure_entry(
    paper_id: str,
    *,
    kind: Any,
    number: Any,
    caption: Any,
    page: Any,
    assets: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build one normalized logical entry without making an importance judgement."""
    kind_token = normalize_figure_kind(kind)
    logical_number = normalize_caption_number(number)
    entry_page = _positive_page(page)
    canonical_caption = _entry_caption(kind_token, logical_number, caption)
    normalized_assets = [_normalize_asset_mapping(asset) for asset in assets]
    if not normalized_assets:
        raise FigureIndexError("figure entry must bind at least one crop asset")
    normalized_assets.sort(key=_canonical_json)
    pages = sorted({entry_page, *(asset["page"] for asset in normalized_assets)})
    return {
        "ref_key": stable_figure_ref_key(
            paper_id,
            kind_token,
            logical_number,
            caption=canonical_caption,
            page=entry_page,
        ),
        "kind": "figure" if kind_token == "fig" else "table",
        "number": logical_number,
        "caption": canonical_caption,
        "caption_digest": caption_digest(canonical_caption),
        "page": pages[0],
        "pages": pages,
        "assets": normalized_assets,
    }


def merge_logical_entries(left: Mapping[str, Any], right: Mapping[str, Any]) -> dict[str, Any]:
    """Merge repeated/panel/continued crops, rejecting an ambiguous same-key caption."""
    left_key = _clean_text(left.get("ref_key"))
    right_key = _clean_text(right.get("ref_key"))
    if not left_key or left_key != right_key:
        raise FigureIndexError("only entries with the same ref_key can be merged")
    for field in ("kind", "number", "caption_digest"):
        if _clean_text(left.get(field)) != _clean_text(right.get(field)):
            raise FigureIndexError(f"conflicting {field} for {left_key}")
    if caption_digest(left.get("caption")) != caption_digest(right.get("caption")):
        raise FigureIndexError(f"conflicting caption for {left_key}")

    assets_by_identity: dict[str, dict[str, Any]] = {}
    for raw_asset in [*list(left.get("assets") or []), *list(right.get("assets") or [])]:
        if not isinstance(raw_asset, Mapping):
            raise FigureIndexError(f"invalid asset binding for {left_key}")
        asset = _normalize_asset_mapping(raw_asset)
        identity = _canonical_json(asset)
        assets_by_identity[identity] = asset
    assets = [assets_by_identity[key] for key in sorted(assets_by_identity)]
    if not assets:
        raise FigureIndexError(f"missing asset binding for {left_key}")
    pages = sorted(
        {
            *[_positive_page(item, where="entry page") for item in list(left.get("pages") or [])],
            *[_positive_page(item, where="entry page") for item in list(right.get("pages") or [])],
            *[asset["page"] for asset in assets],
        }
    )
    if not pages:
        raise FigureIndexError(f"missing page for {left_key}")
    captions = sorted({_clean_text(left.get("caption")), _clean_text(right.get("caption"))})
    caption = min((item for item in captions if item), key=lambda item: (len(item), item.casefold()))
    return {
        "ref_key": left_key,
        "kind": _clean_text(left.get("kind")),
        "number": _clean_text(left.get("number")),
        "caption": caption,
        "caption_digest": _clean_text(left.get("caption_digest")),
        "page": pages[0],
        "pages": pages,
        "assets": assets,
    }


def _canonical_entry(entry: Mapping[str, Any]) -> dict[str, Any]:
    unknown = set(entry) - _ENTRY_KEYS
    if unknown:
        raise FigureIndexError(f"unsupported figure entry fields: {', '.join(sorted(str(item) for item in unknown))}")
    raw_assets = entry.get("assets")
    if not isinstance(raw_assets, list) or any(not isinstance(asset, Mapping) for asset in raw_assets):
        raise FigureIndexError("figure entry assets must be a list of mappings")
    assets = [_normalize_asset_mapping(asset) for asset in raw_assets]
    assets.sort(key=_canonical_json)
    raw_pages = entry.get("pages")
    if not isinstance(raw_pages, list):
        raise FigureIndexError("figure entry pages must be a list")
    pages = sorted({_positive_page(item, where="entry page") for item in raw_pages})
    return {
        "ref_key": _clean_text(entry.get("ref_key")),
        "kind": _clean_text(entry.get("kind")),
        "number": _clean_text(entry.get("number")),
        "caption": _clean_text(entry.get("caption")),
        "caption_digest": _clean_text(entry.get("caption_digest")),
        "page": _positive_page(entry.get("page"), where="entry page"),
        "pages": pages,
        "assets": assets,
    }


def _canonical_index_payload(index: Mapping[str, Any]) -> dict[str, Any]:
    source = index.get("source") if isinstance(index.get("source"), Mapping) else {}
    extraction = index.get("extraction") if isinstance(index.get("extraction"), Mapping) else {}
    raw_entries = index.get("entries")
    if not isinstance(raw_entries, list) or any(not isinstance(entry, Mapping) for entry in raw_entries):
        raise FigureIndexError("figure index entries must be a list of mappings")
    entries = [_canonical_entry(entry) for entry in raw_entries]
    entries.sort(key=lambda item: item["ref_key"])
    return {
        "schema": _clean_text(index.get("schema")),
        "paper_id": _clean_text(index.get("paper_id")),
        "source": {
            "artifact": _clean_text(source.get("artifact")),
            "sha256": _clean_text(source.get("sha256")).lower(),
        },
        "extraction": json.loads(_canonical_json(extraction)),
        "entries": entries,
    }


def canonical_figure_index_digest(index: Mapping[str, Any]) -> str:
    """Digest the semantic index independent of YAML formatting/traversal order."""
    return _sha256_bytes(_canonical_json(_canonical_index_payload(index)).encode("utf-8"))


def _safe_relative_path(value: Any, *, where: str) -> Path:
    text = _clean_text(value)
    path = Path(text)
    if (
        not text
        or path.is_absolute()
        or any(part in {"", ".", ".."} for part in path.parts)
        or ":" in path.parts[0]
    ):
        raise FigureIndexError(f"{where} must be a safe relative path")
    return path


def _resolve_bound_path(
    value: Any,
    *,
    unit_root: Path,
    project_root: Path | None,
    where: str,
) -> Path:
    relative = _safe_relative_path(value, where=where)
    if relative.parts[0] == "kb":
        if project_root is None:
            raise FigureIndexError(f"{where} is project-relative but project_root was not provided")
        base = project_root
    else:
        base = unit_root
    if base.is_symlink():
        raise FigureIndexError(f"{where} base directory must not be a symlink")
    base_resolved = base.resolve()
    candidate = base_resolved.joinpath(*relative.parts)
    try:
        candidate.relative_to(base_resolved)
    except ValueError as exc:  # defensive: _safe_relative_path already rejects '..'
        raise FigureIndexError(f"{where} escapes its allowed root") from exc
    current = base_resolved
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise FigureIndexError(f"{where} must not traverse a symlink")
    return candidate


def build_figure_index(
    paper_id: str,
    *,
    source_artifact: Any,
    source_sha256: Any,
    extraction_settings: Mapping[str, Any],
    entries: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    """Build a deterministic index, merging repeated logical entries."""
    paper = _clean_text(paper_id)
    if _PAPER_ID_RE.fullmatch(paper) is None:
        raise FigureIndexError("paper_id is not safe for a figure reference key")
    source_path = _safe_relative_path(source_artifact, where="source artifact").as_posix()
    source_digest = _require_sha256(source_sha256, where="source sha256")
    if not isinstance(extraction_settings, Mapping):
        raise FigureIndexError("extraction_settings must be a mapping")
    normalized_settings = json.loads(_canonical_json(extraction_settings))

    merged: dict[str, dict[str, Any]] = {}
    for raw_entry in entries:
        if not isinstance(raw_entry, Mapping):
            raise FigureIndexError("figure entries must be mappings")
        entry = _canonical_entry(raw_entry)
        key = entry["ref_key"]
        if not key:
            raise FigureIndexError("figure entry is missing ref_key")
        merged[key] = merge_logical_entries(merged[key], entry) if key in merged else entry
    normalized_entries = [merged[key] for key in sorted(merged)]
    index: dict[str, Any] = {
        "schema": FIGURE_INDEX_SCHEMA,
        "paper_id": paper,
        "source": {"artifact": source_path, "sha256": source_digest},
        "extraction": {"settings": normalized_settings},
        "entries": normalized_entries,
    }
    violations = validate_figure_index(index, verify_files=False, require_digest=False)
    if violations:
        raise FigureIndexError(violations)
    index["index_digest"] = canonical_figure_index_digest(index)
    return index


def validate_figure_index(
    index: Mapping[str, Any],
    *,
    unit_root: Path | None = None,
    project_root: Path | None = None,
    expected_index_digest: str = "",
    expected_source_sha256: str = "",
    verify_files: bool = True,
    require_digest: bool = True,
) -> list[str]:
    """Return all structural/currentness violations without mutating the index."""
    violations: list[str] = []
    if not isinstance(index, Mapping):
        return ["figure index must be a mapping"]
    unknown_top_level = set(index) - _INDEX_KEYS
    if unknown_top_level:
        violations.append(
            "unsupported figure index fields: "
            + ", ".join(sorted(str(item) for item in unknown_top_level))
        )
    if _clean_text(index.get("schema")) != FIGURE_INDEX_SCHEMA:
        violations.append(f"figure index schema must be {FIGURE_INDEX_SCHEMA}")
    paper_id = _clean_text(index.get("paper_id"))
    if _PAPER_ID_RE.fullmatch(paper_id) is None:
        violations.append("figure index paper_id is unsafe")
    source = index.get("source")
    if not isinstance(source, Mapping):
        violations.append("figure index source binding is missing")
        source = {}
    else:
        unknown_source = set(source) - _SOURCE_KEYS
        if unknown_source:
            violations.append(
                "unsupported source binding fields: "
                + ", ".join(sorted(str(item) for item in unknown_source))
            )
    try:
        source_artifact = _safe_relative_path(source.get("artifact"), where="source artifact").as_posix()
        if _clean_text(source.get("artifact")) != source_artifact:
            violations.append("source artifact path is not canonical")
    except FigureIndexError as exc:
        violations.extend(exc.violations)
        source_artifact = ""
    source_digest = _clean_text(source.get("sha256")).lower()
    if _SHA256_RE.fullmatch(source_digest) is None:
        violations.append("source sha256 must be a lowercase sha256")
    if expected_source_sha256 and source_digest != _clean_text(expected_source_sha256).lower():
        violations.append("source sha256 differs from the consumer binding")
    extraction = index.get("extraction")
    if not isinstance(extraction, Mapping) or not isinstance(extraction.get("settings"), Mapping):
        violations.append("figure index extraction.settings must be a mapping")
    else:
        unknown_extraction = set(extraction) - _EXTRACTION_KEYS
        if unknown_extraction:
            violations.append(
                "unsupported extraction fields: "
                + ", ".join(sorted(str(item) for item in unknown_extraction))
            )
        try:
            _canonical_json(extraction)
        except FigureIndexError as exc:
            violations.extend(exc.violations)

    entries = index.get("entries")
    if not isinstance(entries, list):
        violations.append("figure index entries must be a list")
        entries = []
    seen_refs: set[str] = set()
    previous_ref = ""
    asset_paths: list[tuple[str, str]] = []
    for position, raw_entry in enumerate(entries):
        where = f"entries[{position}]"
        if not isinstance(raw_entry, Mapping):
            violations.append(f"{where} must be a mapping")
            continue
        try:
            entry = _canonical_entry(raw_entry)
        except FigureIndexError as exc:
            violations.extend(f"{where}: {item}" for item in exc.violations)
            continue
        try:
            if _canonical_json(raw_entry) != _canonical_json(entry):
                violations.append(f"{where}: entry is not in canonical form")
        except FigureIndexError as exc:
            violations.extend(f"{where}: {item}" for item in exc.violations)
        ref_key = entry["ref_key"]
        if ref_key in seen_refs:
            violations.append(f"duplicate figure ref_key: {ref_key}")
        seen_refs.add(ref_key)
        if previous_ref and ref_key < previous_ref:
            violations.append("figure index entries are not sorted by ref_key")
        previous_ref = ref_key
        try:
            kind_token = normalize_figure_kind(entry["kind"])
            normalized_number = normalize_caption_number(entry["number"])
            if normalized_number != entry["number"]:
                violations.append(f"{where}: caption number is not canonical")
            current_caption_digest = caption_digest(entry["caption"])
            if entry["caption_digest"] != current_caption_digest:
                violations.append(f"{where}: caption digest changed")
            expected_ref = stable_figure_ref_key(
                paper_id,
                kind_token,
                normalized_number,
                caption=entry["caption"],
                page=entry["page"],
            )
            if ref_key != expected_ref:
                violations.append(f"{where}: ref_key does not match paper/kind/number/caption/page")
        except FigureIndexError as exc:
            violations.extend(f"{where}: {item}" for item in exc.violations)
        if not entry["assets"]:
            violations.append(f"{where}: no crop assets are bound")
        asset_pages = {asset["page"] for asset in entry["assets"]}
        if set(entry["pages"]) != asset_pages | {entry["page"]}:
            violations.append(f"{where}: pages do not match entry/asset pages")
        if entry["pages"] and entry["page"] != min(entry["pages"]):
            violations.append(f"{where}: page must be the first logical page")
        for asset in entry["assets"]:
            asset_paths.append((asset["path"], asset["sha256"]))

    try:
        current_digest = canonical_figure_index_digest(index)
    except FigureIndexError as exc:
        violations.extend(exc.violations)
        current_digest = ""
    stored_digest = _clean_text(index.get("index_digest")).lower()
    if require_digest and _SHA256_RE.fullmatch(stored_digest) is None:
        violations.append("figure index is missing a canonical index_digest")
    elif stored_digest and current_digest and stored_digest != current_digest:
        violations.append("figure index canonical digest changed")
    if expected_index_digest and current_digest != _clean_text(expected_index_digest).lower():
        violations.append("figure index differs from the consumer binding")

    if verify_files:
        if unit_root is None:
            violations.append("unit_root is required to verify source and asset bytes")
        else:
            if source_artifact and _SHA256_RE.fullmatch(source_digest):
                try:
                    source_path = _resolve_bound_path(
                        source_artifact,
                        unit_root=unit_root,
                        project_root=project_root,
                        where="source artifact",
                    )
                    if not source_path.is_file():
                        violations.append("source artifact is missing")
                    elif _file_sha256(source_path) != source_digest:
                        violations.append("source artifact bytes changed")
                except FigureIndexError as exc:
                    violations.extend(exc.violations)
            for asset_path, digest in asset_paths:
                try:
                    expected_path = asset_relative_path(digest)
                    if asset_path != expected_path:
                        violations.append(f"asset path is not content-addressed: {asset_path}")
                        continue
                    path = _resolve_bound_path(
                        asset_path,
                        unit_root=unit_root,
                        project_root=project_root,
                        where="figure asset",
                    )
                    if not path.is_file():
                        violations.append(f"figure asset is missing: {asset_path}")
                    elif _file_sha256(path) != digest:
                        violations.append(f"figure asset bytes changed: {asset_path}")
                except FigureIndexError as exc:
                    violations.extend(exc.violations)
    return list(dict.fromkeys(violations))


def load_current_figure_index(
    index_path: Path,
    *,
    unit_root: Path,
    project_root: Path | None = None,
    expected_index_digest: str = "",
    expected_index_byte_sha256: str = "",
    expected_source_sha256: str = "",
) -> dict[str, Any]:
    """Load a YAML index and fail closed on path, byte, or binding drift."""
    if index_path.is_symlink() or not index_path.is_file():
        raise FigureIndexError("figure index artifact must be a regular non-symlink file")
    raw_roots = [unit_root]
    if project_root is not None:
        raw_roots.append(project_root)
    for root in raw_roots:
        if root.is_symlink():
            raise FigureIndexError("figure index allowed root must not be a symlink")
    allowed_roots = [root.resolve() for root in raw_roots]
    lexical_index = index_path.absolute()
    resolved_index = index_path.resolve()
    if not any(
        resolved_index == root or root in resolved_index.parents
        for root in allowed_roots
    ):
        raise FigureIndexError("figure index artifact escapes its allowed root")
    lexical_root: Path | None = None
    for root in (root.absolute() for root in raw_roots):
        try:
            lexical_index.relative_to(root)
        except ValueError:
            continue
        lexical_root = root
        break
    if lexical_root is None:
        raise FigureIndexError("figure index artifact escapes its allowed root")
    current = lexical_root
    for part in lexical_index.relative_to(lexical_root).parts:
        current = current / part
        if current.is_symlink():
            raise FigureIndexError("figure index artifact must not traverse a symlink")
    if expected_index_byte_sha256:
        expected_bytes = _require_sha256(expected_index_byte_sha256, where="expected index byte sha256")
        if _file_sha256(index_path) != expected_bytes:
            raise FigureIndexError("figure index artifact bytes changed")
    try:
        loaded = load_yaml_mapping_bytes_strict(index_path.read_bytes())
    except (OSError, UnicodeError, RuntimeError, StrictYamlError) as exc:
        raise FigureIndexError(f"cannot read figure index artifact: {exc}") from exc
    violations = validate_figure_index(
        loaded,
        unit_root=unit_root,
        project_root=project_root,
        expected_index_digest=expected_index_digest,
        expected_source_sha256=expected_source_sha256,
    )
    if violations:
        raise FigureIndexError(violations)
    return loaded


def resolve_figure_ref(
    index: Mapping[str, Any],
    ref_key: str,
    *,
    unit_root: Path,
    project_root: Path | None = None,
    expected_index_digest: str = "",
    expected_source_sha256: str = "",
) -> dict[str, Any]:
    """Resolve one current logical ref; never fall back to traversal filenames."""
    violations = validate_figure_index(
        index,
        unit_root=unit_root,
        project_root=project_root,
        expected_index_digest=expected_index_digest,
        expected_source_sha256=expected_source_sha256,
    )
    if violations:
        raise FigureIndexError(violations)
    key = _clean_text(ref_key)
    matches = [entry for entry in list(index.get("entries") or []) if _clean_text(entry.get("ref_key")) == key]
    if len(matches) != 1:
        raise FigureIndexError(f"figure ref must resolve exactly once: {key}")
    return json.loads(_canonical_json(matches[0]))
