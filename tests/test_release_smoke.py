import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_SCRIPTS = REPO_ROOT / "evals" / "scripts"
sys.path.insert(0, str(EVAL_SCRIPTS))

from run_release_smoke import SmokeFailure, _json_object, run_checked


class ReleaseSmokeTests(unittest.TestCase):
    def test_run_checked_accepts_success_outside_repository(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            completed = run_checked(
                [sys.executable, "-c", "print('usage: synthetic')"],
                cwd=Path(temp_dir),
                label="synthetic help",
            )
        self.assertIn("usage: synthetic", completed.stdout)

    def test_run_checked_rejects_traceback_even_with_zero_exit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(SmokeFailure, "traceback"):
                run_checked(
                    [
                        sys.executable,
                        "-c",
                        "print('Traceback (most recent call last)')",
                    ],
                    cwd=Path(temp_dir),
                    label="synthetic traceback",
                )

    def test_json_contract_requires_an_object(self):
        self.assertEqual(_json_object('{"status": "pass"}', "report"), {"status": "pass"})
        with self.assertRaisesRegex(SmokeFailure, "must be an object"):
            _json_object("[]", "report")


if __name__ == "__main__":
    unittest.main()
