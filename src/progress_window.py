from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
import re


MAX_PROGRESS_ENTRY_CHARS = 2500
MAX_PROGRESS_WINDOW_CHARS = 12000


@dataclass(frozen=True)
class CheckpointRun:
    timestamp: str
    path: Path


@dataclass(frozen=True)
class ProgressEntry:
    timestamp: str
    text: str
    source_path: Path


@dataclass(frozen=True)
class ProgressWindow:
    requested_last: int | None = None
    requested_since: date | None = None
    selected_runs: list[CheckpointRun] = field(default_factory=list)
    progress_entries: list[ProgressEntry] = field(default_factory=list)
    missing_progress_runs: list[str] = field(default_factory=list)
    unparseable_runs: list[str] = field(default_factory=list)
    truncated: bool = False


def list_checkpoint_runs(memory_dir: Path) -> list[CheckpointRun]:
    runs_dir = memory_dir / "runs"
    if not runs_dir.is_dir():
        return []
    return [
        CheckpointRun(timestamp=path.name, path=path)
        for path in sorted(runs_dir.iterdir(), key=lambda item: item.name)
        if path.is_dir()
    ]


def select_recent_runs(
    runs: list[CheckpointRun],
    last: int,
) -> list[CheckpointRun]:
    if last <= 0:
        raise ValueError("last must be a positive integer")
    return sorted(runs, key=lambda run: run.timestamp)[-last:]


def parse_since_date(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise ValueError("expected YYYY-MM-DD")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("expected a valid YYYY-MM-DD date") from exc


def parse_run_date(timestamp: str) -> date | None:
    formats = (
        "%Y-%m-%d",
        "%Y-%m-%d_%H%M%S",
        "%Y-%m-%dT%H%M%S",
    )
    for format_string in formats:
        try:
            return datetime.strptime(timestamp, format_string).date()
        except ValueError:
            continue
    return None


def select_runs_since(
    runs: list[CheckpointRun],
    since: date,
) -> tuple[list[CheckpointRun], list[str]]:
    selected = []
    unparseable = []
    for run in sorted(runs, key=lambda item: item.timestamp):
        run_date = parse_run_date(run.timestamp)
        if run_date is None:
            unparseable.append(run.timestamp)
        elif run_date >= since:
            selected.append(run)
    return selected, unparseable


def load_progress_window(
    selected_runs: list[CheckpointRun],
    requested_last: int | None = None,
    requested_since: date | None = None,
    unparseable_runs: list[str] | None = None,
    max_entry_chars: int = MAX_PROGRESS_ENTRY_CHARS,
    max_total_chars: int = MAX_PROGRESS_WINDOW_CHARS,
) -> ProgressWindow:
    entries = []
    missing = []
    remaining = max_total_chars
    truncated = False

    for run in sorted(selected_runs, key=lambda item: item.timestamp):
        progress_path = run.path / "progress_since_last.md"
        if not progress_path.is_file():
            missing.append(run.timestamp)
            continue
        text = progress_path.read_text(encoding="utf-8").strip()
        if not text:
            missing.append(run.timestamp)
            continue

        allowed = min(max_entry_chars, max(remaining, 0))
        if allowed <= 0:
            truncated = True
            continue
        rendered = text[:allowed].rstrip()
        if len(rendered) < len(text):
            truncated = True
        entries.append(
            ProgressEntry(
                timestamp=run.timestamp,
                text=rendered,
                source_path=progress_path,
            )
        )
        remaining -= len(rendered)

    return ProgressWindow(
        requested_last=requested_last,
        requested_since=requested_since,
        selected_runs=sorted(selected_runs, key=lambda item: item.timestamp),
        progress_entries=entries,
        missing_progress_runs=missing,
        unparseable_runs=list(unparseable_runs or []),
        truncated=truncated,
    )


def render_progress_window(window: ProgressWindow) -> str:
    if not window.progress_entries:
        return "(no usable selected progress summaries)"
    return "\n\n".join(
        f"--- BEGIN progress_since_last.md for run {entry.timestamp} ---\n"
        f"{entry.text}\n"
        f"--- END progress_since_last.md for run {entry.timestamp} ---"
        for entry in window.progress_entries
    )
