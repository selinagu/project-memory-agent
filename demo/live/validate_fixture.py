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


def validate_fixture() -> dict[str, object]:
    missing = [name for name in EXPECTED_ARTIFACTS if not (BASE_FIXTURE / name).is_file()]
    if missing or not UPDATE_FIXTURE.is_file() or not GOLD_PATH.is_file():
        raise FixtureValidationError("required live-demo files are missing")

    json.loads((BASE_FIXTURE / "benchmark_results.json").read_text(encoding="utf-8"))
    gold = load_gold()
    artifacts = tuple(item.path for item in scan_project(BASE_FIXTURE).artifacts)
    if artifacts != EXPECTED_ARTIFACTS:
        raise FixtureValidationError(f"unexpected scanner selection: {artifacts}")

    required_sources = tuple(gold.get("ask", {}).get("required_sources", []))
    if any(source not in artifacts for source in required_sources):
        raise FixtureValidationError("gold requires a source outside scanner evidence")

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
        "gold_source_count": len(required_sources),
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
    print(f"Gold sources: {report['gold_source_count']}")
    print("Update changes project status: yes")
    print("Privacy findings: 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
