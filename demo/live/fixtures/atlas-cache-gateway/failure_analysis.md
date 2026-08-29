# Failure Analysis

Full-cache refresh was rejected after the synthetic standard workload. The
broad policy caused overlapping refreshes for unrelated key groups, increased
origin request volume by 68 percent, and reached 91.2 ms p95 latency, above the
55 ms target.

The failure does not prove that bounded invalidation is ready for rollout. The
high-churn mixed workload remains untested.
