import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_SCRIPTS = REPO_ROOT / "evals" / "scripts"
sys.path.insert(0, str(EVAL_SCRIPTS))

from run_python_source_eval import discover_cases, run_case


class PythonSourceEvalTests(unittest.TestCase):
    def test_discovers_seven_public_python_source_cases(self):
        cases = discover_cases(REPO_ROOT / "evals" / "public" / "python_source")
        self.assertEqual(
            {gold["case_id"] for _, gold in cases},
            {
                "module_structure_basic",
                "methods_and_bases",
                "sensitive_literals_redacted",
                "syntax_error_is_bounded",
                "default_disabled",
                "opt_in_and_scope",
                "no_code_execution",
            },
        )

    def test_runner_passes_all_cases_without_openai(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(EVAL_SCRIPTS / "run_python_source_eval.py"),
                    "--output-root",
                    temp_dir,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            result_paths = list(Path(temp_dir).rglob("python_source_results.jsonl"))
            self.assertEqual(len(result_paths), 1)
            results = [
                json.loads(line)
                for line in result_paths[0].read_text(encoding="utf-8").splitlines()
            ]
            self.assertEqual(len(results), 7)
            self.assertTrue(all(result["final_status"] == "pass" for result in results))
            self.assertNotIn("OPENAI", completed.stdout.upper())

    def test_runner_supports_case_selection(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(EVAL_SCRIPTS / "run_python_source_eval.py"),
                    "--case-id",
                    "no_code_execution",
                    "--output-root",
                    temp_dir,
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                check=True,
            )
            self.assertIn("no_code_execution: PASS", completed.stdout)
            self.assertNotIn("module_structure_basic: PASS", completed.stdout)

    def test_missing_input_is_a_failed_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = Path(temp_dir) / "case"
            case_dir.mkdir()
            result = run_case(
                case_dir / "gold.yaml",
                {"case_id": "missing_input", "case_type": "python_source"},
            )
        self.assertEqual(result["final_status"], "fail")
        self.assertTrue(
            any("missing input directory" in check for check in result["checks_failed"])
        )


if __name__ == "__main__":
    unittest.main()
