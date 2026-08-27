from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any, Callable

from freshness import (
    FreshnessReason,
    FreshnessResult,
    check_checkpoint_freshness,
    load_checkpoint_git_context,
)
from project_layout import CheckpointLayout, resolve_checkpoint_layout
from schemas import ProjectState

BRIEF_SCHEMA_VERSION = 1
DEFAULT_LATEST_LABEL = ".project_memory/latest"
STATUS_NOTE_PATH = "PROJECT_STATUS.md"
REQUIRED_FILENAMES = (
    "project_state.json",
    "checkpoint_summary.md",
    "git_context.json",
)
METADATA_TIMESTAMP_CANDIDATES = (
    ("run_metadata.json", "run_metadata"),
    ("checkpoint_metadata.json", "checkpoint_metadata"),
)
METADATA_TIMESTAMP_FIELDS = ("created_at", "checkpoint_created_at", "timestamp")


@dataclass(frozen=True)
class CheckpointHealth:
    status: str
    latest_path: str = DEFAULT_LATEST_LABEL
    required_files: list[str] = field(default_factory=list)
    missing_files: list[str] = field(default_factory=list)
    invalid_files: list[str] = field(default_factory=list)
    created_at: str | None = None
    timestamp_source: str | None = None


@dataclass(frozen=True)
class StatusNoteHealth:
    path: str = STATUS_NOTE_PATH
    exists: bool = False
    readable: bool = False
    modified_at: str | None = None
    modified_after_checkpoint: bool | None = None


@dataclass(frozen=True)
class BriefRecommendation:
    code: str
    message: str
    commands: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class BriefResult:
    schema_version: int
    checked_at: str
    checkpoint: CheckpointHealth
    freshness: FreshnessResult
    status_note: StatusNoteHealth
    recommendation: BriefRecommendation

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


FreshnessChecker = Callable[..., FreshnessResult]


def _utc_now() -> str:
    return _format_utc(datetime.now(timezone.utc))


def _format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _latest_file_label(latest_label: str, filename: str) -> str:
    return f"{latest_label}/{filename}"


def _read_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("structured checkpoint artifact must be an object")
    return value


def _metadata_timestamp(latest_dir: Path) -> tuple[str | None, str | None]:
    for filename, source in METADATA_TIMESTAMP_CANDIDATES:
        path = latest_dir / filename
        if not path.is_file():
            continue
        try:
            metadata = _read_json_object(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            continue
        for field_name in METADATA_TIMESTAMP_FIELDS:
            parsed = _parse_timestamp(metadata.get(field_name))
            if parsed is not None:
                return _format_utc(parsed), source
    return None, None


def _structured_timestamp(latest_dir: Path) -> tuple[str | None, str | None]:
    try:
        context = _read_json_object(latest_dir / "git_context.json")
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return None, None
    parsed = _parse_timestamp(context.get("collected_at"))
    if parsed is None:
        return None, None
    return _format_utc(parsed), "git_context.collected_at"


def _filesystem_timestamp(latest_dir: Path) -> tuple[str | None, str | None]:
    candidates = [latest_dir / filename for filename in REQUIRED_FILENAMES]
    candidates.append(latest_dir)
    mtimes = []
    for path in candidates:
        try:
            mtimes.append(path.stat().st_mtime)
        except OSError:
            continue
    if not mtimes:
        return None, None
    return _format_utc(datetime.fromtimestamp(max(mtimes), timezone.utc)), "filesystem_fallback"


def _checkpoint_timestamp(latest_dir: Path) -> tuple[str | None, str | None]:
    for resolver in (_metadata_timestamp, _structured_timestamp, _filesystem_timestamp):
        created_at, source = resolver(latest_dir)
        if created_at is not None:
            return created_at, source
    return None, None


def _inspect_checkpoint_layout(layout: CheckpointLayout) -> CheckpointHealth:
    project_dir = layout.project_dir
    latest_dir = layout.latest_dir
    latest_label = layout.latest_label()
    required_files = sorted(
        _latest_file_label(latest_label, name) for name in REQUIRED_FILENAMES
    )

    def label(filename: str) -> str:
        return _latest_file_label(latest_label, filename)

    if not latest_dir.is_dir():
        return CheckpointHealth(
            status="missing",
            latest_path=latest_label,
            required_files=required_files,
            missing_files=list(required_files),
        )

    missing_files = sorted(
        label(name)
        for name in REQUIRED_FILENAMES
        if not (latest_dir / name).is_file()
    )
    invalid_files: list[str] = []
    if label("project_state.json") not in missing_files:
        state_path = latest_dir / "project_state.json"
        try:
            ProjectState.model_validate_json(state_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            invalid_files.append(label("project_state.json"))

    if label("checkpoint_summary.md") not in missing_files:
        summary_path = latest_dir / "checkpoint_summary.md"
        try:
            with summary_path.open("rb") as source:
                source.read(1)
        except OSError:
            invalid_files.append(label("checkpoint_summary.md"))

    if label("git_context.json") not in missing_files:
        git_path = latest_dir / "git_context.json"
        try:
            load_checkpoint_git_context(git_path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            invalid_files.append(label("git_context.json"))

    created_at, timestamp_source = _checkpoint_timestamp(latest_dir)
    if missing_files:
        status = "incomplete"
    elif invalid_files:
        status = "invalid"
    else:
        status = "available"
    return CheckpointHealth(
        status=status,
        latest_path=latest_label,
        required_files=required_files,
        missing_files=missing_files,
        invalid_files=sorted(set(invalid_files)),
        created_at=created_at,
        timestamp_source=timestamp_source,
    )


def inspect_checkpoint(
    project_dir: Path,
    *,
    project_name: str | None = None,
    base_output_dir: Path | None = None,
    latest_dir: Path | None = None,
) -> CheckpointHealth:
    project_dir = project_dir.resolve()
    layout = resolve_checkpoint_layout(
        project_dir,
        project_name=project_name,
        base_output_dir=base_output_dir,
        latest_dir=latest_dir,
    )
    return _inspect_checkpoint_layout(layout)


def inspect_status_note(
    project_dir: Path,
    checkpoint_created_at: str | None,
) -> StatusNoteHealth:
    project_dir = project_dir.resolve()
    path = project_dir / STATUS_NOTE_PATH
    if not path.is_file():
        return StatusNoteHealth()

    readable = True
    try:
        with path.open("rb") as source:
            source.read(1)
    except OSError:
        readable = False

    try:
        modified = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
        modified_at = _format_utc(modified)
    except OSError:
        modified = None
        modified_at = None
    checkpoint_time = _parse_timestamp(checkpoint_created_at)
    modified_after = (
        modified > checkpoint_time
        if modified is not None and checkpoint_time is not None
        else None
    )
    return StatusNoteHealth(
        exists=True,
        readable=readable,
        modified_at=modified_at,
        modified_after_checkpoint=modified_after,
    )


def build_recommendation(
    checkpoint: CheckpointHealth,
    freshness: FreshnessResult,
    status_note: StatusNoteHealth,
) -> BriefRecommendation:
    if checkpoint.status == "missing":
        return BriefRecommendation(
            code="create_initial_checkpoint",
            message="Create the initial checkpoint.",
            commands=["pma checkpoint --project-dir ."],
        )
    if checkpoint.status in {"incomplete", "invalid"}:
        return BriefRecommendation(
            code="rebuild_checkpoint",
            message="The latest checkpoint artifacts are incomplete or malformed. Rebuild the checkpoint.",
            commands=["pma checkpoint --project-dir ."],
        )
    if freshness.status == "stale" and status_note.modified_after_checkpoint is True:
        return BriefRecommendation(
            code="run_checkpoint",
            message="PROJECT_STATUS.md has been updated since the latest checkpoint. Create a new checkpoint.",
            commands=["pma checkpoint --project-dir ."],
        )
    if freshness.status == "stale" and not status_note.exists:
        return BriefRecommendation(
            code="create_status_note_then_checkpoint",
            message="Create PROJECT_STATUS.md for recent work, then create a new checkpoint.",
            commands=[
                "pma status-note --project-dir . --from-latest --write",
                "pma checkpoint --project-dir .",
            ],
        )
    if freshness.status == "stale":
        return BriefRecommendation(
            code="update_status_note_then_checkpoint",
            message="Review recent changes, update PROJECT_STATUS.md, and create a new checkpoint.",
            commands=["pma checkpoint --project-dir ."],
        )
    if freshness.status == "unknown":
        return BriefRecommendation(
            code="review_checkpoint_freshness",
            message=(
                "PMA cannot reliably verify whether the latest checkpoint is current. "
                "Review the repository state and create a new checkpoint if meaningful changes occurred."
            ),
            commands=[],
        )
    return BriefRecommendation(
        code="no_checkpoint_update_needed",
        message="No checkpoint update is needed.",
        commands=[],
    )


def _unavailable_freshness(status: str, checked_at: str, code: str, message: str) -> FreshnessResult:
    return FreshnessResult(
        status=status,
        checked_at=checked_at,
        checkpoint_available=status != "no_checkpoint",
        reasons=[FreshnessReason(code=code, message=message)],
    )


def build_brief(
    project_dir: Path,
    *,
    checked_at: str | None = None,
    freshness_checker: FreshnessChecker = check_checkpoint_freshness,
    project_name: str | None = None,
    base_output_dir: Path | None = None,
    latest_dir: Path | None = None,
) -> BriefResult:
    project_dir = project_dir.resolve()
    timestamp = checked_at or _utc_now()
    layout = resolve_checkpoint_layout(
        project_dir,
        project_name=project_name,
        base_output_dir=base_output_dir,
        latest_dir=latest_dir,
    )
    checkpoint_health = _inspect_checkpoint_layout(layout)
    if checkpoint_health.status == "missing":
        freshness = _unavailable_freshness(
            "no_checkpoint",
            timestamp,
            "latest_checkpoint_missing",
            "No usable latest checkpoint was found.",
        )
    elif checkpoint_health.status in {"incomplete", "invalid"}:
        freshness = _unavailable_freshness(
            "unknown",
            timestamp,
            "checkpoint_health_unavailable",
            "Freshness was not checked because the latest checkpoint is incomplete or invalid.",
        )
    else:
        freshness = freshness_checker(
            project_dir,
            checked_at=timestamp,
            latest_dir=layout.latest_dir,
        )
    status_note = inspect_status_note(project_dir, checkpoint_health.created_at)
    recommendation = build_recommendation(checkpoint_health, freshness, status_note)
    if layout.mode != "default" and recommendation.commands:
        recommendation = replace(recommendation, commands=[])
    return BriefResult(
        schema_version=BRIEF_SCHEMA_VERSION,
        checked_at=timestamp,
        checkpoint=checkpoint_health,
        freshness=freshness,
        status_note=status_note,
        recommendation=recommendation,
    )


def render_brief_text(result: BriefResult, *, reason_limit: int = 5) -> str:
    lines = [
        "# PMA Checkpoint Brief",
        "",
        f"Checkpoint: {result.checkpoint.status}",
        f"Freshness: {result.freshness.status}",
    ]
    if result.checkpoint.created_at:
        lines.append(f"Latest checkpoint: {result.checkpoint.created_at}")
    lines.append(f"Status note: {'present' if result.status_note.exists else 'missing'}")
    if result.status_note.modified_after_checkpoint is not None:
        value = "yes" if result.status_note.modified_after_checkpoint else "no"
        lines.append(f"Status note updated after checkpoint: {value}")

    if result.checkpoint.status == "incomplete" and result.checkpoint.missing_files:
        lines.extend(["", "Missing files:"])
        lines.extend(f"- `{path}`" for path in result.checkpoint.missing_files)
    if result.checkpoint.invalid_files:
        lines.extend(["", "Invalid files:"])
        lines.extend(f"- `{path}`" for path in result.checkpoint.invalid_files)
    if result.freshness.status in {"stale", "unknown"} and result.freshness.reasons:
        reasons = result.freshness.reasons[:reason_limit]
        lines.extend(["", "Reasons:"])
        lines.extend(f"- {reason.message}" for reason in reasons)
        remaining = len(result.freshness.reasons) - len(reasons)
        if remaining:
            lines.append(f"- + {remaining} more reasons")

    lines.extend(["", "Recommended action:", result.recommendation.message])
    if result.recommendation.commands:
        lines.append("")
        lines.extend(result.recommendation.commands)
    if (
        result.recommendation.code == "no_checkpoint_update_needed"
        and result.checkpoint.latest_path == DEFAULT_LATEST_LABEL
    ):
        lines.extend(
            [
                "",
                "For a project recap, run:",
                "pma memo --type self --project-dir .",
            ]
        )
    return "\n".join(lines) + "\n"
