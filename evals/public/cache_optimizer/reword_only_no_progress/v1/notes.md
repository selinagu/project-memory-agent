# Cache Optimizer Notes

Goal: reduce p95 latency in a key-value cache with Windowed-LRU.

Current stage: reviewing first benchmark results.

Windowed-LRU should be treated as workload-dependent because it helps one workload and hurts another.
