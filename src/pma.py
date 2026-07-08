import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

import checkpoint
from memo import generate_group_update_memo, generate_self_memo
from progress_window import parse_since_date
from query import QueryContextError, ask_project_memory


def run_ask(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="pma ask")
    parser.add_argument("question", help="Question about the latest checkpoint")
    parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing .project_memory (default: current directory)",
    )
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument(
        "--sources",
        action="store_true",
        help="Use bounded SOURCE-marker snippets from combined_notes.md.",
    )
    args = parser.parse_args(argv)

    try:
        answer = ask_project_memory(
            question=args.question,
            project_dir=Path(args.project_dir),
            model=args.model,
            sources=args.sources,
        )
    except QueryContextError as exc:
        parser.error(str(exc))

    print(answer)
    return 0


def run_memo(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="pma memo")
    parser.add_argument("--type", required=True, dest="memo_type")
    parser.add_argument(
        "--project-dir",
        default=".",
        help="Project directory containing .project_memory (default: current directory)",
    )
    parser.add_argument("--model", default="gpt-4.1-mini")
    parser.add_argument(
        "--last",
        type=int,
        help="Use the last N checkpoint runs for a windowed group update.",
    )
    parser.add_argument(
        "--since",
        help="Use checkpoint runs on or after YYYY-MM-DD for a group update.",
    )
    args = parser.parse_args(argv)

    generators = {
        "self": generate_self_memo,
        "group-update": generate_group_update_memo,
    }
    if args.memo_type not in generators:
        parser.error(
            f"Unsupported memo type: {args.memo_type}. "
            "Currently supported types: self, group-update."
        )
    if args.last is not None and args.memo_type != "group-update":
        parser.error("--last is only supported for --type group-update.")
    if args.since is not None and args.memo_type != "group-update":
        parser.error("--since is only supported for --type group-update.")
    if args.last is not None and args.since is not None:
        parser.error("--last and --since are mutually exclusive.")
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
        }
        if args.memo_type == "group-update":
            kwargs["last"] = args.last
            kwargs["since"] = since_date
        memo = generators[args.memo_type](**kwargs)
    except QueryContextError as exc:
        parser.error(str(exc))

    print(memo)
    return 0


def main() -> int:
    load_dotenv()
    argv = sys.argv[1:]

    if argv and argv[0] == "ask":
        return run_ask(argv[1:])
    if argv and argv[0] == "memo":
        return run_memo(argv[1:])

    # Preserve the existing checkpoint command-line interface.
    if argv and argv[0] == "checkpoint":
        sys.argv = [sys.argv[0], *argv[1:]]
    checkpoint.main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
