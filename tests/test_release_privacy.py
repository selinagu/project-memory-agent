import io
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

from evals.scripts.check_release_privacy import scan_release_paths


class ReleasePrivacyTests(unittest.TestCase):
    def test_clean_placeholders_and_environment_lookups_pass(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "README.md"
            path.write_text(
                "OPENAI_" + "API_KEY=your_api_key\n"
                + "os.getenv('OPENAI_" + "API_KEY')\n",
                encoding="utf-8",
            )
            findings = scan_release_paths([path])
        self.assertEqual(findings, [])

    def test_sensitive_patterns_are_reported_without_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "bad.txt"
            path.write_text(
                "/" + "home/alice/private/project\n"
                + "C:" + "\\Users\\Alice\\private\\project\n"
                + "sk" + "-abcdefghijklmnopqrstuvwxyz123456\n"
                + "OPENAI_" + "API_KEY=real-secret-value\n"
                + "-----BEGIN " + "PRIVATE KEY-----\n",
                encoding="utf-8",
            )
            findings = scan_release_paths([path])
        self.assertEqual(
            {finding.rule for finding in findings},
            {
                "posix_home_path", "windows_user_path", "openai_token",
                "openai_api_key_assignment", "private_key",
            },
        )
        self.assertTrue(all(finding.path == "bad.txt" for finding in findings))
        self.assertNotIn("real-secret-value", repr(findings))

    def test_wheel_and_sdist_members_are_scanned_without_extraction(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            wheel = root / "sample.whl"
            with zipfile.ZipFile(wheel, "w") as archive:
                archive.writestr(
                    "package/module.py",
                    "PATH = '/" + "home/alice/work/'\n",
                )
            sdist = root / "sample.tar.gz"
            payload = b"OPENAI_" + b"API_KEY=actual-secret\n"
            info = tarfile.TarInfo("sample/config.txt")
            info.size = len(payload)
            with tarfile.open(sdist, "w:gz") as archive:
                archive.addfile(info, io.BytesIO(payload))
            wheel_findings = scan_release_paths([wheel])
            sdist_findings = scan_release_paths([sdist])
        self.assertEqual(wheel_findings[0].rule, "posix_home_path")
        self.assertIn("!package/module.py", wheel_findings[0].path)
        self.assertEqual(sdist_findings[0].rule, "openai_api_key_assignment")
        self.assertIn("!sample/config.txt", sdist_findings[0].path)


if __name__ == "__main__":
    unittest.main()
