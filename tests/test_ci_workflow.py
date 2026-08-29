import unittest
from pathlib import Path

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "ci.yml"


class CIWorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.workflow = yaml.safe_load(cls.text)

    def test_python_matrix_and_read_only_permissions(self):
        matrix = self.workflow["jobs"]["test"]["strategy"]["matrix"]
        self.assertEqual(
            matrix["python-version"],
            ["3.10", "3.11", "3.12", "3.13"],
        )
        self.assertEqual(self.workflow["permissions"], {"contents": "read"})
        self.assertFalse(self.workflow["jobs"]["test"]["strategy"]["fail-fast"])

    def test_test_job_runs_full_tests_and_all_deterministic_evals(self):
        commands = "\n".join(
            str(step.get("run", ""))
            for step in self.workflow["jobs"]["test"]["steps"]
        )
        self.assertIn("python -m pytest -q", commands)
        self.assertIn("python demo/offline/run_smoke.py --non-interactive", commands)
        self.assertIn("python demo/live/validate_fixture.py", commands)
        self.assertIn("python demo/live/prepare_live_demo.py", commands)
        self.assertIn("git -C /tmp/pma-live-demo-ci status --short", commands)
        self.assertIn("benchmarks/run_benchmark.py", commands)
        self.assertIn("--profile tiny", commands)
        self.assertIn("--warmups 0", commands)
        self.assertIn("--repetitions 1", commands)
        self.assertIn("--output /tmp/", commands)
        for script in (
            "run_query_memo_eval.py",
            "run_status_note_eval.py",
            "run_python_source_eval.py",
            "run_git_aware_state_eval.py",
            "run_reliability_eval.py",
        ):
            self.assertIn(script, commands)
        self.assertIn("--mode fixture", commands)
        self.assertNotIn("--mode live", commands)
        self.assertNotIn("--judge", commands)
        self.assertNotIn("--confirm-live-calls", commands)

    def test_release_job_builds_scans_and_smoke_tests(self):
        commands = "\n".join(
            str(step.get("run", ""))
            for step in self.workflow["jobs"]["release"]["steps"]
        )
        self.assertIn("python -m build --outdir dist", commands)
        self.assertIn("check_release_privacy.py", commands)
        self.assertIn("src benchmarks demo docs README.md PROJECT_STATUS.md", commands)
        self.assertIn("pyproject.toml MANIFEST.in dist", commands)
        self.assertIn("run_release_smoke.py", commands)
        self.assertNotIn("OPENAI_API_KEY:", self.text)


if __name__ == "__main__":
    unittest.main()
