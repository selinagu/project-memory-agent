from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path, PurePosixPath
import fnmatch

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - exercised on Python 3.10
    import tomli as tomllib


CONFIG_FILENAME = "pma.toml"
DEFAULT_MAX_ARTIFACTS = 500
DEFAULT_MAX_NON_PYTHON_FILE_BYTES = 1 * 1024 * 1024
DEFAULT_MAX_TOTAL_SOURCE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_COMBINED_NOTES_CHARS = 250_000

HARD_MAX_ARTIFACTS = 10_000
HARD_MAX_NON_PYTHON_FILE_BYTES = 10 * 1024 * 1024
HARD_MAX_TOTAL_SOURCE_BYTES = 100 * 1024 * 1024
HARD_MAX_COMBINED_NOTES_CHARS = 2_000_000


class ScannerConfigError(ValueError):
    """Raised when pma.toml has an invalid scanner configuration."""


class ResourceBudgetError(RuntimeError):
    """Raised when selected project input exceeds a configured safety budget."""


@dataclass(frozen=True)
class ScannerConfig:
    include_patterns: tuple[str, ...] = ()
    exclude_patterns: tuple[str, ...] = ()
    include_python: bool = False
    max_artifacts: int = DEFAULT_MAX_ARTIFACTS
    max_non_python_file_bytes: int = DEFAULT_MAX_NON_PYTHON_FILE_BYTES
    max_total_source_bytes: int = DEFAULT_MAX_TOTAL_SOURCE_BYTES
    max_combined_notes_chars: int = DEFAULT_MAX_COMBINED_NOTES_CHARS


def _validate_patterns(value: object, field: str, config_path: Path) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise ScannerConfigError(
            f"{config_path}: [scanner].{field} must be a list of strings."
        )
    for index, pattern in enumerate(value):
        if not isinstance(pattern, str):
            raise ScannerConfigError(
                f"{config_path}: [scanner].{field}[{index}] must be a string."
            )
    return tuple(value)


def _validate_positive_integer(
    value: object,
    field: str,
    config_path: Path,
    hard_ceiling: int,
) -> int:
    if type(value) is not int or value <= 0:
        raise ScannerConfigError(
            f"{config_path}: [scanner].{field} must be a positive integer."
        )
    if value > hard_ceiling:
        raise ScannerConfigError(
            f"{config_path}: [scanner].{field} exceeds the hard ceiling "
            f"of {hard_ceiling}."
        )
    return value


def load_scanner_config(project_dir: Path) -> ScannerConfig:
    config_path = project_dir.resolve() / CONFIG_FILENAME
    if not config_path.exists():
        return ScannerConfig()

    try:
        with config_path.open("rb") as config_file:
            document = tomllib.load(config_file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ScannerConfigError(f"{config_path}: invalid TOML: {exc}") from exc

    unknown_sections = set(document) - {"scanner"}
    if unknown_sections:
        section = sorted(unknown_sections)[0]
        raise ScannerConfigError(
            f"{config_path}: unknown top-level section or key {section!r}."
        )

    scanner = document.get("scanner", {})
    if not isinstance(scanner, dict):
        raise ScannerConfigError(f"{config_path}: [scanner] must be a table.")

    known_keys = {
        "include",
        "exclude",
        "include_python",
        "max_artifacts",
        "max_non_python_file_bytes",
        "max_total_source_bytes",
        "max_combined_notes_chars",
    }
    unknown_keys = set(scanner) - known_keys
    if unknown_keys:
        key = sorted(unknown_keys)[0]
        raise ScannerConfigError(
            f"{config_path}: unknown key [scanner].{key}."
        )

    include = _validate_patterns(scanner.get("include", []), "include", config_path)
    exclude = _validate_patterns(scanner.get("exclude", []), "exclude", config_path)
    include_python = scanner.get("include_python", False)
    if type(include_python) is not bool:
        raise ScannerConfigError(
            f"{config_path}: [scanner].include_python must be a boolean."
        )
    max_artifacts = _validate_positive_integer(
        scanner.get("max_artifacts", DEFAULT_MAX_ARTIFACTS),
        "max_artifacts",
        config_path,
        HARD_MAX_ARTIFACTS,
    )
    max_non_python_file_bytes = _validate_positive_integer(
        scanner.get(
            "max_non_python_file_bytes",
            DEFAULT_MAX_NON_PYTHON_FILE_BYTES,
        ),
        "max_non_python_file_bytes",
        config_path,
        HARD_MAX_NON_PYTHON_FILE_BYTES,
    )
    max_total_source_bytes = _validate_positive_integer(
        scanner.get("max_total_source_bytes", DEFAULT_MAX_TOTAL_SOURCE_BYTES),
        "max_total_source_bytes",
        config_path,
        HARD_MAX_TOTAL_SOURCE_BYTES,
    )
    max_combined_notes_chars = _validate_positive_integer(
        scanner.get(
            "max_combined_notes_chars",
            DEFAULT_MAX_COMBINED_NOTES_CHARS,
        ),
        "max_combined_notes_chars",
        config_path,
        HARD_MAX_COMBINED_NOTES_CHARS,
    )
    return ScannerConfig(
        include_patterns=include,
        exclude_patterns=exclude,
        include_python=include_python,
        max_artifacts=max_artifacts,
        max_non_python_file_bytes=max_non_python_file_bytes,
        max_total_source_bytes=max_total_source_bytes,
        max_combined_notes_chars=max_combined_notes_chars,
    )


def normalize_relative_path(path: Path | PurePosixPath | str) -> str:
    """Return a project-relative path in the POSIX form used for matching."""
    return str(path).replace("\\", "/")


def path_matches_glob(relative_path: Path | str, pattern: str) -> bool:
    """Match path globs, with ** consuming zero or more complete segments."""
    normalized_path = normalize_relative_path(relative_path)
    normalized_pattern = pattern.replace("\\", "/")
    if (
        normalized_path.startswith("/")
        or normalized_pattern.startswith("/")
        or (len(normalized_path) >= 2 and normalized_path[1] == ":")
        or (len(normalized_pattern) >= 2 and normalized_pattern[1] == ":")
    ):
        return False
    path_parts = tuple(part for part in normalized_path.split("/") if part)
    pattern_parts = tuple(part for part in normalized_pattern.split("/") if part)


    @lru_cache(maxsize=None)
    def matches(path_index: int, pattern_index: int) -> bool:
        if pattern_index == len(pattern_parts):
            return path_index == len(path_parts)
        pattern_part = pattern_parts[pattern_index]
        if pattern_part == "**":
            return matches(path_index, pattern_index + 1) or (
                path_index < len(path_parts) and matches(path_index + 1, pattern_index)
            )
        return (
            path_index < len(path_parts)
            and fnmatch.fnmatchcase(path_parts[path_index], pattern_part)
            and matches(path_index + 1, pattern_index + 1)
        )

    return matches(0, 0)


def matches_any(relative_path: Path | str, patterns: tuple[str, ...]) -> bool:
    return any(path_matches_glob(relative_path, pattern) for pattern in patterns)
