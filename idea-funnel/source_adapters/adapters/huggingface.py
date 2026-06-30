from __future__ import annotations

from pathlib import Path
import json
import re

from source_adapters.http_utils import clean_text, fetch_bytes, fetch_json, write_raw
from source_adapters.schema import STATUS_DEGRADED, STATUS_FAILED, STATUS_OK, Signal, SourceResult

HF_MODELS = "https://huggingface.co/api/models?sort=trendingScore&direction=-1&limit=25&full=true"
HF_SPACES = "https://huggingface.co/api/spaces?sort=likes&direction=-1&limit=20&full=true"
HF_DAILY_PAPERS_API = "https://huggingface.co/api/daily_papers"
HF_PAPERS_PAGE = "https://huggingface.co/papers"

PAPER_LINK_RE = re.compile(r'href="(/papers/[^"]+)"[^>]*>(.*?)</a>', re.S)


def _model_signal(item: dict) -> Signal | None:
    model_id = clean_text(item.get("modelId") or item.get("id"), max_chars=220)
    if not model_id:
        return None
    tags = [str(t) for t in (item.get("tags") or [])[:12]]
    downloads = item.get("downloads")
    likes = item.get("likes")
    return Signal(
        source="huggingface",
        source_lane="hf_trending_models",
        title=model_id,
        url=f"https://huggingface.co/{model_id}",
        entity_type="model",
        summary=clean_text(item.get("cardData", {}).get("summary") if isinstance(item.get("cardData"), dict) else "", max_chars=700),
        published_at=item.get("lastModified") or item.get("createdAt"),
        score=int(likes) if isinstance(likes, int) else None,
        tags=["huggingface", "model", *tags],
        metadata={"downloads": downloads, "likes": likes, "pipeline_tag": item.get("pipeline_tag")},
    )


def _space_signal(item: dict) -> Signal | None:
    space_id = clean_text(item.get("id") or item.get("name"), max_chars=220)
    if not space_id:
        return None
    likes = item.get("likes")
    return Signal(
        source="huggingface",
        source_lane="hf_spaces",
        title=space_id,
        url=f"https://huggingface.co/spaces/{space_id}",
        entity_type="space",
        summary=clean_text(item.get("sdk") or item.get("subdomain"), max_chars=400),
        published_at=item.get("lastModified") or item.get("createdAt"),
        score=int(likes) if isinstance(likes, int) else None,
        tags=["huggingface", "space", str(item.get("sdk") or "").lower()],
        metadata={"likes": likes, "sdk": item.get("sdk")},
    )


def _paper_from_api(item: dict) -> Signal | None:
    paper = item.get("paper") if isinstance(item.get("paper"), dict) else item
    paper_id = clean_text(paper.get("id") or paper.get("paperId") or item.get("paperId"), max_chars=120)
    title = clean_text(paper.get("title") or item.get("title"), max_chars=260)
    if not title:
        return None
    url = f"https://huggingface.co/papers/{paper_id}" if paper_id else str(item.get("url") or HF_PAPERS_PAGE)
    upvotes = item.get("upvotes") or item.get("numUpvotes") or paper.get("upvotes")
    return Signal(
        source="huggingface",
        source_lane="hf_daily_papers",
        title=title,
        url=url,
        entity_type="paper",
        summary=clean_text(paper.get("summary") or item.get("summary") or paper.get("abstract"), max_chars=900),
        published_at=paper.get("publishedAt") or item.get("publishedAt") or item.get("date"),
        score=int(upvotes) if isinstance(upvotes, int) else None,
        tags=["huggingface", "daily-papers", "paper"],
        metadata={"paper_id": paper_id, "upvotes": upvotes},
    )


def _parse_daily_papers_payload(data: object, *, limit: int) -> list[Signal]:
    if isinstance(data, dict):
        if isinstance(data.get("papers"), list):
            items = data["papers"]
        elif isinstance(data.get("dailyPapers"), list):
            items = data["dailyPapers"]
        else:
            items = [data]
    elif isinstance(data, list):
        items = data
    else:
        items = []
    out = []
    for item in items[:limit]:
        if isinstance(item, dict):
            signal = _paper_from_api(item)
            if signal:
                out.append(signal)
    return out


def _parse_daily_papers_html(data: bytes, *, limit: int) -> list[Signal]:
    html = data.decode("utf-8", "replace")
    out: list[Signal] = []
    seen: set[str] = set()
    for href, label_html in PAPER_LINK_RE.findall(html):
        if href in seen:
            continue
        seen.add(href)
        title = clean_text(label_html, max_chars=260)
        if not title or title.lower() in {"papers", "daily papers"}:
            continue
        out.append(
            Signal(
                source="huggingface",
                source_lane="hf_daily_papers",
                title=title,
                url=f"https://huggingface.co{href}",
                entity_type="paper",
                summary="",
                tags=["huggingface", "daily-papers", "paper"],
                metadata={"parsed_from": "html"},
            )
        )
        if len(out) >= limit:
            break
    return out


def fetch(raw_dir: Path, *, limit: int = 20, timeout: int = 20) -> SourceResult:
    result = SourceResult(adapter="huggingface", status=STATUS_OK)

    try:
        data = fetch_json(HF_MODELS, timeout=timeout)
        raw_path = write_raw(raw_dir, "huggingface_models.json", json.dumps(data, ensure_ascii=False, indent=2))
        result.raw_files.append(str(raw_path))
        models = data if isinstance(data, list) else []
        for item in models[:limit]:
            if isinstance(item, dict):
                signal = _model_signal(item)
                if signal:
                    result.signals.append(signal)
        if not models:
            result.errors.append("hf_trending_models: returned 0 items")
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"hf_trending_models: {type(exc).__name__}: {exc}")

    try:
        data = fetch_json(HF_SPACES, timeout=timeout)
        raw_path = write_raw(raw_dir, "huggingface_spaces.json", json.dumps(data, ensure_ascii=False, indent=2))
        result.raw_files.append(str(raw_path))
        spaces = data if isinstance(data, list) else []
        for item in spaces[:limit]:
            if isinstance(item, dict):
                signal = _space_signal(item)
                if signal:
                    result.signals.append(signal)
        if not spaces:
            result.errors.append("hf_spaces: returned 0 items")
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"hf_spaces: {type(exc).__name__}: {exc}")

    # Papers With Code is now surfaced through Hugging Face Daily Papers; keep it
    # as an HF lane rather than a separate adapter.
    try:
        data = fetch_json(HF_DAILY_PAPERS_API, timeout=timeout)
        raw_path = write_raw(raw_dir, "huggingface_daily_papers.json", json.dumps(data, ensure_ascii=False, indent=2))
        result.raw_files.append(str(raw_path))
        papers = _parse_daily_papers_payload(data, limit=limit)
        if not papers:
            result.errors.append("hf_daily_papers_api: returned 0 parseable papers")
        result.signals.extend(papers)
    except Exception as exc:  # noqa: BLE001
        result.errors.append(f"hf_daily_papers_api: {type(exc).__name__}: {exc}")
        try:
            page = fetch_bytes(HF_PAPERS_PAGE, timeout=timeout, headers={"Accept": "text/html, */*"})
            raw_path = write_raw(raw_dir, "huggingface_papers.html", page)
            result.raw_files.append(str(raw_path))
            papers = _parse_daily_papers_html(page, limit=limit)
            if not papers:
                result.errors.append("hf_daily_papers_html: returned 0 parseable papers")
            result.signals.extend(papers)
        except Exception as html_exc:  # noqa: BLE001
            result.errors.append(f"hf_daily_papers_html: {type(html_exc).__name__}: {html_exc}")

    if not result.signals:
        result.status = STATUS_FAILED
    elif result.errors:
        result.status = STATUS_DEGRADED
    return result.finish()
