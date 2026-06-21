import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from artifacts import ParsedArtifactBundle
from scan_project import scan_project
from parsers import parse_artifacts
from extract_state import extract_state
from render_card import render_project_state_card
from render_checkpoint_summary import render_checkpoint_summary
from schemas import ProjectState


def build_combined_notes(parsed_artifacts: ParsedArtifactBundle) -> str:
    sections = []

    for artifact in parsed_artifacts.artifacts:
        sections.append(
            f"<!-- SOURCE: {artifact.path} -->\n"
            f"# Artifact: {artifact.path}\n\n"
            f"{artifact.content_for_llm.strip()}\n"
        )

    return "\n\n---\n\n".join(sections)


def write_checkpoint_outputs(project_dir: Path, output_dir: Path, model: str) -> None:
    project_dir = project_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    # 1. Scan artifacts
    artifact_index = scan_project(project_dir)

    artifacts_index_path = output_dir / "artifacts_index.json"
    artifacts_index_path.write_text(
        json.dumps(artifact_index.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    # 2. Parse artifacts and build combined notes
    parsed_artifacts = parse_artifacts(project_dir, artifact_index)

    parsed_artifacts_path = output_dir / "parsed_artifacts.json"
    parsed_artifacts_path.write_text(
        json.dumps(parsed_artifacts.model_dump(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    combined_notes = build_combined_notes(parsed_artifacts)

    combined_notes_path = output_dir / "combined_notes.md"
    combined_notes_path.write_text(combined_notes, encoding="utf-8")

    # 3. Extract ProjectState
    project_state_path = output_dir / "project_state.json"
    state: ProjectState = extract_state(
        input_path=combined_notes_path,
        output_path=project_state_path,
        model=model,
    )

    # 4. Render Project State Card
    card = render_project_state_card(state)
    card_path = output_dir / "project_state_card.md"
    card_path.write_text(card, encoding="utf-8")

    # 5. Render Checkpoint Summary
    checkpoint_summary = render_checkpoint_summary(
        state=state,
        artifact_index=artifact_index,
    )
    checkpoint_summary_path = output_dir / "checkpoint_summary.md"
    checkpoint_summary_path.write_text(checkpoint_summary, encoding="utf-8")

    print(f"Artifacts found: {len(artifact_index.artifacts)}")
    print(f"Output dir: {output_dir}")
    print(f"Parsed artifacts: {parsed_artifacts_path}")
    print(f"Project state: {project_state_path}")
    print(f"Project state card: {card_path}")
    print(f"Checkpoint summary: {checkpoint_summary_path}")


def copy_run_to_latest(run_dir: Path, latest_dir: Path) -> None:
    if latest_dir.exists():
        shutil.rmtree(latest_dir)

    shutil.copytree(run_dir, latest_dir)


def run_checkpoint_legacy(project_dir: Path, output_dir: Path, model: str) -> None:
    print("Running checkpoint in legacy output-dir mode.")
    write_checkpoint_outputs(
        project_dir=project_dir,
        output_dir=output_dir,
        model=model,
    )


def run_checkpoint_with_history(
    project_dir: Path,
    project_name: str,
    base_output_dir: Path,
    model: str,
) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    project_output_dir = base_output_dir / project_name
    run_dir = project_output_dir / "runs" / timestamp
    latest_dir = project_output_dir / "latest"

    print("Running checkpoint with history.")
    print(f"Project name: {project_name}")
    print(f"Run dir: {run_dir}")

    write_checkpoint_outputs(
        project_dir=project_dir,
        output_dir=run_dir,
        model=model,
    )

    copy_run_to_latest(run_dir=run_dir, latest_dir=latest_dir)

    print(f"Latest updated: {latest_dir}")


def main():
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--model", default="gpt-4.1-mini")

    # Legacy mode:
    parser.add_argument("--output-dir")

    # History mode:
    parser.add_argument("--project-name")
    parser.add_argument("--base-output-dir")

    args = parser.parse_args()

    project_dir = Path(args.project_dir)

    if args.project_name or args.base_output_dir:
        if not args.project_name or not args.base_output_dir:
            raise ValueError(
                "History mode requires both --project-name and --base-output-dir."
            )

        run_checkpoint_with_history(
            project_dir=project_dir,
            project_name=args.project_name,
            base_output_dir=Path(args.base_output_dir),
            model=args.model,
        )
        return

    if not args.output_dir:
        raise ValueError(
            "Either use legacy mode with --output-dir, or history mode with "
            "--project-name and --base-output-dir."
        )

    run_checkpoint_legacy(
        project_dir=project_dir,
        output_dir=Path(args.output_dir),
        model=args.model,
    )


if __name__ == "__main__":
    main()
