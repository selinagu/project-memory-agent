from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PurePath

DEFAULT_CHECKPOINT_DIRECTORY = ".project_memory"

class CheckpointLayoutError(ValueError):
    """Raised when checkpoint location arguments are contradictory or incomplete."""


@dataclass(frozen=True)
class CheckpointLayout:
    project_dir: Path
    checkpoint_root: Path
    latest_dir: Path
    runs_dir: Path
    mode: str

    @property
    def building_dir(self) -> Path:
        return self.checkpoint_root / ".building"

    @property
    def failed_runs_dir(self) -> Path:
        return self.checkpoint_root / "failed_runs"

    def latest_label(self) -> str:
        """Return a privacy-safe label for the resolved latest directory."""
        return logical_path(self.latest_dir, self.project_dir)


def _validate_project_name(project_name: str) -> None:
    value = PurePath(project_name)
    if not project_name.strip() or value.is_absolute() or ".." in value.parts:
        raise CheckpointLayoutError(
            "--project-name must be a non-empty relative path without '..'."
        )


def resolve_checkpoint_layout(
    project_dir: Path,
    *,
    project_name: str | None = None,
    base_output_dir: Path | None = None,
    latest_dir: Path | None = None,
) -> CheckpointLayout:
    """Resolve the one checkpoint layout shared by producers and consumers.

    Relative ``latest_dir`` values retain the existing status-note behavior and
    resolve below the tracked project. Relative ``base_output_dir`` values retain
    checkpoint CLI behavior and resolve from the process working directory.
    """
    project_dir = project_dir.expanduser().resolve()
    if latest_dir is not None:
        if project_name is not None or base_output_dir is not None:
            raise CheckpointLayoutError(
                "--latest-dir cannot be combined with --project-name or --base-output-dir."
            )
        requested = latest_dir.expanduser()
        resolved_latest = (
            requested.resolve()
            if requested.is_absolute()
            else (project_dir / requested).resolve()
        )
        checkpoint_root = resolved_latest.parent
        return CheckpointLayout(
            project_dir=project_dir,
            checkpoint_root=checkpoint_root,
            latest_dir=resolved_latest,
            runs_dir=checkpoint_root / "runs",
            mode="explicit_latest",
        )

    if (project_name is None) != (base_output_dir is None):
        raise CheckpointLayoutError(
            "--project-name and --base-output-dir must be provided together."
        )
    if project_name is not None and base_output_dir is not None:
        _validate_project_name(project_name)
        checkpoint_root = base_output_dir.expanduser().resolve() / project_name
        mode = "named_output"
    else:
        checkpoint_root = project_dir / DEFAULT_CHECKPOINT_DIRECTORY
        mode = "default"
    checkpoint_root = checkpoint_root.resolve()
    return CheckpointLayout(
        project_dir=project_dir,
        checkpoint_root=checkpoint_root,
        latest_dir=checkpoint_root / "latest",
        runs_dir=checkpoint_root / "runs",
        mode=mode,
    )


def logical_path(path: Path, project_dir: Path) -> str:
    """Return a project-relative POSIX path, or a privacy-safe external label."""
    try:
        relative = path.resolve().relative_to(project_dir.resolve())
    except ValueError:
        return "external"
    return relative.as_posix()


def generated_output_prefixes(project_dir: Path, checkpoint_root: Path) -> tuple[str, ...]:
    """Return project-relative generated paths that must be ignored."""
    project_dir = project_dir.resolve()
    checkpoint_root = checkpoint_root.resolve()
    try:
        relative = checkpoint_root.relative_to(project_dir)
    except ValueError:
        return ()
    if relative == Path("."):
        return (".building", "failed_runs", "latest", "runs")
    return (relative.as_posix(),)
