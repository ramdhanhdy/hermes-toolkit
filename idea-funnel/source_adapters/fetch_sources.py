from __future__ import annotations

from datetime import datetime, timezone
from importlib import import_module
from pathlib import Path
from typing import Iterable
import argparse
import json
import traceback

from source_adapters.schema import STATUS_FAILED, SourceResult, dedupe_signals, utc_now_iso, write_jsonl

DEFAULT_ADAPTERS = ["github", "hackernews", "reddit", "arxiv", "huggingface"]


def _default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d-source-%H%M%SZ")


def run_adapter(name: str, raw_dir: Path, *, limit: int, timeout: int) -> SourceResult:
    try:
        module = import_module(f"source_adapters.adapters.{name}")
        return module.fetch(raw_dir / name, limit=limit, timeout=timeout)
    except Exception as exc:  # noqa: BLE001 - one adapter must not kill the whole prefetch
        return SourceResult(
            adapter=name,
            status=STATUS_FAILED,
            errors=[f"adapter crash: {type(exc).__name__}: {exc}", traceback.format_exc(limit=5)],
        ).finish()


def write_run_artifacts(run_dir: Path, results: Iterable[SourceResult]) -> dict[str, str]:
    run_dir.mkdir(parents=True, exist_ok=True)
    normalized_dir = run_dir / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)

    results = list(results)
    signals = dedupe_signals(signal for result in results for signal in result.signals)
    signals_path = write_jsonl(normalized_dir / "signals.jsonl", signals)

    sources = {result.adapter: result.metrics() for result in results}
    source_lanes: dict[str, int] = {}
    entity_types: dict[str, int] = {}
    for signal in signals:
        source_lanes[signal.source_lane] = source_lanes.get(signal.source_lane, 0) + 1
        entity_types[signal.entity_type] = entity_types.get(signal.entity_type, 0) + 1

    metrics = {
        "run_id": run_dir.name,
        "generated_at": utc_now_iso(),
        "sources": sources,
        "source_lanes": dict(sorted(source_lanes.items())),
        "entity_types": dict(sorted(entity_types.items())),
        "total_signals": len(signals),
        "ok_sources": sum(1 for result in results if result.status == "ok"),
        "degraded_sources": sum(1 for result in results if result.status == "degraded"),
        "failed_sources": sum(1 for result in results if result.status == "failed"),
        "self_improvement": {
            "repeat_discovery_rate": None,
            "wiki_hits_per_run": None,
            "new_entities_per_run": None,
            "updated_entities_per_run": None,
            "dropped_ideas_avoided": None,
            "notes": "Filled after researcher/synthesizer/wiki-curator stages; source layer records acquisition reliability only.",
        },
        "cost": {
            "tokens_wasted_on_source_debug": 0,
            "note": "Source fetching is deterministic Python; researchers should not spend LLM turns debugging Reddit/API access.",
        },
    }
    metrics_path = run_dir / "metrics.json"
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    retrospective_path = run_dir / "retrospective.md"
    retrospective_path.write_text(_render_retrospective(metrics), encoding="utf-8")

    return {
        "run_dir": str(run_dir),
        "signals_jsonl": str(signals_path),
        "metrics": str(metrics_path),
        "retrospective": str(retrospective_path),
    }


def _render_retrospective(metrics: dict) -> str:
    lines = [
        f"# Idea Funnel Source Prefetch Retrospective — {metrics['run_id']}",
        "",
        f"Generated: {metrics['generated_at']}",
        "",
        "## Source health",
        "",
        "| Adapter | Status | Signals | Errors |",
        "|---|---|---:|---|",
    ]
    for adapter, info in metrics["sources"].items():
        errors = "; ".join(info.get("errors") or [])
        if len(errors) > 180:
            errors = errors[:177] + "…"
        lines.append(f"| {adapter} | {info['status']} | {info['signals']} | {errors or '—'} |")
    lines.extend([
        "",
        "## Coverage",
        "",
        f"- Total normalized signals: {metrics['total_signals']}",
        f"- Source lanes: {len(metrics['source_lanes'])}",
        f"- Entity types: {', '.join(f'{k}={v}' for k, v in metrics['entity_types'].items()) or 'none'}",
        "",
        "## Operational lesson",
        "",
        "Researchers should consume `normalized/signals.jsonl` and `wiki/index.md`. They should not retry raw Reddit/GitHub/HF/ArXiv access during analysis; degraded adapters are recorded here for post-run improvement.",
        "",
    ])
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prefetch deterministic idea-funnel source signals")
    parser.add_argument("--ideas-root", default="/opt/data/ideas", help="Persistent ideas root")
    parser.add_argument("--run-id", default=None, help="Run id/directory name under runs/")
    parser.add_argument("--adapter", action="append", choices=DEFAULT_ADAPTERS, help="Adapter to run; repeatable. Defaults to all.")
    parser.add_argument("--limit", type=int, default=20, help="Per-lane signal limit")
    parser.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds")
    args = parser.parse_args(argv)

    ideas_root = Path(args.ideas_root)
    run_id = args.run_id or _default_run_id()
    run_dir = ideas_root / "runs" / run_id
    raw_dir = run_dir / "raw"
    adapters = args.adapter or DEFAULT_ADAPTERS

    results: list[SourceResult] = []
    for adapter in adapters:
        print(f"SOURCE_ADAPTER_START adapter={adapter}", flush=True)
        result = run_adapter(adapter, raw_dir, limit=args.limit, timeout=args.timeout)
        print(f"SOURCE_ADAPTER_DONE adapter={adapter} status={result.status} signals={len(result.signals)} errors={len(result.errors)}", flush=True)
        results.append(result)

    artifacts = write_run_artifacts(run_dir, results)
    print(json.dumps(artifacts, ensure_ascii=False, indent=2), flush=True)
    return 0 if any(result.signals for result in results) else 2


if __name__ == "__main__":
    raise SystemExit(main())
