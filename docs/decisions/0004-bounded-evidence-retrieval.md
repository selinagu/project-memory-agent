# ADR 0004: Use bounded checkpoint evidence instead of repository-wide RAG

- Status: Accepted
- Scope: ask, memo, and source lookup

## Context

PMA is intended to recover reliable project state, not to answer arbitrary
questions over every repository file. Repository-wide retrieval would enlarge
privacy, indexing, staleness, latency, and citation-correctness risks before the
core state-recovery contract is proven.

## Decision

Ask and memo use the validated latest `ProjectState` plus bounded SOURCE
snippets derived from `combined_notes.md`. Lookup applies explicit result and
snippet limits. Git context remains separately labeled checkpoint metadata and
does not enter ordinary SOURCE retrieval.

## Consequences

Answers may decline questions that require evidence outside the checkpoint.
The evidence surface is smaller, auditable, and consistent with checkpoint
freshness. PMA does not currently require a vector database.

## Rejected alternatives

- Index every repository file by default.
- Add a vector database before establishing retrieval evaluations.
- Read arbitrary live source files during ask or memo.

## Reliability implications

Bounded lookup limits accidental disclosure, stale/live-state confusion, prompt
growth, and unsupported citations while preserving source-backed re-entry.
