"""Load dynamic search terms from search-terms.json, falling back to hardcoded defaults.

The search-strategist generates search-terms.json after each run. If the file
is missing (first run, or strategist failed), adapters use their built-in
defaults. This keeps the pipeline functional even without prior runs.
"""
from __future__ import annotations

from pathlib import Path
import os
from typing import Any
import json

IDEAS_ROOT = Path(os.environ.get("IDEAS_ROOT", "/opt/data/ideas"))

# Default search terms — used when no search-terms.json exists.
DEFAULTS: dict[str, Any] = {
    "github": {
        "github_ai_agents": "ai agent pushed:>{since} stars:>20",
        "github_llm_tools": "llm tool calling pushed:>{since} stars:>20",
        "github_mcp": "model context protocol pushed:>{since} stars:>10",
    },
    "hackernews": {
        "hn_ai_agents": "AI agent",
        "hn_llm_tools": "LLM tools",
        "hn_mcp": "MCP model context protocol",
        "hn_show_hn_agents": "Show HN AI agent",
    },
    "arxiv": {
        "agent_tools": 'all:"LLM agent" AND all:"tool"',
        "agent_memory": 'all:"agent memory" OR all:"LLM memory"',
        "mcp_security": 'all:"model context protocol" OR all:"tool poisoning"',
        "context_compaction": 'all:"context compression" OR all:"context compaction"',
    },
    "reddit_feeds": {
        "LocalLLaMA": "https://www.reddit.com/r/LocalLLaMA/top/.rss?t=week&limit=25",
        "MachineLearning": "https://www.reddit.com/r/MachineLearning/top/.rss?t=week&limit=25",
        "artificial": "https://www.reddit.com/r/artificial/top/.rss?t=week&limit=25",
    },
}


def _find_latest_search_terms(ideas_root: Path | None = None) -> dict | None:
    """Find the most recent search-terms.json across all runs."""
    root = ideas_root or IDEAS_ROOT
    runs_dir = root / "runs"
    if not runs_dir.exists():
        return None
    candidates = sorted(runs_dir.glob("*/search-terms.json"), reverse=True)
    for candidate in candidates:
        try:
            data = json.loads(candidate.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, OSError):
            continue
    return None


def load_search_terms(adapter: str, *, ideas_root: Path | None = None) -> dict[str, str]:
    """Load search terms for a specific adapter.

    Args:
        adapter: One of 'github', 'hackernews', 'arxiv', 'reddit_feeds'.
        ideas_root: Override the ideas root directory.

    Returns:
        Dict of {lane_name: query_string}. Falls back to DEFAULTS if no
        search-terms.json exists or the adapter key is missing.
    """
    dynamic = _find_latest_search_terms(ideas_root)
    if dynamic and adapter in dynamic and isinstance(dynamic[adapter], dict):
        return {str(k): str(v) for k, v in dynamic[adapter].items()}
    return DEFAULTS.get(adapter, {}).copy()
