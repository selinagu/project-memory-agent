import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from extract_state import extract_state, normalize_evidence_sources
from git_context import (
    GIT_CONTEXT_EVIDENCE_SOURCE,
    GIT_PROMPT_MAX_CHARS,
    GitContext,
    render_git_context_for_prompt,
)
from source_lookup import SourceSection, project_state_lookup_text, select_source_sections
from prompts import (
    GROUP_UPDATE_MEMO_PROMPT,
    GROUP_UPDATE_SINCE_MEMO_PROMPT,
    GROUP_UPDATE_WINDOW_MEMO_PROMPT,
    SELF_MEMO_PROMPT,
)
from query import build_query_prompt


def context(**overrides) -> GitContext:
    values = {
        "available": True,
        "repository_root": "/private/machine/repository",
        "branch": "feature/checkpoint-context",
        "head_commit": "a" * 40,
        "head_commit_short": "a" * 7,
        "head_commit_subject": "Secret commit subject",
        "working_tree_clean": True,
        "detached_head": False,
        "collected_at": "2026-08-30T00:00:00+00:00",
    }
    values.update(overrides)
    return GitContext(**values)


class GitPromptRendererTests(unittest.TestCase):
    def test_clean_context_is_bounded_and_omits_sensitive_metadata(self):
        rendered = render_git_context_for_prompt(context())

        self.assertIn("repository_available: yes", rendered)
        self.assertIn("snapshot_scope: checkpoint_time_only", rendered)
        self.assertIn("working_tree: clean", rendered)
        self.assertIn("head: aaaaaaa", rendered)
        self.assertNotIn("/private/machine", rendered)
        self.assertNotIn("Secret commit subject", rendered)
        self.assertNotIn("sha256", rendered)
        self.assertLessEqual(len(rendered), GIT_PROMPT_MAX_CHARS)

    def test_dirty_paths_are_sorted_categorized_and_deduplicated(self):
        rendered = render_git_context_for_prompt(
            context(
                working_tree_clean=False,
                staged_files=["z.py", "both.py"],
                unstaged_files=["a.py", "both.py"],
                untracked_files=["new.py"],
                changed_files=["ignored-value.py"],
            )
        )

        self.assertIn("staged_count: 2", rendered)
        self.assertIn("unstaged_count: 2", rendered)
        self.assertIn("changed_path_count: 4", rendered)
        self.assertIn("- [staged,unstaged] both.py", rendered)
        self.assertNotIn("ignored-value.py", rendered)
        self.assertLess(rendered.index("a.py"), rendered.index("both.py"))

    def test_path_count_is_truncated_deterministically(self):
        paths = [f"src/module_{index:03d}.py" for index in range(75)]
        rendered = render_git_context_for_prompt(
            context(working_tree_clean=False, untracked_files=list(reversed(paths)))
        )

        self.assertIn("changed_path_count: 75", rendered)
        self.assertIn("omitted_changed_paths: 25", rendered)
        self.assertIn("src/module_000.py", rendered)
        self.assertNotIn("src/module_074.py", rendered)
        self.assertLessEqual(len(rendered), GIT_PROMPT_MAX_CHARS)

    def test_absolute_parent_and_control_paths_fail_closed(self):
        for unsafe_path in (
            "/" + "home/user/private.py",
            "../outside.py",
            "safe/../../outside.py",
            "bad\npath.py",
        ):
            rendered = render_git_context_for_prompt(
                context(working_tree_clean=False, unstaged_files=[unsafe_path])
            )
            self.assertIn("reason: invalid_git_context", rendered)
            self.assertNotIn(unsafe_path, rendered)

    def test_contradictory_clean_flag_and_path_lists_fail_closed(self):
        rendered = render_git_context_for_prompt(
            context(working_tree_clean=True, staged_files=["changed.py"])
        )
        self.assertIn("reason: invalid_git_context", rendered)

    def test_schema_v1_is_supported_and_future_schema_is_bounded(self):
        legacy = context().to_dict()
        legacy["schema_version"] = 1
        self.assertIn("schema_version: 1", render_git_context_for_prompt(legacy))

        future = context().to_dict()
        future["schema_version"] = 999
        rendered = render_git_context_for_prompt(future)
        self.assertIn("reason: unsupported_git_context_schema", rendered)
        self.assertNotIn("feature/checkpoint-context", rendered)

    def test_detached_and_non_git_contexts_are_explicit(self):
        detached = render_git_context_for_prompt(
            context(branch=None, detached_head=True)
        )
        self.assertIn("branch: none (detached HEAD)", detached)

        unavailable = render_git_context_for_prompt(
            GitContext(reason="not_a_git_repository", collected_at="fixed")
        )
        self.assertIn("repository_available: no", unavailable)
        self.assertIn("reason: not_a_git_repository", unavailable)


class GitAwareExtractionTests(unittest.TestCase):
    def test_prompt_keeps_git_context_separate_and_retains_metadata_evidence(self):
        response_data = {
            "project_name": "sample",
            "one_sentence_summary": "sample",
            "goal": "sample",
            "current_stage": "sample",
            "evidence": [
                {
                    "source": GIT_CONTEXT_EVIDENCE_SOURCE,
                    "quote_or_summary": "The checkpoint worktree was dirty.",
                }
            ],
        }
        calls = []

        def create(**kwargs):
            calls.append(kwargs)
            return SimpleNamespace(output_text=json.dumps(response_data))

        responses = SimpleNamespace(create=create)
        client = SimpleNamespace(responses=responses)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            notes = root / "combined_notes.md"
            output = root / "project_state.json"
            notes.write_text(
                "<!-- SOURCE: README.md -->\nProject source.",
                encoding="utf-8",
            )
            with patch("extract_state.OpenAI", return_value=client):
                state = extract_state(
                    notes,
                    output,
                    "unused",
                    git_context=context(
                        working_tree_clean=False,
                        unstaged_files=["src/core.py"],
                    ),
                )
            prompt = calls[0]["input"]

        self.assertEqual(state.evidence[0].source, GIT_CONTEXT_EVIDENCE_SOURCE)
        self.assertIn("--- BEGIN CHECKPOINT_GIT_CONTEXT ---", prompt)
        self.assertIn("src/core.py", prompt)
        self.assertIn(GIT_CONTEXT_EVIDENCE_SOURCE, prompt)
        self.assertNotIn("Secret commit subject", prompt)

    def test_metadata_evidence_is_not_allowed_without_git_context(self):
        data = {
            "evidence": [
                {
                    "source": GIT_CONTEXT_EVIDENCE_SOURCE,
                    "quote_or_summary": "unsupported",
                }
            ]
        }
        normalize_evidence_sources(
            data,
            Path("combined_notes.md"),
            ["README.md"],
        )
        self.assertEqual(data["evidence"][0]["source"], "README.md")

    def test_unauthorized_metadata_without_source_markers_uses_legacy_fallback(self):
        data = {
            "evidence": [
                {
                    "source": GIT_CONTEXT_EVIDENCE_SOURCE,
                    "quote_or_summary": "unsupported",
                }
            ]
        }
        normalize_evidence_sources(data, Path("notes.md"), [])
        self.assertEqual(data["evidence"][0]["source"], "notes.md")

    def test_metadata_evidence_does_not_trigger_source_lookup_diagnostic(self):
        state = json.dumps(
            {
                "confirmed_findings": ["Recorded source fact."],
                "evidence": [
                    {
                        "source": GIT_CONTEXT_EVIDENCE_SOURCE,
                        "quote_or_summary": "Dirty at checkpoint time.",
                    },
                    {
                        "source": "README.md",
                        "quote_or_summary": "Recorded source fact.",
                    },
                ],
            }
        )
        selected, diagnostics = select_source_sections(
            "What evidence supports the recorded source fact?",
            state,
            [SourceSection("README.md", "Recorded source fact.")],
        )
        _, evidence_sources = project_state_lookup_text(state)

        self.assertEqual([item.source for item in selected], ["README.md"])
        self.assertEqual(diagnostics, [])
        self.assertEqual(evidence_sources, {"README.md"})

    def test_query_and_all_memo_prompts_define_checkpoint_time_boundary(self):
        query_prompt = build_query_prompt(
            "What changed?",
            {"project_state.json": "{}"},
            [],
        )
        self.assertIn("checkpoint-time repository snapshot", query_prompt)
        for prompt in (
            SELF_MEMO_PROMPT,
            GROUP_UPDATE_MEMO_PROMPT,
            GROUP_UPDATE_WINDOW_MEMO_PROMPT,
            GROUP_UPDATE_SINCE_MEMO_PROMPT,
        ):
            self.assertIn("checkpoint-time repository snapshot", prompt)


if __name__ == "__main__":
    unittest.main()
