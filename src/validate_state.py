import json
import argparse
from pathlib import Path

from schemas import ProjectState


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to project state JSON")
    args = parser.parse_args()

    path = Path(args.input)
    data = json.loads(path.read_text(encoding="utf-8"))

    state = ProjectState.model_validate(data)

    print("Validation passed.")
    print(f"Project: {state.project_name}")
    print(f"Confirmed findings: {len(state.confirmed_findings)}")
    print(f"Open questions: {len(state.open_questions)}")
    print(f"Next actions: {len(state.next_actions)}")


if __name__ == "__main__":
    main()
