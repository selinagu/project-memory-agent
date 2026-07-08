import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pma
from query import (
    QueryContextError,
    ask_project_memory,
    build_query_prompt,
    ensure_missing_files_reported,
    normalize_project_state_evidence_citations,
    normalize_source_citations,
    remove_contradictory_no_uncertainty,
    load_checkpoint_context,
    locate_latest_checkpoint,
)
from source_lookup import SourceSection, parse_source_sections, select_source_snippets
from source_lookup import is_source_lookup_question, select_source_sections


class FakeResponses:
    def __init__(self) -> None:
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(output_text="Answer:\nGrounded answer.")


class QueryTests(unittest.TestCase):
    def test_locates_latest_checkpoint(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = project_dir / ".project_memory" / "latest"
            latest.mkdir(parents=True)

            self.assertEqual(locate_latest_checkpoint(project_dir), latest.resolve())

    def test_loads_available_files_and_reports_missing_optional_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            latest = Path(temp_dir)
            (latest / "project_state.json").write_text(
                '{"goal": "Ship ask"}', encoding="utf-8"
            )

            context, missing = load_checkpoint_context(latest)

            self.assertEqual(context["project_state.json"], '{"goal": "Ship ask"}')
            self.assertEqual(
                missing,
                ["checkpoint_summary.md", "progress_since_last.md"],
            )

    def test_errors_when_no_checkpoint_exists(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                QueryContextError, "No project memory directory"
            ):
                locate_latest_checkpoint(Path(temp_dir))

    def test_errors_when_latest_checkpoint_is_missing(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            (project_dir / ".project_memory").mkdir()

            with self.assertRaisesRegex(QueryContextError, "No latest checkpoint"):
                locate_latest_checkpoint(project_dir)

    def test_errors_when_checkpoint_has_no_usable_files(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            with self.assertRaisesRegex(
                QueryContextError, "No usable checkpoint files"
            ):
                load_checkpoint_context(Path(temp_dir))

    def test_builds_prompt_with_question_context_and_missing_files(self):
        prompt = build_query_prompt(
            "What is next?",
            {"checkpoint_summary.md": "Next: add tests."},
            ["progress_since_last.md"],
        )

        self.assertIn("What is next?", prompt)
        self.assertIn("Next: add tests.", prompt)
        self.assertIn("progress_since_last.md", prompt)
        self.assertIn("--- BEGIN checkpoint_summary.md ---", prompt)

    def test_query_prompt_is_project_state_schema_aware(self):
        prompt = build_query_prompt(
            "What hypotheses and next actions are recorded?",
            {
                "project_state.json": (
                    '{"tentative_hypotheses": ["Caching may help"], '
                    '"next_actions": ["Run the recorded benchmark"]}'
                )
            },
            ["checkpoint_summary.md", "progress_since_last.md"],
        )

        for field in (
            "confirmed_findings",
            "tentative_hypotheses",
            "important_decisions",
            "failed_attempts",
            "open_questions",
            "next_actions",
            "evidence",
        ):
            self.assertIn(field, prompt)
        self.assertIn("Do not generate recommendations", prompt)
        self.assertIn("tentative and unverified", prompt)
        self.assertIn("use project_state.json as the primary source", prompt)

    def test_query_prompt_routes_progress_questions_to_progress_file(self):
        prompt = build_query_prompt(
            "What changed since the last checkpoint?",
            {"project_state.json": '{"goal": "Ship query"}'},
            ["progress_since_last.md"],
        )

        self.assertIn("prioritize progress_since_last.md", prompt)
        self.assertIn("checkpoint-to-checkpoint change cannot be", prompt)
        self.assertIn("established from the available memory", prompt)

    def test_missing_report_is_unchanged_when_no_files_are_missing(self):
        answer = (
            "Answer:\nGoal.\n\nEvidence:\n- State.\n\n"
            "Uncertainty / Missing info:\n- None."
        )

        self.assertEqual(ensure_missing_files_reported(answer, []), answer)

    def test_missing_report_is_added_to_existing_uncertainty_section(self):
        answer = (
            "Answer:\nGoal.\n\nEvidence:\n- State.\n\n"
            "Uncertainty / Missing info:\n- None."
        )

        result = ensure_missing_files_reported(
            answer,
            ["checkpoint_summary.md", "progress_since_last.md"],
        )

        self.assertTrue(
            result.endswith(
                "- Missing checkpoint files: checkpoint_summary.md, "
                "progress_since_last.md."
            )
        )
        self.assertEqual(result.count("Uncertainty / Missing info:"), 1)

    def test_missing_report_is_not_duplicated_when_all_files_are_mentioned(self):
        answer = (
            "Answer:\nGoal.\n\nEvidence:\n- State.\n\n"
            "Uncertainty / Missing info:\n"
            "- checkpoint_summary.md and progress_since_last.md are missing."
        )

        self.assertEqual(
            ensure_missing_files_reported(
                answer,
                ["checkpoint_summary.md", "progress_since_last.md"],
            ),
            answer,
        )

    def test_missing_report_appends_uncertainty_section_when_absent(self):
        answer = "Answer:\nGoal.\n\nEvidence:\n- State."

        result = ensure_missing_files_reported(
            answer,
            ["checkpoint_summary.md"],
        )

        self.assertEqual(
            result,
            f"{answer}\n\nUncertainty / Missing info:\n"
            "- Missing checkpoint files: checkpoint_summary.md.",
        )

    def test_ask_calls_llm_with_loaded_context(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = project_dir / ".project_memory" / "latest"
            latest.mkdir(parents=True)
            (latest / "project_state.json").write_text(
                '{"goal": "Ship ask"}', encoding="utf-8"
            )
            responses = FakeResponses()
            client = SimpleNamespace(responses=responses)

            answer = ask_project_memory(
                "What is the goal?",
                project_dir,
                "test-model",
                client=client,
            )

            self.assertEqual(
                answer,
                "Answer:\nGrounded answer.\n\n"
                "Uncertainty / Missing info:\n"
                "- Missing checkpoint files: checkpoint_summary.md, "
                "progress_since_last.md.",
            )
            self.assertEqual(responses.calls[0]["model"], "test-model")
            self.assertIn("Ship ask", responses.calls[0]["input"])
            self.assertIn("What is the goal?", responses.calls[0]["input"])

    def test_ask_reports_missing_files_with_only_project_state(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = project_dir / ".project_memory" / "latest"
            latest.mkdir(parents=True)
            (latest / "project_state.json").write_text(
                '{"goal": "Ship ask"}', encoding="utf-8"
            )
            client = SimpleNamespace(responses=FakeResponses())

            answer = ask_project_memory(
                "What is the goal?",
                project_dir,
                "test-model",
                client=client,
            )

            self.assertIn("checkpoint_summary.md", answer)
            self.assertIn("progress_since_last.md", answer)
            self.assertIn("Uncertainty / Missing info:", answer)

    def test_parses_multiple_source_sections_and_preserves_paths(self):
        sections = parse_source_sections(
            "preamble without a source\n"
            "<!-- SOURCE: path/to/first.md -->\nFirst text.\n"
            "<!-- SOURCE: nested/second file.txt -->\nSecond text."
        )

        self.assertEqual(
            sections,
            [
                SourceSection(source="path/to/first.md", text="First text."),
                SourceSection(
                    source="nested/second file.txt",
                    text="Second text.",
                ),
            ],
        )

    def test_source_parser_ignores_text_before_first_marker(self):
        sections = parse_source_sections(
            "This preamble must not become a source section.\n"
            "<!-- SOURCE: notes.md -->\nRecorded material."
        )

        self.assertEqual(len(sections), 1)
        self.assertNotIn("preamble", sections[0].text)

    def test_source_selection_respects_count_and_character_bounds(self):
        sections = [
            SourceSection(source=f"source-{index}.md", text="goal " + "x" * 100)
            for index in range(4)
        ]

        selected = select_source_snippets(
            sections,
            question="goal",
            project_state_json='{"goal": "goal"}',
            max_count=2,
            max_chars_per_snippet=20,
            max_total_chars=30,
        )

        self.assertLessEqual(len(selected), 2)
        self.assertTrue(all(len(section.text) <= 20 for section in selected))
        self.assertLessEqual(sum(len(section.text) for section in selected), 30)

    def test_source_lookup_trigger_policy(self):
        for question in (
            "What evidence supports the finding?",
            "Which source records this?",
            "Where did this conclusion come from?",
            "Why do we believe this result?",
            "Can you quote the artifact grounding?",
        ):
            self.assertTrue(
                is_source_lookup_question(question),
                f"Expected source lookup for: {question}",
            )

        self.assertFalse(is_source_lookup_question("What is the project goal?"))
        self.assertFalse(
            is_source_lookup_question("What changed since the last checkpoint?")
        )

    def test_exact_project_state_evidence_source_is_selected(self):
        sections = [
            SourceSection(source="a.md", text="Recorded result."),
            SourceSection(source="other.md", text="Unrelated material."),
        ]
        state = (
            '{"evidence": [{"source": "a.md", '
            '"quote_or_summary": "Recorded result"}]}'
        )

        selected, diagnostics = select_source_sections(
            "What evidence supports the result?",
            state,
            sections,
            top_k=1,
        )

        self.assertEqual([section.source for section in selected], ["a.md"])
        self.assertEqual(diagnostics, [])

    def test_substantive_state_field_guides_evidence_source_ranking(self):
        sections = [
            SourceSection(source="results.md", text="Latency improved."),
            SourceSection(source="plans.md", text="Run another benchmark."),
        ]
        state = (
            '{"confirmed_findings": ["Latency improved."], '
            '"next_actions": ["Run another benchmark."], '
            '"evidence": ['
            '{"source": "results.md", "quote_or_summary": "Latency improved."},'
            '{"source": "plans.md", "quote_or_summary": "Run another benchmark."}'
            "]}"
        )

        selected, _ = select_source_sections(
            "What evidence supports the confirmed findings?",
            state,
            sections,
            top_k=1,
        )

        self.assertEqual([section.source for section in selected], ["results.md"])

    def test_missing_project_state_evidence_source_returns_diagnostic(self):
        state = (
            '{"evidence": [{"source": "missing.md", '
            '"quote_or_summary": "Recorded result"}]}'
        )

        selected, diagnostics = select_source_sections(
            "What evidence supports the result?",
            state,
            [SourceSection(source="other.md", text="Unrelated material.")],
        )

        self.assertEqual(selected, [])
        self.assertEqual(len(diagnostics), 1)
        self.assertIn("`missing.md`", diagnostics[0])
        self.assertIn("no matching SOURCE section", diagnostics[0])

    def test_ask_without_sources_does_not_include_combined_notes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = project_dir / ".project_memory" / "latest"
            latest.mkdir(parents=True)
            (latest / "project_state.json").write_text(
                '{"goal": "Ship ask"}', encoding="utf-8"
            )
            (latest / "combined_notes.md").write_text(
                "<!-- SOURCE: secret.md -->\nMUST_NOT_BE_INCLUDED",
                encoding="utf-8",
            )
            responses = FakeResponses()
            client = SimpleNamespace(responses=responses)

            ask_project_memory(
                "What is the goal?",
                project_dir,
                "test-model",
                client=client,
            )

            self.assertNotIn("MUST_NOT_BE_INCLUDED", responses.calls[0]["input"])
            self.assertNotIn("combined_notes.md SOURCE", responses.calls[0]["input"])

    def test_ask_with_sources_includes_bounded_source_snippets(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = project_dir / ".project_memory" / "latest"
            latest.mkdir(parents=True)
            (latest / "project_state.json").write_text(
                '{"goal": "Ship ask", "evidence": '
                '[{"source": "notes.md", "quote_or_summary": "Recorded goal"}]}',
                encoding="utf-8",
            )
            (latest / "combined_notes.md").write_text(
                "<!-- SOURCE: notes.md -->\nRecorded goal: ship ask.",
                encoding="utf-8",
            )
            responses = FakeResponses()
            client = SimpleNamespace(responses=responses)

            ask_project_memory(
                "What evidence supports the goal?",
                project_dir,
                "test-model",
                client=client,
                sources=True,
            )

            prompt = responses.calls[0]["input"]
            self.assertIn("combined_notes.md SOURCE notes.md", prompt)
            self.assertIn("Recorded goal: ship ask.", prompt)
            self.assertIn("raw artifacts were not independently opened", prompt)
            self.assertIn(
                "must cite it exactly as:\n  combined_notes.md SOURCE",
                prompt,
            )
            self.assertIn("Do not cite the path alone", prompt)
            self.assertIn(
                "every Evidence bullet must cite one of these forms",
                prompt,
            )

    def test_evidence_question_automatically_includes_only_relevant_snippet(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = project_dir / ".project_memory" / "latest"
            latest.mkdir(parents=True)
            (latest / "project_state.json").write_text(
                '{"confirmed_findings": ["Cache latency improved"], '
                '"evidence": [{"source": "results.md", '
                '"quote_or_summary": "Cache latency improved"}]}',
                encoding="utf-8",
            )
            (latest / "combined_notes.md").write_text(
                "<!-- SOURCE: results.md -->\nCache latency improved by 10%.\n"
                "<!-- SOURCE: unrelated.md -->\n"
                "WHOLE_FILE_SENTINEL_WITH_NO_RELEVANT_TERMS",
                encoding="utf-8",
            )
            responses = FakeResponses()
            client = SimpleNamespace(responses=responses)

            ask_project_memory(
                "What evidence supports the confirmed finding?",
                project_dir,
                "test-model",
                client=client,
            )

            prompt = responses.calls[0]["input"]
            self.assertIn("combined_notes.md SOURCE results.md", prompt)
            self.assertIn("Cache latency improved by 10%.", prompt)
            self.assertNotIn("WHOLE_FILE_SENTINEL", prompt)

    def test_ask_with_sources_reports_missing_combined_notes(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = project_dir / ".project_memory" / "latest"
            latest.mkdir(parents=True)
            (latest / "project_state.json").write_text("{}", encoding="utf-8")
            client = SimpleNamespace(responses=FakeResponses())

            answer = ask_project_memory(
                "What evidence is available?",
                project_dir,
                "test-model",
                client=client,
                sources=True,
            )

            self.assertIn("Source-marker lookup is unavailable", answer)
            self.assertIn(
                "`.project_memory/latest/combined_notes.md` is missing or empty",
                answer,
            )

    def test_ask_with_sources_reports_no_source_markers(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project_dir = Path(temp_dir)
            latest = project_dir / ".project_memory" / "latest"
            latest.mkdir(parents=True)
            (latest / "project_state.json").write_text("{}", encoding="utf-8")
            (latest / "combined_notes.md").write_text(
                "Notes without marker comments.", encoding="utf-8"
            )
            client = SimpleNamespace(responses=FakeResponses())

            answer = ask_project_memory(
                "What evidence is available?",
                project_dir,
                "test-model",
                client=client,
                sources=True,
            )

            self.assertIn("no SOURCE markers were found", answer)

    def test_source_citations_are_normalized_in_grounded_sections(self):
        answer = (
            "Answer:\nSee notes.md.\n\n"
            "Evidence:\n- Recorded in notes.md.\n\n"
            "Uncertainty / Missing info:\n- notes.md may be incomplete."
        )

        result = normalize_source_citations(answer, ["notes.md"])

        self.assertIn(
            "Answer:\nSee combined_notes.md SOURCE notes.md.",
            result,
        )
        self.assertIn(
            "Evidence:\n- Recorded in combined_notes.md SOURCE notes.md.",
            result,
        )
        self.assertIn("- notes.md may be incomplete.", result)

    def test_existing_source_citation_is_not_duplicated(self):
        answer = (
            "Answer:\nSupported.\n\nEvidence:\n"
            "- combined_notes.md SOURCE notes.md supports it.\n\n"
            "Uncertainty / Missing info:\n- None."
        )

        self.assertEqual(normalize_source_citations(answer, ["notes.md"]), answer)

    def test_default_evidence_source_is_attributed_to_project_state(self):
        answer = (
            "Answer:\nSupported.\n\n"
            "Evidence:\n- Recorded in notes.md.\n\n"
            "Uncertainty / Missing info:\n- notes.md may be incomplete."
        )

        result = normalize_project_state_evidence_citations(
            answer,
            ["notes.md"],
        )

        self.assertIn(
            "Evidence:\n- Recorded in "
            "project_state.json evidence source notes.md.",
            result,
        )
        self.assertIn("- notes.md may be incomplete.", result)

    def test_existing_project_state_evidence_citation_is_not_duplicated(self):
        answer = (
            "Answer:\nSupported.\n\nEvidence:\n"
            "- project_state.json evidence source notes.md supports it.\n\n"
            "Uncertainty / Missing info:\n- None."
        )

        self.assertEqual(
            normalize_project_state_evidence_citations(answer, ["notes.md"]),
            answer,
        )

    def test_removes_none_placeholder_when_real_uncertainty_exists(self):
        answer = (
            "Answer:\nKnown.\n\nEvidence:\n- State.\n\n"
            "Uncertainty / Missing info:\n"
            "- Missing checkpoint files: checkpoint_summary.md.\n"
            "- None identified from the available checkpoint memory."
        )

        result = remove_contradictory_no_uncertainty(answer)

        self.assertIn("Missing checkpoint files", result)
        self.assertNotIn("None identified", result)

    def test_keeps_none_placeholder_when_it_is_the_only_uncertainty(self):
        answer = (
            "Answer:\nKnown.\n\nEvidence:\n- State.\n\n"
            "Uncertainty / Missing info:\n"
            "- None identified from the available checkpoint memory."
        )

        self.assertEqual(remove_contradictory_no_uncertainty(answer), answer)

    def test_ask_command_prints_llm_response(self):
        output = StringIO()
        with (
            patch.object(
                pma,
                "ask_project_memory",
                return_value=(
                    "Answer:\nDone.\n\nEvidence:\n- State.\n\n"
                    "Uncertainty / Missing info:\n- None."
                ),
            ) as mock_ask,
            redirect_stdout(output),
        ):
            exit_code = pma.run_ask(["--sources", "What is done?"])

        self.assertEqual(exit_code, 0)
        self.assertIn("Answer:\nDone.", output.getvalue())
        mock_ask.assert_called_once()
        self.assertTrue(mock_ask.call_args.kwargs["sources"])


if __name__ == "__main__":
    unittest.main()
