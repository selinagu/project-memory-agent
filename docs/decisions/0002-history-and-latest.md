# ADR 0002: Separate immutable history from replaceable latest state

- Status: Accepted
- Scope: checkpoint publication and recovery

## Context

Users need both a stable current snapshot and an auditable sequence of
successful checkpoints. Writing directly into either location can expose
partial state or destroy the last usable checkpoint after a failure.

## Decision

Construct a run under an isolated building location, validate it, publish the
successful run to immutable history, and replace `latest` through the shared
transactional directory helper. Failed runs remain outside successful history.

## Consequences

Consumers have one current location while successful runs remain inspectable.
Publication requires validation, run metadata, cleanup, and rollback handling.
Directory replacement is failure-safe but is not claimed to provide strict
cross-platform atomic visibility for an entire tree.

## Rejected alternatives

- Write generated artifacts directly into `latest`.
- Keep only timestamped runs and make every consumer discover the newest one.
- Treat failed or partial runs as normal history.

## Reliability implications

The prior usable `latest` survives extraction and most publication failures,
and successful history cannot silently contain incomplete checkpoints.
