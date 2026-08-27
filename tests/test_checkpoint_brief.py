import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from pma import main, run_brief
from tests.test_brief import make_latest
from tests.test_git_context import GIT_AVAILABLE, init_repository


def tree_snapshot(root: Path):
    result = {}
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        stat = path.stat()
        result[relative] = (
            "dir" if path.is_dir() else "file",
            stat.st_mtime_ns,
            path.read_bytes() if path.is_file() else None,
        )
    return result


class BriefCliTests(unittest.TestCase):
    def test_human_and_json_missing_checkpoint_exit_zero(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            human = StringIO()
            with redirect_stdout(human):
                human_code = run_brief(["--project-dir", temp_dir])
            structured = StringIO()
            with redirect_stdout(structured):
                json_code = run_brief(["--project-dir", temp_dir, "--json"])
        self.assertEqual(human_code, 0)
        self.assertEqual(json_code, 0)
        self.assertIn("Checkpoint: missing", human.getvalue())
        payload = json.loads(structured.getvalue())
        self.assertEqual(payload["checkpoint"]["status"], "missing")
        self.assertEqual(payload["freshness"]["status"], "no_checkpoint")
        self.assertEqual(payload["recommendation"]["code"], "create_initial_checkpoint")

    def test_main_dispatches_brief_and_json_stdout_is_json_only(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = StringIO()
            with patch.object(sys, "argv", ["pma", "brief", "--project-dir", temp_dir, "--json"]):
                with redirect_stdout(output):
                    code = main()
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["schema_version"], 1)
        self.assertTrue(output.getvalue().lstrip().startswith("{"))

    def test_incomplete_and_invalid_are_ordinary_zero_exit_states(self):
        for mode in ("incomplete", "invalid"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                latest = make_latest(root)
                if mode == "incomplete":
                    (latest / "checkpoint_summary.md").unlink()
                else:
                    (latest / "git_context.json").write_text("{broken", encoding="utf-8")
                output = StringIO()
                with redirect_stdout(output):
                    code = run_brief(["--project-dir", temp_dir, "--json"])
                payload = json.loads(output.getvalue())
                self.assertEqual(code, 0)
                self.assertEqual(payload["checkpoint"]["status"], mode)
                self.assertEqual(payload["recommendation"]["code"], "rebuild_checkpoint")

    def test_missing_project_directory_is_clean_cli_error(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing"
            error = StringIO()
            with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                run_brief(["--project-dir", str(missing)])
        self.assertEqual(raised.exception.code, 2)
        self.assertNotIn("Traceback", error.getvalue())

    def test_brief_is_read_only_and_does_not_call_openai_or_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_latest(root)
            note = root / "PROJECT_STATUS.md"
            note.write_text("# Existing note\n", encoding="utf-8")
            before = tree_snapshot(root)
            output = StringIO()
            with (
                patch("checkpoint.run_checkpoint_with_history", side_effect=AssertionError("checkpoint called")),
                patch("checkpoint.extract_state", side_effect=AssertionError("OpenAI path called")),
                redirect_stdout(output),
            ):
                code = run_brief(["--project-dir", str(root), "--json"])
            after = tree_snapshot(root)
        self.assertEqual(code, 0)
        json.loads(output.getvalue())
        self.assertEqual(before, after)

    @unittest.skipUnless(GIT_AVAILABLE, "Git executable is unavailable")
    def test_brief_does_not_refresh_git_index_metadata(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_repository(root)
            make_latest(root)
            before = tree_snapshot(root)
            with redirect_stdout(StringIO()):
                run_brief(["--project-dir", str(root), "--json"])
            after = tree_snapshot(root)
        self.assertEqual(before, after)

    def test_json_has_no_absolute_paths_or_content_recovery_fields(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_latest(root)
            output = StringIO()
            with redirect_stdout(output):
                run_brief(["--project-dir", str(root), "--json"])
            text = output.getvalue()
        self.assertNotIn(str(root), text)
        self.assertNotIn("confirmed_findings", text)
        self.assertNotIn("open_questions", text)
        self.assertNotIn("next_actions", text)


if __name__ == "__main__":
    unittest.main()
