from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path, PurePosixPath
from typing import Any

from artifact_manifest import build_artifact_manifest, validate_artifact_manifest
from git_context import GIT_CONTEXT_SCHEMA_VERSION, GitContext, collect_git_context
from project_layout import resolve_checkpoint_layout
from scan_project import scan_project
from scanner_config import ResourceBudgetError, ScannerConfigError, load_scanner_config


FRESHNESS_SCHEMA_VERSION = 1
VALID_STATUSES = {"staged", "unstaged", "untracked", "conflicted"}
VALID_KINDS = {"file", "missing", "directory", "symlink"}


@dataclass(frozen=True)
class FreshnessReason:
    code: str
    message: str
    path: str | None = None


@dataclass(frozen=True)
class FreshnessResult:
    schema_version: int = FRESHNESS_SCHEMA_VERSION
    status: str = "unknown"
    project_dir: str = "."
    checked_at: str = ""
    checkpoint_available: bool = False
    git_available_at_checkpoint: bool | None = None
    git_available_now: bool | None = None
    reasons: list[FreshnessReason] = field(default_factory=list)
    checkpoint_head: str | None = None
    current_head: str | None = None
    added_changed_files: list[str] = field(default_factory=list)
    removed_changed_files: list[str] = field(default_factory=list)
    modified_fingerprints: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _checked_at() -> str:
    return datetime.now(timezone.utc).isoformat()


def _reason(code: str, message: str, path: str | None = None) -> FreshnessReason:
    return FreshnessReason(code=code, message=message, path=path)


def _result(
    status: str,
    checked_at: str,
    *,
    checkpoint_available: bool,
    checkpoint: dict[str, Any] | None = None,
    current: GitContext | None = None,
    reasons: list[FreshnessReason] | None = None,
    added: list[str] | None = None,
    removed: list[str] | None = None,
    modified: list[str] | None = None,
) -> FreshnessResult:
    return FreshnessResult(
        status=status,
        checked_at=checked_at,
        checkpoint_available=checkpoint_available,
        git_available_at_checkpoint=(
            checkpoint.get("available")
            if checkpoint is not None and isinstance(checkpoint.get("available"), bool)
            else None
        ),
        git_available_now=current.available if current is not None else None,
        reasons=reasons or [],
        checkpoint_head=(
            checkpoint.get("head_commit")
            if checkpoint is not None and isinstance(checkpoint.get("head_commit"), str)
            else None
        ),
        current_head=current.head_commit if current is not None else None,
        added_changed_files=added or [],
        removed_changed_files=removed or [],
        modified_fingerprints=modified or [],
    )


def _load_checkpoint(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("checkpoint Git context must be an object")
    return value


def load_checkpoint_git_context(path: Path) -> dict[str, Any]:
    """Load and structurally validate a checkpoint Git context.

    Freshness comparison remains responsible for deciding whether a valid old
    context is comparable with the current schema.  This loader only establishes
    that the checkpoint artifact itself is well formed.
    """
    context = _load_checkpoint(path)
    if not _valid_core(context):
        raise ValueError("checkpoint Git context is malformed")
    version = context["schema_version"]
    if version not in {1, GIT_CONTEXT_SCHEMA_VERSION}:
        raise ValueError("checkpoint Git context schema is unsupported")
    if version == GIT_CONTEXT_SCHEMA_VERSION:
        _fingerprint_map(context)
    return context


def _valid_core(context: dict[str, Any]) -> bool:
    scalar_fields = (
        "reason",
        "repository_root",
        "branch",
        "head_commit",
        "head_commit_short",
        "head_commit_subject",
    )
    list_fields = (
        "staged_files",
        "unstaged_files",
        "untracked_files",
        "conflicted_files",
        "changed_files",
    )
    valid = (
        type(context.get("schema_version")) is int
        and isinstance(context.get("available"), bool)
        and all(context.get(field_name) is None or isinstance(context.get(field_name), str) for field_name in scalar_fields)
        and (
            context.get("working_tree_clean") is None
            or isinstance(context.get("working_tree_clean"), bool)
        )
        and (
            context.get("detached_head") is None
            or isinstance(context.get("detached_head"), bool)
        )
        and isinstance(context.get("collected_at"), str)
        and all(
            isinstance(context.get(field_name), list)
            and all(isinstance(path, str) for path in context[field_name])
            and context[field_name] == sorted(set(context[field_name]))
            for field_name in list_fields
        )
    )
    if not valid:
        return False
    status_union = sorted(
        set(context["staged_files"])
        | set(context["unstaged_files"])
        | set(context["untracked_files"])
        | set(context["conflicted_files"])
    )
    return context["changed_files"] == status_union


def _status_map(context: dict[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for status, field_name in (
        ("staged", "staged_files"),
        ("unstaged", "unstaged_files"),
        ("untracked", "untracked_files"),
        ("conflicted", "conflicted_files"),
    ):
        for path in context[field_name]:
            result.setdefault(path, []).append(status)
    return {path: sorted(statuses) for path, statuses in result.items()}


def _fingerprint_map(context: dict[str, Any]) -> dict[str, dict[str, Any]]:
    entries = context.get("file_fingerprints")
    if not isinstance(entries, list):
        raise ValueError("fingerprints are missing")
    result = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("fingerprint must be an object")
        path = entry.get("path")
        statuses = entry.get("status")
        exists = entry.get("exists")
        kind = entry.get("kind")
        size = entry.get("size_bytes")
        digest = entry.get("sha256")
        if not isinstance(path, str) or path in result:
            raise ValueError("fingerprint is malformed")
        pure_path = PurePosixPath(path)
        if pure_path.is_absolute() or ".." in pure_path.parts or "\\" in path:
            raise ValueError("fingerprint path is malformed")
        if (
            not isinstance(statuses, list)
            or not statuses
            or not all(isinstance(status, str) for status in statuses)
            or any(status not in VALID_STATUSES for status in statuses)
            or statuses != sorted(set(statuses))
            or not isinstance(exists, bool)
            or not isinstance(kind, str)
            or kind not in VALID_KINDS
            or (size is not None and (type(size) is not int or size < 0))
            or (digest is not None and not isinstance(digest, str))
        ):
            raise ValueError("fingerprint is malformed")
        if digest is not None and (
            len(digest) != 64 or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise ValueError("fingerprint digest is malformed")
        if kind == "file" and (
            not exists or size is None or digest is None or len(digest) != 64
        ):
            raise ValueError("file fingerprint is incomplete")
        if kind == "missing" and (exists or size is not None or digest is not None):
            raise ValueError("missing fingerprint is inconsistent")
        if kind in {"directory", "other"} and (
            not exists or size is not None or digest is not None
        ):
            raise ValueError("non-file fingerprint is inconsistent")
        if kind == "symlink" and (
            not exists or size is None or digest is None or len(digest) != 64
        ):
            raise ValueError("symlink fingerprint is incomplete")
        result[path] = entry
    if set(result) != set(context["changed_files"]):
        raise ValueError("fingerprints do not cover changed files")
    if any(entry["status"] != _status_map(context)[path] for path, entry in result.items()):
        raise ValueError("fingerprint statuses do not match Git status")
    return result


def compare_git_contexts(
    checkpoint: dict[str, Any],
    current: GitContext,
    *,
    checked_at: str | None = None,
) -> FreshnessResult:
    timestamp = checked_at or _checked_at()
    if not _valid_core(checkpoint):
        return _result(
            "unknown",
            timestamp,
            checkpoint_available=True,
            checkpoint=checkpoint,
            current=current,
            reasons=[_reason("malformed_checkpoint_git_context", "The latest Git context is malformed.")],
        )
    version = checkpoint["schema_version"]
    if version not in {1, GIT_CONTEXT_SCHEMA_VERSION}:
        return _result(
            "unknown",
            timestamp,
            checkpoint_available=True,
            checkpoint=checkpoint,
            current=current,
            reasons=[_reason("unsupported_checkpoint_git_schema", "The checkpoint Git schema is unsupported.")],
        )

    if not current.available and current.reason in {"git_not_installed", "git_command_failed"}:
        return _result(
            "unknown", timestamp, checkpoint_available=True, checkpoint=checkpoint, current=current,
            reasons=[_reason("current_git_unavailable", "Current Git state could not be collected reliably.")],
        )
    checkpoint_available = checkpoint["available"]
    if not checkpoint_available and checkpoint.get("reason") in {
        "git_not_installed",
        "git_command_failed",
    }:
        return _result(
            "unknown", timestamp, checkpoint_available=True, checkpoint=checkpoint, current=current,
            reasons=[_reason("checkpoint_git_unavailable", "The checkpoint did not contain reliable Git state.")],
        )
    if checkpoint_available != current.available:
        return _result(
            "stale", timestamp, checkpoint_available=True, checkpoint=checkpoint, current=current,
            reasons=[_reason("git_availability_changed", "Git repository availability changed after the checkpoint.")],
        )
    if not checkpoint_available:
        return _result(
            "current", timestamp, checkpoint_available=True, checkpoint=checkpoint, current=current,
            reasons=[_reason("git_state_matches", "The project remains outside a Git repository.")],
        )

    current_dict = current.to_dict()
    reasons: list[FreshnessReason] = []
    for field_name, code, label in (
        ("head_commit", "head_changed", "HEAD"),
        ("branch", "branch_changed", "Branch"),
        ("detached_head", "detached_head_changed", "Detached HEAD state"),
    ):
        if checkpoint[field_name] != current_dict[field_name]:
            reasons.append(_reason(code, f"{label} changed after the checkpoint."))

    checkpoint_status = _status_map(checkpoint)
    current_status = _status_map(current_dict)
    checkpoint_paths = set(checkpoint_status)
    current_paths = set(current_status)
    added = sorted(current_paths - checkpoint_paths)
    removed = sorted(checkpoint_paths - current_paths)
    reasons.extend(
        _reason("changed_file_added", f"{path} became changed after the checkpoint.", path)
        for path in added
    )
    reasons.extend(
        _reason("changed_file_removed", f"{path} is no longer changed.", path)
        for path in removed
    )
    for path in sorted(checkpoint_paths & current_paths):
        if checkpoint_status[path] != current_status[path]:
            reasons.append(
                _reason("file_status_changed", f"{path} changed Git status after the checkpoint.", path)
            )

    if reasons:
        return _result(
            "stale", timestamp, checkpoint_available=True, checkpoint=checkpoint, current=current,
            reasons=reasons, added=added, removed=removed,
        )
    if version == 1:
        if checkpoint_paths:
            return _result(
                "unknown", timestamp, checkpoint_available=True, checkpoint=checkpoint, current=current,
                reasons=[_reason("checkpoint_fingerprints_missing", "The dirty checkpoint predates file fingerprints.")],
            )
        return _result(
            "current", timestamp, checkpoint_available=True, checkpoint=checkpoint, current=current,
            reasons=[_reason("git_state_matches", "The clean Git state matches the checkpoint.")],
        )

    try:
        checkpoint_fingerprints = _fingerprint_map(checkpoint)
        current_fingerprints = _fingerprint_map(current_dict)
    except ValueError:
        return _result(
            "unknown", timestamp, checkpoint_available=True, checkpoint=checkpoint, current=current,
            reasons=[_reason("checkpoint_fingerprints_invalid", "Required fingerprint data is missing or malformed.")],
        )
    if any(
        entry["kind"] == "directory"
        for entry in [*checkpoint_fingerprints.values(), *current_fingerprints.values()]
    ):
        return _result(
            "unknown", timestamp, checkpoint_available=True, checkpoint=checkpoint, current=current,
            reasons=[_reason("fingerprint_not_comparable", "A changed directory cannot be fingerprinted recursively.")],
        )
    modified = []
    for path in sorted(checkpoint_paths):
        before = checkpoint_fingerprints[path]
        after = current_fingerprints[path]
        meaningful_fields = ("exists", "kind", "size_bytes", "sha256")
        if any(before[field_name] != after[field_name] for field_name in meaningful_fields):
            modified.append(path)
            code = "file_existence_changed" if before["exists"] != after["exists"] else "file_content_changed"
            reasons.append(_reason(code, f"{path} changed after the latest checkpoint.", path))
    return _result(
        "stale" if reasons else "current",
        timestamp,
        checkpoint_available=True,
        checkpoint=checkpoint,
        current=current,
        reasons=reasons or [_reason("git_state_matches", "The latest checkpoint matches the current Git state.")],
        modified=modified,
    )


def compare_artifact_manifests(
    checkpoint_manifest: dict[str, Any],
    current_manifest: dict[str, Any],
    *,
    checked_at: str | None = None,
    checkpoint: dict[str, Any] | None = None,
    current: GitContext | None = None,
) -> FreshnessResult:
    timestamp = checked_at or _checked_at()
    try:
        before = validate_artifact_manifest(checkpoint_manifest)
        after = validate_artifact_manifest(current_manifest)
    except ValueError:
        return _result(
            "unknown",
            timestamp,
            checkpoint_available=True,
            checkpoint=checkpoint,
            current=current,
            reasons=[
                _reason(
                    "artifact_manifest_invalid",
                    "The checkpoint or current artifact manifest is malformed.",
                )
            ],
        )

    if before["config_fingerprint"] != after["config_fingerprint"]:
        return _result(
            "stale",
            timestamp,
            checkpoint_available=True,
            checkpoint=checkpoint,
            current=current,
            reasons=[
                _reason(
                    "scanner_config_changed",
                    "Scanner configuration changed after the checkpoint.",
                )
            ],
        )

    before_map = {entry["path"]: entry for entry in before["artifacts"]}
    after_map = {entry["path"]: entry for entry in after["artifacts"]}
    before_paths = set(before_map)
    after_paths = set(after_map)
    added = sorted(after_paths - before_paths)
    removed = sorted(before_paths - after_paths)
    reasons = [
        *(
            _reason(
                "artifact_added",
                f"{path} was added after the checkpoint.",
                path,
            )
            for path in added
        ),
        *(
            _reason(
                "artifact_removed",
                f"{path} was removed after the checkpoint.",
                path,
            )
            for path in removed
        ),
    ]
    modified: list[str] = []
    uncomparable: list[str] = []
    for path in sorted(before_paths & after_paths):
        old_entry = before_map[path]
        new_entry = after_map[path]
        if old_entry["status"] != "hashed" or new_entry["status"] != "hashed":
            if old_entry != new_entry:
                uncomparable.append(path)
            elif old_entry["status"] != "hashed":
                uncomparable.append(path)
            continue
        if any(
            old_entry[field] != new_entry[field]
            for field in ("artifact_type", "size_bytes", "sha256")
        ):
            modified.append(path)
            reasons.append(
                _reason(
                    "artifact_content_changed",
                    f"{path} changed after the checkpoint.",
                    path,
                )
            )
    if reasons:
        return _result(
            "stale",
            timestamp,
            checkpoint_available=True,
            checkpoint=checkpoint,
            current=current,
            reasons=reasons,
            added=added,
            removed=removed,
            modified=modified,
        )
    if uncomparable:
        return _result(
            "unknown",
            timestamp,
            checkpoint_available=True,
            checkpoint=checkpoint,
            current=current,
            reasons=[
                _reason(
                    "artifact_not_comparable",
                    f"{path} could not be fingerprinted reliably.",
                    path,
                )
                for path in uncomparable
            ],
        )
    return _result(
        "current",
        timestamp,
        checkpoint_available=True,
        checkpoint=checkpoint,
        current=current,
        reasons=[
            _reason(
                "artifact_manifest_matches",
                "The selected project artifacts match the latest checkpoint.",
            )
        ],
    )


def check_checkpoint_freshness(
    project_dir: Path,
    *,
    checked_at: str | None = None,
    project_name: str | None = None,
    base_output_dir: Path | None = None,
    latest_dir: Path | None = None,
) -> FreshnessResult:
    project_dir = project_dir.resolve()
    timestamp = checked_at or _checked_at()
    layout = resolve_checkpoint_layout(
        project_dir,
        project_name=project_name,
        base_output_dir=base_output_dir,
        latest_dir=latest_dir,
    )
    checkpoint_path = layout.latest_dir / "git_context.json"
    if not checkpoint_path.exists():
        return _result(
            "no_checkpoint", timestamp, checkpoint_available=False,
            reasons=[_reason("latest_checkpoint_missing", "No latest checkpoint Git context was found.")],
        )
    try:
        checkpoint = _load_checkpoint(checkpoint_path)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        return _result(
            "unknown", timestamp, checkpoint_available=True,
            reasons=[_reason("malformed_checkpoint_git_context", "The latest Git context is malformed.")],
        )
    current = collect_git_context(
        project_dir,
        checkpoint_root=layout.checkpoint_root,
    )
    if (
        checkpoint.get("available") is False
        and checkpoint.get("reason") == "not_a_git_repository"
        and not current.available
        and current.reason == "not_a_git_repository"
    ):
        manifest_path = layout.latest_dir / "artifact_manifest.json"
        if not manifest_path.is_file():
            return _result(
                "unknown",
                timestamp,
                checkpoint_available=True,
                checkpoint=checkpoint,
                current=current,
                reasons=[
                    _reason(
                        "artifact_manifest_missing",
                        "The non-Git checkpoint predates artifact manifests.",
                    )
                ],
            )
        try:
            checkpoint_manifest = json.loads(
                manifest_path.read_text(encoding="utf-8")
            )
            validate_artifact_manifest(checkpoint_manifest)
            scanner_config = load_scanner_config(project_dir)
            current_index = scan_project(
                project_dir,
                scanner_config,
                checkpoint_root=layout.checkpoint_root,
            )
            current_manifest = build_artifact_manifest(
                project_dir,
                current_index,
                scanner_config,
            )
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            ValueError,
            ScannerConfigError,
            ResourceBudgetError,
        ):
            return _result(
                "unknown",
                timestamp,
                checkpoint_available=True,
                checkpoint=checkpoint,
                current=current,
                reasons=[
                    _reason(
                        "artifact_manifest_unavailable",
                        "Current artifacts could not be compared reliably.",
                    )
                ],
            )
        return compare_artifact_manifests(
            checkpoint_manifest,
            current_manifest,
            checked_at=timestamp,
            checkpoint=checkpoint,
            current=current,
        )
    return compare_git_contexts(checkpoint, current, checked_at=timestamp)


def render_freshness_text(result: FreshnessResult) -> str:
    lines = [f"Checkpoint freshness: {result.status}", ""]
    if result.status == "current":
        lines.append("The latest checkpoint matches the current Git state.")
        if result.current_head:
            lines.append(f"HEAD: {result.current_head[:7]}")
    elif result.status == "no_checkpoint":
        lines.extend(
            [
                "No latest checkpoint Git context was found.",
                "Run `pma checkpoint --project-dir ...` first.",
            ]
        )
    else:
        lines.append("Reasons:")
        lines.extend(f"- {reason.message}" for reason in result.reasons)
    return "\n".join(lines) + "\n"
