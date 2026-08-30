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


class RecheckError(RuntimeError):
    """Raised when saved rehearsal records cannot be evaluated safely."""


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


def _contains_any(text: str, phrases: list[str]) -> bool:
    folded = text.casefold()
    return any(phrase.casefold() in folded for phrase in phrases)


def extract_allowed_sources(text: str, allowed_sources: list[str]) -> set[str]:
    observed: set[str] = set()
    for source in allowed_sources:
        pattern = re.compile(
            rf"(?<![A-Za-z0-9_./-]){re.escape(source)}"
            rf"(?![A-Za-z0-9_/-]|\.[A-Za-z0-9])",
            re.IGNORECASE,
        )
        if pattern.search(text):
            observed.add(source)
    return observed


def evaluate_ask_contract(
    ask_text: str, contract: dict[str, Any]
) -> tuple[dict[str, bool], dict[str, object]]:
    allowed_sources = list(contract["allowed_sources"])
    observed_sources = extract_allowed_sources(ask_text, allowed_sources)

    unsatisfied_source_groups: list[str] = []
    for index, group in enumerate(contract["required_source_groups"], start=1):
        candidates = set(group["any_of"])
        if not observed_sources & candidates:
            unsatisfied_source_groups.append(str(group.get("name", f"group_{index}")))

    unsatisfied_evidence_groups: list[str] = []
    for index, group in enumerate(contract["required_evidence_groups"], start=1):
        if not _contains_any(ask_text, list(group["any_of"])):
            unsatisfied_evidence_groups.append(
                str(group.get("name", f"evidence_group_{index}"))
            )

    checks = {
        "ask_satisfies_required_source_groups": not unsatisfied_source_groups,
        "ask_has_minimum_distinct_sources": (
            len(observed_sources) >= int(contract["minimum_distinct_sources"])
        ),
        "ask_contains_required_evidence": not unsatisfied_evidence_groups,
        "ask_avoids_forbidden_claims": not any(
            claim.casefold() in ask_text.casefold()
            for claim in contract["forbidden_claims"]
        ),
    }
    diagnostics: dict[str, object] = {
        "observed_sources": sorted(observed_sources),
        "unsatisfied_source_groups": unsatisfied_source_groups,
        "unsatisfied_evidence_groups": unsatisfied_evidence_groups,
    }
    return checks, diagnostics


def _evaluate(
    records: list[dict[str, Any]], gold: dict[str, Any]
) -> tuple[dict[str, bool], dict[str, object]]:
    by_name = {record["name"]: record for record in records}
    memo_text = by_name["memo"]["stdout"]
    ask_text = by_name["ask"]["stdout"]
    freshness_text = by_name["freshness_after_update"]["stdout"]
    brief_text = by_name["brief_after_update"]["stdout"]
    ask_checks, ask_diagnostics = evaluate_ask_contract(ask_text, gold["ask"])
    checks = {
        "all_commands_succeeded": all(record["returncode"] == 0 for record in records),
        "memo_avoids_forbidden_claims": not any(
            claim.casefold() in memo_text.casefold()
            for claim in gold["memo"]["forbidden_claims"]
        ),
        "freshness_reports_stale": "stale" in freshness_text.casefold(),
        "brief_recommends_checkpoint": "checkpoint" in brief_text.casefold(),
    }
    checks.update(ask_checks)
    return checks, {"ask": ask_diagnostics}


REQUIRED_RECORD_NAMES = {
    "checkpoint",
    "brief",
    "memo",
    "ask",
    "freshness_after_update",
    "brief_after_update",
}


def _validated_records(value: object) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise RecheckError("saved run records must be a list of mappings")
    records = list(value)
    names = [record.get("name") for record in records]
    if not all(isinstance(name, str) for name in names):
        raise RecheckError("saved run record names must be strings")
    if len(names) != len(set(names)) or set(names) != REQUIRED_RECORD_NAMES:
        raise RecheckError("saved run records are incomplete or contain duplicate names")
    for record in records:
        returncode = record.get("returncode")
        if isinstance(returncode, bool) or not isinstance(returncode, int):
            raise RecheckError("saved run return codes must be integers")
        if not isinstance(record.get("stdout"), str) or not isinstance(
            record.get("stderr"), str
        ):
            raise RecheckError("saved run output fields must be strings")
    return records


def recheck_results(result_dir: Path) -> tuple[dict[str, object], Path]:
    resolved = result_dir.expanduser().resolve()
    if not resolved.is_dir():
        raise RecheckError("recheck results directory does not exist")
    run_paths = sorted(resolved.glob("run-[0-9][0-9].json"))
    if not run_paths:
        raise RecheckError("recheck results directory contains no run JSON files")

    gold = load_gold()
    results: list[dict[str, object]] = []
    for index, path in enumerate(run_paths, start=1):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RecheckError("saved run JSON is unreadable or invalid") from exc
        if not isinstance(value, dict):
            raise RecheckError("saved run JSON must contain one mapping")
        records = _validated_records(value.get("records"))
        checks, diagnostics = _evaluate(records, gold)
        run_number = value.get("run", index)
        if isinstance(run_number, bool) or not isinstance(run_number, int):
            raise RecheckError("saved run number must be an integer")
        results.append(
            {"run": run_number, "checks": checks, "diagnostics": diagnostics}
        )

    passed = all(all(item["checks"].values()) for item in results)
    summary: dict[str, object] = {
        "runs": len(results),
        "passed": passed,
        "results": results,
    }
    output_path = resolved / "recheck-summary.json"
    output_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=True) + "\n", encoding="utf-8"
    )
    return summary, output_path


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

        if len(records) == 6:
            checks, diagnostics = _evaluate(records, gold)
        else:
            checks = {"all_commands_succeeded": False}
            diagnostics = {"incomplete_record_names": [r["name"] for r in records]}
        run_result = {
            "run": index,
            "checks": checks,
            "diagnostics": diagnostics,
            "records": records,
        }
        (result_dir / f"run-{index:02d}.json").write_text(
            json.dumps(run_result, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        summaries.append({"run": index, "checks": checks, "diagnostics": diagnostics})

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
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--confirm-live-calls", action="store_true")
    mode_group.add_argument("--recheck-results", type=Path)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--pma-command", default="pma")
    args = parser.parse_args(argv)
    if args.recheck_results is not None:
        if (
            args.runs != 3
            or args.results_root != DEFAULT_RESULTS_ROOT
            or args.pma_command != "pma"
        ):
            parser.error("live execution options cannot be used with --recheck-results")
        try:
            summary, _ = recheck_results(args.recheck_results)
        except (RecheckError, OSError, ValueError) as exc:
            print(f"Live rehearsal recheck: FAIL ({exc})", file=sys.stderr)
            return 1
        print(
            f"Live rehearsal recheck: {'PASS' if summary['passed'] else 'FAIL'} "
            f"({summary['runs']} runs)"
        )
        print("Recheck summary: recheck-summary.json")
        return 0 if summary["passed"] else 1
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
