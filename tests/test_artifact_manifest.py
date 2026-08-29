import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import checkpoint
from artifact_manifest import (
    build_artifact_manifest,
    validate_artifact_manifest,
)
from freshness import check_checkpoint_freshness
from scan_project import scan_project
from scanner_config import ScannerConfig
from tests.test_checkpoint_git_context import fake_extract_state


class ArtifactManifestTests(unittest.TestCase):
    def test_manifest_is_deterministic_sorted_and_privacy_safe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "b.md").write_text("b", encoding="utf-8")
            (root / "a.md").write_text("a", encoding="utf-8")
            config = ScannerConfig()
            index = scan_project(root, config)
            first = build_artifact_manifest(root, index, config)
            second = build_artifact_manifest(root, index, config)
            validate_artifact_manifest(first)
            encoded = json.dumps(first)
        self.assertEqual(first, second)
        self.assertEqual(
            [entry["path"] for entry in first["artifacts"]],
            ["a.md", "b.md"],
        )
        self.assertEqual(first["project_path"], ".")
        self.assertNotIn(str(root), encoded)
        self.assertTrue(
            all(entry["status"] == "hashed" for entry in first["artifacts"])
        )

    def test_malformed_or_absolute_manifest_path_is_rejected(self):
        invalid = {
            "schema_version": 1,
            "project_path": ".",
            "config_fingerprint": "a" * 64,
            "artifacts": [
                {
                    "path": "/private/file.md",
                    "artifact_type": "markdown",
                    "size_bytes": 1,
                    "sha256": "b" * 64,
                    "status": "hashed",
                }
            ],
        }
        with self.assertRaises(ValueError):
            validate_artifact_manifest(invalid)


class NonGitFreshnessTests(unittest.TestCase):
    def checkpoint(self, root: Path, suffix: str = "manifest1") -> Path:
        with patch("checkpoint.extract_state", side_effect=fake_extract_state):
            checkpoint.run_checkpoint(
                project_dir=root,
                project_name=None,
                base_output_dir=None,
                model="unused",
                suffix_factory=lambda: suffix,
            )
        return root / ".project_memory" / "latest"

    def test_unchanged_non_git_project_is_current(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("same", encoding="utf-8")
            latest = self.checkpoint(root)
            result = check_checkpoint_freshness(root, checked_at="fixed")
            manifest = json.loads(
                (latest / "artifact_manifest.json").read_text(encoding="utf-8")
            )
        self.assertEqual(result.status, "current")
        self.assertEqual(result.reasons[0].code, "artifact_manifest_matches")
        self.assertEqual(manifest["artifacts"][0]["path"], "README.md")

    def test_content_addition_and_removal_are_stale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            readme = root / "README.md"
            readme.write_text("before", encoding="utf-8")
            self.checkpoint(root)
            readme.write_text("after", encoding="utf-8")
            modified = check_checkpoint_freshness(root, checked_at="fixed")
            (root / "new.md").write_text("new", encoding="utf-8")
            added = check_checkpoint_freshness(root, checked_at="fixed")
            readme.unlink()
            removed = check_checkpoint_freshness(root, checked_at="fixed")
        self.assertEqual(modified.status, "stale")
        self.assertIn("artifact_content_changed", [r.code for r in modified.reasons])
        self.assertIn("artifact_added", [r.code for r in added.reasons])
        self.assertIn("artifact_removed", [r.code for r in removed.reasons])

    def test_scanner_config_change_is_stale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("same", encoding="utf-8")
            self.checkpoint(root)
            (root / "pma.toml").write_text(
                "[scanner]\nmax_artifacts = 400\n",
                encoding="utf-8",
            )
            result = check_checkpoint_freshness(root, checked_at="fixed")
        self.assertEqual(result.status, "stale")
        self.assertEqual(result.reasons[0].code, "scanner_config_changed")

    def test_old_non_git_checkpoint_without_manifest_is_unknown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            latest = root / ".project_memory" / "latest"
            latest.mkdir(parents=True)
            (latest / "git_context.json").write_text(
                json.dumps(
                    {
                        "schema_version": 2,
                        "available": False,
                        "reason": "not_a_git_repository",
                        "repository_root": None,
                        "branch": None,
                        "head_commit": None,
                        "head_commit_short": None,
                        "head_commit_subject": None,
                        "working_tree_clean": None,
                        "detached_head": None,
                        "staged_files": [],
                        "unstaged_files": [],
                        "untracked_files": [],
                        "conflicted_files": [],
                        "changed_files": [],
                        "file_fingerprints": [],
                        "collected_at": "checkpoint",
                    }
                ),
                encoding="utf-8",
            )
            result = check_checkpoint_freshness(root, checked_at="fixed")
        self.assertEqual(result.status, "unknown")
        self.assertEqual(result.reasons[0].code, "artifact_manifest_missing")


if __name__ == "__main__":
    unittest.main()
