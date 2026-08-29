from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from run_query_memo_eval import load_yaml, score_output


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from freshness import compare_artifact_manifests


def discover_cases(eval_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    cases = []
    for gold_path in sorted(eval_root.rglob("gold.yaml")):
        gold = load_yaml(gold_path)
        if gold.get("case_type") == "reliability":
            cases.append((gold_path, gold))
    return cases


def _render_case(payload: dict[str, Any]) -> str:
    operation = payload.get("operation", "compare_manifests")
    if operation == "missing_manifest":
        value = {
            "status": "unknown",
            "reason_codes": ["artifact_manifest_missing"],
        }
    elif operation == "compare_manifests":
        result = compare_artifact_manifests(
            payload["checkpoint_manifest"],
            payload["current_manifest"],
            checked_at="fixed",
        )
        value = {
            "status": result.status,
            "reason_codes": [reason.code for reason in result.reasons],
            "added": result.added_changed_files,
            "removed": result.removed_changed_files,
            "modified": result.modified_fingerprints,
        }
    else:
        raise ValueError(f"unsupported operation: {operation}")
    return json.dumps(value, indent=2, sort_keys=True)


def run_case(gold_path: Path, gold: dict[str, Any]) -> dict[str, Any]:
    input_path = gold_path.parent / "input" / "case.json"
    if not input_path.is_file():
        return {
            "case_id": gold.get("case_id", "unknown"),
            "case_type": "reliability",
            "passed": False,
            "score": 0.0,
            "checks_passed": [],
            "checks_failed": [f"runner_error: missing input: {input_path}"],
            "final_status": "fail",
        }
    try:
        rendered = _render_case(
            json.loads(input_path.read_text(encoding="utf-8"))
        )
        result = {
            "case_id": gold["case_id"],
            "case_type": gold["case_type"],
            "capability": gold.get("capability"),
        }
        result.update(score_output(rendered, 0, gold))
        result["final_status"] = "pass" if result["passed"] else "fail"
        result["rendered_output"] = rendered
        return result
    except Exception as exc:
        return {
            "case_id": gold.get("case_id", "unknown"),
            "case_type": "reliability",
            "passed": False,
            "score": 0.0,
            "checks_passed": [],
            "checks_failed": [f"runner_error: {type(exc).__name__}: {exc}"],
            "final_status": "fail",
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic, OpenAI-free PMA reliability evaluations."
    )
    parser.add_argument("--eval-root", default="evals/public/reliability")
    parser.add_argument("--output-root", default="evals/outputs")
    parser.add_argument("--case-id", action="append")
    args = parser.parse_args()

    eval_root = (REPO_ROOT / args.eval_root).resolve()
    output_root = (REPO_ROOT / args.output_root).resolve()
    run_root = output_root / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_root.mkdir(parents=True, exist_ok=True)
    results_path = run_root / "reliability_results.jsonl"
    cases = discover_cases(eval_root)
    if args.case_id:
        requested = set(args.case_id)
        cases = [
            (path, gold)
            for path, gold in cases
            if gold.get("case_id") in requested
        ]
        missing = sorted(requested - {gold.get("case_id") for _, gold in cases})
        if missing:
            parser.error(f"unknown case id(s): {', '.join(missing)}")
    if not cases:
        parser.error(f"no reliability cases found under {eval_root}")

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
