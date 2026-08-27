import tempfile
import unittest
from datetime import date
from pathlib import Path

from progress_window import (
    CheckpointRun,
    list_checkpoint_runs,
    load_progress_window,
    parse_run_date,
    parse_since_date,
    render_progress_window,
    select_recent_runs,
    select_runs_since,
)


class ProgressWindowTests(unittest.TestCase):
    def test_discovers_sorted_run_directories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            memory_dir = Path(temp_dir)
            runs_dir = memory_dir / "runs"
            runs_dir.mkdir()
            for timestamp in ("2026-07-03", "2026-07-01", "2026-07-02"):
                (runs_dir / timestamp).mkdir()
            (runs_dir / "not-a-run.txt").write_text("ignored", encoding="utf-8")

            runs = list_checkpoint_runs(memory_dir)

            self.assertEqual(
                [run.timestamp for run in runs],
                ["2026-07-01", "2026-07-02", "2026-07-03"],
            )

    def test_selects_last_n_in_chronological_order(self):
        runs = [
            CheckpointRun(timestamp=value, path=Path(value))
            for value in ("03", "01", "04", "02")
        ]

        selected = select_recent_runs(runs, 2)

        self.assertEqual([run.timestamp for run in selected], ["03", "04"])

    def test_loads_progress_and_records_missing_or_empty_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            runs = []
            for timestamp in ("01", "02", "03"):
                path = Path(temp_dir) / timestamp
                path.mkdir()
                runs.append(CheckpointRun(timestamp=timestamp, path=path))
            (runs[0].path / "progress_since_last.md").write_text(
                "First progress.",
                encoding="utf-8",
            )
            (runs[1].path / "progress_since_last.md").write_text(
                "",
                encoding="utf-8",
            )
            (runs[0].path / "project_state.json").write_text(
                "HISTORICAL_STATE_MUST_NOT_LOAD",
                encoding="utf-8",
            )
            (runs[0].path / "combined_notes.md").write_text(
                "HISTORICAL_COMBINED_MUST_NOT_LOAD",
                encoding="utf-8",
            )

            window = load_progress_window(runs, requested_last=3)
            rendered = render_progress_window(window)

            self.assertEqual(
                [entry.timestamp for entry in window.progress_entries],
                ["01"],
            )
            self.assertEqual(window.missing_progress_runs, ["02", "03"])
            self.assertIn("First progress.", rendered)
            self.assertNotIn("HISTORICAL_STATE_MUST_NOT_LOAD", rendered)
            self.assertNotIn("HISTORICAL_COMBINED_MUST_NOT_LOAD", rendered)

    def test_progress_context_is_bounded_and_marks_truncation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "01"
            path.mkdir()
            (path / "progress_since_last.md").write_text(
                "x" * 100,
                encoding="utf-8",
            )

            window = load_progress_window(
                [CheckpointRun(timestamp="01", path=path)],
                requested_last=1,
                max_entry_chars=20,
                max_total_chars=20,
            )

            self.assertTrue(window.truncated)
            self.assertEqual(len(window.progress_entries[0].text), 20)

    def test_parses_strict_since_date_and_supported_run_timestamps(self):
        self.assertEqual(parse_since_date("2026-07-01"), date(2026, 7, 1))
        for invalid in (
            "2026/07/01",
            "July 1",
            "bad-date",
            "2026-7-1",
            "2026-02-30",
        ):
            with self.assertRaises(ValueError):
                parse_since_date(invalid)

        self.assertEqual(parse_run_date("2026-07-01"), date(2026, 7, 1))
        self.assertEqual(
            parse_run_date("2026-07-01_123456"),
            date(2026, 7, 1),
        )
        self.assertEqual(
            parse_run_date("2026-07-01T123456"),
            date(2026, 7, 1),
        )
        self.assertIsNone(parse_run_date("not-a-timestamp"))

    def test_selects_runs_on_or_after_date_and_records_unparseable_names(self):
        runs = [
            CheckpointRun(timestamp=value, path=Path(value))
            for value in (
                "2026-07-03_090000",
                "not-a-timestamp",
                "2026-06-30_235959",
                "2026-07-01_000000",
                "2026-07-02",
            )
        ]

        selected, unparseable = select_runs_since(
            runs,
            date(2026, 7, 1),
        )

        self.assertEqual(
            [run.timestamp for run in selected],
            [
                "2026-07-01_000000",
                "2026-07-02",
                "2026-07-03_090000",
            ],
        )
        self.assertEqual(unparseable, ["not-a-timestamp"])


if __name__ == "__main__":
    unittest.main()
