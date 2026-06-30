# Idea Funnel

An autonomous multi-agent pipeline that discovers, filters, and researches build-worthy ideas. Scans GitHub, Hacker News, Reddit, ArXiv, and Hugging Face, then produces structured idea briefs.

## Architecture

```
DISCOVER → FILTER → GO DEEP → BRIEF → DELIVER
```

### Two Layers

1. **Source adapters** (standalone, no Hermes required) - fetch and normalize signals from APIs
2. **Kanban orchestrator** (requires Hermes) - spawns researcher/judge/synthesizer agents via kanban boards

## Source Adapters

The adapters are pure Python with zero Hermes dependencies:

| Adapter | Source | API |
|---------|--------|-----|
| `github.py` | GitHub trending repos/topics | GitHub Search API |
| `hackernews.py` | Hacker News threads | Algolia HN API |
| `reddit.py` | r/LocalLLaMA, r/MachineLearning, r/artificial | Reddit JSON API |
| `arxiv.py` | Papers on multi-agent systems, LLM apps | ArXiv Atom API |
| `huggingface.py` | Trending models, spaces, daily papers | Hugging Face API |

### Run Adapters Standalone

```bash
cd idea-funnel
python3 source_adapters/fetch_sources.py --run-id test --limit 20 --timeout 20
```

Output:
```
runs/<run_id>/
├── raw/                     # Raw API snapshots per source
├── normalized/signals.jsonl # Normalized signals for analysis
├── metrics.json             # Source health + signal counts
└── retrospective.md         # Source reliability notes
```

## Kanban Orchestrator

The orchestrator creates a unique kanban board per run, spawns parallel researcher agents, then chains through verification → synthesis → judging → wiki curation.

### Pipeline Tasks

```
github_hn ──┐
reddit_arxiv ─┼→ verifier → synthesizer → judge → wiki_curator → search_strategist
huggingface ─┘
```

### Run the Full Pipeline

```bash
export HERMES_BIN=hermes          # or /path/to/hermes
export IDEAS_ROOT=/path/to/ideas  # writable dir for run outputs

# Dry run (print plan, no side effects)
python3 run_idea_funnel.py --dry-run

# Full run
python3 run_idea_funnel.py --max-active-workers 2 --max-minutes 180
```

### CLI Options

```
--run-id ID             Run identifier (defaults to UTC timestamp)
--ideas-root DIR        Root directory for ideas data (default: $IDEAS_ROOT)
--hermes-bin PATH       Path to hermes binary (default: $HERMES_BIN)
--limit N               Per-lane source adapter limit (default: 20)
--timeout N             Source adapter HTTP timeout in seconds (default: 20)
--max-active-workers N  Concurrent kanban workers (default: 2)
--poll-seconds N        Status poll interval (default: 60)
--max-minutes N         Timeout for full pipeline (default: 180)
--dry-run               Print plan only
--skip-fetch            Reuse existing source data
--prepare-only          Create board/tasks but don't dispatch
--no-monitor            Dispatch once and exit
```

## Testing

```bash
cd idea-funnel
python3 -m pytest tests/ -v
```

## Workflow Spec

See [workflows/idea-funnel.md](workflows/idea-funnel.md) for the full pipeline specification.

## License

MIT
