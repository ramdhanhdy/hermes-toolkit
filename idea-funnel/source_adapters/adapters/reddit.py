from __future__ import annotations

from pathlib import Path
import time
import xml.etree.ElementTree as ET

from source_adapters.http_utils import clean_text, fetch_bytes, write_raw
from source_adapters.schema import STATUS_DEGRADED, STATUS_FAILED, STATUS_OK, Signal, SourceResult
from source_adapters.search_terms import load_search_terms

ATOM = "{http://www.w3.org/2005/Atom}"


def parse_reddit_atom(data: bytes, *, subreddit: str, limit: int = 25) -> list[Signal]:
    root = ET.fromstring(data)
    signals: list[Signal] = []
    for entry in root.findall(f"{ATOM}entry")[:limit]:
        title = clean_text(entry.findtext(f"{ATOM}title"), max_chars=220)
        summary = clean_text(entry.findtext(f"{ATOM}summary") or entry.findtext(f"{ATOM}content"), max_chars=700)
        updated = clean_text(entry.findtext(f"{ATOM}updated"), max_chars=80) or None
        link = ""
        for link_el in entry.findall(f"{ATOM}link"):
            href = link_el.attrib.get("href", "")
            if href:
                link = href
                break
        if not title or not link:
            continue
        signals.append(
            Signal(
                source="reddit",
                source_lane=f"r/{subreddit}",
                title=title,
                url=link,
                entity_type="community_post",
                summary=summary,
                published_at=updated,
                tags=["reddit", "community", subreddit.lower()],
                metadata={"subreddit": subreddit},
            )
        )
    return signals


def fetch(raw_dir: Path, *, limit: int = 25, timeout: int = 20, delay_seconds: float = 2.0) -> SourceResult:
    result = SourceResult(adapter="reddit", status=STATUS_OK)
    feeds = load_search_terms("reddit_feeds")
    for idx, (subreddit, url) in enumerate(feeds.items()):
        if idx:
            time.sleep(delay_seconds)
        try:
            data = fetch_bytes(url, timeout=timeout, headers={"Accept": "application/atom+xml, application/rss+xml, */*"})
            raw_path = write_raw(raw_dir, f"reddit_{subreddit}.atom", data)
            result.raw_files.append(str(raw_path))
            parsed = parse_reddit_atom(data, subreddit=subreddit, limit=limit)
            if not parsed:
                result.errors.append(f"{subreddit}: feed returned 0 parseable entries")
            result.signals.extend(parsed)
        except Exception as exc:  # noqa: BLE001 - adapter should degrade, not crash run
            result.errors.append(f"{subreddit}: {type(exc).__name__}: {exc}")
    if not result.signals:
        result.status = STATUS_FAILED
    elif result.errors:
        result.status = STATUS_DEGRADED
    return result.finish()
