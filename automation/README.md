# Kanban Automation Scripts

Operational scripts for managing Hermes kanban pipelines. All scripts require a running Hermes Agent installation.

## Scripts

### kanban-heartbeat.sh
Concurrency-safe kanban task dispatcher. Set up as a `no_agent` cron job — it checks the board, dispatches ready tasks, and **auto-removes itself** when all tasks are complete.

```bash
# Set env vars in the cron job prompt:
#   KANBAN_JOB_ID  — cron job ID (for self-removal)
#   KANBAN_MAX_RUNNING — max concurrent workers (default: 2)
```

### kanban-watchdog.sh
Detects and retries 1-message crash sessions. When a kanban worker crashes immediately (provider/connection issue, not intelligence), the watchdog promotes the task back to ready for retry.

```bash
# Configure which boards to monitor:
export KANBAN_BOARDS="idea-funnel default"
bash kanban-watchdog.sh
```

Limits: 5 max auto-retries per task. After 2 consecutive early crashes, logs a provider-issue warning.

### kanban-gates.sh
Post-run deterministic gates. Verifies that a deliverable file exists and meets minimum structural requirements (file exists, ≥100 bytes, no excessive placeholders). Does NOT evaluate quality — that's the judge's job.

```bash
bash kanban-gates.sh <task_id> <board> <deliverable_path>
# Exit 0 = pass, exit 1 = fail
```

Supports Notion page verification via `NOTION_API_KEY`:
```bash
bash kanban-gates.sh <task_id> <board> "notion:<page_id>"
```

### concurrency-guard.sh
Checks if there's capacity for a new LLM agent. Counts running kanban workers + active hermes processes. Exits 0 if OK, 1 if at capacity.

```bash
bash concurrency-guard.sh 3  # max 3 agents (leaves 1 slot for chat)
```

### prune-cron-sessions.sh
Weekly cleanup of old cron sessions from Hermes `state.db`. Deletes cron sessions older than N days, rebuilds FTS indexes, vacuums.

```bash
bash prune-cron-sessions.sh 7  # delete sessions older than 7 days
```

Configurable via env:
- `HERMES_STATE_DB` — path to state.db (default: `$HOME/state.db`)
- `HERMES_CRON_OUTPUT` — cron output directory (default: `$HOME/cron/output`)

### wiki_graph_orchestrator.py
Pipeline monitor for multi-task kanban chains. Polls every 60s, detects crashes/blocks/completion, and can escalate to an orchestrator profile for decisions. Handles retry with provider switching (up to 3 retries, switches to fallback provider after 2 crashes).

## Environment Variables

| Variable | Default | Used by |
|----------|---------|---------|
| `HERMES_BIN` | `hermes` | All scripts |
| `KANBAN_BOARDS` | `default` | watchdog |
| `KANBAN_MAX_RUNNING` | `2` | heartbeat |
| `KANBAN_JOB_ID` | — | heartbeat (self-removal) |
| `HERMES_STATE_DB` | `$HOME/state.db` | prune |
| `HERMES_CRON_OUTPUT` | `$HOME/cron/output` | prune |
| `NOTION_API_KEY` | — | gates (Notion verification) |

## License

MIT
