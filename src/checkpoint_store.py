from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4


RUN_METADATA_SCHEMA_VERSION = 1
REQUIRED_CHECKPOINT_FILES = (
    "artifacts_index.json",
    "artifact_manifest.json",
    "parsed_artifacts.json",
    "combined_notes.md",
    "git_context.json",
    "git_context.md",
    "project_state.json",
    "project_state_card.md",
    "checkpoint_summary.md",
    "progress_since_last.md",
    "run_metadata.json",
)
JSON_CHECKPOINT_FILES = (
    "artifacts_index.json",
    "artifact_manifest.json",
    "parsed_artifacts.json",
    "git_context.json",
    "project_state.json",
    "run_metadata.json",
)


class CheckpointStoreError(RuntimeError):
    """Raised when a checkpoint cannot be validated or safely published."""


def generate_run_id(
    *,
    now_factory: Callable[[], datetime] | None = None,
    suffix_factory: Callable[[], str] | None = None,
) -> str:
    now = (now_factory or (lambda: datetime.now(timezone.utc)))()
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    suffix = (suffix_factory or (lambda: uuid4().hex[:8]))()
    if not suffix or any(character not in "abcdefghijklmnopqrstuvwxyz0123456789" for character in suffix):
        raise ValueError("run ID suffix must contain only lowercase ASCII letters and digits")
    return f"{now.strftime('%Y-%m-%d_%H%M%S_%f')}_{suffix}"


def new_run_metadata(
    *,
    run_id: str,
    status: str,
    model: str,
    stage: str,
    project_path: str = ".",
    checkpoint_path: str,
    error_code: str | None = None,
    artifact_count: int = 0,
    source_bytes: int = 0,
    combined_notes_chars: int = 0,
    created_at: str | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": RUN_METADATA_SCHEMA_VERSION,
        "run_id": run_id,
        "status": status,
        "stage": stage,
        "error_code": error_code,
        "model": model,
        "project_path": project_path,
        "checkpoint_path": checkpoint_path,
        "artifact_count": artifact_count,
        "source_bytes": source_bytes,
        "combined_notes_chars": combined_notes_chars,
        "created_at": created_at,
    }


def write_json_atomically(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{uuid4().hex}")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def write_run_metadata(run_dir: Path, metadata: dict[str, Any]) -> None:
    write_json_atomically(run_dir / "run_metadata.json", metadata)


def validate_successful_run(run_dir: Path) -> None:
    missing = [name for name in REQUIRED_CHECKPOINT_FILES if not (run_dir / name).is_file()]
    if missing:
        raise CheckpointStoreError(
            "checkpoint is incomplete; missing required files: " + ", ".join(missing)
        )
    for name in JSON_CHECKPOINT_FILES:
        try:
            json.loads((run_dir / name).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CheckpointStoreError(f"checkpoint contains invalid {name}") from exc
    metadata = json.loads((run_dir / "run_metadata.json").read_text(encoding="utf-8"))
    if metadata.get("status") != "succeeded":
        raise CheckpointStoreError("checkpoint run metadata is not marked succeeded")


def _remove_directory_best_effort(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path, ignore_errors=True)


def replace_directory_transactionally(
    source_dir: Path,
    destination_dir: Path,
    *,
    copy_source: bool,
    validator: Callable[[Path], None] | None = None,
) -> None:
    """Replace a directory with rollback if the final rename fails.

    The old destination remains recoverable until the prepared replacement has
    been validated and renamed into place. This is failure-safe, but it does not
    claim strict cross-platform atomic visibility for directory trees.
    """
    destination_dir.parent.mkdir(parents=True, exist_ok=True)
    token = uuid4().hex
    prepared = destination_dir.with_name(f".{destination_dir.name}.prepared-{token}")
    backup = destination_dir.with_name(f".{destination_dir.name}.backup-{token}")
    had_destination = destination_dir.exists()

    try:
        if copy_source:
            shutil.copytree(source_dir, prepared)
        else:
            os.replace(source_dir, prepared)
        if validator is not None:
            validator(prepared)
        if had_destination:
            os.replace(destination_dir, backup)
        try:
            os.replace(prepared, destination_dir)
        except BaseException:
            if had_destination and backup.exists() and not destination_dir.exists():
                os.replace(backup, destination_dir)
            raise
        _remove_directory_best_effort(backup)
    finally:
        _remove_directory_best_effort(prepared)


def publish_latest(run_dir: Path, latest_dir: Path) -> None:
    replace_directory_transactionally(
        run_dir,
        latest_dir,
        copy_source=True,
        validator=validate_successful_run,
    )


def archive_failed_run(
    run_dir: Path,
    failed_runs_dir: Path,
    metadata: dict[str, Any],
) -> Path:
    failed_runs_dir.mkdir(parents=True, exist_ok=True)
    write_run_metadata(run_dir, metadata)
    destination = failed_runs_dir / metadata["run_id"]
    if destination.exists():
        destination = failed_runs_dir / f"{metadata['run_id']}-{uuid4().hex[:8]}"
    os.replace(run_dir, destination)
    return destination
