# ADR 0001: Use one canonical checkpoint-layout resolver

- Status: Accepted
- Scope: checkpoint readers, writers, consumers, scanner, and Git filtering

## Context

PMA supports a project-local default and named external checkpoint storage.
Independent path construction allowed writers and readers to disagree about
`latest`, history, and generated-output exclusions.

## Decision

All workflows resolve checkpoint locations through `project_layout`. Consumers
may accept an explicit latest directory; otherwise external storage requires a
complete base-output/project-name pair, with project-local storage as fallback.
Logical labels are used in artifacts instead of exposing absolute local paths.

## Consequences

Writer and reader precedence is consistent, internal generated output can be
excluded reliably, and external layouts remain testable. New storage layouts
must extend the resolver rather than add path construction in a command.

## Rejected alternatives

- Hard-code `.project_memory/latest` in every consumer.
- Maintain separate reader and writer resolution rules.
- Store absolute host paths as user-facing provenance.

## Reliability implications

A shared resolver removes a cross-module class of stale reads, missing latest
state, recursive ingestion, and environment-specific path disclosure.
