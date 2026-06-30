from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
import json


STATUS_OK = "ok"
STATUS_DEGRADED = "degraded"
STATUS_FAILED = "failed"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class Signal:
    """A normalized discovery signal from any upstream source."""

    source: str
    source_lane: str
    title: str
    url: str
    entity_type: str
    summary: str = ""
    published_at: str | None = None
    score: int | float | None = None
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    fetched_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        # Keep JSONL compact and stable: omit empty optional fields.
        return {k: v for k, v in data.items() if v not in (None, "", [], {})}


@dataclass(slots=True)
class SourceResult:
    """Result from one deterministic adapter run."""

    adapter: str
    status: str
    signals: list[Signal] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    raw_files: list[str] = field(default_factory=list)
    started_at: str = field(default_factory=utc_now_iso)
    finished_at: str | None = None

    def finish(self) -> "SourceResult":
        self.finished_at = utc_now_iso()
        if self.status == STATUS_OK and self.errors:
            self.status = STATUS_DEGRADED
        if not self.signals and self.status == STATUS_OK:
            self.status = STATUS_DEGRADED
        return self

    def metrics(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "signals": len(self.signals),
            "errors": list(self.errors),
            "raw_files": list(self.raw_files),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }


def write_jsonl(path: str | Path, signals: Iterable[Signal]) -> Path:
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for signal in signals:
            f.write(json.dumps(signal.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")
    return out


def dedupe_signals(signals: Iterable[Signal]) -> list[Signal]:
    """Dedupe by canonical URL first, then source+title fallback."""
    seen: set[tuple[str, str]] = set()
    out: list[Signal] = []
    for signal in signals:
        url_key = signal.url.strip().rstrip("/").lower()
        title_key = " ".join(signal.title.lower().split())
        key = (url_key or signal.source, title_key)
        if key in seen:
            continue
        seen.add(key)
        out.append(signal)
    return out
