from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]


class SmokeFailure(RuntimeError):
    """Raised when a release smoke command violates its contract."""


def run_checked(
    command: list[str],
    *,
    cwd: Path,
    label: str,
    expected_exit_code: int = 0,
) -> subprocess.CompletedProcess[str]:
    completed = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if completed.returncode != expected_exit_code:
        raise SmokeFailure(
            f"{label} exited {completed.returncode}; expected {expected_exit_code}.\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    combined = f"{completed.stdout}\n{completed.stderr}".lower()
    if "traceback (most recent call last)" in combined:
        raise SmokeFailure(f"{label} emitted a Python traceback.")
    return completed


def _venv_executable(venv_dir: Path, name: str) -> Path:
    scripts_dir = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return venv_dir / scripts_dir / f"{name}{suffix}"


def _json_object(text: str, label: str) -> dict[str, Any]:
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SmokeFailure(f"{label} did not emit valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise SmokeFailure(f"{label} JSON must be an object.")
    return value


def run_release_smoke() -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="pma_release_smoke_") as temp_dir:
        root = Path(temp_dir)
        artifact_dir = root / "artifacts"
        artifact_dir.mkdir()

        run_checked(
            [
                sys.executable,
                "-m",
                "build",
                "--outdir",
                str(artifact_dir),
                str(REPO_ROOT),
            ],
            cwd=root,
            label="package build",
        )
        wheels = sorted(artifact_dir.glob("*.whl"))
        sdists = sorted(artifact_dir.glob("*.tar.gz"))
        if len(wheels) != 1 or len(sdists) != 1:
            raise SmokeFailure(
                "Build must produce exactly one wheel and one source distribution."
            )

        venv_dir = root / "venv"
        run_checked(
            [sys.executable, "-m", "venv", str(venv_dir)],
            cwd=root,
            label="virtual environment creation",
        )
        python = _venv_executable(venv_dir, "python")
        pma = _venv_executable(venv_dir, "pma")
        run_checked(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                str(wheels[0]),
            ],
            cwd=root,
            label="wheel installation",
        )

        outside_dir = root / "outside-repository"
        project_dir = outside_dir / "synthetic-project"
        project_dir.mkdir(parents=True)
        (project_dir / "README.md").write_text(
            "# Synthetic release smoke project\n",
            encoding="utf-8",
        )

        help_commands = [
            ("pma_help", [str(pma), "--help"]),
            ("checkpoint_help", [str(pma), "checkpoint", "--help"]),
            ("ask_help", [str(pma), "ask", "--help"]),
            ("memo_help", [str(pma), "memo", "--help"]),
            ("brief_help", [str(pma), "brief", "--help"]),
            ("freshness_help", [str(pma), "freshness", "--help"]),
            ("status_note_help", [str(pma), "status-note", "--help"]),
        ]
        checks: list[str] = []
        for label, command in help_commands:
            completed = run_checked(command, cwd=outside_dir, label=label)
            if "usage:" not in completed.stdout.lower():
                raise SmokeFailure(f"{label} did not emit command help.")
            checks.append(label)

        brief = run_checked(
            [str(pma), "brief", "--project-dir", str(project_dir), "--json"],
            cwd=outside_dir,
            label="brief_missing_checkpoint",
        )
        brief_data = _json_object(brief.stdout, "brief_missing_checkpoint")
        if brief_data.get("checkpoint", {}).get("status") != "missing":
            raise SmokeFailure("brief did not report a missing checkpoint.")
        checks.append("brief_missing_checkpoint")

        freshness = run_checked(
            [str(pma), "freshness", "--project-dir", str(project_dir), "--json"],
            cwd=outside_dir,
            label="freshness_missing_checkpoint",
        )
        freshness_data = _json_object(
            freshness.stdout,
            "freshness_missing_checkpoint",
        )
        if freshness_data.get("status") != "no_checkpoint":
            raise SmokeFailure("freshness did not report no_checkpoint.")
        checks.append("freshness_missing_checkpoint")

        status_note = run_checked(
            [str(pma), "status-note", "--project-dir", str(project_dir)],
            cwd=outside_dir,
            label="status_note_without_checkpoint",
        )
        if "TODO: Describe the project" not in status_note.stdout:
            raise SmokeFailure("status-note did not emit the TODO template.")
        if (project_dir / "PROJECT_STATUS.md").exists():
            raise SmokeFailure("status-note preview unexpectedly wrote a file.")
        checks.append("status_note_without_checkpoint")

        return {
            "status": "pass",
            "distribution_count": {"wheel": 1, "sdist": 1},
            "installed_from": wheels[0].name,
            "working_directory_outside_repository": True,
            "checks": checks,
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build PMA, install its wheel into a clean temporary environment, "
            "and run OpenAI-free CLI smoke checks outside the repository."
        )
    )
    parser.add_argument(
        "--json-output",
        help="Optional path for the machine-readable smoke report.",
    )
    args = parser.parse_args()

    try:
        report = run_release_smoke()
    except SmokeFailure as exc:
        print(f"Release smoke: FAIL\n{exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(report, indent=2, sort_keys=True)
    if args.json_output:
        output = Path(args.json_output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(f"{rendered}\n", encoding="utf-8")
    print("Release smoke: PASS")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
