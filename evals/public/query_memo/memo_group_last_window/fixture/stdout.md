# Project Group Update

## TL;DR
- Routing became deterministic on the small synthetic trace set.

## Update window
- Basis: latest ProjectState plus the last 2 checkpoint progress summaries.
- Included checkpoints:
  - 2026-07-02
  - 2026-07-03

## Progress this period
- 2026-07-02: added deterministic ordering to route comparison.
- 2026-07-03: completed the small-trace stability run.

## Current status
- Goal: Stabilize routing decisions across repeated traces.
- Current stage: Validating the new trace set.

## Confirmed findings
- The revised router is deterministic on the small trace set.

## Tentative hypotheses / interpretation
- No recorded tentative hypotheses.

## Failed attempts / blockers
- No recorded failed attempts or blockers.

## Open questions
- Does determinism hold on the new traces?

## Planned next actions
- Run stability check on new traces.

## Evidence pointers
- Selected checkpoint progress summaries describe the two-run window.

## Notes / uncertainty
- Historical progress does not override latest ProjectState.
