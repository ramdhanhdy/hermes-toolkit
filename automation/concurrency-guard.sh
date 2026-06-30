#!/usr/bin/env bash
# concurrency-guard.sh — check if we have capacity for a new LLM agent.
# Usage: ./concurrency-guard.sh <max_agents>
# Exit 0 if OK to proceed, exit 1 if at capacity.
#
# Counts active LLM agents:
#   - Kanban workers (running state)
#   - Background delegate_task processes
#   - This script itself doesn't count (it's a script, not an LLM agent)
#
# Leaves headroom for the main chat session (1 slot always reserved).

set -euo pipefail

MAX="${1:-3}"  # default: 3 agents max (leaves 1 slot for chat on 4-limit plan)

KANBAN="${HERMES_BIN:-hermes} kanban"

# Count running kanban tasks
KANBAN_RUNNING=$($KANBAN ls 2>/dev/null | grep -c '^\●' 2>/dev/null || true)
KANBAN_RUNNING=${KANBAN_RUNNING:-0}

# Count active hermes agent processes (exclude this script, exclude cron scripts)
AGENT_PIDS=$(pgrep -f "hermes.*-p.*researcher\|hermes.*-p.*synthesizer\|hermes.*-p.*judge\|hermes.*chat.*--resume" 2>/dev/null | wc -l || true)
AGENT_PIDS=${AGENT_PIDS:-0}

# Total active LLM agents
TOTAL=$((KANBAN_RUNNING + AGENT_PIDS))

if [ "$TOTAL" -ge "$MAX" ]; then
  echo "AT_CAPACITY: $TOTAL agents running (kanban=$KANBAN_RUNNING, processes=$AGENT_PIDS), limit=$MAX"
  exit 1
else
  echo "OK: $TOTAL agents running (kanban=$KANBAN_RUNNING, processes=$AGENT_PIDS), limit=$MAX"
  exit 0
fi
