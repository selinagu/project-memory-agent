# Project Memory Memo

## Snapshot
- Project: Toy Planner
- Goal: Make toy route planning deterministic and inspectable.
- Current stage: Testing validation and fallback behavior.

## What we know
- The route validator rejects disconnected plans.

## What is still tentative
- Tentative / unverified: timeouts may be caused by repeated dead-end expansion.

## Important decisions
- Keep validation separate from route generation.

## Blockers / failed attempts
- A greedy-only fallback looped on cyclic maps.

## Open questions
- Does the timeout fallback preserve deterministic output?

## Next actions
- Test the recorded timeout fallback on cyclic maps.

## Evidence pointers
- `project_state.json evidence source planner_log.md` records the validator result.

## Notes / uncertainty
- The timeout explanation remains unverified.
