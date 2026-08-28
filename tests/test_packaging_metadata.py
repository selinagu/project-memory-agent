import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib


REPO_ROOT = Path(__file__).resolve().parents[1]


class PackagingMetadataTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
