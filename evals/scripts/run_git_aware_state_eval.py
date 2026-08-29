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

from git_context import GIT_CONTEXT_EVIDENCE_SOURCE, render_git_context_for_prompt
from prompts import EXTRACT_PROJECT_STATE_PROMPT
from source_lookup import (
    SourceSection,
    project_state_lookup_text,
    select_source_sections,
)


def discover_cases(eval_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    cases = []
    for gold_path in sorted(eval_root.rglob("gold.yaml")):
        gold = load_yaml(gold_path)
        if gold.get("case_type") == "git_aware_state":
            cases.append((gold_path, gold))
    return cases


def _record_check(result: dict[str, Any], passed: bool, label: str) -> None:
    target = result["checks_passed"] if passed else result["checks_failed"]
    target.append(label)


def _finalize(result: dict[str, Any]) -> None:
    passed = result["checks_passed"]
    failed = result["checks_failed"]
    result["passed"] = not failed
    result["final_status"] = "pass" if not failed else "fail"
    result["score"] = len(passed) / (len(passed) + len(failed)) if passed or failed else 1.0


def _render_case(case_dir: Path, payload: dict[str, Any]) -> str:
    operation = payload.get("operation", "render")
    context = payload.get("context")
    if operation == "render":
        return render_git_context_for_prompt(context)
    if operation == "prompt_contract":
        block = render_git_context_for_prompt(context)
        return EXTRACT_PROJECT_STATE_PROMPT.format(
            source="combined_notes.md",
            notes="<!-- SOURCE: README.md -->\nSynthetic project notes.",
            git_context=block,
            metadata_evidence_rule=(
                "For repository metadata facts only, the evidence source may be "
                f"exactly {GIT_CONTEXT_EVIDENCE_SOURCE}."
            ),
        )
    if operation == "metadata_boundary":
        project_state = json.dumps(payload["project_state"])
        sections = [
            SourceSection(source=item["source"], text=item["text"])
            for item in payload["sections"]
        ]
        selected, diagnostics = select_source_sections(
            payload["question"],
            project_state,
            sections,
        )
        _, evidence_sources = project_state_lookup_text(project_state)
        return json.dumps(
            {
                "selected_sources": [item.source for item in selected],
                "diagnostics": diagnostics,
                "source_lookup_evidence": sorted(evidence_sources),
            },
            indent=2,
            sort_keys=True,
        )
    raise ValueError(f"unsupported operation: {operation}")


def run_case(gold_path: Path, gold: dict[str, Any]) -> dict[str, Any]:
    input_path = gold_path.parent / "input" / "context.json"
    if not input_path.is_file():
        return {
            "case_id": gold.get("case_id", "unknown"),
            "case_type": "git_aware_state",
            "passed": False,
            "score": 0.0,
            "checks_passed": [],
            "checks_failed": [f"runner_error: missing input: {input_path}"],
            "final_status": "fail",
        }
    try:
        payload = json.loads(input_path.read_text(encoding="utf-8"))
        rendered = _render_case(gold_path.parent, payload)
        result = {
            "case_id": gold["case_id"],
            "case_type": gold["case_type"],
            "capability": gold.get("capability"),
        }
        result.update(score_output(rendered, 0, gold))
        max_chars = gold.get("max_chars")
        if max_chars is not None:
            _record_check(
                result,
                len(rendered) <= int(max_chars),
                f"max_chars: {max_chars}",
            )
        _finalize(result)
        result["rendered_output"] = rendered
        return result
    except Exception as exc:
        return {
            "case_id": gold.get("case_id", "unknown"),
            "case_type": "git_aware_state",
            "passed": False,
            "score": 0.0,
            "checks_passed": [],
            "checks_failed": [f"runner_error: {type(exc).__name__}: {exc}"],
            "final_status": "fail",
        }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run deterministic, OpenAI-free Git-aware state evaluations."
    )
    parser.add_argument("--eval-root", default="evals/public/git_aware_state")
    parser.add_argument("--output-root", default="evals/outputs")
    parser.add_argument("--case-id", action="append")
    args = parser.parse_args()

    eval_root = (REPO_ROOT / args.eval_root).resolve()
    output_root = (REPO_ROOT / args.output_root).resolve()
    run_root = output_root / datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_root.mkdir(parents=True, exist_ok=True)
    results_path = run_root / "git_aware_state_results.jsonl"

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
        parser.error(f"no Git-aware state cases found under {eval_root}")

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
