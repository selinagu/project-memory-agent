from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from evals.scripts.check_release_privacy import scan_release_paths
from scan_project import scan_project


LIVE_ROOT = Path(__file__).resolve().parent
BASE_FIXTURE = LIVE_ROOT / "fixtures" / "atlas-cache-gateway"
UPDATE_FIXTURE = LIVE_ROOT / "fixtures" / "updates" / "PROJECT_STATUS.md"
GOLD_PATH = LIVE_ROOT / "gold.yaml"
EXPECTED_ARTIFACTS = (
    "PROJECT_STATUS.md",
    "README.md",
    "benchmark_results.json",
    "failure_analysis.md",
    "next_steps.md",
)


class FixtureValidationError(RuntimeError):
    """Raised when the public live-demo fixture violates its contract."""


def load_gold() -> dict[str, Any]:
    value = yaml.safe_load(GOLD_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise FixtureValidationError("gold.yaml must contain one mapping")
    return value


def _source_contract(gold: dict[str, Any]) -> tuple[set[str], set[str]]:
    contract = gold.get("ask", {})
    allowed = contract.get("allowed_sources")
    groups = contract.get("required_source_groups")
    minimum = contract.get("minimum_distinct_sources")
    evidence_groups = contract.get("required_evidence_groups")

    if not isinstance(allowed, list) or not allowed or not all(
        isinstance(item, str) and item for item in allowed
    ):
        raise FixtureValidationError("ask.allowed_sources must be a non-empty string list")
    if len(set(allowed)) != len(allowed):
        raise FixtureValidationError("ask.allowed_sources must not contain duplicates")
    allowed_set = set(allowed)
    if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum <= 0:
        raise FixtureValidationError("ask.minimum_distinct_sources must be positive")
    if minimum > len(allowed_set):
        raise FixtureValidationError(
            "ask.minimum_distinct_sources exceeds allowed source count"
        )
    if not isinstance(groups, list) or not groups:
        raise FixtureValidationError("ask.required_source_groups must be non-empty")

    candidates: set[str] = set()
    for group in groups:
        if not isinstance(group, dict):
            raise FixtureValidationError("each ask source group must be a mapping")
        any_of = group.get("any_of")
        if not isinstance(any_of, list) or not any_of or not all(
            isinstance(item, str) and item for item in any_of
        ):
            raise FixtureValidationError("each ask source group needs non-empty any_of")
        group_sources = set(any_of)
        if not group_sources <= allowed_set:
            raise FixtureValidationError("ask source-group candidates must be allowed")
        candidates.update(group_sources)

    if not isinstance(evidence_groups, list) or not evidence_groups:
        raise FixtureValidationError("ask.required_evidence_groups must be non-empty")
    for group in evidence_groups:
        if not isinstance(group, dict):
            raise FixtureValidationError("each ask evidence group must be a mapping")
        any_of = group.get("any_of")
        if not isinstance(any_of, list) or not any_of or not all(
            isinstance(item, (str, int, float)) and not isinstance(item, bool)
            for item in any_of
        ):
            raise FixtureValidationError(
                "each ask evidence group needs a non-empty scalar any_of"
            )
    return allowed_set, candidates


def validate_fixture() -> dict[str, object]:
    missing = [name for name in EXPECTED_ARTIFACTS if not (BASE_FIXTURE / name).is_file()]
    if missing or not UPDATE_FIXTURE.is_file() or not GOLD_PATH.is_file():
        raise FixtureValidationError("required live-demo files are missing")

    json.loads((BASE_FIXTURE / "benchmark_results.json").read_text(encoding="utf-8"))
    gold = load_gold()
    artifacts = tuple(item.path for item in scan_project(BASE_FIXTURE).artifacts)
    if artifacts != EXPECTED_ARTIFACTS:
        raise FixtureValidationError(f"unexpected scanner selection: {artifacts}")

    allowed_sources, source_candidates = _source_contract(gold)
    if any(source not in artifacts for source in allowed_sources):
        raise FixtureValidationError("gold allows a source outside scanner evidence")
    if source_candidates != allowed_sources:
        raise FixtureValidationError(
            "every allowed ask source must be an anchor or source-group candidate"
        )

    for check in gold.get("evidence_checks", []):
        source = str(check["source"])
        text = (BASE_FIXTURE / source).read_text(encoding="utf-8").casefold()
        for phrase in check.get("contains", []):
            if str(phrase).casefold() not in text:
                raise FixtureValidationError(f"gold evidence phrase is missing from {source}")

    base_status = (BASE_FIXTURE / "PROJECT_STATUS.md").read_text(encoding="utf-8")
    update_status = UPDATE_FIXTURE.read_text(encoding="utf-8")
    if base_status == update_status:
        raise FixtureValidationError("update fixture must change PROJECT_STATUS.md")
    all_base_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(BASE_FIXTURE.iterdir())
        if path.is_file()
    ).casefold()
    for section in ("memo", "ask"):
        for claim in gold.get(section, {}).get("forbidden_claims", []):
            if str(claim).casefold() in all_base_text:
                raise FixtureValidationError("a forbidden claim appears in base evidence")

    findings = scan_release_paths([BASE_FIXTURE, UPDATE_FIXTURE, GOLD_PATH])
    if findings:
        raise FixtureValidationError("privacy scan found unsafe fixture content")

    return {
        "artifact_count": len(artifacts),
        "gold_source_candidate_count": len(allowed_sources),
        "update_changes_status": True,
        "privacy_findings": 0,
    }


def main() -> int:
    try:
        report = validate_fixture()
    except (FixtureValidationError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"Live demo fixture: FAIL ({exc})", file=sys.stderr)
        return 1
    print("Live demo fixture: PASS")
    print(f"Artifacts: {report['artifact_count']}")
    print(f"Gold source candidates: {report['gold_source_candidate_count']}")
    print("Update changes project status: yes")
    print("Privacy findings: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
