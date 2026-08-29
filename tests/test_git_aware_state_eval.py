import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_SCRIPTS = REPO_ROOT / "evals" / "scripts"
sys.path.insert(0, str(EVAL_SCRIPTS))

from run_git_aware_state_eval import discover_cases, run_case


EXPECTED_CASES = {
    "clean_repository_context",
    "dirty_status_is_not_progress",
    "changed_filename_is_not_completion_evidence",
    "project_subdirectory_scope",
    "non_git_repository",
    "bounded_path_truncation",
    "metadata_source_boundary",
}


class GitAwareStateEvalTests(unittest.TestCase):
    def test_discovers_seven_public_cases(self):
        cases = discover_cases(
            REPO_ROOT / "evals" / "public" / "git_aware_state"
        )
        self.assertEqual({gold["case_id"] for _, gold in cases}, EXPECTED_CASES)

    def test_runner_passes_all_cases_without_openai(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(EVAL_SCRIPTS / "run_git_aware_state_eval.py"),
                    "--output-root",
                    temp_dir,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            result_paths = list(
                Path(temp_dir).rglob("git_aware_state_results.jsonl")
            )
            self.assertEqual(len(result_paths), 1)
            results = [
                json.loads(line)
                for line in result_paths[0].read_text(encoding="utf-8").splitlines()
            ]

        self.assertEqual(len(results), 7)
        self.assertTrue(all(item["final_status"] == "pass" for item in results))
        self.assertNotIn("OPENAI", completed.stdout.upper())

    def test_runner_supports_case_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(EVAL_SCRIPTS / "run_git_aware_state_eval.py"),
                    "--case-id",
                    "metadata_source_boundary",
                    "--output-root",
                    temp_dir,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
        self.assertIn("metadata_source_boundary: PASS", completed.stdout)
        self.assertNotIn("clean_repository_context: PASS", completed.stdout)

    def test_missing_input_is_a_failed_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = Path(temp_dir) / "case"
            case_dir.mkdir()
            result = run_case(
                case_dir / "gold.yaml",
                {"case_id": "missing_input", "case_type": "git_aware_state"},
            )
        self.assertEqual(result["final_status"], "fail")
        self.assertTrue(
            any("missing input" in item for item in result["checks_failed"])
        )


if __name__ == "__main__":
    unittest.main()
