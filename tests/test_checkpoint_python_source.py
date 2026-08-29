import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import checkpoint
from schemas import ProjectState
from source_lookup import (
    parse_source_sections,
    render_source_snippets,
    select_source_sections,
)


def minimal_state() -> ProjectState:
    return ProjectState(
        project_name="python-source-test",
        one_sentence_summary="test",
        goal="test",
        current_stage="test",
    )


class CheckpointPythonSourceTests(unittest.TestCase):
    def test_checkpoint_uses_structural_python_source_with_provenance(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            output_dir = root / "checkpoint"
            (root / "README.md").write_text("# Synthetic project\n", encoding="utf-8")
            (root / "service.py").write_text(
                'def run(token="checkpoint-default-secret") -> str:\n'
                '    body_secret = "checkpoint-body-secret"\n'
                '    return body_secret\n',
                encoding="utf-8",
            )
            (root / "broken.py").write_text(
                'def broken(:\n    value = "broken-secret"\n',
                encoding="utf-8",
            )
            (root / "excluded.py").write_text(
                'def excluded():\n    return "excluded-secret"\n',
                encoding="utf-8",
            )
            (root / "pma.toml").write_text(
                "[scanner]\n"
                "include_python = true\n"
                'include = ["README.md", "*.py"]\n'
                'exclude = ["excluded.py"]\n',
                encoding="utf-8",
            )

            with patch("checkpoint.extract_state", return_value=minimal_state()):
                checkpoint.write_checkpoint_outputs(root, output_dir, "unused")

            combined = (output_dir / "combined_notes.md").read_text(encoding="utf-8")
            index = json.loads(
                (output_dir / "artifacts_index.json").read_text(encoding="utf-8")
            )

        self.assertIn("<!-- SOURCE: service.py -->", combined)
        self.assertIn("run(token = ...) -> str", combined)
        self.assertNotIn("checkpoint-default-secret", combined)
        self.assertNotIn("checkpoint-body-secret", combined)
        self.assertNotIn("excluded.py", combined)
        self.assertNotIn("broken.py", combined)
        statuses = {item["path"]: item["parser_status"] for item in index["artifacts"]}
        self.assertEqual(statuses["service.py"], "parsed")
        self.assertEqual(statuses["broken.py"], "failed")
        self.assertNotIn("excluded.py", statuses)
        self.assertIn("README.md", combined)

        sections = parse_source_sections(combined)
        selected, diagnostics = select_source_sections(
            question="What source supports the run function?",
            project_state_json=json.dumps(
                {
                    "confirmed_findings": ["The run function is available."],
                    "evidence": [
                        {
                            "source": "service.py",
                            "quote_or_summary": "The structural preview records run.",
                        }
                    ],
                }
            ),
            sections=sections,
        )
        rendered_sources = render_source_snippets(selected)
        self.assertEqual(diagnostics, [])
        self.assertIn("combined_notes.md SOURCE service.py", rendered_sources)
        self.assertNotIn("checkpoint-body-secret", rendered_sources)


if __name__ == "__main__":
    unittest.main()
