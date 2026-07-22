"""Deterministic Markdown reading views for archived research sources.

This module only converts and locates source material.  It never interprets a
paper, invents captions, or writes research judgements.  Raw source bytes stay
authoritative; ``document.md`` is an immutable, human/AI/Obsidian-friendly view.
"""

from __future__ import annotations

import base64
import hashlib
import importlib.metadata
import mimetypes
import os
import re
import tempfile
from html import escape
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Union
from urllib.parse import unquote, unquote_to_bytes, urljoin, urlparse

from bs4 import BeautifulSoup, Tag
from markdownify import markdownify

from .common import clean_text, ensure_dir, file_sha256, write_text_if_changed
from .yaml_io import dump_yaml, write_bytes_atomic


MATERIALIZATION_SCHEMA = "research-source-markdown/v2"
SOURCE_MAP_SCHEMA = "research-source-map/v1"
DOCUMENT_NAME = "document.md"
SOURCE_MAP_NAME = "source-map.yaml"
CONVERSION_NAME = "conversion.yaml"
ARCHIVE_NAME = "archive.html"
ASSETS_DIR_NAME = "assets"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_ASSET_TOTAL_BYTES = 50 * 1024 * 1024
MAX_ASSET_COUNT = 200

IMAGE_EXTENSIONS = {
    "image/avif": ".avif",
    "image/gif": ".gif",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/svg+xml": ".svg",
    "image/webp": ".webp",
}
SAFE_IMAGE_SUFFIXES = {".avif", ".gif", ".jpeg", ".jpg", ".png", ".svg", ".webp"}


ImageFetcher = Callable[..., tuple[Union[bytes, str], str]]


def _write_immutable_text(path: Path, text: str) -> None:
    if path.exists() or path.is_symlink():
        if path.is_symlink() or not path.is_file() or path.read_text(encoding="utf-8") != text:
            raise ValueError(f"immutable source bundle collision: {path.name}")
        return
    write_text_if_changed(path, text)


def _write_immutable_yaml(path: Path, payload: dict[str, Any]) -> None:
    _write_immutable_text(path, dump_yaml(payload))


def _package_version(name: str) -> str:
    try:
        return importlib.metadata.version(name)
    except importlib.metadata.PackageNotFoundError:
        return ""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_block_id(prefix: str, value: str, index: int, used: set[str]) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")[:64]
    base = f"source-{prefix}-{slug or index}"
    candidate = base
    suffix = 2
    while candidate in used:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used.add(candidate)
    return candidate


def _section_anchor(value: str, fallback: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")[:60]
    return slug or fallback


def _markdown_target(path: str) -> str:
    """Percent-encode a local relative Markdown target without changing slashes."""
    from urllib.parse import quote

    return quote(path, safe="/._-")


def _source_header(raw_name: str, source_type: str, source_uri: str, *, archive_name: str = "") -> str:
    label = {
        "pdf": "原始 PDF",
        "html": "原始 HTML",
        "markdown": "原始 Markdown",
        "text": "原始文本",
    }.get(source_type, "原始材料")
    lines = [
        "<!-- research-kb generated reading view; do not edit -->",
        "",
        f"[{label}]({_markdown_target(raw_name)})",
    ]
    if archive_name:
        lines.append(f"[离线阅读页]({_markdown_target(archive_name)})")
    if source_uri.lower().startswith(("http://", "https://")):
        lines.append(f"[在线原文]({source_uri})")
    lines.extend(["", "---", ""])
    return "\n".join(lines)


def _write_bundle(
    source_root: Path,
    *,
    raw_path: Path,
    source_type: str,
    source_uri: str,
    converter: str,
    converter_version: str,
    document_text: str,
    blocks: list[dict[str, Any]],
    assets: list[dict[str, Any]],
    warnings: list[str],
    archive_path: Path | None = None,
    quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    document_path = source_root / DOCUMENT_NAME
    source_map_path = source_root / SOURCE_MAP_NAME
    conversion_path = source_root / CONVERSION_NAME
    normalized = document_text.replace("\r\n", "\n").replace("\r", "\n").rstrip() + "\n"
    _write_immutable_text(document_path, normalized)
    document_hash = file_sha256(document_path)
    raw_hash = file_sha256(raw_path)
    asset_entries = sorted(assets, key=lambda item: (str(item.get("path") or ""), str(item.get("block_id") or "")))
    _write_immutable_yaml(
        source_map_path,
        {
            "schema": SOURCE_MAP_SCHEMA,
            "source_type": source_type,
            "source_file": raw_path.name,
            "document": DOCUMENT_NAME,
            "blocks": blocks,
            "assets": asset_entries,
        },
    )
    status = "degraded" if warnings else "complete"
    conversion: dict[str, Any] = {
        "schema": MATERIALIZATION_SCHEMA,
        "status": status,
        "source_type": source_type,
        "source_file": raw_path.name,
        "source_sha256": raw_hash,
        "document": DOCUMENT_NAME,
        "document_sha256": document_hash,
        "converter": converter,
        "converter_version": converter_version,
        "source_map": SOURCE_MAP_NAME,
        "assets": sorted({str(item["path"]) for item in asset_entries}),
        "warnings": warnings,
    }
    if quality:
        conversion["quality"] = quality
    archive_hash = ""
    if archive_path is not None:
        archive_hash = file_sha256(archive_path)
        conversion["archive"] = archive_path.name
        conversion["archive_sha256"] = archive_hash
    _write_immutable_yaml(
        conversion_path,
        conversion,
    )
    asset_paths = [source_root / path for path in sorted({str(item["path"]) for item in asset_entries})]
    return {
        "status": status,
        "document_path": document_path,
        "document_hash": document_hash,
        "source_map_path": source_map_path,
        "conversion_path": conversion_path,
        "asset_paths": asset_paths,
        "converter": converter,
        "converter_version": converter_version,
        "warnings": list(warnings),
        "archive_path": archive_path,
        "archive_hash": archive_hash,
        "quality": dict(quality or {}),
    }


def _asset_extension(content_type: str, source_name: str, data: bytes) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    if normalized in IMAGE_EXTENSIONS:
        return IMAGE_EXTENSIONS[normalized]
    suffix = Path(urlparse(source_name).path).suffix.lower()
    if suffix in SAFE_IMAGE_SUFFIXES:
        return ".jpg" if suffix == ".jpeg" else suffix
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return ".gif"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data[:12].startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    if b"<svg" in data[:2048].lower():
        return ".svg"
    guessed = mimetypes.guess_extension(normalized) if normalized else None
    return guessed if guessed in SAFE_IMAGE_SUFFIXES else ".bin"


def _sanitize_svg(data: bytes) -> bytes:
    text = data.decode("utf-8", errors="replace")
    soup = BeautifulSoup(text, "html.parser")
    svg = soup.find("svg")
    if svg is None:
        raise ValueError("SVG payload has no svg root")
    for unsafe in svg.find_all(["script", "foreignobject", "iframe", "object", "embed"]):
        unsafe.decompose()
    for tag in svg.find_all(True):
        for name, value in list(tag.attrs.items()):
            lowered = str(name).lower()
            rendered = " ".join(value) if isinstance(value, list) else str(value)
            if lowered.startswith("on") or (lowered in {"href", "xlink:href"} and rendered.strip().lower().startswith("javascript:")):
                del tag.attrs[name]
    return str(svg).encode("utf-8")


def _write_hashed_asset(assets_root: Path, data: bytes, content_type: str, source_name: str) -> tuple[Path, str]:
    extension = _asset_extension(content_type, source_name, data)
    if extension == ".bin":
        raise ValueError("unsupported image payload")
    if extension == ".svg":
        data = _sanitize_svg(data)
    digest = _sha256_bytes(data)
    target = assets_root / f"image-{digest[:16]}{extension}"
    ensure_dir(assets_root)
    if target.exists():
        if target.is_symlink() or not target.is_file() or file_sha256(target) != digest:
            raise ValueError(f"asset path collision: {target.name}")
    else:
        write_bytes_atomic(target, data)
    return target, digest


def _data_image(source: str) -> tuple[bytes, str] | None:
    match = re.match(r"^data:([^;,]+)?(;base64)?,(.*)$", source, flags=re.IGNORECASE | re.DOTALL)
    if not match:
        return None
    content_type = str(match.group(1) or "application/octet-stream").lower()
    payload = match.group(3)
    data = base64.b64decode(payload, validate=True) if match.group(2) else unquote_to_bytes(payload)
    return data, content_type


def _srcset_choice(value: str) -> str:
    candidates = [part.strip().split()[0] for part in str(value or "").split(",") if part.strip()]
    return candidates[-1] if candidates else ""


def _safe_local_image(base_root: Path, source: str) -> tuple[bytes, str] | None:
    parsed = urlparse(source)
    if parsed.scheme not in {"", "file"} or parsed.netloc or source.startswith("~"):
        return None
    from urllib.parse import unquote

    root = base_root.resolve()
    if parsed.scheme == "file":
        candidate = Path(unquote(parsed.path))
        if not candidate.is_absolute():
            return None
    else:
        if source.startswith("/"):
            return None
        lexical = PurePosixPath(unquote(parsed.path))
        if not lexical.parts or any(part in {"", ".", ".."} for part in lexical.parts):
            return None
        candidate = root.joinpath(*lexical.parts)
    if candidate.is_symlink() or not candidate.is_file():
        return None
    resolved = candidate.resolve()
    try:
        resolved.relative_to(root)
    except ValueError:
        return None
    if resolved.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("local image exceeds size limit")
    return resolved.read_bytes(), mimetypes.guess_type(resolved.name)[0] or ""


def inspect_html_quality(html: str, *, require_full_text: bool = False) -> dict[str, Any]:
    """Return deterministic source-integrity signals without interpreting content."""
    soup = BeautifulSoup(html, "html.parser")
    title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    root = soup.select_one("article.ltx_document") or soup.find("article") or soup.find("main") or soup.body
    text = clean_text(root.get_text(" ", strip=True)) if isinstance(root, Tag) else ""
    lowered = html.lower()
    fatal_markers = [
        marker
        for marker in (
            "conversion to html had a fatal error",
            "ar5iv-severity-fatal",
            "ltx_page_error",
        )
        if marker in lowered
    ]
    error_count = len(soup.select(".ltx_ERROR, .ltx_error"))
    heading_count = len(root.find_all(re.compile(r"^h[1-6]$"))) if isinstance(root, Tag) else 0
    paragraph_count = len(root.find_all("p")) if isinstance(root, Tag) else 0
    rejection_reasons: list[str] = []
    warnings: list[str] = []
    if fatal_markers:
        rejection_reasons.append("HTML source declares a fatal conversion error")
    if title.strip().lower() in {"untitled document", "untitled"}:
        rejection_reasons.append("HTML source has an untitled conversion placeholder")
    if not isinstance(root, Tag):
        rejection_reasons.append("HTML source has no article/main/body root")
    if require_full_text and len(text) < 300:
        rejection_reasons.append(f"HTML full-text body is too small ({len(text)} characters)")
    if require_full_text and heading_count == 0 and paragraph_count < 3:
        rejection_reasons.append("HTML full-text body has no section structure")
    if error_count:
        warnings.append(f"HTML source contains {error_count} LaTeXML error marker(s)")
    return {
        "accepted": not rejection_reasons,
        "title": title,
        "text_characters": len(text),
        "heading_count": heading_count,
        "paragraph_count": paragraph_count,
        "latexml_error_count": error_count,
        "fatal_markers": fatal_markers,
        "rejection_reasons": rejection_reasons,
        "warnings": warnings,
    }


def _document_base_url(soup: BeautifulSoup, resolved_url: str) -> str:
    base = soup.find("base", href=True)
    href = str(base.get("href") or "").strip() if isinstance(base, Tag) else ""
    return urljoin(resolved_url, href) if href else resolved_url


def _safe_image_alt(value: Any, fallback: str = "Source image") -> str:
    text = clean_text(str(value or ""))
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1].strip()
    text = text.replace("[", "(").replace("]", ")")
    return text or fallback


def _sanitize_passive_html(root: Tag) -> None:
    """Make a derived reading DOM passive without changing the raw source."""
    for unsafe in list(root.find_all(["iframe", "object", "embed"])):
        unsafe.decompose()
    for source in list(root.find_all("source")):
        if source.find_parent("picture") is not None:
            source.decompose()
    for tag in [root, *root.find_all(True)]:
        for name, value in list(tag.attrs.items()):
            lowered = str(name).lower()
            rendered = " ".join(value) if isinstance(value, list) else str(value)
            normalized = re.sub(r"[\x00-\x20\x7f]+", "", rendered).lower()
            if (
                lowered.startswith("on")
                or lowered in {"srcdoc", "ping", "style", "action", "formaction"}
                or (
                    lowered in {"href", "src", "xlink:href"}
                    and normalized.startswith(("javascript:", "vbscript:", "data:text/html"))
                )
            ):
                del tag.attrs[name]
        if tag.name == "a" and str(tag.get("href") or "").lower().startswith(("http://", "https://")):
            tag["rel"] = "noopener noreferrer"


_FENCE_OPEN_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})(.*)$")


def _markdown_line_state(text: str) -> tuple[list[str], list[bool], bool, int]:
    """Return lines, fenced-line mask, unclosed state, and fence block count."""
    lines = text.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    protected = [False] * len(lines)
    marker_char = ""
    marker_size = 0
    fence_count = 0
    for index, line in enumerate(lines):
        match = _FENCE_OPEN_RE.match(line)
        if not marker_char:
            if match:
                marker = match.group(1)
                marker_char = marker[0]
                marker_size = len(marker)
                fence_count += 1
                protected[index] = True
            continue
        protected[index] = True
        stripped = line.lstrip(" ")
        closing = re.match(rf"{re.escape(marker_char)}{{{marker_size},}}[ \t]*$", stripped)
        if closing:
            marker_char = ""
            marker_size = 0
    return lines, protected, bool(marker_char), fence_count


def _transform_outside_inline_code(line: str, transform: Callable[[str], str]) -> str:
    output: list[str] = []
    cursor = 0
    while cursor < len(line):
        opening = line.find("`", cursor)
        if opening < 0:
            output.append(transform(line[cursor:]))
            break
        run_end = opening
        while run_end < len(line) and line[run_end] == "`":
            run_end += 1
        marker = line[opening:run_end]
        closing = line.find(marker, run_end)
        if closing < 0:
            output.append(transform(line[cursor:opening]))
            output.append(line[opening:])
            break
        output.append(transform(line[cursor:opening]))
        output.append(line[opening : closing + len(marker)])
        cursor = closing + len(marker)
    return "".join(output)


def _replace_markdown_inline_images(
    text: str,
    replace: Callable[[str, str, str], str],
) -> str:
    """Rewrite inline image nodes while preserving fenced and inline code verbatim."""

    def replace_segment(segment: str) -> str:
        output: list[str] = []
        cursor = 0
        while cursor < len(segment):
            start = segment.find("![", cursor)
            if start < 0:
                output.append(segment[cursor:])
                break
            slash_count = 0
            probe = start - 1
            while probe >= 0 and segment[probe] == "\\":
                slash_count += 1
                probe -= 1
            if slash_count % 2:
                output.append(segment[cursor : start + 2])
                cursor = start + 2
                continue
            depth = 1
            closing_alt = start + 2
            while closing_alt < len(segment) and depth:
                char = segment[closing_alt]
                if char == "\\":
                    closing_alt += 2
                    continue
                if char == "[":
                    depth += 1
                elif char == "]":
                    depth -= 1
                closing_alt += 1
            if depth or closing_alt >= len(segment) or segment[closing_alt] != "(":
                output.append(segment[cursor : start + 2])
                cursor = start + 2
                continue
            closing_alt -= 1
            target_start = closing_alt + 2
            position = target_start
            paren_depth = 1
            quote = ""
            angle = False
            while position < len(segment):
                char = segment[position]
                if char == "\\":
                    position += 2
                    continue
                if angle:
                    angle = char != ">"
                elif quote:
                    if char == quote:
                        quote = ""
                elif char == "<":
                    angle = True
                elif char in {'"', "'"}:
                    quote = char
                elif char == "(":
                    paren_depth += 1
                elif char == ")":
                    paren_depth -= 1
                    if not paren_depth:
                        break
                position += 1
            if paren_depth:
                output.append(segment[cursor : start + 2])
                cursor = start + 2
                continue
            output.append(segment[cursor:start])
            alt = segment[start + 2 : closing_alt]
            raw_target = segment[target_start:position]
            original = segment[start : position + 1]
            output.append(replace(alt, raw_target, original))
            cursor = position + 1
        return "".join(output)

    return _transform_markdown_noncode_blocks(text, replace_segment)


def _transform_markdown_noncode_blocks(text: str, transform: Callable[[str], str]) -> str:
    """Transform non-fenced Markdown blocks while masking inline code spans."""
    lines, protected, _unclosed, _count = _markdown_line_state(text)
    output: list[str] = []
    index = 0
    mask_index = 0
    while index < len(lines):
        if protected[index]:
            output.append(lines[index])
            index += 1
            continue
        end = index
        while end < len(lines) and not protected[end]:
            end += 1
        masks: dict[str, str] = {}
        original_block = "\n".join(lines[index:end])
        cursor = 0
        rendered: list[str] = []
        while cursor < len(original_block):
            opening = original_block.find("`", cursor)
            if opening < 0:
                rendered.append(original_block[cursor:])
                break
            run_end = opening
            while run_end < len(original_block) and original_block[run_end] == "`":
                run_end += 1
            marker = original_block[opening:run_end]
            closing = original_block.find(marker, run_end)
            if closing < 0:
                rendered.append(original_block[cursor:])
                break
            rendered.append(original_block[cursor:opening])
            mask_index += 1
            original = original_block[opening : closing + len(marker)]
            nonce = hashlib.sha256(
                f"{mask_index}:{original}:{text}".encode("utf-8")
            ).hexdigest()[:12].upper()
            token = f"KBINLINEMASK{mask_index:06d}{nonce}Z"
            while token in text or token in masks:
                token += "X"
            masks[token] = original
            rendered.append(token)
            cursor = closing + len(marker)
        block = transform("".join(rendered))
        for token, original in masks.items():
            block = block.replace(token, original)
        output.extend(block.split("\n"))
        index = end
    return "\n".join(output) + ("\n" if text.endswith(("\n", "\r")) else "")


def _sanitize_markdown_raw_html(text: str) -> str:
    """Passivate raw HTML in Markdown while leaving code spans untouched."""
    unsafe = r"script|style|noscript|template|iframe|object|embed"
    paired = re.compile(
        rf"(?is)<(?P<tag>{unsafe})\b[^>]*>.*?</(?P=tag)\s*>",
    )
    standalone_unsafe = re.compile(rf"(?is)</?(?:{unsafe})\b[^>]*>")
    opening_tag = re.compile(r"(?is)<(?!/|!|\?)([a-z][a-z0-9:-]*)\b([^<>]*)>")

    def sanitize_opening(match: re.Match[str]) -> str:
        raw = match.group(0)
        fragment = BeautifulSoup(raw, "html.parser").find(True)
        if not isinstance(fragment, Tag):
            return ""
        _sanitize_passive_html(fragment)
        if fragment.parent is None:
            return ""
        serialized = str(fragment)
        end = serialized.find(">")
        return serialized[: end + 1] if end >= 0 else ""

    def sanitize_block(block: str) -> str:
        block = paired.sub("", block)
        block = standalone_unsafe.sub("", block)
        return opening_tag.sub(sanitize_opening, block)

    return _transform_markdown_noncode_blocks(text, sanitize_block)


def _markdown_heading_positions(text: str) -> list[tuple[int, str]]:
    lines, protected, _unclosed, _count = _markdown_line_state(text)
    positions: list[tuple[int, str]] = []
    index = 0
    while index < len(lines):
        if protected[index]:
            index += 1
            continue
        atx = re.match(r"^ {0,3}#{1,6}[ \t]+(.+?)[ \t]*#*[ \t]*$", lines[index])
        if atx:
            positions.append((index, clean_text(atx.group(1))))
            index += 1
            continue
        if (
            lines[index].strip()
            and index + 1 < len(lines)
            and not protected[index + 1]
            and re.match(r"^ {0,3}(?:=+|-+)[ \t]*$", lines[index + 1])
        ):
            positions.append((index + 1, clean_text(lines[index].strip())))
            index += 2
            continue
        index += 1
    return positions


def _extract_source_frontmatter(text: str) -> tuple[str, str]:
    normalized = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = normalized.splitlines()
    if not lines or lines[0].strip() != "---":
        return "", normalized
    for index in range(1, min(len(lines), 500)):
        if lines[index].strip() in {"---", "..."}:
            frontmatter = "\n".join(lines[1:index]).rstrip()
            body = "\n".join(lines[index + 1 :]).lstrip("\n")
            return frontmatter, body
    return "", normalized


def _frontmatter_reading_block(frontmatter: str) -> str:
    if not frontmatter:
        return ""
    rendered = escape(frontmatter, quote=False)
    return (
        '<details class="kb-source-frontmatter">\n'
        "<summary>Source front matter</summary>\n"
        f'<pre><code class="language-yaml">{rendered}</code></pre>\n'
        "</details>\n\n"
    )


def _split_markdown_image_target(raw_target: str) -> tuple[str, str]:
    rendered = raw_target.strip()
    if rendered.startswith("<"):
        closing = rendered.find(">")
        if closing > 0:
            return rendered[1:closing], rendered[closing + 1 :]
    match = re.match(r"(\S+)(.*)$", rendered, flags=re.DOTALL)
    if not match:
        return rendered, ""
    return match.group(1), match.group(2)


def _math_latex(math: Tag) -> str:
    latex = str(math.get("alttext") or math.get("aria-label") or "").strip()
    if not latex:
        annotation = math.find("annotation", attrs={"encoding": re.compile(r"tex", re.IGNORECASE)})
        latex = annotation.get_text("", strip=True) if isinstance(annotation, Tag) else ""
    if latex.startswith(r"\(") and latex.endswith(r"\)"):
        latex = latex[2:-2].strip()
    elif latex.startswith(r"\[") and latex.endswith(r"\]"):
        latex = latex[2:-2].strip()
    return latex


def _standalone_archive(title: str, root: Tag, source_uri: str) -> str:
    safe_title = escape(title or "Archived source")
    safe_source = escape(source_uri, quote=True)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src 'self' data:; style-src 'unsafe-inline'; frame-src 'none'; form-action 'none'; base-uri 'none'">
<title>{safe_title}</title>
<style>
:root {{ color-scheme: light dark; font-family: ui-serif, Georgia, Cambria, "Times New Roman", serif; }}
body {{ margin: 0; background: Canvas; color: CanvasText; line-height: 1.62; }}
main {{ box-sizing: border-box; max-width: 980px; margin: 0 auto; padding: 3rem 2rem 6rem; }}
h1,h2,h3,h4,h5,h6 {{ line-height: 1.25; scroll-margin-top: 1rem; }}
a {{ color: LinkText; }}
img,svg {{ max-width: 100%; height: auto; }}
figure {{ margin: 2rem 0; padding: 1rem; border: 1px solid color-mix(in srgb, CanvasText 20%, transparent); border-radius: .5rem; overflow-x: auto; }}
figcaption {{ margin-top: .75rem; font-size: .95rem; opacity: .82; }}
table {{ display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; }}
th,td {{ padding: .45rem .65rem; border: 1px solid color-mix(in srgb, CanvasText 22%, transparent); vertical-align: top; }}
pre {{ padding: 1rem; overflow-x: auto; background: color-mix(in srgb, CanvasText 7%, Canvas); border-radius: .4rem; }}
math[display="block"], .ltx_display, .ltx_equation {{ overflow-x: auto; }}
.ltx_figure_panel, .ltx_tabular {{ max-width: 100%; overflow-x: auto; }}
.kb-source {{ margin-bottom: 2rem; font-family: ui-sans-serif, system-ui, sans-serif; font-size: .85rem; }}
</style>
</head>
<body>
<main>
<p class="kb-source">Offline reading view · <a href="{safe_source}">online source</a></p>
{str(root)}
</main>
</body>
</html>
"""


def _gallery_html(figure: Tag) -> str:
    classes = [str(item) for item in figure.get("class") or []]
    if "kb-source-gallery" not in classes:
        classes.append("kb-source-gallery")
    figure["class"] = classes
    return (
        '<div class="kb-source-gallery-wrap" style="max-width:100%;overflow-x:auto">\n'
        + str(figure)
        + "\n</div>"
    )


def _unique_placeholder(prefix: str, index: int, root: Tag, used: set[str]) -> str:
    corpus = str(root)
    nonce = hashlib.sha256(f"{prefix}:{index}:{corpus}".encode("utf-8")).hexdigest()[:12].upper()
    token = f"KB{prefix}TOKEN{index:06d}{nonce}Z"
    suffix = 2
    while token in corpus or token in used:
        token = f"KB{prefix}TOKEN{index:06d}{nonce}{suffix}Z"
        suffix += 1
    used.add(token)
    return token


def _numbered_equation_markdown(table: Tag) -> str:
    math = table.find("math")
    if not isinstance(math, Tag):
        return ""
    latex = _math_latex(math)
    if not latex:
        return ""
    tag_node = table.select_one(".ltx_tag_equation, .ltx_tag")
    tag = clean_text(tag_node.get_text(" ", strip=True)) if isinstance(tag_node, Tag) else ""
    match = re.fullmatch(r"\(([^()]+)\)", tag)
    if match and r"\tag{" not in latex:
        safe_tag = re.sub(r"[^0-9A-Za-z._:-]+", "", match.group(1))
        if safe_tag:
            latex = f"{latex} \\tag{{{safe_tag}}}"
    return f"\n\n$$\n{latex}\n$$\n\n"


def _code_block_markdown(pre: Tag) -> str:
    code = pre.find("code")
    source = code if isinstance(code, Tag) else pre
    body = source.get_text("", strip=False).replace("\r\n", "\n").replace("\r", "\n")
    classes = [str(item) for item in source.get("class") or []]
    language = ""
    for item in classes:
        match = re.match(r"(?:language|lang)-([A-Za-z0-9_+.-]+)$", item)
        if match:
            language = match.group(1)
            break
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", body)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"\n\n{fence}{language}\n{body.rstrip()}\n{fence}\n\n"


def _is_complex_html_table(table: Tag) -> bool:
    if table.find("table") is not None:
        return True
    for cell in table.find_all(["th", "td"]):
        for attribute in ("rowspan", "colspan"):
            try:
                if int(str(cell.get(attribute) or "1")) > 1:
                    return True
            except ValueError:
                return True
    return False


def _complex_table_html(table: Tag) -> str:
    return (
        '\n\n<div class="kb-source-table" style="max-width:100%;overflow-x:auto">\n'
        + str(table)
        + "\n</div>\n\n"
    )


def _markdown_format_quality(markdown: str, source_root: Path) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    lines, protected, unclosed_fence, fence_count = _markdown_line_state(markdown)
    visible_parts: list[str] = []
    fenced_block_ids = 0
    for index, line in enumerate(lines):
        if protected[index]:
            if re.match(r"^\^source-[a-z0-9-]+\s*$", line.strip()):
                fenced_block_ids += 1
            continue
        visible_parts.append(_transform_outside_inline_code(line, lambda value: value))
    visible = "\n".join(visible_parts)
    if re.search(r"!\[\[", visible):
        warnings.append("Markdown contains an Obsidian wikilink/image syntax collision")
    if re.search(r"KB(?:MATH|ANCHOR|FIGURE|EQUATION|TABLE|CODE)TOKEN[0-9A-F]+Z", visible):
        warnings.append("Markdown contains an unrestored conversion placeholder")
    if re.search(r"\]\(#(?!\^)[^)]+\)", visible):
        warnings.append("Markdown contains an unresolved internal fragment link")
    if unclosed_fence:
        warnings.append("Markdown contains an unclosed fenced code block")
    if fenced_block_ids:
        warnings.append("Markdown contains generated source block IDs inside fenced code")

    image_count = 0
    local_asset_refs: set[str] = set()

    def collect_image(_alt: str, raw_target: str, original: str) -> str:
        nonlocal image_count
        image_count += 1
        target, _suffix = _split_markdown_image_target(raw_target)
        if target.startswith(f"{ASSETS_DIR_NAME}/"):
            local_asset_refs.add(target)
        return original

    _replace_markdown_inline_images(markdown, collect_image)
    for match in re.finditer(r"<img\b[^>]*>", visible, flags=re.IGNORECASE):
        image_count += 1
        fragment = BeautifulSoup(match.group(0), "html.parser").find("img")
        if isinstance(fragment, Tag):
            source = str(fragment.get("src") or "").strip()
            if source.startswith(f"{ASSETS_DIR_NAME}/"):
                local_asset_refs.add(source)
    reference_uses = {
        " ".join((match.group(2) or match.group(1)).split()).casefold()
        for match in re.finditer(r"!\[([^\]\n]+)\]\[([^\]\n]*)\]", visible)
    }
    reference_definitions = {
        " ".join(match.group(1).split()).casefold(): _split_markdown_image_target(match.group(2))[0]
        for match in re.finditer(
            r"(?m)^ {0,3}\[([^\]\n]+)\]:[ \t]*(<[^>\n]+>|\S+)(?:[^\n]*)$", visible
        )
    }
    local_asset_refs.update(
        target
        for target in reference_definitions.values()
        if target.startswith(f"{ASSETS_DIR_NAME}/")
    )
    for relative in sorted(local_asset_refs):
        if not (source_root / relative).is_file():
            warnings.append(f"Markdown references a missing local asset: {relative}")
    unresolved_references = [
        label
        for label in sorted(reference_uses)
        if not str(reference_definitions.get(label) or "").startswith(f"{ASSETS_DIR_NAME}/")
    ]
    if unresolved_references:
        warnings.append("Markdown contains an unmaterialized reference-style image")

    display_math_count = len(re.findall(r"(?<!\\)\$\$", visible))
    if display_math_count % 2:
        warnings.append("Markdown contains unbalanced display-math delimiters")

    pipe_table_count = 0
    malformed_pipe_table_count = 0
    index = 0
    while index < len(lines):
        if protected[index] or not (lines[index].strip().startswith("|") and lines[index].strip().endswith("|")):
            index += 1
            continue
        start = index
        run: list[str] = []
        while (
            index < len(lines)
            and not protected[index]
            and lines[index].strip().startswith("|")
            and lines[index].strip().endswith("|")
        ):
            run.append(lines[index].strip())
            index += 1
        if len(run) < 2:
            continue
        separator_cells = re.split(r"(?<!\\)\|", run[1].strip("|"))
        if not separator_cells or not all(re.match(r"^\s*:?-{3,}:?\s*$", cell) for cell in separator_cells):
            continue
        pipe_table_count += 1
        expected = len(re.split(r"(?<!\\)\|", run[0].strip("|")))
        if any(len(re.split(r"(?<!\\)\|", row.strip("|"))) != expected for row in run[1:]):
            malformed_pipe_table_count += 1
    if malformed_pipe_table_count:
        warnings.append(f"Markdown contains {malformed_pipe_table_count} malformed pipe table(s)")

    metrics = {
        "document_characters": len(markdown),
        "heading_count": len(_markdown_heading_positions(markdown)),
        "fenced_code_block_count": fence_count,
        "unclosed_fence": unclosed_fence,
        "pipe_table_count": pipe_table_count,
        "raw_html_table_count": len(re.findall(r"<table\b", visible, flags=re.IGNORECASE)),
        "malformed_pipe_table_count": malformed_pipe_table_count,
        "image_count": image_count,
        "local_asset_reference_count": len(local_asset_refs),
        "display_math_delimiter_count": display_math_count,
    }
    return metrics, list(dict.fromkeys(warnings))


def _html_heading_specs(root: Tag) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    used: set[str] = set()
    for index, heading in enumerate(root.find_all(re.compile(r"^h[1-6]$")), start=1):
        title = clean_text(heading.get_text(" ", strip=True))
        anchor = str(heading.get("id") or title or index)
        specs.append(
            {
                "block_id": _safe_block_id("section", anchor, index, used),
                "anchor": str(heading.get("id") or ""),
                "heading": title,
            }
        )
    return specs


def _inject_heading_blocks(markdown: str, specs: list[dict[str, str]]) -> tuple[str, list[dict[str, Any]]]:
    lines = markdown.replace("\r\n", "\n").replace("\r", "\n").splitlines()
    output: list[str] = ["^source-document", ""]
    blocks: list[dict[str, Any]] = [
        {"block_id": "source-document", "locator_kind": "section", "anchor": "document", "heading": ""}
    ]
    heading_positions = {position for position, _heading in _markdown_heading_positions(markdown)}
    spec_index = 0
    for line_index, line in enumerate(lines):
        output.append(line.rstrip())
        if spec_index >= len(specs) or line_index not in heading_positions:
            continue
        spec = specs[spec_index]
        spec_index += 1
        output.extend(["", f"^{spec['block_id']}", ""])
        blocks.append(
            {
                "block_id": spec["block_id"],
                "locator_kind": "section",
                "anchor": spec["anchor"],
                "heading": spec["heading"],
            }
        )
    text = "\n".join(output)
    text = re.sub(r"\n{4,}", "\n\n\n", text).strip()
    return text, blocks


def materialize_html(
    source_root: Path,
    raw_path: Path,
    html: str,
    *,
    source_uri: str,
    resolved_url: str,
    fetch_image: ImageFetcher | None,
    local_asset_root: Path | None = None,
    initial_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create normalized Markdown plus an offline HTML reading view."""
    soup = BeautifulSoup(html, "html.parser")
    title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    quality = dict(initial_quality or inspect_html_quality(html))
    rejection_reasons = [str(item) for item in quality.get("rejection_reasons", []) if str(item)]
    if not quality.get("accepted", not rejection_reasons) or rejection_reasons:
        raise ValueError("HTML source failed quality gate: " + "; ".join(rejection_reasons or ["rejected"]))
    document_base = _document_base_url(soup, resolved_url)
    for script in list(soup.find_all("script")):
        script_type = str(script.get("type") or "").strip().lower()
        if script_type.startswith("math/tex"):
            math = soup.new_tag("math")
            math["alttext"] = script.get_text("", strip=True)
            math["display"] = "block" if "mode=display" in script_type else "inline"
            script.replace_with(math)
        else:
            script.decompose()
    for node in soup.find_all(["style", "noscript", "template"]):
        node.decompose()
    root = soup.select_one("article.ltx_document") or soup.find("article") or soup.find("main") or soup.body or soup
    assert isinstance(root, Tag)
    warnings = [str(item) for item in quality.get("warnings", []) if str(item)]
    for error_node in root.select(".ltx_ERROR, .ltx_error"):
        error_node.decompose()
    assets: list[dict[str, Any]] = []
    assets_root = source_root / ASSETS_DIR_NAME
    total_asset_bytes = 0
    asset_sources: dict[str, dict[str, Any]] = {}

    def persist_asset(data: bytes, content_type: str, source: str, *, kind: str = "image") -> str:
        nonlocal total_asset_bytes
        if len(assets) >= MAX_ASSET_COUNT:
            raise ValueError("asset count limit reached")
        if len(data) > MAX_IMAGE_BYTES or total_asset_bytes + len(data) > MAX_ASSET_TOTAL_BYTES:
            raise ValueError("asset byte limit reached")
        target, digest = _write_hashed_asset(assets_root, data, content_type, source)
        relative = f"{ASSETS_DIR_NAME}/{target.name}"
        total_asset_bytes += 0 if relative in asset_sources else len(data)
        if relative not in asset_sources:
            entry = {
                "path": relative,
                "sha256": digest,
                "kind": kind,
                "source": source,
                "locator_kind": "section",
            }
            asset_sources[relative] = entry
            assets.append(entry)
        return relative

    for index, svg in enumerate(list(root.find_all("svg")), start=1):
        try:
            relative = persist_asset(str(svg).encode("utf-8"), "image/svg+xml", f"inline-svg-{index}", kind="inline-svg")
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"inline SVG {index} was not localized: {exc}")
            continue
        replacement = soup.new_tag("img")
        replacement["src"] = relative
        replacement["alt"] = _safe_image_alt(
            svg.get("aria-label") or svg.get("title"), f"Inline SVG {index}"
        )
        replacement["data-kb-localized"] = "1"
        svg.replace_with(replacement)

    for index, image in enumerate(root.find_all("img"), start=1):
        if str(image.get("data-kb-localized") or "") == "1":
            image.attrs.pop("data-kb-localized", None)
            continue
        source = str(image.get("data-src") or image.get("data-original") or image.get("src") or _srcset_choice(str(image.get("srcset") or ""))).strip()
        if not source:
            warnings.append(f"image {index} has no source")
            continue
        figcaption = image.find_parent("figure")
        caption_node = figcaption.find("figcaption") if figcaption else None
        if not str(image.get("alt") or "").strip() and caption_node:
            image["alt"] = clean_text(caption_node.get_text(" ", strip=True))
        image["alt"] = _safe_image_alt(image.get("alt"), f"Source image {index}")
        try:
            loaded: tuple[bytes, str] | None = _data_image(source)
            absolute_source = source
            if loaded is None and local_asset_root is not None:
                loaded = _safe_local_image(local_asset_root, source)
            if loaded is None:
                resolved_source = urljoin(document_base, source)
                if local_asset_root is not None:
                    loaded = _safe_local_image(local_asset_root, resolved_source)
                if loaded is not None:
                    absolute_source = source
                else:
                    absolute_source = resolved_source
            if loaded is None:
                if fetch_image is None or not absolute_source.lower().startswith(("http://", "https://")):
                    raise ValueError("image is not locally reachable")
                payload, content_type = fetch_image(absolute_source, binary=True, max_bytes=MAX_IMAGE_BYTES)
                data = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
                loaded = (data, content_type)
            data, content_type = loaded
            relative = persist_asset(data, content_type, absolute_source)
            image["src"] = relative
            for attribute in ("srcset", "data-src", "data-original", "loading"):
                image.attrs.pop(attribute, None)
        except Exception as exc:  # noqa: BLE001
            absolute_source = urljoin(document_base, source) if document_base else source
            if absolute_source.lower().startswith(("http://", "https://")):
                image["src"] = absolute_source
            warnings.append(f"image {index} was not localized: {exc}")

    for link in root.find_all("a"):
        href = str(link.get("href") or "").strip()
        if href and not href.startswith(("#", "mailto:", "tel:")):
            link["href"] = urljoin(document_base, href)

    _sanitize_passive_html(root)

    archive_path = source_root / ARCHIVE_NAME
    _write_immutable_text(archive_path, _standalone_archive(title, root, source_uri))

    heading_specs = _html_heading_specs(root)
    anchor_to_block = {
        str(spec["anchor"]): str(spec["block_id"])
        for spec in heading_specs
        if str(spec.get("anchor") or "")
    }
    used_blocks = {str(spec["block_id"]) for spec in heading_specs}
    used_placeholders: set[str] = set()
    extra_blocks: list[dict[str, Any]] = []
    anchor_tokens: dict[str, str] = {}
    referenced_anchors = {
        unquote(str(link.get("href") or "")[1:])
        for link in root.find_all("a")
        if str(link.get("href") or "").startswith("#") and len(str(link.get("href") or "")) > 1
    }
    for index, anchor in enumerate(sorted(referenced_anchors), start=1):
        block_id = anchor_to_block.get(anchor, "")
        if not block_id:
            target = root.find(attrs={"id": anchor})
            if not isinstance(target, Tag):
                warnings.append(f"internal fragment has no target: #{anchor}")
                continue
            block_id = _safe_block_id("anchor", anchor, index, used_blocks)
            anchor_to_block[anchor] = block_id
            token = _unique_placeholder("ANCHOR", index, root, used_placeholders)
            marker = soup.new_tag("p")
            marker.string = token
            target.insert_after(marker)
            anchor_tokens[token] = f"\n\n^{block_id}\n\n"
            extra_blocks.append(
                {
                    "block_id": block_id,
                    "locator_kind": "section",
                    "anchor": anchor,
                    "heading": "",
                }
            )
    for link in root.find_all("a"):
        href = str(link.get("href") or "")
        decoded_anchor = unquote(href[1:]) if href.startswith("#") else ""
        if decoded_anchor in anchor_to_block:
            link["href"] = f"#^{anchor_to_block[decoded_anchor]}"

    heading_tags = list(root.find_all(re.compile(r"^h[1-6]$")))
    for image in root.find_all("img"):
        relative = str(image.get("src") or "")
        entry = asset_sources.get(relative)
        if entry is None:
            continue
        preceding = image.find_previous(re.compile(r"^h[1-6]$"))
        if preceding in heading_tags:
            spec = heading_specs[heading_tags.index(preceding)]
            entry["block_id"] = spec["block_id"]
            entry["anchor"] = spec["anchor"] or _section_anchor(spec["heading"], "document")
        else:
            entry["block_id"] = "source-document"
            entry["anchor"] = "document"

    code_tokens: dict[str, str] = {}
    for index, pre in enumerate(list(root.find_all("pre")), start=1):
        token = _unique_placeholder("CODE", index, root, used_placeholders)
        code_tokens[token] = _code_block_markdown(pre)
        pre.replace_with(token)

    equation_tokens: dict[str, str] = {}
    for index, equation in enumerate(
        list(root.select("table.ltx_equation, table.ltx_eqn_table")), start=1
    ):
        rendered = _numbered_equation_markdown(equation)
        if not rendered:
            warnings.append(f"equation table {index} has no TeX representation; preserved as HTML")
            continue
        token = _unique_placeholder("EQUATION", index, root, used_placeholders)
        equation_tokens[token] = rendered
        equation.replace_with(token)

    table_tokens: dict[str, str] = {}
    for index, table in enumerate(list(root.find_all("table")), start=1):
        if not _is_complex_html_table(table):
            continue
        token = _unique_placeholder("TABLE", index, root, used_placeholders)
        table_tokens[token] = _complex_table_html(table)
        table.replace_with(token)

    figure_tokens: dict[str, str] = {}
    for index, figure in enumerate(list(root.find_all("figure")), start=1):
        if figure.find_parent("figure") is not None or len(figure.find_all("img")) <= 1:
            continue
        token = _unique_placeholder("FIGURE", index, root, used_placeholders)
        figure_tokens[token] = "\n\n" + _gallery_html(figure) + "\n\n"
        figure.replace_with(token)

    math_tokens: dict[str, str] = {}
    for index, math in enumerate(list(root.find_all("math")), start=1):
        latex = _math_latex(math)
        if not latex:
            token = _unique_placeholder("MATH", index, root, used_placeholders)
            math_tokens[token] = str(math)
            warnings.append(f"math node {index} has no TeX representation; preserved as MathML")
            math.replace_with(token)
            continue
        token = _unique_placeholder("MATH", index, root, used_placeholders)
        display = str(math.get("display") or "").lower() == "block" or "ltx_display" in " ".join(math.get("class") or [])
        math_tokens[token] = f"\n\n$$\n{latex}\n$$\n\n" if display else f"${latex}$"
        math.replace_with(token)

    converted = markdownify(
        str(root),
        heading_style="ATX",
        bullets="-",
        strip=["script", "style", "noscript", "template"],
    )
    converted, blocks = _inject_heading_blocks(converted, heading_specs)
    for token, replacement in {
        **code_tokens,
        **math_tokens,
        **equation_tokens,
        **table_tokens,
        **figure_tokens,
        **anchor_tokens,
    }.items():
        converted = converted.replace(token, replacement)
    converted = re.sub(r"\n{3,}", "\n\n", converted).strip()
    blocks.extend(extra_blocks)
    if title and not re.search(r"(?m)^#\s+", converted):
        converted = f"# {title}\n\n{converted}"
    format_quality, format_warnings = _markdown_format_quality(converted, source_root)
    warnings.extend(format_warnings)
    warnings = list(dict.fromkeys(warnings))
    output_quality = {
        **format_quality,
        "markdown_characters": len(converted),
        "block_count": len(blocks),
        "asset_count": len(assets),
        "internal_fragment_count": len(referenced_anchors),
        "math_count": len(math_tokens) + len(equation_tokens),
        "code_block_count": len(code_tokens),
        "equation_count": len(equation_tokens),
        "complex_table_count": len(table_tokens),
        "multi_image_figure_count": len(figure_tokens),
    }
    quality["output"] = output_quality
    document = _source_header(raw_path.name, "html", source_uri, archive_name=ARCHIVE_NAME) + converted
    return _write_bundle(
        source_root,
        raw_path=raw_path,
        source_type="html",
        source_uri=source_uri,
        converter="markdownify",
        converter_version=_package_version("markdownify"),
        document_text=document,
        blocks=blocks,
        assets=assets,
        warnings=warnings,
        archive_path=archive_path,
        quality=quality,
    )


_IMAGE_LINK_RE = re.compile(r"(!\[[^\]]*\]\()([^\n)]+)(\))")


def _rewrite_pdf_image_links(
    text: str,
    mapping: dict[str, tuple[str, str]],
    page_number: int,
    unavailable: set[str],
) -> tuple[str, list[str]]:
    referenced: list[str] = []

    def replace(match: re.Match[str]) -> str:
        raw_target = match.group(2).strip()
        target = raw_target.split(" ", 1)[0].strip("<>")
        name = Path(target).name
        if name not in mapping:
            if name in unavailable:
                return "*PDF image could not be archived; see the original PDF.*"
            return match.group(0)
        relative, _digest = mapping[name]
        referenced.append(relative)
        prefix = match.group(1)
        if prefix == "![](":
            prefix = f"![PDF page {page_number} image]("
        return f"{prefix}{relative}{match.group(3)}"

    return _IMAGE_LINK_RE.sub(replace, text), referenced


def _text_token_coverage(reference: str, candidate: str) -> float:
    reference_tokens = {
        token.lower()
        for token in re.findall(r"[^\W_]{2,}", reference, flags=re.UNICODE)
    }
    if not reference_tokens:
        return 1.0
    candidate_tokens = {
        token.lower()
        for token in re.findall(r"[^\W_]{2,}", candidate, flags=re.UNICODE)
    }
    return len(reference_tokens & candidate_tokens) / len(reference_tokens)


def materialize_pdf(source_root: Path, raw_path: Path, *, source_uri: str) -> dict[str, Any]:
    """Create full page-separated Markdown and hash-addressed local PDF images."""
    import fitz  # type: ignore
    import pymupdf4llm  # type: ignore

    warnings: list[str] = []
    assets: list[dict[str, Any]] = []
    blocks: list[dict[str, Any]] = []
    assets_root = source_root / ASSETS_DIR_NAME
    with tempfile.TemporaryDirectory(prefix="kb-pdf-assets-") as temporary:
        temporary_assets = Path(temporary)
        with fitz.open(str(raw_path)) as document:
            native_page_text = {
                index: page.get_text("text")
                for index, page in enumerate(document, start=1)
            }
            page_data = pymupdf4llm.to_markdown(
                document,
                page_chunks=True,
                show_progress=False,
                write_images=True,
                image_path=str(temporary_assets),
            )
        mapping: dict[str, tuple[str, str]] = {}
        extracted_files = [path for path in sorted(temporary_assets.iterdir()) if path.is_file() and not path.is_symlink()]
        total_asset_bytes = 0
        unavailable: set[str] = set()
        for extracted in extracted_files:
            if not extracted.is_file() or extracted.is_symlink():
                continue
            try:
                size = extracted.stat().st_size
                if len(mapping) >= MAX_ASSET_COUNT:
                    raise ValueError("asset count limit reached")
                if size > MAX_IMAGE_BYTES or total_asset_bytes + size > MAX_ASSET_TOTAL_BYTES:
                    raise ValueError("asset byte limit reached")
                target, digest = _write_hashed_asset(
                    assets_root,
                    extracted.read_bytes(),
                    mimetypes.guess_type(extracted.name)[0] or "",
                    extracted.name,
                )
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"PDF image {extracted.name} was not archived: {exc}")
                unavailable.add(extracted.name)
                continue
            mapping[extracted.name] = (f"{ASSETS_DIR_NAME}/{target.name}", digest)
            total_asset_bytes += size

        pages: list[str] = []
        asset_seen: set[tuple[str, int]] = set()
        native_recovery_pages: list[int] = []
        entries_by_page: dict[int, dict[str, Any]] = {}
        for index, entry in enumerate(page_data if isinstance(page_data, list) else [], start=1):
            if not isinstance(entry, dict):
                continue
            metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
            page_number = metadata.get("page_number") or metadata.get("page") or index
            try:
                page_number = int(page_number)
            except (TypeError, ValueError):
                page_number = index
            entries_by_page.setdefault(page_number, entry)
        for page_number, native_text in native_page_text.items():
            if page_number in entries_by_page:
                continue
            entries_by_page[page_number] = {
                "metadata": {"page_number": page_number},
                "text": native_text,
                "page_boxes": [],
            }
            native_recovery_pages.append(page_number)
            warnings.append(
                f"PDF page {page_number} was missing from converted chunks; used native PDF text recovery"
            )

        for page_number, entry in sorted(entries_by_page.items()):
            metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
            block_id = f"source-page-{page_number}"
            extracted_text = str(entry.get("text") or "")
            native_text = str(native_page_text.get(page_number) or "").strip()
            if len(clean_text(native_text)) >= 40 and _text_token_coverage(native_text, extracted_text) < 0.7:
                image_lines = [
                    line
                    for line in extracted_text.splitlines()
                    if re.search(r"!\[[^\]]*\]\([^\n)]+\)", line)
                ]
                extracted_text = native_text + ("\n\n" + "\n".join(image_lines) if image_lines else "")
                native_recovery_pages.append(page_number)
                warnings.append(
                    f"PDF page {page_number} had low converted-text coverage; used native PDF text recovery"
                )
            page_text, referenced = _rewrite_pdf_image_links(
                extracted_text, mapping, page_number, unavailable
            )
            pages.extend([f"## Page {page_number}", "", f"^{block_id}", "", page_text.strip(), ""])
            blocks.append({"block_id": block_id, "locator_kind": "page", "page": page_number})
            picture_boxes = [
                item.get("bbox")
                for item in entry.get("page_boxes", [])
                if isinstance(item, dict) and str(item.get("class") or "") == "picture" and item.get("bbox")
            ]
            for asset_index, relative in enumerate(referenced):
                key = (relative, page_number)
                if key in asset_seen:
                    continue
                asset_seen.add(key)
                digest = next((value[1] for value in mapping.values() if value[0] == relative), "")
                asset_entry: dict[str, Any] = {
                    "path": relative,
                    "sha256": digest,
                    "kind": "pdf-image",
                    "locator_kind": "page",
                    "page": page_number,
                }
                if asset_index < len(picture_boxes):
                    asset_entry["bbox"] = [round(float(value), 2) for value in picture_boxes[asset_index]]
                assets.append(asset_entry)

        referenced_paths = {str(item["path"]) for item in assets}
        unplaced = sorted(
            (relative, digest)
            for relative, digest in mapping.values()
            if relative not in referenced_paths
        )
        if unplaced:
            pages.extend(["## Extracted images", "", "^source-extracted-images", ""])
            blocks.append(
                {
                    "block_id": "source-extracted-images",
                    "locator_kind": "section",
                    "anchor": "extracted-images",
                    "heading": "Extracted images",
                }
            )
            for relative, digest in unplaced:
                pages.extend([f"![Extracted PDF image]({relative})", ""])
                assets.append(
                    {
                        "path": relative,
                        "sha256": digest,
                        "kind": "pdf-image",
                        "locator_kind": "section",
                        "block_id": "source-extracted-images",
                    }
                )
            warnings.append("Some PDF images could not be associated with a source page and were appended separately.")

    if not blocks:
        warnings.append("PDF converter returned no page chunks")
    body = "\n".join(pages).strip()
    format_quality, format_warnings = _markdown_format_quality(body, source_root)
    warnings.extend(format_warnings)
    warnings = list(dict.fromkeys(warnings))
    format_quality["native_text_recovery_pages"] = sorted(set(native_recovery_pages))
    document = _source_header(raw_path.name, "pdf", source_uri) + body
    result = _write_bundle(
        source_root,
        raw_path=raw_path,
        source_type="pdf",
        source_uri=source_uri,
        converter="pymupdf4llm",
        converter_version=_package_version("pymupdf4llm"),
        document_text=document,
        blocks=blocks,
        assets=assets,
        warnings=warnings,
        quality={"output": format_quality},
    )
    result["page_data"] = page_data
    return result


def materialize_text(
    source_root: Path,
    raw_path: Path,
    text: str,
    *,
    source_uri: str,
    markdown: bool,
    fetch_image: ImageFetcher | None = None,
    local_asset_root: Path | None = None,
) -> dict[str, Any]:
    """Create a complete reading view for Markdown or UTF-8 plain text."""
    source_type = "markdown" if markdown else "text"
    assets: list[dict[str, Any]] = []
    warnings: list[str] = []
    if markdown:
        frontmatter, text = _extract_source_frontmatter(text)
        assets_root = source_root / ASSETS_DIR_NAME
        total_asset_bytes = 0
        asset_paths: set[str] = set()

        def archive_image(target_text: str) -> str:
            nonlocal total_asset_bytes
            loaded = _data_image(target_text)
            absolute_source = target_text
            if loaded is None and local_asset_root is not None:
                loaded = _safe_local_image(local_asset_root, target_text)
            if loaded is None:
                absolute_source = (
                    urljoin(source_uri, target_text)
                    if source_uri.lower().startswith(("http://", "https://"))
                    else target_text
                )
                if fetch_image is None or not absolute_source.lower().startswith(("http://", "https://")):
                    raise ValueError("image is not locally reachable")
                payload, content_type = fetch_image(
                    absolute_source, binary=True, max_bytes=MAX_IMAGE_BYTES
                )
                data = payload if isinstance(payload, bytes) else str(payload).encode("utf-8")
                loaded = (data, content_type)
            data, content_type = loaded
            if len(asset_paths) >= MAX_ASSET_COUNT:
                raise ValueError("asset count limit reached")
            if len(data) > MAX_IMAGE_BYTES or total_asset_bytes + len(data) > MAX_ASSET_TOTAL_BYTES:
                raise ValueError("asset byte limit reached")
            asset, digest = _write_hashed_asset(assets_root, data, content_type, absolute_source)
            relative = f"{ASSETS_DIR_NAME}/{asset.name}"
            if relative not in asset_paths:
                asset_paths.add(relative)
                total_asset_bytes += len(data)
                assets.append(
                    {
                        "path": relative,
                        "sha256": digest,
                        "kind": "image",
                        "source": absolute_source,
                        "locator_kind": "section",
                        "block_id": "source-document",
                        "anchor": "document",
                    }
                )
            return relative

        def localize_markdown_image(alt: str, raw_target: str, original: str) -> str:
            target_text, title_suffix = _split_markdown_image_target(raw_target)
            try:
                relative = archive_image(target_text)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Markdown image {target_text} was not localized: {exc}")
                return original
            return f"![{alt}]({relative}{title_suffix})"

        text = _replace_markdown_inline_images(text, localize_markdown_image)

        def localize_wikilink_images(block: str) -> str:
            pattern = re.compile(r"!\[\[([^\]|#\n]+)(?:\|([^\]\n]+))?\]\]")

            def replace_wikilink(match: re.Match[str]) -> str:
                target_text = match.group(1).strip()
                suffix = Path(urlparse(target_text).path).suffix.lower()
                if suffix not in SAFE_IMAGE_SUFFIXES:
                    return match.group(0)
                try:
                    relative = archive_image(target_text)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Markdown image {target_text} was not localized: {exc}")
                    return match.group(0)
                alias = str(match.group(2) or "").strip()
                dimensions = re.fullmatch(r"(\d{1,5})(?:x(\d{1,5}))?", alias)
                if dimensions:
                    width = int(dimensions.group(1))
                    height = int(dimensions.group(2)) if dimensions.group(2) else 0
                    if width > 0 and (not dimensions.group(2) or height > 0):
                        height_attribute = f' height="{height}"' if height else ""
                        alt = escape(_safe_image_alt(Path(target_text).stem), quote=True)
                        return (
                            f'<img src="{relative}" alt="{alt}" width="{width}"'
                            f"{height_attribute}>"
                        )
                alt = _safe_image_alt(alias or Path(target_text).stem)
                return f"![{alt}]({relative})"

            return pattern.sub(replace_wikilink, block)

        text = _transform_markdown_noncode_blocks(text, localize_wikilink_images)

        reference_labels: set[str] = set()

        def collect_reference_images(block: str) -> str:
            for match in re.finditer(r"!\[([^\]\n]+)\]\[([^\]\n]*)\]", block):
                label = match.group(2) or match.group(1)
                reference_labels.add(" ".join(label.split()).casefold())
            return block

        _transform_markdown_noncode_blocks(text, collect_reference_images)

        def localize_reference_definitions(block: str) -> str:
            definition = re.compile(
                r"(?m)^( {0,3}\[([^\]\n]+)\]:[ \t]*)(<[^>\n]+>|\S+)([^\n]*)$"
            )

            def replace_definition(match: re.Match[str]) -> str:
                label = " ".join(match.group(2).split()).casefold()
                if label not in reference_labels:
                    return match.group(0)
                target_text, _suffix = _split_markdown_image_target(match.group(3))
                try:
                    relative = archive_image(target_text)
                except Exception as exc:  # noqa: BLE001
                    warnings.append(f"Markdown image {target_text} was not localized: {exc}")
                    return match.group(0)
                return f"{match.group(1)}{relative}{match.group(4)}"

            return definition.sub(replace_definition, block)

        text = _transform_markdown_noncode_blocks(text, localize_reference_definitions)

        def localize_raw_image_tag(rendered: str) -> str:
            fragment = BeautifulSoup(rendered, "html.parser").find("img")
            if not isinstance(fragment, Tag):
                return rendered
            source = str(
                fragment.get("data-src")
                or fragment.get("data-original")
                or fragment.get("src")
                or _srcset_choice(str(fragment.get("srcset") or ""))
            ).strip()
            _sanitize_passive_html(fragment)
            if not source:
                warnings.append("Markdown raw HTML image has no source")
                return str(fragment)
            try:
                fragment["src"] = (
                    source if source in asset_paths else archive_image(source)
                )
                fragment["alt"] = _safe_image_alt(fragment.get("alt"))
                for attribute in ("srcset", "data-src", "data-original", "loading"):
                    fragment.attrs.pop(attribute, None)
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Markdown raw HTML image {source} was not localized: {exc}")
            return str(fragment)

        text = _transform_markdown_noncode_blocks(
            text,
            lambda block: re.sub(
                r"<img\b[^>]*>",
                lambda match: localize_raw_image_tag(match.group(0)),
                block,
                flags=re.IGNORECASE,
            ),
        )
        text = _sanitize_markdown_raw_html(text)
        specs: list[dict[str, str]] = []
        used: set[str] = set()
        used_anchors: set[str] = set()
        for index, (_position, heading) in enumerate(_markdown_heading_positions(text), start=1):
            base_anchor = _section_anchor(heading, f"s{index}")
            anchor = base_anchor
            suffix = 2
            while anchor in used_anchors:
                anchor = f"{base_anchor}-{suffix}"
                suffix += 1
            used_anchors.add(anchor)
            specs.append(
                {
                    "block_id": _safe_block_id("section", heading, index, used),
                    "anchor": anchor,
                    "heading": heading,
                }
            )
        anchor_to_block: dict[str, str] = {}
        for spec in specs:
            for value in (
                str(spec["anchor"]),
                str(spec["heading"]),
                _section_anchor(str(spec["heading"]), str(spec["anchor"])),
            ):
                anchor_to_block[value.casefold()] = str(spec["block_id"])

        def rewrite_heading_links(block: str) -> str:
            pattern = re.compile(r"(?<!!)\[([^\]\n]+)\]\(#([^\s)]+)([^)]*)\)")

            def replace_link(match: re.Match[str]) -> str:
                fragment = unquote(match.group(2)).casefold()
                block_id = anchor_to_block.get(fragment)
                if not block_id:
                    return match.group(0)
                return f"[{match.group(1)}](#^{block_id}{match.group(3)})"

            return pattern.sub(replace_link, block)

        text = _transform_markdown_noncode_blocks(text, rewrite_heading_links)
        body_text, blocks = _inject_heading_blocks(text, specs)
        body = _frontmatter_reading_block(frontmatter) + body_text
    else:
        blocks = [{"block_id": "source-document", "locator_kind": "section", "anchor": "document", "heading": ""}]
        rendered = escape(text, quote=False)
        body = (
            '^source-document\n\n<pre class="kb-source-plain-text" '
            'style="white-space:pre-wrap;overflow-wrap:anywhere">'
            f"{rendered}</pre>"
        )
    if markdown:
        format_quality, format_warnings = _markdown_format_quality(body, source_root)
    else:
        # Markdown-like characters inside the escaped <pre> are literal source
        # text, not headings, images, math, tables, or fences to lint.
        format_quality = {
            "document_characters": len(body),
            "heading_count": 0,
            "fenced_code_block_count": 0,
            "unclosed_fence": False,
            "pipe_table_count": 0,
            "raw_html_table_count": 0,
            "malformed_pipe_table_count": 0,
            "image_count": 0,
            "local_asset_reference_count": 0,
            "display_math_delimiter_count": 0,
        }
        format_warnings = []
    warnings.extend(format_warnings)
    warnings = list(dict.fromkeys(warnings))
    document = _source_header(raw_path.name, source_type, source_uri) + body
    return _write_bundle(
        source_root,
        raw_path=raw_path,
        source_type=source_type,
        source_uri=source_uri,
        converter="identity" if markdown else "plain-text",
        converter_version="1",
        document_text=document,
        blocks=blocks,
        assets=assets,
        warnings=warnings,
        quality={"output": format_quality},
    )


def materialize_fallback(
    source_root: Path,
    raw_path: Path,
    *,
    source_type: str,
    source_uri: str,
    error: Exception,
) -> dict[str, Any]:
    """Persist a safe raw-source reading stub when deterministic conversion fails."""
    warning_text = clean_text(str(error))[:500] or error.__class__.__name__
    warnings = [f"{source_type} conversion failed ({error.__class__.__name__}): {warning_text}"]
    assets: list[dict[str, Any]] = []
    assets_root = source_root / ASSETS_DIR_NAME
    if assets_root.is_dir() and not assets_root.is_symlink():
        for path in sorted(assets_root.iterdir()):
            if path.is_file() and not path.is_symlink():
                assets.append(
                    {
                        "path": f"{ASSETS_DIR_NAME}/{path.name}",
                        "sha256": file_sha256(path),
                        "kind": "unplaced-image",
                        "locator_kind": "section",
                        "block_id": "source-document",
                    }
                )
    body = "\n".join(
        [
            "^source-document",
            "",
            "# Markdown conversion unavailable",
            "",
            "The original source was preserved and remains the authoritative fallback.",
        ]
    )
    return _write_bundle(
        source_root,
        raw_path=raw_path,
        source_type=source_type,
        source_uri=source_uri,
        converter="fallback",
        converter_version="1",
        document_text=_source_header(raw_path.name, source_type, source_uri) + body,
        blocks=[
            {"block_id": "source-document", "locator_kind": "section", "anchor": "document", "heading": ""}
        ],
        assets=assets,
        warnings=warnings,
    )


def _rebase_materialization_result(
    result: dict[str, Any], staged_root: Path, source_root: Path
) -> dict[str, Any]:
    """Point staged result paths at their committed immutable destinations."""
    rebased = dict(result)
    for key in ("document_path", "source_map_path", "conversion_path", "archive_path"):
        value = rebased.get(key)
        if isinstance(value, Path):
            rebased[key] = source_root / value.relative_to(staged_root)
    rebased["asset_paths"] = [
        source_root / Path(value).relative_to(staged_root)
        for value in rebased.get("asset_paths", [])
    ]
    return rebased


def _bundle_target(source_root: Path, relative: Path) -> Path:
    """Resolve a derived relative path without allowing a symlinked parent."""
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"immutable source bundle collision: {relative.as_posix()}")
    current = source_root
    for part in relative.parts[:-1]:
        current = current / part
        if current.exists() or current.is_symlink():
            if current.is_symlink() or not current.is_dir():
                raise ValueError(
                    f"immutable source bundle collision: {relative.as_posix()}"
                )
    return source_root / relative


def _publish_immutable_bytes(target: Path, data: bytes, *, relative: Path) -> bool:
    """Create an immutable file without replacing a concurrent destination."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.parent.is_symlink() or not target.parent.is_dir():
        raise ValueError(f"immutable source bundle collision: {relative.as_posix()}")
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".publish",
            delete=False,
        ) as handle:
            temporary = Path(handle.name)
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target, follow_symlinks=False)
            return True
        except FileExistsError:
            if (
                target.is_symlink()
                or not target.is_file()
                or target.read_bytes() != data
            ):
                raise ValueError(
                    f"immutable source bundle collision: {relative.as_posix()}"
                )
            return False
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def _materialize_transactionally(
    source_root: Path,
    raw_path: Path,
    factory: Callable[[Path, Path], dict[str, Any]],
) -> dict[str, Any]:
    """Build a derived source bundle off-tree, then publish it as one unit.

    All immutable-collision checks happen before the first destination write.
    If an I/O error occurs while publishing, only files created by this attempt
    are removed; raw source bytes and pre-existing immutable files are untouched.
    ``conversion.yaml`` is installed last and acts as the bundle commit marker.
    """
    if source_root.is_symlink() or raw_path.is_symlink():
        raise ValueError("immutable source bundle collision: symlinked source root or raw source")
    source_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=f".{source_root.name}-materialize-", dir=source_root.parent
    ) as temporary:
        staged_root = Path(temporary)
        staged_raw = staged_root / raw_path.name
        write_bytes_atomic(staged_raw, raw_path.read_bytes())
        result = factory(staged_root, staged_raw)

        staged_files = [
            path
            for path in sorted(staged_root.rglob("*"))
            if path.is_file() and not path.is_symlink() and path != staged_raw
        ]
        publish: list[tuple[Path, Path]] = []
        for staged in staged_files:
            relative = staged.relative_to(staged_root)
            target = _bundle_target(source_root, relative)
            if target.exists() or target.is_symlink():
                if (
                    target.is_symlink()
                    or not target.is_file()
                    or target.read_bytes() != staged.read_bytes()
                ):
                    raise ValueError(f"immutable source bundle collision: {relative.as_posix()}")
                continue
            publish.append((staged, target))

        publish.sort(
            key=lambda item: (
                item[1].name == CONVERSION_NAME,
                item[1].as_posix(),
            )
        )
        created: list[Path] = []
        try:
            for staged, target in publish:
                relative = target.relative_to(source_root)
                target = _bundle_target(source_root, relative)
                if target.exists() or target.is_symlink():
                    if (
                        target.is_symlink()
                        or not target.is_file()
                        or target.read_bytes() != staged.read_bytes()
                    ):
                        raise ValueError(
                            f"immutable source bundle collision: {target.relative_to(source_root).as_posix()}"
                        )
                    continue
                if _publish_immutable_bytes(
                    target, staged.read_bytes(), relative=relative
                ):
                    created.append(target)
        except Exception:
            for target in reversed(created):
                if target.exists() and not target.is_symlink():
                    target.unlink()
            assets_root = source_root / ASSETS_DIR_NAME
            if assets_root.is_dir() and not assets_root.is_symlink() and not any(assets_root.iterdir()):
                assets_root.rmdir()
            raise
        return _rebase_materialization_result(result, staged_root, source_root)


# Keep converters individually testable while making every public materializer
# publish its document/map/conversion/archive/assets as one immutable transaction.
_materialize_html_direct = materialize_html
_materialize_pdf_direct = materialize_pdf
_materialize_text_direct = materialize_text
_materialize_fallback_direct = materialize_fallback


def materialize_html(
    source_root: Path,
    raw_path: Path,
    html: str,
    *,
    source_uri: str,
    resolved_url: str,
    fetch_image: ImageFetcher | None,
    local_asset_root: Path | None = None,
    initial_quality: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return _materialize_transactionally(
        source_root,
        raw_path,
        lambda staged_root, staged_raw: _materialize_html_direct(
            staged_root,
            staged_raw,
            html,
            source_uri=source_uri,
            resolved_url=resolved_url,
            fetch_image=fetch_image,
            local_asset_root=local_asset_root,
            initial_quality=initial_quality,
        ),
    )


def materialize_pdf(source_root: Path, raw_path: Path, *, source_uri: str) -> dict[str, Any]:
    return _materialize_transactionally(
        source_root,
        raw_path,
        lambda staged_root, staged_raw: _materialize_pdf_direct(
            staged_root, staged_raw, source_uri=source_uri
        ),
    )


def materialize_text(
    source_root: Path,
    raw_path: Path,
    text: str,
    *,
    source_uri: str,
    markdown: bool,
    fetch_image: ImageFetcher | None = None,
    local_asset_root: Path | None = None,
) -> dict[str, Any]:
    return _materialize_transactionally(
        source_root,
        raw_path,
        lambda staged_root, staged_raw: _materialize_text_direct(
            staged_root,
            staged_raw,
            text,
            source_uri=source_uri,
            markdown=markdown,
            fetch_image=fetch_image,
            local_asset_root=local_asset_root,
        ),
    )


def materialize_fallback(
    source_root: Path,
    raw_path: Path,
    *,
    source_type: str,
    source_uri: str,
    error: Exception,
) -> dict[str, Any]:
    return _materialize_transactionally(
        source_root,
        raw_path,
        lambda staged_root, staged_raw: _materialize_fallback_direct(
            staged_root,
            staged_raw,
            source_type=source_type,
            source_uri=source_uri,
            error=error,
        ),
    )


def source_fields(project_root: Path, result: dict[str, Any]) -> dict[str, Any]:
    """Project a materialization result into the additive record.source contract."""
    from .paths import rel

    materialization = {
        "schema": MATERIALIZATION_SCHEMA,
        "status": str(result["status"]),
        "converter": str(result["converter"]),
        "converter_version": str(result["converter_version"]),
        "source_map_path": rel(project_root, Path(result["source_map_path"])),
        "conversion_path": rel(project_root, Path(result["conversion_path"])),
        "asset_paths": [rel(project_root, Path(path)) for path in result.get("asset_paths", [])],
    }
    archive_path = result.get("archive_path")
    if isinstance(archive_path, Path):
        materialization["archive_path"] = rel(project_root, archive_path)
        materialization["archive_hash"] = str(result.get("archive_hash") or "")
    return {
        "markdown_path": rel(project_root, Path(result["document_path"])),
        "markdown_hash": str(result["document_hash"]),
        "materialization": materialization,
    }


def materialization_paths(result: dict[str, Any]) -> list[Path]:
    paths = [
        Path(result["document_path"]),
        Path(result["source_map_path"]),
        Path(result["conversion_path"]),
        *[Path(path) for path in result.get("asset_paths", [])],
    ]
    if isinstance(result.get("archive_path"), Path):
        paths.append(Path(result["archive_path"]))
    return list(dict.fromkeys(paths))


__all__ = [
    "ARCHIVE_NAME",
    "ASSETS_DIR_NAME",
    "CONVERSION_NAME",
    "DOCUMENT_NAME",
    "MATERIALIZATION_SCHEMA",
    "SOURCE_MAP_NAME",
    "inspect_html_quality",
    "materialization_paths",
    "materialize_fallback",
    "materialize_html",
    "materialize_pdf",
    "materialize_text",
    "source_fields",
]
