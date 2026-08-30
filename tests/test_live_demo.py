from __future__ import annotations

import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import unittest
from unittest import mock

from demo.live import prepare_live_demo, rehearse_live_demo, validate_fixture


REPO_ROOT = Path(__file__).resolve().parents[1]
LIVE_ROOT = REPO_ROOT / "demo" / "live"

SUPPORTED_FACTS = (
    "The bounded policy limits refresh work to affected key groups. "
    "Full refresh reached 91.2 ms and increased origin requests by 68%. "
    "The bounded policy remained at 48.7 ms."
)


def answer_with_sources(*sources: str, facts: str = SUPPORTED_FACTS) -> str:
    citations = " ".join(
        f"combined_notes.md SOURCE {source}." for source in sources
    )
    return f"Answer: {facts}\nEvidence:\n- {citations}\nUncertainty: pending."


def complete_records(ask_text: str) -> list[dict[str, object]]:
    outputs = {
        "checkpoint": "checkpoint complete",
        "brief": "checkpoint available",
        "memo": "rollout remains blocked",
        "ask": ask_text,
        "freshness_after_update": "Freshness: stale",
        "brief_after_update": "Create a new checkpoint.",
    }
    return [
        {"name": name, "returncode": 0, "stdout": output, "stderr": ""}
        for name, output in outputs.items()
    ]


def fixture_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted((LIVE_ROOT / "fixtures").rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(LIVE_ROOT).as_posix().encode())
            digest.update(path.read_bytes())
    digest.update((LIVE_ROOT / "gold.yaml").read_bytes())
    return digest.hexdigest()


class LiveDemoTests(unittest.TestCase):
    def test_fixture_validates_offline_without_mutation(self):
        before = fixture_digest()
        with mock.patch.object(socket, "socket", side_effect=AssertionError("network used")):
            report = validate_fixture.validate_fixture()
        self.assertEqual(report["artifact_count"], 5)
        self.assertEqual(report["gold_source_candidate_count"], 3)
        self.assertTrue(report["update_changes_status"])
        self.assertEqual(fixture_digest(), before)

    def test_prepare_creates_clean_git_repo_and_separate_update(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            update = root / "update.md"
            with mock.patch.object(socket, "socket", side_effect=AssertionError("network used")):
                prepared = prepare_live_demo.prepare_demo(project, update)

            self.assertEqual(prepared.project_dir, project.resolve())
            self.assertEqual(prepared.update_path, update.resolve())
            self.assertTrue((project / ".git" / prepare_live_demo.SENTINEL_NAME).is_file())
            self.assertEqual(
                subprocess.run(
                    ["git", "status", "--short"],
                    cwd=project,
                    text=True,
                    stdout=subprocess.PIPE,
                    check=True,
                ).stdout,
                "",
            )
            shutil.copy2(update, project / "PROJECT_STATUS.md")
            self.assertEqual(
                subprocess.run(
                    ["git", "status", "--short"],
                    cwd=project,
                    text=True,
                    stdout=subprocess.PIPE,
                    check=True,
                ).stdout.strip(),
                "M PROJECT_STATUS.md",
            )

    def test_reset_requires_sentinel_and_recreates_known_demo(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            update = root / "update.md"
            project.mkdir()
            with self.assertRaisesRegex(prepare_live_demo.PrepareError, "sentinel"):
                prepare_live_demo.prepare_demo(project, update, reset=True)
            project.rmdir()
            prepare_live_demo.prepare_demo(project, update)
            (project / "untracked.txt").write_text("remove on reset\n", encoding="utf-8")
            prepare_live_demo.prepare_demo(project, update, reset=True)
            self.assertFalse((project / "untracked.txt").exists())

    def test_prepare_rejects_repository_and_home(self):
        with self.assertRaises(prepare_live_demo.PrepareError):
            prepare_live_demo.prepare_demo(REPO_ROOT, Path("/tmp/pma-live-update-test.md"))
        with self.assertRaises(prepare_live_demo.PrepareError):
            prepare_live_demo.prepare_demo(Path.home(), Path("/tmp/pma-live-update-test.md"))

    def test_rehearsal_is_guarded_before_subprocess_or_api_use(self):
        stderr = io.StringIO()
        with mock.patch.object(rehearse_live_demo.subprocess, "run") as run_mock:
            with mock.patch("sys.stderr", stderr):
                exit_code = rehearse_live_demo.main([])
        self.assertEqual(exit_code, 2)
        self.assertFalse(run_mock.called)
        self.assertIn("blocked", stderr.getvalue().casefold())

    def test_status_and_benchmark_satisfy_ask_contract(self):
        checks, diagnostics = rehearse_live_demo.evaluate_ask_contract(
            answer_with_sources("PROJECT_STATUS.md", "benchmark_results.json"),
            validate_fixture.load_gold()["ask"],
        )
        self.assertTrue(all(checks.values()))
        self.assertEqual(
            diagnostics["observed_sources"],
            ["PROJECT_STATUS.md", "benchmark_results.json"],
        )

    def test_status_and_failure_analysis_satisfy_ask_contract(self):
        checks, _ = rehearse_live_demo.evaluate_ask_contract(
            answer_with_sources("PROJECT_STATUS.md", "failure_analysis.md"),
            validate_fixture.load_gold()["ask"],
        )
        self.assertTrue(all(checks.values()))

    def test_benchmark_and_failure_analysis_satisfy_ask_contract(self):
        checks, diagnostics = rehearse_live_demo.evaluate_ask_contract(
            answer_with_sources("benchmark_results.json", "failure_analysis.md"),
            validate_fixture.load_gold()["ask"],
        )
        self.assertTrue(all(checks.values()))
        self.assertEqual(
            diagnostics["observed_sources"],
            ["benchmark_results.json", "failure_analysis.md"],
        )

    def test_all_three_sources_satisfy_ask_contract(self):
        checks, _ = rehearse_live_demo.evaluate_ask_contract(
            answer_with_sources(
                "PROJECT_STATUS.md", "benchmark_results.json", "failure_analysis.md"
            ),
            validate_fixture.load_gold()["ask"],
        )
        self.assertTrue(all(checks.values()))

    def test_status_alone_fails_group_and_minimum(self):
        checks, diagnostics = rehearse_live_demo.evaluate_ask_contract(
            answer_with_sources("PROJECT_STATUS.md"),
            validate_fixture.load_gold()["ask"],
        )
        self.assertFalse(checks["ask_satisfies_required_source_groups"])
        self.assertFalse(checks["ask_has_minimum_distinct_sources"])
        self.assertEqual(diagnostics["unsatisfied_source_groups"], ["measurement"])

    def test_benchmark_alone_fails_decision_group_and_minimum(self):
        checks, diagnostics = rehearse_live_demo.evaluate_ask_contract(
            answer_with_sources("benchmark_results.json"),
            validate_fixture.load_gold()["ask"],
        )
        self.assertFalse(checks["ask_satisfies_required_source_groups"])
        self.assertFalse(checks["ask_has_minimum_distinct_sources"])
        self.assertEqual(
            diagnostics["unsatisfied_source_groups"], ["decision_or_rationale"]
        )

    def test_failure_analysis_alone_satisfies_roles_but_fails_minimum(self):
        checks, diagnostics = rehearse_live_demo.evaluate_ask_contract(
            answer_with_sources("failure_analysis.md"),
            validate_fixture.load_gold()["ask"],
        )
        self.assertTrue(checks["ask_satisfies_required_source_groups"])
        self.assertFalse(checks["ask_has_minimum_distinct_sources"])
        self.assertEqual(diagnostics["unsatisfied_source_groups"], [])

    def test_unrelated_source_does_not_count_toward_minimum(self):
        text = answer_with_sources("PROJECT_STATUS.md") + "\n- unrelated_notes.md"
        checks, diagnostics = rehearse_live_demo.evaluate_ask_contract(
            text, validate_fixture.load_gold()["ask"]
        )
        self.assertFalse(checks["ask_has_minimum_distinct_sources"])
        self.assertEqual(diagnostics["observed_sources"], ["PROJECT_STATUS.md"])

    def test_source_name_inside_longer_path_does_not_match(self):
        text = answer_with_sources("benchmark_results.json")
        text += "\n- archive/PROJECT_STATUS.md.backup"
        checks, diagnostics = rehearse_live_demo.evaluate_ask_contract(
            text, validate_fixture.load_gold()["ask"]
        )
        self.assertNotIn("PROJECT_STATUS.md", diagnostics["observed_sources"])
        self.assertFalse(checks["ask_satisfies_required_source_groups"])

    def test_sources_without_required_facts_fail_evidence(self):
        checks, diagnostics = rehearse_live_demo.evaluate_ask_contract(
            answer_with_sources(
                "PROJECT_STATUS.md",
                "benchmark_results.json",
                facts="The bounded policy was selected after testing.",
            ),
            validate_fixture.load_gold()["ask"],
        )
        self.assertFalse(checks["ask_contains_required_evidence"])
        self.assertIn("full_refresh_latency", diagnostics["unsatisfied_evidence_groups"])

    def test_forbidden_completion_claim_still_fails(self):
        text = answer_with_sources("PROJECT_STATUS.md", "benchmark_results.json")
        text += "\nThe rollout is complete."
        checks, _ = rehearse_live_demo.evaluate_ask_contract(
            text, validate_fixture.load_gold()["ask"]
        )
        self.assertFalse(checks["ask_avoids_forbidden_claims"])

    def test_semantically_supported_two_source_live_equivalent_passes(self):
        text = """Answer:
We chose bounded key-prefix invalidation because it limits refresh work to
affected key groups. Full refresh increased origin requests by 68% and reached
91.2 ms, while the bounded policy stayed at 48.7 ms.

Evidence:
- combined_notes.md SOURCE failure_analysis.md records the decision rationale.
- project_state.json evidence source benchmark_results.json records the metrics.

Uncertainty / Missing info:
- The high-churn workload remains unvalidated.
"""
        checks, _ = rehearse_live_demo.evaluate_ask_contract(
            text, validate_fixture.load_gold()["ask"]
        )
        self.assertTrue(all(checks.values()))

    def test_recheck_is_offline_preserves_input_and_writes_separate_summary(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            run_path = root / "run-01.json"
            run_path.write_text(
                json.dumps(
                    {
                        "run": 1,
                        "records": complete_records(
                            answer_with_sources(
                                "benchmark_results.json", "failure_analysis.md"
                            )
                        ),
                    }
                ),
                encoding="utf-8",
            )
            original = run_path.read_bytes()
            stdout = io.StringIO()
            with mock.patch.object(rehearse_live_demo.subprocess, "run") as run_mock:
                with mock.patch.dict("os.environ", {}, clear=True):
                    with mock.patch("sys.stdout", stdout):
                        exit_code = rehearse_live_demo.main(
                            ["--recheck-results", str(root)]
                        )

            self.assertEqual(exit_code, 0)
            self.assertFalse(run_mock.called)
            self.assertEqual(run_path.read_bytes(), original)
            summary = json.loads((root / "recheck-summary.json").read_text())
            self.assertTrue(summary["passed"])
            self.assertEqual(summary["runs"], 1)
            self.assertIn("PASS", stdout.getvalue())

    def test_recheck_rejects_incomplete_records_without_subprocess(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "run-01.json").write_text(
                json.dumps({"run": 1, "records": []}), encoding="utf-8"
            )
            stderr = io.StringIO()
            with mock.patch.object(rehearse_live_demo.subprocess, "run") as run_mock:
                with mock.patch("sys.stderr", stderr):
                    exit_code = rehearse_live_demo.main(
                        ["--recheck-results", str(root)]
                    )
            self.assertEqual(exit_code, 1)
            self.assertFalse(run_mock.called)
            self.assertIn("incomplete", stderr.getvalue().casefold())
            self.assertFalse((root / "recheck-summary.json").exists())

    def test_source_contract_validation_rejects_invalid_minimum_and_groups(self):
        gold = validate_fixture.load_gold()
        invalid_minimum = copy.deepcopy(gold)
        invalid_minimum["ask"]["minimum_distinct_sources"] = 4
        with self.assertRaisesRegex(
            validate_fixture.FixtureValidationError, "exceeds allowed"
        ):
            validate_fixture._source_contract(invalid_minimum)

        invalid_group = copy.deepcopy(gold)
        invalid_group["ask"]["required_source_groups"] = [{"any_of": []}]
        with self.assertRaisesRegex(
            validate_fixture.FixtureValidationError, "non-empty any_of"
        ):
            validate_fixture._source_contract(invalid_group)

    def test_commands_and_storyboards_cover_the_live_workflow(self):
        commands = (LIVE_ROOT / "commands.txt").read_text(encoding="utf-8")
        narration = (LIVE_ROOT / "narration.md").read_text(encoding="utf-8")
        for command in ("checkpoint", "brief", "memo", "ask", "freshness"):
            self.assertIn(f"pma {command}", commands)
        self.assertIn("30–45 second", narration)
        self.assertIn("2–3 minute", narration)
        self.assertIn("PROJECT_STATUS.md", narration)


if __name__ == "__main__":
    unittest.main()
