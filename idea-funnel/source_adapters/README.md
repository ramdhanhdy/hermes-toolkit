# Idea Funnel Source Adapters

Deterministic source acquisition for `<ideas-root>`.

## Why this exists

Researchers should not spend LLM/tool turns debugging Reddit, GitHub, HN, ArXiv, or Hugging Face access. This layer fetches source data before the kanban researcher runs, normalizes it, and records degraded source lanes in metrics.

## Run source prefetch only

```bash
cd <ideas-root>
python3 fetch_sources.py --run-id 2026-06-29 --limit 20 --timeout 20
```

Outputs:

```text
runs/<run_id>/
├── raw/                     # raw adapter snapshots
├── normalized/signals.jsonl # researcher input
├── metrics.json             # source health + self-improvement placeholders
└── retrospective.md         # source reliability notes
```

## Run the manual idea-funnel orchestrator

Dry-run, no side effects:

```bash
python3 <ideas-root>/run_idea_funnel.py --dry-run
```

Prepare a unique board and run archive without dispatching workers:

```bash
python3 <ideas-root>/run_idea_funnel.py --prepare-only
```

Full manual run:

```bash
python3 <ideas-root>/run_idea_funnel.py --max-active-workers 2
```

Safety detail: prepare-only boards create tasks unassigned. Hermes may recompute parentless tasks to `ready`, but unassigned ready tasks do not dispatch. The runner assigns/unblocks tasks only when actually launching work.

## Adapters

- `github` - GitHub Search API for AI-agent/tool/MCP repos
- `hackernews` - HN Algolia API for AI-agent/tool/MCP discussions
- `reddit` - Reddit RSS feeds with proper UA; degrades instead of blocking the run
- `arxiv` - ArXiv Atom API for agents/tools/memory/MCP/context-compaction
- `huggingface` - trending models, spaces, and Hugging Face Daily Papers

Note: Papers With Code is now surfaced through Hugging Face Daily Papers. Do not maintain a separate Papers With Code adapter unless HF changes the product again.

## Researcher contract

Researcher reads:

1. `<ideas-root>/wiki/index.md`
2. `runs/<run_id>/normalized/signals.jsonl`
3. `runs/<run_id>/metrics.json`

Researcher does **not** retry raw source fetching during normal discovery. If a source lane is degraded, note the gap and continue.
