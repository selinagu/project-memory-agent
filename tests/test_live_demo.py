from __future__ import annotations

import hashlib
import io
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
        self.assertEqual(report["gold_source_count"], 3)
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
