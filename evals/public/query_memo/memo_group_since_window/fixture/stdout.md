# Project Group Update

## TL;DR
- Parser cleanup checks progressed while current state remained latest-authoritative.

## Update window
- Requested since date: 2026-07-01
- Included checkpoints:
  - 2026-07-01
  - 2026-07-02_120000
- Excluded unparseable run directories:
  - bad-run-name

## Progress this period
- 2026-07-01: added the compact cleanup regression fixture.
- 2026-07-02_120000: the new token branch passed the compact suite.

## Current status
- Goal: Remove obsolete parser branches safely.
- Current stage: Running cleanup regression checks.

## Confirmed findings
- The new token branch passes the compact regression suite.

## Tentative hypotheses / interpretation
- No recorded tentative hypotheses.

## Failed attempts / blockers
- No recorded failed attempts or blockers.

## Open questions
- Does the cleanup preserve legacy delimiter handling?

## Planned next actions
- Rerun parser cleanup checks on the compatibility fixture.

## Evidence pointers
- Selected checkpoint progress summaries describe the date window.

## Notes / uncertainty
- `bad-run-name` was excluded because its timestamp could not be parsed.
