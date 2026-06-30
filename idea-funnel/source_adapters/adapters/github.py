from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode
import json

from source_adapters.http_utils import clean_text, fetch_json, write_raw
from source_adapters.schema import STATUS_DEGRADED, STATUS_FAILED, STATUS_OK, Signal, SourceResult
from source_adapters.search_terms import load_search_terms

GITHUB_ENDPOINT = "https://api.github.com/search/repositories"


def _since(days: int = 90) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).date().isoformat()


def _repo_signal(item: dict, *, lane: str) -> Signal:
    full_name = clean_text(item.get("full_name"), max_chars=180)
    description = clean_text(item.get("description"), max_chars=700)
    topics = item.get("topics") or []
    stars = int(item.get("stargazers_count") or 0)
    return Signal(
        source="github",
        source_lane=lane,
        title=full_name,
        url=str(item.get("html_url") or ""),
        entity_type="repo",
        summary=description,
        published_at=item.get("pushed_at") or item.get("updated_at"),
        score=stars,
        tags=["github", "repo", *[str(t) for t in topics[:8]]],
        metadata={
            "language": item.get("language"),
            "stars": stars,
            "forks": item.get("forks_count"),
            "open_issues": item.get("open_issues_count"),
            "topics": topics,
        },
    )


def fetch(raw_dir: Path, *, limit: int = 20, timeout: int = 20) -> SourceResult:
    result = SourceResult(adapter="github", status=STATUS_OK)
    since = _since(90)
    queries = load_search_terms("github")
    for lane, query in queries.items():
        query = query.replace("{since}", since)
        url = f"{GITHUB_ENDPOINT}?" + urlencode({"q": query, "sort": "stars", "order": "desc", "per_page": limit})
        try:
            data = fetch_json(url, timeout=timeout, headers={"Accept": "application/vnd.github+json"})
            raw_path = write_raw(raw_dir, f"{lane}.json", json.dumps(data, ensure_ascii=False, indent=2))
            result.raw_files.append(str(raw_path))
            items = data.get("items", []) if isinstance(data, dict) else []
            if not items:
                result.errors.append(f"{lane}: GitHub returned 0 items")
            for item in items[:limit]:
                if item.get("html_url") and item.get("full_name"):
                    result.signals.append(_repo_signal(item, lane=lane))
        except Exception as exc:  # noqa: BLE001
            result.errors.append(f"{lane}: {type(exc).__name__}: {exc}")
    if not result.signals:
        result.status = STATUS_FAILED
    elif result.errors:
        result.status = STATUS_DEGRADED
    return result.finish()
