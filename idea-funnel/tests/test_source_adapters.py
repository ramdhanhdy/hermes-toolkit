import json
import tempfile
import unittest
from pathlib import Path

from source_adapters.schema import Signal, SourceResult, write_jsonl
from source_adapters.adapters.reddit import parse_reddit_atom
from source_adapters.fetch_sources import write_run_artifacts
from source_adapters.adapters.huggingface import HF_MODELS


class SourceAdapterTests(unittest.TestCase):
    def test_signal_serializes_to_jsonl_record(self):
        signal = Signal(
            source="unit",
            source_lane="unit_test",
            title="A useful AI agent paper",
            url="https://example.com/paper",
            entity_type="paper",
            summary="Short summary",
            published_at="2026-06-29T00:00:00Z",
            score=42,
            tags=["agent", "testing"],
            metadata={"origin": "fixture"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "signals.jsonl"
            write_jsonl(out, [signal])
            records = [json.loads(line) for line in out.read_text().splitlines()]

        self.assertEqual(records[0]["source"], "unit")
        self.assertEqual(records[0]["source_lane"], "unit_test")
        self.assertEqual(records[0]["title"], "A useful AI agent paper")
        self.assertEqual(records[0]["tags"], ["agent", "testing"])
        self.assertEqual(records[0]["metadata"], {"origin": "fixture"})

    def test_reddit_atom_parser_extracts_entries(self):
        atom = """<?xml version='1.0' encoding='UTF-8'?>
        <feed xmlns='http://www.w3.org/2005/Atom'>
          <entry>
            <title>New local agent runtime released</title>
            <link href='https://www.reddit.com/r/LocalLLaMA/comments/abc123/test/' />
            <updated>2026-06-29T01:02:03+00:00</updated>
            <summary>Discussion about tool calling and local LLM agents.</summary>
          </entry>
        </feed>
        """
        signals = parse_reddit_atom(atom.encode("utf-8"), subreddit="LocalLLaMA", limit=5)
        self.assertEqual(len(signals), 1)
        self.assertEqual(signals[0].source, "reddit")
        self.assertEqual(signals[0].source_lane, "r/LocalLLaMA")
        self.assertEqual(signals[0].title, "New local agent runtime released")
        self.assertIn("reddit.com/r/LocalLLaMA", signals[0].url)

    def test_huggingface_models_endpoint_uses_supported_trending_sort(self):
        self.assertIn("sort=trendingScore", HF_MODELS)
        self.assertNotIn("sort=trending&", HF_MODELS)

    def test_write_run_artifacts_records_ok_and_degraded_sources(self):
        ok_signal = Signal(
            source="github",
            source_lane="github_search",
            title="agent repo",
            url="https://github.com/example/agent",
            entity_type="repo",
            summary="repo summary",
        )
        results = [
            SourceResult(adapter="github", status="ok", signals=[ok_signal], raw_files=["raw/github.json"]),
            SourceResult(adapter="reddit", status="degraded", signals=[], errors=["rss timeout"]),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            run_dir = Path(tmp) / "runs" / "unit-run"
            artifacts = write_run_artifacts(run_dir, results)
            metrics = json.loads(Path(artifacts["metrics"]).read_text())
            records = [json.loads(line) for line in Path(artifacts["signals_jsonl"]).read_text().splitlines()]

        self.assertEqual(records[0]["source"], "github")
        self.assertEqual(metrics["sources"]["github"]["status"], "ok")
        self.assertEqual(metrics["sources"]["reddit"]["status"], "degraded")
        self.assertEqual(metrics["total_signals"], 1)
        self.assertEqual(metrics["sources"]["reddit"]["signals"], 0)


if __name__ == "__main__":
    unittest.main()
