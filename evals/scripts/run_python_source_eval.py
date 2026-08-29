from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from run_query_memo_eval import load_yaml, score_output


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from checkpoint import build_combined_notes
from parsers import parse_artifacts
from scan_project import scan_project


def discover_cases(eval_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    cases = []
    for gold_path in sorted(eval_root.rglob("gold.yaml")):
        gold = load_yaml(gold_path)
        if gold.get("case_type") == "python_source":
            cases.append((gold_path, gold))
    return cases


def _record_check(
    result: dict[str, Any],
    passed: bool,
    label: str,
) -> None:
    target = result["checks_passed"] if passed else result["checks_failed"]
    target.append(label)


def _finalize(result: dict[str, Any]) -> None:
    passed = result["checks_passed"]
    failed = result["checks_failed"]
    result["passed"] = not failed
    result["final_status"] = "pass" if not failed else "fail"
    result["score"] = len(passed) / (len(passed) + len(failed)) if passed or failed else 1.0


def run_case(gold_path: Path, gold: dict[str, Any]) -> dict[str, Any]:
    input_dir = gold_path.parent / "input"
    if not input_dir.is_dir():
        return {
            "case_id": gold.get("case_id", "unknown"),
            "case_type": "python_source",
            "passed": False,
            "score": 0.0,
            "checks_passed": [],
            "checks_failed": [f"runner_error: missing input directory: {input_dir}"],
            "final_status": "fail",
        }

    try:
        with tempfile.TemporaryDirectory(prefix=f"pma_python_{gold['case_id']}_") as temp_dir:
            project_dir = Path(temp_dir) / "project"
            shutil.copytree(input_dir, project_dir)
            index = scan_project(project_dir)
            parsed = parse_artifacts(project_dir, index)
            combined_notes = build_combined_notes(parsed)
            parsed_by_path = {artifact.path: artifact for artifact in parsed.artifacts}
            rendered_artifacts = []
            for artifact in index.artifacts:
                parsed_artifact = parsed_by_path.get(artifact.path)
                rendered_artifacts.append(
                    {
                        "path": artifact.path,
                        "artifact_type": artifact.artifact_type,
                        "parser_status": artifact.parser_status,
                        "content_preview": artifact.content_preview,
                        "content_for_llm": (
                            parsed_artifact.content_for_llm if parsed_artifact else None
                        ),
                        "metadata": parsed_artifact.metadata if parsed_artifact else {},
                        "warnings": parsed_artifact.warnings if parsed_artifact else [],
                    }
                )
            rendered = json.dumps(
                {
                    "artifacts": rendered_artifacts,
                    "combined_notes": combined_notes,
                },
                indent=2,
                ensure_ascii=False,
                sort_keys=True,
            )
            result = {
                "case_id": gold["case_id"],
                "case_type": gold["case_type"],
                "capability": gold.get("capability"),
            }
            result.update(score_output(rendered, 0, gold))

            paths = [artifact.path for artifact in index.artifacts]
            expected_paths = gold.get("expected_paths")
            if expected_paths is not None:
                _record_check(
                    result,
                    paths == expected_paths,
                    f"expected_paths: {expected_paths}",
                )
            status_by_path = {
                artifact.path: artifact.parser_status for artifact in index.artifacts
            }
            for path, expected_status in (gold.get("expected_statuses") or {}).items():
                _record_check(
                    result,
                    status_by_path.get(path) == expected_status,
                    f"expected_status: {path}: {expected_status}",
                )
            for relative_path in gold.get("forbidden_created_paths", []) or []:
                _record_check(
                    result,
                    not (project_dir / relative_path).exists(),
                    f"forbidden_created_path: {relative_path}",
                )
            _record_check(
                result,
                str(project_dir) not in rendered,
                "privacy_safe_project_paths",
            )
            _finalize(result)
            result["rendered_output"] = rendered
    except Exception as exc:
        return {
            "case_id": gold.get("case_id", "unknown"),
            "case_type": "python_source",
            "passed": False,
            "score": 0.0,
            "checks_passed": [],
            "checks_failed": [f"runner_error: {type(exc).__name__}: {exc}"],
            "final_status": "fail",
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic, OpenAI-free Python source evaluations."
    )
    parser.add_argument("--eval-root", default="evals/public/python_source")
    parser.add_argument("--output-root", default="evals/outputs")
    parser.add_argument(
        "--case-id",
        action="append",
        help="Run only the specified Python source case id. Can be repeated.",
    )
    args = parser.parse_args()

    eval_root = (REPO_ROOT / args.eval_root).resolve()
    output_root = (REPO_ROOT / args.output_root).resolve()
    run_root = output_root / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_root.mkdir(parents=True, exist_ok=True)
    results_path = run_root / "python_source_results.jsonl"

    cases = discover_cases(eval_root)
    if args.case_id:
        requested = set(args.case_id)
        cases = [(path, gold) for path, gold in cases if gold.get("case_id") in requested]
        missing = sorted(requested - {gold.get("case_id") for _, gold in cases})
        if missing:
            parser.error(f"unknown case id(s): {', '.join(missing)}")
    if not cases:
        parser.error(f"no Python source cases found under {eval_root}")

    all_passed = True
    with results_path.open("w", encoding="utf-8") as results_file:
        for gold_path, gold in cases:
            result = run_case(gold_path, gold)
            all_passed = all_passed and result["final_status"] == "pass"
            stored = dict(result)
            stored.pop("rendered_output", None)
            results_file.write(json.dumps(stored, ensure_ascii=False) + "\n")
            print(f"{result['case_id']}: {result['final_status'].upper()}")

    print(f"Results: {results_path}")
    return 0 if all_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
