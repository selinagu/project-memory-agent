from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from dataclasses import dataclass
from datetime import datetime, timezone
from io import StringIO
from pathlib import Path
import shutil
import sys
import tempfile
from types import SimpleNamespace
from typing import TextIO
from unittest.mock import patch


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from brief import build_brief
from checkpoint import run_checkpoint
from project_layout import resolve_checkpoint_layout
from query import ask_project_memory
from schemas import Evidence, ProjectState


FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "cache-service"
DEMO_MODEL = "deterministic-demo-boundary"
DEMO_QUESTION = "What evidence supports the bounded invalidation design decision?"
EXPECTED_CITATION = "combined_notes.md SOURCE PROJECT_STATUS.md"
REQUIRED_CHECKPOINT_FILES = (
    "artifact_manifest.json",
    "checkpoint_summary.md",
    "combined_notes.md",
    "git_context.json",
    "parsed_artifacts.json",
    "progress_since_last.md",
    "project_state.json",
    "run_metadata.json",
)


@dataclass(frozen=True)
class DemoResult:
    checkpoint_status: str
    initial_freshness: str
    final_freshness: str
    final_recommendation: str
    answer: str
    checkpoint_files: tuple[str, ...]


class _DeterministicResponses:
    def create(self, **_: object) -> SimpleNamespace:
        return SimpleNamespace(
            output_text=(
                "Answer:\n"
                "Use bounded key-prefix invalidation instead of a full-cache refresh.\n\n"
                "Evidence:\n"
                "- PROJECT_STATUS.md records the decision and rollout rationale.\n\n"
                "Uncertainty / Missing info:\n"
                "- This offline demonstration does not make a live model call."
            )
        )


class _DeterministicClient:
    def __init__(self) -> None:
        self.responses = _DeterministicResponses()


def _extract_demo_state(
    input_path: Path,
    output_path: Path,
    model: str,
    git_context: object | None = None,
) -> ProjectState:
    del input_path, model, git_context
    state = ProjectState(
        project_name="Synthetic Cache Service",
        one_sentence_summary=(
            "A synthetic service is validating bounded cache invalidation before rollout."
        ),
        goal="Reduce unnecessary cache refresh work without missing affected keys.",
        current_stage="Validation and rollout preparation",
        confirmed_findings=[
            "Bounded invalidation preserved the latency target in the synthetic benchmark."
        ],
        important_decisions=[
            "Use bounded key-prefix invalidation instead of full-cache refresh."
        ],
        open_questions=[
            "Does the bounded policy remain stable under the final mixed workload?"
        ],
        next_actions=[
            "Run the final mixed-workload validation and document the rollout guardrail."
        ],
        evidence=[
            Evidence(
                source="PROJECT_STATUS.md",
                quote_or_summary=(
                    "The project selected bounded key-prefix invalidation and recorded its "
                    "rollout rationale."
                ),
            ),
            Evidence(
                source="benchmark_results.json",
                quote_or_summary="The synthetic p95 latency remains below the target.",
            ),
        ],
        last_updated="2026-08-30",
    )
    output_path.write_text(state.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return state


def _step(stream: TextIO, number: int, label: str) -> None:
    print(f"[{number}/6] {label}", file=stream)


def execute_demo(project_dir: Path, *, stream: TextIO) -> DemoResult:
    _step(stream, 1, "Prepare a synthetic long-running project")
    print("Project: Synthetic Cache Service", file=stream)

    _step(stream, 2, "Create a deterministic checkpoint")
    with patch("checkpoint.extract_state", side_effect=_extract_demo_state):
        with redirect_stdout(StringIO()):
            run_checkpoint(
                project_dir=project_dir,
                project_name=None,
                base_output_dir=None,
                model=DEMO_MODEL,
                now_factory=lambda: datetime(2026, 8, 30, 0, 0, tzinfo=timezone.utc),
                suffix_factory=lambda: "demo",
            )

    layout = resolve_checkpoint_layout(project_dir)
    checkpoint_files = tuple(
        name for name in REQUIRED_CHECKPOINT_FILES if (layout.latest_dir / name).is_file()
    )
    if checkpoint_files != REQUIRED_CHECKPOINT_FILES:
        missing = sorted(set(REQUIRED_CHECKPOINT_FILES) - set(checkpoint_files))
        raise RuntimeError(f"offline checkpoint is incomplete: {', '.join(missing)}")
    print(f"Checkpoint: complete ({len(checkpoint_files)} required artifacts)", file=stream)

    _step(stream, 3, "Verify memory health with brief")
    initial_brief = build_brief(
        project_dir,
        checked_at="2026-08-30T08:01:00+00:00",
    )
    print(
        "Brief: "
        f"checkpoint={initial_brief.checkpoint.status}, "
        f"freshness={initial_brief.freshness.status}",
        file=stream,
    )
    if initial_brief.checkpoint.status != "available":
        raise RuntimeError("offline checkpoint did not pass brief health validation")
    if initial_brief.freshness.status != "current":
        raise RuntimeError("new offline checkpoint was not current")

    _step(stream, 4, "Ask a source-grounded design question")
    answer = ask_project_memory(
        DEMO_QUESTION,
        project_dir,
        DEMO_MODEL,
        client=_DeterministicClient(),
        sources=True,
    )
    if EXPECTED_CITATION not in answer:
        raise RuntimeError("offline answer did not preserve the expected SOURCE citation")
    print("Question: What design choice controls cache invalidation?", file=stream)
    for line in answer.splitlines():
        if line.strip():
            print(line, file=stream)

    _step(stream, 5, "Simulate new project work")
    status_path = project_dir / "PROJECT_STATUS.md"
    with status_path.open("a", encoding="utf-8") as status_file:
        status_file.write(
            "\n## Work after checkpoint\n"
            "The mixed-workload validation now needs to be rerun before rollout.\n"
        )
    print("Changed source: PROJECT_STATUS.md", file=stream)

    _step(stream, 6, "Detect stale memory with freshness and brief")
    final_brief = build_brief(
        project_dir,
        checked_at="2026-08-30T08:02:00+00:00",
    )
    print(f"Freshness: {final_brief.freshness.status}", file=stream)
    print(f"Recommendation: {final_brief.recommendation.message}", file=stream)
    if final_brief.freshness.status != "stale":
        raise RuntimeError("source change did not make the checkpoint stale")
    replacement_recommendations = {
        "run_checkpoint",
        "create_status_note_then_checkpoint",
        "update_status_note_then_checkpoint",
    }
    if final_brief.recommendation.code not in replacement_recommendations:
        raise RuntimeError("brief did not recommend a replacement checkpoint")

    print("", file=stream)
    print(
        "Boundary note: deterministic responses are injected only at the LLM boundary.",
        file=stream,
    )
    print(
        "Scanner, checkpoint storage, bounded lookup, brief, and freshness are real PMA workflows.",
        file=stream,
    )

    return DemoResult(
        checkpoint_status=initial_brief.checkpoint.status,
        initial_freshness=initial_brief.freshness.status,
        final_freshness=final_brief.freshness.status,
        final_recommendation=final_brief.recommendation.code,
        answer=answer,
        checkpoint_files=checkpoint_files,
    )


def run_demo(
    *,
    stream: TextIO = sys.stdout,
    temp_parent: Path | None = None,
) -> DemoResult:
    with tempfile.TemporaryDirectory(prefix="pma-offline-demo-", dir=temp_parent) as temp_dir:
        project_dir = Path(temp_dir) / "cache-service"
        shutil.copytree(FIXTURE_ROOT, project_dir)
        return execute_demo(project_dir, stream=stream)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run PMA's deterministic, network-free end-to-end smoke."
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Run without pauses; retained as the explicit CI mode.",
    )
    parser.parse_args(argv)
    run_demo()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
