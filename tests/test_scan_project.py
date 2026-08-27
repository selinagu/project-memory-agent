import tempfile
import unittest
from pathlib import Path

from scan_project import scan_project
from scanner_config import ScannerConfig


PMA_SCOPE_CONFIG = """[scanner]
exclude = [
  "evals/private/**",
  "evals/private_outputs/**",
  "evals/outputs/**",
  "evals/public/**/input/**",
  "evals/public/**/fixture/**",
  "evals/public/**/v1/**",
  "evals/public/**/v2/**",
  "data/raw/**",
  "data/projects/**",
  "outputs/**",
]
"""


class ScanProjectIgnoreTests(unittest.TestCase):
    def scan_paths(self, files: list[str], config_text: str | None = None) -> set[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for file_path in files:
                path = root / file_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("content", encoding="utf-8")
            if config_text is not None:
                (root / "pma.toml").write_text(config_text, encoding="utf-8")

            index = scan_project(root)

        return {artifact.path for artifact in index.artifacts}

    def test_excludes_private_eval_inputs(self):
        paths = self.scan_paths(
            [
                "evals/private/case/input/notes.md",
                "evals/public/case/notes.md",
            ],
            PMA_SCOPE_CONFIG,
        )

        self.assertNotIn("evals/private/case/input/notes.md", paths)
        self.assertIn("evals/public/case/notes.md", paths)

    def test_excludes_private_eval_outputs(self):
        paths = self.scan_paths(
            [
                "evals/private_outputs/run/result.md",
                "evals/public/case/gold.yaml",
                "README.md",
            ],
            PMA_SCOPE_CONFIG,
        )

        self.assertNotIn("evals/private_outputs/run/result.md", paths)
        self.assertIn("README.md", paths)

    def test_excludes_project_memory_directories(self):
        paths = self.scan_paths(
            [
                ".project_memory/latest/project_state.json",
                "evals/public/query_memo/case/input/.project_memory/latest/project_state.json",
                "notes.md",
            ]
        )

        self.assertNotIn(".project_memory/latest/project_state.json", paths)
        self.assertNotIn(
            "evals/public/query_memo/case/input/.project_memory/latest/project_state.json",
            paths,
        )
        self.assertIn("notes.md", paths)


class ScanProjectConfigTests(unittest.TestCase):
    FILES = [
        "README.md",
        "notes.txt",
        "docs/overview.md",
        "docs/nested/design.md",
        "docs/image.png",
        "results/metrics.json",
        "results/debug/raw.json",
        "archive/old.md",
        "script.py",
        ".project_memory/hidden.md",
        "src/project_memory_agent.egg-info/SOURCES.txt",
    ]

    def scan_paths(self, files: list[str], config_text: str | None = None) -> set[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for file_path in files:
                path = root / file_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("content", encoding="utf-8")
            if config_text is not None:
                (root / "pma.toml").write_text(config_text, encoding="utf-8")
            index = scan_project(root)
        return {artifact.path for artifact in index.artifacts}

    def scan(self, config: ScannerConfig | None) -> set[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for file_path in self.FILES:
                path = root / file_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("content", encoding="utf-8")
            index = scan_project(root, config)
            return {artifact.path for artifact in index.artifacts}

    def test_no_config_preserves_default_results(self):
        self.assertEqual(self.scan(None), self.scan(ScannerConfig()))

    def test_include_patterns_restrict_and_use_or_semantics(self):
        paths = self.scan(ScannerConfig(("README.md", "docs/**/*.md")))
        self.assertEqual(paths, {"README.md", "docs/overview.md", "docs/nested/design.md"})

    def test_exclude_only_removes_matches_with_or_semantics(self):
        paths = self.scan(ScannerConfig(exclude_patterns=("archive/**", "results/debug/**")))
        self.assertNotIn("archive/old.md", paths)
        self.assertNotIn("results/debug/raw.json", paths)
        self.assertIn("results/metrics.json", paths)

    def test_exclude_overrides_include(self):
        paths = self.scan(
            ScannerConfig(("results/**/*.json",), ("results/debug/**",))
        )
        self.assertEqual(paths, {"results/metrics.json"})

    def test_safety_ignores_and_extensions_override_include(self):
        paths = self.scan(ScannerConfig(("**",)))
        self.assertNotIn(".project_memory/hidden.md", paths)
        self.assertNotIn("src/project_memory_agent.egg-info/SOURCES.txt", paths)
        self.assertNotIn("script.py", paths)
        self.assertNotIn("docs/image.png", paths)

    def test_config_is_loaded_relative_to_project_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("readme", encoding="utf-8")
            (root / "notes.md").write_text("notes", encoding="utf-8")
            (root / "pma.toml").write_text(
                '[scanner]\ninclude = ["README.md"]\n', encoding="utf-8"
            )
            paths = {artifact.path for artifact in scan_project(root).artifacts}
        self.assertEqual(paths, {"README.md"})

    def test_excludes_env_file(self):
        paths = self.scan_paths([".env", ".env.md", "notes.md"])

        self.assertNotIn(".env", paths)
        self.assertIn(".env.md", paths)
        self.assertIn("notes.md", paths)

    def test_excludes_raw_and_project_data_notes(self):
        paths = self.scan_paths(
            [
                "data/raw/private_notes.md",
                "data/projects/private_project/notes.md",
                "data/examples/public_example.md",
            ],
            PMA_SCOPE_CONFIG,
        )

        self.assertNotIn("data/raw/private_notes.md", paths)
        self.assertNotIn("data/projects/private_project/notes.md", paths)
        self.assertIn("data/examples/public_example.md", paths)

    def test_excludes_public_eval_fixture_inputs_and_outputs(self):
        paths = self.scan_paths(
            [
                "evals/public/cache_optimizer/state_reconstruction/input/notes.md",
                "evals/public/cache_optimizer/state_reconstruction/fixture/project_state.json",
                "evals/public/cache_optimizer/progress_case/v1/notes.md",
                "evals/public/cache_optimizer/progress_case/v2/notes.md",
                "evals/public/cache_optimizer/state_reconstruction/README.md",
            ],
            PMA_SCOPE_CONFIG,
        )

        self.assertNotIn(
            "evals/public/cache_optimizer/state_reconstruction/input/notes.md",
            paths,
        )
        self.assertNotIn(
            "evals/public/cache_optimizer/state_reconstruction/fixture/project_state.json",
            paths,
        )
        self.assertNotIn(
            "evals/public/cache_optimizer/progress_case/v1/notes.md",
            paths,
        )
        self.assertNotIn(
            "evals/public/cache_optimizer/progress_case/v2/notes.md",
            paths,
        )
        self.assertIn(
            "evals/public/cache_optimizer/state_reconstruction/README.md",
            paths,
        )

    def test_includes_repo_status_and_eval_docs(self):
        paths = self.scan_paths(
            [
                "PROJECT_STATUS.md",
                "evals/README.md",
                "evals/public/query_memo/case/input/.project_memory/latest/project_state.json",
            ],
            PMA_SCOPE_CONFIG,
        )

        self.assertIn("PROJECT_STATUS.md", paths)
        self.assertIn("evals/README.md", paths)
        self.assertNotIn(
            "evals/public/query_memo/case/input/.project_memory/latest/project_state.json",
            paths,
        )


if __name__ == "__main__":
    unittest.main()
