import tempfile
import unittest
from pathlib import Path

from scan_project import scan_project


class ScanProjectIgnoreTests(unittest.TestCase):
    def scan_paths(self, files: list[str]) -> set[str]:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for file_path in files:
                path = root / file_path
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("content", encoding="utf-8")

            index = scan_project(root)

        return {artifact.path for artifact in index.artifacts}

    def test_excludes_private_eval_inputs(self):
        paths = self.scan_paths(
            [
                "evals/private/case/input/notes.md",
                "evals/public/case/notes.md",
            ]
        )

        self.assertNotIn("evals/private/case/input/notes.md", paths)
        self.assertIn("evals/public/case/notes.md", paths)

    def test_excludes_private_eval_outputs(self):
        paths = self.scan_paths(
            [
                "evals/private_outputs/run/result.md",
                "evals/public/case/gold.yaml",
                "README.md",
            ]
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
            ]
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
            ]
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
            ]
        )

        self.assertIn("PROJECT_STATUS.md", paths)
        self.assertIn("evals/README.md", paths)
        self.assertNotIn(
            "evals/public/query_memo/case/input/.project_memory/latest/project_state.json",
            paths,
        )


if __name__ == "__main__":
    unittest.main()
