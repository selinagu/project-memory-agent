import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import checkpoint
import checkpoint_store
from checkpoint_store import (
    CheckpointStoreError,
    generate_run_id,
    replace_directory_transactionally,
    validate_successful_run,
)
from progress_window import parse_run_date
from project_layout import resolve_checkpoint_layout
from tests.test_checkpoint_git_context import fake_extract_state


FIXED_NOW = datetime(2026, 8, 30, 1, 2, 3, 456789, tzinfo=timezone.utc)


class RunIdTests(unittest.TestCase):
    def test_run_id_is_utc_sortable_and_accepts_injected_factories(self):
        first = generate_run_id(
            now_factory=lambda: FIXED_NOW,
            suffix_factory=lambda: "00000001",
        )
        second = generate_run_id(
            now_factory=lambda: FIXED_NOW,
            suffix_factory=lambda: "00000002",
        )
        self.assertEqual(first, "2026-08-30_010203_456789_00000001")
        self.assertLess(first, second)
        self.assertEqual(parse_run_date(first).isoformat(), "2026-08-30")

    def test_invalid_injected_suffix_is_rejected(self):
        with self.assertRaises(ValueError):
            generate_run_id(
                now_factory=lambda: FIXED_NOW,
                suffix_factory=lambda: "../bad",
            )


class DirectoryTransactionTests(unittest.TestCase):
    def test_copy_failure_preserves_old_destination(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "run"
            destination = root / "latest"
            source.mkdir()
            destination.mkdir()
            (source / "value").write_text("new", encoding="utf-8")
            (destination / "value").write_text("old", encoding="utf-8")
            with patch(
                "checkpoint_store.shutil.copytree",
                side_effect=OSError("copy failed"),
            ):
                with self.assertRaisesRegex(OSError, "copy failed"):
                    replace_directory_transactionally(
                        source,
                        destination,
                        copy_source=True,
                    )
            self.assertEqual((destination / "value").read_text(encoding="utf-8"), "old")
            self.assertEqual(list(root.glob(".latest.*")), [])

    def test_final_rename_failure_rolls_back_old_destination(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "run"
            destination = root / "latest"
            source.mkdir()
            destination.mkdir()
            (source / "value").write_text("new", encoding="utf-8")
            (destination / "value").write_text("old", encoding="utf-8")
            real_replace = os.replace

            def fail_prepared_publish(source_path, destination_path):
                source_path = Path(source_path)
                destination_path = Path(destination_path)
                if source_path.name.startswith(".latest.prepared-") and destination_path == destination:
                    raise OSError("rename failed")
                return real_replace(source_path, destination_path)

            with patch("checkpoint_store.os.replace", side_effect=fail_prepared_publish):
                with self.assertRaisesRegex(OSError, "rename failed"):
                    replace_directory_transactionally(
                        source,
                        destination,
                        copy_source=True,
                    )
            self.assertEqual((destination / "value").read_text(encoding="utf-8"), "old")
            self.assertEqual(list(root.glob(".latest.*")), [])


class CheckpointTransactionTests(unittest.TestCase):
    def _run(self, project: Path, storage: Path, suffix: str) -> None:
        with patch("checkpoint.extract_state", side_effect=fake_extract_state):
            checkpoint.run_checkpoint(
                project_dir=project,
                project_name="memory",
                base_output_dir=storage,
                model="test-model",
                now_factory=lambda: FIXED_NOW,
                suffix_factory=lambda: suffix,
            )

    def test_success_is_complete_metadata_backed_and_published_once(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            (project / "README.md").write_text("source", encoding="utf-8")
            storage = root / "storage"
            self._run(project, storage, "00000001")
            layout = resolve_checkpoint_layout(
                project,
                project_name="memory",
                base_output_dir=storage,
            )
            runs = list(layout.runs_dir.iterdir())
            metadata = json.loads(
                (runs[0] / "run_metadata.json").read_text(encoding="utf-8")
            )
            validate_successful_run(runs[0])
            validate_successful_run(layout.latest_dir)
            encoded = json.dumps(metadata)
            self.assertEqual(len(runs), 1)
            self.assertEqual(metadata["status"], "succeeded")
            self.assertEqual(metadata["stage"], "complete")
            self.assertEqual(metadata["model"], "test-model")
            self.assertEqual(metadata["project_path"], ".")
            self.assertEqual(metadata["checkpoint_path"], "external")
            self.assertEqual(metadata["artifact_count"], 1)
            self.assertNotIn(str(root), encoded)
            self.assertFalse(layout.building_dir.exists())
            self.assertFalse(layout.failed_runs_dir.exists())

    def test_extraction_failure_preserves_latest_and_archives_failed_run(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            (project / "README.md").write_text("source", encoding="utf-8")
            storage = root / "storage"
            self._run(project, storage, "00000001")
            layout = resolve_checkpoint_layout(
                project,
                project_name="memory",
                base_output_dir=storage,
            )
            before = {
                path.relative_to(layout.latest_dir).as_posix(): path.read_bytes()
                for path in layout.latest_dir.rglob("*")
                if path.is_file()
            }
            with patch(
                "checkpoint.extract_state",
                side_effect=RuntimeError("simulated extraction failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "simulated extraction"):
                    checkpoint.run_checkpoint(
                        project_dir=project,
                        project_name="memory",
                        base_output_dir=storage,
                        model="test-model",
                        now_factory=lambda: FIXED_NOW,
                        suffix_factory=lambda: "00000002",
                    )
            after = {
                path.relative_to(layout.latest_dir).as_posix(): path.read_bytes()
                for path in layout.latest_dir.rglob("*")
                if path.is_file()
            }
            failed = list(layout.failed_runs_dir.iterdir())
            failed_metadata = json.loads(
                (failed[0] / "run_metadata.json").read_text(encoding="utf-8")
            )
            self.assertEqual(before, after)
            self.assertEqual(len(list(layout.runs_dir.iterdir())), 1)
            self.assertEqual(len(failed), 1)
            self.assertEqual(failed_metadata["status"], "failed")
            self.assertEqual(failed_metadata["stage"], "scan_and_extract")
            self.assertEqual(
                failed_metadata["error_code"],
                "scan_and_extract_failed",
            )
            self.assertFalse(layout.building_dir.exists() and any(layout.building_dir.iterdir()))

    def test_incomplete_run_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            run_dir = Path(temp_dir)
            with self.assertRaisesRegex(CheckpointStoreError, "missing required"):
                validate_successful_run(run_dir)

    def test_legacy_failure_preserves_previous_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            (project / "README.md").write_text("source", encoding="utf-8")
            output = project / "legacy"
            output.mkdir()
            (output / "keep.txt").write_text("old", encoding="utf-8")
            with patch(
                "checkpoint.extract_state",
                side_effect=RuntimeError("legacy failure"),
            ):
                with self.assertRaisesRegex(RuntimeError, "legacy failure"):
                    checkpoint.run_checkpoint_legacy(project, output, "test-model")
            self.assertEqual((output / "keep.txt").read_text(encoding="utf-8"), "old")
            self.assertEqual(list(project.glob(".legacy.building-*")), [])


if __name__ == "__main__":
    unittest.main()
