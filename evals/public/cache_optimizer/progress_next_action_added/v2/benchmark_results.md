# Benchmark Results

| Workload | Baseline p95 latency | Windowed-LRU p95 latency |
| --- | ---: | ---: |
| small | 42ms | 31ms |
| long-context | 88ms | 97ms |

Windowed-LRU improves the small workload and regresses on long-context.
