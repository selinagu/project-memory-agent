import tempfile
import unittest
from pathlib import Path

from benchmarks.generate_repo import generate_repository
from benchmarks.profiles import PROFILES, get_profile
from scan_project import scan_project


class BenchmarkProfileTests(unittest.TestCase):
    def test_profiles_have_expected_sizes(self):
        self.assertEqual(
            {name: profile.generated_files for name, profile in PROFILES.items()},
            {
                "tiny": 25,
                "small": 100,
                "medium": 500,
                "large": 1000,
                "stress": 2500,
            },
        )
        self.assertEqual(get_profile("tiny").selected_artifacts, 20)
        with self.assertRaisesRegex(ValueError, "unknown benchmark profile"):
            get_profile("missing")


class BenchmarkGeneratorTests(unittest.TestCase):
    def generate(self, parent: Path, name: str, seed: int = 7):
        return generate_repository(
            parent / name,
            get_profile("tiny"),
            seed=seed,
        )

    def test_same_seed_has_identical_counts_bytes_loc_and_digest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = self.generate(root, "first")
            second = self.generate(root, "second")
            first_paths = sorted(
                path.relative_to(root / "first").as_posix()
                for path in (root / "first").rglob("*")
                if path.is_file()
            )
            second_paths = sorted(
                path.relative_to(root / "second").as_posix()
                for path in (root / "second").rglob("*")
                if path.is_file()
            )
        self.assertEqual(first, second)
        self.assertEqual(first_paths, second_paths)
        self.assertEqual(len(first_paths), 25)

    def test_different_seed_changes_content_digest_not_shape(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            first = self.generate(root, "first", seed=7)
            second = self.generate(root, "second", seed=8)
        self.assertNotEqual(first.content_digest, second.content_digest)
        self.assertEqual(first.generated_files, second.generated_files)
        self.assertEqual(first.approximate_loc, second.approximate_loc)

    def test_scanner_selects_only_expected_safe_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            generated = self.generate(Path(temp_dir), "project")
            index = scan_project(project)
            paths = [artifact.path for artifact in index.artifacts]
        self.assertEqual(len(paths), generated.expected_selected_artifacts)
        self.assertEqual(
            sum(artifact.size_bytes for artifact in index.artifacts),
            generated.selected_raw_bytes,
        )
        self.assertFalse(any(path.startswith(".project_memory/") for path in paths))
        self.assertFalse(any(path.startswith("node_modules/") for path in paths))
        self.assertNotIn(".env", paths)
        self.assertNotIn("assets/unsupported.bin", paths)

    def test_generator_refuses_existing_output_and_invalid_seed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "existing"
            target.mkdir()
            with self.assertRaises(FileExistsError):
                generate_repository(target, get_profile("tiny"), seed=7)
            with self.assertRaises(ValueError):
                generate_repository(
                    Path(temp_dir) / "invalid",
                    get_profile("tiny"),
                    seed=-1,
                )


if __name__ == "__main__":
    unittest.main()
