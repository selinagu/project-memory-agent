import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import checkpoint
from schemas import ProjectState
from tests.test_git_context import GIT_AVAILABLE, init_repository


def fake_extract_state(input_path: Path, output_path: Path, model: str) -> ProjectState:
    state = ProjectState(
        project_name="test",
        one_sentence_summary="test",
        goal="test",
        current_stage="test",
    )
    output_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    return state


class CheckpointGitContextTests(unittest.TestCase):
    def test_non_git_checkpoint_writes_context_without_changing_llm_input(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "README.md").write_text("source text", encoding="utf-8")
            output = root / "output"

            with patch("checkpoint.extract_state", side_effect=fake_extract_state):
                checkpoint.write_checkpoint_outputs(root, output, "unused")

            context = json.loads(
                (output / "git_context.json").read_text(encoding="utf-8")
            )
            markdown = (output / "git_context.md").read_text(encoding="utf-8")
            combined = (output / "combined_notes.md").read_text(encoding="utf-8")
            state = json.loads((output / "project_state.json").read_text(encoding="utf-8"))

        self.assertFalse(context["available"])
        self.assertEqual(context["reason"], "not_a_git_repository")
        self.assertIn("Git context is unavailable", markdown)
        self.assertNotIn("Git Context", combined)
        self.assertNotIn("git_context", state)

    @unittest.skipUnless(GIT_AVAILABLE, "Git executable is unavailable")
    def test_clean_git_history_checkpoint_copies_context_to_latest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "project"
            root.mkdir()
            init_repository(root)
            base_output = Path(temp_dir) / "memory"

            with patch("checkpoint.extract_state", side_effect=fake_extract_state):
                checkpoint.run_checkpoint(
                    project_dir=root,
                    project_name="project",
                    base_output_dir=base_output,
                    model="unused",
                )

            project_output = base_output / "project"
            run_dirs = list((project_output / "runs").iterdir())
            latest = project_output / "latest"

            self.assertEqual(len(run_dirs), 1)
            for filename in ("git_context.json", "git_context.md"):
                self.assertTrue((run_dirs[0] / filename).is_file())
                self.assertEqual(
                    (run_dirs[0] / filename).read_bytes(),
                    (latest / filename).read_bytes(),
                )
            context = json.loads(
                (latest / "git_context.json").read_text(encoding="utf-8")
            )
            self.assertTrue(context["available"])
            self.assertTrue(context["working_tree_clean"])
            self.assertEqual(context["changed_files"], [])


if __name__ == "__main__":
    unittest.main()
