#!/usr/bin/env bash
# kanban-heartbeat.sh — reusable concurrency-safe kanban dispatcher.
# Auto-removes itself when all tasks on the board are complete.
#
# Usage:
#   Set up as no_agent cron job with --script kanban-heartbeat.sh
#   The script checks the kanban board, dispatches ready tasks,
#   and self-destructs (via hermes cron remove) when done.
#
# Environment variables (set in cron prompt or script):
#   KANBAN_JOB_ID  — the cron job ID of this heartbeat (for self-removal)
#   KANBAN_MAX_RUNNING — max concurrent workers (default 2, leaves headroom on 4-limit)

set -uo pipefail

KANBAN="${HERMES_BIN:-hermes} kanban"
HERMES="${HERMES_BIN:-hermes}"
MAX_RUNNING="${KANBAN_MAX_RUNNING:-2}"
JOB_ID="${KANBAN_JOB_ID:-}"

# Count tasks by status
RUNNING=$($KANBAN ls 2>/dev/null | grep -c '^\●' 2>/dev/null || true); RUNNING=${RUNNING:-0}
BLOCKED=$($KANBAN ls 2>/dev/null | grep -c '^\⊘' 2>/dev/null || true); BLOCKED=${BLOCKED:-0}
TODO=$($KANBAN ls 2>/dev/null | grep -c '^\◻' 2>/dev/null || true); TODO=${TODO:-0}

# ── Check if pipeline is complete ──────────────────────────────────
# Complete = no running, no todo, no blocked tasks (only done tasks remain)
if [ "$RUNNING" -eq 0 ] && [ "$TODO" -eq 0 ] && [ "$BLOCKED" -eq 0 ]; then
  echo "✅ Kanban pipeline complete — all tasks done."
  echo ""
  $KANBAN ls 2>/dev/null
  echo ""
  
  # Self-destruct: remove this cron job
  if [ -n "$JOB_ID" ]; then
    $HERMES cron remove "$JOB_ID" 2>/dev/null && echo "Heartbeat cron auto-removed." || true
  fi
  exit 0
fi

# ── Report blocked tasks ──────────────────────────────────────────
if [ "$BLOCKED" -gt 0 ]; then
  echo "⚠️ $BLOCKED blocked task(s):"
  $KANBAN ls 2>/dev/null | grep '^\⊘'
  echo ""
  for task_id in $($KANBAN ls 2>/dev/null | grep '^\⊘' | awk '{print $1}' | sed 's/⊘//'); do
    echo "  $task_id:"
    $KANBAN show "$task_id" 2>/dev/null | grep -A2 "error\|Diagnostic" | head -5
  done
  exit 0
fi

# ── Dispatch if under concurrency limit ───────────────────────────
if [ "$RUNNING" -lt "$MAX_RUNNING" ]; then
  if [ "$TODO" -gt 0 ]; then
    echo "Dispatching — $RUNNING running, $TODO todo, capacity available ($MAX_RUNNING max)"
    $KANBAN dispatch 2>/dev/null
    echo ""
    $KANBAN ls 2>/dev/null | tail -6
  fi
fi

# Silent if at capacity or nothing to dispatch
exit 0
