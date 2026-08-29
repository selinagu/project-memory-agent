from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
LIVE_ROOT = Path(__file__).resolve().parent
BASE_FIXTURE = LIVE_ROOT / "fixtures" / "atlas-cache-gateway"
UPDATE_FIXTURE = LIVE_ROOT / "fixtures" / "updates" / "PROJECT_STATUS.md"
DEFAULT_OUTPUT = Path("/tmp/pma-live-demo")
DEFAULT_UPDATE_OUTPUT = Path("/tmp/pma-live-demo-update.md")
SENTINEL_NAME = "pma-live-demo-sentinel"
REQUIRED_PROJECT_FILES = (
    "README.md",
    "PROJECT_STATUS.md",
    "benchmark_results.json",
    "failure_analysis.md",
    "next_steps.md",
)


class PrepareError(RuntimeError):
    """Raised when a live-demo workspace cannot be prepared safely."""


@dataclass(frozen=True)
class PreparedDemo:
    project_dir: Path
    update_path: Path


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve()


def _reject_unsafe_target(path: Path, *, label: str) -> Path:
    resolved = _resolved(path)
    home = Path.home().resolve()
    repository = REPO_ROOT.resolve()
    if resolved == Path(resolved.anchor):
        raise PrepareError(f"{label} must not be a filesystem root")
    if resolved == home:
        raise PrepareError(f"{label} must not be the user home directory")
    if resolved == repository or repository in resolved.parents or resolved in repository.parents:
        raise PrepareError(f"{label} must remain outside the PMA repository")
    return resolved


def _run_git(project_dir: Path, *arguments: str, env: dict[str, str] | None = None) -> str:
    completed = subprocess.run(
        ["git", *arguments],
        cwd=project_dir,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if completed.returncode != 0:
        raise PrepareError(f"git {arguments[0]} failed while preparing the demo")
    return completed.stdout.strip()


def _sentinel_path(project_dir: Path) -> Path:
    return project_dir / ".git" / SENTINEL_NAME


def prepare_demo(
    output: Path = DEFAULT_OUTPUT,
    update_output: Path = DEFAULT_UPDATE_OUTPUT,
    *,
    reset: bool = False,
) -> PreparedDemo:
    project_dir = _reject_unsafe_target(output, label="demo output")
    update_path = _reject_unsafe_target(update_output, label="demo update output")
    if project_dir == update_path or project_dir in update_path.parents:
        raise PrepareError("demo update output must remain outside the demo project")

    if project_dir.exists():
        if not reset:
            raise PrepareError("demo output already exists; pass --reset only for a prepared demo")
        if not _sentinel_path(project_dir).is_file():
            raise PrepareError("refusing to reset a directory without the live-demo sentinel")
        shutil.rmtree(project_dir)
    if update_path.exists():
        if not reset:
            raise PrepareError("demo update output already exists")
        update_path.unlink()

    if not BASE_FIXTURE.is_dir() or not UPDATE_FIXTURE.is_file():
        raise PrepareError("checked-in live-demo fixtures are incomplete")
    shutil.copytree(BASE_FIXTURE, project_dir)
    update_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(UPDATE_FIXTURE, update_path)

    _run_git(project_dir, "init", "--quiet")
    _run_git(project_dir, "config", "user.name", "PMA Live Demo")
    _run_git(project_dir, "config", "user.email", "demo@example.invalid")
    _run_git(project_dir, "add", "--", *REQUIRED_PROJECT_FILES)
    commit_env = dict(__import__("os").environ)
    commit_env.update(
        GIT_AUTHOR_DATE="2026-08-30T00:00:00+00:00",
        GIT_COMMITTER_DATE="2026-08-30T00:00:00+00:00",
    )
    _run_git(project_dir, "commit", "--quiet", "-m", "Prepare synthetic demo", env=commit_env)
    _sentinel_path(project_dir).write_text("prepared-by-pma-live-demo\n", encoding="utf-8")
    if _run_git(project_dir, "status", "--short"):
        raise PrepareError("prepared demo repository is not clean")
    return PreparedDemo(project_dir=project_dir, update_path=update_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare PMA's manual live-demo workspace.")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--update-output", type=Path, default=DEFAULT_UPDATE_OUTPUT)
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args(argv)
    try:
        prepared = prepare_demo(args.output, args.update_output, reset=args.reset)
    except PrepareError as exc:
        print(f"Live demo preparation: FAIL ({exc})", file=sys.stderr)
        return 1
    print("Live demo preparation: PASS")
    print(f"Project: {prepared.project_dir}")
    print(f"Update: {prepared.update_path}")
    print(f"Next: cd {prepared.project_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
