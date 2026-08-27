# Project Memory Agent Status

## Project overview and goal

Project Memory Agent is a checkpointing and query layer for project memory. It
scans selected project artifacts, derives a structured `ProjectState`, records
checkpoint-to-checkpoint progress, and exposes lightweight commands such as
`pma ask` and `pma memo` for re-entry, evidence-grounded answers, and project
updates.

The current goal is to make Project Memory Agent reliable as a repo-level memory
tool while keeping checkpoint inputs safe, scoped, and auditable.

## Current stage

Phase 0 has restored one consistent v0.1.1 code baseline across checkpoint
production and consumption. The canonical layout now provides privacy-safe
labels for default, named, internal, external, and explicit-latest storage.
Legacy direct `--output-dir` remains available without creating history, while
the default and named modes retain `latest/` plus `runs/`. PMA-specific scanner
scope is declared in the repository's `pma.toml` instead of being embedded in
universal scanner rules.

The checked-in `.project_memory/latest` predates Git-context checkpoints and
does not contain `git_context.json`. A new live checkpoint was deliberately not
created during Phase 0 because this pass did not call OpenAI. Until a later
approved checkpoint rerun, freshness correctly reports `no_checkpoint` for
that old snapshot.

## Phase 0 validation

- Level 0 fixture rule eval: 7/7 pass in Phase 0.
- Earlier live-command and optional-judge runs recorded 7/7; Phase 0 did not
  rerun OpenAI-backed modes.
- These are the same 7 query/memo cases across evaluation layers, not 21
  separate cases.
- Query/memo eval tests: 13 passed.
- Full test suite: 212 passed.
- Compilation passed.
- `git diff --check` passed.

## Scanner safety milestone

Universal scanner rules exclude `.env`, `.project_memory`, caches, virtual
environments, unsupported files, and the active resolved checkpoint root.
PMA's root `pma.toml` additionally excludes `evals/private`,
`evals/private_outputs`, generated eval output, `data/raw`, `data/projects`,
`outputs`, and public fixture project content. This keeps repository-specific
privacy and focus rules out of the reusable scanner implementation.

Repo-level checkpoint scanning also excludes public eval fixture project
contents under `evals/public/**/input/`, `evals/public/**/fixture/`,
`evals/public/**/v1/`, and `evals/public/**/v2/` while preserving project docs
and eval metadata such as `evals/README.md`.

Stage B1 adds optional scanner configuration from `<project-dir>/pma.toml`.
Projects may restrict supported artifacts with `[scanner].include` and apply
additional `[scanner].exclude` patterns. Excludes run after includes, while
built-in safety ignores and supported-extension checks remain mandatory. The
configuration uses deterministic project-relative glob matching where `**`
matches zero or more path segments. Invalid TOML, unknown configuration keys,
and invalid field types stop checkpointing before output is written.

Stage B2 adds deterministic Git context to every checkpoint as
`git_context.json` and `git_context.md`. It records the current branch, HEAD,
and project-filtered working-tree status without reading full diffs or invoking
OpenAI. Non-Git projects receive an explicit unavailable record and continue
checkpointing. Git context remains checkpoint metadata and does not yet affect
artifact scanning, `ProjectState`, semantic diff, query, memo, or status-note
behavior.

Stage B3 upgrades Git context to schema version 2 with SHA-256 fingerprints for
Git-reported changed project files and adds `pma freshness`. The read-only,
OpenAI-free command compares the latest snapshot with current repository
availability, HEAD and branch state, path-status categories, and fingerprints,
then reports `current`, `stale`, `unknown`, or `no_checkpoint`. Schema-version-1
clean snapshots remain comparable; dirty version-1 snapshots are conservative
`unknown` results unless another signal proves staleness.

Stage B4 adds `pma brief` and `pma brief --json`. It validates the three required
latest artifacts (`project_state.json`, `checkpoint_summary.md`, and
`git_context.json`), reuses B3 freshness, compares `PROJECT_STATUS.md` mtime with
the best available checkpoint timestamp, and emits one deterministic checkpoint
maintenance recommendation. Missing, incomplete, invalid, stale, unknown, and
current states are ordinary successful command outcomes. The command does not
run checkpoint, write status notes or checkpoint files, inspect full Git diffs,
call OpenAI, or expose `ProjectState` findings, questions, or next actions.

The corrective Stage B layout pass removes `.project_memory/latest` as a
universal product assumption. Checkpoint generation, freshness, brief, ask,
memo, and status-note lookup now share resolution precedence: explicit latest
directory for consumers, then a complete base-output/project-name pair, then
the backward-compatible `.project_memory` default. Scanner and Git collection
receive the active resolved checkpoint root and exclude it when it lies inside
the tracked project, preventing generated runs, latest files, and fingerprints
from contaminating future checkpoints. External storage is represented as a
logical `external` location in brief JSON rather than an absolute local path.

## Corrected checkpoint attempt

The first repo-level checkpoint completed successfully, but it extracted the
wrong project focus because public synthetic eval fixture content dominated
the scanned artifacts. That checkpoint summarized the cache optimizer fixture
instead of Project Memory Agent.

The issue was corrected by adding repository-specific scanner scope for public
fixture project content and adding this top-level `PROJECT_STATUS.md` source so
repo-level checkpointing has an explicit project-status anchor.

The corrected checkpoint rerun completed successfully with 4 scanned artifacts:
`PROJECT_STATUS.md`, `README.md`,
`data/examples/synthetic_cache_router_state.json`, and `evals/README.md`. The
resulting `ProjectState` focuses on Project Memory Agent. The current Phase 0
validation results are recorded above; the old checkpoint itself has not been
regenerated in this pass.

## Important design finding

Repo-level checkpointing must avoid treating public synthetic eval fixture
projects as primary project artifacts. Public eval fixture contents under
`evals/public/**/input/`, `evals/public/**/fixture/`,
`evals/public/**/v1/`, and `evals/public/**/v2/` can otherwise dominate
extraction and cause `ProjectState` to summarize a synthetic fixture project
instead of Project Memory Agent itself.

Major implementation and evaluation milestones should be recorded in a scanned
Markdown source before checkpointing. `pma status-note` addresses this by
generating a concise `PROJECT_STATUS.md` template or a deterministic draft from
latest checkpoint memory.

## v0.1.1 status-note milestone

v0.1.1 identifies the repository code baseline. It has not been published or
pushed as part of this work.

- Added `pma status-note`.
- The first version is deterministic and OpenAI-free.
- Without `--write`, it prints a status-note draft to stdout.
- With `--write`, it writes `PROJECT_STATUS.md` by default.
- Existing status notes are not overwritten unless `--force` is passed.
- `--from-latest` pre-fills from resolved latest `project_state.json`,
  `checkpoint_summary.md`, and `progress_since_last.md` when available; the
  `.project_memory/latest` location is only the default layout.
- If latest checkpoint memory is missing, the command still generates a TODO
  template with missing-information notes.

## Known limitations

- Query/memo judge mode is optional and not default.
- The query/memo judge does not read full fixture checkpoint context by default.
- The query/memo judge cannot override rule failures in the first Level 2
  version.
- The scanner uses explicit allow/ignore rules rather than `.gitignore` as its
  contract.
- The scanner does not parse `.py` source files directly.

## Source-grounded next actions

- Dogfood project-specific `pma.toml` include/exclude rules across repositories
  with different directory conventions.
- Keep public examples synthetic and exclude any private/raw project data from
  release scope.
- Consider adding status-note eval coverage after the deterministic v0.1.1
  command settles.
