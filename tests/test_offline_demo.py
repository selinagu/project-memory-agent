from __future__ import annotations

import hashlib
from io import StringIO
import os
from pathlib import Path
import re
import socket
import tempfile
import unittest
from unittest.mock import patch

from demo.offline.run_smoke import (
    EXPECTED_CITATION,
    FIXTURE_ROOT,
    REQUIRED_CHECKPOINT_FILES,
    run_demo,
)


POSIX_HOME_PATH = re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+/")
WINDOWS_USER_PATH = re.compile(r"(?i)[A-Z]:[\\/]Users[\\/][^\\/\s]+[\\/]")


def _fixture_digest() -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in FIXTURE_ROOT.rglob("*") if item.is_file()):
        digest.update(path.relative_to(FIXTURE_ROOT).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


class OfflineDemoSmokeTests(unittest.TestCase):
    def _run_network_blocked(self, parent: Path) -> tuple[object, str]:
        stream = StringIO()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            with patch(
                "socket.create_connection",
                side_effect=AssertionError("demo attempted a network connection"),
            ), patch.object(
                socket.socket,
                "connect",
                side_effect=AssertionError("demo attempted a socket connection"),
            ):
                result = run_demo(stream=stream, temp_parent=parent)
        return result, stream.getvalue()

    def test_demo_runs_real_checkpoint_query_and_freshness_without_network(self):
        before = _fixture_digest()
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            result, output = self._run_network_blocked(parent)
            self.assertEqual(list(parent.iterdir()), [])

        self.assertEqual(_fixture_digest(), before)
        self.assertEqual(result.checkpoint_status, "available")
        self.assertEqual(result.initial_freshness, "current")
        self.assertEqual(result.final_freshness, "stale")
        self.assertIn("checkpoint", result.final_recommendation)
        self.assertEqual(result.checkpoint_files, REQUIRED_CHECKPOINT_FILES)
        self.assertIn(EXPECTED_CITATION, result.answer)
        for number in range(1, 7):
            self.assertIn(f"[{number}/6]", output)
        self.assertIn("Freshness: stale", output)
        self.assertIn("create a new checkpoint", output.casefold())
        self.assertNotRegex(output, POSIX_HOME_PATH)
        self.assertNotRegex(output, WINDOWS_USER_PATH)
        self.assertNotIn(temp_dir, output)

    def test_demo_output_is_stable_across_runs(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            parent = Path(temp_dir)
            _, first = self._run_network_blocked(parent)
            _, second = self._run_network_blocked(parent)

        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
