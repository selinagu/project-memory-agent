# ADR 0007: Keep generated claims and evaluation gold within available evidence

- Status: Accepted
- Scope: state reconstruction, ask, memo, and evaluation

## Context

An LLM can produce plausible project claims that are not supported by selected
artifacts. Evaluation can hide the same problem if gold expectations require
facts outside the fixture's evidence boundary.

## Decision

Project meaning, progress, completion, decisions, and next actions require
selected SOURCE evidence. Bounded Git metadata may support repository facts but
not semantic progress. Query and memo normalize citations and enforce field
boundaries. Public gold files may test only behavior supported or explicitly
unsupported by their checked-in inputs.

## Consequences

PMA must express missing evidence and uncertainty instead of maximizing answer
coverage. Evaluation fixtures remain synthetic, reviewable, and reproducible;
an optional LLM judge cannot override deterministic rule failures.

## Rejected alternatives

- Score plausible unsupported assertions as correct.
- Treat a changed filename or dirty repository as completion evidence.
- Allow judge output to replace deterministic evidence rules.

## Reliability implications

The same evidence policy governs product behavior and evaluation, reducing
hallucination incentives and misleading pass results.
