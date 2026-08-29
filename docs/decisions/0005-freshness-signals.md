# ADR 0005: Combine artifact manifests with bounded Git metadata for freshness

- Status: Accepted
- Scope: deterministic checkpoint freshness

## Context

A latest checkpoint can exist but no longer represent the repository. Git-only
comparison is unavailable for non-Git projects and may not cover scanner scope;
manifest-only comparison does not represent branch, HEAD, or tracked changes
outside selected text artifacts.

## Decision

Persist bounded checkpoint-time Git context and a deterministic manifest of
selected artifacts plus scanner configuration. Freshness chooses applicable
signals and returns `current`, `stale`, `unknown`, or `no_checkpoint`. Missing
legacy evidence produces `unknown` when currency cannot be proven.

## Consequences

Freshness is OpenAI-free and read-only. Git snapshots include status and
fingerprints but exclude full diffs, logs, remotes, commit subjects, and source
contents. Non-Git projects can still detect selected-file and scope changes.

## Rejected alternatives

- Infer freshness only from file modification timestamps.
- Treat the existence of `latest` as proof that it is current.
- Return current when legacy metadata cannot support comparison.

## Reliability implications

The four-state result preserves uncertainty and avoids false confidence while
keeping comparison reproducible and bounded.
