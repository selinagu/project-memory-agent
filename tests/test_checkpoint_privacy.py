import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import checkpoint
from checkpoint_reader import load_checkpoint
from schemas import ProjectState
from tests.test_checkpoint_git_context import fake_extract_state


class CheckpointSerializationPrivacyTests(unittest.TestCase):
    def test_new_structured_artifacts_use_logical_project_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir) / "private-user" / "project"
            root.mkdir(parents=True)
            (root / "README.md").write_text("public source", encoding="utf-8")
            output = root / "checkpoint"
            with patch("checkpoint.extract_state", side_effect=fake_extract_state):
                checkpoint.run_checkpoint_legacy(root, output, "unused")
            index = json.loads(
                (output / "artifacts_index.json").read_text(encoding="utf-8")
            )
            parsed = json.loads(
                (output / "parsed_artifacts.json").read_text(encoding="utf-8")
            )
            manifest = json.loads(
                (output / "artifact_manifest.json").read_text(encoding="utf-8")
            )
            metadata = json.loads(
                (output / "run_metadata.json").read_text(encoding="utf-8")
            )
            serialized = json.dumps(
                {
                    "index": index,
                    "parsed": parsed,
                    "manifest": manifest,
                    "metadata": metadata,
                }
            )
        self.assertEqual(index["project_dir"], ".")
        self.assertEqual(parsed["project_dir"], ".")
        self.assertEqual(manifest["project_path"], ".")
        self.assertEqual(metadata["project_path"], ".")
        self.assertNotIn(str(root), serialized)
        self.assertNotIn("private-user", serialized)

    def test_reader_accepts_legacy_absolute_project_dir(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            checkpoint_dir = Path(temp_dir)
            state = ProjectState(
                project_name="legacy",
                one_sentence_summary="legacy",
                goal="legacy",
                current_stage="legacy",
            )
            (checkpoint_dir / "project_state.json").write_text(
                state.model_dump_json(),
                encoding="utf-8",
            )
            (checkpoint_dir / "parsed_artifacts.json").write_text(
                json.dumps(
                    {
                        "project_dir": "/legacy/private/project",
                        "artifacts": [],
                    }
                ),
                encoding="utf-8",
            )
            loaded = load_checkpoint(checkpoint_dir)
        self.assertEqual(
            loaded.parsed_artifacts.project_dir,
            "/legacy/private/project",
        )


if __name__ == "__main__":
    unittest.main()
