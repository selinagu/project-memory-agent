from dataclasses import dataclass
from pathlib import Path

from artifacts import ParsedArtifactBundle
from schemas import ProjectState


@dataclass(frozen=True)
class LoadedCheckpoint:
    state: ProjectState | None
    parsed_artifacts: ParsedArtifactBundle | None


def load_checkpoint(checkpoint_dir: Path) -> LoadedCheckpoint:
    """Load available structured data from a checkpoint directory.

    Missing files are returned as None. Invalid JSON or schema data raises
    the underlying parsing or validation error.
    """
    state_path = checkpoint_dir / "project_state.json"
    artifacts_path = checkpoint_dir / "parsed_artifacts.json"

    state = (
        ProjectState.model_validate_json(
            state_path.read_text(encoding="utf-8")
        )
        if state_path.exists()
        else None
    )

    parsed_artifacts = (
        ParsedArtifactBundle.model_validate_json(
            artifacts_path.read_text(encoding="utf-8")
        )
        if artifacts_path.exists()
        else None
    )

    return LoadedCheckpoint(
        state=state,
        parsed_artifacts=parsed_artifacts,
    )