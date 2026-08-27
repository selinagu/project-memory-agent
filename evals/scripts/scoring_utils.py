import json
import re
from typing import Any


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return "\n".join(str(item) for item in value)
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def contains_ci(haystack: Any, needle: str) -> bool:
    return str(needle).lower() in normalize_text(haystack).lower()


def extract_numbers(text: str) -> list[dict[str, Any]]:
    candidates = []
    for match in re.finditer(r"[-+]?\d[\d,]*(?:\.\d+)?%?", text):
        raw = match.group(0)
        try:
            value = float(raw.rstrip("%").replace(",", ""))
        except ValueError:
            continue

        start = max(0, match.start() - 40)
        end = min(len(text), match.end() + 40)
        candidates.append(
            {
                "value": value,
                "raw": raw,
                "start": match.start(),
                "end": match.end(),
                "context": text[start:end],
            }
        )

    return candidates


def numeric_check_matches(
    text: Any,
    numeric_check: dict[str, Any],
) -> tuple[bool, dict[str, Any] | None]:
    normalized = normalize_text(text)
    expected = float(numeric_check["expected"])
    tolerance = float(numeric_check.get("tolerance", 0))
    unit_any = numeric_check.get("unit_any", []) or []
    candidates = extract_numbers(normalized)
    observed_candidates = [candidate["value"] for candidate in candidates]
    lowered = normalized.lower()

    for candidate in candidates:
        if abs(candidate["value"] - expected) > tolerance:
            continue

        if unit_any:
            window = lowered[candidate["end"] : candidate["end"] + 20]
            has_unit = any(unit.lower() in window for unit in unit_any) or any(
                unit.lower() in lowered for unit in unit_any
            )
            if not has_unit:
                continue

        return True, None

    return (
        False,
        {
            "numeric_check_id": numeric_check.get("id", "unnamed_numeric_check"),
            "expected": expected,
            "tolerance": tolerance,
            "unit_any": unit_any,
            "observed_candidates": observed_candidates,
            "reason": "no numeric value within tolerance",
        },
    )


def claim_matches(text: Any, claim: dict[str, Any]) -> tuple[bool, list[Any]]:
    normalized_text = normalize_text(text)
    normalized = normalized_text.lower()
    missing: list[Any] = []

    must_mention_all = claim.get("must_mention_all", []) or []
    must_mention_any = claim.get("must_mention_any", []) or []

    for phrase in must_mention_all:
        if str(phrase).lower() not in normalized:
            missing.append(f"must_mention_all: {phrase}")

    if must_mention_any and not any(
        str(phrase).lower() in normalized for phrase in must_mention_any
    ):
        missing.append(
            "must_mention_any: "
            + " | ".join(str(phrase) for phrase in must_mention_any)
        )

    for numeric_check in claim.get("numeric_checks", []) or []:
        matched, failure = numeric_check_matches(normalized_text, numeric_check)
        if not matched:
            missing.append(failure)

    return not missing, missing


def claim_triggered(text: Any, claim: dict[str, Any]) -> bool:
    has_all = bool(claim.get("must_mention_all"))
    has_any = bool(claim.get("must_mention_any"))
    if not has_all and not has_any:
        return False

    matched, _missing = claim_matches(text, claim)
    return matched


def section_text(markdown: str, heading: str) -> str:
    pattern = rf"^## {re.escape(heading)}\s*$"
    match = re.search(pattern, markdown, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return ""

    next_heading = re.search(
        r"^##\s+",
        markdown[match.end() :],
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if next_heading:
        return markdown[match.end() : match.end() + next_heading.start()]
    return markdown[match.end() :]


def subsection_text(markdown: str, section: str, subsection: str) -> str:
    parent = section_text(markdown, section)
    pattern = rf"^### {re.escape(subsection)}\s*$"
    match = re.search(pattern, parent, flags=re.IGNORECASE | re.MULTILINE)
    if not match:
        return ""

    next_subheading = re.search(
        r"^###\s+",
        parent[match.end() :],
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if next_subheading:
        return parent[match.end() : match.end() + next_subheading.start()]
    return parent[match.end() :]


def get_markdown_scope(
    markdown: str,
    section: str | None = None,
    subsection: str | None = None,
) -> str:
    if not section:
        return markdown
    if subsection:
        return subsection_text(markdown, section, subsection)
    return section_text(markdown, section)


def claim_weight(claim: dict[str, Any]) -> float:
    return float(claim.get("weight", 1))


def score_from_weight(earned_weight: float, total_weight: float, failed: bool) -> float:
    if total_weight == 0:
        return 0.0 if failed else 1.0
    return earned_weight / total_weight


def apply_hybrid_status(
    result: dict[str, Any],
    *,
    judge_enabled: bool,
    judge_result: dict[str, Any] | None = None,
) -> None:
    rule_passed = bool(result.get("passed", False))
    rule_score = float(result.get("score", 0.0))

    result["rule_passed"] = rule_passed
    result["rule_score"] = rule_score
    result["judge_enabled"] = judge_enabled
    result["judge_result"] = judge_result

    if not judge_enabled:
        result["final_status"] = "pass" if rule_passed else "fail"
        result["final_score"] = rule_score
        return

    if not judge_result:
        result["final_status"] = "needs_review"
        result["final_score"] = rule_score
        return

    status = judge_result.get("status")
    if status not in {"pass", "fail", "needs_review"}:
        status = "needs_review"

    result["final_status"] = status
    result["final_score"] = float(judge_result.get("score", rule_score))


def add_category_score(
    category_scores: dict[str, Any],
    category: str,
    earned: float,
    total: float,
    passed: bool,
    item_id: str,
) -> None:
    entry = category_scores.setdefault(
        category,
        {
            "earned_weight": 0.0,
            "total_weight": 0.0,
            "score": 1.0,
            "passed": True,
            "failed_ids": [],
        },
    )
    entry["earned_weight"] += earned
    entry["total_weight"] += total
    if not passed:
        entry["passed"] = False
        entry["failed_ids"].append(item_id)
    entry["score"] = score_from_weight(
        entry["earned_weight"],
        entry["total_weight"],
        failed=not entry["passed"],
    )


def merge_category_scores(
    category_scores: dict[str, Any],
    incoming_scores: dict[str, Any],
) -> None:
    for category, incoming in incoming_scores.items():
        entry = category_scores.setdefault(
            category,
            {
                "earned_weight": 0.0,
                "total_weight": 0.0,
                "score": 1.0,
                "passed": True,
                "failed_ids": [],
            },
        )
        entry["earned_weight"] += incoming.get("earned_weight", 0.0)
        entry["total_weight"] += incoming.get("total_weight", 0.0)
        if not incoming.get("passed", True):
            entry["passed"] = False
        entry["failed_ids"].extend(incoming.get("failed_ids", []) or [])
        entry["score"] = score_from_weight(
            entry["earned_weight"],
            entry["total_weight"],
            failed=not entry["passed"],
        )


def infer_state_category(claim: dict[str, Any], default: str = "legacy") -> str:
    if claim.get("category"):
        return claim["category"]
    target_field = claim.get("target_field")
    if target_field:
        return target_field
    if claim.get("required_evidence_sources"):
        return "evidence"
    return default


def infer_progress_claim_category(claim: dict[str, Any], default: str = "legacy") -> str:
    if claim.get("category"):
        return claim["category"]

    section = claim.get("target_section")
    if section == "New Confirmed Findings":
        return "progress_added_findings"
    if section == "Removed or Revised Confirmed Findings":
        return "progress_revised_or_removed_findings"
    if section == "Next Action Changes":
        return "progress_next_actions"
    if section == "Open Question Changes":
        return "progress_open_questions"
    if section == "Source Artifact Changes":
        return "progress_source_artifacts"
    return default


def infer_progress_change_category(change: dict[str, Any], change_type: str) -> str:
    if change.get("category"):
        return change["category"]
    return f"progress_{change_type}"


def numeric_failures_from_missing(missing_conditions: list[Any]) -> list[dict[str, Any]]:
    return [
        item
        for item in missing_conditions
        if isinstance(item, dict) and item.get("numeric_check_id")
    ]


def _old_claim_allowed_in_revised_section(progress: str, old_claim: str) -> bool:
    revised_section = section_text(progress, "Removed or Revised Confirmed Findings")
    if not contains_ci(progress, old_claim):
        return True
    if not contains_ci(revised_section, old_claim):
        return False

    outside_revised = progress.replace(revised_section, "", 1)
    return not contains_ci(outside_revised, old_claim)


def _change_scope(progress: str, change: dict[str, Any]) -> str:
    return get_markdown_scope(
        progress,
        section=change.get("target_section"),
        subsection=change.get("target_subsection"),
    )


def _change_failure(
    change: dict[str, Any],
    change_type: str,
    reason: str,
    missing_conditions: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "id": change.get("id", f"unnamed_{change_type}_change"),
        "change_type": change_type,
        "reason": reason,
        "missing_conditions": missing_conditions or [],
        "weight": claim_weight(change),
    }


def evaluate_expected_changes(
    progress: str,
    expected_changes: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    change_checks_passed: list[str] = []
    change_checks_failed: list[str] = []
    missing_changes: list[dict[str, Any]] = []
    misclassified_changes: list[dict[str, Any]] = []
    category_scores: dict[str, Any] = {}
    earned_weight = 0.0
    total_weight = 0.0

    for change_type in ("added", "revised", "removed", "unchanged"):
        for change in expected_changes.get(change_type, []) or []:
            change_id = change.get("id", f"unnamed_{change_type}_change")
            check_id = f"expected_change:{change_type}:{change_id}"
            weight = claim_weight(change)
            category = infer_progress_change_category(change, change_type)
            total_weight += weight
            scope = _change_scope(progress, change)

            if change_type == "added":
                matched, missing = claim_matches(scope, change)
                if matched:
                    earned_weight += weight
                    add_category_score(
                        category_scores, category, weight, weight, True, change_id
                    )
                    change_checks_passed.append(check_id)
                else:
                    add_category_score(
                        category_scores, category, 0.0, weight, False, change_id
                    )
                    change_checks_failed.append(check_id)
                    missing_changes.append(
                        _change_failure(
                            change,
                            change_type,
                            "added change not found in expected scope",
                            missing,
                        )
                    )
                continue

            if change_type == "revised":
                matched, missing = claim_matches(scope, change)
                failure_reasons: list[str] = []
                missing_conditions = list(missing)

                new_claims = change.get("new_must_claim", []) or []
                if new_claims and not any(contains_ci(scope or progress, item) for item in new_claims):
                    failure_reasons.append("new corrected claim not found")
                    missing_conditions.append(
                        "new_must_claim: " + " | ".join(str(item) for item in new_claims)
                    )

                for old_claim in change.get("old_must_not_claim", []) or []:
                    if not _old_claim_allowed_in_revised_section(progress, old_claim):
                        failure_reasons.append("old claim appears outside revised section")
                        missing_conditions.append(f"old_must_not_claim outside revised section: {old_claim}")

                if not matched:
                    new_section = section_text(progress, "New Confirmed Findings")
                    if claim_triggered(new_section, change):
                        failure_reasons.append("revised change reported as new finding")
                        misclassified_changes.append(
                            _change_failure(
                                change,
                                change_type,
                                "reported under New Confirmed Findings",
                                missing_conditions,
                            )
                        )

                if matched and not failure_reasons:
                    earned_weight += weight
                    add_category_score(
                        category_scores, category, weight, weight, True, change_id
                    )
                    change_checks_passed.append(check_id)
                else:
                    add_category_score(
                        category_scores, category, 0.0, weight, False, change_id
                    )
                    change_checks_failed.append(check_id)
                    missing_changes.append(
                        _change_failure(
                            change,
                            change_type,
                            "; ".join(failure_reasons) or "revised change not found in expected scope",
                            missing_conditions,
                        )
                    )
                continue

            if change_type == "removed":
                matched, missing = claim_matches(scope, change)
                new_section = section_text(progress, "New Confirmed Findings")
                if claim_triggered(new_section, change):
                    add_category_score(
                        category_scores, category, 0.0, weight, False, change_id
                    )
                    change_checks_failed.append(check_id)
                    failure = _change_failure(
                        change,
                        change_type,
                        "removed change reported under New Confirmed Findings",
                    )
                    missing_changes.append(failure)
                    misclassified_changes.append(failure)
                elif matched:
                    earned_weight += weight
                    add_category_score(
                        category_scores, category, weight, weight, True, change_id
                    )
                    change_checks_passed.append(check_id)
                else:
                    add_category_score(
                        category_scores, category, 0.0, weight, False, change_id
                    )
                    change_checks_failed.append(check_id)
                    missing_changes.append(
                        _change_failure(
                            change,
                            change_type,
                            "removed change not found in expected scope",
                            missing,
                        )
                    )
                continue

            if change_type == "unchanged":
                allowed_sections = set(change.get("allowed_sections", []) or [])
                bad_sections = [
                    section
                    for section in change.get("should_not_appear_in_sections", []) or []
                    if section not in allowed_sections
                    and claim_triggered(section_text(progress, section), change)
                ]

                if bad_sections:
                    add_category_score(
                        category_scores, category, 0.0, weight, False, change_id
                    )
                    change_checks_failed.append(check_id)
                    failure = _change_failure(
                        change,
                        change_type,
                        "unchanged claim appeared in progress change section",
                        [f"should_not_appear_in_sections: {section}" for section in bad_sections],
                    )
                    missing_changes.append(failure)
                    misclassified_changes.append(failure)
                else:
                    earned_weight += weight
                    add_category_score(
                        category_scores, category, weight, weight, True, change_id
                    )
                    change_checks_passed.append(check_id)

    return {
        "earned_weight": earned_weight,
        "total_weight": total_weight,
        "change_checks_passed": change_checks_passed,
        "change_checks_failed": change_checks_failed,
        "missing_changes": missing_changes,
        "misclassified_changes": misclassified_changes,
        "category_scores": category_scores,
    }
