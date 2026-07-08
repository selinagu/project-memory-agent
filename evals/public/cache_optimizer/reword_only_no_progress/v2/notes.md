# Cache Optimizer Notes

Goal: use Windowed-LRU to lower p95 latency for a key-value cache.

Current stage: first-pass benchmark review.

The result is workload-dependent: the method helps the small workload but hurts the long-context workload.
