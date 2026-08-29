import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import checkpoint
from artifacts import ArtifactRecord
from parsers import parse_artifact
from project_layout import resolve_checkpoint_layout
from scan_project import scan_project
from scanner_config import (
    HARD_MAX_ARTIFACTS,
    ResourceBudgetError,
    ScannerConfig,
    ScannerConfigError,
    load_scanner_config,
)


class BudgetConfigurationTests(unittest.TestCase):
    def test_optional_budgets_load_as_positive_integers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "pma.toml").write_text(
                """[scanner]
max_artifacts = 12
max_non_python_file_bytes = 1024
max_total_source_bytes = 4096
max_combined_notes_chars = 2048
""",
                encoding="utf-8",
            )
            config = load_scanner_config(root)
        self.assertEqual(config.max_artifacts, 12)
        self.assertEqual(config.max_non_python_file_bytes, 1024)
        self.assertEqual(config.max_total_source_bytes, 4096)
        self.assertEqual(config.max_combined_notes_chars, 2048)

    def test_bool_zero_negative_and_hard_ceiling_are_rejected(self):
        values = ("true", "0", "-1", str(HARD_MAX_ARTIFACTS + 1))
        for value in values:
            with self.subTest(value=value), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                (root / "pma.toml").write_text(
                    f"[scanner]\nmax_artifacts = {value}\n",
                    encoding="utf-8",
                )
                with self.assertRaises(ScannerConfigError):
                    load_scanner_config(root)


class ScanBudgetTests(unittest.TestCase):
    def test_artifact_count_limit_fails_deterministically(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "b.md").write_text("b", encoding="utf-8")
            (root / "a.md").write_text("a", encoding="utf-8")
            with self.assertRaisesRegex(ResourceBudgetError, "artifact count"):
                scan_project(root, ScannerConfig(max_artifacts=1))

    def test_non_python_file_limit_checks_size_before_reading(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "large.md"
            path.write_bytes(b"x" * 9)
            with patch("scan_project.read_preview") as preview:
                with self.assertRaisesRegex(
                    ResourceBudgetError,
                    "large.md.*max_non_python_file_bytes",
                ):
                    scan_project(
                        root,
                        ScannerConfig(max_non_python_file_bytes=8),
                    )
            preview.assert_not_called()

    def test_total_source_byte_limit_fails_before_parsing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "a.md").write_bytes(b"a" * 6)
            (root / "b.md").write_bytes(b"b" * 6)
            with self.assertRaisesRegex(ResourceBudgetError, "total_source_bytes"):
                scan_project(
                    root,
                    ScannerConfig(
                        max_non_python_file_bytes=10,
                        max_total_source_bytes=10,
                    ),
                )

    def test_parser_rechecks_file_limit_with_bounded_read(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "changed.md").write_bytes(b"x" * 9)
            artifact = ArtifactRecord(
                path="changed.md",
                artifact_type="markdown",
                size_bytes=1,
                modified_time="2026-08-30T00:00:00+00:00",
            )
            with self.assertRaisesRegex(ResourceBudgetError, "changed.md"):
                parse_artifact(
                    root,
                    artifact,
                    max_non_python_file_bytes=8,
                )


class CheckpointBudgetTests(unittest.TestCase):
    def test_combined_note_limit_fails_before_openai_and_never_updates_latest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            (project / "README.md").write_text("a" * 80, encoding="utf-8")
            (project / "pma.toml").write_text(
                "[scanner]\nmax_combined_notes_chars = 20\n",
                encoding="utf-8",
            )
            storage = root / "storage"
            with patch("checkpoint.extract_state") as extract:
                with self.assertRaisesRegex(
                    ResourceBudgetError,
                    "max_combined_notes_chars",
                ):
                    checkpoint.run_checkpoint(
                        project_dir=project,
                        project_name="memory",
                        base_output_dir=storage,
                        model="unused",
                        suffix_factory=lambda: "budget001",
                    )
            extract.assert_not_called()
            layout = resolve_checkpoint_layout(
                project,
                project_name="memory",
                base_output_dir=storage,
            )
            failed = list(layout.failed_runs_dir.iterdir())
            metadata = json.loads(
                (failed[0] / "run_metadata.json").read_text(encoding="utf-8")
            )
            self.assertFalse(layout.latest_dir.exists())
            self.assertFalse(layout.runs_dir.exists())
            self.assertEqual(len(failed), 1)
            self.assertEqual(metadata["status"], "failed")
            self.assertEqual(metadata["stage"], "scan_and_extract")


if __name__ == "__main__":
    unittest.main()
