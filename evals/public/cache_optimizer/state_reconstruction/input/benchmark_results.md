# Benchmark Results

| Workload | Baseline p95 latency | Windowed-LRU p95 latency |
| --- | ---: | ---: |
| small | 42ms | 31ms |
| long-context | 88ms | 97ms |

Confirmed finding: Windowed-LRU improves p95 latency on the small workload but regresses on the long-context workload.
