import os
import re
from pathlib import Path
from typing import Any

from openai import OpenAI

from prompts import (
    QUERY_PROJECT_MEMORY_PROMPT,
    QUERY_SOURCE_LOOKUP_INSTRUCTIONS,
)
from project_layout import resolve_checkpoint_layout
from source_lookup import (
    is_source_lookup_question,
    load_combined_notes,
    parse_source_sections,
    project_state_lookup_text,
    render_source_snippets,
    select_source_sections,
)


CONTEXT_FILES = (
    "project_state.json",
    "checkpoint_summary.md",
    "progress_since_last.md",
)


class QueryContextError(ValueError):
    """Raised when checkpoint memory cannot be used for a query."""


def locate_latest_checkpoint(
    project_dir: Path,
    *,
    project_name: str | None = None,
    base_output_dir: Path | None = None,
    latest_dir: Path | None = None,
) -> Path:
    layout = resolve_checkpoint_layout(
        project_dir,
        project_name=project_name,
        base_output_dir=base_output_dir,
        latest_dir=latest_dir,
    )
    if layout.mode == "default" and not layout.checkpoint_root.is_dir():
        raise QueryContextError(
            "No project memory directory found at .project_memory. "
            "Run a checkpoint first."
        )
    if not layout.latest_dir.is_dir():
        raise QueryContextError(
            f"No latest checkpoint found at {layout.latest_label()}. "
            "Run a checkpoint first."
        )
    return layout.latest_dir


def load_checkpoint_context(latest_dir: Path) -> tuple[dict[str, str], list[str]]:
    context: dict[str, str] = {}
    missing: list[str] = []

    for filename in CONTEXT_FILES:
        path = latest_dir / filename
        if not path.is_file():
            missing.append(filename)
            continue

        content = path.read_text(encoding="utf-8").strip()
        if content:
            context[filename] = content
        else:
            missing.append(filename)

    if not context:
        expected = ", ".join(CONTEXT_FILES)
        raise QueryContextError(
            f"No usable checkpoint files found in {latest_dir}. "
            f"Expected at least one of: {expected}."
        )

    return context, missing


def build_query_prompt(
    question: str,
    context: dict[str, str],
    missing: list[str],
    source_snippets: str = "",
) -> str:
    sections = []
    for filename in CONTEXT_FILES:
        if filename in context:
            sections.append(
                f"--- BEGIN {filename} ---\n"
                f"{context[filename]}\n"
                f"--- END {filename} ---"
            )

    missing_text = ", ".join(missing) if missing else "None"
    source_instructions = ""
    source_context = ""
    if source_snippets:
        source_instructions = QUERY_SOURCE_LOOKUP_INSTRUCTIONS
        source_context = (
            "Selected source-marker snippets:\n"
            f"{source_snippets}"
            if source_snippets
            else ""
        )

    return QUERY_PROJECT_MEMORY_PROMPT.format(
        question=question.strip(),
        missing_files=missing_text,
        context="\n\n".join(sections),
        source_instructions=source_instructions,
        source_context=source_context,
    )


def ensure_missing_files_reported(answer: str, missing: list[str]) -> str:
    if not missing or all(filename in answer for filename in missing):
        return answer

    note = f"- Missing checkpoint files: {', '.join(missing)}."
    uncertainty_heading = "Uncertainty / Missing info:"
    if uncertainty_heading in answer:
        return f"{answer.rstrip()}\n{note}"

    return f"{answer.rstrip()}\n\n{uncertainty_heading}\n{note}"


def ensure_source_issue_reported(answer: str, issue: str | None) -> str:
    if not issue or issue in answer:
        return answer

    note = f"- {issue}"
    uncertainty_heading = "Uncertainty / Missing info:"
    if uncertainty_heading in answer:
        return f"{answer.rstrip()}\n{note}"
    return f"{answer.rstrip()}\n\n{uncertainty_heading}\n{note}"


def ensure_source_issues_reported(answer: str, issues: list[str]) -> str:
    for issue in issues:
        answer = ensure_source_issue_reported(answer, issue)
    return answer


def normalize_source_citations(answer: str, sources: list[str]) -> str:
    if not sources:
        return answer

    grounded_text, uncertainty_heading, after = answer.partition(
        "Uncertainty / Missing info:"
    )
    for source in sorted(set(sources), key=len, reverse=True):
        pattern = re.compile(
            rf"(?<!combined_notes\.md SOURCE )"
            rf"(?<![A-Za-z0-9_./-]){re.escape(source)}"
            rf"(?![A-Za-z0-9_/-]|\.[A-Za-z0-9])"
        )
        grounded_text = pattern.sub(
            f"combined_notes.md SOURCE {source}",
            grounded_text,
        )

    return grounded_text + uncertainty_heading + after


def normalize_project_state_evidence_citations(
    answer: str,
    evidence_sources: list[str],
) -> str:
    if not evidence_sources or "Evidence:" not in answer:
        return answer

    before, heading, remainder = answer.partition("Evidence:")
    evidence, uncertainty_heading, after = remainder.partition(
        "Uncertainty / Missing info:"
    )
    for source in sorted(set(evidence_sources), key=len, reverse=True):
        pattern = re.compile(
            rf"(?<!project_state\.json evidence source )"
            rf"(?<![A-Za-z0-9_./-]){re.escape(source)}"
            rf"(?![A-Za-z0-9_/-]|\.[A-Za-z0-9])"
        )
        evidence = pattern.sub(
            f"project_state.json evidence source {source}",
            evidence,
        )

    return before + heading + evidence + uncertainty_heading + after


NO_UNCERTAINTY_BULLET = (
    "- None identified from the available checkpoint memory."
)


def remove_contradictory_no_uncertainty(answer: str) -> str:
    heading = "Uncertainty / Missing info:"
    if heading not in answer:
        return answer

    before, separator, uncertainty = answer.partition(heading)
    lines = uncertainty.splitlines()
    has_real_uncertainty = any(
        line.strip() and line.strip() != NO_UNCERTAINTY_BULLET for line in lines
    )
    if not has_real_uncertainty:
        return answer

    cleaned_lines = [
        line for line in lines if line.strip() != NO_UNCERTAINTY_BULLET
    ]
    return before + separator + "\n".join(cleaned_lines)


def ask_project_memory(
    question: str,
    project_dir: Path,
    model: str,
    client: Any | None = None,
    sources: bool = False,
    latest_dir: Path | None = None,
    project_name: str | None = None,
    base_output_dir: Path | None = None,
) -> str:
    if not question.strip():
        raise QueryContextError("The question must not be empty.")

    latest_dir = locate_latest_checkpoint(
        project_dir,
        latest_dir=latest_dir,
        project_name=project_name,
        base_output_dir=base_output_dir,
    )
    context, missing = load_checkpoint_context(latest_dir)
    use_source_lookup = sources or is_source_lookup_question(question)
    source_snippets = ""
    selected_sources: list[str] = []
    source_issues: list[str] = []
    if use_source_lookup:
        combined_notes = load_combined_notes(latest_dir)
        if combined_notes is None:
            source_issues.append(
                "Source-marker lookup is unavailable because "
                "`combined_notes.md` is missing or empty in the resolved latest checkpoint."
            )
        else:
            sections = parse_source_sections(combined_notes)
            if not sections:
                source_issues.append(
                    "Source-marker lookup was requested, but no SOURCE "
                    "markers were found in `combined_notes.md`."
                )
            else:
                snippets, diagnostics = select_source_sections(
                    sections=sections,
                    question=question,
                    project_state_json=context.get("project_state.json", ""),
                )
                source_issues.extend(diagnostics)
                source_snippets = render_source_snippets(snippets)
                selected_sources = [snippet.source for snippet in snippets]
                if not source_snippets:
                    source_issues.append(
                        "Source-marker lookup found no usable SOURCE snippets "
                        "in `combined_notes.md`."
                    )

    prompt = build_query_prompt(
        question,
        context,
        missing,
        source_snippets=source_snippets,
    )

    if client is None:
        if not os.getenv("OPENAI_API_KEY"):
            raise QueryContextError(
                "Missing LLM configuration: set OPENAI_API_KEY before using "
                "`pma ask`."
            )
        client = OpenAI()

    response = client.responses.create(model=model, input=prompt)
    answer = response.output_text.strip()
    if use_source_lookup:
        answer = normalize_source_citations(answer, selected_sources)
        _, evidence_sources = project_state_lookup_text(
            context.get("project_state.json", "")
        )
        answer = normalize_project_state_evidence_citations(
            answer,
            sorted(evidence_sources - set(selected_sources)),
        )
    else:
        _, evidence_sources = project_state_lookup_text(
            context.get("project_state.json", "")
        )
        answer = normalize_project_state_evidence_citations(
            answer,
            sorted(evidence_sources),
        )
    answer = ensure_missing_files_reported(answer, missing)
    answer = ensure_source_issues_reported(answer, source_issues)
    return remove_contradictory_no_uncertainty(answer)
