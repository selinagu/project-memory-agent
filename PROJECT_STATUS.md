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

The Query/Memo eval stack has been implemented and validated through fixture,
live-command, and optional judge layers. Repo-level checkpoint scope has been
tightened so synthetic public eval fixture projects do not dominate
`ProjectState` extraction, and the latest corrected checkpoint focuses on
Project Memory Agent itself.

## Confirmed Query/Memo eval milestone

- Level 0 fixture rule eval: 7/7 pass.
- Level 1 live-command rule eval: 7/7 pass.
- Level 2 fixture + judge: 7/7 pass.
- Level 2 live + judge: 7/7 pass.
- Query/memo eval tests: 13 passed.
- Full test suite: 85 passed for Level 2 validation.
- Later full test suite after scanner ignore changes: 90 passed.
- Latest full test suite after corrected repo-level checkpoint rerun: 92
  passed.
- Compilation passed.
- `git diff --check` passed.

## Scanner safety milestone

Checkpoint artifact scanning excludes `.env`, `.project_memory`,
`evals/private`, `evals/private_outputs`, `data/raw`, and `data/projects`.
This prevents repo-root checkpoints from sending secrets, private evals,
private outputs, previous checkpoint memory, and private/raw project notes as
checkpoint input.

Repo-level checkpoint scanning also excludes public eval fixture project
contents under `evals/public/**/input/`, `evals/public/**/fixture/`,
`evals/public/**/v1/`, and `evals/public/**/v2/` while preserving project docs
and eval metadata such as `evals/README.md`.

## Corrected checkpoint attempt

The first repo-level checkpoint completed successfully, but it extracted the
wrong project focus because public synthetic eval fixture content dominated
the scanned artifacts. That checkpoint summarized the cache optimizer fixture
instead of Project Memory Agent.

The issue was corrected by adding scanner ignores for public fixture project
content and adding this top-level `PROJECT_STATUS.md` source so repo-level
checkpointing has an explicit project-status anchor.

The corrected checkpoint rerun completed successfully with 4 scanned artifacts:
`PROJECT_STATUS.md`, `README.md`,
`data/examples/synthetic_cache_router_state.json`, and `evals/README.md`. The
resulting `ProjectState` now focuses on Project Memory Agent. Validation after
the rerun: full test suite 92 passed, compilation passed, and `git diff
--check` passed.

## Important design finding

Repo-level checkpointing must avoid treating public synthetic eval fixture
projects as primary project artifacts. Public eval fixture contents under
`evals/public/**/input/`, `evals/public/**/fixture/`,
`evals/public/**/v1/`, and `evals/public/**/v2/` can otherwise dominate
extraction and cause `ProjectState` to summarize a synthetic fixture project
instead of Project Memory Agent itself.

## Known limitations

- Query/memo judge mode is optional and not default.
- The query/memo judge does not read full fixture checkpoint context by default.
- The query/memo judge cannot override rule failures in the first Level 2
  version.
- The scanner uses explicit allow/ignore rules rather than `.gitignore` as its
  contract.
- The scanner does not parse `.py` source files directly.

## Source-grounded next actions

- Consider adding a scanner mode or scope configuration for repo-level versus
  fixture-level checkpointing.
- Add a lightweight status-note workflow so major implementation and eval
  milestones are recorded in scanned Markdown before checkpointing.
- Keep public examples synthetic and exclude any private/raw project data from
  release scope.
