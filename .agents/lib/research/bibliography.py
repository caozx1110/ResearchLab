"""Pure bibliography normalization, deduplication, and BibTeX rendering.

This module deliberately does not fetch metadata or infer bibliographic facts.
It converts the factual metadata already present in a canonical paper record into
a small, typed interchange shape and renders only a fixed field whitelist.
"""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import unquote, urlparse

from .dedup import canonicalize_url


class BibliographyError(ValueError):
    """Bibliography input is incomplete, contradictory, or unsafe to render."""


_DOI_RE = re.compile(r"10\.\d{4,9}/[-._;()/:+A-Z0-9]+", re.IGNORECASE)
_ARXIV_MODERN_RE = re.compile(r"(?<!\d)(\d{4}\.\d{4,5})(?:v\d+)?(?!\d)", re.IGNORECASE)
_ARXIV_LEGACY_RE = re.compile(
    r"(?<![A-Za-z0-9])([A-Za-z][A-Za-z0-9.-]*/\d{7})(?:v\d+)?(?!\d)",
    re.IGNORECASE,
)
_UNIT_KEY_RUN_RE = re.compile(r"[^a-z0-9_.:+-]+")
_CITATION_KEY_RE = re.compile(r"cite_[a-z0-9][a-z0-9_.:+-]*")
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

_ENTRY_TYPES = {
    "article",
    "book",
    "booklet",
    "inbook",
    "incollection",
    "inproceedings",
    "manual",
    "mastersthesis",
    "misc",
    "phdthesis",
    "proceedings",
    "techreport",
    "unpublished",
}
_SUPPLEMENT_FIELDS = {
    "address",
    "edition",
    "howpublished",
    "institution",
    "month",
    "note",
    "number",
    "organization",
    "pages",
    "primary_class",
    "publisher",
    "school",
    "series",
    "venue_field",
    "volume",
}
_VENUE_FIELDS = {"booktitle", "howpublished", "institution", "journal", "school"}
_BIBTEX_FIELDS = {
    "address",
    "archiveprefix",
    "author",
    "booktitle",
    "doi",
    "edition",
    "eprint",
    "howpublished",
    "institution",
    "journal",
    "month",
    "note",
    "number",
    "organization",
    "pages",
    "primaryclass",
    "publisher",
    "school",
    "series",
    "title",
    "url",
    "volume",
    "year",
}
_FIELD_ORDER = (
    "author",
    "title",
    "journal",
    "booktitle",
    "howpublished",
    "school",
    "institution",
    "organization",
    "publisher",
    "year",
    "month",
    "volume",
    "number",
    "pages",
    "edition",
    "series",
    "address",
    "doi",
    "eprint",
    "archiveprefix",
    "primaryclass",
    "url",
    "note",
)
_ENTRY_KEYS = {"schema", "unit_id", "citation_key", "entry_type", "fields", "identity"}
_IDENTITY_KEYS = {"doi", "arxiv_id", "source_urls"}


def _one_line_text(value: Any, *, field: str, allow_empty: bool = True) -> str:
    if value in (None, ""):
        if allow_empty:
            return ""
        raise BibliographyError(f"{field} must not be empty")
    if not isinstance(value, (str, int)) or isinstance(value, bool):
        raise BibliographyError(f"{field} must be a scalar string")
    text = unicodedata.normalize("NFC", str(value)).strip()
    if not text and not allow_empty:
        raise BibliographyError(f"{field} must not be empty")
    if "\n" in text or "\r" in text or _CONTROL_RE.search(text):
        raise BibliographyError(f"{field} must be one line and contain no control characters")
    if len(text.encode("utf-8")) > 16_384:
        raise BibliographyError(f"{field} exceeds the bibliography size limit")
    return text


def normalize_doi(value: Any) -> str:
    """Return a lower-case DOI identity without a scheme/prefix, or ``""``."""

    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFC", value).strip()
    if "\n" in text or "\r" in text or _CONTROL_RE.search(text):
        return ""
    text = unquote(text)
    text = re.sub(
        r"^(?:doi\s*:\s*|https?://(?:dx\.)?doi\.org/)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = text.split("?", 1)[0].split("#", 1)[0].strip().rstrip(".,;")
    if _DOI_RE.fullmatch(text) is None:
        return ""
    return text.lower()


def normalize_arxiv_id(value: Any) -> str:
    """Return a versionless modern or legacy arXiv work identity, or ``""``."""

    if not isinstance(value, str):
        return ""
    text = unicodedata.normalize("NFC", value).strip()
    if "\n" in text or "\r" in text or _CONTROL_RE.search(text):
        return ""
    text = unquote(text)
    modern = _ARXIV_MODERN_RE.search(text)
    if modern is not None:
        return modern.group(1)
    legacy = _ARXIV_LEGACY_RE.search(text)
    if legacy is not None:
        return legacy.group(1).lower()
    return ""


# Readable alias for call sites that do not persist the normalized value as a field.
normalize_arxiv = normalize_arxiv_id


def citation_key_for_unit_id(unit_id: Any) -> str:
    """Derive the only supported citation key from a canonical paper unit id."""

    text = _one_line_text(unit_id, field="unit_id", allow_empty=False).lower()
    sanitized = _UNIT_KEY_RUN_RE.sub("_", text).strip("_.:+-")
    if not sanitized:
        raise BibliographyError("unit_id does not contain a citation-key-safe character")
    key = f"cite_{sanitized}"
    if len(key.encode("ascii")) > 255 or _CITATION_KEY_RE.fullmatch(key) is None:
        raise BibliographyError("derived citation key is invalid or too long")
    return key


def _canonical_source_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        return ""
    text = _one_line_text(value, field="source_url")
    parsed = urlparse(text)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return ""
    if parsed.username is not None or parsed.password is not None:
        raise BibliographyError("source_url must not contain credentials")
    return canonicalize_url(text)


def _authors(value: Any) -> str:
    if value in (None, ""):
        return ""
    if not isinstance(value, list):
        raise BibliographyError("basic_info.authors must be a list")
    cleaned = [
        _one_line_text(item, field="basic_info.authors[]", allow_empty=False)
        for item in value
    ]
    return " and ".join(cleaned)


def _mapping(value: Any, *, field: str) -> Mapping[str, Any]:
    if value in (None, ""):
        return {}
    if not isinstance(value, Mapping):
        raise BibliographyError(f"{field} must be a mapping")
    return value


def bibtex_entry_from_record(record: Mapping[str, Any]) -> dict[str, Any]:
    """Build a whitelist-only BibTeX entry from one canonical paper record.

    Missing publication type uses BibTeX's neutral ``misc`` container; this is a
    serialization fallback, not a claim that the paper is a journal/conference
    publication. Provider-supplied raw BibTeX and duplicate canonical fields in
    the supplementary ``bibtex`` mapping are rejected.
    """

    if not isinstance(record, Mapping) or record.get("kind") != "paper":
        raise BibliographyError("bibliography entries require a canonical paper record")
    unit_id = _one_line_text(record.get("id"), field="record.id", allow_empty=False)
    key = citation_key_for_unit_id(unit_id)
    payload = _mapping(record.get("payload"), field="record.payload")
    basic = _mapping(payload.get("basic_info"), field="payload.basic_info")
    supplied_key = _one_line_text(basic.get("citation_key"), field="basic_info.citation_key")
    if supplied_key and supplied_key != key:
        raise BibliographyError("basic_info.citation_key does not match the canonical unit id")

    supplement = _mapping(basic.get("bibtex"), field="basic_info.bibtex")
    unknown = sorted(set(supplement) - ({"entry_type"} | _SUPPLEMENT_FIELDS))
    if unknown:
        raise BibliographyError(
            "basic_info.bibtex contains non-whitelisted or duplicate fields: "
            + ", ".join(unknown)
        )
    entry_type = (
        _one_line_text(supplement.get("entry_type"), field="bibtex.entry_type").lower()
        or "misc"
    )
    if entry_type and entry_type not in _ENTRY_TYPES:
        raise BibliographyError("bibtex.entry_type is not in the supported whitelist")

    explicit_doi = _one_line_text(basic.get("doi"), field="basic_info.doi")
    if explicit_doi and not normalize_doi(explicit_doi):
        raise BibliographyError("basic_info.doi is not a valid DOI identity")
    explicit_arxiv = _one_line_text(basic.get("arxiv_id"), field="basic_info.arxiv_id")
    if explicit_arxiv and not normalize_arxiv_id(explicit_arxiv):
        raise BibliographyError("basic_info.arxiv_id is not a valid arXiv identity")
    doi_candidates = {
        normalized
        for candidate in (
            basic.get("doi"),
            basic.get("source_url"),
            _mapping(record.get("source"), field="record.source").get("original_uri"),
        )
        if (normalized := normalize_doi(candidate))
    }
    if len(doi_candidates) > 1:
        raise BibliographyError("paper record contains conflicting DOI identities")
    doi = next(iter(doi_candidates), "")

    arxiv_candidates = {
        normalized
        for candidate in (
            basic.get("arxiv_id"),
            basic.get("source_url"),
            _mapping(record.get("source"), field="record.source").get("original_uri"),
        )
        if (normalized := normalize_arxiv_id(candidate))
    }
    if len(arxiv_candidates) > 1:
        raise BibliographyError("paper record contains conflicting arXiv identities")
    arxiv_id = next(iter(arxiv_candidates), "")

    urls: list[str] = []
    for candidate in (
        basic.get("source_url"),
        _mapping(record.get("source"), field="record.source").get("original_uri"),
    ):
        url = _canonical_source_url(candidate)
        if url and url not in urls:
            urls.append(url)

    fields: dict[str, str] = {}
    title = _one_line_text(basic.get("title") or record.get("title"), field="basic_info.title")
    author = _authors(basic.get("authors"))
    year = _one_line_text(basic.get("year"), field="basic_info.year")
    for name, value in (("author", author), ("title", title), ("year", year)):
        if value:
            fields[name] = value

    venue = _one_line_text(basic.get("venue"), field="basic_info.venue")
    venue_field = _one_line_text(supplement.get("venue_field"), field="bibtex.venue_field").lower()
    if venue_field and venue_field not in _VENUE_FIELDS:
        raise BibliographyError("bibtex.venue_field is not in the supported whitelist")
    if venue and venue_field:
        fields[venue_field] = venue

    for source_name, target_name in (
        ("address", "address"),
        ("edition", "edition"),
        ("howpublished", "howpublished"),
        ("institution", "institution"),
        ("month", "month"),
        ("note", "note"),
        ("number", "number"),
        ("organization", "organization"),
        ("pages", "pages"),
        ("publisher", "publisher"),
        ("school", "school"),
        ("series", "series"),
        ("volume", "volume"),
    ):
        value = _one_line_text(supplement.get(source_name), field=f"bibtex.{source_name}")
        if value:
            if target_name in fields and fields[target_name] != value:
                raise BibliographyError(f"bibtex.{source_name} conflicts with canonical venue")
            fields[target_name] = value
    if doi:
        fields["doi"] = doi
    if arxiv_id:
        fields["eprint"] = arxiv_id
        fields["archiveprefix"] = "arXiv"
        primary_class = _one_line_text(
            supplement.get("primary_class"), field="bibtex.primary_class"
        )
        if primary_class:
            fields["primaryclass"] = primary_class
    if urls:
        fields["url"] = urls[0]

    return {
        "schema": "bibtex-entry/v1",
        "unit_id": unit_id,
        "citation_key": key,
        "entry_type": entry_type,
        "fields": fields,
        "identity": {
            "doi": doi,
            "arxiv_id": arxiv_id,
            "source_urls": urls,
        },
    }


def _validate_entry(entry: Mapping[str, Any], *, require_type: bool) -> dict[str, Any]:
    if not isinstance(entry, Mapping):
        raise BibliographyError("bibliography entry must be a mapping")
    unknown = sorted(set(entry) - _ENTRY_KEYS)
    if unknown:
        raise BibliographyError("bibliography entry contains unknown keys: " + ", ".join(unknown))
    if entry.get("schema") != "bibtex-entry/v1":
        raise BibliographyError("bibliography entry schema must be bibtex-entry/v1")
    unit_id = _one_line_text(entry.get("unit_id"), field="entry.unit_id", allow_empty=False)
    expected_key = citation_key_for_unit_id(unit_id)
    key = _one_line_text(entry.get("citation_key"), field="entry.citation_key", allow_empty=False)
    if key != expected_key or _CITATION_KEY_RE.fullmatch(key) is None:
        raise BibliographyError("bibliography citation key is not derived from its unit id")
    entry_type = _one_line_text(entry.get("entry_type"), field="entry.entry_type").lower()
    if require_type and not entry_type:
        raise BibliographyError(f"{unit_id} has no explicit BibTeX entry type")
    if entry_type and entry_type not in _ENTRY_TYPES:
        raise BibliographyError(f"{unit_id} has an unsupported BibTeX entry type")

    raw_fields = _mapping(entry.get("fields"), field="entry.fields")
    extra_fields = sorted(set(raw_fields) - _BIBTEX_FIELDS)
    if extra_fields:
        raise BibliographyError("bibliography entry contains unknown fields: " + ", ".join(extra_fields))
    fields = {
        name: _one_line_text(value, field=f"entry.fields.{name}", allow_empty=False)
        for name, value in raw_fields.items()
    }

    raw_identity = _mapping(entry.get("identity"), field="entry.identity")
    extra_identity = sorted(set(raw_identity) - _IDENTITY_KEYS)
    if extra_identity:
        raise BibliographyError("bibliography identity contains unknown keys: " + ", ".join(extra_identity))
    doi_raw = _one_line_text(raw_identity.get("doi"), field="entry.identity.doi")
    doi = normalize_doi(doi_raw)
    if doi_raw and (not doi or doi_raw.lower() != doi):
        raise BibliographyError("bibliography identity DOI is not normalized")
    arxiv_raw = _one_line_text(raw_identity.get("arxiv_id"), field="entry.identity.arxiv_id")
    arxiv_id = normalize_arxiv_id(arxiv_raw)
    if arxiv_raw and (not arxiv_id or arxiv_raw.lower() != arxiv_id.lower()):
        raise BibliographyError("bibliography identity arXiv id is not normalized and versionless")
    raw_urls = raw_identity.get("source_urls", [])
    if raw_urls in (None, ""):
        raw_urls = []
    if not isinstance(raw_urls, list):
        raise BibliographyError("entry.identity.source_urls must be a list")
    urls: list[str] = []
    for raw_url in raw_urls:
        url = _canonical_source_url(raw_url)
        if not url:
            raise BibliographyError("entry.identity.source_urls contains a non-HTTP(S) URL")
        if raw_url != url:
            raise BibliographyError("entry.identity.source_urls must already be canonical")
        if url not in urls:
            urls.append(url)

    if fields.get("doi", "") != doi:
        raise BibliographyError("rendered DOI field does not match the strong identity")
    if fields.get("eprint", "") != arxiv_id:
        raise BibliographyError("rendered arXiv field does not match the strong identity")
    if arxiv_id and fields.get("archiveprefix") != "arXiv":
        raise BibliographyError("arXiv entries require the literal archiveprefix arXiv")
    if fields.get("url", "") and fields["url"] not in urls:
        raise BibliographyError("rendered URL field does not match a canonical source identity")

    return {
        "schema": "bibtex-entry/v1",
        "unit_id": unit_id,
        "citation_key": key,
        "entry_type": entry_type,
        "fields": fields,
        "identity": {"doi": doi, "arxiv_id": arxiv_id, "source_urls": urls},
    }


def strong_identity_tokens(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """Return stable DOI/arXiv/canonical-URL tokens for a normalized entry."""

    normalized = _validate_entry(entry, require_type=False)
    identity = normalized["identity"]
    tokens = []
    if identity["doi"]:
        tokens.append(f"doi:{identity['doi']}")
    if identity["arxiv_id"]:
        tokens.append(f"arxiv:{identity['arxiv_id']}")
    tokens.extend(f"url:{url}" for url in identity["source_urls"])
    return tuple(sorted(tokens))


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, left: int, right: int) -> None:
        left_root = self.find(left)
        right_root = self.find(right)
        if left_root != right_root:
            self.parent[right_root] = left_root


def deduplicate_bibtex_entries(entries: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Deduplicate by the transitive closure of strong identities.

    Records without a strong identity fall back to exact unit id.  A component
    with multiple DOI/arXiv identities, multiple citation keys, or contradictory
    metadata is rejected instead of choosing an input-order-dependent winner.
    """

    normalized = [_validate_entry(entry, require_type=False) for entry in entries]
    union_find = _UnionFind(len(normalized))
    token_owner: dict[str, int] = {}
    for index, entry in enumerate(normalized):
        tokens = strong_identity_tokens(entry)
        if not tokens:
            tokens = (f"unit:{entry['unit_id']}",)
        for token in tokens:
            if token in token_owner:
                union_find.union(index, token_owner[token])
            else:
                token_owner[token] = index

    components: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for index, entry in enumerate(normalized):
        components[union_find.find(index)].append(entry)

    deduplicated: list[dict[str, Any]] = []
    for component in components.values():
        dois = {item["identity"]["doi"] for item in component if item["identity"]["doi"]}
        arxiv_ids = {
            item["identity"]["arxiv_id"]
            for item in component
            if item["identity"]["arxiv_id"]
        }
        keys = {item["citation_key"] for item in component}
        unit_ids = {item["unit_id"] for item in component}
        if len(dois) > 1:
            raise BibliographyError("one bibliography identity component contains conflicting DOIs")
        if len(arxiv_ids) > 1:
            raise BibliographyError("one bibliography identity component contains conflicting arXiv ids")
        if len(keys) > 1:
            raise BibliographyError("one bibliography identity component contains conflicting citation keys")
        if len(unit_ids) > 1:
            raise BibliographyError("one citation key resolves to multiple canonical unit ids")

        representative = component[0]
        if any(item != representative for item in component[1:]):
            raise BibliographyError("duplicate bibliography selections contain contradictory snapshots")
        deduplicated.append(representative)

    ordered = sorted(deduplicated, key=lambda item: (item["citation_key"], item["unit_id"]))
    seen_keys: dict[str, str] = {}
    for item in ordered:
        existing = seen_keys.get(item["citation_key"])
        if existing is not None and existing != item["unit_id"]:
            raise BibliographyError("citation key collision across bibliography components")
        seen_keys[item["citation_key"]] = item["unit_id"]
    return ordered


def _bibtex_escape(value: str) -> str:
    replacements = {
        # Each replacement containing braces has a net-zero brace depth.  Do
        # not rely on a BibTeX implementation treating ``\{``/``\}`` as
        # structurally escaped: some scanners count those braces while lexing.
        "\\": r"{\textbackslash}",
        "{": r"{\char123}",
        "}": r"{\char125}",
        "#": r"\#",
        "%": r"\%",
        "&": r"\&",
        "$": r"\$",
        "_": r"\_",
        "^": r"{\char94}",
        "~": r"{\char126}",
    }
    return "".join(replacements.get(character, character) for character in value)


def render_bibtex(entries: Sequence[Mapping[str, Any]]) -> str:
    """Render deterministic UTF-8 BibTeX from validated structured entries."""

    deduplicated = deduplicate_bibtex_entries(entries)
    rendered: list[str] = []
    for candidate in deduplicated:
        entry = _validate_entry(candidate, require_type=True)
        fields = entry["fields"]
        lines = [f"@{entry['entry_type']}{{{entry['citation_key']},"]
        for field in _FIELD_ORDER:
            value = fields.get(field)
            if value:
                lines.append(f"  {field} = {{{_bibtex_escape(value)}}},")
        lines.append("}")
        rendered.append("\n".join(lines))
    return "\n\n".join(rendered) + ("\n" if rendered else "")


def bibliography_from_records(records: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], str]:
    """Convenience pure pipeline for integrations that already hold snapshots."""

    entries = [bibtex_entry_from_record(record) for record in records]
    deduplicated = deduplicate_bibtex_entries(entries)
    return deduplicated, render_bibtex(deduplicated)
