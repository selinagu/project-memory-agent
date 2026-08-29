import tempfile
import unittest
from pathlib import Path

from scanner_config import (
    ScannerConfig,
    ScannerConfigError,
    load_scanner_config,
    path_matches_glob,
)


class ScannerConfigLoadingTests(unittest.TestCase):
    def load(self, content: str | None) -> ScannerConfig:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            if content is not None:
                (root / "pma.toml").write_text(content, encoding="utf-8")
            return load_scanner_config(root)

    def test_missing_config_has_no_restrictions(self):
        self.assertEqual(self.load(None), ScannerConfig())

    def test_loads_include_only(self):
        config = self.load('[scanner]\ninclude = ["README.md", "docs/**"]\n')
        self.assertEqual(config.include_patterns, ("README.md", "docs/**"))
        self.assertEqual(config.exclude_patterns, ())

    def test_loads_exclude_only(self):
        config = self.load('[scanner]\nexclude = ["archive/**"]\n')
        self.assertEqual(config.include_patterns, ())
        self.assertEqual(config.exclude_patterns, ("archive/**",))

    def test_loads_include_and_exclude(self):
        config = self.load(
            '[scanner]\ninclude = ["docs/**"]\nexclude = ["docs/drafts/**"]\n'
        )
        self.assertEqual(config.include_patterns, ("docs/**",))
        self.assertEqual(config.exclude_patterns, ("docs/drafts/**",))

    def test_loads_python_opt_in(self):
        config = self.load(
            '[scanner]\ninclude_python = true\ninclude = ["src/**/*.py"]\n'
        )
        self.assertTrue(config.include_python)
        self.assertEqual(config.include_patterns, ("src/**/*.py",))

    def test_python_scanning_defaults_to_disabled(self):
        self.assertFalse(self.load("[scanner]\n").include_python)

    def test_empty_lists_have_no_restrictions(self):
        self.assertEqual(
            self.load("[scanner]\ninclude = []\nexclude = []\n"), ScannerConfig()
        )

    def assert_invalid(self, content: str, message: str) -> None:
        with self.assertRaisesRegex(ScannerConfigError, message) as raised:
            self.load(content)
        self.assertIn("pma.toml", str(raised.exception))

    def test_rejects_invalid_toml(self):
        self.assert_invalid("[scanner\n", "invalid TOML")

    def test_rejects_non_list_include(self):
        self.assert_invalid('[scanner]\ninclude = "docs/**"\n', "list of strings")

    def test_rejects_non_string_entry(self):
        self.assert_invalid("[scanner]\ninclude = [123]\n", r"include\[0\]")

    def test_rejects_unknown_top_level_section(self):
        self.assert_invalid("[unknown]\nvalue = true\n", "unknown top-level")

    def test_rejects_unknown_scanner_key(self):
        self.assert_invalid("[scanner]\nincludes = []\n", "unknown key")

    def test_rejects_non_boolean_python_opt_in(self):
        self.assert_invalid(
            '[scanner]\ninclude_python = "true"\n',
            "include_python must be a boolean",
        )


class ScannerGlobTests(unittest.TestCase):
    def test_double_star_matches_zero_or_more_directories(self):
        self.assertTrue(path_matches_glob("docs/overview.md", "docs/**/*.md"))
        self.assertTrue(path_matches_glob("docs/design/scanner.md", "docs/**/*.md"))

    def test_trailing_double_star_matches_recursively(self):
        self.assertTrue(path_matches_glob("archive/old.md", "archive/**"))
        self.assertTrue(path_matches_glob("archive/old/older.md", "archive/**"))

    def test_windows_style_candidate_is_normalized(self):
        self.assertTrue(path_matches_glob(r"docs\design\scanner.md", "docs/**/*.md"))

    def test_absolute_paths_and_patterns_do_not_match(self):
        self.assertFalse(path_matches_glob("/project/docs/file.md", "**/*.md"))
        self.assertFalse(path_matches_glob("docs/file.md", "/project/**/*.md"))
        self.assertFalse(path_matches_glob(r"C:\project\docs\file.md", "**/*.md"))


if __name__ == "__main__":
    unittest.main()
