import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any


def load_results(path: Path) -> list[dict[str, Any]]:
    results = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                results.append(json.loads(line))
    return results


def failure_reasons(result: dict[str, Any]) -> list[str]:
    reasons = []
    for check in result.get("checks_failed", []) or []:
        reasons.append(str(check).split(":", 1)[0])
    if result.get("missing_expected"):
        reasons.append("missing_expected")
    if result.get("forbidden_found"):
        reasons.append("forbidden_found")
    if result.get("invalid_evidence_sources"):
        reasons.append("invalid_evidence_sources")
    for failed_change in result.get("missing_changes", []) or []:
        reasons.append(f"change_type:{failed_change.get('change_type', 'unknown')}")
    if result.get("misclassified_changes"):
        reasons.append("misclassified_changes")
    return reasons or ["unknown"]


def collect_numeric_failures(items: list[dict[str, Any]]) -> list[str]:
    numeric_ids = []
    for item in items:
        for condition in item.get("missing_conditions", []) or []:
            if isinstance(condition, dict) and condition.get("numeric_check_id"):
                numeric_ids.append(str(condition["numeric_check_id"]))
    return numeric_ids


def aggregate_category_scores(results: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    category_totals: dict[str, dict[str, Any]] = {}
    for result in results:
        for category, scores in (result.get("category_scores", {}) or {}).items():
            entry = category_totals.setdefault(
                category,
                {
                    "earned_weight": 0.0,
                    "total_weight": 0.0,
                    "failed_items": 0,
                },
            )
            entry["earned_weight"] += float(scores.get("earned_weight", 0.0))
            entry["total_weight"] += float(scores.get("total_weight", 0.0))
            entry["failed_items"] += len(scores.get("failed_ids", []) or [])

    for scores in category_totals.values():
        total = scores["total_weight"]
        scores["score"] = (scores["earned_weight"] / total) if total else 1.0

    return category_totals


def render_summary(results: list[dict[str, Any]], results_path: Path) -> str:
    total = len(results)
    rule_passed = sum(
        1
        for result in results
        if result.get("rule_passed", result.get("passed")) is True
    )
    rule_failed = total - rule_passed
    rule_pass_rate = (rule_passed / total * 100.0) if total else 0.0
    rule_scores = [
        float(result.get("rule_score", result.get("score")))
        for result in results
        if isinstance(result.get("rule_score", result.get("score")), (int, float))
    ]
    average_rule_score = (
        sum(rule_scores) / len(rule_scores) * 100.0 if rule_scores else 0.0
    )
    final_status_counts: Counter[str] = Counter(
        result.get(
            "final_status",
            "pass" if result.get("rule_passed", result.get("passed")) else "fail",
        )
        for result in results
    )
    final_scores = [
        float(result["final_score"])
        for result in results
        if isinstance(result.get("final_score"), (int, float))
    ]
    average_final_score = (
        sum(final_scores) / len(final_scores) * 100.0
        if final_scores
        else average_rule_score
    )
    failed_ids = [
        str(result.get("case_id", "unknown"))
        for result in results
        if result.get(
            "final_status",
            "pass" if result.get("rule_passed", result.get("passed")) else "fail",
        )
        != "pass"
    ]

    reason_counts: Counter[str] = Counter()
    missing_claim_counts: Counter[str] = Counter()
    numeric_failure_counts: Counter[str] = Counter()
    change_failure_counts: Counter[str] = Counter()
    judge_failed_counts: Counter[str] = Counter()
    judge_uncertain_counts: Counter[str] = Counter()
    category_scores = aggregate_category_scores(results)
    for result in results:
        final_status = result.get(
            "final_status",
            "pass" if result.get("rule_passed", result.get("passed")) else "fail",
        )
        if final_status != "pass":
            reason_counts.update(failure_reasons(result))
            for missing in result.get("missing_expected", []) or []:
                claim_id = missing.get("claim_id")
                if claim_id:
                    missing_claim_counts[str(claim_id)] += 1
            numeric_failure_counts.update(
                collect_numeric_failures(result.get("missing_expected", []) or [])
            )
            for failed_change in result.get("missing_changes", []) or []:
                change_failure_counts[str(failed_change.get("change_type", "unknown"))] += 1
            numeric_failure_counts.update(
                collect_numeric_failures(result.get("missing_changes", []) or [])
            )
        judge_result = result.get("judge_result") or {}
        for criterion in judge_result.get("failed_criteria", []) or []:
            judge_failed_counts[str(criterion)] += 1
        for criterion in judge_result.get("uncertain_criteria", []) or []:
            judge_uncertain_counts[str(criterion)] += 1

    lines = [
        "# Eval Summary",
        "",
        f"Results file: `{results_path}`",
        "",
        f"- Total cases: {total}",
        f"- Rule passed cases: {rule_passed}",
        f"- Rule failed cases: {rule_failed}",
        f"- Rule pass rate: {rule_pass_rate:.1f}%",
        f"- Average rule score: {average_rule_score:.1f}%",
        f"- Final pass: {final_status_counts.get('pass', 0)}",
        f"- Final fail: {final_status_counts.get('fail', 0)}",
        f"- Final needs_review: {final_status_counts.get('needs_review', 0)}",
        f"- Average final score: {average_final_score:.1f}%",
        "",
        "## Non-Passing Final Case IDs",
        "",
    ]

    if failed_ids:
        lines.extend(f"- {case_id}" for case_id in failed_ids)
    else:
        lines.append("- None")

    lines.extend(["", "## Category Scores", ""])
    if category_scores:
        lines.extend(
            [
                "| Category | Score | Earned / Total | Failed Items |",
                "|---|---:|---:|---:|",
            ]
        )
        for category, scores in sorted(category_scores.items()):
            earned = scores["earned_weight"]
            total_weight = scores["total_weight"]
            score = scores["score"] * 100.0
            failed_items = scores["failed_items"]
            lines.append(
                f"| {category} | {score:.1f}% | {earned:g} / {total_weight:g} | {failed_items} |"
            )
    else:
        lines.append("- None")

    lines.extend(["", "## Top Failure Reasons", ""])
    if reason_counts:
        for reason, count in reason_counts.most_common():
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- None")

    lines.extend(["", "## Most Common Missing Expected Claim IDs", ""])
    if missing_claim_counts:
        for claim_id, count in missing_claim_counts.most_common():
            lines.append(f"- {claim_id}: {count}")
    else:
        lines.append("- None")

    lines.extend(["", "## Top Numeric Check Failures", ""])
    if numeric_failure_counts:
        for numeric_id, count in numeric_failure_counts.most_common():
            lines.append(f"- {numeric_id}: {count}")
    else:
        lines.append("- None")

    lines.extend(["", "## Change-Type Eval", ""])
    lines.append(f"- Added changes failed: {change_failure_counts.get('added', 0)}")
    lines.append(f"- Revised changes failed: {change_failure_counts.get('revised', 0)}")
    lines.append(f"- Removed changes failed: {change_failure_counts.get('removed', 0)}")
    lines.append(f"- Unchanged misclassified: {change_failure_counts.get('unchanged', 0)}")

    lines.extend(["", "## Judge Failed Criteria", ""])
    if judge_failed_counts:
        for criterion, count in judge_failed_counts.most_common():
            lines.append(f"- {criterion}: {count}")
    else:
        lines.append("- None")

    lines.extend(["", "## Judge Uncertain Criteria", ""])
    if judge_uncertain_counts:
        for criterion, count in judge_uncertain_counts.most_common():
            lines.append(f"- {criterion}: {count}")
    else:
        lines.append("- None")

    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("results_jsonl")
    args = parser.parse_args()

    results_path = Path(args.results_jsonl).resolve()
    results = load_results(results_path)
    summary = render_summary(results=results, results_path=results_path)
    summary_path = results_path.with_name("summary.md")
    summary_path.write_text(summary, encoding="utf-8")

    print(summary)
    print(f"Summary written: {summary_path}")


if __name__ == "__main__":
    main()
