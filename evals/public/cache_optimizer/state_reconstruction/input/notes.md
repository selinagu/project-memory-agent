# Cache Optimizer Notes

Goal: reduce p95 latency in a key-value cache by testing a cache eviction heuristic called Windowed-LRU.

Windowed-LRU keeps a short recency window before admitting keys into the main cache. The expectation is that one-time burst keys will be filtered out before they displace reusable items.

Current stage: benchmark interpretation after initial implementation.

The small workload looks promising, but the long-context workload is worse than baseline. We should not describe Windowed-LRU as a universal improvement.
