import json
import os
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from openai import OpenAI

from progress_window import (
    ProgressWindow,
    list_checkpoint_runs,
    load_progress_window,
    render_progress_window,
    select_recent_runs,
    select_runs_since,
)
from prompts import (
    GROUP_UPDATE_MEMO_PROMPT,
    GROUP_UPDATE_SINCE_MEMO_PROMPT,
    GROUP_UPDATE_WINDOW_MEMO_PROMPT,
    SELF_MEMO_PROMPT,
)
from query import (
    QueryContextError,
    locate_latest_checkpoint,
    normalize_source_citations,
)
from source_lookup import (
    SourceSection,
    load_combined_notes,
    parse_source_sections,
    project_state_lookup_text,
    render_source_snippets,
    select_source_sections,
)


@dataclass(frozen=True)
class MemoContext:
    latest_dir: Path
    project_state_text: str
    project_state: dict[str, Any]
    checkpoint_summary: str | None = None
    progress_since_last: str | None = None
    source_snippets: list[SourceSection] = field(default_factory=list)
    source_diagnostics: list[str] = field(default_factory=list)
    missing_optional_files: list[str] = field(default_factory=list)


def _ground_source_snippets_in_state(
    snippets: list[SourceSection],
    project_state: dict[str, Any],
) -> list[SourceSection]:
    anchor_fields = (
        "goal",
        "current_stage",
        "confirmed_findings",
        "tentative_hypotheses",
        "open_questions",
        "next_actions",
    )
    anchors = []
    for field_name in anchor_fields:
        value = project_state.get(field_name)
        if isinstance(value, str):
            anchors.append(value)
        elif isinstance(value, list):
            anchors.extend(item for item in value if isinstance(item, str))

    grounded = []
    for snippet in snippets:
        matched = []
        lowered = snippet.text.lower()
        for anchor in anchors:
            if anchor.lower() in lowered and anchor not in matched:
                matched.append(anchor)
        if matched:
            grounded.append(
                SourceSection(
                    source=snippet.source,
                    text="\n".join(f"- {item}" for item in matched),
                )
            )
    return grounded


def load_memo_context(
    project_dir: Path,
    *,
    latest_dir: Path | None = None,
    project_name: str | None = None,
    base_output_dir: Path | None = None,
) -> MemoContext:
    latest_dir = locate_latest_checkpoint(
        project_dir,
        latest_dir=latest_dir,
        project_name=project_name,
        base_output_dir=base_output_dir,
    )
    state_path = latest_dir / "project_state.json"
    if not state_path.is_file() or not state_path.read_text(encoding="utf-8").strip():
        raise QueryContextError(
            f"Required checkpoint state is missing or empty at {state_path}. "
            "Run a checkpoint first."
        )

    project_state_text = state_path.read_text(encoding="utf-8").strip()
    try:
        project_state = json.loads(project_state_text)
    except json.JSONDecodeError as exc:
        raise QueryContextError(
            f"Required checkpoint state is not valid JSON at {state_path}. "
            "Run a checkpoint first."
        ) from exc
    if not isinstance(project_state, dict):
        raise QueryContextError(
            f"Required checkpoint state is unusable at {state_path}. "
            "Run a checkpoint first."
        )

    optional_context: dict[str, str | None] = {}
    missing_optional_files = []
    for filename in ("checkpoint_summary.md", "progress_since_last.md"):
        path = latest_dir / filename
        text = path.read_text(encoding="utf-8").strip() if path.is_file() else ""
        optional_context[filename] = text or None
        if not text:
            missing_optional_files.append(filename)

    source_snippets: list[SourceSection] = []
    source_diagnostics: list[str] = []
    combined_notes = load_combined_notes(latest_dir)
    if combined_notes:
        sections = parse_source_sections(combined_notes)
        if sections:
            findings_snippets, findings_diagnostics = select_source_sections(
                question="confirmed findings tentative hypotheses evidence",
                project_state_json=project_state_text,
                sections=sections,
                top_k=2,
            )
            action_snippets, action_diagnostics = select_source_sections(
                question="next actions open questions evidence",
                project_state_json=project_state_text,
                sections=sections,
                top_k=1,
            )
            source_diagnostics = list(
                dict.fromkeys(findings_diagnostics + action_diagnostics)
            )
            source_snippets = list(
                dict.fromkeys(findings_snippets + action_snippets)
            )[:3]
            source_snippets = _ground_source_snippets_in_state(
                source_snippets,
                project_state,
            )
        else:
            source_diagnostics.append(
                "No SOURCE markers were found in `combined_notes.md`."
            )

    return MemoContext(
        latest_dir=latest_dir,
        project_state_text=project_state_text,
        project_state=project_state,
        checkpoint_summary=optional_context["checkpoint_summary.md"],
        progress_since_last=optional_context["progress_since_last.md"],
        source_snippets=source_snippets,
        source_diagnostics=source_diagnostics,
        missing_optional_files=missing_optional_files,
    )


def build_self_memo_prompt(context: MemoContext) -> str:
    summary = context.checkpoint_summary or "(unavailable)"
    progress = context.progress_since_last or "(unavailable)"
    snippets = render_source_snippets(context.source_snippets) or "(none selected)"
    diagnostics = (
        "\n".join(f"- {item}" for item in context.source_diagnostics)
        or "- None"
    )
    missing = ", ".join(context.missing_optional_files) or "None"

    return SELF_MEMO_PROMPT.format(
        project_state=context.project_state_text,
        checkpoint_summary=summary,
        progress_since_last=progress,
        source_snippets=snippets,
        source_diagnostics=diagnostics,
        missing_optional_files=missing,
    )


def build_group_update_prompt(
    context: MemoContext,
    progress_window: ProgressWindow | None = None,
) -> str:
    summary = context.checkpoint_summary or "(unavailable)"
    progress = context.progress_since_last or "(unavailable)"
    snippets = render_source_snippets(context.source_snippets) or "(none selected)"
    diagnostics = (
        "\n".join(f"- {item}" for item in context.source_diagnostics)
        or "- None"
    )
    missing = ", ".join(context.missing_optional_files) or "None"

    if progress_window is None:
        prompt = GROUP_UPDATE_MEMO_PROMPT
    elif progress_window.requested_since is not None:
        prompt = GROUP_UPDATE_SINCE_MEMO_PROMPT
    else:
        prompt = GROUP_UPDATE_WINDOW_MEMO_PROMPT
    window_values = {}
    if progress_window is not None:
        selected = (
            "\n".join(
                f"  - {run.timestamp}" for run in progress_window.selected_runs
            )
            or "  - None"
        )
        missing_progress = (
            "\n".join(
                f"  - {timestamp}"
                for timestamp in progress_window.missing_progress_runs
            )
            or "  - None"
        )
        window_values = {
            "requested_last": progress_window.requested_last,
            "selected_run_count": len(progress_window.selected_runs),
            "selected_runs": selected,
            "missing_progress_runs": missing_progress,
            "progress_window_truncated": str(progress_window.truncated).lower(),
            "progress_window": render_progress_window(progress_window),
            "requested_since": (
                progress_window.requested_since.isoformat()
                if progress_window.requested_since
                else ""
            ),
            "unparseable_runs": (
                "\n".join(
                    f"  - {name}" for name in progress_window.unparseable_runs
                )
                or "  - None"
            ),
        }

    return prompt.format(
        project_state=context.project_state_text,
        checkpoint_summary=summary,
        progress_since_last=progress,
        source_snippets=snippets,
        source_diagnostics=diagnostics,
        missing_optional_files=missing,
        **window_values,
    )


def _memo_client(client: Any | None) -> Any:
    if client is not None:
        return client
    if not os.getenv("OPENAI_API_KEY"):
        raise QueryContextError(
            "Missing LLM configuration: set OPENAI_API_KEY before using "
            "`pma memo`."
        )
    return OpenAI()


def _normalize_memo_citations(memo: str, context: MemoContext) -> str:
    memo = normalize_memo_markdown(memo)
    selected_sources = {
        snippet.source for snippet in context.source_snippets
    }
    memo = normalize_source_citations(memo, sorted(selected_sources))
    for source in sorted(selected_sources, key=len, reverse=True):
        citation = f"combined_notes.md SOURCE {source}"
        memo = re.sub(
            rf"({re.escape(citation)})(?:,\s*\1)+",
            r"\1",
            memo,
        )
    _, evidence_sources = project_state_lookup_text(context.project_state_text)
    return normalize_memo_evidence_citations(
        memo,
        sorted(evidence_sources - selected_sources),
    )


def normalize_memo_markdown(memo: str) -> str:
    memo = memo.strip()
    if memo.startswith("```markdown"):
        memo = memo.removeprefix("```markdown").lstrip()
    elif memo.startswith("```"):
        memo = memo.removeprefix("```").lstrip()
    if memo.endswith("```"):
        memo = memo.removesuffix("```").rstrip()
    return re.sub(r"^[ \t]+(?=#+\s)", "", memo, flags=re.MULTILINE)


def generate_self_memo(
    project_dir: Path,
    model: str,
    client: Any | None = None,
    latest_dir: Path | None = None,
    project_name: str | None = None,
    base_output_dir: Path | None = None,
) -> str:
    context = load_memo_context(
        project_dir,
        latest_dir=latest_dir,
        project_name=project_name,
        base_output_dir=base_output_dir,
    )
    prompt = build_self_memo_prompt(context)
    client = _memo_client(client)
    response = client.responses.create(model=model, input=prompt)
    memo = _normalize_memo_citations(response.output_text.strip(), context)
    return enforce_memo_field_boundaries(memo, context.project_state)


def generate_group_update_memo(
    project_dir: Path,
    model: str,
    client: Any | None = None,
    last: int | None = None,
    since: date | None = None,
    latest_dir: Path | None = None,
    project_name: str | None = None,
    base_output_dir: Path | None = None,
) -> str:
    context = load_memo_context(
        project_dir,
        latest_dir=latest_dir,
        project_name=project_name,
        base_output_dir=base_output_dir,
    )
    progress_window = None
    if last is not None and since is not None:
        raise QueryContextError("--last and --since are mutually exclusive.")
    if last is not None:
        if last <= 0:
            raise QueryContextError("--last must be a positive integer.")
        runs = list_checkpoint_runs(context.latest_dir.parent)
        selected_runs = select_recent_runs(runs, last)
        progress_window = load_progress_window(
            selected_runs,
            requested_last=last,
        )
    elif since is not None:
        runs = list_checkpoint_runs(context.latest_dir.parent)
        selected_runs, unparseable_runs = select_runs_since(runs, since)
        progress_window = load_progress_window(
            selected_runs,
            requested_since=since,
            unparseable_runs=unparseable_runs,
        )

    prompt = build_group_update_prompt(context, progress_window)
    client = _memo_client(client)
    response = client.responses.create(model=model, input=prompt)
    memo = _normalize_memo_citations(response.output_text.strip(), context)
    memo = enforce_group_update_field_boundaries(memo, context.project_state)
    if progress_window is not None:
        memo = ensure_group_update_window(memo, progress_window)
        return ensure_group_window_uncertainty(memo, progress_window)

    progress_available = context.progress_since_last is not None
    memo = ensure_group_update_basis(
        memo,
        progress_available=progress_available,
    )
    return ensure_group_progress_note(
        memo,
        progress_available=progress_available,
    )


def normalize_memo_evidence_citations(
    memo: str,
    evidence_sources: list[str],
) -> str:
    if not evidence_sources:
        return memo

    grounded, notes_heading, after = memo.partition("## Notes / uncertainty")
    for source in sorted(set(evidence_sources), key=len, reverse=True):
        pattern = re.compile(
            rf"(?<!project_state\.json evidence source )"
            rf"(?<![A-Za-z0-9_./-]){re.escape(source)}"
            rf"(?![A-Za-z0-9_/-]|\.[A-Za-z0-9])"
        )
        grounded = pattern.sub(
            f"project_state.json evidence source {source}",
            grounded,
        )
    return grounded + notes_heading + after


def enforce_memo_field_boundaries(
    memo: str,
    project_state: dict[str, Any],
) -> str:
    heading = "## What we know"
    next_heading = "## What is still tentative"
    if heading not in memo or next_heading not in memo:
        return memo

    before, separator, remainder = memo.partition(heading)
    confirmed, tentative_heading, after = remainder.partition(next_heading)
    hypotheses = [
        " ".join(re.findall(r"[a-z0-9]+", item.lower()))
        for item in project_state.get("tentative_hypotheses", [])
        if isinstance(item, str)
    ]
    confirmed_lines = [
        line
        for line in confirmed.splitlines()
        if not any(
            hypothesis
            in " ".join(re.findall(r"[a-z0-9]+", line.lower()))
            for hypothesis in hypotheses
        )
    ]
    return (
        before
        + separator
        + "\n".join(confirmed_lines)
        + tentative_heading
        + after
    )


def enforce_group_update_field_boundaries(
    memo: str,
    project_state: dict[str, Any],
) -> str:
    status_lines = []
    goal = project_state.get("goal")
    current_stage = project_state.get("current_stage")
    status_lines.append(
        f"- Goal: {goal}" if isinstance(goal, str) and goal else "- Goal: Not recorded."
    )
    status_lines.append(
        (
            f"- Current stage: {current_stage}"
            if isinstance(current_stage, str) and current_stage
            else "- Current stage: Not recorded."
        )
    )
    memo = _replace_memo_section(
        memo,
        "## Current status",
        "## Confirmed findings",
        "\n".join(status_lines),
    )

    sections = (
        (
            "## Confirmed findings",
            "## Tentative hypotheses / interpretation",
            project_state.get("confirmed_findings"),
            "No recorded confirmed findings.",
            "",
        ),
        (
            "## Tentative hypotheses / interpretation",
            "## Failed attempts / blockers",
            project_state.get("tentative_hypotheses"),
            "No recorded tentative hypotheses.",
            "Tentative / unverified: ",
        ),
        (
            "## Failed attempts / blockers",
            "## Open questions",
            project_state.get("failed_attempts"),
            "No recorded failed attempts or blockers.",
            "",
        ),
        (
            "## Open questions",
            "## Planned next actions",
            project_state.get("open_questions"),
            "No recorded open questions.",
            "",
        ),
        (
            "## Planned next actions",
            "## Evidence pointers",
            project_state.get("next_actions"),
            "No recorded planned next actions.",
            "",
        ),
    )
    for heading, next_heading, values, empty_text, prefix in sections:
        items = values if isinstance(values, list) else []
        body = "\n".join(
            f"- {prefix}{item}" for item in items if isinstance(item, str)
        )
        if not body:
            body = f"- {empty_text}"
        memo = _replace_memo_section(
            memo,
            heading,
            next_heading,
            body,
        )
    return memo


def _replace_memo_section(
    memo: str,
    heading: str,
    next_heading: str,
    body: str,
) -> str:
    if heading not in memo or next_heading not in memo:
        return memo
    before, separator, remainder = memo.partition(heading)
    _, next_separator, after = remainder.partition(next_heading)
    return (
        f"{before}{separator}\n{body}\n\n"
        f"{next_separator}\n{after.lstrip()}"
    )


def ensure_group_progress_note(memo: str, progress_available: bool) -> str:
    if progress_available or "cannot be established" in memo.lower():
        return memo

    heading = "## Progress since last checkpoint"
    note = (
        "- Checkpoint-to-checkpoint progress cannot be established because "
        "latest `progress_since_last.md` is unavailable."
    )
    if heading not in memo:
        return f"{memo.rstrip()}\n\n{heading}\n{note}"

    before, separator, after = memo.partition(heading)
    return f"{before}{separator}\n{note}{after}"


def ensure_group_update_basis(memo: str, progress_available: bool) -> str:
    progress_source = (
        "- Progress source: latest `progress_since_last.md`."
        if progress_available
        else "- Progress source: unavailable; latest `progress_since_last.md` "
        "is missing or empty."
    )
    body = "\n".join(
        (
            "- Based on: latest checkpoint memory.",
            progress_source,
            "- Scope note: this Step 4A update does not aggregate multiple "
            "history runs.",
        )
    )
    return _replace_memo_section(
        memo,
        "## Update basis",
        "## Progress since last checkpoint",
        body,
    )


def ensure_group_update_window(
    memo: str,
    window: ProgressWindow,
) -> str:
    selected = (
        "\n".join(f"  - {run.timestamp}" for run in window.selected_runs)
        or "  - None available"
    )
    missing = (
        "\n".join(f"  - {timestamp}" for timestamp in window.missing_progress_runs)
        or "  - None"
    )
    unparseable = (
        "\n".join(f"  - {name}" for name in window.unparseable_runs)
        or "  - None"
    )
    if window.requested_since is not None:
        since = window.requested_since.isoformat()
        basis = (
            f"- Basis: latest ProjectState + checkpoint progress summaries "
            f"since {since}."
        )
        requested = f"- Requested since date: {since}"
    else:
        basis = (
            f"- Basis: latest ProjectState + last {window.requested_last} "
            "checkpoint progress summaries."
        )
        requested = f"- Requested runs: {window.requested_last}"

    body = "\n".join(
        (
            basis,
            requested,
            f"- Included checkpoints: {len(window.selected_runs)}",
            selected,
            "- Missing progress summaries:",
            missing,
            "- Excluded unparseable run directories:",
            unparseable,
            f"- Progress context truncated: {str(window.truncated).lower()}",
            "- Scope note: historical progress summarizes this reporting "
            "window only; latest ProjectState remains current-state authority.",
        )
    )
    return _replace_memo_section(
        memo,
        "## Update window",
        "## Progress this period",
        body,
    )


def ensure_group_window_uncertainty(
    memo: str,
    window: ProgressWindow,
) -> str:
    notes = []
    if not window.selected_runs:
        if window.requested_since is not None:
            notes.append(
                "No checkpoint runs matched "
                f"`--since {window.requested_since.isoformat()}`; no windowed "
                "progress could be established."
            )
        else:
            notes.append(
                f"No history runs were available for `--last "
                f"{window.requested_last}`."
            )
    if window.missing_progress_runs:
        notes.append(
            "The progress window is incomplete because these selected runs "
            "lack usable progress summaries: "
            + ", ".join(window.missing_progress_runs)
            + "."
        )
    if window.truncated:
        notes.append(
            "The selected progress context was truncated to the configured "
            "prompt-size bounds."
        )
    if window.unparseable_runs:
        notes.append(
            "These history run directories were excluded because their names "
            "could not be parsed as dates: "
            + ", ".join(window.unparseable_runs)
            + "."
        )
    if not notes:
        return memo

    heading = "## Notes / uncertainty"
    bullets = "\n".join(f"- {note}" for note in notes)
    if heading not in memo:
        return f"{memo.rstrip()}\n\n{heading}\n{bullets}"
    return f"{memo.rstrip()}\n{bullets}"
