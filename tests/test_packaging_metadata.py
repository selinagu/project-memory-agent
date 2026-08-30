import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]


class PackagingMetadataTests(unittest.TestCase):
    def test_publication_metadata_points_to_tracked_docs(self):
        with (REPO_ROOT / "pyproject.toml").open("rb") as pyproject_file:
            project = tomllib.load(pyproject_file)["project"]

        self.assertEqual(project["readme"], "README.md")
        self.assertEqual(project["license"], "MIT")
        self.assertEqual(project["license-files"], ["LICENSE"])
        self.assertTrue((REPO_ROOT / project["readme"]).is_file())
        self.assertTrue((REPO_ROOT / project["license-files"][0]).is_file())

    def test_every_runtime_module_is_in_the_wheel_manifest(self):
        with (REPO_ROOT / "pyproject.toml").open("rb") as pyproject_file:
            pyproject = tomllib.load(pyproject_file)

        declared = set(pyproject["tool"]["setuptools"]["py-modules"])
        runtime_modules = {
            path.stem
            for path in (REPO_ROOT / "src").glob("*.py")
            if path.name != "__init__.py"
        }

        self.assertEqual(declared, runtime_modules)

    def test_source_distribution_manifest_includes_project_docs(self):
        manifest = (REPO_ROOT / "MANIFEST.in").read_text(encoding="utf-8")

        self.assertIn(
            "include README.md LICENSE CHANGELOG.md PROJECT_STATUS.md",
            manifest,
        )
        self.assertIn("recursive-include demo *.json *.md *.py *.txt *.yaml", manifest)
        self.assertIn("recursive-include docs *.md", manifest)


if __name__ == "__main__":
    unittest.main()
