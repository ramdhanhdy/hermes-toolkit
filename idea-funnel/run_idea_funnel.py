#!/usr/bin/env python3
"""Manual idea-funnel run orchestrator.

This wires the deterministic source prefetcher into future idea-funnel kanban
runs. It uses one unique kanban board per run and keeps the trigger manual for
now: run this script when you want a new idea-funnel cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable, Sequence
import argparse
import json
import os
import re
import subprocess
import sys
import time

IDEAS_ROOT = Path(os.environ.get("IDEAS_ROOT", "/opt/data/ideas"))
HERMES_BIN = os.environ.get("HERMES_BIN", "hermes")
CORE_SOURCES = ("github", "hackernews", "arxiv")
TERMINAL_STATUSES = {"done", "blocked", "archived"}
FAILED_STATUSES = {"blocked", "failed"}


@dataclass(frozen=True)
class TaskSpec:
    key: str
    title: str
    assignee: str
    body: str
    parents: list[str]
    max_runtime: str = "2h"


def default_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dt%H%M%SZ")


def make_board_slug(run_id: str) -> str:
    slug = run_id.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return f"idea-funnel-{slug or default_run_id()}"


def run_dir_for(ideas_root: Path, run_id: str) -> Path:
    return ideas_root / "runs" / run_id


def _common_inputs(run_id: str, ideas_root: Path) -> str:
    run_dir = run_dir_for(ideas_root, run_id)
    return f"""Run ID: `{run_id}`

Inputs:
- Wiki index: `{ideas_root}/wiki/index.md`
- Normalized source bundle: `{run_dir}/normalized/signals.jsonl`
- Source metrics: `{run_dir}/metrics.json`
- Source retrospective: `{run_dir}/retrospective.md`

Global rules:
- Read wiki/index.md first.
- Read signals.jsonl and filter to your assigned lanes.
- Use metrics.json to disclose degraded source lanes.
- Do NOT fetch sources from the web. Source acquisition has already happened.
- Do NOT modify `{ideas_root}/wiki/`; wiki-curator is the only writer.
- Every claim needs a source URL from signals.jsonl or a run artifact reference.
"""


def _researcher_body(run_id: str, ideas_root: Path, *, lanes: list[str], output: str, objective: str) -> str:
    lane_text = "\n".join(f"- `{lane}`" for lane in lanes)
    return f"""# {objective}

{_common_inputs(run_id, ideas_root)}

Assigned source lanes:
{lane_text}

Output:
- `{output}`

Acceptance criteria:
1. Analyze 8-12 strongest candidate signals from assigned lanes, or all available signals if fewer.
2. For each candidate, mark status as `new`, `delta`, `already_covered`, or `similar_to_dropped` based on the wiki.
3. Include source URL, source lane, short rationale, and build relevance for each candidate.
4. Explicitly mention degraded/missing lanes from metrics.json.
5. Avoid duplicate ideas already covered in wiki unless reporting a meaningful delta.

Do-not scope:
- Do NOT fetch sources.
- Do NOT write wiki pages.
- Do NOT produce final briefs; just discovery analysis.

Verification before completion:
- Re-read `{output}`.
- Confirm it contains source URLs and assigned-lane coverage.
- Call `kanban_complete` exactly once on success, or `kanban_block` with a concrete blocker.
"""


def build_task_specs(run_id: str, board_slug: str, ideas_root: Path = IDEAS_ROOT) -> list[TaskSpec]:
    run_dir = run_dir_for(ideas_root, run_id)
    discovery_dir = run_dir / "discovery"
    return [
        TaskSpec(
            key="github_hn",
            title=f"{run_id}: Analyze GitHub + Hacker News signals",
            assignee="researcher",
            parents=[],
            body=_researcher_body(
                run_id,
                ideas_root,
                lanes=[
                    "github_ai_agents",
                    "github_llm_tools",
                    "github_mcp",
                    "hn_ai_agents",
                    "hn_llm_tools",
                    "hn_mcp",
                    "hn_show_hn_agents",
                ],
                output=str(discovery_dir / "github-hn.md"),
                objective="Analyze GitHub and Hacker News idea-funnel signals",
            ),
        ),
        TaskSpec(
            key="reddit_arxiv",
            title=f"{run_id}: Analyze Reddit + ArXiv signals",
            assignee="researcher",
            parents=[],
            body=_researcher_body(
                run_id,
                ideas_root,
                lanes=["r/LocalLLaMA", "r/MachineLearning", "r/artificial", "agent_tools", "agent_memory", "mcp_security", "context_compaction"],
                output=str(discovery_dir / "reddit-arxiv.md"),
                objective="Analyze Reddit and ArXiv idea-funnel signals",
            ),
        ),
        TaskSpec(
            key="huggingface",
            title=f"{run_id}: Analyze Hugging Face signals",
            assignee="researcher",
            parents=[],
            body=_researcher_body(
                run_id,
                ideas_root,
                lanes=["hf_trending_models", "hf_spaces", "hf_daily_papers"],
                output=str(discovery_dir / "huggingface.md"),
                objective="Analyze Hugging Face models, spaces, and Daily Papers signals",
            ),
        ),
        TaskSpec(
            key="verifier",
            title=f"{run_id}: Verify discovery outputs and filter candidates",
            assignee="judge",
            parents=["github_hn", "reddit_arxiv", "huggingface"],
            body=f"""# Verify idea-funnel discovery outputs

{_common_inputs(run_id, ideas_root)}

Inputs to verify:
- `{discovery_dir}/github-hn.md`
- `{discovery_dir}/reddit-arxiv.md`
- `{discovery_dir}/huggingface.md`

Output:
- `{run_dir}/verification.md`

Acceptance criteria:
1. Check every discovery output exists and cites source URLs.
2. Check researchers did not fetch raw sources or write wiki pages.
3. Confirm each proposed candidate is traceable to signals.jsonl or a run artifact.
4. Filter candidates into: `survives`, `watchlist`, `drop`, `needs_more_evidence`.
5. Complete only if evidence is sufficient for synthesis; otherwise block with exact missing work.

Completion protocol:
- If pass: write verification.md and call `kanban_complete`.
- If fail: call `kanban_block` and name the missing artifact/evidence.
""",
        ),
        TaskSpec(
            key="synthesizer",
            title=f"{run_id}: Synthesize verified idea briefs",
            assignee="synthesizer",
            parents=["verifier"],
            body=f"""# Synthesize verified idea-funnel briefs

{_common_inputs(run_id, ideas_root)}

Inputs:
- `{run_dir}/verification.md`
- `{discovery_dir}/github-hn.md`
- `{discovery_dir}/reddit-arxiv.md`
- `{discovery_dir}/huggingface.md`

Outputs:
- `{run_dir}/briefs.md`
- Optional: `{run_dir}/briefs.docx` if easy and supported by existing tooling.

Acceptance criteria:
1. Produce 1-3 decision-ready build briefs, each under 400 words.
2. Tie every evidence claim to source URLs or run artifacts.
3. Connect candidates to prior wiki concepts/entities when relevant.
4. Include dropped/watchlist candidates in a short appendix so wiki-curator can record them.
5. Do NOT write wiki pages.

Completion protocol:
- Re-read briefs.md before completion.
- Call `kanban_complete` exactly once on success, or `kanban_block` with a concrete blocker.
""",
        ),
        TaskSpec(
            key="judge",
            title=f"{run_id}: Final judge gate for briefs",
            assignee="judge",
            parents=["synthesizer"],
            body=f"""# Final judge gate for idea-funnel briefs

{_common_inputs(run_id, ideas_root)}

Inputs:
- `{run_dir}/briefs.md`
- `{run_dir}/verification.md`
- source metrics and discovery artifacts

Output:
- `{run_dir}/judge-report.md`

Acceptance criteria:
1. Verify briefs are evidence-backed and not duplicates of existing wiki ideas unless they contain deltas.
2. Verify source degradation is disclosed.
3. Verify the selected ideas have a concrete Python-buildable angle and AI-company relevance.
4. If briefs are not good enough, block; do not complete and let wiki-curator ingest bad data.

Completion protocol:
- If pass: write judge-report.md with `Gate: PASS`, then `kanban_complete`.
- If fail: write exact reasons, then `kanban_block`.
""",
        ),
        TaskSpec(
            key="wiki_curator",
            title=f"{run_id}: Curate run into ideas wiki",
            assignee="wiki-curator",
            parents=["judge"],
            body=f"""# Curate completed idea-funnel run into wiki

You are the only writer to `{ideas_root}/wiki/` for this run.

Inputs:
- `{run_dir}/briefs.md`
- `{run_dir}/judge-report.md`
- `{run_dir}/verification.md`
- `{run_dir}/normalized/signals.jsonl`
- `{run_dir}/metrics.json`
- `{ideas_root}/wiki/index.md`
- `{ideas_root}/manifest.json`

Outputs:
- Updated `{ideas_root}/wiki/index.md`
- Updated entity/concept/idea/dropped/watchlist/source pages as needed
- Updated `{ideas_root}/wiki/log.md`
- Updated `{ideas_root}/manifest.json`
- `{run_dir}/curation-report.md`

Acceptance criteria:
1. Preserve provenance: run_id, task_id where available, source URL, source lane.
2. Deduplicate entities and concepts before creating pages.
3. Record dropped/rejected ideas so future researchers do not rediscover them.
4. Update `Do not repeat` sections for covered entities/ideas.
5. Update run metrics with wiki self-improvement fields where possible.

Completion protocol:
- Re-read curation-report.md and wiki/index.md.
- Call `kanban_complete` exactly once on success, or `kanban_block` with a concrete blocker.
""",
            max_runtime="3h",
        ),
        TaskSpec(
            key="search_strategist",
            title=f"{run_id}: Generate search terms for next run",
            assignee="search-strategist",
            parents=["wiki_curator"],
            body=f"""# Generate search terms for next idea-funnel run

You are the search strategist. You generate search queries for the next run's source prefetcher.

Inputs:
- `{ideas_root}/wiki/index.md` — current wiki state
- `{ideas_root}/wiki/log.md` — recent changes
- `{run_dir}/metrics.json` — source health from the run just completed
- `{run_dir}/retrospective.md` — source reliability notes
- `{run_dir}/curation-report.md` — what the wiki-curator just did
- Previous run's `search-terms.json` (if any, search `{ideas_root}/runs/*/search-terms.json`)

Output:
- `{run_dir}/search-terms.json`

Read your SOUL.md for the full schema and rules.

Key points:
- Use correct platform syntax (GitHub operators, ArXiv boolean, HN plain text)
- `{{since}}` is a placeholder in GitHub queries — the adapter replaces it
- Do NOT include huggingface — it uses API endpoints, not search terms
- 3-6 lanes per adapter is the sweet spot
- Be creative: use community vocabulary, not academic phrasing
- Do NOT modify the wiki

Completion protocol:
- Re-read search-terms.json and confirm it's valid JSON with all required adapter keys.
- Call `kanban_complete` exactly once on success, or `kanban_block` with a concrete blocker.
""",
            max_runtime="30m",
        ),
    ]


def validate_source_metrics(metrics: dict, *, min_total_signals: int = 20, core_sources: Sequence[str] = CORE_SOURCES) -> list[str]:
    errors: list[str] = []
    total = int(metrics.get("total_signals") or 0)
    sources = metrics.get("sources") or {}
    if total < min_total_signals:
        errors.append(f"total_signals={total} is below required minimum {min_total_signals}")
    core_failed = []
    for source in core_sources:
        status = (sources.get(source) or {}).get("status")
        if status not in {"ok", "degraded"}:
            core_failed.append(source)
    if len(core_failed) == len(tuple(core_sources)):
        errors.append(f"all core sources failed: {', '.join(core_failed)}")
    return errors


def run_command(argv: Sequence[str], *, cwd: Path | None = None) -> str:
    proc = subprocess.run(list(argv), cwd=str(cwd) if cwd else None, text=True, capture_output=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            "Command failed:\n"
            + " ".join(str(a) for a in argv)
            + f"\nexit={proc.returncode}\nstdout={proc.stdout}\nstderr={proc.stderr}"
        )
    return proc.stdout


class KanbanClient:
    def __init__(self, *, hermes_bin: str = HERMES_BIN, runner: Callable[..., str] = run_command):
        self.hermes_bin = hermes_bin
        self.runner = runner

    def _kanban(self, *args: str, board_slug: str | None = None) -> str:
        argv = [self.hermes_bin, "kanban"]
        if board_slug:
            argv.extend(["--board", board_slug])
        argv.extend(args)
        return self.runner(argv, cwd=Path(os.environ.get("HERMES_HOME", os.getcwd())))

    def create_pipeline(self, *, board_slug: str, run_id: str, specs: Iterable[TaskSpec]) -> dict[str, str]:
        run_dir = run_dir_for(IDEAS_ROOT, run_id)
        self.runner(
            [
                self.hermes_bin,
                "kanban",
                "boards",
                "create",
                board_slug,
                "--name",
                f"Idea Funnel {run_id}",
                "--description",
                f"Idea-funnel run {run_id}; deterministic source bundle under {run_dir}",
                "--icon",
                "🧪",
                "--color",
                "#8b5cf6",
                "--switch",
                "--default-workdir",
                str(run_dir / "workspaces"),
            ],
            cwd=Path(os.environ.get("HERMES_HOME", os.getcwd())),
        )
        task_ids: dict[str, str] = {}
        specs = list(specs)
        for spec in specs:
            out = self._kanban(
                "create",
                spec.title,
                "--body",
                spec.body,
                "--workspace",
                "scratch",
                "--max-runtime",
                spec.max_runtime,
                "--created-by",
                "idea-funnel-runner",
                "--idempotency-key",
                f"{board_slug}:{run_id}:{spec.key}",
                "--initial-status",
                "blocked",
                "--json",
                board_slug=board_slug,
            )
            task_ids[spec.key] = json.loads(out)["id"]
        for spec in specs:
            for parent_key in spec.parents:
                self._kanban("link", task_ids[parent_key], task_ids[spec.key], board_slug=board_slug)
        # `--initial-status blocked` alone is not sticky: Hermes' recompute_ready
        # can promote parentless blocked tasks because no explicit `blocked`
        # event exists. Emit a real block event before assigning profiles so the
        # gateway dispatcher cannot auto-spawn prepare-only boards.
        for spec in specs:
            self._kanban(
                "block",
                "--kind",
                "needs_input",
                task_ids[spec.key],
                "prepared by idea-funnel runner; assign and unblock only when dispatching",
                board_slug=board_slug,
            )
        return task_ids

    def activate_specs(self, *, board_slug: str, task_ids: dict[str, str], specs: Iterable[TaskSpec], keys: Iterable[str]) -> list[str]:
        spec_by_key = {spec.key: spec for spec in specs}
        selected = [spec_by_key[key] for key in keys if key in spec_by_key]
        ids = [task_ids[spec.key] for spec in selected]
        if not ids:
            return []
        for spec in selected:
            self._kanban("assign", task_ids[spec.key], spec.assignee, board_slug=board_slug)
        self._kanban(
            "unblock",
            *ids,
            "--reason",
            "idea-funnel runner activating eligible task after dependency/slot check",
            board_slug=board_slug,
        )
        return ids

    def activate_roots(self, *, board_slug: str, task_ids: dict[str, str], specs: Iterable[TaskSpec], limit: int | None = None) -> list[str]:
        root_keys = [spec.key for spec in specs if not spec.parents]
        if limit is not None:
            root_keys = root_keys[: max(0, limit)]
        return self.activate_specs(board_slug=board_slug, task_ids=task_ids, specs=specs, keys=root_keys)

    def dispatch(self, *, board_slug: str, max_active_workers: int, dry_run: bool = False) -> str:
        args = ["dispatch", "--max", str(max_active_workers), "--json"]
        if dry_run:
            args.append("--dry-run")
        return self._kanban(*args, board_slug=board_slug)

    def list_tasks(self, *, board_slug: str) -> list[dict]:
        out = self._kanban("list", "--json", board_slug=board_slug)
        data = json.loads(out or "[]")
        return data if isinstance(data, list) else []


def run_prefetch(*, run_id: str, ideas_root: Path, limit: int, timeout: int, python_bin: str = sys.executable) -> None:
    fetch_script = ideas_root / "fetch_sources.py"
    run_command([python_bin, str(fetch_script), "--run-id", run_id, "--limit", str(limit), "--timeout", str(timeout)], cwd=ideas_root)


def load_metrics(run_id: str, ideas_root: Path) -> dict:
    metrics_path = run_dir_for(ideas_root, run_id) / "metrics.json"
    return json.loads(metrics_path.read_text(encoding="utf-8"))


def write_orchestration_manifest(run_id: str, board_slug: str, task_ids: dict[str, str], specs: list[TaskSpec], ideas_root: Path) -> Path:
    run_dir = run_dir_for(ideas_root, run_id)
    path = run_dir / "orchestration.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "run_id": run_id,
        "board_slug": board_slug,
        "created_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "task_ids": task_ids,
        "graph": {spec.key: spec.parents for spec in specs},
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def status_counts(tasks: Iterable[dict]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in tasks:
        status = str(task.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def eligible_specs_to_activate(tasks: Iterable[dict], specs: Iterable[TaskSpec], task_ids: dict[str, str], *, slots: int) -> list[str]:
    if slots <= 0:
        return []
    tasks_by_id = {str(task.get("id")): task for task in tasks}
    out: list[str] = []
    for spec in specs:
        task_id = task_ids.get(spec.key)
        task = tasks_by_id.get(str(task_id))
        if not task:
            continue
        status = str(task.get("status") or "")
        assignee = task.get("assignee")
        if assignee:
            continue
        if status in {"done", "archived"} or status == "running":
            continue
        parents_ready = True
        for parent_key in spec.parents:
            parent_id = task_ids.get(parent_key)
            parent = tasks_by_id.get(str(parent_id))
            if not parent or str(parent.get("status")) not in {"done", "archived"}:
                parents_ready = False
                break
        if not parents_ready:
            continue
        out.append(spec.key)
        if len(out) >= slots:
            break
    return out


def monitor_until_terminal(
    client: KanbanClient,
    *,
    board_slug: str,
    run_id: str,
    task_ids: dict[str, str],
    specs: list[TaskSpec],
    max_active_workers: int,
    poll_seconds: int,
    max_minutes: int,
) -> int:
    started = time.time()
    deadline = started + max_minutes * 60
    while True:
        tasks = client.list_tasks(board_slug=board_slug)
        counts = status_counts(tasks)
        elapsed = int(time.time() - started)
        print(f"ORCHESTRATOR_PROGRESS run_id={run_id} board={board_slug} elapsed_s={elapsed} statuses={counts}", flush=True)
        if tasks and all(str(t.get("status")) in TERMINAL_STATUSES for t in tasks):
            if any(str(t.get("status")) in FAILED_STATUSES for t in tasks):
                print(f"PIPELINE_BLOCKED run_id={run_id} board={board_slug} statuses={counts}", flush=True)
                return 3
            print(f"PIPELINE_COMPLETE run_id={run_id} board={board_slug}", flush=True)
            return 0
        if time.time() >= deadline:
            print(f"PIPELINE_TIMEOUT run_id={run_id} board={board_slug} max_minutes={max_minutes}", flush=True)
            return 4
        running = counts.get("running", 0)
        slots = max(0, max_active_workers - running)
        if slots:
            keys = eligible_specs_to_activate(tasks, specs, task_ids, slots=slots)
            if keys:
                activated = client.activate_specs(board_slug=board_slug, task_ids=task_ids, specs=specs, keys=keys)
                print(f"ORCHESTRATOR_PROGRESS run_id={run_id} board={board_slug} activated={keys} task_ids={activated}", flush=True)
                slots = min(slots, len(activated))
            if slots:
                client.dispatch(board_slug=board_slug, max_active_workers=slots, dry_run=False)
        time.sleep(poll_seconds)


def print_plan(run_id: str, board_slug: str, specs: list[TaskSpec], ideas_root: Path) -> None:
    print(json.dumps({
        "run_id": run_id,
        "board_slug": board_slug,
        "run_dir": str(run_dir_for(ideas_root, run_id)),
        "tasks": [
            {"key": s.key, "title": s.title, "assignee": s.assignee, "parents": s.parents, "max_runtime": s.max_runtime}
            for s in specs
        ],
    }, ensure_ascii=False, indent=2), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Manual idea-funnel runner: prefetch sources, create unique board, dispatch kanban pipeline")
    parser.add_argument("--run-id", default=None, help="Run ID under <ideas-root>/runs/. Defaults to UTC timestamp.")
    parser.add_argument("--ideas-root", default=str(IDEAS_ROOT))
    parser.add_argument("--hermes-bin", default=HERMES_BIN)
    parser.add_argument("--limit", type=int, default=20, help="Per-lane source adapter limit")
    parser.add_argument("--timeout", type=int, default=20, help="Source adapter HTTP timeout")
    parser.add_argument("--min-total-signals", type=int, default=20)
    parser.add_argument("--max-active-workers", type=int, default=2)
    parser.add_argument("--poll-seconds", type=int, default=60)
    parser.add_argument("--max-minutes", type=int, default=180)
    parser.add_argument("--dry-run", action="store_true", help="Print plan only; no fetch, no board creation, no dispatch")
    parser.add_argument("--skip-fetch", action="store_true", help="Use existing metrics/signals for this run_id")
    parser.add_argument("--prepare-only", action="store_true", help="Fetch and create board/tasks/links, but do not dispatch workers")
    parser.add_argument("--no-monitor", action="store_true", help="Dispatch once and exit instead of polling until terminal state")
    parser.add_argument("--dispatch-dry-run", action="store_true", help="Create board/tasks but run kanban dispatch --dry-run")
    args = parser.parse_args(argv)

    ideas_root = Path(args.ideas_root)
    run_id = args.run_id or default_run_id()
    board_slug = make_board_slug(run_id)
    specs = build_task_specs(run_id=run_id, board_slug=board_slug, ideas_root=ideas_root)

    if args.dry_run:
        print_plan(run_id, board_slug, specs, ideas_root)
        return 0

    if not args.skip_fetch:
        print(f"SOURCE_PREFETCH_START run_id={run_id}", flush=True)
        run_prefetch(run_id=run_id, ideas_root=ideas_root, limit=args.limit, timeout=args.timeout)
        print(f"SOURCE_PREFETCH_DONE run_id={run_id}", flush=True)

    metrics = load_metrics(run_id, ideas_root)
    errors = validate_source_metrics(metrics, min_total_signals=args.min_total_signals)
    if errors:
        for error in errors:
            print(f"SOURCE_PREFETCH_INVALID run_id={run_id} error={error}", flush=True)
        return 2

    client = KanbanClient(hermes_bin=args.hermes_bin)
    print(f"KANBAN_CREATE_START run_id={run_id} board={board_slug}", flush=True)
    task_ids = client.create_pipeline(board_slug=board_slug, run_id=run_id, specs=specs)
    manifest_path = write_orchestration_manifest(run_id, board_slug, task_ids, specs, ideas_root)
    print(f"KANBAN_CREATE_DONE run_id={run_id} board={board_slug} manifest={manifest_path}", flush=True)

    if args.prepare_only:
        print(f"PIPELINE_PREPARED run_id={run_id} board={board_slug}", flush=True)
        return 0

    if args.dispatch_dry_run:
        print(f"KANBAN_DISPATCH_DRY_RUN_START run_id={run_id} board={board_slug} max_active_workers={args.max_active_workers}", flush=True)
        client.dispatch(board_slug=board_slug, max_active_workers=args.max_active_workers, dry_run=True)
        print(f"PIPELINE_DISPATCH_DRY_RUN run_id={run_id} board={board_slug} note=all_tasks_remain_blocked_until_real_dispatch", flush=True)
        return 0

    print(f"KANBAN_ACTIVATE_ROOTS run_id={run_id} board={board_slug} max_active_workers={args.max_active_workers}", flush=True)
    client.activate_roots(board_slug=board_slug, task_ids=task_ids, specs=specs, limit=args.max_active_workers)

    print(f"KANBAN_DISPATCH_START run_id={run_id} board={board_slug} max_active_workers={args.max_active_workers}", flush=True)
    client.dispatch(board_slug=board_slug, max_active_workers=args.max_active_workers, dry_run=False)
    if args.no_monitor:
        print(f"PIPELINE_DISPATCHED run_id={run_id} board={board_slug}", flush=True)
        return 0
    return monitor_until_terminal(
        client,
        board_slug=board_slug,
        run_id=run_id,
        task_ids=task_ids,
        specs=specs,
        max_active_workers=args.max_active_workers,
        poll_seconds=args.poll_seconds,
        max_minutes=args.max_minutes,
    )


if __name__ == "__main__":
    raise SystemExit(main())
