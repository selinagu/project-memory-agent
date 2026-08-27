import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SOURCE_MARKER_RE = re.compile(r"<!--\s*SOURCE:\s*(.*?)\s*-->")
TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")
# i think this is hard-coding again, not generalizable
SOURCE_LOOKUP_TERMS = {
    "artifact",
    "artifacts",
    "evidence",
    "grounded",
    "grounding",
    "quote",
    "quotes",
    "source",
    "sources",
    "support",
    "supports",
}


@dataclass(frozen=True)
class SourceSection:
    source: str
    text: str


@dataclass(frozen=True)
class ProjectStateLookupData:
    state: dict[str, Any]
    all_text: str
    evidence: tuple[tuple[str, str], ...]


def parse_source_sections(combined_notes: str) -> list[SourceSection]:
    matches = list(SOURCE_MARKER_RE.finditer(combined_notes))
    sections: list[SourceSection] = []

    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else None
        source = match.group(1).strip()
        if source:
            sections.append(
                SourceSection(
                    source=source,
                    text=combined_notes[start:end].strip(),
                )
            )

    return sections


def load_combined_notes(latest_dir: Path) -> str | None:
    path = latest_dir / "combined_notes.md"
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


# i think it is still very narrow in design
def is_source_lookup_question(question: str) -> bool:
    lowered = question.lower()
    tokens = _tokens(question)
    return bool(tokens & SOURCE_LOOKUP_TERMS) or (
        "where did" in lowered and "come from" in lowered
    ) or "why do we believe" in lowered


def _tokens(text: str) -> set[str]:
    return {token.lower() for token in TOKEN_RE.findall(text)}


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result = []
        for item in value:
            result.extend(_string_values(item))
        return result
    if isinstance(value, dict):
        result = []
        for item in value.values():
            result.extend(_string_values(item))
        return result
    return []


def _parse_project_state_lookup_data(
    project_state_json: str,
) -> ProjectStateLookupData | None:
    try:
        state = json.loads(project_state_json)
    except (json.JSONDecodeError, TypeError):
        return None

    if not isinstance(state, dict):
        return None

    evidence: list[tuple[str, str]] = []
    raw_evidence = state.get("evidence", [])

    if isinstance(raw_evidence, list):
        for item in raw_evidence:
            if not isinstance(item, dict):
                continue

            source = item.get("source")
            if not isinstance(source, str):
                continue

            source = source.strip()
            if not source:
                continue

            summary = item.get("quote_or_summary", "")
            evidence.append((source, str(summary)))

    return ProjectStateLookupData(
        state=state,
        all_text=" ".join(_string_values(state)),
        evidence=tuple(evidence),
    )


# What is the use of this function?
def project_state_lookup_text(
    project_state_json: str,
) -> tuple[str, set[str]]:
    lookup_data = _parse_project_state_lookup_data(project_state_json)

    if lookup_data is None:
        return "", set()

    evidence_sources = {
        source
        for source, _ in lookup_data.evidence
    }

    return lookup_data.all_text, evidence_sources


def _relevant_project_state_text(
    state: dict[str, Any],
    question_tokens: set[str],
) -> str:
    matched_fields: list[tuple[str, Any]] = []
    for field, value in state.items():
        field_tokens = _tokens(field.replace("_", " "))
        if question_tokens & field_tokens:
            matched_fields.append((field, value))

    substantive_fields = [
        item for item in matched_fields if item[0] != "evidence"
    ]
    relevant_values: list[str] = []
    for _, value in substantive_fields or matched_fields:
        relevant_values.extend(_string_values(value))
    return " ".join(relevant_values)


TRUNCATION_MARKER = "\n[Snippet truncated]"
MIN_SNIPPET_CONTENT_CHARS = 20

def _truncate_snippet(text: str, limit: int) -> str:
    stripped = text.strip()

    if len(stripped) <= limit:
        return stripped

    content_limit = limit - len(TRUNCATION_MARKER)
    if content_limit < MIN_SNIPPET_CONTENT_CHARS:
        return ""

    truncated = stripped[:content_limit]
    last_newline = truncated.rfind("\n")

    if last_newline > 0:
        truncated = truncated[:last_newline]

    truncated = truncated.rstrip()
    if not truncated:
        return ""

    return f"{truncated}{TRUNCATION_MARKER}"


def _bounded_sections(
    sections: list[SourceSection],
    max_count: int,
    max_chars_per_snippet: int,
    max_total_chars: int,
) -> list[SourceSection]:
    selected = []
    remaining = max_total_chars
    for section in sections:
        if len(selected) >= max_count or remaining <= 0:
            break
        limit = min(max_chars_per_snippet, remaining)
        text = _truncate_snippet(section.text, limit)
        if not text:
            break
        selected.append(SourceSection(source=section.source, text=text))
        remaining -= len(text)
    return selected


def select_source_sections(
    question: str,
    project_state_json: str,
    sections: list[SourceSection],
    top_k: int = 3,
    max_chars_per_snippet: int = 1200,
    max_total_chars: int = 3600,
) -> tuple[list[SourceSection], list[str]]:
    if top_k <= 0 or max_chars_per_snippet <= 0 or max_total_chars <= 0:
        return [], []

    lookup_data = _parse_project_state_lookup_data(project_state_json)
    if lookup_data is None:
        state: dict[str, Any] = {}
        state_text = ""
        state_evidence: list[tuple[str, str]] = []
    else:
        state = lookup_data.state
        state_text = lookup_data.all_text
        state_evidence = list(lookup_data.evidence)

    sections_by_source: dict[str, list[SourceSection]] = {}
    for section in sections:
        sections_by_source.setdefault(section.source, []).append(section)

    named_sources = list(dict.fromkeys(source for source, _ in state_evidence))
    diagnostics = [
        (
            f"`project_state.json` names `{source}` as evidence, but no "
            "matching SOURCE section was found in `combined_notes.md`."
        )
        for source in named_sources
        if source not in sections_by_source
    ]

    question_tokens = _tokens(question)
    state_tokens = _tokens(state_text)
    relevant_state_tokens = _tokens(
        _relevant_project_state_text(state, question_tokens)
    )
    evidence_text = {
        source: " ".join(
            summary
            for item_source, summary in state_evidence
            if item_source == source
        )
        for source in named_sources
    }

    ranked = []
    for index, section in enumerate(sections):
        section_tokens = _tokens(section.text)
        score = 5 * len(question_tokens & section_tokens)
        score += len(state_tokens & section_tokens)
        score += 8 * len(relevant_state_tokens & section_tokens)
        if section.source in evidence_text:
            score += 20
            score += 3 * len(
                question_tokens & _tokens(evidence_text[section.source])
            )
            score += 20 * len(
                relevant_state_tokens & _tokens(evidence_text[section.source])
            )
        ranked.append(
            (
                section.source not in evidence_text,
                -score,
                index,
                section,
            )
        )

    ordered = [
        item[-1]
        for item in sorted(ranked)
        if not item[0] or item[1] < 0
    ]
    return (
        _bounded_sections(
            ordered,
            max_count=top_k,
            max_chars_per_snippet=max_chars_per_snippet,
            max_total_chars=max_total_chars,
        ),
        diagnostics,
    )


# isn't this just wrapping selected_source_sections? why do we need this?
def select_source_snippets(
    sections: list[SourceSection],
    question: str,
    project_state_json: str,
    max_count: int = 5,
    max_chars_per_snippet: int = 1200,
    max_total_chars: int = 6000,
) -> list[SourceSection]:
    selected, _ = select_source_sections(
        question=question,
        project_state_json=project_state_json,
        sections=sections,
        top_k=max_count,
        max_chars_per_snippet=max_chars_per_snippet,
        max_total_chars=max_total_chars,
    )
    return selected


def render_source_snippets(snippets: list[SourceSection]) -> str:
    return "\n\n".join(
        f"--- BEGIN combined_notes.md SOURCE {snippet.source} ---\n"
        f"{snippet.text}\n"
        f"--- END combined_notes.md SOURCE {snippet.source} ---"
        for snippet in snippets
    )
