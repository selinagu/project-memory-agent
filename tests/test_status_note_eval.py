import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_SCRIPTS = REPO_ROOT / "evals" / "scripts"
sys.path.insert(0, str(EVAL_SCRIPTS))

from run_status_note_eval import discover_cases, run_case


class StatusNoteEvalTests(unittest.TestCase):
    def test_discovers_six_public_status_note_cases(self):
        cases = discover_cases(REPO_ROOT / "evals" / "public" / "status_note")
        self.assertEqual(
            {gold["case_id"] for _, gold in cases},
            {
                "no_latest_todo_template",
                "complete_latest_progress_preferred",
                "summary_fallback",
                "canonical_named_layout",
                "write_refuses_without_force",
                "force_overwrites",
            },
        )

    def test_runner_passes_all_cases_without_openai(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(EVAL_SCRIPTS / "run_status_note_eval.py"),
                    "--eval-root",
                    "evals/public/status_note",
                    "--output-root",
                    temp_dir,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            result_paths = list(Path(temp_dir).rglob("status_note_results.jsonl"))
            self.assertEqual(len(result_paths), 1)
            results = [
                json.loads(line)
                for line in result_paths[0].read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(results), 6)
            self.assertTrue(all(result["final_status"] == "pass" for result in results))
            self.assertNotIn("OPENAI", completed.stdout.upper())

    def test_runner_supports_case_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(EVAL_SCRIPTS / "run_status_note_eval.py"),
                    "--case-id",
                    "summary_fallback",
                    "--output-root",
                    temp_dir,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("summary_fallback: PASS", completed.stdout)
            self.assertNotIn("no_latest_todo_template: PASS", completed.stdout)

    def test_missing_input_is_a_failed_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = Path(temp_dir) / "case"
            case_dir.mkdir()
            gold_path = case_dir / "gold.yaml"
            gold = {
                "case_id": "missing_input",
                "case_type": "status_note",
                "command": ["pma", "status-note"],
            }
            result = run_case(gold_path, gold, Path(temp_dir) / "output")
            self.assertEqual(result["final_status"], "fail")
            self.assertTrue(
                any("missing input directory" in check for check in result["checks_failed"])
            )


if __name__ == "__main__":
    unittest.main()
