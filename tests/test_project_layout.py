import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import checkpoint
from brief import build_brief
from freshness import check_checkpoint_freshness
from git_context import collect_git_context
from memo import load_memo_context
from pma import run_brief, run_freshness, run_status_note
from project_layout import (
    CheckpointLayoutError,
    generated_output_prefixes,
    resolve_checkpoint_layout,
)
from query import ask_project_memory, locate_latest_checkpoint
from scan_project import scan_project
from scanner_config import ScannerConfig
from status_note import load_latest_memory, resolve_latest_dir
from tests.test_brief import VALID_STATE
from tests.test_checkpoint_git_context import fake_extract_state
from tests.test_git_context import GIT_AVAILABLE, git, init_repository


def write_latest(project_dir: Path, latest_dir: Path, *, name: str = "Example") -> None:
    latest_dir.mkdir(parents=True, exist_ok=True)
    state = dict(VALID_STATE)
    state["project_name"] = name
    (latest_dir / "project_state.json").write_text(json.dumps(state), encoding="utf-8")
    (latest_dir / "checkpoint_summary.md").write_text(f"# {name}\n", encoding="utf-8")
    (latest_dir / "progress_since_last.md").write_text("No changes.\n", encoding="utf-8")
    context = collect_git_context(project_dir, collected_at="2026-07-15T09:00:00Z")
    (latest_dir / "git_context.json").write_text(
        json.dumps(context.to_dict()), encoding="utf-8"
    )


class _FakeResponses:
    def create(self, **kwargs):
        return SimpleNamespace(output_text="Answer:\nConfigured checkpoint.")


class _FakeClient:
    responses = _FakeResponses()


class CheckpointLayoutResolutionTests(unittest.TestCase):
    def test_default_named_and_explicit_layouts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            default = resolve_checkpoint_layout(project)
            named = resolve_checkpoint_layout(
                project, project_name="experiment-a", base_output_dir=root / "outputs"
            )
            explicit = resolve_checkpoint_layout(project, latest_dir=Path("memory/latest"))
        self.assertEqual(default.checkpoint_root, project.resolve() / ".project_memory")
        self.assertEqual(default.latest_dir, project.resolve() / ".project_memory/latest")
        self.assertEqual(named.latest_dir, (root / "outputs/experiment-a/latest").resolve())
        self.assertEqual(named.runs_dir, (root / "outputs/experiment-a/runs").resolve())
        self.assertEqual(explicit.latest_dir, (project / "memory/latest").resolve())
        self.assertEqual(default.latest_label(), ".project_memory/latest")
        self.assertEqual(explicit.latest_label(), "memory/latest")
        self.assertEqual(named.latest_label(), "external")

    def test_internal_named_and_external_explicit_labels_are_privacy_safe(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            internal = resolve_checkpoint_layout(
                project,
                project_name="pma-output",
                base_output_dir=project,
            )
            external = resolve_checkpoint_layout(
                project,
                latest_dir=root / "external/latest",
            )
        self.assertEqual(internal.latest_label(), "pma-output/latest")
        self.assertEqual(external.latest_label(), "external")

    def test_resolution_with_absolute_arguments_is_cwd_independent(self):
        with tempfile.TemporaryDirectory() as temp_dir, tempfile.TemporaryDirectory() as other:
            root = Path(temp_dir)
            project = root / "project"
            base = root / "outputs"
            project.mkdir()
            before = Path.cwd()
            try:
                os.chdir(other)
                layout = resolve_checkpoint_layout(
                    project.resolve(), project_name="one", base_output_dir=base.resolve()
                )
            finally:
                os.chdir(before)
        self.assertEqual(layout.latest_dir, (base / "one/latest").resolve())

    def test_contradictory_and_incomplete_arguments_fail(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            cases = (
                {"project_name": "only"},
                {"base_output_dir": project / "base"},
                {"latest_dir": Path("latest"), "project_name": "x", "base_output_dir": project},
                {"project_name": "../escape", "base_output_dir": project},
            )
            for kwargs in cases:
                with self.subTest(kwargs=kwargs), self.assertRaises(CheckpointLayoutError):
                    resolve_checkpoint_layout(project, **kwargs)

    def test_all_consumers_resolve_the_same_latest_directory(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            base = root / "storage"
            latest = base / "alpha/latest"
            write_latest(project, latest)
            kwargs = {"project_name": "alpha", "base_output_dir": base}
            self.assertEqual(locate_latest_checkpoint(project, **kwargs), latest.resolve())
            self.assertEqual(resolve_latest_dir(project, **kwargs), latest.resolve())
            self.assertEqual(load_memo_context(project, **kwargs).latest_dir, latest.resolve())
            answer = ask_project_memory(
                "Which checkpoint?",
                project,
                "unused",
                client=_FakeClient(),
                **kwargs,
            )
            self.assertIn("Configured checkpoint", answer)
            self.assertEqual(build_brief(project, **kwargs).checkpoint.status, "available")
            self.assertNotEqual(check_checkpoint_freshness(project, **kwargs).status, "no_checkpoint")


@unittest.skipUnless(GIT_AVAILABLE, "Git executable is unavailable")
class CustomStorageIntegrationTests(unittest.TestCase):
    def test_legacy_direct_output_has_no_history_and_excludes_itself(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            (project / "README.md").write_text("source\n", encoding="utf-8")
            output = project / "legacy-output"
            output.mkdir()
            (output / "generated.md").write_text("generated\n", encoding="utf-8")
            with patch("checkpoint.extract_state", side_effect=fake_extract_state):
                checkpoint.run_checkpoint_legacy(project, output, "unused")
            index = json.loads(
                (output / "artifacts_index.json").read_text(encoding="utf-8")
            )
            self.assertTrue((output / "project_state.json").is_file())
            self.assertFalse((output / "latest").exists())
            self.assertFalse((output / "runs").exists())
            self.assertEqual(
                [item["path"] for item in index["artifacts"]],
                ["README.md"],
            )

    def test_internal_checkpoint_excludes_generated_output_everywhere(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir) / "project"
            project.mkdir()
            init_repository(project)
            (project / "PROJECT_STATUS.md").write_text("# Status\n", encoding="utf-8")
            storage = project / "pma-output"
            storage.mkdir()
            (storage / "should-not-scan.md").write_text("generated\n", encoding="utf-8")
            with patch("checkpoint.extract_state", side_effect=fake_extract_state):
                checkpoint.run_checkpoint(
                    project_dir=project,
                    project_name="pma-output",
                    base_output_dir=project,
                    model="unused",
                )
            layout = resolve_checkpoint_layout(
                project, project_name="pma-output", base_output_dir=project
            )
            index = scan_project(project, checkpoint_root=layout.checkpoint_root)
            git_context = collect_git_context(project, checkpoint_root=layout.checkpoint_root)
            fresh = check_checkpoint_freshness(
                project, project_name="pma-output", base_output_dir=project
            )
            brief = build_brief(project, project_name="pma-output", base_output_dir=project)
            checkpoint_context = json.loads(
                (layout.latest_dir / "git_context.json").read_text(encoding="utf-8")
            )
            latest_exists = layout.latest_dir.is_dir()
            default_exists = (project / ".project_memory").exists()
        self.assertTrue(latest_exists)
        self.assertFalse(default_exists)
        self.assertNotIn("pma-output/should-not-scan.md", [a.path for a in index.artifacts])
        self.assertFalse(any(path.startswith("pma-output/") for path in git_context.changed_files))
        self.assertFalse(any(path.startswith("pma-output/") for path in checkpoint_context["changed_files"]))
        self.assertFalse(any(item["path"].startswith("pma-output/") for item in checkpoint_context["file_fingerprints"]))
        self.assertEqual(fresh.status, "current")
        self.assertEqual(brief.recommendation.code, "no_checkpoint_update_needed")

    def test_user_include_cannot_reinclude_active_checkpoint_root(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            output = project / "memory-output"
            output.mkdir()
            (output / "included.md").write_text("generated", encoding="utf-8")
            (project / "README.md").write_text("source", encoding="utf-8")
            config = ScannerConfig(include_patterns=("**/*.md",))
            index = scan_project(project, config, checkpoint_root=output)
        self.assertEqual([artifact.path for artifact in index.artifacts], ["README.md"])

    def test_external_storage_is_private_and_status_note_stays_in_project(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            workspace = Path(temp_dir)
            project = workspace / "research-project"
            project.mkdir()
            init_repository(project)
            note = project / "PROJECT_STATUS.md"
            note.write_text("# Project note\n", encoding="utf-8")
            base = workspace / "pma-artifacts"
            latest = base / "experiment/latest"
            write_latest(project, latest)
            kwargs = {"project_name": "experiment", "base_output_dir": base}
            result = build_brief(project, **kwargs)
            encoded = json.dumps(result.to_dict())
            memory = load_latest_memory(project, **kwargs)
            default_exists = (project / ".project_memory").exists()
        self.assertEqual(result.checkpoint.latest_path, "external")
        self.assertNotIn(str(workspace), encoded)
        self.assertTrue(result.status_note.exists)
        self.assertIn("Example", memory.project_state["project_name"])
        self.assertFalse(default_exists)

    def test_configured_layout_ignores_misleading_default_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            init_repository(project)
            wrong = project / ".project_memory/latest"
            wrong.mkdir(parents=True)
            (wrong / "git_context.json").write_text("{broken", encoding="utf-8")
            base = root / "correct"
            latest = base / "right/latest"
            write_latest(project, latest, name="Right project")
            kwargs = {"project_name": "right", "base_output_dir": base}
            fresh = check_checkpoint_freshness(project, **kwargs)
            brief = build_brief(project, **kwargs)
            memo = load_memo_context(project, **kwargs)
            status = load_latest_memory(project, **kwargs)
        self.assertEqual(fresh.status, "current")
        self.assertEqual(brief.checkpoint.status, "available")
        self.assertEqual(memo.project_state["project_name"], "Right project")
        self.assertEqual(status.project_state["project_name"], "Right project")

    def test_shared_output_base_keeps_projects_isolated(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            base = root / "shared"
            projects = []
            for name in ("a", "b"):
                project = root / f"project-{name}"
                project.mkdir()
                init_repository(project)
                write_latest(project, base / f"memory-{name}/latest", name=f"Project {name}")
                projects.append(project)
            first = load_memo_context(
                projects[0], project_name="memory-a", base_output_dir=base
            )
            second = load_memo_context(
                projects[1], project_name="memory-b", base_output_dir=base
            )
        self.assertEqual(first.project_state["project_name"], "Project a")
        self.assertEqual(second.project_state["project_name"], "Project b")


class LayoutCliTests(unittest.TestCase):
    def test_checkpoint_cli_rejects_legacy_and_named_arguments(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            error = StringIO()
            argv = [
                "pma",
                "--project-dir",
                temp_dir,
                "--output-dir",
                str(Path(temp_dir) / "legacy"),
                "--project-name",
                "named",
                "--base-output-dir",
                temp_dir,
            ]
            with (
                patch.object(sys, "argv", argv),
                redirect_stderr(error),
                self.assertRaises(SystemExit) as raised,
            ):
                checkpoint.main()
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--output-dir cannot be combined", error.getvalue())

    def test_brief_freshness_and_status_note_smoke_matrix(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            cases = (
                ("default", project / ".project_memory/latest", []),
                (
                    "named-internal",
                    project / "memory/latest",
                    ["--project-name", "memory", "--base-output-dir", str(project)],
                ),
                (
                    "named-external",
                    root / "external/alpha/latest",
                    [
                        "--project-name",
                        "alpha",
                        "--base-output-dir",
                        str(root / "external"),
                    ],
                ),
                (
                    "explicit",
                    root / "explicit/latest",
                    ["--latest-dir", str(root / "explicit/latest")],
                ),
                (
                    "legacy-consumer",
                    root / "legacy-direct",
                    ["--latest-dir", str(root / "legacy-direct")],
                ),
            )
            for name, latest, location_args in cases:
                with self.subTest(name=name):
                    write_latest(project, latest, name=name)
                    brief_output = StringIO()
                    with redirect_stdout(brief_output):
                        self.assertEqual(
                            run_brief(
                                ["--project-dir", str(project), "--json", *location_args]
                            ),
                            0,
                        )
                    brief_payload = json.loads(brief_output.getvalue())
                    self.assertEqual(brief_payload["checkpoint"]["status"], "available")
                    self.assertNotIn(str(root), brief_output.getvalue())

                    freshness_output = StringIO()
                    with redirect_stdout(freshness_output):
                        self.assertEqual(
                            run_freshness(
                                ["--project-dir", str(project), "--json", *location_args]
                            ),
                            0,
                        )
                    self.assertNotEqual(
                        json.loads(freshness_output.getvalue())["status"],
                        "no_checkpoint",
                    )

                    note_output = StringIO()
                    with redirect_stdout(note_output):
                        self.assertEqual(
                            run_status_note(
                                [
                                    "--project-dir",
                                    str(project),
                                    "--from-latest",
                                    *location_args,
                                ]
                            ),
                            0,
                        )
                    self.assertIn(f"- Project: {name}", note_output.getvalue())

    def test_freshness_and_brief_cli_use_explicit_latest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            project = root / "project"
            project.mkdir()
            latest = root / "external/latest"
            write_latest(project, latest)
            freshness_output = StringIO()
            with redirect_stdout(freshness_output):
                fresh_code = run_freshness(
                    ["--project-dir", str(project), "--latest-dir", str(latest), "--json"]
                )
            brief_output = StringIO()
            with redirect_stdout(brief_output):
                brief_code = run_brief(
                    ["--project-dir", str(project), "--latest-dir", str(latest), "--json"]
                )
        self.assertEqual(fresh_code, 0)
        self.assertEqual(brief_code, 0)
        self.assertNotEqual(json.loads(freshness_output.getvalue())["status"], "no_checkpoint")
        self.assertEqual(json.loads(brief_output.getvalue())["checkpoint"]["latest_path"], "external")

    def test_cli_rejects_contradictory_layout_arguments_cleanly(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            error = StringIO()
            with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                run_brief(
                    [
                        "--project-dir", temp_dir,
                        "--latest-dir", "one/latest",
                        "--project-name", "one",
                        "--base-output-dir", temp_dir,
                    ]
                )
        self.assertEqual(raised.exception.code, 2)
        self.assertIn("cannot be combined", error.getvalue())


if __name__ == "__main__":
    unittest.main()
