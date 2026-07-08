import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pma
from memo import (
    build_group_update_prompt,
    build_self_memo_prompt,
    enforce_group_update_field_boundaries,
    ensure_group_window_uncertainty,
    ensure_group_update_basis,
    enforce_memo_field_boundaries,
    generate_group_update_memo,
    generate_self_memo,
    load_memo_context,
    normalize_memo_markdown,
    normalize_memo_evidence_citations,
)
from query import QueryContextError
from progress_window import (
    CheckpointRun,
    ProgressEntry,
    ProgressWindow,
    load_progress_window,
)


PROJECT_STATE = """{
  "project_name": "Cache Lab",
  "one_sentence_summary": "Reduce cache latency.",
  "goal": "Improve p95 latency.",
  "current_stage": "Benchmarking",
  "confirmed_findings": ["The small workload improved."],
  "tentative_hypotheses": ["Cache churn may explain regressions."],
  "important_decisions": [],
  "failed_attempts": [],
  "open_questions": ["Does prefetching cause churn?"],
  "next_actions": ["Run the recorded prefetch-disabled ablation."],
  "evidence": [
    {
      "source": "results.md",
      "quote_or_summary": "The small workload improved."
    }
  ],
  "last_updated": null
}"""


class FakeResponses:
    def __init__(self, output_text: str = "# Project Memory Memo\n\nMock memo.") -> None:
        self.output_text = output_text
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text=self.output_text)


def make_latest(project_dir: Path) -> Path:
    latest = project_dir / ".project_memory" / "latest"
    latest.mkdir(parents=True)
    return latest


class MemoTests(unittest.TestCase):
    def test_load_context_requires_project_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            make_latest(project_dir)

            with self.assertRaisesRegex(
                QueryContextError,
                "Required checkpoint state is missing or empty",
            ):
                load_memo_context(project_dir)

    def test_load_context_rejects_invalid_project_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = make_latest(project_dir)
            (latest / "project_state.json").write_text(
                "not json",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                QueryContextError,
                "not valid JSON",
            ):
                load_memo_context(project_dir)

    def test_load_context_reports_missing_memory_and_latest(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            with self.assertRaisesRegex(
                QueryContextError,
                "No project memory directory",
            ):
                load_memo_context(project_dir)

            (project_dir / ".project_memory").mkdir()
            with self.assertRaisesRegex(
                QueryContextError,
                "No latest checkpoint",
            ):
                load_memo_context(project_dir)

    def test_optional_files_can_be_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = make_latest(project_dir)
            (latest / "project_state.json").write_text(
                PROJECT_STATE,
                encoding="utf-8",
            )

            context = load_memo_context(project_dir)

            self.assertIsNone(context.checkpoint_summary)
            self.assertIsNone(context.progress_since_last)
            self.assertEqual(
                context.missing_optional_files,
                ["checkpoint_summary.md", "progress_since_last.md"],
            )

    def test_prompt_includes_checkpoint_context_and_bounded_source_snippets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = make_latest(project_dir)
            (latest / "project_state.json").write_text(
                PROJECT_STATE,
                encoding="utf-8",
            )
            (latest / "checkpoint_summary.md").write_text(
                "Summary context.",
                encoding="utf-8",
            )
            (latest / "progress_since_last.md").write_text(
                "Progress context.",
                encoding="utf-8",
            )
            (latest / "combined_notes.md").write_text(
                "<!-- SOURCE: results.md -->\n"
                "The small workload improved.\n"
                "STALE_DETAIL_NOT_RECORDED_IN_PROJECT_STATE\n"
                "<!-- SOURCE: unrelated.md -->\n"
                "ENTIRE_COMBINED_NOTES_SENTINEL",
                encoding="utf-8",
            )

            prompt = build_self_memo_prompt(load_memo_context(project_dir))

            self.assertIn('"project_name": "Cache Lab"', prompt)
            self.assertIn("Summary context.", prompt)
            self.assertIn("Progress context.", prompt)
            self.assertIn("combined_notes.md SOURCE results.md", prompt)
            self.assertIn("The small workload improved.", prompt)
            self.assertNotIn("STALE_DETAIL_NOT_RECORDED", prompt)
            self.assertNotIn("ENTIRE_COMBINED_NOTES_SENTINEL", prompt)
            self.assertIn("raw artifacts were not independently opened", prompt)
            self.assertIn("approximately 250-600 words", prompt)
            self.assertIn("closer to 200-300 words", prompt)
            self.assertIn("allow 400-600 words", prompt)
            self.assertIn("Prioritize rapid recall over completeness", prompt)
            self.assertIn("Do not expand into a group-update", prompt)

    def test_generate_self_memo_calls_llm_with_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = make_latest(project_dir)
            (latest / "project_state.json").write_text(
                PROJECT_STATE,
                encoding="utf-8",
            )
            responses = FakeResponses()
            client = SimpleNamespace(responses=responses)

            memo = generate_self_memo(
                project_dir,
                "test-model",
                client=client,
            )

            self.assertEqual(memo, "# Project Memory Memo\n\nMock memo.")
            self.assertEqual(responses.calls[0]["model"], "test-model")
            self.assertIn("Cache Lab", responses.calls[0]["input"])
            self.assertIn("## Next actions", responses.calls[0]["input"])

    def test_group_update_prompt_is_latest_only_and_uses_bounded_sources(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = make_latest(project_dir)
            (latest / "project_state.json").write_text(
                PROJECT_STATE,
                encoding="utf-8",
            )
            (latest / "checkpoint_summary.md").write_text(
                "Summary context.",
                encoding="utf-8",
            )
            (latest / "progress_since_last.md").write_text(
                "Added the recorded ablation.",
                encoding="utf-8",
            )
            (latest / "combined_notes.md").write_text(
                "<!-- SOURCE: results.md -->\n"
                "The small workload improved.\n"
                "SOURCE_ONLY_DETAIL_NOT_IN_STATE",
                encoding="utf-8",
            )

            prompt = build_group_update_prompt(load_memo_context(project_dir))

            self.assertIn('"project_name": "Cache Lab"', prompt)
            self.assertIn("Summary context.", prompt)
            self.assertIn("Added the recorded ablation.", prompt)
            self.assertIn("combined_notes.md SOURCE results.md", prompt)
            self.assertNotIn("SOURCE_ONLY_DETAIL_NOT_IN_STATE", prompt)
            self.assertIn("Step 4A latest-only update", prompt)
            self.assertIn(
                "does not aggregate multiple history runs",
                prompt,
            )
            self.assertIn("## Progress since last checkpoint", prompt)
            self.assertIn("## Planned next actions", prompt)

    def test_group_update_missing_progress_is_explicit(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = make_latest(project_dir)
            (latest / "project_state.json").write_text(
                PROJECT_STATE,
                encoding="utf-8",
            )
            responses = FakeResponses(
                "# Project Group Update\n\n"
                "## Progress since last checkpoint\n"
                "- No progress details.\n\n"
                "## Notes / uncertainty\n"
                "- None."
            )
            client = SimpleNamespace(responses=responses)

            memo = generate_group_update_memo(
                project_dir,
                "test-model",
                client=client,
            )

            self.assertIn(
                "Checkpoint-to-checkpoint progress cannot be established",
                memo,
            )
            self.assertIn("progress_since_last.md", memo)
            self.assertIn("(unavailable)", responses.calls[0]["input"])

    def test_windowed_group_update_uses_only_historical_progress_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = make_latest(project_dir)
            (latest / "project_state.json").write_text(
                PROJECT_STATE,
                encoding="utf-8",
            )
            runs_dir = project_dir / ".project_memory" / "runs"
            for timestamp, progress in (
                ("2026-07-01", "Completed historical experiment A."),
                ("2026-07-02", "Added historical-only action B."),
            ):
                run_dir = runs_dir / timestamp
                run_dir.mkdir(parents=True)
                (run_dir / "progress_since_last.md").write_text(
                    progress,
                    encoding="utf-8",
                )
                (run_dir / "project_state.json").write_text(
                    f"HISTORICAL_STATE_{timestamp}",
                    encoding="utf-8",
                )
                (run_dir / "combined_notes.md").write_text(
                    f"HISTORICAL_COMBINED_{timestamp}",
                    encoding="utf-8",
                )

            responses = FakeResponses(
                "# Project Group Update\n\n"
                "## TL;DR\n- Window summary.\n\n"
                "## Update window\n- Model basis.\n\n"
                "## Progress this period\n"
                "- Completed historical experiment A.\n"
                "- Added historical-only action B.\n\n"
                "## Current status\n- Model status.\n\n"
                "## Confirmed findings\n- Model finding.\n\n"
                "## Tentative hypotheses / interpretation\n- Model hypothesis.\n\n"
                "## Failed attempts / blockers\n- Model blocker.\n\n"
                "## Open questions\n- Model question.\n\n"
                "## Planned next actions\n- Historical-only action B.\n\n"
                "## Evidence pointers\n- State.\n\n"
                "## Notes / uncertainty\n- None."
            )
            client = SimpleNamespace(responses=responses)

            memo = generate_group_update_memo(
                project_dir,
                "test-model",
                client=client,
                last=2,
            )
            prompt = responses.calls[0]["input"]

            self.assertLess(
                prompt.index("run 2026-07-01"),
                prompt.index("run 2026-07-02"),
            )
            self.assertIn("Completed historical experiment A.", prompt)
            self.assertIn("Added historical-only action B.", prompt)
            self.assertNotIn("HISTORICAL_STATE_", prompt)
            self.assertNotIn("HISTORICAL_COMBINED_", prompt)
            self.assertIn("- Completed historical experiment A.", memo)
            self.assertIn("- Added historical-only action B.", memo)
            planned = memo.split("## Planned next actions", 1)[1].split(
                "## Evidence pointers",
                1,
            )[0]
            self.assertEqual(
                planned.strip(),
                "- Run the recorded prefetch-disabled ablation.",
            )
            self.assertIn("Included checkpoints: 2", memo)
            self.assertIn(
                "latest ProjectState remains current-state authority",
                memo,
            )

    def test_windowed_prompt_instructs_chronological_conflict_resolution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = make_latest(project_dir)
            latest_state = PROJECT_STATE.replace(
                '"The small workload improved."',
                '"Corrected result Y."',
            )
            (latest / "project_state.json").write_text(
                latest_state,
                encoding="utf-8",
            )
            runs_dir = project_dir / ".project_memory" / "runs"
            earlier = runs_dir / "2026-07-01"
            later = runs_dir / "2026-07-02"
            earlier.mkdir(parents=True)
            later.mkdir(parents=True)
            (earlier / "progress_since_last.md").write_text(
                "Initial result X.",
                encoding="utf-8",
            )
            (later / "progress_since_last.md").write_text(
                "Result X was corrected to result Y.",
                encoding="utf-8",
            )

            context = load_memo_context(project_dir)
            runs = [
                CheckpointRun(timestamp="2026-07-01", path=earlier),
                CheckpointRun(timestamp="2026-07-02", path=later),
            ]
            window = load_progress_window(runs, requested_last=2)
            prompt = build_group_update_prompt(context, window)

            self.assertLess(
                prompt.index("Initial result X."),
                prompt.index("corrected to result Y"),
            )
            self.assertIn(
                "ordered chronologically from oldest to newest",
                prompt,
            )
            self.assertIn(
                "do not present both versions as simultaneously true",
                prompt,
            )
            self.assertIn(
                "latest ProjectState as authority for the resolved/current",
                prompt,
            )
            self.assertIn(
                "report the unresolved conflict under Notes / uncertainty",
                prompt,
            )

    def test_latest_state_replaces_historical_result_in_confirmed_section(self):
        memo = (
            "# Project Group Update\n\n"
            "## Current status\n- Model status.\n\n"
            "## Confirmed findings\n"
            "- Historical result X.\n"
            "- Corrected result Y.\n\n"
            "## Tentative hypotheses / interpretation\n- None.\n\n"
            "## Failed attempts / blockers\n- None.\n\n"
            "## Open questions\n- None.\n\n"
            "## Planned next actions\n- Historical action.\n\n"
            "## Evidence pointers\n- State."
        )
        state = {
            "goal": "Goal.",
            "current_stage": "Stage.",
            "confirmed_findings": ["Corrected result Y."],
            "tentative_hypotheses": [],
            "failed_attempts": [],
            "open_questions": [],
            "next_actions": ["Current action."],
        }

        result = enforce_group_update_field_boundaries(memo, state)
        confirmed = result.split("## Confirmed findings", 1)[1].split(
            "## Tentative hypotheses / interpretation",
            1,
        )[0]

        self.assertIn("Corrected result Y.", confirmed)
        self.assertNotIn("Historical result X.", confirmed)
        self.assertIn("- Current action.", result)
        self.assertNotIn("- Historical action.", result)

    def test_window_uncertainty_reports_no_runs_missing_and_truncation(self):
        window = ProgressWindow(
            requested_last=3,
            selected_runs=[],
            progress_entries=[],
            missing_progress_runs=["2026-07-02"],
            truncated=True,
        )
        memo = (
            "# Project Group Update\n\n"
            "## Notes / uncertainty\n"
            "- Existing note."
        )

        result = ensure_group_window_uncertainty(memo, window)

        self.assertIn("No history runs were available for `--last 3`", result)
        self.assertIn("2026-07-02", result)
        self.assertIn("window is incomplete", result)
        self.assertIn("progress context was truncated", result)

    def test_since_window_uncertainty_reports_no_matching_runs(self):
        window = ProgressWindow(
            requested_since=date(2026, 7, 1),
            selected_runs=[],
            progress_entries=[],
            unparseable_runs=["bad-run"],
        )
        memo = (
            "# Project Group Update\n\n"
            "## Notes / uncertainty\n"
            "- Existing note."
        )

        result = ensure_group_window_uncertainty(memo, window)

        self.assertIn(
            "No checkpoint runs matched `--since 2026-07-01`",
            result,
        )
        self.assertIn("bad-run", result)

    def test_since_window_prompt_includes_date_runs_and_conflict_rules(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = make_latest(project_dir)
            (latest / "project_state.json").write_text(
                PROJECT_STATE,
                encoding="utf-8",
            )
            run_path = project_dir / ".project_memory" / "runs" / "2026-07-01"
            run_path.mkdir(parents=True)
            progress_path = run_path / "progress_since_last.md"
            progress_path.write_text("Corrected result Y.", encoding="utf-8")
            (run_path / "project_state.json").write_text(
                "HISTORICAL_STATE_MUST_NOT_APPEAR",
                encoding="utf-8",
            )
            window = ProgressWindow(
                requested_since=date(2026, 7, 1),
                selected_runs=[
                    CheckpointRun(timestamp="2026-07-01", path=run_path)
                ],
                progress_entries=[
                    ProgressEntry(
                        timestamp="2026-07-01",
                        text="Corrected result Y.",
                        source_path=progress_path,
                    )
                ],
                unparseable_runs=["bad-run-name"],
            )

            prompt = build_group_update_prompt(
                load_memo_context(project_dir),
                window,
            )

            self.assertIn("on or after\n2026-07-01", prompt)
            self.assertIn("2026-07-01", prompt)
            self.assertIn("Corrected result Y.", prompt)
            self.assertIn("bad-run-name", prompt)
            self.assertIn(
                "latest project_state.json remains authoritative",
                prompt,
            )
            self.assertIn(
                "Historical\nprogress cannot override latest ProjectState",
                prompt,
            )
            self.assertIn(
                "summarize the evolution rather than presenting both as true",
                prompt,
            )
            self.assertIn("Notes / uncertainty instead of choosing a side", prompt)
            self.assertNotIn("HISTORICAL_STATE_MUST_NOT_APPEAR", prompt)

    def test_generate_group_update_calls_llm_with_group_prompt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = make_latest(project_dir)
            (latest / "project_state.json").write_text(
                PROJECT_STATE,
                encoding="utf-8",
            )
            responses = FakeResponses(
                "# Project Group Update\n\nMock update."
            )
            client = SimpleNamespace(responses=responses)

            memo = generate_group_update_memo(
                project_dir,
                "test-model",
                client=client,
            )

            self.assertEqual(
                memo,
                "# Project Group Update\n\nMock update.\n\n"
                "## Progress since last checkpoint\n"
                "- Checkpoint-to-checkpoint progress cannot be established "
                "because latest `progress_since_last.md` is unavailable.",
            )
            self.assertEqual(responses.calls[0]["model"], "test-model")
            self.assertIn("# Project Group Update", responses.calls[0]["input"])
            self.assertIn("latest-only", responses.calls[0]["input"])

    def test_unselected_evidence_source_is_attributed_to_project_state(self):
        memo = (
            "# Project Memory Memo\n\n"
            "## What we know\n"
            "- notes.md records the goal.\n\n"
            "## Evidence pointers\n"
            "- notes.md records the goal.\n\n"
            "## Notes / uncertainty\n"
            "- None."
        )

        result = normalize_memo_evidence_citations(memo, ["notes.md"])

        self.assertEqual(
            result.count(
                "project_state.json evidence source notes.md records the goal"
            ),
            2,
        )

    def test_memo_markdown_removes_fences_and_normalizes_headings(self):
        memo = (
            "```markdown\n"
            "# Project Group Update\n\n"
            "  ## Tentative hypotheses / interpretation\n"
            "- Tentative item.\n"
            "```"
        )

        self.assertEqual(
            normalize_memo_markdown(memo),
            "# Project Group Update\n\n"
            "## Tentative hypotheses / interpretation\n"
            "- Tentative item.",
        )

    def test_tentative_hypothesis_is_removed_from_what_we_know(self):
        memo = (
            "# Project Memory Memo\n\n"
            "## What we know\n"
            "- The small workload improved.\n"
            "- Cache churn may explain regressions. This is tentative.\n\n"
            "## What is still tentative\n"
            "- Cache churn may explain regressions.\n"
        )
        state = {
            "tentative_hypotheses": ["Cache churn may explain regressions."]
        }

        result = enforce_memo_field_boundaries(memo, state)
        confirmed = result.split("## What is still tentative", 1)[0]

        self.assertIn("The small workload improved.", confirmed)
        self.assertNotIn("Cache churn may explain regressions.", confirmed)
        self.assertIn(
            "Cache churn may explain regressions.",
            result.split("## What is still tentative", 1)[1],
        )

    def test_group_update_core_sections_use_exact_project_state_fields(self):
        memo = (
            "# Project Group Update\n\n"
            "## Progress since last checkpoint\n"
            "- Progress-only action was added.\n\n"
            "## Current status\n- Invented underway work.\n\n"
            "## Confirmed findings\n- Invented detail.\n\n"
            "## Tentative hypotheses / interpretation\n- Presented as fact.\n\n"
            "## Failed attempts / blockers\n- Invented blocker.\n\n"
            "## Open questions\n- Invented question.\n\n"
            "## Planned next actions\n- Elaborated action.\n\n"
            "## Evidence pointers\n- State."
        )
        state = {
            "goal": "Recorded goal.",
            "current_stage": "Recorded stage.",
            "confirmed_findings": ["Confirmed result."],
            "tentative_hypotheses": ["Possible explanation."],
            "failed_attempts": [],
            "open_questions": ["Recorded question?"],
            "next_actions": ["Run recorded experiment."],
        }

        result = enforce_group_update_field_boundaries(memo, state)

        self.assertIn("- Progress-only action was added.", result)
        self.assertIn("- Goal: Recorded goal.", result)
        self.assertIn("- Current stage: Recorded stage.", result)
        self.assertIn("- Confirmed result.", result)
        self.assertIn(
            "- Tentative / unverified: Possible explanation.",
            result,
        )
        self.assertIn("- No recorded failed attempts or blockers.", result)
        self.assertIn("- Recorded question?", result)
        self.assertIn("- Run recorded experiment.", result)
        self.assertNotIn("Invented", result)
        self.assertNotIn("Elaborated", result)

    def test_group_update_basis_with_available_progress_is_non_contradictory(self):
        memo = (
            "# Project Group Update\n\n"
            "## Update basis\n- Model-written basis.\n\n"
            "## Progress since last checkpoint\n"
            "- Grounded progress detail.\n"
        )

        result = ensure_group_update_basis(memo, progress_available=True)

        self.assertIn(
            "- Progress source: latest `progress_since_last.md`.",
            result,
        )
        self.assertNotIn("missing or empty", result)
        self.assertIn(
            "does not aggregate multiple history runs",
            result,
        )
        self.assertIn("- Grounded progress detail.", result)

    def test_group_update_basis_with_missing_progress_is_explicit(self):
        memo = (
            "# Project Group Update\n\n"
            "## Update basis\n- Model-written basis.\n\n"
            "## Progress since last checkpoint\n"
            "- No details.\n"
        )

        result = ensure_group_update_basis(memo, progress_available=False)

        self.assertIn(
            "latest `progress_since_last.md` is missing or empty",
            result,
        )
        self.assertIn(
            "does not aggregate multiple history runs",
            result,
        )

    def test_memo_cli_routes_and_prints_generated_memo(self):
        output = StringIO()
        with (
            patch.object(
                pma,
                "generate_self_memo",
                return_value="# Project Memory Memo\n\nMock memo.",
            ) as generate,
            redirect_stdout(output),
        ):
            exit_code = pma.run_memo(
                ["--project-dir", "/tmp/project", "--type", "self"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("# Project Memory Memo", output.getvalue())
        generate.assert_called_once()
        self.assertEqual(
            generate.call_args.kwargs["project_dir"],
            Path("/tmp/project"),
        )

    def test_group_update_cli_routes_and_prints_generated_memo(self):
        output = StringIO()
        with (
            patch.object(
                pma,
                "generate_group_update_memo",
                return_value="# Project Group Update\n\nMock update.",
            ) as generate,
            redirect_stdout(output),
        ):
            exit_code = pma.run_memo(
                ["--type", "group-update", "--project-dir", "/tmp/project"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIn("# Project Group Update", output.getvalue())
        generate.assert_called_once()
        self.assertEqual(
            generate.call_args.kwargs["project_dir"],
            Path("/tmp/project"),
        )
        self.assertIsNone(generate.call_args.kwargs["last"])
        self.assertIsNone(generate.call_args.kwargs["since"])

    def test_windowed_group_update_cli_passes_last(self):
        output = StringIO()
        with (
            patch.object(
                pma,
                "generate_group_update_memo",
                return_value="# Project Group Update\n\nWindowed.",
            ) as generate,
            redirect_stdout(output),
        ):
            exit_code = pma.run_memo(
                ["--type", "group-update", "--last", "3"]
            )

        self.assertEqual(exit_code, 0)
        self.assertEqual(generate.call_args.kwargs["last"], 3)
        self.assertIsNone(generate.call_args.kwargs["since"])

    def test_since_group_update_cli_passes_parsed_date(self):
        output = StringIO()
        with (
            patch.object(
                pma,
                "generate_group_update_memo",
                return_value="# Project Group Update\n\nDate window.",
            ) as generate,
            redirect_stdout(output),
        ):
            exit_code = pma.run_memo(
                ["--type", "group-update", "--since", "2026-07-01"]
            )

        self.assertEqual(exit_code, 0)
        self.assertIsNone(generate.call_args.kwargs["last"])
        self.assertEqual(
            generate.call_args.kwargs["since"],
            date(2026, 7, 1),
        )

    def test_last_is_rejected_for_self_memo(self):
        error = StringIO()
        with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            pma.run_memo(["--type", "self", "--last", "3"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn(
            "--last is only supported for --type group-update.",
            error.getvalue(),
        )

    def test_non_positive_last_is_rejected(self):
        error = StringIO()
        with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            pma.run_memo(["--type", "group-update", "--last", "0"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn("--last must be a positive integer.", error.getvalue())

    def test_since_is_rejected_for_self_memo(self):
        error = StringIO()
        with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            pma.run_memo(
                ["--type", "self", "--since", "2026-07-01"]
            )

        self.assertEqual(raised.exception.code, 2)
        self.assertIn(
            "--since is only supported for --type group-update.",
            error.getvalue(),
        )

    def test_last_and_since_are_mutually_exclusive(self):
        error = StringIO()
        with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            pma.run_memo(
                [
                    "--type",
                    "group-update",
                    "--last",
                    "3",
                    "--since",
                    "2026-07-01",
                ]
            )

        self.assertEqual(raised.exception.code, 2)
        self.assertIn(
            "--last and --since are mutually exclusive.",
            error.getvalue(),
        )

    def test_invalid_since_date_is_rejected(self):
        for value in ("2026/07/01", "July 1", "bad-date"):
            error = StringIO()
            with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
                pma.run_memo(
                    ["--type", "group-update", "--since", value]
                )

            self.assertEqual(raised.exception.code, 2)
            self.assertIn(
                "--since must be a valid date in YYYY-MM-DD format.",
                error.getvalue(),
            )

    def test_memo_cli_rejects_unsupported_type(self):
        error = StringIO()
        with redirect_stderr(error), self.assertRaises(SystemExit) as raised:
            pma.run_memo(["--type", "daily"])

        self.assertEqual(raised.exception.code, 2)
        self.assertIn(
            "Unsupported memo type: daily. "
            "Currently supported types: self, group-update.",
            error.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
