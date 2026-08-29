import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_SCRIPTS = REPO_ROOT / "evals" / "scripts"
sys.path.insert(0, str(EVAL_SCRIPTS))

from run_reliability_eval import discover_cases, run_case


EXPECTED_CASES = {
    "artifact_added",
    "content_changed",
    "legacy_manifest_missing",
    "non_git_unchanged",
    "scanner_config_changed",
}


class ReliabilityEvalTests(unittest.TestCase):
    def test_discovers_five_public_cases(self):
        cases = discover_cases(REPO_ROOT / "evals" / "public" / "reliability")
        self.assertEqual({gold["case_id"] for _, gold in cases}, EXPECTED_CASES)

    def test_runner_passes_all_cases_without_openai(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(EVAL_SCRIPTS / "run_reliability_eval.py"),
                    "--output-root",
                    temp_dir,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            result_paths = list(Path(temp_dir).rglob("reliability_results.jsonl"))
            results = [
                json.loads(line)
                for line in result_paths[0].read_text(encoding="utf-8").splitlines()
            ]
        self.assertEqual(len(result_paths), 1)
        self.assertEqual(len(results), 5)
        self.assertTrue(all(item["final_status"] == "pass" for item in results))
        self.assertNotIn("OPENAI", completed.stdout.upper())

    def test_case_selection_and_missing_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(EVAL_SCRIPTS / "run_reliability_eval.py"),
                    "--case-id",
                    "content_changed",
                    "--output-root",
                    temp_dir,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            missing_dir = Path(temp_dir) / "missing"
            missing_dir.mkdir()
            failed = run_case(
                missing_dir / "gold.yaml",
                {"case_id": "missing", "case_type": "reliability"},
            )
        self.assertIn("content_changed: PASS", completed.stdout)
        self.assertNotIn("artifact_added: PASS", completed.stdout)
        self.assertEqual(failed["final_status"], "fail")


if __name__ == "__main__":
    unittest.main()
