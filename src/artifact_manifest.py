from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import Any

from artifacts import ArtifactIndex
from python_source import PYTHON_MAX_BYTES
from scanner_config import ResourceBudgetError, ScannerConfig


ARTIFACT_MANIFEST_SCHEMA_VERSION = 1


def scanner_config_fingerprint(config: ScannerConfig) -> str:
    payload = {
        "include": list(config.include_patterns),
        "exclude": list(config.exclude_patterns),
        "include_python": config.include_python,
        "max_artifacts": config.max_artifacts,
        "max_non_python_file_bytes": config.max_non_python_file_bytes,
        "max_total_source_bytes": config.max_total_source_bytes,
        "max_combined_notes_chars": config.max_combined_notes_chars,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_artifact_manifest(
    project_dir: Path,
    artifact_index: ArtifactIndex,
    config: ScannerConfig,
) -> dict[str, Any]:
    project_dir = project_dir.resolve()
    entries: list[dict[str, Any]] = []
    for artifact in artifact_index.artifacts:
        path = project_dir / artifact.path
        if path.is_symlink():
            entries.append(
                {
                    "path": artifact.path,
                    "artifact_type": artifact.artifact_type,
                    "size_bytes": artifact.size_bytes,
                    "sha256": None,
                    "status": "symbolic_link",
                }
            )
            continue
        limit = (
            PYTHON_MAX_BYTES
            if artifact.artifact_type == "python"
            else config.max_non_python_file_bytes
        )
        try:
            with path.open("rb") as source:
                content = source.read(limit + 1)
        except OSError:
            entries.append(
                {
                    "path": artifact.path,
                    "artifact_type": artifact.artifact_type,
                    "size_bytes": artifact.size_bytes,
                    "sha256": None,
                    "status": "read_error",
                }
            )
            continue
        if len(content) > limit:
            if artifact.artifact_type != "python":
                raise ResourceBudgetError(
                    f"artifact {artifact.path!r} exceeds "
                    "[scanner].max_non_python_file_bytes "
                    f"({config.max_non_python_file_bytes})"
                )
            entries.append(
                {
                    "path": artifact.path,
                    "artifact_type": artifact.artifact_type,
                    "size_bytes": artifact.size_bytes,
                    "sha256": None,
                    "status": "size_limit",
                }
            )
            continue
        entries.append(
            {
                "path": artifact.path,
                "artifact_type": artifact.artifact_type,
                "size_bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
                "status": "hashed",
            }
        )
    return {
        "schema_version": ARTIFACT_MANIFEST_SCHEMA_VERSION,
        "project_path": ".",
        "config_fingerprint": scanner_config_fingerprint(config),
        "artifacts": entries,
    }


def validate_artifact_manifest(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("artifact manifest must be an object")
    if value.get("schema_version") != ARTIFACT_MANIFEST_SCHEMA_VERSION:
        raise ValueError("artifact manifest schema is unsupported")
    if value.get("project_path") != ".":
        raise ValueError("artifact manifest project path must be logical")
    fingerprint = value.get("config_fingerprint")
    if (
        not isinstance(fingerprint, str)
        or len(fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in fingerprint)
    ):
        raise ValueError("artifact manifest config fingerprint is malformed")
    artifacts = value.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("artifact manifest artifacts must be a list")
    seen: set[str] = set()
    for entry in artifacts:
        if not isinstance(entry, dict):
            raise ValueError("artifact manifest entry must be an object")
        path = entry.get("path")
        pure = PurePosixPath(path) if isinstance(path, str) else None
        digest = entry.get("sha256")
        if (
            not isinstance(path, str)
            or path in seen
            or pure is None
            or pure.is_absolute()
            or ".." in pure.parts
            or "\\" in path
            or not isinstance(entry.get("artifact_type"), str)
            or type(entry.get("size_bytes")) is not int
            or entry["size_bytes"] < 0
            or entry.get("status") not in {
                "hashed",
                "symbolic_link",
                "read_error",
                "size_limit",
            }
        ):
            raise ValueError("artifact manifest entry is malformed")
        if entry["status"] == "hashed":
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(character not in "0123456789abcdef" for character in digest)
            ):
                raise ValueError("artifact manifest digest is malformed")
        elif digest is not None:
            raise ValueError("unavailable artifact manifest entry has a digest")
        seen.add(path)
    if [entry["path"] for entry in artifacts] != sorted(seen):
        raise ValueError("artifact manifest entries must be sorted")
    return value
