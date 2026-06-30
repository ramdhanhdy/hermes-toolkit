from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode
import xml.etree.ElementTree as ET

from source_adapters.http_utils import clean_text, fetch_bytes, write_raw
from source_adapters.schema import STATUS_DEGRADED, STATUS_FAILED, STATUS_OK, Signal, SourceResult
from source_adapters.search_terms import load_search_terms

ARXIV_ENDPOINT = "https://export.arxiv.org/api/query"
ATOM = "{http://www.w3.org/2005/Atom}"


def parse_arxiv_atom(data: bytes, *, lane: str, limit: int = 10) -> list[Signal]:
    root = ET.fromstring(data)
    signals: list[Signal] = []
    for entry in root.findall(f"{ATOM}entry")[:limit]:
        title = clean_text(entry.findtext(f"{ATOM}title"), max_chars=260)
        summary = clean_text(entry.findtext(f"{ATOM}summary"), max_chars=900)
        published = clean_text(entry.findtext(f"{ATOM}published"), max_chars=80) or None
        url = clean_text(entry.findtext(f"{ATOM}id"), max_chars=240)
        authors = [clean_text(a.findtext(f"{ATOM}name"), max_chars=120) for a in entry.findall(f"{ATOM}author")]
        authors = [a for a in authors if a]
        if not title or not url:
            continue
        arxiv_id = url.rstrip("/").split("/")[-1]
        signals.append(
            Signal(
                source="arxiv",
                source_lane=lane,
                title=title,
                url=url,
                entity_type="paper",
                summary=summary,
                published_at=published,
                tags=["arxiv", lane.replace("_", "-")],
                metadata={"arxiv_id": arxiv_id, "authors": authors[:8]},
            )
        )
    return signals


def fetch(raw_dir: Path, *, limit: int = 10, timeout: int = 25) -> SourceResult:
    result = SourceResult(adapter="arxiv", status=STATUS_OK)
    queries = load_search_terms("arxiv")
    for lane, query in queries.items():
        params = urlencode({
            "search_query": query,
            "start": 0,
            "max_results": limit,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        })
        url = f"{ARXIV_ENDPOINT}?{params}"
        try:
            data = fetch_bytes(url, timeout=timeout, headers={"Accept": "application/atom+xml, */*"})
            raw_path = write_raw(raw_dir, f"arxiv_{lane}.atom", data)
            result.raw_files.append(str(raw_path))
            parsed = parse_arxiv_atom(data, lane=lane, limit=limit)
            if not parsed:
                result.errors.append(f"{lane}: API returned 0 parseable entries")
            result.signals.extend(parsed)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{lane}: {type(exc).__name__}: {exc}")
    if not result.signals:
        result.status = STATUS_FAILED
    elif result.errors:
        result.status = STATUS_DEGRADED
    return result.finish()
