import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from artifacts import ArtifactIndex, ArtifactRecord
from scanner_config import (
    ScannerConfig,
    ScannerConfigError,
    load_scanner_config,
    matches_any,
    normalize_relative_path,
)
from project_layout import CheckpointLayoutError, generated_output_prefixes, resolve_checkpoint_layout
from python_source import PYTHON_MAX_BYTES, PythonSourceResult, extract_python_structure


SUPPORTED_EXTENSIONS = {
    ".md": "markdown",
    ".txt": "text",
    ".log": "log",
    ".json": "json",
    ".csv": "csv",
    ".py": "python",
}


DEFAULT_IGNORE_DIRS = {
    ".git",
    ".project_memory",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "node_modules",
}


SENSITIVE_IGNORE_FILES = {
    ".env",
}


def detect_artifact_type(path: Path) -> str:
    return SUPPORTED_EXTENSIONS.get(path.suffix.lower(), "unknown")


def should_ignore(path: Path) -> bool:
    if path.name in SENSITIVE_IGNORE_FILES:
        return True

    return any(
        part in DEFAULT_IGNORE_DIRS or part.endswith(".egg-info")
        for part in path.parts
    )


def read_preview(path: Path, max_chars: int = 500) -> str | None:
    artifact_type = detect_artifact_type(path)

    if artifact_type == "unknown":
        return None

    if artifact_type == "python":
        result = _read_python_structure(path)
        return result.content if result is not None else None

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    text = text.strip()
    if not text:
        return ""

    return text[:max_chars]


def _read_python_structure(path: Path) -> PythonSourceResult | None:
    try:
        with path.open("rb") as source:
            raw = source.read(PYTHON_MAX_BYTES + 1)
    except OSError:
        return None
    return extract_python_structure(raw)


def _preview_and_status(path: Path, artifact_type: str) -> tuple[str | None, str]:
    if artifact_type == "python":
        result = _read_python_structure(path)
        if result is None:
            return None, "failed"
        return result.content, result.status
    preview = read_preview(path)
    if preview is None:
        return None, "failed"
    return preview, "parsed"


def scan_project(
    project_dir: Path,
    scanner_config: ScannerConfig | None = None,
    *,
    checkpoint_root: Path | None = None,
) -> ArtifactIndex:
    project_dir = project_dir.resolve()
    ignored_generated_prefixes = (
        generated_output_prefixes(project_dir, checkpoint_root)
        if checkpoint_root is not None
        else ()
    )

    if scanner_config is None:
        scanner_config = load_scanner_config(project_dir)

    records: list[ArtifactRecord] = []

    for path in sorted(project_dir.rglob("*")):
        relative_path = path.relative_to(project_dir)

        if should_ignore(relative_path):
            continue

        is_symlink = path.is_symlink()
        if not is_symlink and not path.is_file():
            continue

        relative_posix = relative_path.as_posix()
        if any(
            relative_posix == prefix or relative_posix.startswith(f"{prefix}/")
            for prefix in ignored_generated_prefixes
        ):
            continue

        artifact_type = detect_artifact_type(path)
        if artifact_type == "unknown":
            continue
        if artifact_type == "python" and not scanner_config.include_python:
            continue

        match_path = normalize_relative_path(relative_path)
        if (
            scanner_config.include_patterns
            and not matches_any(match_path, scanner_config.include_patterns)
        ):
            continue
        if matches_any(match_path, scanner_config.exclude_patterns):
            continue

        stat = path.lstat() if is_symlink else path.stat()
        modified_time = datetime.fromtimestamp(
            stat.st_mtime,
            tz=timezone.utc,
        ).isoformat()

        if is_symlink:
            preview = "[Artifact unavailable: symbolic_link.]"
            parser_status = "failed"
        else:
            preview, parser_status = _preview_and_status(path, artifact_type)

        record = ArtifactRecord(
            path=match_path,
            artifact_type=artifact_type,
            size_bytes=stat.st_size,
            modified_time=modified_time,
            content_preview=preview,
            parser_status=parser_status,
        )
        records.append(record)

    return ArtifactIndex(
        project_dir=str(project_dir),
        artifacts=records,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    project_dir = Path(args.project_dir)
    output_path = Path(args.output)

    try:
        layout = resolve_checkpoint_layout(project_dir)
        index = scan_project(
            project_dir,
            checkpoint_root=layout.checkpoint_root,
        )
    except (ScannerConfigError, CheckpointLayoutError) as exc:
        parser.error(str(exc))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(index.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("Project scan completed.")
    print(f"Project dir: {project_dir}")
    print(f"Artifacts found: {len(index.artifacts)}")
    print(f"Output: {output_path}")


if __name__ == "__main__":
    main()
