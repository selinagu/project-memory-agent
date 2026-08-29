from __future__ import annotations

from dataclasses import asdict, dataclass, field
import math
import platform
import sys
from typing import Any


BENCHMARK_SCHEMA_VERSION = 1
BENCHMARK_STAGE_NAMES = (
    "scan",
    "manifest",
    "parse",
    "combined_notes",
    "checkpoint_offline",
    "publication",
    "source_lookup",
)
SCANNER_CONFIG_FIELDS = {
    "include_patterns",
    "exclude_patterns",
    "include_python",
    "max_artifacts",
    "max_non_python_file_bytes",
    "max_total_source_bytes",
    "max_combined_notes_chars",
}


@dataclass(frozen=True)
class TimingSummary:
    repetitions: int
    min_ms: float
    median_ms: float
    p95_ms: float
    max_ms: float

    def __post_init__(self) -> None:
        values = (self.min_ms, self.median_ms, self.p95_ms, self.max_ms)
        if self.repetitions <= 0:
            raise ValueError("timing repetitions must be positive")
        if any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError("timing values must be finite and non-negative")
        if not self.min_ms <= self.median_ms <= self.max_ms:
            raise ValueError("timing median must fall between min and max")
        if not self.min_ms <= self.p95_ms <= self.max_ms:
            raise ValueError("timing p95 must fall between min and max")

    def to_dict(self) -> dict[str, int | float]:
        return asdict(self)


def summarize_samples_ns(samples_ns: list[int]) -> TimingSummary:
    if not samples_ns or any(type(value) is not int or value < 0 for value in samples_ns):
        raise ValueError("timing samples must be non-negative integer nanoseconds")
    ordered = sorted(samples_ns)
    count = len(ordered)
    middle = count // 2
    median_ns = (
        ordered[middle]
        if count % 2
        else (ordered[middle - 1] + ordered[middle]) / 2
    )
    p95_index = max(0, math.ceil(0.95 * count) - 1)
    to_ms = lambda value: round(value / 1_000_000, 6)
    return TimingSummary(
        repetitions=count,
        min_ms=to_ms(ordered[0]),
        median_ms=to_ms(median_ns),
        p95_ms=to_ms(ordered[p95_index]),
        max_ms=to_ms(ordered[-1]),
    )


@dataclass(frozen=True)
class BenchmarkEnvironment:
    python_version: str
    python_implementation: str
    operating_system: str
    machine_architecture: str

    @classmethod
    def current(cls) -> "BenchmarkEnvironment":
        return cls(
            python_version=".".join(str(value) for value in sys.version_info[:3]),
            python_implementation=platform.python_implementation(),
            operating_system=platform.system() or "unknown",
            machine_architecture=platform.machine() or "unknown",
        )


@dataclass(frozen=True)
class RepositoryStats:
    generated_files: int
    selected_artifacts: int
    approximate_loc: int
    raw_bytes: int
    combined_notes_chars: int
    artifact_type_counts: dict[str, int] = field(default_factory=dict)

    def __post_init__(self) -> None:
        values = (
            self.generated_files,
            self.selected_artifacts,
            self.approximate_loc,
            self.raw_bytes,
            self.combined_notes_chars,
        )
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("repository statistics must be non-negative integers")
        if any(
            not isinstance(name, str) or type(count) is not int or count < 0
            for name, count in self.artifact_type_counts.items()
        ):
            raise ValueError("artifact type counts are malformed")


@dataclass(frozen=True)
class BenchmarkCaseResult:
    case_id: str
    profile: str
    seed: int
    warmups: int
    repetitions: int
    scanner_config_fingerprint: str
    scanner_config: dict[str, Any]
    repository: RepositoryStats
    timings: dict[str, TimingSummary]
    peak_python_bytes: int
    extractor: str = "deterministic_fake"

    def __post_init__(self) -> None:
        if not self.case_id or not self.profile:
            raise ValueError("benchmark case and profile names are required")
        if type(self.seed) is not int or self.seed < 0:
            raise ValueError("benchmark seed must be a non-negative integer")
        if type(self.warmups) is not int or self.warmups < 0:
            raise ValueError("benchmark warmups must be a non-negative integer")
        if type(self.repetitions) is not int or self.repetitions <= 0:
            raise ValueError("benchmark repetitions must be positive")
        if (
            len(self.scanner_config_fingerprint) != 64
            or any(
                character not in "0123456789abcdef"
                for character in self.scanner_config_fingerprint
            )
        ):
            raise ValueError("scanner config fingerprint must be lowercase SHA-256")
        if set(self.scanner_config) != SCANNER_CONFIG_FIELDS:
            raise ValueError("benchmark scanner config snapshot is incomplete")
        if not isinstance(self.scanner_config["include_patterns"], list) or not isinstance(
            self.scanner_config["exclude_patterns"], list
        ):
            raise ValueError("benchmark scanner patterns must be lists")
        if type(self.scanner_config["include_python"]) is not bool:
            raise ValueError("benchmark Python opt-in must be boolean")
        if any(
            type(self.scanner_config[field]) is not int
            or self.scanner_config[field] <= 0
            for field in SCANNER_CONFIG_FIELDS
            if field.startswith("max_")
        ):
            raise ValueError("benchmark scanner budgets must be positive integers")
        if set(self.timings) != set(BENCHMARK_STAGE_NAMES):
            raise ValueError("benchmark timings must cover every declared stage")
        if any(value.repetitions != self.repetitions for value in self.timings.values()):
            raise ValueError("timing repetition counts must match the case")
        if type(self.peak_python_bytes) is not int or self.peak_python_bytes < 0:
            raise ValueError("peak Python bytes must be a non-negative integer")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["schema_version"] = BENCHMARK_SCHEMA_VERSION
        return value


@dataclass(frozen=True)
class BenchmarkReport:
    environment: BenchmarkEnvironment
    cases: tuple[BenchmarkCaseResult, ...]
    clock: str = "time.perf_counter_ns"
    memory_metric: str = "tracemalloc_peak_python_allocations"
    calls_openai: bool = False

    def __post_init__(self) -> None:
        if not self.cases:
            raise ValueError("benchmark report must contain at least one case")
        case_ids = [case.case_id for case in self.cases]
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("benchmark case IDs must be unique")
        if self.calls_openai:
            raise ValueError("PMA deterministic benchmarks must not call OpenAI")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": BENCHMARK_SCHEMA_VERSION,
            "environment": asdict(self.environment),
            "clock": self.clock,
            "memory_metric": self.memory_metric,
            "calls_openai": self.calls_openai,
            "cases": [case.to_dict() for case in self.cases],
        }
