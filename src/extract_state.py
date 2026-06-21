import argparse
import json
import re
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import ValidationError

from prompts import EXTRACT_PROJECT_STATE_PROMPT
from schemas import ProjectState


SOURCE_MARKER_RE = re.compile(r"<!--\s*SOURCE:\s*(.*?)\s*-->")


def extract_json_text(text: str) -> str:
    """
    Best-effort cleanup in case the model accidentally returns markdown fences.
    The prompt asks for JSON only, but this makes the script slightly more robust.
    """
    text = text.strip()

    if text.startswith("```json"):
        text = text.removeprefix("```json").strip()
    elif text.startswith("```"):
        text = text.removeprefix("```").strip()

    if text.endswith("```"):
        text = text.removesuffix("```").strip()

    return text


def extract_source_markers(notes: str) -> list[str]:
    """
    Extract source marker paths from combined notes.

    Example marker:
    <!-- SOURCE: notes.md -->
    """
    markers = SOURCE_MARKER_RE.findall(notes)
    return [marker.strip() for marker in markers if marker.strip()]


def normalize_evidence_sources(data: dict, input_path: Path, allowed_sources: list[str]) -> None:
    """
    Keep evidence sources program-controlled without blindly overwriting useful sources.

    Behavior:
    - If SOURCE markers exist and the model uses one of them, keep it.
    - If SOURCE markers exist and there is exactly one allowed source, repair invalid/missing
      evidence source to that source.
    - If SOURCE markers exist and there are multiple allowed sources, keep valid sources;
      repair invalid/missing sources to a conservative fallback string listing allowed sources.
      This makes the problem visible instead of pretending all evidence came from one file.
    - If no SOURCE markers exist, use the input file path for missing/invalid sources.
    """
    if "evidence" not in data or not isinstance(data["evidence"], list):
        return

    fallback_source = str(input_path)

    for ev in data["evidence"]:
        if not isinstance(ev, dict):
            continue

        source = ev.get("source")

        if allowed_sources:
            if source in allowed_sources:
                continue

            if len(allowed_sources) == 1:
                ev["source"] = allowed_sources[0]
            else:
                ev["source"] = "UNKNOWN_SOURCE_REVIEW_NEEDED"
        else:
            if not source:
                ev["source"] = fallback_source


def extract_state(input_path: Path, output_path: Path, model: str) -> ProjectState:
    notes = input_path.read_text(encoding="utf-8")

    allowed_sources = extract_source_markers(notes)

    prompt = EXTRACT_PROJECT_STATE_PROMPT.format(
        source=str(input_path),
        notes=notes,
    )

    client = OpenAI()

    response = client.responses.create(
        model=model,
        input=prompt,
    )

    raw_text = response.output_text
    json_text = extract_json_text(raw_text)

    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as e:
        debug_path = output_path.with_suffix(".raw.txt")
        debug_path.write_text(raw_text, encoding="utf-8")
        raise ValueError(
            f"Model output was not valid JSON. Raw output saved to {debug_path}"
        ) from e

    normalize_evidence_sources(
        data=data,
        input_path=input_path,
        allowed_sources=allowed_sources,
    )

    try:
        state = ProjectState.model_validate(data)
    except ValidationError as e:
        debug_path = output_path.with_suffix(".invalid.json")
        debug_path.write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        raise ValueError(
            f"JSON did not match ProjectState schema. Invalid JSON saved to {debug_path}"
        ) from e

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(state.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return state


def main():
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Path to raw project notes")
    parser.add_argument("--output", required=True, help="Path to output state JSON")
    parser.add_argument("--model", default="gpt-4.1-mini")
    args = parser.parse_args()

    state = extract_state(
        input_path=Path(args.input),
        output_path=Path(args.output),
        model=args.model,
    )

    print("Extraction succeeded.")
    print(f"Project: {state.project_name}")
    print(f"Output: {args.output}")
    print(f"Confirmed findings: {len(state.confirmed_findings)}")
    print(f"Open questions: {len(state.open_questions)}")
    print(f"Next actions: {len(state.next_actions)}")


if __name__ == "__main__":
    main()
