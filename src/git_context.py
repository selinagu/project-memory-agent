from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
from typing import Callable

from project_layout import generated_output_prefixes as resolve_generated_output_prefixes


GIT_CONTEXT_SCHEMA_VERSION = 2
GIT_TIMEOUT_SECONDS = 10
CONFLICT_CODES = {"DD", "AU", "UD", "UA", "DU", "AA", "UU"}


@dataclass(frozen=True)
class FileFingerprint:
    path: str
    status: list[str]
    exists: bool
    kind: str
    size_bytes: int | None
    sha256: str | None


@dataclass(frozen=True)
class GitContext:
    schema_version: int = GIT_CONTEXT_SCHEMA_VERSION
    available: bool = False
    reason: str | None = None
    repository_root: str | None = None
    branch: str | None = None
    head_commit: str | None = None
    head_commit_short: str | None = None
    head_commit_subject: str | None = None
    working_tree_clean: bool | None = None
    detached_head: bool | None = None
    staged_files: list[str] = field(default_factory=list)
    unstaged_files: list[str] = field(default_factory=list)
    untracked_files: list[str] = field(default_factory=list)
    conflicted_files: list[str] = field(default_factory=list)
    changed_files: list[str] = field(default_factory=list)
    file_fingerprints: list[FileFingerprint] = field(default_factory=list)
    collected_at: str = ""

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ParsedStatus:
    staged_files: list[str]
    unstaged_files: list[str]
    untracked_files: list[str]
    conflicted_files: list[str]


GitRunner = Callable[[list[str]], subprocess.CompletedProcess[bytes]]


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _unavailable(reason: str, collected_at: str) -> GitContext:
    return GitContext(reason=reason, collected_at=collected_at)


def _run_git(arguments: list[str]) -> subprocess.CompletedProcess[bytes]:
    environment = os.environ.copy()
    # Read-only inspection should not refresh or rewrite the repository index.
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    return subprocess.run(
        ["git", *arguments],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=GIT_TIMEOUT_SECONDS,
        env=environment,
    )


def _decode(value: bytes) -> str:
    return value.decode("utf-8", errors="surrogateescape")


def parse_porcelain_v1_z(output: bytes) -> ParsedStatus:
    staged: set[str] = set()
    unstaged: set[str] = set()
    untracked: set[str] = set()
    conflicted: set[str] = set()
    records = output.split(b"\0")
    index = 0

    while index < len(records):
        record = records[index]
        index += 1
        if not record:
            continue
        if len(record) < 4 or record[2:3] != b" ":
            raise ValueError("invalid porcelain status record")

        status = _decode(record[:2])
        path = _decode(record[3:]).replace("\\", "/")
        if status[0] in {"R", "C"} or status[1] in {"R", "C"}:
            if index >= len(records) or not records[index]:
                raise ValueError("rename or copy status is missing its source path")
            index += 1  # In -z format the destination is in the first record.

        if status == "??":
            untracked.add(path)
        elif status == "!!":
            continue
        elif status in CONFLICT_CODES:
            conflicted.add(path)
        else:
            if status[0] not in {" ", "?"}:
                staged.add(path)
            if status[1] not in {" ", "?"}:
                unstaged.add(path)

    return ParsedStatus(
        staged_files=sorted(staged),
        unstaged_files=sorted(unstaged),
        untracked_files=sorted(untracked),
        conflicted_files=sorted(conflicted),
    )


def _project_relative_status(
    status: ParsedStatus,
    repository_root: Path,
    project_dir: Path,
    generated_output_prefixes: tuple[str, ...] = (),
) -> ParsedStatus:
    project_prefix = project_dir.relative_to(repository_root).as_posix()

    def filtered(paths: list[str]) -> list[str]:
        if project_prefix == ".":
            relative_paths = paths
        else:
            prefix = f"{project_prefix}/"
            relative_paths = [
                path[len(prefix):] for path in paths if path.startswith(prefix)
            ]
        return sorted(
            path
            for path in relative_paths
            if path != ".project_memory" and not path.startswith(".project_memory/")
            and not any(
                path == prefix or path.startswith(f"{prefix}/")
                for prefix in generated_output_prefixes
            )
        )

    return ParsedStatus(
        staged_files=filtered(status.staged_files),
        unstaged_files=filtered(status.unstaged_files),
        untracked_files=filtered(status.untracked_files),
        conflicted_files=filtered(status.conflicted_files),
    )


def fingerprint_changed_files(
    project_dir: Path,
    status: ParsedStatus,
) -> list[FileFingerprint]:
    statuses_by_path: dict[str, list[str]] = {}
    categories = (
        ("staged", status.staged_files),
        ("unstaged", status.unstaged_files),
        ("untracked", status.untracked_files),
        ("conflicted", status.conflicted_files),
    )
    for category, paths in categories:
        for path in paths:
            statuses_by_path.setdefault(path, []).append(category)

    fingerprints = []
    for relative_path in sorted(statuses_by_path):
        pure_path = PurePosixPath(relative_path)
        if pure_path.is_absolute() or ".." in pure_path.parts:
            raise ValueError("Git reported a path outside the project directory")
        path = project_dir.joinpath(*pure_path.parts)
        if path.is_symlink():
            target_bytes = os.fsencode(os.readlink(path))
            fingerprint = FileFingerprint(
                path=relative_path,
                status=sorted(statuses_by_path[relative_path]),
                exists=True,
                kind="symlink",
                size_bytes=len(target_bytes),
                sha256=hashlib.sha256(target_bytes).hexdigest(),
            )
        elif not path.exists():
            fingerprint = FileFingerprint(
                path=relative_path,
                status=sorted(statuses_by_path[relative_path]),
                exists=False,
                kind="missing",
                size_bytes=None,
                sha256=None,
            )
        elif path.is_dir():
            fingerprint = FileFingerprint(
                path=relative_path,
                status=sorted(statuses_by_path[relative_path]),
                exists=True,
                kind="directory",
                size_bytes=None,
                sha256=None,
            )
        elif path.is_file():
            digest = hashlib.sha256()
            size_bytes = 0
            with path.open("rb") as source:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    size_bytes += len(chunk)
                    digest.update(chunk)
            fingerprint = FileFingerprint(
                path=relative_path,
                status=sorted(statuses_by_path[relative_path]),
                exists=True,
                kind="file",
                size_bytes=size_bytes,
                sha256=digest.hexdigest(),
            )
        else:
            fingerprint = FileFingerprint(
                path=relative_path,
                status=sorted(statuses_by_path[relative_path]),
                exists=True,
                kind="other",
                size_bytes=None,
                sha256=None,
            )
        fingerprints.append(fingerprint)
    return fingerprints


def collect_git_context(
    project_dir: Path,
    *,
    runner: GitRunner = _run_git,
    collected_at: str | None = None,
    checkpoint_root: Path | None = None,
    generated_output_prefixes: tuple[str, ...] = (),
) -> GitContext:
    project_dir = project_dir.resolve()
    if checkpoint_root is not None:
        generated_output_prefixes = tuple(
            sorted(
                set(generated_output_prefixes)
                | set(resolve_generated_output_prefixes(project_dir, checkpoint_root))
            )
        )
    timestamp = collected_at or _timestamp()

    try:
        root_result = runner(["-C", str(project_dir), "rev-parse", "--show-toplevel"])
    except FileNotFoundError:
        return _unavailable("git_not_installed", timestamp)
    except (subprocess.TimeoutExpired, OSError):
        return _unavailable("git_command_failed", timestamp)

    if root_result.returncode != 0:
        stderr = _decode(root_result.stderr).lower()
        reason = (
            "not_a_git_repository"
            if "not a git repository" in stderr
            else "git_command_failed"
        )
        return _unavailable(reason, timestamp)

    try:
        repository_root = Path(_decode(root_result.stdout).strip()).resolve()
        project_dir.relative_to(repository_root)
        status_result = runner(
            [
                "-C",
                str(repository_root),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
                "--ignore-submodules=none",
            ]
        )
        branch_result = runner(
            ["-C", str(repository_root), "symbolic-ref", "--quiet", "--short", "HEAD"]
        )
        head_result = runner(["-C", str(repository_root), "rev-parse", "--verify", "HEAD"])
        if status_result.returncode != 0 or branch_result.returncode not in {0, 1}:
            return _unavailable("git_command_failed", timestamp)
        if head_result.returncode not in {0, 128}:
            return _unavailable("git_command_failed", timestamp)

        parsed = _project_relative_status(
            parse_porcelain_v1_z(status_result.stdout),
            repository_root,
            project_dir,
            generated_output_prefixes,
        )
        branch = _decode(branch_result.stdout).strip() if branch_result.returncode == 0 else None
        head_commit = _decode(head_result.stdout).strip() if head_result.returncode == 0 else None
        detached_head = branch is None and head_commit is not None
        head_short = None
        head_subject = None
        if head_commit is not None:
            short_result = runner(
                ["-C", str(repository_root), "rev-parse", "--short=7", "HEAD"]
            )
            subject_result = runner(
                ["-C", str(repository_root), "log", "-1", "--pretty=%s"]
            )
            if short_result.returncode != 0 or subject_result.returncode != 0:
                return _unavailable("git_command_failed", timestamp)
            head_short = _decode(short_result.stdout).strip()
            head_subject = _decode(subject_result.stdout).rstrip("\r\n")
    except FileNotFoundError:
        return _unavailable("git_not_installed", timestamp)
    except (ValueError, subprocess.TimeoutExpired, OSError):
        return _unavailable("git_command_failed", timestamp)

    changed = sorted(
        set(parsed.staged_files)
        | set(parsed.unstaged_files)
        | set(parsed.untracked_files)
        | set(parsed.conflicted_files)
    )
    try:
        fingerprints = fingerprint_changed_files(project_dir, parsed)
    except (OSError, ValueError):
        return _unavailable("git_command_failed", timestamp)
    relative_root = Path(os.path.relpath(repository_root, project_dir)).as_posix()
    return GitContext(
        available=True,
        repository_root=relative_root,
        branch=branch,
        head_commit=head_commit,
        head_commit_short=head_short,
        head_commit_subject=head_subject,
        working_tree_clean=not changed,
        detached_head=detached_head,
        staged_files=parsed.staged_files,
        unstaged_files=parsed.unstaged_files,
        untracked_files=parsed.untracked_files,
        conflicted_files=parsed.conflicted_files,
        changed_files=changed,
        file_fingerprints=fingerprints,
        collected_at=timestamp,
    )


def render_git_context_markdown(context: GitContext) -> str:
    if not context.available:
        explanations = {
            "not_a_git_repository": "this project directory is not inside a Git repository",
            "git_not_installed": "the Git executable is not installed or available",
            "git_command_failed": "a Git command failed or timed out",
        }
        explanation = explanations.get(context.reason, "Git metadata could not be collected")
        return f"# Git Context\n\nGit context is unavailable: {explanation}.\n"

    branch = f"`{context.branch}`" if context.branch else "None (detached HEAD)"
    if context.head_commit_short:
        head = f"`{context.head_commit_short}`"
        if context.head_commit_subject:
            head += f" — {context.head_commit_subject}"
    else:
        head = "None (repository has no commits)"
    lines = [
        "# Git Context",
        "",
        "- Repository available: yes",
        f"- Branch: {branch}",
        f"- HEAD: {head}",
        f"- Working tree: {'clean' if context.working_tree_clean else 'dirty'}",
    ]
    if not context.changed_files:
        return "\n".join([*lines, "", "No changed files.", ""])

    lines.extend(["", "## Changed Files"])
    sections = (
        ("Staged", context.staged_files),
        ("Unstaged", context.unstaged_files),
        ("Untracked", context.untracked_files),
        ("Conflicted", context.conflicted_files),
    )
    for title, paths in sections:
        lines.extend(["", f"### {title}", ""])
        lines.extend([f"- `{path}`" for path in paths] or ["- None"])
    return "\n".join([*lines, ""])


def write_git_context(context: GitContext, output_dir: Path) -> None:
    (output_dir / "git_context.json").write_text(
        json.dumps(context.to_dict(), indent=2, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "git_context.md").write_text(
        render_git_context_markdown(context),
        encoding="utf-8",
        errors="surrogateescape",
    )
