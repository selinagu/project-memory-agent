import json
import tempfile
import unittest
from pathlib import Path

from freshness import (
    check_checkpoint_freshness,
    compare_git_contexts,
    render_freshness_text,
)
from git_context import FileFingerprint, GitContext


def context(
    *,
    available: bool = True,
    reason: str | None = None,
    head: str | None = "a" * 40,
    branch: str | None = "main",
    detached: bool | None = False,
    statuses: dict[str, list[str]] | None = None,
    contents: dict[str, tuple[bool, str, int | None, str | None]] | None = None,
) -> GitContext:
    statuses = statuses or {}
    contents = contents or {}
    categories = {name: [] for name in ("staged", "unstaged", "untracked", "conflicted")}
    for path, values in statuses.items():
        for value in values:
            categories[value].append(path)
    fingerprints = []
    for path in sorted(statuses):
        exists, kind, size, digest = contents.get(path, (True, "file", 1, "1" * 64))
        fingerprints.append(
            FileFingerprint(path, sorted(statuses[path]), exists, kind, size, digest)
        )
    changed = sorted(statuses)
    return GitContext(
        available=available,
        reason=reason,
        repository_root="." if available else None,
        branch=branch if available else None,
        head_commit=head if available else None,
        head_commit_short=head[:7] if available and head else None,
        working_tree_clean=not changed if available else None,
        detached_head=detached if available else None,
        staged_files=sorted(categories["staged"]),
        unstaged_files=sorted(categories["unstaged"]),
        untracked_files=sorted(categories["untracked"]),
        conflicted_files=sorted(categories["conflicted"]),
        changed_files=changed,
        file_fingerprints=fingerprints,
        collected_at="checkpoint",
    )


class FreshnessComparisonTests(unittest.TestCase):
    def compare(self, before: GitContext | dict, after: GitContext):
        checkpoint = before if isinstance(before, dict) else before.to_dict()
        return compare_git_contexts(checkpoint, after, checked_at="fixed")

    def test_clean_dirty_untracked_and_unborn_unchanged_are_current(self):
        cases = [
            context(),
            context(statuses={"README.md": ["unstaged"]}),
            context(statuses={"new.txt": ["untracked"]}),
            context(head=None),
        ]
        for value in cases:
            with self.subTest(value=value):
                self.assertEqual(self.compare(value, value).status, "current")

    def test_head_branch_and_detached_changes_are_stale(self):
        before = context()
        cases = [
            (context(head="b" * 40), "head_changed"),
            (context(branch="other"), "branch_changed"),
            (context(branch=None, detached=True), "detached_head_changed"),
        ]
        for after, code in cases:
            result = self.compare(before, after)
            self.assertEqual(result.status, "stale")
            self.assertIn(code, [reason.code for reason in result.reasons])

    def test_added_removed_and_status_changed_paths_are_stale(self):
        before = context(statuses={"README.md": ["unstaged"]})
        added = context(statuses={"README.md": ["unstaged"], "new.md": ["untracked"]})
        removed = context()
        status_changed = context(statuses={"README.md": ["staged"]})
        self.assertEqual(self.compare(before, added).added_changed_files, ["new.md"])
        self.assertEqual(self.compare(before, removed).removed_changed_files, ["README.md"])
        result = self.compare(before, status_changed)
        self.assertIn("file_status_changed", [reason.code for reason in result.reasons])

    def test_same_path_content_and_same_size_hash_changes_are_stale(self):
        statuses = {"README.md": ["unstaged"]}
        before = context(
            statuses=statuses,
            contents={"README.md": (True, "file", 4, "1" * 64)},
        )
        after = context(
            statuses=statuses,
            contents={"README.md": (True, "file", 4, "2" * 64)},
        )
        result = self.compare(before, after)
        self.assertEqual(result.status, "stale")
        self.assertEqual(result.modified_fingerprints, ["README.md"])
        self.assertIn("file_content_changed", [reason.code for reason in result.reasons])

    def test_deleted_and_recreated_files_are_stale(self):
        statuses = {"README.md": ["unstaged"]}
        present = context(statuses=statuses)
        missing = context(
            statuses=statuses,
            contents={"README.md": (False, "missing", None, None)},
        )
        self.assertEqual(self.compare(present, missing).status, "stale")
        self.assertEqual(self.compare(missing, present).status, "stale")

    def test_non_git_availability_transitions_and_failures(self):
        non_git = context(available=False, reason="not_a_git_repository")
        failed = context(available=False, reason="git_command_failed")
        self.assertEqual(self.compare(non_git, non_git).status, "current")
        self.assertEqual(self.compare(non_git, context()).status, "stale")
        self.assertEqual(self.compare(context(), non_git).status, "stale")
        self.assertEqual(self.compare(context(), failed).status, "unknown")

    def test_version_one_clean_is_current_and_dirty_is_unknown(self):
        clean = context().to_dict()
        clean["schema_version"] = 1
        clean.pop("file_fingerprints")
        self.assertEqual(self.compare(clean, context()).status, "current")

        dirty_context = context(statuses={"README.md": ["unstaged"]})
        dirty = dirty_context.to_dict()
        dirty["schema_version"] = 1
        dirty.pop("file_fingerprints")
        self.assertEqual(self.compare(dirty, dirty_context).status, "unknown")

    def test_malformed_missing_fingerprint_and_future_schema_are_unknown(self):
        current = context(statuses={"README.md": ["unstaged"]})
        malformed = current.to_dict()
        malformed["file_fingerprints"][0].pop("sha256")
        future = current.to_dict()
        future["schema_version"] = 999
        wrong_kind = current.to_dict()
        wrong_kind["file_fingerprints"][0]["kind"] = "device"
        wrong_status_type = current.to_dict()
        wrong_status_type["file_fingerprints"][0]["status"] = [{}]
        missing_required = current.to_dict()
        missing_required.pop("collected_at")
        for value in (
            malformed,
            future,
            wrong_kind,
            wrong_status_type,
            missing_required,
            {"schema_version": 2},
        ):
            self.assertEqual(self.compare(value, current).status, "unknown")

    def test_directory_fingerprint_is_conservatively_unknown(self):
        value = context(
            statuses={"submodule": ["unstaged"]},
            contents={"submodule": (True, "directory", None, None)},
        )
        self.assertEqual(self.compare(value, value).status, "unknown")


class FreshnessLoadingTests(unittest.TestCase):
    def test_missing_checkpoint_and_human_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            result = check_checkpoint_freshness(Path(temp_dir), checked_at="fixed")
        self.assertEqual(result.status, "no_checkpoint")
        self.assertIn("No latest checkpoint", render_freshness_text(result))
        json.dumps(result.to_dict())

    def test_malformed_json_is_unknown(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            latest = root / ".project_memory" / "latest"
            latest.mkdir(parents=True)
            (latest / "git_context.json").write_text("{broken", encoding="utf-8")
            result = check_checkpoint_freshness(root, checked_at="fixed")
        self.assertEqual(result.status, "unknown")


if __name__ == "__main__":
    unittest.main()
