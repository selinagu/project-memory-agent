import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from artifacts import ParsedArtifactBundle
from diff_states import render_progress_since_last
from scan_project import scan_project
from parsers import parse_artifacts
from extract_state import extract_state
from render_card import render_project_state_card
from render_checkpoint_summary import render_checkpoint_summary
from schemas import ProjectState
from semantic_diff import align_project_state_fields


def build_combined_notes(parsed_artifacts: ParsedArtifactBundle) -> str:
    sections = []

    for artifact in parsed_artifacts.artifacts:
        sections.append(
            f"<!-- SOURCE: {artifact.path} -->\n"
            f"# Artifact: {artifact.path}\n\n"
            f"{artifact.content_for_llm.strip()}\n"
        )

    return "\n\n---\n\n".join(sections)


def write_checkpoint_outputs(
    project_dir: Path,
    output_dir: Path,
    model: str,
) -> tuple[ProjectState, ParsedArtifactBundle]:
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

    return state, parsed_artifacts


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
    semantic_diff: bool = False,
    semantic_diff_model: str = "gpt-4.1-mini",
) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    project_output_dir = base_output_dir / project_name
    run_dir = project_output_dir / "runs" / timestamp
    latest_dir = project_output_dir / "latest"
    previous_state_path = latest_dir / "project_state.json"
    previous_parsed_artifacts_path = latest_dir / "parsed_artifacts.json"

    previous_state = None
    if previous_state_path.exists():
        previous_state = ProjectState.model_validate_json(
            previous_state_path.read_text(encoding="utf-8")
        )

    previous_parsed_artifacts = None
    if previous_parsed_artifacts_path.exists():
        previous_parsed_artifacts = ParsedArtifactBundle.model_validate_json(
            previous_parsed_artifacts_path.read_text(encoding="utf-8")
        )

    print("Running checkpoint with history.")
    print(f"Project name: {project_name}")
    print(f"Run dir: {run_dir}")

    new_state, new_parsed_artifacts = write_checkpoint_outputs(
        project_dir=project_dir,
        output_dir=run_dir,
        model=model,
    )

    field_alignments = None
    source_hashes_changed = (
        previous_parsed_artifacts is not None
        and {
            artifact.path: artifact.content_hash
            for artifact in previous_parsed_artifacts.artifacts
        }
        != {
            artifact.path: artifact.content_hash
            for artifact in new_parsed_artifacts.artifacts
        }
    )
    if semantic_diff and previous_state is not None and source_hashes_changed:
        try:
            (
                field_alignments,
                alignment_errors,
                alignment_repairs,
            ) = align_project_state_fields(
                old_state=previous_state,
                new_state=new_state,
                model=semantic_diff_model,
            )
            semantic_alignments_path = run_dir / "semantic_alignments.json"
            semantic_alignments_path.write_text(
                json.dumps(
                    {
                        "semantic_diff_model": semantic_diff_model,
                        "project_name": project_name,
                        "run_dir": str(run_dir),
                        "fallback_fields": sorted(alignment_errors),
                        "repaired_fields": sorted(alignment_repairs),
                        "repair_diagnostics": alignment_repairs,
                        "fields": {
                            field: alignment.model_dump()
                            for field, alignment in field_alignments.items()
                        },
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            print(f"Semantic diff model: {semantic_diff_model}")
            print(f"Semantic alignments: {semantic_alignments_path}")
            if alignment_errors or alignment_repairs:
                semantic_error_path = run_dir / "semantic_alignments_error.json"
                semantic_error_path.write_text(
                    json.dumps(
                        {
                            "semantic_diff_model": semantic_diff_model,
                            "project_name": project_name,
                            "run_dir": str(run_dir),
                            "fallback": (
                                "deterministic_per_field"
                                if alignment_errors
                                else "none"
                            ),
                            "field_errors": alignment_errors,
                            "field_repairs": alignment_repairs,
                            "note": (
                                "Coverage repairs preserve valid classifications "
                                "and move uncovered indexes to uncertain. Failed "
                                "fields use deterministic fallback."
                            ),
                        },
                        indent=2,
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )
                if alignment_repairs:
                    print(
                        "Semantic alignment repaired fields: "
                        f"{', '.join(sorted(alignment_repairs))}"
                    )
                if alignment_errors:
                    print(
                        "Semantic alignment field fallbacks: "
                        f"{', '.join(sorted(alignment_errors))}"
                    )
                print(f"Semantic alignment errors: {semantic_error_path}")
        except Exception as exc:
            semantic_error_path = run_dir / "semantic_alignments_error.json"
            semantic_error_path.write_text(
                json.dumps(
                    {
                        "error": str(exc),
                        "semantic_diff_model": semantic_diff_model,
                        "project_name": project_name,
                        "run_dir": str(run_dir),
                        "fallback": "deterministic",
                        "note": "Semantic alignment failed; deterministic fallback was used.",
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            print(
                "Semantic diff unavailable; using deterministic fallback: "
                f"{exc}"
            )
            print(f"Semantic alignment error: {semantic_error_path}")

    progress = render_progress_since_last(
        previous_state,
        new_state,
        previous_parsed_artifacts,
        new_parsed_artifacts,
        field_alignments,
    )
    progress_path = run_dir / "progress_since_last.md"
    progress_path.write_text(progress, encoding="utf-8")

    copy_run_to_latest(run_dir=run_dir, latest_dir=latest_dir)

    print(f"Progress since last checkpoint: {progress_path}")
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
    parser.add_argument(
        "--semantic-diff",
        action="store_true",
        help="Use an LLM to align old and new ProjectState list items.",
    )
    parser.add_argument(
        "--semantic-diff-model",
        default="gpt-4.1-mini",
        help="Model used by --semantic-diff.",
    )

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
            semantic_diff=args.semantic_diff,
            semantic_diff_model=args.semantic_diff_model,
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
