import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from project_layout import resolve_checkpoint_layout


class StatusNoteError(ValueError):
    """Raised when a status note cannot be written safely."""


@dataclass(frozen=True)
class LatestMemory:
    project_state: dict[str, Any] | None = None
    checkpoint_summary: str | None = None
    progress_since_last: str | None = None
    missing: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


def _read_optional_text(path: Path) -> str | None:
    if not path.is_file():
        return None
    text = path.read_text(encoding="utf-8").strip()
    return text or None


def resolve_latest_dir(
    project_dir: Path,
    latest_dir: Path | None = None,
    *,
    project_name: str | None = None,
    base_output_dir: Path | None = None,
) -> Path:
    return resolve_checkpoint_layout(
        project_dir,
        latest_dir=latest_dir,
        project_name=project_name,
        base_output_dir=base_output_dir,
    ).latest_dir


def load_latest_memory(
    project_dir: Path,
    latest_dir: Path | None = None,
    *,
    project_name: str | None = None,
    base_output_dir: Path | None = None,
) -> LatestMemory:
    latest_dir = resolve_latest_dir(
        project_dir,
        latest_dir,
        project_name=project_name,
        base_output_dir=base_output_dir,
    )
    expected = (
        "project_state.json",
        "checkpoint_summary.md",
        "progress_since_last.md",
    )

    if not latest_dir.is_dir():
        return LatestMemory(
            missing=expected,
            errors=(f"No latest checkpoint found at {latest_dir}.",),
        )

    missing: list[str] = []
    errors: list[str] = []
    project_state = None

    state_text = _read_optional_text(latest_dir / "project_state.json")
    if state_text is None:
        missing.append("project_state.json")
    else:
        try:
            parsed = json.loads(state_text)
            if isinstance(parsed, dict):
                project_state = parsed
            else:
                errors.append("project_state.json did not contain a JSON object.")
        except json.JSONDecodeError as exc:
            errors.append(f"project_state.json is invalid JSON: {exc}.")

    checkpoint_summary = _read_optional_text(latest_dir / "checkpoint_summary.md")
    if checkpoint_summary is None:
        missing.append("checkpoint_summary.md")

    progress_since_last = _read_optional_text(latest_dir / "progress_since_last.md")
    if progress_since_last is None:
        missing.append("progress_since_last.md")

    return LatestMemory(
        project_state=project_state,
        checkpoint_summary=checkpoint_summary,
        progress_since_last=progress_since_last,
        missing=tuple(missing),
        errors=tuple(errors),
    )


def _list_items(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


def _bullet_list(items: list[str], placeholder: str = "TODO") -> str:
    if not items:
        return f"- {placeholder}"
    return "\n".join(f"- {item}" for item in items)


def _truncate_lines(text: str, max_lines: int = 8) -> str:
    lines = [line.rstrip() for line in text.strip().splitlines() if line.strip()]
    if not lines:
        return "TODO"
    selected = lines[:max_lines]
    if len(lines) > max_lines:
        selected.append("...")
    return "\n".join(selected)


def _format_evidence(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []

    formatted: list[str] = []
    for item in value:
        if isinstance(item, dict):
            source = item.get("source", "unknown source")
            summary = item.get("quote_or_summary", "")
            formatted.append(f"`{source}`: {summary}".strip())
        elif str(item).strip():
            formatted.append(str(item))

    return formatted


def build_template_status_note(memory: LatestMemory | None = None) -> str:
    missing_note = ""
    if memory and (memory.missing or memory.errors):
        details = [*memory.errors]
        if memory.missing:
            details.append(f"Missing latest checkpoint files: {', '.join(memory.missing)}.")
        missing_note = "\n".join(f"- {detail}" for detail in details)
    else:
        missing_note = "- TODO"

    return (
        "# Project Status\n\n"
        "## Project overview\n\n"
        "- TODO: Describe the project and its goal.\n\n"
        "## Current stage\n\n"
        "- TODO: Describe the current stage.\n\n"
        "## Recent progress\n\n"
        "- TODO: Summarize recent progress since the last meaningful checkpoint.\n\n"
        "## Confirmed findings\n\n"
        "- TODO: List only supported conclusions or observations.\n\n"
        "## Uncertainty and unresolved items\n\n"
        "- TODO: Record tentative hypotheses, failed or blocked attempts, and open questions.\n\n"
        "## Current next actions\n\n"
        "- TODO: List source-grounded next actions only.\n\n"
        "## Validation / evidence\n\n"
        "- TODO: Record tests, eval results, source files, or evidence references.\n\n"
        "## Notes for next checkpoint\n\n"
        f"{missing_note}\n"
    )


def build_status_note_from_latest(memory: LatestMemory) -> str:
    state = memory.project_state
    if not state:
        return build_template_status_note(memory)

    project_name = state.get("project_name") or "TODO"
    summary = state.get("one_sentence_summary") or "TODO"
    goal = state.get("goal") or "TODO"
    current_stage = state.get("current_stage") or "TODO"
    findings = _list_items(state.get("confirmed_findings"))
    hypotheses = _list_items(state.get("tentative_hypotheses"))
    failed = _list_items(state.get("failed_attempts"))
    questions = _list_items(state.get("open_questions"))
    next_actions = _list_items(state.get("next_actions"))
    evidence = _format_evidence(state.get("evidence", []))

    unresolved_items = []
    unresolved_items.extend(
        f"Tentative hypothesis: {item}"
        for item in hypotheses
    )
    unresolved_items.extend(
        f"Failed / blocked attempt: {item}"
        for item in failed
    )
    unresolved_items.extend(
        f"Open question: {item}"
        for item in questions
    )


    notes = []
    if memory.missing:
        notes.append(f"Missing latest checkpoint files: {', '.join(memory.missing)}.")
    notes.extend(memory.errors)
    if not notes:
        notes.append("TODO: Add context that should be preserved for the next checkpoint.")

    recent_progress = memory.progress_since_last or memory.checkpoint_summary or "TODO"

    return (
        "# Project Status\n\n"
        "## Project overview\n\n"
        f"- Project: {project_name}\n"
        f"- Summary: {summary}\n"
        f"- Goal: {goal}\n\n"
        "## Current stage\n\n"
        f"- {current_stage}\n\n"
        "## Recent progress\n\n"
        f"{_truncate_lines(recent_progress)}\n\n"
        "## Confirmed findings\n\n"
        f"{_bullet_list(findings, 'TODO: List supported findings.')}\n\n"
        "## Uncertainty and unresolved items\n\n"
        f"{_bullet_list(unresolved_items, 'TODO: Record uncertainty or unresolved items.')}\n\n"
        "## Current next actions\n\n"
        f"{_bullet_list(next_actions, 'TODO: List recorded next actions.')}\n\n"
        "## Validation / evidence\n\n"
        f"{_bullet_list(evidence, 'TODO: Record validation or evidence references.')}\n\n"
        "## Notes for next checkpoint\n\n"
        f"{_bullet_list(notes)}\n"
    )


def build_status_note(
    project_dir: Path,
    from_latest: bool = False,
    latest_dir: Path | None = None,
    project_name: str | None = None,
    base_output_dir: Path | None = None,
) -> str:
    if not from_latest:
        return build_template_status_note()

    memory = load_latest_memory(
        project_dir,
        latest_dir,
        project_name=project_name,
        base_output_dir=base_output_dir,
    )
    return build_status_note_from_latest(memory)


def write_status_note(output_path: Path, note: str, force: bool = False) -> None:
    output_path = output_path.expanduser()
    if output_path.exists() and not force:
        raise StatusNoteError(
            f"Refusing to overwrite existing status note at {output_path}. "
            "Pass --force or choose another --output path."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(note, encoding="utf-8")
