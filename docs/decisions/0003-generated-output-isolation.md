# ADR 0003: Exclude generated artifacts from repository ingestion

- Status: Accepted
- Scope: repository scanning and Git-context collection

## Context

Checkpoint output is text-like and can satisfy normal scanner extensions. If a
generated run is scanned again, PMA can amplify its own summaries, confuse
project evidence with output state, and grow recursively across checkpoints.

## Decision

Built-in safety rules exclude default generated directories. The active root
resolved for the current internal layout is also excluded dynamically from the
scanner and Git-context collector. External output does not alter project
artifact selection and is not exposed as source provenance.

## Consequences

Project evidence and PMA output state remain separate. Scanner configuration
cannot override mandatory safety ignores. Custom internal output paths must be
passed through the canonical layout boundary so they can be excluded.

## Rejected alternatives

- Depend only on a repository's `.gitignore`.
- Ask each user to maintain matching exclusion patterns.
- Allow generated summaries to become ordinary source evidence.

## Reliability implications

Repeated checkpoints remain bounded and do not recursively ingest runs,
`latest`, generated eval output, caches, or private checkpoint data.
