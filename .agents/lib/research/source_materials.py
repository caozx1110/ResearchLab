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
import re
import tempfile
from html import escape
from pathlib import Path, PurePosixPath
from typing import Any, Callable
from urllib.parse import unquote_to_bytes, urljoin, urlparse

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


ImageFetcher = Callable[..., tuple[bytes | str, str]]


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
    if parsed.scheme or parsed.netloc or source.startswith(("/", "~")):
        return None
    from urllib.parse import unquote

    lexical = PurePosixPath(unquote(parsed.path))
    if not lexical.parts or any(part in {"", ".", ".."} for part in lexical.parts):
        return None
    root = base_root.resolve()
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
    images = figure.find_all("img")
    rendered: list[str] = []
    for image in images:
        source = escape(str(image.get("src") or ""), quote=True)
        alt = escape(_safe_image_alt(image.get("alt")), quote=True)
        rendered.append(f'<img src="{source}" alt="{alt}" style="max-width:100%;height:auto">')
    caption_node = figure.find("figcaption")
    caption = clean_text(caption_node.get_text(" ", strip=True)) if isinstance(caption_node, Tag) else ""
    caption_html = f"<figcaption>{escape(caption)}</figcaption>" if caption else ""
    return (
        '<figure class="kb-source-gallery"><div style="display:grid;grid-template-columns:'
        'repeat(auto-fit,minmax(220px,1fr));gap:.75rem;align-items:start">'
        + "".join(rendered)
        + f"</div>{caption_html}</figure>"
    )


def _markdown_quality_warnings(markdown: str, source_root: Path) -> list[str]:
    warnings: list[str] = []
    if re.search(r"!\[\[", markdown):
        warnings.append("Markdown contains an Obsidian wikilink/image syntax collision")
    if re.search(r"KB(?:MATH|ANCHOR|FIGURE)TOKEN\d+Z", markdown):
        warnings.append("Markdown contains an unrestored conversion placeholder")
    if re.search(r"\]\(#(?!\^)[^)]+\)", markdown):
        warnings.append("Markdown contains an unresolved internal fragment link")
    for match in re.finditer(r"!\[[^\]]*\]\((assets/[^\s)]+)", markdown):
        if not (source_root / match.group(1)).is_file():
            warnings.append(f"Markdown references a missing local asset: {match.group(1)}")
    if len(re.findall(r"(?<!\\)\$\$", markdown)) % 2:
        warnings.append("Markdown contains unbalanced display-math delimiters")
    return list(dict.fromkeys(warnings))


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
    spec_index = 0
    for line in lines:
        output.append(line.rstrip())
        if spec_index >= len(specs) or not re.match(r"^#{1,6}\s+\S", line):
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
    for node in soup.find_all(["script", "style", "noscript", "template"]):
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
                absolute_source = urljoin(document_base, source)
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

    archive_path = source_root / ARCHIVE_NAME
    _write_immutable_text(archive_path, _standalone_archive(title, root, source_uri))

    heading_specs = _html_heading_specs(root)
    anchor_to_block = {
        str(spec["anchor"]): str(spec["block_id"])
        for spec in heading_specs
        if str(spec.get("anchor") or "")
    }
    used_blocks = {str(spec["block_id"]) for spec in heading_specs}
    extra_blocks: list[dict[str, Any]] = []
    anchor_tokens: dict[str, str] = {}
    referenced_anchors = {
        str(link.get("href") or "")[1:]
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
            token = f"KBANCHORTOKEN{index:06d}Z"
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
        if href.startswith("#") and href[1:] in anchor_to_block:
            link["href"] = f"#^{anchor_to_block[href[1:]]}"

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

    figure_tokens: dict[str, str] = {}
    for index, figure in enumerate(list(root.find_all("figure")), start=1):
        if len(figure.find_all("img")) <= 1:
            continue
        token = f"KBFIGURETOKEN{index:06d}Z"
        figure_tokens[token] = "\n\n" + _gallery_html(figure) + "\n\n"
        figure.replace_with(token)

    math_tokens: dict[str, str] = {}
    for index, math in enumerate(list(root.find_all("math")), start=1):
        latex = _math_latex(math)
        if not latex:
            warnings.append(f"math node {index} has no TeX representation; preserved as text")
            continue
        token = f"KBMATHTOKEN{index:06d}Z"
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
    for token, replacement in {**math_tokens, **figure_tokens, **anchor_tokens}.items():
        converted = converted.replace(token, replacement)
    converted = re.sub(r"\n{3,}", "\n\n", converted).strip()
    blocks.extend(extra_blocks)
    if title and not re.search(r"(?m)^#\s+", converted):
        converted = f"# {title}\n\n{converted}"
    warnings.extend(_markdown_quality_warnings(converted, source_root))
    warnings = list(dict.fromkeys(warnings))
    output_quality = {
        "markdown_characters": len(converted),
        "block_count": len(blocks),
        "asset_count": len(assets),
        "internal_fragment_count": len(referenced_anchors),
        "math_count": len(math_tokens),
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
        for index, entry in enumerate(page_data if isinstance(page_data, list) else [], start=1):
            if not isinstance(entry, dict):
                continue
            metadata = entry.get("metadata") if isinstance(entry.get("metadata"), dict) else {}
            page_number = metadata.get("page_number") or metadata.get("page") or index
            try:
                page_number = int(page_number)
            except (TypeError, ValueError):
                page_number = index
            block_id = f"source-page-{page_number}"
            page_text, referenced = _rewrite_pdf_image_links(
                str(entry.get("text") or ""), mapping, page_number, unavailable
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
    document = _source_header(raw_path.name, "pdf", source_uri) + "\n".join(pages).strip()
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
        assets_root = source_root / ASSETS_DIR_NAME
        total_asset_bytes = 0
        asset_paths: set[str] = set()

        def localize(match: re.Match[str]) -> str:
            nonlocal total_asset_bytes
            raw_target = match.group(2).strip()
            if raw_target.startswith("<") and ">" in raw_target:
                closing = raw_target.index(">")
                target_text = raw_target[1:closing]
                title_suffix = raw_target[closing + 1 :]
            else:
                parts = raw_target.split(maxsplit=1)
                target_text = parts[0]
                title_suffix = f" {parts[1]}" if len(parts) > 1 else ""
            try:
                loaded = _data_image(target_text)
                absolute_source = target_text
                if loaded is None and local_asset_root is not None:
                    loaded = _safe_local_image(local_asset_root, target_text)
                if loaded is None:
                    absolute_source = urljoin(source_uri, target_text) if source_uri.lower().startswith(("http://", "https://")) else target_text
                    if fetch_image is None or not absolute_source.lower().startswith(("http://", "https://")):
                        raise ValueError("image is not locally reachable")
                    payload, content_type = fetch_image(absolute_source, binary=True, max_bytes=MAX_IMAGE_BYTES)
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
                return f"{match.group(1)}{relative}{title_suffix}{match.group(3)}"
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"Markdown image {target_text} was not localized: {exc}")
                return match.group(0)

        text = _IMAGE_LINK_RE.sub(localize, text)
        specs: list[dict[str, str]] = []
        used: set[str] = set()
        used_anchors: set[str] = set()
        for index, match in enumerate(re.finditer(r"(?m)^#{1,6}\s+(.+?)\s*$", text), start=1):
            heading = clean_text(match.group(1).rstrip("#").strip())
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
        body, blocks = _inject_heading_blocks(text, specs)
    else:
        body = text
        blocks = [{"block_id": "source-document", "locator_kind": "section", "anchor": "document", "heading": ""}]
        body = f"^source-document\n\n{body}"
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
