#!/usr/bin/env bash
# kanban-watchdog.sh — Detects and retries 1-message crash sessions
# 
# Problem: When a kanban worker crashes with "pid not alive" after only 1 message
# (the initial "work kanban task t_XXXX" prompt), it's a provider/connection issue,
# not a model intelligence issue. The dispatcher should retry these automatically.
#
# This script checks for recently crashed tasks where the worker never made a
# tool call, and promotes them back to ready for retry.
#
# Run via cron every 5 minutes.

set -euo pipefail

HERMES="${HERMES_BIN:-hermes}"
BOARDS=(${KANBAN_BOARDS:-"default"})
MAX_AUTO_RETRIES=5          # Max auto-retries per task before giving up
PROVIDER_SWITCH_AFTER=2    # After N consecutive early crashes, log warning (manual escalation)
PROVIDER_SWITCH_MSG=""
RETRY_COUNT_FILE="/tmp/kanban-watchdog-retries.txt"

for board in "${BOARDS[@]}"; do
  # Get all tasks with recent crashed runs
  tasks=$($HERMES kanban --board "$board" ls 2>/dev/null | grep -E "crashed|timed_out" | awk '{print $2}')
  
  for task_id in $tasks; do
    # Check retry count for this task
    retry_count=$(grep -c "$task_id" "$RETRY_COUNT_FILE" 2>/dev/null || echo 0)
    
    if [ "$retry_count" -ge "$MAX_AUTO_RETRIES" ]; then
      echo "[$(date -u +%H:%M:%S)] Board=$board Task=$task_id: MAX_RETRIES ($MAX_AUTO_RETRIES) exceeded, leaving blocked"
      continue
    fi
    
    # Check the last run for this task
    runs=$($HERMES kanban --board "$board" runs "$task_id" --json 2>/dev/null)
    if [ -z "$runs" ]; then
      continue
    fi
    
    # Extract last run outcome and elapsed
    last_run=$(echo "$runs" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin)
    if data:
        r = data[-1]
        outcome = r.get('outcome', '')
        elapsed = r.get('elapsed_seconds', 0) or 0
        # 1-message crash = elapsed < 120s and outcome is crashed
        if outcome in ('crashed',) and elapsed < 120:
            print('retry')
        else:
            print('skip')
except:
    print('skip')
" 2>/dev/null)
    
    if [ "$last_run" = "retry" ]; then
      # Log the retry
      echo "$task_id" >> "$RETRY_COUNT_FILE"
      new_count=$((retry_count + 1))
      
      # Check for consecutive early crashes (provider issue indicator)
      if [ "$new_count" -ge "$PROVIDER_SWITCH_AFTER" ]; then
        PROVIDER_SWITCH_MSG="WARNING: $new_count consecutive early crashes on $task_id — possible provider issue"
      fi
      
      echo "[$(date -u +%H:%M:%S)] Board=$board Task=$task_id: 1-message crash detected (retry $new_count/$MAX_AUTO_RETRIES), promoting to ready"
      $HERMES kanban --board "$board" promote "$task_id" 2>/dev/null || true
      
      if [ -n "$PROVIDER_SWITCH_MSG" ]; then
        echo "[$(date -u +%H:%M:%S)] $PROVIDER_SWITCH_MSG"
        PROVIDER_SWITCH_MSG=""
      fi
    fi
  done
done

# Clean up retry count file entries older than 1 hour
if [ -f "$RETRY_COUNT_FILE" ]; then
  find /tmp -name "kanban-watchdog-retries.txt" -mmin +60 -delete 2>/dev/null || true
fi
