import json
import unittest

from benchmarks.benchmark_models import (
    BENCHMARK_STAGE_NAMES,
    BenchmarkCaseResult,
    BenchmarkEnvironment,
    BenchmarkReport,
    RepositoryStats,
    summarize_samples_ns,
)


class BenchmarkModelTests(unittest.TestCase):
    def case(self) -> BenchmarkCaseResult:
        timing = summarize_samples_ns([1_000_000, 2_000_000, 9_000_000])
        return BenchmarkCaseResult(
            case_id="tiny-seed-7",
            profile="tiny",
            seed=7,
            warmups=1,
            repetitions=3,
            scanner_config_fingerprint="a" * 64,
            scanner_config={
                "include_patterns": [],
                "exclude_patterns": [],
                "include_python": True,
                "max_artifacts": 500,
                "max_non_python_file_bytes": 1_048_576,
                "max_total_source_bytes": 10_485_760,
                "max_combined_notes_chars": 250_000,
            },
            repository=RepositoryStats(
                generated_files=25,
                selected_artifacts=20,
                approximate_loc=500,
                raw_bytes=10_000,
                combined_notes_chars=8_000,
                artifact_type_counts={"markdown": 20},
            ),
            timings={name: timing for name in BENCHMARK_STAGE_NAMES},
            peak_python_bytes=1024,
        )

    def test_nanosecond_summary_uses_median_and_nearest_rank_p95(self):
        result = summarize_samples_ns(
            [5_000_000, 1_000_000, 2_000_000, 4_000_000, 3_000_000]
        )
        self.assertEqual(result.min_ms, 1.0)
        self.assertEqual(result.median_ms, 3.0)
        self.assertEqual(result.p95_ms, 5.0)
        self.assertEqual(result.max_ms, 5.0)

    def test_report_is_json_serializable_and_contains_no_host_identity_or_paths(self):
        report = BenchmarkReport(
            environment=BenchmarkEnvironment(
                python_version="3.12.3",
                python_implementation="CPython",
                operating_system="Linux",
                machine_architecture="x86_64",
            ),
            cases=(self.case(),),
        )
        encoded = json.dumps(report.to_dict(), sort_keys=True)
        self.assertIn('"schema_version": 1', encoded)
        self.assertIn('"calls_openai": false', encoded)
        self.assertNotIn("hostname", encoded.lower())
        self.assertNotIn("project_dir", encoded)
        self.assertNotIn("/home/", encoded)
        self.assertNotIn("\\Users\\", encoded)

    def test_case_requires_all_stages_and_matching_repetitions(self):
        case = self.case()
        with self.assertRaisesRegex(ValueError, "every declared stage"):
            BenchmarkCaseResult(
                **{
                    **case.__dict__,
                    "timings": {"scan": case.timings["scan"]},
                }
            )

    def test_samples_reject_empty_negative_and_boolean_values(self):
        for samples in ([], [-1], [True]):
            with self.subTest(samples=samples), self.assertRaises(ValueError):
                summarize_samples_ns(samples)


if __name__ == "__main__":
    unittest.main()
