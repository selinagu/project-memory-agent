import json
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import checkpoint
from schemas import ProjectState


def minimal_state() -> ProjectState:
    return ProjectState(
        project_name="test",
        one_sentence_summary="test",
        goal="test",
        current_stage="test",
    )


class CheckpointScannerConfigTests(unittest.TestCase):
    def test_checkpoint_automatically_loads_project_config(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "checkpoint"
            (root / "README.md").write_text("readme", encoding="utf-8")
            (root / "notes.md").write_text("notes", encoding="utf-8")
            (root / "pma.toml").write_text(
                '[scanner]\ninclude = ["README.md"]\n', encoding="utf-8"
            )

            with patch("checkpoint.extract_state", return_value=minimal_state()):
                checkpoint.write_checkpoint_outputs(root, output_dir, "unused")

            index = json.loads(
                (output_dir / "artifacts_index.json").read_text(encoding="utf-8")
            )

        self.assertEqual(
            [artifact["path"] for artifact in index["artifacts"]], ["README.md"]
        )

    def test_invalid_config_is_clear_and_does_not_touch_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "checkpoint"
            output_dir.mkdir()
            marker = output_dir / "existing.txt"
            marker.write_text("unchanged", encoding="utf-8")
            (root / "notes.md").write_text("notes", encoding="utf-8")
            (root / "pma.toml").write_text(
                '[scanner]\ninclude = "notes.md"\n', encoding="utf-8"
            )
            stderr = StringIO()
            argv = [
                "pma",
                "--project-dir",
                str(root),
                "--output-dir",
                str(output_dir),
            ]

            with patch.object(sys, "argv", argv), redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as raised:
                    checkpoint.main()

            self.assertEqual(raised.exception.code, 2)
            self.assertIn("pma.toml", stderr.getvalue())
            self.assertIn("list of strings", stderr.getvalue())
            self.assertNotIn("Traceback", stderr.getvalue())
            self.assertEqual(marker.read_text(encoding="utf-8"), "unchanged")
            self.assertEqual(list(output_dir.iterdir()), [marker])


if __name__ == "__main__":
    unittest.main()
