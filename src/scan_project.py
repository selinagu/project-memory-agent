import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from artifacts import ArtifactIndex, ArtifactRecord


SUPPORTED_EXTENSIONS = {
    ".md": "markdown",
    ".txt": "text",
    ".log": "log",
    ".json": "json",
    ".csv": "csv",
}


DEFAULT_IGNORE_DIRS = {
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "env",
    "node_modules",
    "outputs",
}


def detect_artifact_type(path: Path) -> str:
    return SUPPORTED_EXTENSIONS.get(path.suffix.lower(), "unknown")


def should_ignore(path: Path) -> bool:
    return any(part in DEFAULT_IGNORE_DIRS for part in path.parts)


def read_preview(path: Path, max_chars: int = 500) -> str | None:
    artifact_type = detect_artifact_type(path)

    if artifact_type == "unknown":
        return None

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None

    text = text.strip()
    if not text:
        return ""

    return text[:max_chars]


def scan_project(project_dir: Path) -> ArtifactIndex:
    project_dir = project_dir.resolve()

    records: list[ArtifactRecord] = []

    for path in sorted(project_dir.rglob("*")):
        if not path.is_file():
            continue

        relative_path = path.relative_to(project_dir)

        if should_ignore(relative_path):
            continue

        artifact_type = detect_artifact_type(path)
        if artifact_type == "unknown":
            continue

        stat = path.stat()
        modified_time = datetime.fromtimestamp(
            stat.st_mtime,
            tz=timezone.utc,
        ).isoformat()

        preview = read_preview(path)

        record = ArtifactRecord(
            path=str(relative_path),
            artifact_type=artifact_type,
            size_bytes=stat.st_size,
            modified_time=modified_time,
            content_preview=preview,
            parser_status="parsed" if preview is not None else "failed",
        )
        records.append(record)

    return ArtifactIndex(
        project_dir=str(project_dir),
        artifacts=records,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    project_dir = Path(args.project_dir)
    output_path = Path(args.output)

    index = scan_project(project_dir)

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
