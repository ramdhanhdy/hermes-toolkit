import json
import os
import tempfile
import unittest
from pathlib import Path

from run_idea_funnel import (
    CORE_SOURCES,
    KanbanClient,
    build_task_specs,
    make_board_slug,
    validate_source_metrics,
    eligible_specs_to_activate,
)
from source_adapters.search_terms import load_search_terms, DEFAULTS


class FakeCommandRunner:
    def __init__(self):
        self.commands = []
        self.created = 0

    def __call__(self, argv, *, cwd=None):
        self.commands.append(list(argv))
        if "create" in argv and "--json" in argv:
            self.created += 1
            return json.dumps({"id": f"t_fake_{self.created}"})
        if "list" in argv and "--json" in argv:
            return "[]"
        return ""


class IdeaFunnelRunnerTests(unittest.TestCase):
    def test_unique_board_slug_is_stable_and_prefixed(self):
        self.assertEqual(make_board_slug("2026-06-29T102032Z"), "idea-funnel-2026-06-29t102032z")
        self.assertEqual(make_board_slug("Run 3 / HF+Reddit"), "idea-funnel-run-3-hf-reddit")

    def test_validate_source_metrics_allows_degraded_reddit_when_core_sources_work(self):
        metrics = {
            "total_signals": 43,
            "sources": {
                "github": {"status": "ok"},
                "hackernews": {"status": "ok"},
                "arxiv": {"status": "ok"},
                "reddit": {"status": "degraded"},
                "huggingface": {"status": "ok"},
            },
        }
        errors = validate_source_metrics(metrics, min_total_signals=20, core_sources=CORE_SOURCES)
        self.assertEqual(errors, [])

    def test_validate_source_metrics_blocks_too_few_signals_or_all_core_failed(self):
        too_few = {"total_signals": 12, "sources": {"github": {"status": "ok"}}}
        self.assertTrue(any("total_signals" in err for err in validate_source_metrics(too_few, min_total_signals=20)))

        core_failed = {
            "total_signals": 50,
            "sources": {
                "github": {"status": "failed"},
                "hackernews": {"status": "failed"},
                "arxiv": {"status": "failed"},
                "reddit": {"status": "ok"},
                "huggingface": {"status": "ok"},
            },
        }
        self.assertTrue(any("core sources" in err for err in validate_source_metrics(core_failed)))

    def test_task_specs_use_unique_run_paths_and_single_wiki_curator_writer(self):
        specs = build_task_specs(run_id="unit-run", board_slug="idea-funnel-unit-run", ideas_root=Path(os.environ.get("IDEAS_ROOT", "/opt/data/ideas")))
        self.assertEqual([s.key for s in specs], ["github_hn", "reddit_arxiv", "huggingface", "verifier", "synthesizer", "judge", "wiki_curator", "search_strategist"])
        self.assertEqual(specs[3].parents, ["github_hn", "reddit_arxiv", "huggingface"])
        self.assertEqual(specs[-1].assignee, "search-strategist")
        self.assertEqual(specs[-2].assignee, "wiki-curator")
        self.assertIn(f"{os.environ.get(\"IDEAS_ROOT\", \"/opt/data/ideas\")}/runs/unit-run/normalized/signals.jsonl", specs[0].body)
        self.assertIn("only writer", specs[-2].body)

    def test_search_terms_fallback_to_defaults_when_no_runs_exist(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            terms = load_search_terms("github", ideas_root=Path(tmpdir))
            self.assertIn("github_ai_agents", terms)
            self.assertEqual(terms, DEFAULTS["github"])
            arxiv = load_search_terms("arxiv", ideas_root=Path(tmpdir))
            self.assertIn("agent_tools", arxiv)
            reddit = load_search_terms("reddit_feeds", ideas_root=Path(tmpdir))
            self.assertIn("LocalLLaMA", reddit)

    def test_search_terms_load_from_latest_run(self):
        import tempfile, json
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            run1 = root / "runs" / "2026-06-28"
            run1.mkdir(parents=True)
            (run1 / "search-terms.json").write_text(json.dumps({
                "github": {"custom_lane": "vibe coding pushed:>{since} stars:>5"},
                "arxiv": {"custom_arxiv": 'all:"vibe coding"'},
            }))
            run2 = root / "runs" / "2026-06-29"
            run2.mkdir(parents=True)
            (run2 / "search-terms.json").write_text(json.dumps({
                "github": {"github_computer_use": "computer use agent pushed:>{since} stars:>10"},
            }))
            github = load_search_terms("github", ideas_root=root)
            self.assertIn("github_computer_use", github)
            self.assertNotIn("custom_lane", github)
            arxiv = load_search_terms("arxiv", ideas_root=root)
            self.assertEqual(arxiv, DEFAULTS["arxiv"])

    def test_eligible_specs_activate_unassigned_roots_then_verified_chain(self):
        specs = build_task_specs(run_id="unit-run", board_slug="idea-funnel-unit-run", ideas_root=Path(os.environ.get("IDEAS_ROOT", "/opt/data/ideas")))
        task_ids = {spec.key: f"id_{spec.key}" for spec in specs}
        tasks = [{"id": tid, "status": "ready", "assignee": None} for tid in task_ids.values()]
        self.assertEqual(
            eligible_specs_to_activate(tasks, specs, task_ids, slots=2),
            ["github_hn", "reddit_arxiv"],
        )

        tasks = []
        for spec in specs:
            status = "done" if spec.key in {"github_hn", "reddit_arxiv", "huggingface"} else "blocked"
            tasks.append({"id": task_ids[spec.key], "status": status, "assignee": None})
        self.assertEqual(eligible_specs_to_activate(tasks, specs, task_ids, slots=2), ["verifier"])

    def test_kanban_client_creates_board_tasks_links_and_dispatches_with_cap(self):
        fake = FakeCommandRunner()
        client = KanbanClient(hermes_bin="hermes", runner=fake)
        specs = build_task_specs(run_id="unit-run", board_slug="idea-funnel-unit-run", ideas_root=Path(os.environ.get("IDEAS_ROOT", "/opt/data/ideas")))
        task_ids = client.create_pipeline(board_slug="idea-funnel-unit-run", run_id="unit-run", specs=specs)
        client.activate_roots(board_slug="idea-funnel-unit-run", task_ids=task_ids, specs=specs)
        client.dispatch(board_slug="idea-funnel-unit-run", max_active_workers=2, dry_run=False)

        self.assertEqual(len(task_ids), 8)
        self.assertEqual(fake.commands[0][:5], ["hermes", "kanban", "boards", "create", "idea-funnel-unit-run"])
        create_commands = [cmd for cmd in fake.commands if "create" in cmd and "--json" in cmd]
        link_commands = [cmd for cmd in fake.commands if "link" in cmd]
        dispatch_commands = [cmd for cmd in fake.commands if "dispatch" in cmd]
        self.assertEqual(len(create_commands), 8)
        self.assertTrue(all("--assignee" not in cmd for cmd in create_commands))
        self.assertTrue(all("--initial-status" in cmd and "blocked" in cmd for cmd in create_commands))
        block_commands = [cmd for cmd in fake.commands if "block" in cmd]
        self.assertEqual(len(block_commands), 8)
        assign_commands = [cmd for cmd in fake.commands if "assign" in cmd]
        self.assertEqual(len(assign_commands), 3)
        unblock_commands = [cmd for cmd in fake.commands if "unblock" in cmd]
        self.assertEqual(len(unblock_commands), 1)
        self.assertIn("t_fake_1", unblock_commands[0])
        self.assertIn("t_fake_2", unblock_commands[0])
        self.assertIn("t_fake_3", unblock_commands[0])
        self.assertGreaterEqual(len(link_commands), 7)
        self.assertIn("--max", dispatch_commands[-1])
        self.assertIn("2", dispatch_commands[-1])


if __name__ == "__main__":
    unittest.main()
