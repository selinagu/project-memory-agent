# Project Status

## Current stage

Pre-rollout validation.

## Current decision

Use bounded key-prefix invalidation instead of full-cache refresh. The bounded
policy limits refresh work to affected key groups and avoids the origin-request
spike observed with broad invalidation.

## Current result

The bounded policy passed the synthetic standard workload and remains below the
p95 latency target.

## Blocker

The high-churn mixed workload has not yet been validated.

## Next action

Run the high-churn trace and confirm that invalidation coverage remains above
the rollout guardrail.
