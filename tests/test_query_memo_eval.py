import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_SCRIPTS = REPO_ROOT / "evals" / "scripts"
sys.path.insert(0, str(EVAL_SCRIPTS))

from run_query_memo_eval import (
    apply_query_memo_judge,
    build_query_memo_judge_prompt,
    command_with_project_dir,
    discover_cases,
    parse_query_memo_judge_response,
    run_live_case,
    score_output,
)


class QueryMemoEvalTests(unittest.TestCase):
    def test_discovers_all_public_query_memo_cases(self):
        cases = discover_cases(REPO_ROOT / "evals" / "public")
        discovered_ids = {gold["case_id"] for _, gold in cases}
        expected_ids = {
            "ask_schema_basic",
            "ask_source_evidence",
            "memo_self_basic",
            "memo_group_latest",
            "memo_group_last_window",
            "memo_group_conflict_correction",
            "memo_group_since_window",
        }
        self.assertEqual(discovered_ids, expected_ids)

    def test_rule_checks_detect_missing_and_forbidden_text(self):
        gold = {
            "required_includes": ["required fact"],
            "forbidden_includes": ["invented action"],
        }
        result = score_output("An invented action appears.", 0, gold)
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("required_include" in item for item in result["checks_failed"])
        )
        self.assertTrue(
            any("forbidden_include" in item for item in result["checks_failed"])
        )

    def test_rule_checks_sections_and_command_errors(self):
        gold = {
            "fixture_exit_code": 0,
            "required_sections": ["## Planned next actions"],
            "section_constraints": [
                {
                    "section": "## Planned next actions",
                    "required_includes": ["current action"],
                    "forbidden_includes": ["old action"],
                }
            ],
        }
        output = (
            "# Update\n\n## Planned next actions\n- old action\n\n"
            "## Notes\n- None"
        )
        result = score_output(output, 2, gold)
        self.assertFalse(result["passed"])
        self.assertTrue(
            any("exit_code" in item for item in result["checks_failed"])
        )
        self.assertTrue(
            any("section_required" in item for item in result["checks_failed"])
        )

    def test_fixture_runner_passes_without_live_llm(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = subprocess.run(
                [
                    sys.executable,
                    str(EVAL_SCRIPTS / "run_query_memo_eval.py"),
                    "--mode",
                    "fixture",
                    "--eval-root",
                    "evals/public",
                    "--output-root",
                    temp_dir,
                ],
                cwd=REPO_ROOT,
                check=True,
                capture_output=True,
                text=True,
            )
            matches = list(Path(temp_dir).rglob("query_memo_results.jsonl"))
            self.assertEqual(len(matches), 1)
            results = [
                json.loads(line)
                for line in matches[0].read_text(encoding="utf-8").splitlines()
            ]
            self.assertTrue(results)
            self.assertTrue(all(row["final_status"] == "pass" for row in results))
            self.assertTrue(all(row["fixture_exit_code"] == 0 for row in results))
            self.assertTrue(
                all(row["evaluation_mode"] == "fixture" for row in results)
            )
            self.assertNotIn("OPENAI", completed.stdout)

    def test_command_with_project_dir_inserts_and_replaces_project_dir(self):
        project_dir = Path("/tmp/pma-live-project")

        ask_command = command_with_project_dir(
            ["pma", "ask", "What is the goal?"],
            project_dir,
        )
        self.assertEqual(
            ask_command,
            [
                sys.executable,
                "-m",
                "pma",
                "ask",
                "--project-dir",
                str(project_dir),
                "What is the goal?",
            ],
        )

        memo_command = command_with_project_dir(
            ["pma", "memo", "--type", "group-update"],
            project_dir,
        )
        self.assertEqual(
            memo_command[:6],
            [sys.executable, "-m", "pma", "memo", "--project-dir", str(project_dir)],
        )

        replaced_command = command_with_project_dir(
            ["pma", "ask", "--project-dir", "/old/project", "Question?"],
            project_dir,
        )
        self.assertIn(str(project_dir), replaced_command)
        self.assertNotIn("/old/project", replaced_command)

    def test_live_case_errors_clearly_when_input_dir_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = Path(temp_dir) / "case"
            case_dir.mkdir()
            gold_path = case_dir / "gold.yaml"
            gold_path.write_text("", encoding="utf-8")
            run_root = Path(temp_dir) / "run"
            gold = {
                "case_id": "missing_input",
                "case_type": "query_memo",
                "command": ["pma", "ask", "Question?"],
            }

            result = run_live_case(gold_path, gold, run_root)

            self.assertEqual(result["evaluation_mode"], "live")
            self.assertEqual(result["final_status"], "fail")
            self.assertTrue(
                any("missing input directory" in item for item in result["checks_failed"])
            )
            self.assertTrue(Path(result["stderr_path"]).exists())

    def test_live_case_uses_observed_exit_code_and_writes_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            case_dir = Path(temp_dir) / "case"
            input_dir = case_dir / "input"
            input_dir.mkdir(parents=True)
            (input_dir / "README.md").write_text("fixture project", encoding="utf-8")
            gold_path = case_dir / "gold.yaml"
            gold_path.write_text("", encoding="utf-8")
            run_root = Path(temp_dir) / "run"
            gold = {
                "case_id": "live_plumbing",
                "case_type": "query_memo",
                "capability": "mocked_live",
                "command": ["pma", "memo", "--type", "self"],
                "expected_exit_code": 3,
                "required_includes": ["mock stdout"],
            }
            completed = subprocess.CompletedProcess(
                args=[],
                returncode=3,
                stdout="mock stdout",
                stderr="mock stderr",
            )

            with patch("run_query_memo_eval.subprocess.run", return_value=completed) as run:
                result = run_live_case(gold_path, gold, run_root)

            self.assertEqual(result["evaluation_mode"], "live")
            self.assertEqual(result["exit_code"], 3)
            self.assertEqual(result["final_status"], "pass")
            self.assertEqual(Path(result["stdout_path"]).read_text(), "mock stdout")
            self.assertEqual(Path(result["stderr_path"]).read_text(), "mock stderr")
            command = json.loads(Path(result["command_path"]).read_text())
            self.assertEqual(command[:4], [sys.executable, "-m", "pma", "memo"])
            self.assertIn("--project-dir", command)
            self.assertEqual(run.call_args.kwargs["timeout"], 120)

    def test_judge_prompt_includes_case_context_output_and_rule_summary(self):
        gold = {
            "case_id": "memo_case",
            "case_type": "query_memo",
            "capability": "self_memo",
            "command": ["pma", "memo", "--type", "self"],
            "required_includes": ["required fact"],
        }
        result = {
            "passed": False,
            "score": 0.5,
            "checks_passed": ["exit_code"],
            "checks_failed": ["required_include: required fact"],
        }

        prompt = build_query_memo_judge_prompt(
            gold=gold,
            output="actual memo output",
            result=result,
        )

        self.assertIn("memo_case", prompt)
        self.assertIn("self_memo", prompt)
        self.assertIn('"pma"', prompt)
        self.assertIn("required fact", prompt)
        self.assertIn("actual memo output", prompt)
        self.assertIn("required_include: required fact", prompt)

    def test_valid_and_invalid_judge_json_are_parsed(self):
        parsed = parse_query_memo_judge_response(
            '{"judge_passed": true, "reason": "ok", "issues": []}'
        )
        self.assertTrue(parsed["judge_passed"])
        self.assertEqual(parsed["judge_reason"], "ok")
        self.assertEqual(parsed["judge_issues"], [])

        invalid = parse_query_memo_judge_response("not json")
        self.assertFalse(invalid["judge_passed"])
        self.assertIn("valid JSON", invalid["judge_reason"])

    def test_judge_off_rule_behavior_is_unchanged(self):
        gold = {"required_includes": ["required fact"]}
        result = score_output("required fact", 0, gold)

        self.assertTrue(result["passed"])
        self.assertEqual(result["final_status"], "pass")
        self.assertNotIn("judge_passed", result)
        self.assertNotIn("rule_passed", result)

    def test_judge_pass_requires_rule_and_judge_pass(self):
        result = score_output("required fact", 0, {"required_includes": ["required"]})

        with patch(
            "run_query_memo_eval.call_query_memo_judge",
            return_value={
                "judge_passed": True,
                "judge_reason": "semantically ok",
                "judge_issues": [],
            },
        ):
            judged = apply_query_memo_judge(
                result=result,
                gold={"case_id": "case", "command": ["pma", "ask", "Q"]},
                output="required fact",
                model="fake-model",
            )

        self.assertTrue(judged["rule_passed"])
        self.assertTrue(judged["judge_passed"])
        self.assertEqual(judged["judge_reason"], "semantically ok")
        self.assertEqual(judged["judge_issues"], [])
        self.assertEqual(judged["final_status"], "pass")

    def test_judge_fail_fails_even_when_rules_pass(self):
        result = score_output("required fact", 0, {"required_includes": ["required"]})

        with patch(
            "run_query_memo_eval.call_query_memo_judge",
            return_value={
                "judge_passed": False,
                "judge_reason": "missing semantic requirement",
                "judge_issues": ["missing requirement"],
            },
        ):
            judged = apply_query_memo_judge(
                result=result,
                gold={"case_id": "case", "command": ["pma", "ask", "Q"]},
                output="required fact",
                model="fake-model",
            )

        self.assertTrue(judged["rule_passed"])
        self.assertFalse(judged["judge_passed"])
        self.assertEqual(judged["final_status"], "fail")

    def test_judge_pass_cannot_override_rule_failure(self):
        result = score_output("missing", 0, {"required_includes": ["required"]})

        with patch(
            "run_query_memo_eval.call_query_memo_judge",
            return_value={
                "judge_passed": True,
                "judge_reason": "semantically ok",
                "judge_issues": [],
            },
        ):
            judged = apply_query_memo_judge(
                result=result,
                gold={"case_id": "case", "command": ["pma", "ask", "Q"]},
                output="missing",
                model="fake-model",
            )

        self.assertFalse(judged["rule_passed"])
        self.assertTrue(judged["judge_passed"])
        self.assertEqual(judged["final_status"], "fail")


if __name__ == "__main__":
    unittest.main()
