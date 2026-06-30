from __future__ import annotations

from pathlib import Path
from urllib.parse import urlencode
import json

from source_adapters.http_utils import clean_text, fetch_json, write_raw
from source_adapters.schema import STATUS_DEGRADED, STATUS_FAILED, STATUS_OK, Signal, SourceResult
from source_adapters.search_terms import load_search_terms

HN_ENDPOINT = "https://hn.algolia.com/api/v1/search_by_date"


def _hit_signal(hit: dict, *, lane: str) -> Signal | None:
    title = clean_text(hit.get("title") or hit.get("story_title"), max_chars=220)
    story_url = hit.get("url") or hit.get("story_url")
    object_id = hit.get("objectID")
    url = story_url or (f"https://news.ycombinator.com/item?id={object_id}" if object_id else "")
    if not title or not url:
        return None
    points = hit.get("points")
    return Signal(
        source="hackernews",
        source_lane=lane,
        title=title,
        url=str(url),
        entity_type="community_post",
        summary=clean_text(hit.get("comment_text") or hit.get("story_text"), max_chars=700),
        published_at=hit.get("created_at"),
        score=int(points) if isinstance(points, int) else None,
        tags=["hackernews", lane.replace("hn_", "")],
        metadata={"object_id": object_id, "author": hit.get("author"), "num_comments": hit.get("num_comments")},
    )


def fetch(raw_dir: Path, *, limit: int = 20, timeout: int = 20) -> SourceResult:
    result = SourceResult(adapter="hackernews", status=STATUS_OK)
    queries = load_search_terms("hackernews")
    for lane, query in queries.items():
        url = f"{HN_ENDPOINT}?" + urlencode({"query": query, "tags": "story", "hitsPerPage": limit})
        try:
            data = fetch_json(url, timeout=timeout)
            raw_path = write_raw(raw_dir, f"{lane}.json", json.dumps(data, ensure_ascii=False, indent=2))
            result.raw_files.append(str(raw_path))
            hits = data.get("hits", []) if isinstance(data, dict) else []
            if not hits:
                result.errors.append(f"{lane}: HN returned 0 hits")
            for hit in hits[:limit]:
                signal = _hit_signal(hit, lane=lane)
                if signal:
                    result.signals.append(signal)
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{lane}: {type(exc).__name__}: {exc}")
    if not result.signals:
        result.status = STATUS_FAILED
    elif result.errors:
        result.status = STATUS_DEGRADED
    return result.finish()
