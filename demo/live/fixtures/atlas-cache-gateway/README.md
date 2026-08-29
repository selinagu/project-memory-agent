# Atlas Cache Gateway

Atlas Cache Gateway is a synthetic service used to evaluate cache invalidation
policies before a guarded rollout. The fixture is public and contains no
production or private-project data.

## Goal

Reduce unnecessary origin refresh work while preserving cache coherence.

## Success criteria

- p95 invalidation latency must be at most 55 ms.
- Invalidation coverage must remain at or above 99.9 percent.
- Origin request volume must increase by no more than 10 percent.
- The high-churn mixed workload must pass before rollout.
