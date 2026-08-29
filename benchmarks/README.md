# PMA Scalability Benchmarks

This directory contains reproducible, OpenAI-free benchmarks for PMA's
deterministic pipeline. Generated repositories and raw benchmark reports are
not committed.

## Profiles

| Profile | Generated files | Selected artifacts | Lines per selected artifact |
|---|---:|---:|---:|
| tiny | 25 | 20 | 16 |
| small | 100 | 95 | 24 |
| medium | 500 | 495 | 30 |
| large | 1,000 | 995 | 30 |
| stress | 2,500 | 2,495 | 12 |

Each profile contains deterministic Markdown, text, JSON, CSV, log, and
opt-in Python artifacts plus five safety cases: `pma.toml`, `.env`,
`.project_memory` output, `node_modules` content, and an unsupported binary.
The latter four inputs must not be selected by the scanner. A fixed seed
reproduces paths, content, hashes, byte counts, and approximate LOC.

Stress uses fewer lines per file so it exercises file-count scaling without
exceeding the 2,000,000-character hard ceiling for combined notes. It is not a
same-LOC-density continuation of medium and large.

## Running

Install development dependencies, then choose one or more profiles:

```bash
python benchmarks/run_benchmark.py --profile tiny --profile small --profile medium --profile large --seed 20260830 --warmups 1 --repetitions 5 --output benchmarks/results/local
```

`benchmarks/results/` is ignored. The runner writes
`benchmark_results.json` and `summary.md`. Reports contain Python version,
implementation, operating-system family, and machine architecture, but not
hostname, username, project roots, environment variables, or source content.

## Measurement contract

Each timed sample uses `time.perf_counter_ns()`. Warmups are excluded, and
formal samples report minimum, median, nearest-rank p95, and maximum.

Measured stages are:

- repository scan;
- artifact-manifest hashing;
- deterministic parsing;
- combined-notes construction;
- full offline checkpoint with a deterministic fake extractor;
- validated history-to-latest publication;
- bounded local source lookup.

The full offline checkpoint includes scan, parsing, serialization, fake state
extraction, progress rendering, history publication, and latest publication.
It is not real LLM checkpoint latency. Source lookup is local bounded selection,
not end-to-end `pma ask` latency.

Peak memory is measured in a separate full checkpoint run with `tracemalloc`.
It represents peak Python-tracked allocations, not process RSS. Timings and
memory results are observational and machine-dependent; CI validates the
runner and schema but has no strict millisecond threshold.

## P1 WSL baseline

Environment: CPython 3.12.3 on Linux x86_64. Seed `20260830`, one warmup and
five measured repetitions. These results are an observational local baseline,
not a cross-machine performance guarantee.

| Profile | Files | Selected | Approx. LOC | Raw bytes | Combined chars | Scan p50 ms | Offline checkpoint p50 / p95 ms | Lookup p50 ms | Peak Python MB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| tiny | 25 | 20 | 349 | 11,896 | 14,732 | 2.297 | 10.317 / 11.350 | 0.253 | 1.20 |
| small | 100 | 95 | 2,453 | 84,747 | 97,591 | 9.725 | 28.939 / 49.196 | 1.518 | 1.76 |
| medium | 500 | 495 | 15,600 | 548,219 | 617,892 | 32.683 | 122.669 / 138.719 | 12.268 | 6.57 |
| large | 1,000 | 995 | 31,350 | 1,102,269 | 1,242,792 | 63.007 | 186.382 / 208.520 | 20.773 | 13.21 |
| stress | 2,500 | 2,495 | 33,188 | 1,122,107 | 1,476,620 | 147.340 | 394.779 / 401.174 | 23.118 | 26.05 |

Scan is the largest separately measured stage, followed by parsing. At stress,
their medians were 147.340 ms and 65.739 ms; manifest hashing was 29.580 ms and
publication was 29.839 ms. Growth is broadly proportional to selected file
count, and no product optimization was justified by this baseline alone.

The benchmark deliberately raises scanner budgets up to existing hard
ceilings. Under default limits, tiny and small fit. Medium stays under the
default 500-artifact limit but its 617,892 combined characters exceed the
default 250,000-character budget. Large and stress also exceed the default
artifact-count limit. All five remain below the 10 MiB default raw-byte budget;
stress remains below the 2,000,000-character combined-notes hard ceiling.
