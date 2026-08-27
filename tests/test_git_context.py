import shutil
import hashlib
import subprocess
import tempfile
import unittest
from pathlib import Path

from git_context import (
    GIT_CONTEXT_SCHEMA_VERSION,
    ParsedStatus,
    collect_git_context,
    fingerprint_changed_files,
    parse_porcelain_v1_z,
    render_git_context_markdown,
)


GIT_AVAILABLE = shutil.which("git") is not None


def git(root: Path, *arguments: str) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(
        ["git", "-C", str(root), *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )


def init_repository(root: Path, *, commit: bool = True) -> None:
    git(root, "init", "-q")
    git(root, "config", "user.name", "PMA Test")
    git(root, "config", "user.email", "pma-test@example.com")
    if commit:
        (root / "README.md").write_text("initial\n", encoding="utf-8")
        git(root, "add", "README.md")
        git(root, "commit", "-q", "-m", "Initial checkpoint fixture")


class PorcelainParsingTests(unittest.TestCase):
    def test_categories_union_spaces_unicode_and_nested_paths(self):
        parsed = parse_porcelain_v1_z(
            b"M  staged.txt\0 M both.txt\0M  both.txt\0?? notes/file with space.md\0"
            + "?? notes/结果.md\0".encode()
        )
        self.assertEqual(parsed.staged_files, ["both.txt", "staged.txt"])
        self.assertEqual(parsed.unstaged_files, ["both.txt"])
        self.assertEqual(
            parsed.untracked_files, ["notes/file with space.md", "notes/结果.md"]
        )

    def test_staged_rename_uses_destination_and_consumes_source(self):
        parsed = parse_porcelain_v1_z(b"R  new name.md\0old name.md\0?? next.md\0")
        self.assertEqual(parsed.staged_files, ["new name.md"])
        self.assertEqual(parsed.untracked_files, ["next.md"])

    def test_conflict_is_detected(self):
        parsed = parse_porcelain_v1_z(b"UU conflicted.md\0")
        self.assertEqual(parsed.conflicted_files, ["conflicted.md"])
        self.assertEqual(parsed.staged_files, [])
        self.assertEqual(parsed.unstaged_files, [])


class FingerprintTests(unittest.TestCase):
    def fingerprints(self, root: Path, paths: list[str]):
        return fingerprint_changed_files(
            root,
            ParsedStatus([], [], paths, []),
        )

    def test_regular_binary_empty_space_and_unicode_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            values = {
                "empty file.bin": b"",
                "nested/data.bin": b"\x00\xff\x10",
                "结果.txt": "结果".encode(),
            }
            for name, content in values.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            fingerprints = self.fingerprints(root, list(reversed(values)))

        self.assertEqual([item.path for item in fingerprints], sorted(values))
        for item in fingerprints:
            self.assertEqual(item.kind, "file")
            self.assertEqual(item.size_bytes, len(values[item.path]))
            self.assertEqual(item.sha256, hashlib.sha256(values[item.path]).hexdigest())
            self.assertFalse(Path(item.path).is_absolute())

    def test_missing_path_and_multiple_statuses(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            fingerprint = fingerprint_changed_files(
                root,
                ParsedStatus(["deleted.md"], ["deleted.md"], [], []),
            )[0]
        self.assertFalse(fingerprint.exists)
        self.assertEqual(fingerprint.kind, "missing")
        self.assertEqual(fingerprint.status, ["staged", "unstaged"])
        self.assertIsNone(fingerprint.sha256)

    @unittest.skipUnless(hasattr(Path, "symlink_to"), "symlinks are unavailable")
    def test_symlink_hashes_target_text_without_following(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "target.txt").write_text("destination contents", encoding="utf-8")
            (root / "link.txt").symlink_to("target.txt")
            fingerprint = self.fingerprints(root, ["link.txt"])[0]
        target_bytes = b"target.txt"
        self.assertEqual(fingerprint.kind, "symlink")
        self.assertEqual(fingerprint.size_bytes, len(target_bytes))
        self.assertEqual(fingerprint.sha256, hashlib.sha256(target_bytes).hexdigest())


class GitContextFailureTests(unittest.TestCase):
    def test_non_git_directory_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            context = collect_git_context(Path(temp_dir), collected_at="fixed")
        self.assertFalse(context.available)
        self.assertEqual(context.reason, "not_a_git_repository")
        self.assertEqual(context.changed_files, [])
        self.assertIn("not inside a Git repository", render_git_context_markdown(context))

    def test_missing_git_degrades_cleanly(self):
        def missing(_arguments):
            raise FileNotFoundError

        context = collect_git_context(Path.cwd(), runner=missing, collected_at="fixed")
        self.assertEqual(context.reason, "git_not_installed")

    def test_timeout_degrades_cleanly(self):
        def timeout(arguments):
            raise subprocess.TimeoutExpired(arguments, 10)

        context = collect_git_context(Path.cwd(), runner=timeout, collected_at="fixed")
        self.assertEqual(context.reason, "git_command_failed")

    def test_command_failure_degrades_cleanly(self):
        def failed(_arguments):
            return subprocess.CompletedProcess([], 2, b"", b"unexpected failure")

        context = collect_git_context(Path.cwd(), runner=failed, collected_at="fixed")
        self.assertEqual(context.reason, "git_command_failed")


@unittest.skipUnless(GIT_AVAILABLE, "Git executable is unavailable")
class GitContextRepositoryTests(unittest.TestCase):
    def test_clean_repository_records_head_branch_and_subject(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_repository(root)
            context = collect_git_context(root, collected_at="fixed")

        self.assertTrue(context.available)
        self.assertEqual(context.schema_version, GIT_CONTEXT_SCHEMA_VERSION)
        self.assertEqual(context.repository_root, ".")
        self.assertIsNotNone(context.branch)
        self.assertEqual(len(context.head_commit), 40)
        self.assertGreaterEqual(len(context.head_commit_short), 7)
        self.assertEqual(context.head_commit_subject, "Initial checkpoint fixture")
        self.assertTrue(context.working_tree_clean)
        self.assertFalse(context.detached_head)
        self.assertEqual(context.changed_files, [])
        self.assertIn("No changed files.", render_git_context_markdown(context))

    def test_dirty_repository_distinguishes_all_categories(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_repository(root)
            (root / "staged file.md").write_text("staged\n", encoding="utf-8")
            git(root, "add", "staged file.md")
            (root / "README.md").write_text("staged version\n", encoding="utf-8")
            git(root, "add", "README.md")
            (root / "README.md").write_text("unstaged version\n", encoding="utf-8")
            notes = root / "notes"
            notes.mkdir()
            (notes / "结果.md").write_text("untracked\n", encoding="utf-8")
            context = collect_git_context(root, collected_at="fixed")

        self.assertEqual(context.staged_files, ["README.md", "staged file.md"])
        self.assertEqual(context.unstaged_files, ["README.md"])
        self.assertEqual(context.untracked_files, ["notes/结果.md"])
        self.assertEqual(
            context.changed_files,
            ["README.md", "notes/结果.md", "staged file.md"],
        )
        self.assertEqual(
            [item.path for item in context.file_fingerprints],
            context.changed_files,
        )
        readme = next(
            item for item in context.file_fingerprints if item.path == "README.md"
        )
        self.assertEqual(readme.status, ["staged", "unstaged"])
        markdown = render_git_context_markdown(context)
        self.assertIn("### Staged", markdown)
        self.assertIn("### Unstaged", markdown)
        self.assertIn("### Untracked", markdown)

    def test_subproject_filters_and_rewrites_paths(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_repository(root)
            subproject = root / "subproject"
            subproject.mkdir()
            (subproject / "README.md").write_text("inside\n", encoding="utf-8")
            (root / "outside.md").write_text("outside\n", encoding="utf-8")
            context = collect_git_context(subproject, collected_at="fixed")

        self.assertTrue(context.available)
        self.assertEqual(context.repository_root, "..")
        self.assertEqual(context.untracked_files, ["README.md"])
        self.assertEqual(context.changed_files, ["README.md"])
        self.assertNotIn(str(root), str(context.to_dict()))
        self.assertEqual(
            [item.path for item in context.file_fingerprints], ["README.md"]
        )

    def test_unsupported_and_scanner_excluded_files_are_fingerprinted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_repository(root)
            (root / "ignored.py").write_text("print('changed')\n", encoding="utf-8")
            (root / "pma.toml").write_text(
                '[scanner]\nexclude = ["ignored.py"]\n', encoding="utf-8"
            )
            context = collect_git_context(root, collected_at="fixed")
        paths = [item.path for item in context.file_fingerprints]
        self.assertIn("ignored.py", paths)
        self.assertIn("pma.toml", paths)

    def test_detached_head_is_represented(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_repository(root)
            git(root, "checkout", "-q", "--detach", "HEAD")
            context = collect_git_context(root, collected_at="fixed")
        self.assertIsNone(context.branch)
        self.assertTrue(context.detached_head)
        self.assertIsNotNone(context.head_commit)

    def test_unborn_repository_is_available(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            init_repository(root, commit=False)
            context = collect_git_context(root, collected_at="fixed")
        self.assertTrue(context.available)
        self.assertIsNotNone(context.branch)
        self.assertIsNone(context.head_commit)
        self.assertFalse(context.detached_head)


if __name__ == "__main__":
    unittest.main()
