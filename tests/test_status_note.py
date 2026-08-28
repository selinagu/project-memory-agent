import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pma
from status_note import (
    StatusNoteError,
    build_status_note,
    load_latest_memory,
    resolve_latest_dir,
    write_status_note,
)


PROJECT_STATE = {
    "project_name": "Status Lab",
    "one_sentence_summary": "Keep status notes checkpoint-friendly.",
    "goal": "Record milestones before checkpointing.",
    "current_stage": "Testing status-note generation.",
    "confirmed_findings": ["Status notes improve checkpoint focus."],
    "tentative_hypotheses": ["Templates may reduce forgotten milestones."],
    "important_decisions": [],
    "failed_attempts": ["A prior checkpoint missed the intended focus."],
    "open_questions": ["Should status notes be required before release?"],
    "next_actions": ["Run status-note tests."],
    "evidence": [
        {
            "source": "PROJECT_STATUS.md",
            "quote_or_summary": "Status-note workflow is recorded.",
        }
    ],
    "last_updated": None,
}


def make_latest(project_dir: Path) -> Path:
    latest = project_dir / ".project_memory" / "latest"
    latest.mkdir(parents=True)
    return latest


class StatusNoteTests(unittest.TestCase):
    def test_template_generation_when_no_latest_checkpoint_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            note = build_status_note(Path(temp_dir), from_latest=False)

        self.assertIn("# Project Status", note)
        self.assertIn("## Project overview", note)
        self.assertIn("TODO: Describe the project", note)

    def test_from_latest_missing_checkpoint_returns_template_with_missing_note(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            note = build_status_note(Path(temp_dir), from_latest=True)

        self.assertIn("# Project Status", note)
        self.assertIn("No latest checkpoint found", note)
        self.assertIn("Missing latest checkpoint files", note)

    def test_generation_from_minimal_project_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = make_latest(project_dir)
            (latest / "project_state.json").write_text(
                json.dumps(PROJECT_STATE),
                encoding="utf-8",
            )

            note = build_status_note(project_dir, from_latest=True)

        self.assertIn("- Project: Status Lab", note)
        self.assertIn("Status notes improve checkpoint focus.", note)
        self.assertIn("Tentative hypothesis: Templates may reduce", note)
        self.assertIn("Failed / blocked attempt: A prior checkpoint", note)
        self.assertIn("Open question: Should status notes", note)
        self.assertIn("Run status-note tests.", note)
        self.assertIn("`PROJECT_STATUS.md`: Status-note workflow", note)

    def test_progress_since_last_is_included_when_present(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = make_latest(project_dir)
            (latest / "project_state.json").write_text(
                json.dumps(PROJECT_STATE),
                encoding="utf-8",
            )
            (latest / "progress_since_last.md").write_text(
                "# Progress Since Last Checkpoint\n\n"
                "- Added deterministic status-note generation.",
                encoding="utf-8",
            )

            note = build_status_note(project_dir, from_latest=True)

        self.assertIn("Added deterministic status-note generation", note)

    def test_checkpoint_summary_is_used_when_progress_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = make_latest(project_dir)
            (latest / "project_state.json").write_text(
                json.dumps(PROJECT_STATE),
                encoding="utf-8",
            )
            (latest / "checkpoint_summary.md").write_text(
                "# Checkpoint Summary\n\n- Restored the canonical layout.",
                encoding="utf-8",
            )

            note = build_status_note(project_dir, from_latest=True)

        self.assertIn("Restored the canonical layout", note)

    def test_write_creates_output_when_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "PROJECT_STATUS.md"

            write_status_note(output, "# Project Status\n")

            self.assertEqual(output.read_text(encoding="utf-8"), "# Project Status\n")

    def test_write_refuses_to_overwrite_without_force(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "PROJECT_STATUS.md"
            output.write_text("existing", encoding="utf-8")

            with self.assertRaisesRegex(StatusNoteError, "Refusing to overwrite"):
                write_status_note(output, "new")

            self.assertEqual(output.read_text(encoding="utf-8"), "existing")

    def test_force_overwrites_existing_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "PROJECT_STATUS.md"
            output.write_text("existing", encoding="utf-8")

            write_status_note(output, "new", force=True)

            self.assertEqual(output.read_text(encoding="utf-8"), "new")

    def test_load_latest_memory_reports_missing_optional_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = make_latest(project_dir)
            (latest / "project_state.json").write_text(
                json.dumps(PROJECT_STATE),
                encoding="utf-8",
            )

            memory = load_latest_memory(project_dir)

        self.assertEqual(
            memory.missing,
            ("checkpoint_summary.md", "progress_since_last.md"),
        )
        self.assertEqual(memory.project_state["project_name"], "Status Lab")

    def test_default_latest_dir_is_under_project_memory_latest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)

            latest_dir = resolve_latest_dir(project_dir)

            self.assertEqual(
                latest_dir,
                (project_dir / ".project_memory" / "latest").resolve(),
            )

    def test_custom_relative_latest_dir_is_resolved_under_project_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            custom_latest = project_dir / "memory" / "latest"
            custom_latest.mkdir(parents=True)
            (custom_latest / "project_state.json").write_text(
                json.dumps(PROJECT_STATE),
                encoding="utf-8",
            )

            note = build_status_note(
                project_dir,
                from_latest=True,
                latest_dir=Path("memory/latest"),
            )

            self.assertIn("- Project: Status Lab", note)

    def test_custom_absolute_latest_dir_is_used_directly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "project"
            external_latest = Path(temp_dir) / "external" / "latest"
            external_latest.mkdir(parents=True)
            (external_latest / "project_state.json").write_text(
                json.dumps(PROJECT_STATE),
                encoding="utf-8",
            )

            note = build_status_note(
                project_dir,
                from_latest=True,
                latest_dir=external_latest,
            )

        self.assertIn("- Project: Status Lab", note)

    def test_missing_external_latest_uses_privacy_safe_label(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir) / "project"
            external_latest = Path(temp_dir) / "external-memory" / "latest"
            project_dir.mkdir()

            note = build_status_note(
                project_dir,
                from_latest=True,
                latest_dir=external_latest,
            )

        self.assertIn("No latest checkpoint found at external.", note)
        self.assertNotIn(str(external_latest), note)

    def test_cli_prints_preview_without_writing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = StringIO()

            with redirect_stdout(output):
                exit_code = pma.run_status_note(["--project-dir", temp_dir])

            self.assertEqual(exit_code, 0)
            self.assertIn("# Project Status", output.getvalue())
            self.assertFalse((Path(temp_dir) / "PROJECT_STATUS.md").exists())

    def test_cli_write_creates_default_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = StringIO()

            with (
                patch.object(pma, "build_status_note", return_value="# Project Status\n"),
                redirect_stdout(output),
            ):
                exit_code = pma.run_status_note(["--project-dir", temp_dir, "--write"])

            self.assertEqual(exit_code, 0)
            self.assertTrue((Path(temp_dir) / "PROJECT_STATUS.md").exists())
            self.assertIn("Wrote status note", output.getvalue())

    def test_cli_refuses_to_overwrite_existing_output_without_force(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "PROJECT_STATUS.md"
            output.write_text("existing", encoding="utf-8")
            error = StringIO()

            with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                pma.run_status_note(["--project-dir", temp_dir, "--write"])

            self.assertEqual(raised.exception.code, 2)
            self.assertIn("Refusing to overwrite", error.getvalue())

    def test_cli_rejects_latest_dir_without_from_latest(self):
        error = StringIO()

        with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            pma.run_status_note(["--latest-dir", ".project_memory/latest"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--latest-dir requires --from-latest", error.getvalue())

    def test_cli_routes_main_status_note_subcommand(self):
        output = StringIO()
        with (
            patch.object(pma, "run_status_note", return_value=0) as run_status_note,
            patch.object(pma.sys, "argv", ["pma", "status-note", "--project-dir", "."]),
            redirect_stdout(output),
        ):
            exit_code = pma.main()

        self.assertEqual(exit_code, 0)
        run_status_note.assert_called_once_with(["--project-dir", "."])


if __name__ == "__main__":
    unittest.main()
