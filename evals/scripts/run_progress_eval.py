import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from llm_judge import judge_progress_case
from scoring_utils import (
    add_category_score,
    apply_hybrid_status,
    claim_matches,
    claim_triggered,
    claim_weight,
    contains_ci,
    evaluate_expected_changes,
    get_markdown_scope,
    infer_progress_claim_category,
    merge_category_scores,
    score_from_weight,
    section_text,
    subsection_text,
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
        if gold.get("case_type") == "progress_update":
            cases.append((gold_path, gold))
    return cases


def run_checkpoint_history(
    project_dir: Path,
    project_name: str,
    base_output_dir: Path,
    model: str,
    semantic_diff: bool,
    semantic_diff_model: str,
) -> None:
    cmd = [
        sys.executable,
        str(CHECKPOINT_SCRIPT),
        "--project-dir",
        str(project_dir),
        "--project-name",
        project_name,
        "--base-output-dir",
        str(base_output_dir),
        "--model",
        model,
    ]
    if semantic_diff:
        cmd.extend([
            "--semantic-diff",
            "--semantic-diff-model",
            semantic_diff_model,
        ])
    subprocess.run(cmd, cwd=REPO_ROOT, check=True)


def build_rule_details(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "rule_score": result.get("score"),
        "checks_failed": result.get("checks_failed", []),
        "missing_expected": result.get("missing_expected", []),
        "missing_changes": result.get("missing_changes", []),
        "forbidden_found": result.get("forbidden_found", []),
        "misclassified_changes": result.get("misclassified_changes", []),
    }


def has_non_none_bullet(markdown: str) -> bool:
    for line in markdown.splitlines():
        stripped = line.strip()
        if stripped.startswith("- ") and stripped.lower() != "- none":
            return True
    return False


def no_progress_reported(progress: str) -> bool:
    checks = [
        section_text(progress, "New Confirmed Findings"),
        section_text(progress, "Removed or Revised Confirmed Findings"),
        subsection_text(progress, "Next Action Changes", "Added"),
        subsection_text(progress, "Open Question Changes", "Added"),
    ]
    return not any(has_non_none_bullet(text) for text in checks)


def score_progress(progress: str, gold: dict[str, Any]) -> dict[str, Any]:
    expected = gold.get("expected", {})
    forbidden = gold.get("forbidden", {})
    expected_claims = gold.get("expected_claims", []) or []
    forbidden_claims = gold.get("forbidden_claims", []) or []
    expected_changes = gold.get("expected_changes", {}) or {}

    checks_passed: list[str] = []
    checks_failed: list[str] = []
    missing_expected: list[dict[str, Any]] = []
    forbidden_found: list[dict[str, Any]] = []
    change_checks_passed: list[str] = []
    change_checks_failed: list[str] = []
    missing_changes: list[dict[str, Any]] = []
    misclassified_changes: list[dict[str, Any]] = []
    category_scores: dict[str, Any] = {}
    not_implemented_checks: list[str] = []
    earned_weight = 0.0
    total_weight = 0.0

    for claim in expected_claims:
        claim_id = claim.get("id", "unnamed_expected_claim")
        weight = claim_weight(claim)
        category = infer_progress_claim_category(claim)
        total_weight += weight
        scope = get_markdown_scope(
            progress,
            section=claim.get("target_section"),
            subsection=claim.get("target_subsection"),
        )
        matched, missing = claim_matches(scope, claim)
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
                    "target_section": claim.get("target_section"),
                    "target_subsection": claim.get("target_subsection"),
                    "missing_conditions": missing,
                    "weight": weight,
                }
            )

    expected_fields = {
        "changed_artifacts": "changed_artifacts",
        "added_next_actions": "added_next_actions",
        "added_open_questions": "added_open_questions",
        "corrected_results": "corrected_results",
    }

    for field in expected_fields:
        for expected_text in expected.get(field, []) or []:
            check_id = f"{field}: {expected_text}"
            total_weight += 1
            if contains_ci(progress, expected_text):
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
                        "field": field,
                        "expected": expected_text,
                        "missing_conditions": [f"substring: {expected_text}"],
                        "weight": 1,
                    }
                )

    if expected.get("no_progress_expected") is True:
        total_weight += 1
        if no_progress_reported(progress):
            earned_weight += 1
            add_category_score(
                category_scores,
                "legacy",
                1.0,
                1.0,
                True,
                "no_progress_expected",
            )
            checks_passed.append("no_progress_expected")
        else:
            add_category_score(
                category_scores,
                "legacy",
                0.0,
                1.0,
                False,
                "no_progress_expected",
            )
            checks_failed.append("no_progress_expected")
            missing_expected.append(
                {
                    "field": "no_progress_expected",
                    "expected": "no semantic progress bullets",
                    "missing_conditions": ["semantic change bullet present"],
                    "weight": 1,
                }
            )

    for claim in forbidden_claims:
        claim_id = claim.get("id", "unnamed_forbidden_claim")
        scope = get_markdown_scope(
            progress,
            section=claim.get("target_section"),
            subsection=claim.get("target_subsection"),
        )
        if claim_triggered(scope, claim):
            checks_failed.append(f"forbidden_claim:{claim_id}")
            forbidden_found.append(
                {
                    "claim_id": claim_id,
                    "target_section": claim.get("target_section"),
                    "target_subsection": claim.get("target_subsection"),
                    "weight": claim_weight(claim),
                }
            )
        else:
            checks_passed.append(f"forbidden_claim_absent:{claim_id}")

    change_results = evaluate_expected_changes(progress, expected_changes)
    earned_weight += change_results["earned_weight"]
    total_weight += change_results["total_weight"]
    merge_category_scores(category_scores, change_results["category_scores"])
    change_checks_passed.extend(change_results["change_checks_passed"])
    change_checks_failed.extend(change_results["change_checks_failed"])
    checks_passed.extend(change_results["change_checks_passed"])
    checks_failed.extend(change_results["change_checks_failed"])
    missing_changes.extend(change_results["missing_changes"])
    misclassified_changes.extend(change_results["misclassified_changes"])

    for section in forbidden.get("sections", []) or []:
        check_id = f"forbidden section absent: {section}"
        if contains_ci(progress, f"## {section}") or contains_ci(
            progress, f"### {section}"
        ):
            checks_failed.append(check_id)
            forbidden_found.append({"claim_id": "legacy_section", "text": section})
        else:
            checks_passed.append(check_id)

    for claim in forbidden.get("claims", []) or []:
        check_id = f"forbidden claim absent: {claim}"
        if contains_ci(progress, claim):
            checks_failed.append(check_id)
            forbidden_found.append({"claim_id": "legacy_claim", "text": claim})
        else:
            checks_passed.append(check_id)

    for item in forbidden.get("should_not_report", []) or []:
        check_id = f"should_not_report absent: {item}"
        if contains_ci(progress, item):
            checks_failed.append(check_id)
            forbidden_found.append({"claim_id": "legacy_should_not_report", "text": item})
        else:
            checks_passed.append(check_id)

    for change_type in forbidden.get("change_types", []) or []:
        not_implemented_checks.append(f"change_types: {change_type}")

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
        "change_checks_passed": change_checks_passed,
        "change_checks_failed": change_checks_failed,
        "missing_changes": missing_changes,
        "misclassified_changes": misclassified_changes,
        "category_scores": category_scores,
        "not_implemented_checks": not_implemented_checks,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=("fixture", "live"),
        default="fixture",
        help=(
            "fixture scores checked-in canonical outputs (deterministic); "
            "live reruns LLM extraction/alignment (robustness check)"
        ),
    )
    parser.add_argument("--eval-root", default="evals/public")
    parser.add_argument("--output-root", default="evals/outputs")
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument("--judge", action="store_true")
    parser.add_argument("--judge-model", default="gpt-4.1-mini")
    parser.add_argument("--judge-with-sources", action="store_true")
    parser.add_argument("--semantic-diff", action="store_true")
    parser.add_argument("--semantic-diff-model", default="gpt-4.1-mini")
    args = parser.parse_args()
    if args.mode == "fixture" and (
        args.judge or args.judge_with_sources or args.semantic_diff
    ):
        parser.error(
            "--judge, --judge-with-sources, and --semantic-diff require --mode live"
        )

    eval_root = (REPO_ROOT / args.eval_root).resolve()
    output_root = (REPO_ROOT / args.output_root).resolve()
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    run_root = output_root / timestamp
    run_root.mkdir(parents=True, exist_ok=True)

    base_output_dir = run_root / "progress_checkpoints"
    results_path = run_root / "progress_results.jsonl"
    print(
        "Mode: deterministic fixture regression"
        if args.mode == "fixture"
        else "Mode: live LLM robustness check (results may vary)"
    )

    cases = discover_cases(eval_root)
    with results_path.open("w", encoding="utf-8") as results_file:
        for gold_path, gold in cases:
            case_id = gold["case_id"]
            project_name = f"eval_{case_id}"
            v1_dir = gold_path.parent / "v1"
            v2_dir = gold_path.parent / "v2"
            progress_path = (
                base_output_dir / project_name / "latest" / "progress_since_last.md"
            )
            latest_dir = base_output_dir / project_name / "latest"
            fixture_path = gold_path.parent / "fixture" / "progress_since_last.md"

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
                    fixture_path.parent
                    if args.mode == "fixture"
                    else base_output_dir / project_name
                ),
                "progress_path": str(
                    fixture_path if args.mode == "fixture" else progress_path
                ),
            }

            try:
                combined_notes_v1 = None
                if args.mode == "fixture":
                    progress = fixture_path.read_text(encoding="utf-8")
                else:
                    run_checkpoint_history(
                        project_dir=v1_dir,
                        project_name=project_name,
                        base_output_dir=base_output_dir,
                        model=args.model,
                        semantic_diff=args.semantic_diff,
                        semantic_diff_model=args.semantic_diff_model,
                    )
                    if args.judge and args.judge_with_sources:
                        combined_notes_v1_path = latest_dir / "combined_notes.md"
                        combined_notes_v1 = (
                            combined_notes_v1_path.read_text(encoding="utf-8")
                            if combined_notes_v1_path.exists()
                            else None
                        )
                    run_checkpoint_history(
                        project_dir=v2_dir,
                        project_name=project_name,
                        base_output_dir=base_output_dir,
                        model=args.model,
                        semantic_diff=args.semantic_diff,
                        semantic_diff_model=args.semantic_diff_model,
                    )
                    progress = progress_path.read_text(encoding="utf-8")
                result.update(score_progress(progress=progress, gold=gold))
                combined_notes_v2 = None
                if args.judge and args.judge_with_sources:
                    combined_notes_v2_path = latest_dir / "combined_notes.md"
                    combined_notes_v2 = (
                        combined_notes_v2_path.read_text(encoding="utf-8")
                        if combined_notes_v2_path.exists()
                        else None
                    )

                judge_result = None
                if args.judge:
                    try:
                        judge_result = judge_progress_case(
                            gold=gold,
                            progress_report=progress,
                            rule_details=build_rule_details(result),
                            combined_notes_v1=combined_notes_v1,
                            combined_notes_v2=combined_notes_v2,
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
                        "change_checks_passed": [],
                        "change_checks_failed": [],
                        "missing_changes": [],
                        "misclassified_changes": [],
                        "category_scores": {},
                        "not_implemented_checks": [],
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
