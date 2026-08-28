import tempfile
import unittest
from pathlib import Path

from scan_project import scan_project
from scanner_config import ScannerConfigError


def write_files(root: Path, paths: list[str]) -> None:
    for relative in paths:
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"synthetic content for {relative}\n", encoding="utf-8")


class ScannerDogfoodTests(unittest.TestCase):
    def artifact_paths(
        self,
        root: Path,
        *,
        checkpoint_root: Path | None = None,
    ) -> list[str]:
        return [
            artifact.path
            for artifact in scan_project(root, checkpoint_root=checkpoint_root).artifacts
        ]

    def test_root_document_repository_uses_safe_defaults(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_files(
                root,
                ["README.md", "PROJECT_STATUS.md", "notes.txt", "app.py", "image.png"],
            )
            paths = self.artifact_paths(root)

        self.assertEqual(paths, ["PROJECT_STATUS.md", "README.md", "notes.txt"])

    def test_nested_document_repository_dogfoods_double_star_and_exclusion(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_files(
                root,
                [
                    "docs/overview.md",
                    "docs/design/architecture.md",
                    "notes/daily.md",
                    "research/logs/run-01.log",
                    "research/logs/private/debug.log",
                    "archive/old.md",
                ],
            )
            (root / "pma.toml").write_text(
                "[scanner]\n"
                'include = ["docs/**/*.md", "notes/**", "research/**/logs/**/*.log"]\n'
                'exclude = ["research/**/private/**", "archive/**"]\n',
                encoding="utf-8",
            )
            paths = self.artifact_paths(root)

        self.assertEqual(
            paths,
            [
                "docs/design/architecture.md",
                "docs/overview.md",
                "notes/daily.md",
                "research/logs/run-01.log",
            ],
        )

    def test_mixed_repository_keeps_safety_ignores_mandatory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_files(
                root,
                [
                    "README.md",
                    ".env",
                    ".project_memory/latest/project_state.json",
                    ".venv/notes.md",
                    "src/package.egg-info/SOURCES.txt",
                    "private/notes.md",
                    "generated/result.json",
                    "docs/release.md",
                    "src/app.py",
                ],
            )
            (root / "pma.toml").write_text(
                "[scanner]\n"
                'include = ["**"]\n'
                'exclude = ["private/**", "generated/**"]\n',
                encoding="utf-8",
            )
            paths = self.artifact_paths(root)

        self.assertEqual(paths, ["README.md", "docs/release.md"])

    def test_active_internal_checkpoint_root_is_excluded(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            checkpoint_root = root / "memory" / "status-lab"
            write_files(
                root,
                [
                    "README.md",
                    "memory/status-lab/latest/project_state.json",
                    "memory/status-lab/runs/001/checkpoint_summary.md",
                    "memory/other-project/notes.md",
                ],
            )
            paths = self.artifact_paths(root, checkpoint_root=checkpoint_root)

        self.assertEqual(paths, ["README.md", "memory/other-project/notes.md"])

    def test_external_checkpoint_root_does_not_change_or_leak_artifact_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "project"
            external = Path(temp_dir) / "external-memory" / "status-lab"
            root.mkdir()
            external.mkdir(parents=True)
            write_files(root, ["README.md", "docs/notes.md"])

            paths = self.artifact_paths(root, checkpoint_root=external)

        self.assertEqual(paths, ["README.md", "docs/notes.md"])
        self.assertTrue(all(not Path(path).is_absolute() for path in paths))
        self.assertTrue(all("external-memory" not in path for path in paths))

    def test_repeated_scans_are_deterministic(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_files(root, ["z.md", "a.md", "nested/m.md", "nested/b.md"])

            first = self.artifact_paths(root)
            second = self.artifact_paths(root)

        self.assertEqual(first, second)
        self.assertEqual(first, sorted(first))

    def test_invalid_config_fails_before_scanning(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            write_files(root, ["README.md"])
            (root / "pma.toml").write_text(
                '[scanner]\nunknown = ["README.md"]\n',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ScannerConfigError, "unknown key"):
                scan_project(root)


if __name__ == "__main__":
    unittest.main()
