from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from typing import Any

ARXIV_API = "http://export.arxiv.org/api/query"
OPENALEX_WORKS = "https://api.openalex.org/works"
S2_SEARCH = "https://api.semanticscholar.org/graph/v1/paper/search"
USER_AGENT = "thesis-topic-finder/1.0 (mailto:student@example.com)"  # sostituisci con email reale via --email


def set_email(email: str) -> None:
    global USER_AGENT
    USER_AGENT = f"thesis-topic-finder/1.0 (mailto:{email})"


class APIError(RuntimeError):
    """Raised when an upstream API fails."""


def _get_json(url: str, timeout: int = 30) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise APIError(f"HTTP error {exc.code} for URL: {url}") from exc
    except urllib.error.URLError as exc:
        raise APIError(f"Network error for URL: {url} ({exc.reason})") from exc


def _get_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise APIError(f"HTTP error {exc.code} for URL: {url}") from exc
    except urllib.error.URLError as exc:
        raise APIError(f"Network error for URL: {url} ({exc.reason})") from exc


def _reconstruct_abstract(inverted_index: dict[str, list[int]] | None) -> str:
    """Ricostruisce l'abstract dall'indice invertito di OpenAlex."""
    if not inverted_index:
        return ""
    positions: list[tuple[int, str]] = [
        (pos, word)
        for word, pos_list in inverted_index.items()
        for pos in pos_list
    ]
    positions.sort()
    return " ".join(word for _, word in positions)


def search_arxiv(topic: str, max_results: int = 25, sleep_s: float = 0.0) -> list[dict[str, Any]]:
    query = urllib.parse.urlencode(
        {
            "search_query": f"all:{topic}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
    )
    xml_text = _get_text(f"{ARXIV_API}?{query}")

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "arxiv": "http://arxiv.org/schemas/atom",
    }
    root = ET.fromstring(xml_text)

    results: list[dict[str, Any]] = []
    for entry in root.findall("atom:entry", ns):
        authors = [a.findtext("atom:name", default="", namespaces=ns) for a in entry.findall("atom:author", ns)]
        doi = entry.findtext("arxiv:doi", default="", namespaces=ns)

        links = entry.findall("atom:link", ns)
        pdf_url = ""
        for link in links:
            if link.attrib.get("title") == "pdf":
                pdf_url = link.attrib.get("href", "")
                break

        results.append(
            {
                "source": "arxiv",
                "arxiv_id": entry.findtext("atom:id", default="", namespaces=ns).rsplit("/", 1)[-1],
                "title": " ".join((entry.findtext("atom:title", default="", namespaces=ns) or "").split()),
                "summary": " ".join((entry.findtext("atom:summary", default="", namespaces=ns) or "").split()),
                "published": entry.findtext("atom:published", default="", namespaces=ns),
                "updated": entry.findtext("atom:updated", default="", namespaces=ns),
                "arxiv_url": entry.findtext("atom:id", default="", namespaces=ns),
                "pdf_url": pdf_url,
                "doi": doi.strip() if doi else "",
                "authors_arxiv": [a for a in authors if a],
            }
        )

    if sleep_s > 0:
        time.sleep(sleep_s)
    return results


def search_openalex(topic: str, max_results: int = 25) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "search": topic,
            "per-page": min(max_results, 200),
            "select": "id,display_name,doi,publication_year,authorships,abstract_inverted_index",
        }
    )
    data = _get_json(f"{OPENALEX_WORKS}?{params}")

    results: list[dict[str, Any]] = []
    for work in data.get("results", []):
        doi = (work.get("doi") or "").replace("https://doi.org/", "")
        authors = [
            (a.get("author") or {}).get("display_name", "")
            for a in (work.get("authorships") or [])
        ]
        year = work.get("publication_year")
        results.append(
            {
                "source": "openalex",
                "arxiv_id": "",
                "title": work.get("display_name") or "",
                "summary": _reconstruct_abstract(work.get("abstract_inverted_index")),
                "published": f"{year}-01-01" if year else "",
                "updated": "",
                "arxiv_url": "",
                "pdf_url": "",
                "doi": doi,
                "authors_arxiv": [a for a in authors if a],
                "_openalex_work": work,
            }
        )
    return results


def search_semanticscholar(topic: str, max_results: int = 25) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "query": topic,
            "limit": min(max_results, 100),
            "fields": "title,abstract,authors,year,externalIds,publicationDate",
        }
    )
    data = _get_json(f"{S2_SEARCH}?{params}")

    results: list[dict[str, Any]] = []
    for paper in data.get("data", []):
        ext = paper.get("externalIds") or {}
        doi = ext.get("DOI", "")
        arxiv_id = ext.get("ArXiv", "")
        authors = [a.get("name", "") for a in (paper.get("authors") or [])]
        pub_date = paper.get("publicationDate") or (f"{paper.get('year')}-01-01" if paper.get("year") else "")
        results.append(
            {
                "source": "semanticscholar",
                "arxiv_id": arxiv_id,
                "title": paper.get("title") or "",
                "summary": paper.get("abstract") or "",
                "published": pub_date,
                "updated": "",
                "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
                "pdf_url": "",
                "doi": doi,
                "authors_arxiv": [a for a in authors if a],
            }
        )
    return results


def fetch_openalex_by_doi(doi: str) -> dict[str, Any] | None:
    clean = doi.strip().lower()
    if not clean:
        return None

    doi_url = f"https://doi.org/{clean}"
    encoded = urllib.parse.quote(doi_url, safe="")
    url = f"{OPENALEX_WORKS}/{encoded}"
    try:
        return _get_json(url)
    except APIError:
        return None


def search_openalex_by_title(title: str, per_page: int = 3) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "search": title,
            "per-page": per_page,
            "select": "id,display_name,doi,publication_year,authorships",
        }
    )
    url = f"{OPENALEX_WORKS}?{params}"
    data = _get_json(url)
    return data.get("results", [])


def resolve_metadata(article: dict[str, Any], title_fallback: bool = True) -> dict[str, Any] | None:
    # Se l'articolo viene da OpenAlex, il work è già embedded — nessuna chiamata extra.
    if article.get("_openalex_work"):
        return article["_openalex_work"]

    by_doi = fetch_openalex_by_doi(article.get("doi", ""))
    if by_doi is not None:
        return by_doi

    if not title_fallback:
        return None

    candidates = search_openalex_by_title(article.get("title", ""), per_page=3)
    if not candidates:
        return None

    arxiv_title = (article.get("title", "") or "").lower().strip()
    for candidate in candidates:
        cand_title = (candidate.get("display_name") or "").lower().strip()
        if cand_title and cand_title == arxiv_title:
            return candidate

    return None
