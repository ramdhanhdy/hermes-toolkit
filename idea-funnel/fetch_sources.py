#!/usr/bin/env python3
"""CLI shim for the idea-funnel deterministic source prefetcher."""

from source_adapters.fetch_sources import main

if __name__ == "__main__":
    raise SystemExit(main())
