# Hermes Toolkit

Custom tools, skills, and patches built for [Hermes Agent](https://github.com/nousresearch/hermes-agent) — an AI agent framework by Nous Research.

## What's Inside

| Component | Type | Install | Requires Hermes? |
|-----------|------|---------|:-----------------:|
| [fitness-tracker](skills/fitness-tracker/) | Skill | `hermes skills tap add <your-username>/hermes-toolkit` then install | Yes |
| [idea-funnel](idea-funnel/) | Python package | `pip install ./idea-funnel` or run directly | Orchestrator: Yes, Adapters: No |
| [automation](automation/) | Shell + Python scripts | Copy to PATH or run in place | Yes |
| [provider-slot](patches/provider-slot/) | Source patch | See [patch README](patches/provider-slot/README.md) | Yes (source) |

## Quick Start

### Install as a Skill Tap

```bash
# Add this repo as a skill source
hermes skills tap add <your-username>/hermes-toolkit

# List available skills
hermes skills search

# Install the fitness tracker
hermes skills install fitness-tracker
```

### Use Idea Funnel Standalone

The source adapters work without Hermes — they're pure Python:

```bash
cd idea-funnel
python3 source_adapters/fetch_sources.py --run-id test --limit 20 --timeout 20
```

The orchestrator (`run_idea_funnel.py`) requires Hermes to spawn kanban tasks:

```bash
export HERMES_BIN=hermes      # or full path to hermes binary
export IDEAS_ROOT=/path/to/ideas
python3 run_idea_funnel.py --dry-run
```

### Install Provider-Slot Limiter

See [patches/provider-slot/README.md](patches/provider-slot/README.md) for installation and configuration.

## Environment Variables

| Variable | Default | Used by |
|----------|---------|---------|
| `HERMES_BIN` | `hermes` | idea-funnel, automation scripts |
| `IDEAS_ROOT` | `/opt/data/ideas` | idea-funnel |
| `HERMES_HOME` | current directory | idea-funnel (kanban cwd) |
| `HERMES_PATCHES_DIR` | `~/.hermes/patches` | provider-slot patch |
| `HERMES_PROVIDER_CONCURRENCY_LIMIT` | `3` | provider-slot limiter |
| `HERMES_PROVIDER_SLOT_MAX_WAIT_SEC` | `300` | provider-slot limiter |
| `KANBAN_BOARDS` | `default` | kanban watchdog |
| `KANBAN_MAX_RUNNING` | `2` | kanban heartbeat |
| `LYFTA_API_KEY` | — | fitness-tracker workout sync |
| `NOTION_API_KEY` | — | kanban gates (Notion verification) |

## Repository Structure

```
hermes-toolkit/
├── skills/                    # Hermes skills (tap-installable)
│   └── fitness-tracker/       # Calorie/macro tracking + workout detection
├── idea-funnel/               # Autonomous idea discovery pipeline
│   ├── source_adapters/       # Standalone API adapters (GitHub, HN, Reddit, ArXiv, HF)
│   ├── run_idea_funnel.py     # Kanban orchestrator (requires Hermes)
│   ├── tests/
│   └── workflows/             # Pipeline spec
├── automation/                # Kanban operations scripts
│   ├── kanban-heartbeat.sh    # Concurrency-safe task dispatcher
│   ├── kanban-gates.sh        # Post-run deliverable verification
│   ├── kanban-watchdog.sh     # Crash detection + auto-retry
│   ├── concurrency-guard.sh   # Capacity checker
│   ├── prune-cron-sessions.sh # state.db maintenance
│   └── wiki_graph_orchestrator.py  # Pipeline monitor + crash handler
└── patches/                   # Hermes source patches
    └── provider-slot/         # Cross-process concurrency limiter (fcntl)
```

## License

MIT
