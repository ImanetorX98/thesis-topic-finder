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
NASA_ADS_SEARCH = "https://api.adsabs.harvard.edu/v1/search/query"
INSPIRE_API = "https://inspirehep.net/api/literature"
USER_AGENT = "thesis-topic-finder/1.0 (mailto:student@example.com)"  # sostituisci con email reale via --email


def set_email(email: str) -> None:
    global USER_AGENT
    USER_AGENT = f"thesis-topic-finder/1.0 (mailto:{email})"


class APIError(RuntimeError):
    """Raised when an upstream API fails."""


def _get_json(url: str, timeout: int = 30, extra_headers: dict[str, str] | None = None) -> dict[str, Any]:
    headers = {"User-Agent": USER_AGENT}
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
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

        journal_ref = entry.findtext("arxiv:journal_ref", default="", namespaces=ns) or ""
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
                "journal": journal_ref.strip(),
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
            "select": "id,display_name,doi,publication_year,authorships,abstract_inverted_index,primary_location",
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
        primary = work.get("primary_location") or {}
        journal = ((primary.get("source") or {}).get("display_name") or "").strip()
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
                "journal": journal,
                "_openalex_work": work,
            }
        )
    return results


def search_semanticscholar(topic: str, max_results: int = 25) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "query": topic,
            "limit": min(max_results, 100),
            "fields": "title,abstract,authors,year,externalIds,publicationDate,publicationVenue",
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
        journal = ((paper.get("publicationVenue") or {}).get("name") or "").strip()
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
                "journal": journal,
            }
        )
    return results


def search_nasa_ads(topic: str, max_results: int = 25, token: str = "") -> list[dict[str, Any]]:
    if not token:
        raise APIError("NASA ADS richiede un token API. Registrati su https://ui.adsabs.harvard.edu e aggiungi 'ads_token' nel config.json.")
    params = urllib.parse.urlencode(
        {
            "q": topic,
            "fl": "title,abstract,author,aff,doi,pubdate,bibcode,pub,identifier",
            "rows": min(max_results, 2000),
            "sort": "score desc",
        }
    )
    data = _get_json(
        f"{NASA_ADS_SEARCH}?{params}",
        extra_headers={"Authorization": f"Bearer {token}"},
    )
    results: list[dict[str, Any]] = []
    for doc in (data.get("response") or {}).get("docs") or []:
        titles = doc.get("title") or []
        title = titles[0] if titles else ""
        dois = doc.get("doi") or []
        doi = dois[0] if dois else ""
        # Cerca arxiv_id negli identifier
        arxiv_id = ""
        for ident in (doc.get("identifier") or []):
            if ident.lower().startswith("arxiv:"):
                arxiv_id = ident[6:]
                break
        authors = doc.get("author") or []
        pub_date = (doc.get("pubdate") or "")[:10]  # "YYYY-MM-DD"
        results.append(
            {
                "source": "nasaads",
                "arxiv_id": arxiv_id,
                "title": title,
                "summary": doc.get("abstract") or "",
                "published": pub_date,
                "updated": "",
                "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
                "pdf_url": "",
                "doi": doi,
                "authors_arxiv": [a for a in authors if a],
                "journal": doc.get("pub") or "",
            }
        )
    return results


def search_inspire(topic: str, max_results: int = 25) -> list[dict[str, Any]]:
    params = urllib.parse.urlencode(
        {
            "sort": "mostrecent",
            "size": min(max_results, 1000),
            "page": 1,
            "q": topic,
            "fields": "titles,abstracts,authors,dois,arxiv_eprints,publication_info",
        }
    )
    data = _get_json(f"{INSPIRE_API}?{params}")
    results: list[dict[str, Any]] = []
    for hit in (data.get("hits") or {}).get("hits") or []:
        meta = hit.get("metadata") or {}
        titles = meta.get("titles") or []
        title = titles[0].get("value", "") if titles else ""
        abstracts = meta.get("abstracts") or []
        abstract = abstracts[0].get("value", "") if abstracts else ""
        dois = meta.get("dois") or []
        doi = dois[0].get("value", "") if dois else ""
        eprints = meta.get("arxiv_eprints") or []
        arxiv_id = eprints[0].get("value", "") if eprints else ""
        authors = [
            a.get("full_name", "")
            for a in (meta.get("authors") or [])
        ]
        pub_info = (meta.get("publication_info") or [{}])[0]
        journal = pub_info.get("journal_title") or ""
        year = pub_info.get("year")
        pub_date = f"{year}-01-01" if year else ""
        results.append(
            {
                "source": "inspirehep",
                "arxiv_id": arxiv_id,
                "title": title,
                "summary": abstract,
                "published": pub_date,
                "updated": "",
                "arxiv_url": f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else "",
                "pdf_url": "",
                "doi": doi,
                "authors_arxiv": [a for a in authors if a],
                "journal": journal,
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
