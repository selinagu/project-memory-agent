import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_judge import judge_state_case
from scoring_utils import (
    add_category_score,
    apply_hybrid_status,
    claim_matches,
    claim_triggered,
    claim_weight,
    contains_ci,
    infer_state_category,
    score_from_weight,
)

try:
    import yaml
except ImportError as exc:
    raise SystemExit(
        "PyYAML is required for eval scripts. Install with: pip install pyyaml"
    ) from exc


REPO_ROOT = Path(__file__).resolve().parents[2]
CHECKPOINT_SCRIPT = REPO_ROOT / "src" / "checkpoint.py"


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def discover_cases(eval_root: Path) -> list[tuple[Path, dict[str, Any]]]:
    cases = []
    for gold_path in sorted(eval_root.rglob("gold.yaml")):
        gold = load_yaml(gold_path)
        if gold.get("case_type") == "state_reconstruction":
            cases.append((gold_path, gold))
    return cases


def run_checkpoint(input_dir: Path, output_dir: Path, model: str) -> None:
    cmd = [
        sys.executable,
        str(CHECKPOINT_SCRIPT),
        "--project-dir",
        str(input_dir),
        "--output-dir",
        str(output_dir),
        "--model",
        model,
    ]
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def build_rule_details(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_score": result.get("score"),
        "checks_failed": result.get("checks_failed", []),
        "missing_expected": result.get("missing_expected", []),
        "forbidden_found": result.get("forbidden_found", []),
    }


def score_state(
    state: dict[str, Any],
    gold: dict[str, Any],
) -> dict[str, Any]:
    expected = gold.get("expected", {})
    forbidden = gold.get("forbidden", {})
    expected_claims = gold.get("expected_claims", []) or []
    forbidden_claims = gold.get("forbidden_claims", []) or []

    checks_passed: list[str] = []
    checks_failed: list[str] = []
    missing_expected: list[dict[str, Any]] = []
    forbidden_found: list[dict[str, Any]] = []
    invalid_evidence_sources: list[str] = []
    category_scores: dict[str, Any] = {}
    earned_weight = 0.0
    total_weight = 0.0

    for claim in expected_claims:
        claim_id = claim.get("id", "unnamed_expected_claim")
        weight = claim_weight(claim)
        category = infer_state_category(claim)
        total_weight += weight
        target_field = claim.get("target_field")
        target_text = state.get(target_field) if target_field else state
        matched, missing = claim_matches(target_text, claim)

        required_sources = set(claim.get("required_evidence_sources", []) or [])
        if required_sources:
            actual_sources = {
                evidence.get("source", "")
                for evidence in state.get("evidence", []) or []
            }
            if not actual_sources.intersection(required_sources):
                matched = False
                missing.append(
                    "required_evidence_sources: "
                    + " | ".join(sorted(required_sources))
                )

        if matched:
            earned_weight += weight
            add_category_score(
                category_scores, category, weight, weight, True, claim_id
            )
            checks_passed.append(f"expected_claim:{claim_id}")
        else:
            add_category_score(
                category_scores, category, 0.0, weight, False, claim_id
            )
            checks_failed.append(f"expected_claim:{claim_id}")
            missing_expected.append(
                {
                    "claim_id": claim_id,
                    "target_field": target_field,
                    "missing_conditions": missing,
                    "weight": weight,
                }
            )

        if required_sources:
            evidence_category = "evidence"
            evidence_passed = not any(
                isinstance(item, str) and item.startswith("required_evidence_sources:")
                for item in missing
            )
            add_category_score(
                category_scores,
                evidence_category,
                weight if evidence_passed else 0.0,
                weight,
                evidence_passed,
                claim_id,
            )

    field_map = {
        "goal_contains": "goal",
        "current_stage_contains": "current_stage",
        "confirmed_findings_must_include": "confirmed_findings",
        "tentative_hypotheses_must_include": "tentative_hypotheses",
        "open_questions_must_include": "open_questions",
        "next_actions_must_include": "next_actions",
    }

    for expected_key, state_key in field_map.items():
        for expected_text in expected.get(expected_key, []) or []:
            check_id = f"{expected_key}: {expected_text}"
            total_weight += 1
            if contains_ci(state.get(state_key), expected_text):
                earned_weight += 1
                add_category_score(
                    category_scores, "legacy", 1.0, 1.0, True, check_id
                )
                checks_passed.append(check_id)
            else:
                add_category_score(
                    category_scores, "legacy", 0.0, 1.0, False, check_id
                )
                checks_failed.append(check_id)
                missing_expected.append(
                    {
                        "field": expected_key,
                        "expected": expected_text,
                        "missing_conditions": [f"substring: {expected_text}"],
                        "weight": 1,
                    }
                )

    rendered_state = json.dumps(state, ensure_ascii=False, sort_keys=True)
    for claim in forbidden_claims:
        claim_id = claim.get("id", "unnamed_forbidden_claim")
        if claim_triggered(rendered_state, claim):
            checks_failed.append(f"forbidden_claim:{claim_id}")
            forbidden_found.append(
                {
                    "claim_id": claim_id,
                    "weight": claim_weight(claim),
                }
            )
        else:
            checks_passed.append(f"forbidden_claim_absent:{claim_id}")

    for forbidden_text in forbidden.get("must_not_claim", []) or []:
        check_id = f"must_not_claim absent: {forbidden_text}"
        if contains_ci(rendered_state, forbidden_text):
            checks_failed.append(check_id)
            forbidden_found.append(
                {"claim_id": "legacy_must_not_claim", "text": forbidden_text}
            )
        else:
            checks_passed.append(check_id)

    allowed_sources = set(expected.get("evidence_sources_allowed", []) or [])
    if allowed_sources:
        for evidence in state.get("evidence", []) or []:
            source = evidence.get("source", "")
            if source not in allowed_sources:
                invalid_evidence_sources.append(source)

        if invalid_evidence_sources:
            checks_failed.append("evidence_sources_allowed")
        else:
            checks_passed.append("evidence_sources_allowed")

    failed = bool(checks_failed)
    score = score_from_weight(
        earned_weight=earned_weight,
        total_weight=total_weight,
        failed=failed,
    )

    return {
        "passed": not failed,
        "score": score,
        "earned_weight": earned_weight,
        "total_weight": total_weight,
        "checks_passed": checks_passed,
        "checks_failed": checks_failed,
        "missing_expected": missing_expected,
        "forbidden_found": forbidden_found,
        "invalid_evidence_sources": sorted(set(invalid_evidence_sources)),
        "category_scores": category_scores,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("fixture", "live"),
        default="fixture",
        help=(
            "fixture scores checked-in canonical outputs (deterministic); "
            "live reruns LLM extraction (robustness check)"
        ),
    )
    parser.add_argument("--eval-root", default="evals/public")
    parser.add_argument("--output-root", default="evals/outputs")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--judge-model", default="gpt-4.1-mini")
    parser.add_argument("--judge-with-sources", action="store_true")
    args = parser.parse_args()
    if args.mode == "fixture" and (args.judge or args.judge_with_sources):
        parser.error("--judge and --judge-with-sources require --mode live")

    eval_root = (REPO_ROOT / args.eval_root).resolve()
    output_root = (REPO_ROOT / args.output_root).resolve()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_root = output_root / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    results_path = run_root / "state_results.jsonl"
    print(
        "Mode: deterministic fixture regression"
        if args.mode == "fixture"
        else "Mode: live LLM robustness check (results may vary)"
    )

    cases = discover_cases(eval_root)
    with results_path.open("w", encoding="utf-8") as results_file:
        for gold_path, gold in cases:
            case_id = gold["case_id"]
            input_dir = gold_path.parent / "input"
            output_dir = run_root / "state" / case_id
            fixture_path = gold_path.parent / "fixture" / "project_state.json"

            result = {
                "case_id": case_id,
                "case_type": gold.get("case_type"),
                "project_name": gold.get("project_name"),
                "evaluation_mode": args.mode,
                "run_classification": (
                    "deterministic_regression"
                    if args.mode == "fixture"
                    else "live_llm_robustness"
                ),
                "output_dir": str(
                    fixture_path.parent if args.mode == "fixture" else output_dir
                ),
            }

            try:
                if args.mode == "fixture":
                    state_path = fixture_path
                else:
                    run_checkpoint(
                        input_dir=input_dir,
                        output_dir=output_dir,
                        model=args.model,
                    )
                    state_path = output_dir / "project_state.json"
                state = json.loads(state_path.read_text(encoding="utf-8"))
                result.update(score_state(state=state, gold=gold))

                judge_result = None
                if args.judge:
                    try:
                        combined_notes = None
                        if args.judge_with_sources:
                            combined_notes_path = output_dir / "combined_notes.md"
                            combined_notes = (
                                combined_notes_path.read_text(encoding="utf-8")
                                if combined_notes_path.exists()
                                else None
                            )
                        judge_result = judge_state_case(
                            gold=gold,
                            project_state=state,
                            rule_details=build_rule_details(result),
                            combined_notes=combined_notes,
                            model=args.judge_model,
                        )
                    except Exception as judge_exc:
                        judge_result = {
                            "status": "needs_review",
                            "score": result.get("score", 0.0),
                            "rationale": f"Judge failed: {judge_exc}",
                            "passed_criteria": [],
                            "failed_criteria": [],
                            "uncertain_criteria": ["judge_error"],
                        }

                apply_hybrid_status(
                    result,
                    judge_enabled=args.judge,
                    judge_result=judge_result,
                )
            except Exception as exc:
                result.update(
                    {
                        "passed": False,
                        "score": 0.0,
                        "earned_weight": 0,
                        "total_weight": 0,
                        "checks_passed": [],
                        "checks_failed": [f"runner_error: {exc}"],
                        "missing_expected": [],
                        "forbidden_found": [],
                        "invalid_evidence_sources": [],
                        "category_scores": {},
                    }
                )
                apply_hybrid_status(
                    result,
                    judge_enabled=args.judge,
                    judge_result={
                        "status": "needs_review",
                        "score": 0.0,
                        "rationale": f"Runner failed before judge could run: {exc}",
                        "passed_criteria": [],
                        "failed_criteria": [],
                        "uncertain_criteria": ["runner_error"],
                    }
                    if args.judge
                    else None,
                )

            results_file.write(json.dumps(result, ensure_ascii=False) + "\n")
            results_file.flush()
            status = result["final_status"].upper()
            if args.mode == "live" and status != "PASS":
                status = f"LIVE_VARIANCE_{status}"
            print(f"{case_id}: {status}")

    print(f"Results: {results_path}")


if __name__ == "__main__":
    main()
