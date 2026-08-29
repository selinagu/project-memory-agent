from __future__ import annotations

import argparse
from contextlib import redirect_stdout
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import tempfile
import time
import tracemalloc
from typing import Any, Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = REPO_ROOT / "src"
for import_root in (REPO_ROOT, SRC_ROOT):
    if str(import_root) not in sys.path:
        sys.path.insert(0, str(import_root))

import checkpoint
from artifact_manifest import build_artifact_manifest, scanner_config_fingerprint
from benchmarks.benchmark_models import (
    BENCHMARK_STAGE_NAMES,
    BenchmarkCaseResult,
    BenchmarkEnvironment,
    BenchmarkReport,
    RepositoryStats,
    TimingSummary,
    summarize_samples_ns,
)
from benchmarks.generate_repo import GeneratedRepository, generate_repository
from benchmarks.profiles import PROFILES, get_profile
from checkpoint_store import publish_latest, validate_successful_run
from parsers import parse_artifacts
from project_layout import resolve_checkpoint_layout
from scan_project import scan_project
from scanner_config import load_scanner_config
from schemas import ProjectState
from source_lookup import parse_source_sections, select_source_sections


FIXED_BENCHMARK_TIME = datetime(2026, 8, 30, tzinfo=timezone.utc)


def deterministic_extract_state(
    input_path: Path,
    output_path: Path,
    model: str,
    git_context=None,
) -> ProjectState:
    state = ProjectState(
        project_name="synthetic-benchmark",
        one_sentence_summary="Deterministic offline benchmark state.",
        goal="Measure PMA deterministic pipeline performance.",
        current_stage="benchmark",
        evidence=[
            {
                "source": "layer_00/group_00/artifact_00000.md",
                "quote_or_summary": "Synthetic benchmark evidence.",
            }
        ],
    )
    output_path.write_text(state.model_dump_json(indent=2), encoding="utf-8")
    return state


def _measure(
    operation: Callable[[], Any],
    *,
    warmups: int,
    repetitions: int,
) -> TimingSummary:
    for _ in range(warmups):
        operation()
    samples: list[int] = []
    for _ in range(repetitions):
        start = time.perf_counter_ns()
        operation()
        samples.append(time.perf_counter_ns() - start)
    return summarize_samples_ns(samples)


def _checkpoint_operation(
    project_dir: Path,
    storage_dir: Path,
) -> tuple[Callable[[], Path], list[Path]]:
    counter = 0
    completed_runs: list[Path] = []

    def run() -> Path:
        nonlocal counter
        counter += 1
        suffix = f"bench{counter:08d}"
        with redirect_stdout(io.StringIO()):
            checkpoint.run_checkpoint(
                project_dir=project_dir,
                project_name="benchmark",
                base_output_dir=storage_dir,
                model="deterministic-fake",
                now_factory=lambda: FIXED_BENCHMARK_TIME,
                suffix_factory=lambda: suffix,
            )
        layout = resolve_checkpoint_layout(
            project_dir,
            project_name="benchmark",
            base_output_dir=storage_dir,
        )
        run_dir = layout.runs_dir / f"2026-08-30_000000_000000_{suffix}"
        validate_successful_run(run_dir)
        validate_successful_run(layout.latest_dir)
        if layout.failed_runs_dir.exists() and any(layout.failed_runs_dir.iterdir()):
            raise RuntimeError("offline benchmark produced a failed checkpoint run")
        completed_runs.append(run_dir)
        return run_dir

    return run, completed_runs


def _peak_python_allocations(operation: Callable[[], Any]) -> int:
    tracemalloc.start()
    try:
        operation()
        _, peak = tracemalloc.get_traced_memory()
        return peak
    finally:
        tracemalloc.stop()


def benchmark_profile(
    profile_name: str,
    *,
    seed: int,
    warmups: int,
    repetitions: int,
    workspace: Path,
) -> BenchmarkCaseResult:
    if warmups < 0 or repetitions <= 0:
        raise ValueError("warmups must be non-negative and repetitions positive")
    profile = get_profile(profile_name)
    project_dir = workspace / f"project-{profile_name}"
    generated: GeneratedRepository = generate_repository(
        project_dir,
        profile,
        seed=seed,
    )
    config = load_scanner_config(project_dir)

    index = scan_project(project_dir, config)
    manifest = build_artifact_manifest(project_dir, index, config)
    parsed = parse_artifacts(project_dir, index, config)
    combined_notes = checkpoint.build_combined_notes(
        parsed,
        max_chars=config.max_combined_notes_chars,
    )
    sections = parse_source_sections(combined_notes)
    state_json = deterministic_extract_state(
        project_dir / "unused-input",
        workspace / f"state-{profile_name}.json",
        "deterministic-fake",
    ).model_dump_json()

    timings: dict[str, TimingSummary] = {}
    timings["scan"] = _measure(
        lambda: scan_project(project_dir, config),
        warmups=warmups,
        repetitions=repetitions,
    )
    timings["manifest"] = _measure(
        lambda: build_artifact_manifest(project_dir, index, config),
        warmups=warmups,
        repetitions=repetitions,
    )
    timings["parse"] = _measure(
        lambda: parse_artifacts(project_dir, index, config),
        warmups=warmups,
        repetitions=repetitions,
    )
    timings["combined_notes"] = _measure(
        lambda: checkpoint.build_combined_notes(
            parsed,
            max_chars=config.max_combined_notes_chars,
        ),
        warmups=warmups,
        repetitions=repetitions,
    )
    timings["source_lookup"] = _measure(
        lambda: select_source_sections(
            "What evidence supports the benchmark findings?",
            state_json,
            sections,
        ),
        warmups=warmups,
        repetitions=repetitions,
    )

    storage_dir = workspace / f"storage-{profile_name}"
    checkpoint_operation, completed_runs = _checkpoint_operation(
        project_dir,
        storage_dir,
    )
    original_extractor = checkpoint.extract_state
    checkpoint.extract_state = deterministic_extract_state
    try:
        timings["checkpoint_offline"] = _measure(
            checkpoint_operation,
            warmups=warmups,
            repetitions=repetitions,
        )
        publication_counter = 0

        def publication_operation() -> None:
            nonlocal publication_counter
            publication_counter += 1
            destination = (
                workspace
                / f"publication-{profile_name}"
                / f"latest-{publication_counter:08d}"
            )
            publish_latest(completed_runs[-1], destination)
            validate_successful_run(destination)

        timings["publication"] = _measure(
            publication_operation,
            warmups=warmups,
            repetitions=repetitions,
        )
        peak_python_bytes = _peak_python_allocations(checkpoint_operation)
    finally:
        checkpoint.extract_state = original_extractor

    if set(timings) != set(BENCHMARK_STAGE_NAMES):
        raise RuntimeError("benchmark runner did not measure every declared stage")
    type_counts: dict[str, int] = {}
    for artifact in index.artifacts:
        type_counts[artifact.artifact_type] = (
            type_counts.get(artifact.artifact_type, 0) + 1
        )
    repository = RepositoryStats(
        generated_files=generated.generated_files,
        selected_artifacts=len(index.artifacts),
        approximate_loc=generated.approximate_loc,
        raw_bytes=sum(artifact.size_bytes for artifact in index.artifacts),
        combined_notes_chars=len(combined_notes),
        artifact_type_counts=dict(sorted(type_counts.items())),
    )
    if repository.selected_artifacts != generated.expected_selected_artifacts:
        raise RuntimeError("scanner selection differs from the generated profile")
    if repository.raw_bytes != generated.selected_raw_bytes:
        raise RuntimeError("scanner byte count differs from the generated profile")
    if manifest["config_fingerprint"] != scanner_config_fingerprint(config):
        raise RuntimeError("manifest config fingerprint is inconsistent")

    return BenchmarkCaseResult(
        case_id=f"{profile_name}-seed-{seed}",
        profile=profile_name,
        seed=seed,
        warmups=warmups,
        repetitions=repetitions,
        scanner_config_fingerprint=manifest["config_fingerprint"],
        scanner_config={
            "include_patterns": list(config.include_patterns),
            "exclude_patterns": list(config.exclude_patterns),
            "include_python": config.include_python,
            "max_artifacts": config.max_artifacts,
            "max_non_python_file_bytes": config.max_non_python_file_bytes,
            "max_total_source_bytes": config.max_total_source_bytes,
            "max_combined_notes_chars": config.max_combined_notes_chars,
        },
        repository=repository,
        timings=timings,
        peak_python_bytes=peak_python_bytes,
    )


def render_markdown(report: BenchmarkReport) -> str:
    lines = [
        "# PMA Deterministic Benchmark",
        "",
        (
            "Offline measurements use a deterministic fake extractor. "
            "They are not LLM latency or end-to-end `pma ask` latency."
        ),
        "",
        "| Profile | Files | Selected | LOC | Raw bytes | Scan p50 ms | "
        "Offline checkpoint p50 ms | Lookup p50 ms | Peak Python bytes |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for case in report.cases:
        repository = case.repository
        lines.append(
            f"| {case.profile} | {repository.generated_files} | "
            f"{repository.selected_artifacts} | {repository.approximate_loc} | "
            f"{repository.raw_bytes} | {case.timings['scan'].median_ms:.3f} | "
            f"{case.timings['checkpoint_offline'].median_ms:.3f} | "
            f"{case.timings['source_lookup'].median_ms:.3f} | "
            f"{case.peak_python_bytes} |"
        )
    lines.extend(
        [
            "",
            "Timing clock: `time.perf_counter_ns()`.",
            (
                "Memory metric: peak Python-tracked allocations from `tracemalloc`; "
                "this is not process RSS."
            ),
            "Generated repositories are synthetic and deterministic by seed.",
            "",
        ]
    )
    return "\n".join(lines)


def run_benchmarks(
    profile_names: list[str],
    *,
    seed: int,
    warmups: int,
    repetitions: int,
    output_dir: Path,
) -> BenchmarkReport:
    if not profile_names:
        raise ValueError("at least one benchmark profile is required")
    output_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pma_benchmark_") as temp_dir:
        workspace = Path(temp_dir)
        cases = tuple(
            benchmark_profile(
                name,
                seed=seed,
                warmups=warmups,
                repetitions=repetitions,
                workspace=workspace,
            )
            for name in profile_names
        )
    report = BenchmarkReport(
        environment=BenchmarkEnvironment.current(),
        cases=cases,
    )
    (output_dir / "benchmark_results.json").write_text(
        json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_dir / "summary.md").write_text(
        render_markdown(report),
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run reproducible, OpenAI-free PMA scalability benchmarks."
    )
    parser.add_argument(
        "--profile",
        action="append",
        choices=tuple(PROFILES),
        required=True,
    )
    parser.add_argument("--seed", type=int, default=20260830)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_benchmarks(
        args.profile,
        seed=args.seed,
        warmups=args.warmups,
        repetitions=args.repetitions,
        output_dir=args.output,
    )
    for case in report.cases:
        print(
            f"{case.profile}: files={case.repository.generated_files}, "
            f"checkpoint_p50_ms={case.timings['checkpoint_offline'].median_ms:.3f}"
        )
    print(f"Results: {args.output / 'benchmark_results.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
