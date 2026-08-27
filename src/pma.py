import argparse
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

import checkpoint
from brief import build_brief, render_brief_text
from freshness import check_checkpoint_freshness, render_freshness_text
from memo import generate_group_update_memo, generate_self_memo
from progress_window import parse_since_date
from project_layout import CheckpointLayoutError
from query import QueryContextError, ask_project_memory
from status_note import StatusNoteError, build_status_note, write_status_note


def _add_checkpoint_location_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--latest-dir",
        help="Explicit latest checkpoint directory; relative paths resolve under --project-dir.",
    )
    parser.add_argument("--project-name", help="Checkpoint project name under --base-output-dir.")
    parser.add_argument("--base-output-dir", help="Base directory containing named checkpoint roots.")


def _checkpoint_location_kwargs(args: argparse.Namespace) -> dict[str, object]:
    return {
        "latest_dir": Path(args.latest_dir) if args.latest_dir else None,
        "project_name": args.project_name,
        "base_output_dir": Path(args.base_output_dir) if args.base_output_dir else None,
    }


def run_brief(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="pma brief",
        description="Inspect latest checkpoint health without modifying the project.",
    )
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--json", action="store_true", dest="json_output")
    _add_checkpoint_location_arguments(parser)
    args = parser.parse_args(argv)
    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        parser.error(f"Project directory does not exist or is not a directory: {project_dir}")

    try:
        result = build_brief(project_dir, **_checkpoint_location_kwargs(args))
    except CheckpointLayoutError as exc:
        parser.error(str(exc))
    if args.json_output:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=True))
    else:
        print(render_brief_text(result), end="")
    return 0


def run_freshness(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="pma freshness")
    parser.add_argument("--project-dir", default=".")
    parser.add_argument("--json", action="store_true", dest="json_output")
    _add_checkpoint_location_arguments(parser)
    args = parser.parse_args(argv)
    project_dir = Path(args.project_dir)
    if not project_dir.is_dir():
        parser.error(f"Project directory does not exist or is not a directory: {project_dir}")

    try:
        result = check_checkpoint_freshness(
            project_dir, **_checkpoint_location_kwargs(args)
        )
    except CheckpointLayoutError as exc:
        parser.error(str(exc))
    if args.json_output:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=True))
    else:
        print(render_freshness_text(result), end="")
    return 0


def run_ask(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="pma ask")
    parser.add_argument("question", help="Question about the latest checkpoint")
    parser.add_argument(
        "--project-dir",
        default=".",
        help="Tracked project directory (default: current directory)",
    )
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument(
        "--sources",
        action="store_true",
        help=(
            "Force bounded SOURCE-marker lookup. Without this flag, "
            "source lookup may still be enabled automatically for "
            "source- or evidence-related questions."
        ),
    )
    _add_checkpoint_location_arguments(parser)
    args = parser.parse_args(argv)

    try:
        answer = ask_project_memory(
            question=args.question,
            project_dir=Path(args.project_dir),
            model=args.model,
            sources=args.sources,
            **_checkpoint_location_kwargs(args),
        )
    except (CheckpointLayoutError, QueryContextError) as exc:
        parser.error(str(exc))

    print(answer)
    return 0


def run_memo(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="pma memo")
    parser.add_argument(
        "--type",
        required=True,
        dest="memo_type",
        choices=("self", "group-update"),
    )
    parser.add_argument(
        "--project-dir",
        default=".",
        help="Tracked project directory (default: current directory)",
    )
    parser.add_argument("--model", default="gpt-4.1-mini")

    window_group = parser.add_mutually_exclusive_group()
    window_group.add_argument(
        "--last",
        type=int,
        help="Use the last N checkpoint runs for a windowed group update.",
    )
    window_group.add_argument(
        "--since",
        help="Use checkpoint runs on or after YYYY-MM-DD for a group update.",
    )

    _add_checkpoint_location_arguments(parser)
    args = parser.parse_args(argv)

    generators = {
        "self": generate_self_memo,
        "group-update": generate_group_update_memo,
    }

    if args.last is not None and args.memo_type != "group-update":
        parser.error("--last is only supported for --type group-update.")
    if args.since is not None and args.memo_type != "group-update":
        parser.error("--since is only supported for --type group-update.")
    if args.last is not None and args.last <= 0:
        parser.error("--last must be a positive integer.")
    since_date = None
    if args.since is not None:
        try:
            since_date = parse_since_date(args.since)
        except ValueError:
            parser.error("--since must be a valid date in YYYY-MM-DD format.")

    try:
        kwargs = {
            "project_dir": Path(args.project_dir),
            "model": args.model,
            **_checkpoint_location_kwargs(args),
        }
        if args.memo_type == "group-update":
            kwargs["last"] = args.last
            kwargs["since"] = since_date
        memo = generators[args.memo_type](**kwargs)
    except (CheckpointLayoutError, QueryContextError) as exc:
        parser.error(str(exc))

    print(memo)
    return 0


def run_status_note(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="pma status-note")
    parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory for checkpoint lookup and default output.",
    )
    parser.add_argument(
        "--output",
        help="Status note path. Defaults to PROJECT_STATUS.md in --project-dir.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Write the note instead of printing it to stdout.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite an existing output file when used with --write.",
    )
    parser.add_argument(
        "--from-latest",
        action="store_true",
        help="Prefill from the resolved latest checkpoint when available.",
    )
    _add_checkpoint_location_arguments(parser)
    args = parser.parse_args(argv)

    if args.output and not args.write:
        parser.error("--output requires --write.")
    if args.force and not args.write:
        parser.error("--force requires --write.")
    if args.latest_dir and not args.from_latest:
        parser.error("--latest-dir requires --from-latest.")
    if (args.project_name or args.base_output_dir) and not args.from_latest:
        parser.error("Checkpoint location arguments require --from-latest.")

    project_dir = Path(args.project_dir)
    if args.output:
        requested_output = Path(args.output)
        output_path = (
            requested_output
            if requested_output.is_absolute()
            else project_dir / requested_output
        )
    else:
        output_path = project_dir / "PROJECT_STATUS.md"
    try:
        note = build_status_note(
            project_dir=project_dir,
            from_latest=args.from_latest,
            **_checkpoint_location_kwargs(args),
        )
    except CheckpointLayoutError as exc:
        parser.error(str(exc))

    if not args.write:
        print(note)
        return 0

    try:
        write_status_note(output_path, note, force=args.force)
    except StatusNoteError as exc:
        parser.error(str(exc))

    print(f"Wrote status note: {output_path}")
    return 0


def main() -> int:
    load_dotenv()
    argv = sys.argv[1:]

    if argv and argv[0] == "ask":
        return run_ask(argv[1:])
    if argv and argv[0] == "memo":
        return run_memo(argv[1:])
    if argv and argv[0] == "status-note":
        return run_status_note(argv[1:])
    if argv and argv[0] == "freshness":
        return run_freshness(argv[1:])
    if argv and argv[0] == "brief":
        return run_brief(argv[1:])

    # Preserve the existing checkpoint command-line interface.
    if argv and argv[0] == "checkpoint":
        sys.argv = [sys.argv[0], *argv[1:]]
    checkpoint.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
