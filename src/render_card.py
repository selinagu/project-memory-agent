import argparse
import json
from pathlib import Path

from schemas import ProjectState


def bullet_list(items: list[str]) -> str:
    if not items:
        return "- None"
    return "\n".join(f"- {item}" for item in items)


def render_project_state_card(state: ProjectState) -> str:
    evidence_lines = []
    if state.evidence:
        for ev in state.evidence:
            evidence_lines.append(f"- `{ev.source}`: {ev.quote_or_summary}")
    else:
        evidence_lines.append("- None")

    last_updated = state.last_updated if state.last_updated else "Not specified"

    return f"""# Project State Card: {state.project_name}

## One-sentence Summary

{state.one_sentence_summary}

## Goal

{state.goal}

## Current Stage

{state.current_stage}

## Confirmed Findings

{bullet_list(state.confirmed_findings)}

## Tentative Hypotheses

{bullet_list(state.tentative_hypotheses)}

## Important Decisions

{bullet_list(state.important_decisions)}

## Failed / Blocked Attempts

{bullet_list(state.failed_attempts)}

## Open Questions

{bullet_list(state.open_questions)}

## Next Actions

{bullet_list(state.next_actions)}

## Evidence

{chr(10).join(evidence_lines)}

## Last Updated

{last_updated}
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True, help="Path to ProjectState JSON")
    parser.add_argument("--output", help="Path to output markdown card")
    args = parser.parse_args()

    state_path = Path(args.state)
    data = json.loads(state_path.read_text(encoding="utf-8"))
    state = ProjectState.model_validate(data)

    card = render_project_state_card(state)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(card, encoding="utf-8")
        print(f"Card written to {output_path}")
    else:
        print(card)


if __name__ == "__main__":
    main()
