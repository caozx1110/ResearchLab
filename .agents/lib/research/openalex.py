"""Bounded OpenAlex Works client and factual candidate mapping."""
from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable
from urllib.error import HTTPError
from urllib.parse import urlencode
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


def _canonical_doi(value: Any) -> str:
    doi = _text(value)
    if not doi:
        return ""
    doi = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)", "", doi, flags=re.IGNORECASE).strip()
    return f"https://doi.org/{doi.lower()}" if doi else ""


def _location_url(value: Any, field: str) -> str:
    return _text(value.get(field)) if isinstance(value, dict) else ""


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
        is_retracted = bool(raw.get("is_retracted"))
        if is_retracted and not include_retracted:
            continue
        work_id = _text(raw.get("id"))
        doi = _canonical_doi(raw.get("doi"))
        stable_identities = {identity for identity in (work_id, doi) if identity}
        if not stable_identities or stable_identities & seen:
            continue
        seen.update(stable_identities)
        title = _text(raw.get("display_name"))
        primary = raw.get("primary_location")
        best_oa = raw.get("best_oa_location")
        landing_url = _location_url(primary, "landing_page_url") or doi or work_id
        if not title or not landing_url:
            continue
        oa_landing = _location_url(best_oa, "landing_page_url")
        oa_pdf = _location_url(best_oa, "pdf_url")
        facts = {
            "work_id": work_id,
            "doi": doi,
            "publication_date": _text(raw.get("publication_date")),
            "publication_year": raw.get("publication_year"),
            "type": _text(raw.get("type")),
            "language": _text(raw.get("language")),
            "cited_by_count": raw.get("cited_by_count"),
            "is_retracted": is_retracted,
            "open_access_landing_url": oa_landing,
            "open_access_pdf_url": oa_pdf,
            "queried_at": queried_at,
        }
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
]
