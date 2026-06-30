from __future__ import annotations

from html import unescape
from pathlib import Path
from typing import Mapping
import json
import re
import urllib.request

USER_AGENT = "idea-funnel-source-adapter/0.1 (+local Hermes research pipeline)"
DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json, application/atom+xml, application/rss+xml, text/html;q=0.8, */*;q=0.5",
}

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def clean_text(value: object, *, max_chars: int = 500) -> str:
    text = "" if value is None else str(value)
    text = unescape(text)
    text = _TAG_RE.sub(" ", text)
    text = _WS_RE.sub(" ", text).strip()
    if max_chars and len(text) > max_chars:
        return text[: max_chars - 1].rstrip() + "…"
    return text


def fetch_bytes(url: str, *, timeout: int = 20, headers: Mapping[str, str] | None = None) -> bytes:
    merged = dict(DEFAULT_HEADERS)
    if headers:
        merged.update(headers)
    req = urllib.request.Request(url, headers=merged)
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 - controlled URLs from adapters
        return resp.read()


def fetch_json(url: str, *, timeout: int = 20, headers: Mapping[str, str] | None = None) -> object:
    return json.loads(fetch_bytes(url, timeout=timeout, headers=headers).decode("utf-8", "replace"))


def write_raw(raw_dir: Path, filename: str, data: bytes | str) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / filename
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8")
    else:
        path.write_bytes(data)
    return path
