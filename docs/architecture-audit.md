# P2 architecture audit

This audit records the static architecture review performed before P2 changes.
It distinguishes the existing reliable boundaries from the one defect corrected
by the phase and from intentionally deferred work.

## Already aligned with the target

- `pma` parses command arguments and delegates to workflow functions; no runtime
  module depends on the CLI entry point.
- `project_layout` is the shared resolver for internal, named external, and
  explicit-latest checkpoint locations.
- Checkpoint publication and loading are separated into `checkpoint_store` and
  `checkpoint_reader` rather than implemented by query consumers.
- The scanner and Git collector receive the active resolved output root, so
  internal generated output is excluded from later evidence and fingerprints.
- Ask and memo read generated checkpoint memory and bounded SOURCE snippets;
  they do not perform arbitrary live repository retrieval.
- Freshness is deterministic and read-only. It owns current repository
  comparison instead of allowing ask or memo to imply live state.
- Runtime modules are explicitly listed in the wheel manifest, and CI exercises
  the full tests, five offline eval suites, release build, privacy scan, clean
  install smoke, and a tiny offline benchmark.

## Corrected in P2

The initial dependency audit found a two-module cycle:

```text
diff_states → semantic_diff → diff_states
```

`diff_states` used semantic-alignment models declared in `semantic_diff`, while
`semantic_diff` used a delayed import of deterministic alignment from
`diff_states`. P2 moved only the shared Pydantic data contracts into the
foundation module `alignment_models`. Both workflows now depend on the shared
models, and the runtime graph is acyclic. Existing names remain imported by
`semantic_diff`, preserving its prior module-level API.

## Accepted technical debt

- Runtime code is distributed as flat `py_modules` rather than one namespaced
  package. Packaging tests cover the current contract; migrating would add
  compatibility risk without changing the reliability boundary.
- `checkpoint` is a deliberately broad application orchestrator. Storage,
  layout, scanning, and model details remain separate even though the workflow
  coordinates all of them.
- `memo` builds on shared query and source-lookup behavior. This is an explicit
  application-layer dependency rather than duplicate retrieval logic.
- Some backward-compatible `.project_memory` wording remains in messages and
  safety fallbacks. Physical resolution still flows through `project_layout`.
- Directory replacement is rollback-safe but is not a strict cross-platform
  atomic tree switch.

## Out of scope for P2

- New commands or user workflows.
- A package-directory migration or framework-driven dependency injection.
- Incremental indexing, a vector database, or repository-wide RAG.
- Autonomous execution and Slack, GitHub, or other service integrations.
- Replacing prompt-guided semantic interpretation with a new inference system.
- Running OpenAI-backed evals or regenerating the repository checkpoint.

## Enforced architecture contract

`tests/test_architecture_boundaries.py` now fails on an unclassified runtime
module, an internal import cycle, a reverse dependency on `pma`, a higher-layer
dependency from foundation models or layout, or storage coupling to collection
and application workflows. These constraints protect durable boundaries rather
than freezing every current import.
