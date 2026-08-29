# ADR 0008: Defer autonomous loops and external integrations

- Status: Accepted
- Scope: product boundary and roadmap

## Context

Autonomous agents, Slack or GitHub integrations, and persistent vector stores
could broaden PMA, but each adds authorization, synchronization, privacy,
failure-recovery, and evaluation requirements. The primary product risk remains
reliable state reconstruction and re-entry.

## Decision

Keep PMA a local, user-invoked CLI centered on checkpoint, freshness, brief,
ask, memo, and status-note workflows. Do not add autonomous execution, external
service writes, or a vector database until the existing reliability and
retrieval contracts justify that expansion.

## Consequences

PMA has a narrower feature surface and no fabricated integration story. Work is
directly initiated by the developer. Future integrations must define authority,
data retention, freshness, failure handling, and evaluation before adoption.

## Rejected alternatives

- Add an agent loop because checkpoint state already exists.
- Add external service integrations without a synchronization model.
- Add infrastructure primarily to increase feature count.

## Reliability implications

The current system can be tested and delivered as a bounded local tool without
claiming operational guarantees for external mutations or autonomous behavior.
