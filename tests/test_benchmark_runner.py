import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmarks.benchmark_models import BENCHMARK_STAGE_NAMES
from benchmarks.run_benchmark import run_benchmarks


REPO_ROOT = Path(__file__).resolve().parents[1]


class BenchmarkRunnerTests(unittest.TestCase):
    def test_generated_result_directory_is_ignored(self):
        ignore = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("benchmarks/results/", ignore.splitlines())

    def test_tiny_runner_is_offline_complete_private_and_deterministic_in_shape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = root / "results"
            with patch.dict(os.environ, {"OPENAI_API_KEY": "must-not-be-used"}):
                report = run_benchmarks(
                    ["tiny"],
                    seed=7,
                    warmups=0,
                    repetitions=2,
                    output_dir=output,
                )
            result_json = json.loads(
                (output / "benchmark_results.json").read_text(encoding="utf-8")
            )
            summary = (output / "summary.md").read_text(encoding="utf-8")
            encoded = json.dumps(result_json)
        self.assertFalse(report.calls_openai)
        self.assertEqual(len(report.cases), 1)
        case = report.cases[0]
        self.assertEqual(set(case.timings), set(BENCHMARK_STAGE_NAMES))
        self.assertTrue(all(item.repetitions == 2 for item in case.timings.values()))
        self.assertEqual(case.repository.generated_files, 25)
        self.assertEqual(case.repository.selected_artifacts, 20)
        self.assertGreater(case.repository.raw_bytes, 0)
        self.assertGreater(case.repository.combined_notes_chars, 0)
        self.assertGreater(case.peak_python_bytes, 0)
        self.assertEqual(case.scanner_config["max_artifacts"], 500)
        self.assertEqual(case.scanner_config["max_combined_notes_chars"], 2_000_000)
        self.assertIn("not LLM latency", summary)
        self.assertNotIn(str(root), encoded)
        self.assertNotIn("must-not-be-used", encoded)
        self.assertNotIn("hostname", encoded.lower())

    def test_cli_writes_json_and_markdown_without_openai(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "output"
            environment = dict(os.environ)
            environment.pop("OPENAI_API_KEY", None)
            completed = subprocess.run(
                [
                    sys.executable,
                    "benchmarks/run_benchmark.py",
                    "--profile",
                    "tiny",
                    "--seed",
                    "9",
                    "--warmups",
                    "0",
                    "--repetitions",
                    "1",
                    "--output",
                    str(output),
                ],
                cwd=REPO_ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=True,
            )
        self.assertIn("tiny: files=25", completed.stdout)
        self.assertNotIn("OPENAI", completed.stderr.upper())

    def test_invalid_run_configuration_fails_before_creating_cases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "output"
            with self.assertRaises(ValueError):
                run_benchmarks(
                    [],
                    seed=7,
                    warmups=0,
                    repetitions=1,
                    output_dir=output,
                )


if __name__ == "__main__":
    unittest.main()
