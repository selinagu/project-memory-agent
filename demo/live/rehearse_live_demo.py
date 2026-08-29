from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from demo.live.prepare_live_demo import PrepareError, prepare_demo
from demo.live.validate_fixture import load_gold, validate_fixture


DEFAULT_RESULTS_ROOT = Path("/tmp/pma-live-demo-rehearsals")
QUESTION = (
    "Why did we choose bounded key-prefix invalidation over full-cache refresh, "
    "and what evidence supports that decision?"
)


class RehearsalError(RuntimeError):
    """Raised when an explicitly authorized live rehearsal fails."""


def _sanitize(text: str, project_dir: Path, update_path: Path) -> str:
    sanitized = text.replace(str(project_dir), "<DEMO_PROJECT>")
    sanitized = sanitized.replace(str(update_path), "<DEMO_UPDATE>")
    sanitized = re.sub(r"/home/[^/\s]+", "/home/<USER>", sanitized)
    sanitized = re.sub(r"[A-Za-z]:\\Users\\[^\\\s]+", r"C:\\Users\\<USER>", sanitized)
    return sanitized


def _run(command: list[str], project_dir: Path, update_path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=project_dir,
        env=dict(os.environ),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    return {
        "command": " ".join(command),
        "returncode": completed.returncode,
        "stdout": _sanitize(completed.stdout, project_dir, update_path),
        "stderr": _sanitize(completed.stderr, project_dir, update_path),
    }


def _contains_all(text: str, phrases: list[str]) -> bool:
    folded = text.casefold()
    return all(phrase.casefold() in folded for phrase in phrases)


def _evaluate(records: list[dict[str, Any]], gold: dict[str, Any]) -> dict[str, bool]:
    by_name = {record["name"]: record for record in records}
    memo_text = by_name["memo"]["stdout"]
    ask_text = by_name["ask"]["stdout"]
    freshness_text = by_name["freshness_after_update"]["stdout"]
    brief_text = by_name["brief_after_update"]["stdout"]
    return {
        "all_commands_succeeded": all(record["returncode"] == 0 for record in records),
        "memo_avoids_forbidden_claims": not any(
            claim.casefold() in memo_text.casefold()
            for claim in gold["memo"]["forbidden_claims"]
        ),
        "ask_contains_required_sources": _contains_all(
            ask_text, list(gold["ask"]["required_sources"])
        ),
        "ask_avoids_forbidden_claims": not any(
            claim.casefold() in ask_text.casefold()
            for claim in gold["ask"]["forbidden_claims"]
        ),
        "freshness_reports_stale": "stale" in freshness_text.casefold(),
        "brief_recommends_checkpoint": "checkpoint" in brief_text.casefold(),
    }


def rehearse(*, runs: int, results_root: Path, pma_command: str) -> Path:
    if runs < 1:
        raise RehearsalError("--runs must be a positive integer")
    validate_fixture()
    if not os.environ.get("OPENAI_API_KEY"):
        raise RehearsalError("OPENAI_API_KEY is required for an authorized rehearsal")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    result_dir = results_root.expanduser().resolve() / timestamp
    result_dir.mkdir(parents=True, exist_ok=False)
    gold = load_gold()
    summaries: list[dict[str, Any]] = []

    for index in range(1, runs + 1):
        project_dir = result_dir / f"workspace-{index:02d}"
        update_path = result_dir / f"update-{index:02d}.md"
        prepare_demo(project_dir, update_path)
        commands = [
            ("checkpoint", [pma_command, "checkpoint", "--project-dir", "."]),
            ("brief", [pma_command, "brief", "--project-dir", "."]),
            ("memo", [pma_command, "memo", "--type", "self", "--project-dir", "."]),
            (
                "ask",
                [pma_command, "ask", "--project-dir", ".", "--sources", QUESTION],
            ),
        ]
        records: list[dict[str, Any]] = []
        for name, command in commands:
            record = _run(command, project_dir, update_path)
            record["name"] = name
            records.append(record)
            if record["returncode"] != 0:
                break

        if all(record["returncode"] == 0 for record in records):
            shutil.copy2(update_path, project_dir / "PROJECT_STATUS.md")
            for name, command in (
                ("freshness_after_update", [pma_command, "freshness", "--project-dir", "."]),
                ("brief_after_update", [pma_command, "brief", "--project-dir", "."]),
            ):
                record = _run(command, project_dir, update_path)
                record["name"] = name
                records.append(record)

        checks = _evaluate(records, gold) if len(records) == 6 else {
            "all_commands_succeeded": False
        }
        run_result = {"run": index, "checks": checks, "records": records}
        (result_dir / f"run-{index:02d}.json").write_text(
            json.dumps(run_result, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        summaries.append({"run": index, "checks": checks})

    passed = all(all(item["checks"].values()) for item in summaries)
    summary = {"runs": runs, "passed": passed, "results": summaries}
    (result_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    if not passed:
        raise RehearsalError(f"one or more rehearsals failed; inspect {result_dir}")
    return result_dir


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run explicitly authorized, API-backed PMA live-demo rehearsals."
    )
    parser.add_argument("--confirm-live-calls", action="store_true")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--pma-command", default="pma")
    args = parser.parse_args(argv)
    if not args.confirm_live_calls:
        print(
            "Live rehearsal blocked: pass --confirm-live-calls to authorize API-backed commands.",
            file=sys.stderr,
        )
        return 2
    try:
        result_dir = rehearse(
            runs=args.runs,
            results_root=args.results_root,
            pma_command=args.pma_command,
        )
    except (RehearsalError, PrepareError, OSError, ValueError) as exc:
        print(f"Live rehearsal: FAIL ({exc})", file=sys.stderr)
        return 1
    print(f"Live rehearsal: PASS ({result_dir})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
