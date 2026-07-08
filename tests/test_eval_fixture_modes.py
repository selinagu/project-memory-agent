import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
PUBLIC_EVAL_ROOT = REPO_ROOT / "evals" / "public"


class EvalFixtureModeTests(unittest.TestCase):
    def run_fixture_eval(self, script: str, result_name: str) -> list[dict]:
        with tempfile.TemporaryDirectory() as temp_dir:
            env = os.environ.copy()
            env["PYTHONPATH"] = str(REPO_ROOT / "src")
            subprocess.run(
                [
                    sys.executable,
                    str(REPO_ROOT / "evals" / "scripts" / script),
                    "--mode",
                    "fixture",
                    "--eval-root",
                    "evals/public",
                    "--output-root",
                    temp_dir,
                ],
                cwd=REPO_ROOT,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            matches = list(Path(temp_dir).rglob(result_name))
            self.assertEqual(
                len(matches),
                1,
                f"Expected exactly one {result_name}, found: {matches}",
            )
            result_path = matches[0]
            return [
                json.loads(line)
                for line in result_path.read_text(encoding="utf-8").splitlines()
            ]

    def discover_expected_case_ids(self, case_type: str) -> set[str]:
        case_ids = []
        for gold_path in sorted(PUBLIC_EVAL_ROOT.rglob("gold.yaml")):
            gold = yaml.safe_load(gold_path.read_text(encoding="utf-8")) or {}
            if gold.get("case_type") == case_type:
                case_ids.append(gold.get("case_id"))

        self.assertTrue(
            case_ids,
            f"No public eval cases discovered for case_type={case_type!r}",
        )
        self.assertNotIn(
            None,
            case_ids,
            f"A public {case_type!r} gold.yaml is missing case_id",
        )
        self.assertEqual(
            len(case_ids),
            len(set(case_ids)),
            f"Duplicate public case_id values for {case_type!r}: {case_ids}",
        )
        return set(case_ids)

    def assert_fixture_results_cover_public_cases(
        self,
        results: list[dict],
        case_type: str,
    ) -> None:
        self.assertTrue(results, f"No fixture results produced for {case_type!r}")
        expected_ids = self.discover_expected_case_ids(case_type)
        actual_ids = [result.get("case_id") for result in results]

        self.assertNotIn(
            None,
            actual_ids,
            f"A {case_type!r} result row is missing case_id: {results}",
        )
        self.assertEqual(
            len(actual_ids),
            len(set(actual_ids)),
            f"Duplicate result case_id values for {case_type!r}: {actual_ids}",
        )

        actual_id_set = set(actual_ids)
        self.assertEqual(
            actual_id_set,
            expected_ids,
            (
                f"Fixture result coverage mismatch for {case_type!r}; "
                f"missing={sorted(expected_ids - actual_id_set)}, "
                f"unexpected={sorted(actual_id_set - expected_ids)}"
            ),
        )

        failed = {
            result["case_id"]: result.get("final_status")
            for result in results
            if result.get("final_status") != "pass"
        }
        self.assertFalse(
            failed,
            f"Fixture cases did not pass for {case_type!r}: {failed}",
        )

        wrong_modes = {
            result["case_id"]: result.get("evaluation_mode")
            for result in results
            if result.get("evaluation_mode") != "fixture"
        }
        self.assertFalse(
            wrong_modes,
            f"Fixture cases reported the wrong evaluation_mode: {wrong_modes}",
        )

    def test_state_fixture_regression_passes_all_public_cases(self):
        results = self.run_fixture_eval(
            "run_state_eval.py",
            "state_results.jsonl",
        )

        self.assert_fixture_results_cover_public_cases(
            results,
            "state_reconstruction",
        )

    def test_progress_fixture_regression_passes_all_public_cases(self):
        results = self.run_fixture_eval(
            "run_progress_eval.py",
            "progress_results.jsonl",
        )

        self.assert_fixture_results_cover_public_cases(
            results,
            "progress_update",
        )


if __name__ == "__main__":
    unittest.main()
