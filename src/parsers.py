import csv
import hashlib
import io
import json
import math
import re
from pathlib import Path
from typing import Any

from artifacts import (
    ArtifactIndex,
    ArtifactRecord,
    ParsedArtifact,
    ParsedArtifactBundle,
)
from python_source import PYTHON_MAX_BYTES, extract_python_structure
from scanner_config import (
    DEFAULT_MAX_NON_PYTHON_FILE_BYTES,
    ResourceBudgetError,
    ScannerConfig,
)


_MARKDOWN_HEADING_RE = re.compile(
    r"^[ \t]{0,3}#{1,6}(?:[ \t]+|$)"
)

LOG_HEAD_LINES = 20
LOG_TAIL_LINES = 40

LOG_DIAGNOSTIC_TERMS = (
    "error",
    "warning",
    "exception",
    "traceback",
    "failed",
    "fatal",
)


def _base_metadata(artifact: ArtifactRecord, content: str) -> dict[str, Any]:
    return {
        "size_bytes": artifact.size_bytes,
        "modified_time": artifact.modified_time,
        "line_count": len(content.splitlines()),
        "character_count": len(content),
    }


def _parse_plain_text(content: str) -> tuple[str, dict[str, Any], list[str]]:
    return content.strip(), {}, []


def _parse_markdown(content: str) -> tuple[str, dict[str, Any], list[str]]:
    stripped = content.strip()
    heading_count = sum(
        1
        for line in stripped.splitlines()
        if _MARKDOWN_HEADING_RE.match(line)
    )
    return stripped, {"heading_count": heading_count}, []


def _parse_log(
    content: str,
) -> tuple[str, dict[str, Any], list[str]]:
    lines = content.splitlines()

    head_lines = lines[:LOG_HEAD_LINES]
    tail_start = max(LOG_HEAD_LINES, len(lines) - LOG_TAIL_LINES)
    tail_lines = lines[tail_start:]

    diagnostic_lines: list[str] = []
    seen_lines: set[str] = set(head_lines + tail_lines)

    for line in lines:
        lowered = line.lower()
        if (
            any(term in lowered for term in LOG_DIAGNOSTIC_TERMS)
            and line not in seen_lines
        ):
            diagnostic_lines.append(line)
            seen_lines.add(line)

    kept_line_count = (
        len(head_lines)
        + len(tail_lines)
        + len(diagnostic_lines)
    )
    truncated = kept_line_count < len(lines)

    sections = [
        "# Log Summary",
        f"Total lines: {len(lines)}",
        "",
        f"## First {LOG_HEAD_LINES} Lines",
        "\n".join(head_lines) if head_lines else "[Log is empty.]",
        "",
        "## Diagnostic Lines",
        (
            "\n".join(diagnostic_lines)
            if diagnostic_lines
            else "[No diagnostic lines found.]"
        ),
        "",
        f"## Last {LOG_TAIL_LINES} Lines",
        (
            "\n".join(tail_lines)
            if tail_lines
            else "[No additional tail lines.]"
        ),
    ]

    metadata = {
        "line_count": len(lines),
        "head_line_count": len(head_lines),
        "tail_line_count": len(tail_lines),
        "diagnostic_line_count": len(diagnostic_lines),
        "truncated": truncated,
        "summary_strategy": "head_diagnostics_tail",
    }

    warnings = (
        ["Log was summarized using head, diagnostic, and tail lines."]
        if truncated
        else []
    )

    return "\n".join(sections), metadata, warnings


def _parse_csv(content: str) -> tuple[str, dict[str, Any], list[str]]:
    warnings: list[str] = []

    try:
        rows = list(csv.reader(io.StringIO(content), strict=True))
    except csv.Error as e:
        return content.strip(), {
            "row_count": 0,
            "column_count": 0,
            "columns": [],
            "preview_strategy": "full",
            "truncated": False,
        }, [f"Could not parse CSV: {e}"]

    if not rows:
        return "", {
            "row_count": 0,
            "column_count": 0,
            "columns": [],
            "preview_strategy": "full",
            "truncated": False,
        }, ["CSV artifact is empty."]

    column_count = max(len(row) for row in rows)
    if column_count == 0:
        return "", {
            "row_count": max(len(rows) - 1, 0),
            "column_count": 0,
            "columns": [],
            "preview_strategy": "full",
            "truncated": False,
        }, ["CSV artifact has no columns."]

    if any(len(row) != column_count for row in rows):
        warnings.append("CSV rows have inconsistent column counts.")

    normalized_rows = [
        row + [""] * (column_count - len(row))
        for row in rows
    ]
    header = normalized_rows[0]
    body = normalized_rows[1:]
    truncated = len(body) > 50
    preview_strategy = "head_tail_summary" if truncated else "full"

    def escape_cell(value: str) -> str:
        return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")

    def render_table(data_rows: list[list[str]]) -> list[str]:
        table_lines = [
            "| " + " | ".join(escape_cell(value) for value in header) + " |",
            "| " + " | ".join("---" for _ in range(column_count)) + " |",
        ]
        table_lines.extend(
            "| " + " | ".join(escape_cell(value) for value in row) + " |"
            for row in data_rows
        )
        return table_lines

    if truncated:
        table_lines = [
            "## First 10 Rows",
            *render_table(body[:10]),
            "",
            "## Last 10 Rows",
            *render_table(body[-10:]),
        ]
    else:
        table_lines = render_table(body)

    numeric_ranges: list[str] = []

    for column_index in range(column_count):
        numeric_values: list[float] = []

        for row in body:
            value = row[column_index].strip()
            if not value:
                continue

            try:
                numeric_value = float(value)
            except ValueError:
                continue

            if math.isfinite(numeric_value):
                numeric_values.append(numeric_value)

        if numeric_values:
            column_name = (
                header[column_index]
                or f"Column {column_index + 1}"
            )
            numeric_ranges.append(
                f"- {column_name}: "
                f"numeric_count={len(numeric_values)}, "
                f"min={min(numeric_values):.6g}, "
                f"max={max(numeric_values):.6g}"
            )

    summary_lines = [
        "",
        "## Basic Numeric Range Summary",
        *(
            numeric_ranges
            if numeric_ranges
            else ["[No numeric columns found.]"]
        ),
    ]

    if truncated:
        warnings.append(
            "Large CSV artifact summarized with head/tail rows and basic numeric ranges."
        )

    metadata = {
        "row_count": len(body),
        "column_count": column_count,
        "columns": header,
        "preview_strategy": preview_strategy,
        "truncated": truncated,
    }
    return "\n".join(table_lines + summary_lines), metadata, warnings


def _parse_json(content: str) -> tuple[str, dict[str, Any], list[str]]:
    try:
        value = json.loads(content)
    except json.JSONDecodeError as e:
        return content.strip(), {}, [
            f"Could not parse JSON at line {e.lineno}, column {e.colno}: {e.msg}"
        ]

    metadata: dict[str, Any] = {"root_type": type(value).__name__}
    if isinstance(value, dict):
        metadata["key_count"] = len(value)
        metadata["keys"] = list(value.keys())
    elif isinstance(value, list):
        metadata["item_count"] = len(value)

    normalized = json.dumps(
        value,
        indent=2,
        ensure_ascii=False,
        sort_keys=True,
    )
    return normalized, metadata, []


def parse_artifact(
    project_dir: Path,
    artifact: ArtifactRecord,
    *,
    max_non_python_file_bytes: int = DEFAULT_MAX_NON_PYTHON_FILE_BYTES,
) -> ParsedArtifact:
    path = project_dir / artifact.path
    warnings: list[str] = []

    if artifact.artifact_type == "python":
        try:
            if path.is_symlink():
                raise OSError("symbolic links are not read")
            with path.open("rb") as source:
                raw_content = source.read(PYTHON_MAX_BYTES + 1)
        except OSError as exc:
            return ParsedArtifact(
                path=artifact.path,
                artifact_type=artifact.artifact_type,
                content_hash="",
                content_for_llm="[Python source unavailable: read_error.]",
                metadata={
                    "size_bytes": artifact.size_bytes,
                    "modified_time": artifact.modified_time,
                    "summary_strategy": "python_ast_structure",
                    "failure_code": "read_error",
                },
                warnings=[f"Python source could not be read safely: {type(exc).__name__}."],
            )

        result = extract_python_structure(raw_content)
        content_hash = (
            hashlib.sha256(raw_content).hexdigest()
            if len(raw_content) <= PYTHON_MAX_BYTES
            else ""
        )
        metadata = {
            "size_bytes": artifact.size_bytes,
            "modified_time": artifact.modified_time,
            **result.metadata,
        }
        return ParsedArtifact(
            path=artifact.path,
            artifact_type=artifact.artifact_type,
            content_hash=content_hash,
            content_for_llm=result.content,
            metadata=metadata,
            warnings=list(result.warnings),
        )

    try:
        with path.open("rb") as source:
            raw_content = source.read(max_non_python_file_bytes + 1)
        if len(raw_content) > max_non_python_file_bytes:
            raise ResourceBudgetError(
                f"artifact {artifact.path!r} exceeds "
                "[scanner].max_non_python_file_bytes "
                f"({max_non_python_file_bytes})"
            )
        content = raw_content.decode("utf-8", errors="replace")
    except ResourceBudgetError:
        raise
    except Exception as e:
        return ParsedArtifact(
            path=artifact.path,
            artifact_type=artifact.artifact_type,
            content_hash="",
            content_for_llm=f"[Could not read artifact: {e}]",
            metadata={
                "size_bytes": artifact.size_bytes,
                "modified_time": artifact.modified_time,
            },
            warnings=[f"Could not read artifact: {e}"],
        )

    content_hash = hashlib.sha256(raw_content).hexdigest()

    if "\ufffd" in content:
        warnings.append("Invalid UTF-8 bytes were replaced while reading the artifact.")

    parsers = {
        "markdown": _parse_markdown,
        "text": _parse_plain_text,
        "log": _parse_log,
        "csv": _parse_csv,
        "json": _parse_json,
    }
    parser = parsers.get(artifact.artifact_type)

    if parser is None:
        parsed_content = content.strip()
        parser_metadata: dict[str, Any] = {}
        parser_warnings = [
            f"No parser is registered for artifact type '{artifact.artifact_type}'."
        ]
    else:
        parsed_content, parser_metadata, parser_warnings = parser(content)

    metadata = _base_metadata(artifact, content)
    metadata.update(parser_metadata)
    warnings.extend(parser_warnings)

    if not content.strip():
        warnings.append("Artifact is empty.")

    return ParsedArtifact(
        path=artifact.path,
        artifact_type=artifact.artifact_type,
        content_hash=content_hash,
        content_for_llm=parsed_content,
        metadata=metadata,
        warnings=warnings,
    )


def parse_artifacts(
    project_dir: Path,
    artifact_index: ArtifactIndex,
    scanner_config: ScannerConfig | None = None,
) -> ParsedArtifactBundle:
    scanner_config = scanner_config or ScannerConfig()
    parsed_artifacts = [
        parse_artifact(
            project_dir,
            artifact,
            max_non_python_file_bytes=scanner_config.max_non_python_file_bytes,
        )
        for artifact in artifact_index.artifacts
        if artifact.parser_status == "parsed"
    ]

    return ParsedArtifactBundle(
        project_dir=".",
        artifacts=parsed_artifacts,
    )
