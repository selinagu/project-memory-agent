import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import checkpoint
from freshness import check_checkpoint_freshness
from git_context import GIT_CONTEXT_SCHEMA_VERSION, collect_git_context
from pma import main, run_freshness
from tests.test_checkpoint_git_context import fake_extract_state
from tests.test_git_context import GIT_AVAILABLE, git, init_repository


@unittest.skipUnless(GIT_AVAILABLE, "Git executable is unavailable")
class CheckpointFreshnessIntegrationTests(unittest.TestCase):
    def checkpoint(self, root: Path) -> None:
        with patch("checkpoint.extract_state", side_effect=fake_extract_state):
            checkpoint.run_checkpoint(
                project_dir=root,
                project_name=".project_memory",
                base_output_dir=root,
                model="unused",
            )

    def test_checkpoint_writes_v2_fingerprints_to_run_and_latest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_repository(root)
            (root / "README.md").write_text("dirty checkpoint\n", encoding="utf-8")
            self.checkpoint(root)

            memory = root / ".project_memory"
            run_dir = next((memory / "runs").iterdir())
            run_json = (run_dir / "git_context.json").read_bytes()
            latest_json = (memory / "latest" / "git_context.json").read_bytes()
            context = json.loads(latest_json)
            combined = (memory / "latest" / "combined_notes.md").read_text(
                encoding="utf-8"
            )

        self.assertEqual(run_json, latest_json)
        self.assertEqual(context["schema_version"], GIT_CONTEXT_SCHEMA_VERSION)
        self.assertEqual(context["file_fingerprints"][0]["path"], "README.md")
        self.assertNotIn("file_fingerprints", combined)

    def test_dirty_checkpoint_is_current_then_same_path_edit_is_stale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_repository(root)
            (root / "README.md").write_text("first dirty value\n", encoding="utf-8")
            self.checkpoint(root)
            self.assertEqual(check_checkpoint_freshness(root).status, "current")

            (root / "README.md").write_text("second dirty valu\n", encoding="utf-8")
            result = check_checkpoint_freshness(root)

        self.assertEqual(result.status, "stale")
        self.assertIn("file_content_changed", [reason.code for reason in result.reasons])

    def test_head_change_is_stale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_repository(root)
            self.checkpoint(root)
            (root / "README.md").write_text("next commit\n", encoding="utf-8")
            git(root, "add", "README.md")
            git(root, "commit", "-q", "-m", "Move HEAD")
            result = check_checkpoint_freshness(root)
        self.assertEqual(result.status, "stale")
        self.assertIn("head_changed", [reason.code for reason in result.reasons])


class FreshnessCliTests(unittest.TestCase):
    def write_non_git_checkpoint(self, root: Path) -> Path:
        latest = root / ".project_memory" / "latest"
        latest.mkdir(parents=True)
        path = latest / "git_context.json"
        context = collect_git_context(root, collected_at="checkpoint")
        path.write_text(json.dumps(context.to_dict()), encoding="utf-8")
        return path

    def test_human_and_json_cli_return_zero_for_ordinary_states(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            checkpoint_path = self.write_non_git_checkpoint(root)
            before = checkpoint_path.read_bytes()
            runs_before = list((root / ".project_memory").iterdir())

            human = StringIO()
            with redirect_stdout(human):
                human_code = run_freshness(["--project-dir", str(root)])
            structured = StringIO()
            with redirect_stdout(structured):
                json_code = run_freshness(["--project-dir", str(root), "--json"])

            self.assertEqual(human_code, 0)
            self.assertEqual(json_code, 0)
            self.assertIn("Checkpoint freshness: current", human.getvalue())
            self.assertEqual(json.loads(structured.getvalue())["status"], "current")
            self.assertEqual(checkpoint_path.read_bytes(), before)
            self.assertEqual(list((root / ".project_memory").iterdir()), runs_before)

    def test_stale_and_no_checkpoint_also_return_zero_without_traceback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output = StringIO()
            with redirect_stdout(output):
                code = run_freshness(["--project-dir", str(root)])
            self.assertEqual(code, 0)
            self.assertIn("no_checkpoint", output.getvalue())

    @unittest.skipUnless(GIT_AVAILABLE, "Git executable is unavailable")
    def test_stale_and_unknown_return_zero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            checkpoint_path = self.write_non_git_checkpoint(root)
            init_repository(root, commit=False)
            stale_output = StringIO()
            with redirect_stdout(stale_output):
                stale_code = run_freshness(["--project-dir", str(root)])
            checkpoint_path.write_text("{broken", encoding="utf-8")
            unknown_output = StringIO()
            with redirect_stdout(unknown_output):
                unknown_code = run_freshness(["--project-dir", str(root)])
        self.assertEqual(stale_code, 0)
        self.assertIn("Checkpoint freshness: stale", stale_output.getvalue())
        self.assertEqual(unknown_code, 0)
        self.assertIn("Checkpoint freshness: unknown", unknown_output.getvalue())

    def test_main_dispatches_freshness_command(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = StringIO()
            argv = ["pma", "freshness", "--project-dir", temp_dir, "--json"]
            with patch.object(sys, "argv", argv), redirect_stdout(output):
                code = main()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["status"], "no_checkpoint")

    def test_missing_project_directory_is_clean_cli_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing"
            stderr = StringIO()
            with redirect_stderr(stderr), self.assertRaises(SystemExit) as raised:
                run_freshness(["--project-dir", str(missing)])
        self.assertEqual(raised.exception.code, 2)
        self.assertNotIn("Traceback", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
