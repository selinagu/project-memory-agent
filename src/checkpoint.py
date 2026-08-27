import argparse
import json
import shutil
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from artifacts import ParsedArtifactBundle
from diff_states import render_progress_since_last
from git_context import collect_git_context, write_git_context
from scan_project import scan_project
from scanner_config import ScannerConfigError, load_scanner_config
from parsers import parse_artifacts
from project_layout import CheckpointLayoutError, logical_path, resolve_checkpoint_layout
from extract_state import extract_state
from render_card import render_project_state_card
from render_checkpoint_summary import render_checkpoint_summary
from schemas import ProjectState
from semantic_diff import run_semantic_diff_workflow
from checkpoint_reader import load_checkpoint


def build_combined_notes(parsed_artifacts: ParsedArtifactBundle) -> str:
    sections = []

    for artifact in parsed_artifacts.artifacts:
        sections.append(
            f"<!-- SOURCE: {artifact.path} -->\n"
            f"# Artifact: {artifact.path}\n\n"
            f"{artifact.content_for_llm.strip()}\n"
        )

    return "\n\n---\n\n".join(sections)


def generate_checkpoint_outputs(
    project_dir: Path,
    output_dir: Path,
    model: str,
    *,
    checkpoint_root: Path,
) -> tuple[ProjectState, ParsedArtifactBundle]:
    project_dir = project_dir.resolve()
    checkpoint_root = checkpoint_root.resolve()
    scanner_config = load_scanner_config(project_dir)
    git_context = collect_git_context(
        project_dir,
        checkpoint_root=checkpoint_root,
    )
    artifact_index = scan_project(
        project_dir,
        scanner_config,
        checkpoint_root=checkpoint_root,
    )

    # 1. Configuration is validated by scanning before any checkpoint output is created.
    output_dir.mkdir(parents=True, exist_ok=True)

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

    # Git context is deterministic checkpoint metadata, not LLM input.
    write_git_context(git_context, output_dir)

    print(f"Artifacts found: {len(artifact_index.artifacts)}")
    print(f"Output dir: {output_dir}")
    print(f"Parsed artifacts: {parsed_artifacts_path}")
    print(f"Project state: {project_state_path}")
    print(f"Project state card: {card_path}")
    print(f"Checkpoint summary: {checkpoint_summary_path}")
    print(f"Git context: {output_dir / 'git_context.json'}")

    return state, parsed_artifacts


def write_checkpoint_outputs(
    project_dir: Path,
    output_dir: Path,
    model: str,
) -> tuple[ProjectState, ParsedArtifactBundle]:
    """Compatibility wrapper for the original direct-output checkpoint API."""
    return generate_checkpoint_outputs(
        project_dir=project_dir,
        output_dir=output_dir,
        model=model,
        checkpoint_root=output_dir,
    )


def copy_run_to_latest(run_dir: Path, latest_dir: Path) -> None:
    if latest_dir.exists():
        shutil.rmtree(latest_dir)

    shutil.copytree(run_dir, latest_dir)


def run_checkpoint_legacy(
    project_dir: Path,
    output_dir: Path,
    model: str,
) -> None:
    """Write one checkpoint directly to ``output_dir`` without history."""
    print("Running checkpoint in legacy output-dir mode.")
    write_checkpoint_outputs(
        project_dir=project_dir,
        output_dir=output_dir,
        model=model,
    )


def run_checkpoint(
    project_dir: Path,
    project_name: str | None,
    base_output_dir: Path | None,
    model: str,
    semantic_diff: bool = False,
    semantic_diff_model: str = "gpt-4.1-mini",
) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")

    layout = resolve_checkpoint_layout(
        project_dir,
        project_name=project_name,
        base_output_dir=base_output_dir,
    )
    effective_project_name = project_name or layout.project_dir.name
    run_dir = layout.runs_dir / timestamp
    latest_dir = layout.latest_dir
    run_label = logical_path(run_dir, layout.project_dir)
    previous_checkpoint = load_checkpoint(latest_dir)

    previous_state = previous_checkpoint.state
    previous_parsed_artifacts = previous_checkpoint.parsed_artifacts

    print("Running checkpoint.")
    print(f"Project name: {effective_project_name}")
    print(f"Run dir: {run_dir}")

    new_state, new_parsed_artifacts = generate_checkpoint_outputs(
        project_dir=project_dir,
        output_dir=run_dir,
        model=model,
        checkpoint_root=layout.checkpoint_root,
    )

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
    field_alignments = None
    if semantic_diff and previous_state is not None and source_hashes_changed:
        field_alignments = run_semantic_diff_workflow(
            old_state=previous_state,
            new_state=new_state,
            model=semantic_diff_model,
            output_dir=run_dir,
            project_name=effective_project_name,
            run_label=run_label,
        )

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


def run_checkpoint_with_history(
    project_dir: Path,
    project_name: str,
    base_output_dir: Path,
    model: str,
    semantic_diff: bool = False,
    semantic_diff_model: str = "gpt-4.1-mini",
) -> None:
    """Compatibility wrapper for the original named-history API."""
    run_checkpoint(
        project_dir=project_dir,
        project_name=project_name,
        base_output_dir=base_output_dir,
        model=model,
        semantic_diff=semantic_diff,
        semantic_diff_model=semantic_diff_model,
    )


def main() -> None:
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--project-dir", required=True)
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument(
        "--output-dir",
        help="Legacy direct checkpoint artifact directory (no latest/runs history).",
    )
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

    try:
        if args.output_dir is not None:
            if args.project_name is not None or args.base_output_dir is not None:
                parser.error(
                    "--output-dir cannot be combined with --project-name or "
                    "--base-output-dir."
                )
            run_checkpoint_legacy(
                project_dir=Path(args.project_dir),
                output_dir=Path(args.output_dir),
                model=args.model,
            )
            return
        run_checkpoint(
            project_dir=Path(args.project_dir),
            project_name=args.project_name,
            base_output_dir=(
                Path(args.base_output_dir)
                if args.base_output_dir is not None
                else None
            ),
            model=args.model,
            semantic_diff=args.semantic_diff,
            semantic_diff_model=args.semantic_diff_model,
        )
    except (CheckpointLayoutError, ScannerConfigError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
