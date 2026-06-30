#!/usr/bin/env python3
"""Kanban pipeline orchestrator — monitors wiki-graph board, handles crashes,
blocks, and completion. Uses GPT-5.5 (openai-codex) for decisions — uncapped.

Polls every 60s. On events, calls the orchestrator profile for a decision.
Notifies via stdout (captured by Hermes background process notification).
"""
import json
import subprocess
import time
import os
import sys
import logging
from datetime import datetime

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [ORCHESTRATOR] %(message)s',
    stream=sys.stdout,
)
log = logging.getLogger(__name__)

HERMES = "os.environ.get("HERMES_BIN", "hermes")"
BOARD = "wiki-graph"
POLL_INTERVAL = 60  # seconds
MAX_RETRIES = 3
TASK_CHAIN = [
    "t_3aae2993",  # T1: architect — spec
    "t_2cab7b54",  # T2: coder — parser + core graph
    "t_f299160e",  # T3: visual-design — aesthetic polish
    "t_2419f251",  # T4: structure-design — UX features
    "t_79cf4948",  # T5: minimal-design — final polish
    "t_727685a1",  # Judge — verify
]

# Track retry counts per task
retry_counts = {tid: 0 for tid in TASK_CHAIN}
# Track last known status
last_status = {tid: None for tid in TASK_CHAIN}
# Emit Telegram-visible progress at most every 5 minutes
last_progress_emit = 0
PROGRESS_INTERVAL = 300


def run_cmd(cmd, timeout=30):
    """Run a shell command, return (success, output)."""
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode == 0, r.stdout.strip() or r.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "TIMEOUT"
    except Exception as e:
        return False, str(e)


def get_task_status(task_id):
    """Get the current status of a task."""
    ok, out = run_cmd(f"{HERMES} kanban --board {BOARD} show {task_id} --json")
    if not ok:
        return None
    try:
        data = json.loads(out)
        return data.get("status")
    except json.JSONDecodeError:
        return None


def get_task_log(task_id, lines=10):
    """Get the last N lines of a task's log."""
    ok, out = run_cmd(f"{HERMES} kanban --board {BOARD} log {task_id} 2>&1 | tail -{lines}")
    return out if ok else "unable to read log"


def get_all_statuses():
    """Get status of all tasks in the chain."""
    ok, out = run_cmd(f"{HERMES} kanban --board {BOARD} list --json 2>&1")
    if not ok:
        return {}
    try:
        data = json.loads(out)
        statuses = {}
        tasks = data.get("tasks", data) if isinstance(data, dict) else data
        for task in tasks:
            statuses[task["id"]] = task["status"]
        return statuses
    except (json.JSONDecodeError, KeyError, TypeError):
        return {}


def emit_progress(statuses, reason="periodic"):
    """Emit progress marker for background watch_patterns."""
    labels = {
        "t_3aae2993": "T1 spec",
        "t_2cab7b54": "T2 parser",
        "t_f299160e": "T3 visual",
        "t_2419f251": "T4 UX",
        "t_79cf4948": "T5 polish",
        "t_727685a1": "Judge",
    }
    parts = []
    for tid in TASK_CHAIN:
        parts.append(f"{labels.get(tid, tid)}={statuses.get(tid, 'unknown')}")
    print(f"ORCHESTRATOR_PROGRESS reason={reason} | " + " | ".join(parts), flush=True)


def ask_orchestrator(prompt):
    """Call the orchestrator profile (GPT-5.5) with a decision prompt."""
    ok, out = run_cmd(
        f'{HERMES} -p orchestrator -z {repr(prompt)} --yolo 2>&1',
        timeout=120,
    )
    return out if ok else f"ORCHESTRATOR_FAILED: {out}"


def dispatch_task(task_id, provider=None, model=None):
    """Dispatch (or re-dispatch) a task.
    
    Note: `hermes kanban dispatch` dispatches ALL ready tasks — it doesn't take
    a task ID. We rely on the serial chain links to auto-advance tasks to 'ready'
    when their predecessor completes. For re-dispatch after crash, we unblock
    first, then dispatch.
    """
    # Unblock if blocked
    run_cmd(f"{HERMES} kanban --board {BOARD} unblock {task_id}")
    # Dispatch all ready tasks (the kanban daemon handles assignment)
    cmd = f"{HERMES} kanban --board {BOARD} dispatch"
    ok, out = run_cmd(cmd)
    log.info(f"Dispatched (board-wide): ok={ok} out={out[:100]}")
    return ok


def advance_chain(task_id):
    """If a task is done, dispatch the next one in the chain."""
    idx = TASK_CHAIN.index(task_id)
    if idx + 1 < len(TASK_CHAIN):
        next_task = TASK_CHAIN[idx + 1]
        log.info(f"Task {task_id} done — advancing to {next_task}")
        dispatch_task(next_task)
    else:
        log.info(f"Task {task_id} done — this is the last task (judge). Pipeline complete!")
        print(f"\nPIPELINE_COMPLETE All tasks finished.", flush=True)
        print(f"[ORCHESTRATOR] Final deliverable: <wiki-root>/graph.html", flush=True)
        print(f"[ORCHESTRATOR] Verification report: <wiki-root>/verification.md", flush=True)
        sys.exit(0)


def handle_crash(task_id):
    """Handle a crashed task — retry or switch provider."""
    retries = retry_counts.get(task_id, 0)
    log_tail = get_task_log(task_id, lines=5)

    if retries < 2:
        # Retry on same provider
        retry_counts[task_id] = retries + 1
        log.info(f"Task {task_id} crashed (retry {retries + 1}/{MAX_RETRIES}) — retrying on umans")
        dispatch_task(task_id)
    elif retries < MAX_RETRIES:
        # Switch to GPT-5.5
        retry_counts[task_id] = retries + 1
        log.info(f"Task {task_id} crashed (retry {retries + 1}/{MAX_RETRIES}) — switching to GPT-5.5")
        # Ask orchestrator for confirmation
        prompt = f"Task {task_id} crashed {retries} times on umans/glm-5.2. Log tail: {log_tail}. Switching to openai-codex/gpt-5.5. Confirm?"
        decision = ask_orchestrator(prompt)
        log.info(f"Orchestrator decision: {decision[:200]}")
        dispatch_task(task_id, provider="openai-codex", model="gpt-5.5")
    else:
        # Max retries — escalate
        log.error(f"Task {task_id} failed after {MAX_RETRIES} retries. Escalating.")
        prompt = f"Task {task_id} failed after {MAX_RETRIES} retries. Last error: {log_tail}. Pipeline is blocked. What should we tell the user?"
        decision = ask_orchestrator(prompt)
        print(f"\nPIPELINE_BLOCKED Task {task_id} failed after {MAX_RETRIES} retries.", flush=True)
        print(f"[ORCHESTRATOR] Decision: {decision[:500]}", flush=True)
        sys.exit(1)


def handle_block(task_id):
    """Handle a blocked task — ask orchestrator for diagnosis."""
    log_tail = get_task_log(task_id, lines=10)
    log.info(f"Task {task_id} is blocked. Asking orchestrator for diagnosis...")

    prompt = (
        f"Task {task_id} on the wiki-graph kanban board is blocked. "
        f"Log tail:\n{log_tail}\n\n"
        f"Decide: should we retry with patched instructions, switch to GPT-5.5, or escalate?"
    )
    decision = ask_orchestrator(prompt)
    log.info(f"Orchestrator decision: {decision[:300]}")

    # Parse decision — simple heuristic
    decision_lower = decision.lower()
    if "switch" in decision_lower or "gpt-5.5" in decision_lower:
        dispatch_task(task_id, provider="openai-codex", model="gpt-5.5")
    elif "retry" in decision_lower:
        dispatch_task(task_id)
    else:
        print(f"\nPIPELINE_BLOCKED Task {task_id} blocked; escalation recommended.", flush=True)
        print(f"[ORCHESTRATOR] Decision: {decision[:500]}", flush=True)
        sys.exit(1)


def main():
    global last_progress_emit
    log.info("=" * 60)
    log.info("Wiki Graph Pipeline Orchestrator")
    log.info(f"Board: {BOARD}")
    log.info(f"Chain: {' → '.join(TASK_CHAIN)}")
    log.info(f"Poll interval: {POLL_INTERVAL}s")
    log.info(f"Max retries: {MAX_RETRIES}")
    log.info("=" * 60)

    # Main monitoring loop — don't dispatch T1, it's already running
    log.info("Monitoring existing pipeline (T3 running)...")

    # Main monitoring loop
    while True:
        time.sleep(POLL_INTERVAL)

        statuses = get_all_statuses()
        if not statuses:
            log.warning("Could not get task statuses — retrying next cycle")
            continue

        now = time.time()
        if now - last_progress_emit >= PROGRESS_INTERVAL:
            emit_progress(statuses, reason="periodic")
            last_progress_emit = now

        for task_id in TASK_CHAIN:
            current = statuses.get(task_id, "unknown")

            # Skip if status unchanged
            if current == last_status[task_id]:
                continue

            log.info(f"Task {task_id}: {last_status[task_id]} → {current}")
            last_status[task_id] = current
            emit_progress(statuses, reason=f"status_change:{task_id}:{current}")
            last_progress_emit = time.time()

            if current == "done":
                advance_chain(task_id)
            elif current == "failed":
                handle_crash(task_id)
            elif current == "blocked":
                handle_block(task_id)

        # Check if all tasks are done
        all_done = all(
            statuses.get(tid, "") == "done" for tid in TASK_CHAIN
        )
        if all_done:
            log.info("All tasks complete! Pipeline finished successfully.")
            # Ask orchestrator for summary
            prompt = (
                "Pipeline complete. All 6 tasks done. "
                "Summarize what was built for the user. "
                "Deliverable is at <wiki-root>/graph.html"
            )
            summary = ask_orchestrator(prompt)
            print(f"\n[ORCHESTRATOR] Pipeline complete!")
            print(f"[ORCHESTRATOR] Summary: {summary[:1000]}")
            sys.exit(0)


if __name__ == "__main__":
    main()
