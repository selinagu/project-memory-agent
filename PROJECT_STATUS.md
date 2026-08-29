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

The P1 scalability benchmark is complete on top of the P0 reliability
baseline. A deterministic synthetic generator now covers 25, 100, 500, 1,000,
and 2,500 total-file profiles with fixed-seed content, nested mixed artifact
types, scanner safety cases, exact byte/LOC counts, and ignored raw reports.
The offline runner measures seven stages with `time.perf_counter_ns()`,
median/p95/min/max summaries, effective scanner budgets plus fingerprint, and
peak Python-tracked allocations. It uses a deterministic fake extractor and
does not call OpenAI.

On CPython 3.12.3 under WSL, offline checkpoint p50 increased from 10.317 ms at
25 files to 394.779 ms at 2,500 files. Scan was the largest separately measured
stage; stress scan was 147.340 ms, parsing 65.739 ms, manifest hashing 29.580 ms,
and publication 29.839 ms. Peak Python allocation increased from approximately
1.20 MB to 26.05 MB. The observed curve is broadly proportional to selected
file count, so P1 did not add a speculative optimization.

The P0 reliability baseline remains complete on top of the Phase 3 Git-aware and
Phase 2 Python-aware product baseline. It adds:

- validated construction under `.building/`, immutable successful history,
  failed-run isolation, and rollback-safe `latest`/legacy replacement;
- unique UTC microsecond run IDs plus privacy-safe `run_metadata.json` stage,
  status, model, error, and size/count fields;
- configurable budgets for artifact count, non-Python file bytes, aggregate
  raw bytes, and combined-note characters, enforced before LLM extraction;
- deterministic `artifact_manifest.json` and current/stale/unknown freshness
  for non-Git projects;
- logical `"."` project paths in new checkpoint artifacts while older
  absolute-path records remain readable;
- Python 3.10–3.13 CI, five OpenAI-free deterministic eval suites, build and
  clean-install smoke, and a release privacy gate.

The earlier Phase 3 capability provides ProjectState extraction with a
separately delimited, checkpoint-time Git
metadata block. The block is capped at 4,000 characters and 50 changed paths
and excludes repository roots, commit subjects, fingerprints, file contents,
raw Git errors, remotes, logs, and full diffs.

Git metadata remains distinct from SOURCE artifacts and is not written into
`combined_notes.md`. It can support repository facts through the logical
evidence label `CHECKPOINT_METADATA: git_context.json`, but changed paths,
branch names, dirty state, and HEAD identifiers cannot prove semantic progress,
implementation, completion, tests, decisions, removals, or next actions.
Metadata-only evidence is excluded from bounded SOURCE lookup.

The Phase 2 Python extractor records bounded structural information such as imports, public
classes/functions/methods, signatures, bases, safe annotations, a short module
docstring summary, and static `__all__` names. It does not import or execute
project code and does not expose function bodies, ordinary constants, decorator
arguments, or actual default values. Successful previews retain SOURCE markers
in `combined_notes.md`; safe failures remain visible in the artifact index but
do not enter LLM context.

The clean-install pass found and fixed a packaging defect that source/editable
tests could not detect: `checkpoint_reader.py` was missing from the setuptools
module manifest, causing the installed CLI to fail at import time. A packaging
metadata regression test now requires every runtime module under `src/` to be
declared in the wheel manifest.

The status-note eval exposed and fixed a privacy issue in missing external
latest-memory reporting. Status-note drafts now use the canonical logical label
`external` instead of embedding an absolute local path.

The checked-in `.project_memory/latest` predates Git-context checkpoints and
does not contain `git_context.json`. A new live checkpoint was deliberately not
created during Phases 0 through 3 because those passes did not call OpenAI.
Until a later
approved checkpoint rerun, freshness correctly reports `no_checkpoint` for
that old snapshot.

## Current validation

- Query/memo Level 0 fixture rule eval: 7/7 pass in Phase 3.
- Earlier live-command and optional-judge runs recorded 7/7; Phase 3 did not
  rerun OpenAI-backed modes.
- These are the same 7 query/memo cases across evaluation layers, not 21
  separate cases.
- Status-note deterministic eval: 6/6 pass. This is a separate suite and is not
  included in the query/memo case count.
- Python source deterministic eval: 7/7 pass. This is also a separate suite.
- Git-aware state deterministic eval: 7/7 pass. This is a fourth separate suite.
- Reliability deterministic eval: 5/5 pass. This is a fifth separate suite.
- Full test suite: 317 passed, with 39 pytest subtests also passing.
- Query/memo eval tests: 13 passed.
- Scanner-focused regression and dogfood tests: 36 passed.
- Wheel and sdist build: passed.
- Clean wheel install and installed CLI smoke outside the repository: passed.
- Compilation passed.
- `git diff --check` passed.

PMA's default repo-self-scan now selects exactly five public project sources:
`PROJECT_STATUS.md`, `README.md`,
`benchmarks/README.md`, `data/examples/synthetic_cache_router_state.json`, and
`evals/README.md`.
Python scanning has not been enabled in PMA's own root `pma.toml`.

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

P0 adds default budgets of 500 selected artifacts, 1 MiB per non-Python file,
10 MiB total raw input, and 250,000 combined-note characters. Optional
`pma.toml` overrides must be positive integers below hard ceilings; booleans
are rejected. These failures do not call OpenAI or update `latest`.

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
resulting `ProjectState` focuses on Project Memory Agent. The current validation
results are recorded above; the old checkpoint itself has not been
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
- Missing external latest memory is described with the privacy-safe logical
  label `external`; local absolute paths are not included in the draft.

## Phase 1 scanner dogfooding

Synthetic dogfood repositories now cover root-level documents, nested
`docs`/`notes`/`research` layouts, and mixed repositories containing source,
private data, generated output, virtual environments, egg-info, and checkpoint
storage. The coverage confirms include/exclude precedence, zero-or-more `**`
matching, mandatory safety ignores, supported-extension boundaries, internal
checkpoint-root exclusion, external checkpoint isolation, deterministic order,
and invalid-configuration failure. Real private repositories were not used.

## Phase 1 release rehearsal

`evals/scripts/run_release_smoke.py` builds a wheel and source distribution in
temporary storage, installs the wheel into a clean temporary environment, and
runs the installed console entry point from outside the repository. It covers
top-level and subcommand help, `brief --json`, `freshness --json`, and a
non-writing `status-note` preview without checkpoint memory. The rehearsal does
not publish artifacts, modify release services, or call OpenAI.

## Phase 2 bounded Python source awareness

The Python extractor enforces a 262,144-byte input limit, a 4,000-character
preview limit, a 240-character module-docstring limit, at most 20 imports, 40
public top-level definitions, and 20 public methods per class. Default values
and literal annotation values render as `...`. Private and dunder definitions
are omitted by policy. Syntax, decoding, size, read, and symlink failures use
bounded error codes without source excerpts or local absolute paths.

The separate seven-case public evaluation covers module structure, class bases
and methods, sensitive-literal redaction, bounded syntax failure, default-off
behavior, opt-in include/exclude scope, and non-execution of top-level source
side effects. Additional unit coverage checks encoding cookies, parameter kinds,
deterministic symbol truncation, oversized sources, external file symlinks, and
mocked checkpoint SOURCE provenance.

## Phase 3 bounded Git-aware state reconstruction

The Phase 3 renderer accepts Git-context schema versions 1 and 2 and fails
closed for malformed or future records. Non-Git repositories, detached HEAD,
unborn repositories, missing HEAD, internal/external checkpoint layouts, and
projects nested inside larger repositories retain bounded fallback behavior.
Git metadata is persisted before OpenAI extraction begins, so deterministic
`git_context.json` and `git_context.md` survive an extraction failure.

Query and all memo modes treat metadata-derived ProjectState facts as
checkpoint-time snapshots rather than live worktree state. They do not execute
new Git commands or scan the repository; `pma freshness` remains responsible
for current deterministic comparison. The separate seven-case public eval
covers clean and dirty contexts, filename non-inference, subproject scope,
non-Git fallback, deterministic truncation, and metadata/SOURCE separation.
Phase 3 did not run OpenAI-backed live or judge evals and did not regenerate the
repository checkpoint.

## Known limitations

- Query/memo judge mode is optional and not default.
- The query/memo judge does not read full fixture checkpoint context by default.
- The query/memo judge cannot override rule failures in the first Level 2
  version.
- The scanner uses explicit allow/ignore rules rather than `.gitignore` as its
  contract.
- Python source awareness is opt-in and intentionally structural; it does not
  inspect function bodies, infer types, build call graphs, or follow imports.
- Non-Python programming languages remain unsupported.
- Git-aware semantic interpretation remains prompt-guided. Phase 3 does not
  ingest full diffs, file contents, commit history, remotes, or live repository
  state into ask or memo.
- Latest and legacy directory replacement is failure-safe with backup/rollback,
  but PMA does not claim strict cross-platform atomic visibility for directory
  trees.

## Source-grounded next actions

- Keep public examples synthetic and exclude any private/raw project data from
  release scope.
- Phase 1 release readiness was committed as `6b6d2f1`.
- Review the Phase 2 bounded-source and Phase 3 Git-metadata contracts before
  enabling them in real project configurations.
- Consider versioning the Phase 2 Python and Phase 3 Git-aware capabilities as
  v0.2.0; neither phase changed the current v0.1.1 package version.
- Decide whether author, license, and project URL metadata should be added
  before an actual package publication; Phase 1 did not invent these values.
- Regenerate the PMA repo checkpoint only after separately approving an OpenAI
  call; the existing old checkpoint still lacks `git_context.json`.
