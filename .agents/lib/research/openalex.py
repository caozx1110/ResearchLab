"""Bounded OpenAlex Works client and factual candidate mapping."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


OPENALEX_WORKS_URL = "https://api.openalex.org/works"
DEFAULT_PER_PAGE = 25
MAX_PER_PAGE = 100
WORK_SELECT_FIELDS = (
    "id",
    "doi",
    "display_name",
    "publication_date",
    "publication_year",
    "type",
    "language",
    "cited_by_count",
    "is_retracted",
    "primary_location",
    "best_oa_location",
)

Transport = Callable[[str, float], tuple[int, bytes]]


class OpenAlexError(RuntimeError):
    """A deliberately redacted, user-safe OpenAlex failure."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _stdlib_transport(url: str, timeout: float) -> tuple[int, bytes]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "research-literature-scout/1"})
    try:
        with urlopen(request, timeout=timeout) as response:
            return int(getattr(response, "status", 200)), response.read()
    except HTTPError as exc:
        return int(exc.code), exc.read()


def _text(value: Any) -> str:
    return " ".join(str(value or "").split())


def _bounded_string(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def _safe_http_url(value: Any, *, host: str = "") -> str:
    url = _bounded_string(value, 4096)
    if not url:
        return ""
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        return ""
    if host and (parsed.hostname or "").lower() != host:
        return ""
    return url


def _canonical_doi(value: Any) -> str:
    doi = _bounded_string(value, 512)
    if not doi:
        return ""
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.IGNORECASE).strip()
    if re.fullmatch(r"10\.\d{4,9}/\S+", doi) is None:
        return ""
    return f"https://doi.org/{doi.lower()}"


def _safe_nonnegative_int(value: Any, *, maximum: int) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= maximum:
        return None
    return value


def _safe_date(value: Any) -> str:
    date = _bounded_string(value, 10)
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) is None:
        return ""
    try:
        datetime.fromisoformat(date)
    except ValueError:
        return ""
    return date


def sanitize_openalex_provenance(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    work_id = _safe_http_url(raw.get("work_id"), host="openalex.org")
    if work_id and re.fullmatch(r"/W\d+/?", urlparse(work_id).path, flags=re.IGNORECASE) is None:
        work_id = ""
    facts: dict[str, Any] = {
        "work_id": work_id,
        "doi": _canonical_doi(raw.get("doi")),
        "publication_date": _safe_date(raw.get("publication_date")),
        "publication_year": _safe_nonnegative_int(raw.get("publication_year"), maximum=9999),
        "type": _bounded_string(raw.get("type"), 128),
        "language": _bounded_string(raw.get("language"), 32),
        "cited_by_count": _safe_nonnegative_int(raw.get("cited_by_count"), maximum=2**63 - 1),
        "open_access_landing_url": _safe_http_url(raw.get("open_access_landing_url")),
        "open_access_pdf_url": _safe_http_url(raw.get("open_access_pdf_url")),
        "queried_at": _bounded_string(raw.get("queried_at"), 64),
    }
    if isinstance(raw.get("is_retracted"), bool):
        facts["is_retracted"] = raw["is_retracted"]
    return {key: value for key, value in facts.items() if value not in (None, "", [], {})}


def _candidate_id(work_id: str, doi: str) -> str:
    if work_id:
        suffix = work_id.rstrip("/").rsplit("/", 1)[-1].lower()
        suffix = re.sub(r"[^a-z0-9-]+", "-", suffix).strip("-")
        if suffix:
            return f"openalex-{suffix}"
    return "openalex-doi-" + hashlib.sha1(doi.encode("utf-8")).hexdigest()[:12]


def map_openalex_works(
    results: Any,
    *,
    queried_at: str,
    include_retracted: bool = False,
) -> list[dict[str, Any]]:
    if not isinstance(results, list):
        raise OpenAlexError("OpenAlex returned an invalid works response before staging.")
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in results:
        if not isinstance(raw, dict):
            continue
        is_retracted = raw.get("is_retracted") is True
        if is_retracted and not include_retracted:
            continue
        work_id = _safe_http_url(raw.get("id"), host="openalex.org")
        if work_id and re.fullmatch(r"/W\d+/?", urlparse(work_id).path, flags=re.IGNORECASE) is None:
            work_id = ""
        doi = _canonical_doi(raw.get("doi"))
        stable_identities = {identity for identity in (work_id, doi) if identity}
        if not stable_identities or stable_identities & seen:
            continue
        seen.update(stable_identities)
        title = _bounded_string(raw.get("display_name"), 1000)
        primary = raw.get("primary_location")
        best_oa = raw.get("best_oa_location")
        primary_landing = _safe_http_url(primary.get("landing_page_url")) if isinstance(primary, dict) else ""
        landing_url = primary_landing or doi or work_id
        if not title or not landing_url:
            continue
        oa_landing = _safe_http_url(best_oa.get("landing_page_url")) if isinstance(best_oa, dict) else ""
        oa_pdf = _safe_http_url(best_oa.get("pdf_url")) if isinstance(best_oa, dict) else ""
        facts = sanitize_openalex_provenance({
            "work_id": work_id,
            "doi": doi,
            "publication_date": raw.get("publication_date"),
            "publication_year": raw.get("publication_year"),
            "type": raw.get("type"),
            "language": raw.get("language"),
            "cited_by_count": raw.get("cited_by_count"),
            "is_retracted": is_retracted,
            "open_access_landing_url": oa_landing,
            "open_access_pdf_url": oa_pdf,
            "queried_at": queried_at,
        })
        candidates.append(
            {
                "candidate_id": _candidate_id(work_id, doi),
                "title": title,
                "url": landing_url,
                "provenance": {
                    "openalex": {
                        key: value
                        for key, value in facts.items()
                        if value not in (None, "", [], {})
                    }
                },
            }
        )
    return candidates


class OpenAlexClient:
    def __init__(self, *, transport: Transport | None = None, timeout: float = 20.0) -> None:
        self._transport = transport or _stdlib_transport
        self._timeout = timeout

    def search_works(
        self,
        query: str,
        *,
        per_page: int = DEFAULT_PER_PAGE,
        include_retracted: bool = False,
    ) -> list[dict[str, Any]]:
        clean_query = _text(query)
        if not clean_query:
            raise OpenAlexError("OpenAlex search requires a research question before staging.")
        if not isinstance(per_page, int) or isinstance(per_page, bool) or not 1 <= per_page <= MAX_PER_PAGE:
            raise OpenAlexError(f"OpenAlex search size must be between 1 and {MAX_PER_PAGE}.")
        api_key = _text(os.environ.get("OPENALEX_API_KEY"))
        if not api_key:
            raise OpenAlexError("OpenAlex access is not configured; no candidates were staged.")
        query_string = urlencode(
            {
                "search": clean_query,
                "per-page": per_page,
                "select": ",".join(WORK_SELECT_FIELDS),
                "api_key": api_key,
            }
        )
        request_url = f"{OPENALEX_WORKS_URL}?{query_string}"
        try:
            status, body = self._transport(request_url, self._timeout)
        except Exception:
            raise OpenAlexError("OpenAlex could not be reached; no candidates were staged.") from None
        if status == 429:
            raise OpenAlexError("OpenAlex rate limit was reached; no candidates were staged.")
        if status < 200 or status >= 300:
            raise OpenAlexError("OpenAlex request failed; no candidates were staged.")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise OpenAlexError("OpenAlex returned an invalid response; no candidates were staged.") from None
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise OpenAlexError("OpenAlex returned an invalid works response before staging.")
        return map_openalex_works(
            payload["results"],
            queried_at=_utc_now_iso(),
            include_retracted=include_retracted,
        )


__all__ = [
    "DEFAULT_PER_PAGE",
    "MAX_PER_PAGE",
    "OPENALEX_WORKS_URL",
    "WORK_SELECT_FIELDS",
    "OpenAlexClient",
    "OpenAlexError",
    "map_openalex_works",
    "sanitize_openalex_provenance",
]
