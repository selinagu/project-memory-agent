from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from run_query_memo_eval import load_yaml, score_output


REPO_ROOT = Path(__file__).resolve().parents[2]


def discover_cases(eval_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    cases = []
    for gold_path in sorted(eval_root.rglob("gold.yaml")):
        gold = load_yaml(gold_path)
        if gold.get("case_type") == "status_note":
            cases.append((gold_path, gold))
    return cases


def command_with_project_dir(command: list[str], project_dir: Path) -> list[str]:
    if not command:
        raise ValueError("gold.yaml command must not be empty")
    updated = list(command)
    if updated[0] == "pma":
        updated = [sys.executable, "-m", "pma", *updated[1:]]

    for index, argument in enumerate(updated):
        if argument == "--project-dir":
            if index + 1 >= len(updated):
                raise ValueError("--project-dir is missing a value")
            updated[index + 1] = str(project_dir)
            return updated
        if argument.startswith("--project-dir="):
            updated[index] = f"--project-dir={project_dir}"
            return updated

    try:
        insert_at = updated.index("status-note") + 1
    except ValueError:
        insert_at = len(updated)
    updated[insert_at:insert_at] = ["--project-dir", str(project_dir)]
    return updated


def live_environment() -> dict[str, str]:
    environment = os.environ.copy()
    src_path = str(REPO_ROOT / "src")
    existing = environment.get("PYTHONPATH")
    environment["PYTHONPATH"] = (
        f"{src_path}{os.pathsep}{existing}" if existing else src_path
    )
    return environment


def _selected_output(
    completed: subprocess.CompletedProcess[str],
    gold: dict[str, Any],
) -> str:
    stream = gold.get("score_stream", "stdout")
    if stream == "stdout":
        return completed.stdout
    if stream == "stderr":
        return completed.stderr
    if stream == "combined":
        return f"{completed.stdout}\n{completed.stderr}"
    raise ValueError(f"unsupported score_stream: {stream}")


def _record_file_assertions(
    result: dict[str, Any],
    project_dir: Path,
    gold: dict[str, Any],
) -> None:
    passed = result["checks_passed"]
    failed = result["checks_failed"]

    for relative_path, expected in (gold.get("file_equals") or {}).items():
        path = project_dir / relative_path
        check = f"file_equals: {relative_path}"
        try:
            observed = path.read_text(encoding="utf-8")
        except OSError:
            observed = None
        (passed if observed == str(expected) else failed).append(check)

    for relative_path, expected_values in (
        gold.get("file_required_includes") or {}
    ).items():
        path = project_dir / relative_path
        try:
            observed = path.read_text(encoding="utf-8").lower()
        except OSError:
            observed = ""
        for expected in expected_values or []:
            check = f"file_required_include: {relative_path}: {expected}"
            (passed if str(expected).lower() in observed else failed).append(check)

    result["passed"] = not failed
    result["final_status"] = "pass" if not failed else "fail"
    result["score"] = len(passed) / (len(passed) + len(failed)) if passed or failed else 1.0


def failed_result(
    gold: dict[str, Any],
    case_output_dir: Path,
    message: str,
) -> dict[str, Any]:
    case_output_dir.mkdir(parents=True, exist_ok=True)
    stderr_path = case_output_dir / "stderr.txt"
    stderr_path.write_text(message, encoding="utf-8")
    return {
        "case_id": gold.get("case_id", "unknown"),
        "case_type": "status_note",
        "capability": gold.get("capability"),
        "stderr_path": str(stderr_path),
        "passed": False,
        "score": 0.0,
        "checks_passed": [],
        "checks_failed": [f"runner_error: {message}"],
        "final_status": "fail",
    }


def run_case(
    gold_path: Path,
    gold: dict[str, Any],
    run_root: Path,
    *,
    timeout_seconds: int = 30,
) -> dict[str, Any]:
    case_output_dir = run_root / gold["case_id"]
    case_output_dir.mkdir(parents=True, exist_ok=True)
    input_dir = gold_path.parent / "input"
    if not input_dir.is_dir():
        return failed_result(gold, case_output_dir, f"missing input directory: {input_dir}")

    try:
        with tempfile.TemporaryDirectory(prefix=f"pma_status_{gold['case_id']}_") as temp_dir:
            project_dir = Path(temp_dir) / "project"
            shutil.copytree(input_dir, project_dir)
            command = command_with_project_dir(gold.get("command", []), project_dir)
            completed = subprocess.run(
                command,
                cwd=project_dir,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                env=live_environment(),
            )
            output = _selected_output(completed, gold)
            result = {
                "case_id": gold["case_id"],
                "case_type": gold["case_type"],
                "capability": gold.get("capability"),
                "command": gold.get("command"),
                "exit_code": completed.returncode,
            }
            result.update(score_output(output, completed.returncode, gold))
            _record_file_assertions(result, project_dir, gold)
    except subprocess.TimeoutExpired:
        return failed_result(
            gold,
            case_output_dir,
            f"command timed out after {timeout_seconds} seconds",
        )
    except Exception as exc:
        return failed_result(gold, case_output_dir, str(exc))

    stdout_path = case_output_dir / "stdout.md"
    stderr_path = case_output_dir / "stderr.txt"
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")
    result["stdout_path"] = str(stdout_path)
    result["stderr_path"] = str(stderr_path)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic, OpenAI-free status-note evaluations."
    )
    parser.add_argument("--eval-root", default="evals/public/status_note")
    parser.add_argument("--output-root", default="evals/outputs")
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument(
        "--case-id",
        action="append",
        help="Run only the specified status-note case id. Can be repeated.",
    )
    args = parser.parse_args()

    eval_root = (REPO_ROOT / args.eval_root).resolve()
    output_root = (REPO_ROOT / args.output_root).resolve()
    run_root = output_root / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_root.mkdir(parents=True, exist_ok=True)
    results_path = run_root / "status_note_results.jsonl"

    cases = discover_cases(eval_root)
    if args.case_id:
        requested = set(args.case_id)
        cases = [(path, gold) for path, gold in cases if gold.get("case_id") in requested]
        missing = sorted(requested - {gold.get("case_id") for _, gold in cases})
        if missing:
            parser.error(f"unknown case id(s): {', '.join(missing)}")
    if not cases:
        parser.error(f"no status-note cases found under {eval_root}")

    all_passed = True
    with results_path.open("w", encoding="utf-8") as results_file:
        for gold_path, gold in cases:
            result = run_case(
                gold_path,
                gold,
                run_root,
                timeout_seconds=args.timeout_seconds,
            )
            all_passed = all_passed and result["final_status"] == "pass"
            results_file.write(json.dumps(result, ensure_ascii=False) + "\n")
            print(f"{result['case_id']}: {result['final_status'].upper()}")

    print(f"Results: {results_path}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
