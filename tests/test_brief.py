import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import Mock

from brief import (
    BriefRecommendation,
    CheckpointHealth,
    StatusNoteHealth,
    build_brief,
    build_recommendation,
    inspect_checkpoint,
    inspect_status_note,
    render_brief_text,
)
from freshness import FreshnessReason, FreshnessResult
from git_context import collect_git_context


VALID_STATE = {
    "project_name": "Example",
    "one_sentence_summary": "An example project.",
    "goal": "Test checkpoint health.",
    "current_stage": "Validation",
    "confirmed_findings": [],
    "tentative_hypotheses": [],
    "important_decisions": [],
    "failed_attempts": [],
    "open_questions": [],
    "next_actions": ["This must not affect recommendations."],
    "evidence": [],
    "last_updated": None,
}


def make_latest(root: Path, *, collected_at: str = "2026-07-15T09:42:11Z") -> Path:
    latest = root / ".project_memory" / "latest"
    latest.mkdir(parents=True)
    (latest / "project_state.json").write_text(json.dumps(VALID_STATE), encoding="utf-8")
    (latest / "checkpoint_summary.md").write_text("# Checkpoint\n", encoding="utf-8")
    context = collect_git_context(root, collected_at=collected_at)
    (latest / "git_context.json").write_text(
        json.dumps(context.to_dict()), encoding="utf-8"
    )
    return latest


def freshness(status: str) -> FreshnessResult:
    return FreshnessResult(
        status=status,
        checked_at="2026-07-15T10:00:00Z",
        checkpoint_available=True,
    )


class CheckpointInspectionTests(unittest.TestCase):
    def test_missing_latest_is_missing_with_relative_sorted_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = inspect_checkpoint(Path(temp_dir))
        self.assertEqual(result.status, "missing")
        self.assertEqual(result.required_files, sorted(result.required_files))
        self.assertEqual(result.missing_files, result.required_files)
        self.assertTrue(all(not Path(path).is_absolute() for path in result.required_files))

    def test_complete_latest_is_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_latest(root)
            result = inspect_checkpoint(root)
        self.assertEqual(result.status, "available")
        self.assertEqual(result.missing_files, [])
        self.assertEqual(result.invalid_files, [])

    def test_each_missing_required_file_is_incomplete(self):
        for filename in ("project_state.json", "checkpoint_summary.md", "git_context.json"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                latest = make_latest(root)
                (latest / filename).unlink()
                result = inspect_checkpoint(root)
                self.assertEqual(result.status, "incomplete")
                self.assertEqual(result.missing_files, [f".project_memory/latest/{filename}"])

    def test_malformed_project_state_and_git_context_are_invalid(self):
        for filename in ("project_state.json", "git_context.json"):
            with self.subTest(filename=filename), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                latest = make_latest(root)
                (latest / filename).write_text("{broken", encoding="utf-8")
                result = inspect_checkpoint(root)
                self.assertEqual(result.status, "invalid")
                self.assertEqual(result.invalid_files, [f".project_memory/latest/{filename}"])

    def test_missing_and_invalid_lists_are_both_sorted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            latest = make_latest(root)
            (latest / "project_state.json").write_text("{}", encoding="utf-8")
            (latest / "checkpoint_summary.md").unlink()
            result = inspect_checkpoint(root)
        self.assertEqual(result.status, "incomplete")
        self.assertEqual(result.missing_files, sorted(result.missing_files))
        self.assertEqual(result.invalid_files, sorted(result.invalid_files))
        self.assertEqual(result.invalid_files, [".project_memory/latest/project_state.json"])

    def test_result_contains_no_absolute_project_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_latest(root)
            encoded = json.dumps(build_brief(root, checked_at="2026-07-15T10:00:00Z").to_dict())
        self.assertNotIn(str(root), encoded)


class TimestampTests(unittest.TestCase):
    def test_run_metadata_timestamp_has_precedence(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            latest = make_latest(root, collected_at="2026-07-14T01:00:00Z")
            (latest / "run_metadata.json").write_text(
                json.dumps({"created_at": "2026-07-15T12:00:00+08:00"}), encoding="utf-8"
            )
            result = inspect_checkpoint(root)
        self.assertEqual(result.created_at, "2026-07-15T04:00:00Z")
        self.assertEqual(result.timestamp_source, "run_metadata")

    def test_git_collected_at_is_structured_fallback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_latest(root, collected_at="2026-07-15T09:42:11+00:00")
            result = inspect_checkpoint(root)
        self.assertEqual(result.created_at, "2026-07-15T09:42:11Z")
        self.assertEqual(result.timestamp_source, "git_context.collected_at")

    def test_filesystem_fallback_is_utc(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            latest = make_latest(root, collected_at="not-a-time")
            target = datetime(2026, 7, 15, 9, 42, 11, tzinfo=timezone.utc).timestamp()
            for path in [latest, *(latest / name for name in (
                "project_state.json", "checkpoint_summary.md", "git_context.json"
            ))]:
                os.utime(path, (target, target))
            result = inspect_checkpoint(root)
        self.assertEqual(result.created_at, "2026-07-15T09:42:11Z")
        self.assertEqual(result.timestamp_source, "filesystem_fallback")

    def test_missing_checkpoint_has_null_timestamp(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = inspect_checkpoint(Path(temp_dir))
        self.assertIsNone(result.created_at)
        self.assertIsNone(result.timestamp_source)


class StatusNoteInspectionTests(unittest.TestCase):
    def test_missing_status_note(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = inspect_status_note(Path(temp_dir), "2026-07-15T09:00:00Z")
        self.assertEqual(result.path, "PROJECT_STATUS.md")
        self.assertFalse(result.exists)
        self.assertFalse(result.readable)
        self.assertIsNone(result.modified_after_checkpoint)

    def test_present_note_timing_before_and_after_checkpoint(self):
        checkpoint = "2026-07-15T09:00:00Z"
        for hour, expected in ((8, False), (10, True)):
            with self.subTest(hour=hour), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                note = root / "PROJECT_STATUS.md"
                note.write_text("Any content is accepted.\n", encoding="utf-8")
                stamp = datetime(2026, 7, 15, hour, tzinfo=timezone.utc).timestamp()
                os.utime(note, (stamp, stamp))
                result = inspect_status_note(root, checkpoint)
                self.assertTrue(result.exists)
                self.assertTrue(result.readable)
                self.assertEqual(result.modified_after_checkpoint, expected)

    def test_unknown_checkpoint_time_gives_unknown_comparison(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "PROJECT_STATUS.md").write_text("Not parsed semantically.", encoding="utf-8")
            result = inspect_status_note(root, None)
        self.assertIsNone(result.modified_after_checkpoint)
        self.assertNotIn("content", result.to_dict() if hasattr(result, "to_dict") else {})


class RecommendationTests(unittest.TestCase):
    def recommendation(self, checkpoint_status: str, freshness_status: str, note: StatusNoteHealth):
        checkpoint = CheckpointHealth(status=checkpoint_status)
        return build_recommendation(checkpoint, freshness(freshness_status), note)

    def test_missing_incomplete_and_invalid_precede_freshness(self):
        cases = {
            "missing": "create_initial_checkpoint",
            "incomplete": "rebuild_checkpoint",
            "invalid": "rebuild_checkpoint",
        }
        for checkpoint_status, code in cases.items():
            with self.subTest(checkpoint_status=checkpoint_status):
                result = self.recommendation(
                    checkpoint_status, "stale", StatusNoteHealth(exists=True, modified_after_checkpoint=True)
                )
                self.assertEqual(result.code, code)

    def test_stale_recommendations_follow_status_note_signal(self):
        cases = (
            (StatusNoteHealth(exists=True, modified_after_checkpoint=True), "run_checkpoint"),
            (StatusNoteHealth(exists=True, modified_after_checkpoint=False), "update_status_note_then_checkpoint"),
            (StatusNoteHealth(exists=True, modified_after_checkpoint=None), "update_status_note_then_checkpoint"),
            (StatusNoteHealth(exists=False), "create_status_note_then_checkpoint"),
        )
        for note, code in cases:
            with self.subTest(code=code):
                self.assertEqual(self.recommendation("available", "stale", note).code, code)

    def test_unknown_and_current_recommendations(self):
        note = StatusNoteHealth()
        self.assertEqual(
            self.recommendation("available", "unknown", note).code,
            "review_checkpoint_freshness",
        )
        self.assertEqual(
            self.recommendation("available", "current", note).code,
            "no_checkpoint_update_needed",
        )

    def test_existing_status_note_does_not_get_predictably_failing_write_command(self):
        result = self.recommendation(
            "available", "stale", StatusNoteHealth(exists=True, modified_after_checkpoint=False)
        )
        self.assertEqual(result.commands, ["pma checkpoint --project-dir ."])

    def test_missing_status_note_uses_valid_creation_then_checkpoint_commands(self):
        result = self.recommendation("available", "stale", StatusNoteHealth(exists=False))
        self.assertEqual(
            result.commands,
            [
                "pma status-note --project-dir . --from-latest --write",
                "pma checkpoint --project-dir .",
            ],
        )


class FreshnessIntegrationAndRenderingTests(unittest.TestCase):
    def test_missing_and_unhealthy_checkpoints_skip_freshness_checker(self):
        for mode in ("missing", "incomplete", "invalid"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                if mode != "missing":
                    latest = make_latest(root)
                    if mode == "incomplete":
                        (latest / "git_context.json").unlink()
                    else:
                        (latest / "project_state.json").write_text("{}", encoding="utf-8")
                checker = Mock(side_effect=AssertionError("freshness should not run"))
                result = build_brief(root, checked_at="fixed", freshness_checker=checker)
                checker.assert_not_called()
                self.assertNotEqual(result.freshness.status, "current")

    def test_available_checkpoint_reuses_and_preserves_freshness_result(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            make_latest(root)
            expected = FreshnessResult(
                status="stale",
                checked_at="fixed",
                checkpoint_available=True,
                reasons=[FreshnessReason("file_content_changed", "README.md changed.", "README.md")],
                checkpoint_head="a" * 40,
                current_head="b" * 40,
            )
            checker = Mock(return_value=expected)
            result = build_brief(root, checked_at="fixed", freshness_checker=checker)
        checker.assert_called_once()
        self.assertEqual(result.freshness, expected)
        self.assertEqual(result.to_dict()["freshness"]["reasons"][0]["path"], "README.md")

    def test_human_output_truncates_reasons_and_has_no_project_state_content(self):
        checkpoint = CheckpointHealth(status="available")
        stale = FreshnessResult(
            status="stale",
            checked_at="fixed",
            reasons=[FreshnessReason(f"code_{index}", f"Reason {index}") for index in range(7)],
        )
        note = StatusNoteHealth(exists=True, modified_after_checkpoint=False)
        from brief import BriefResult
        brief_result = BriefResult(
            1,
            "fixed",
            checkpoint,
            stale,
            note,
            build_recommendation(checkpoint, stale, note),
        )
        output = render_brief_text(brief_result)
        self.assertIn("Reason 4", output)
        self.assertNotIn("Reason 5", output)
        self.assertIn("+ 2 more reasons", output)
        self.assertNotIn("next_actions", output)
        self.assertNotIn("open questions", output.lower())

    def test_current_output_keeps_self_memo_separate_as_optional_recap(self):
        checkpoint = CheckpointHealth(status="available")
        current = freshness("current")
        note = StatusNoteHealth(exists=False)
        from brief import BriefResult
        result = BriefResult(
            1, "fixed", checkpoint, current, note, build_recommendation(checkpoint, current, note)
        )
        output = render_brief_text(result)
        self.assertIn("No checkpoint update is needed.", output)
        self.assertIn("pma memo --type self --project-dir .", output)


if __name__ == "__main__":
    unittest.main()
