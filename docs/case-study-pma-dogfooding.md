# Case study: maintaining PMA with PMA

PMA has been dogfooded against its own public repository as a maintenance and
release-readiness exercise. This case study records only behavior supported by
checked-in code, tests, project status, architecture audit, and Git history. It
does not use private project data, claim external users, or present the
synthetic offline demo as a real user session.

## Context

PMA began as a local checkpoint and query prototype. As the command set grew,
the harder problem became keeping repository inputs, generated output, storage
layouts, freshness, packaging, and evidence semantics consistent. The project
therefore used its own repository as a public dogfooding target while keeping
private/raw data and generated checkpoint memory outside release scope.

The current self-scan uses repository-specific rules in [`pma.toml`](../pma.toml).
It retains public project documentation while excluding eval fixture projects,
demo fixtures, private/raw data, generated evaluation output, benchmark reports,
and checkpoint output.

## How PMA was dogfooded

The repository-level workflow combined four kinds of evidence:

- deterministic scanner dogfood over representative repository layouts;
- public synthetic evaluation fixtures with explicit evidence boundaries;
- PMA's own `PROJECT_STATUS.md`, README, architecture, benchmark, and eval docs;
- build, clean-install, privacy, and CLI smoke checks from source distributions
  and wheels.

The checked-in PMA checkpoint was not regenerated during the recent reliability,
benchmark, or architecture passes because doing so would require separately
approved live extraction. Current status is recorded directly in
[`PROJECT_STATUS.md`](../PROJECT_STATUS.md), and the old generated checkpoint is
excluded from release scope.

## Maintenance problems discovered

### Synthetic fixture content could dominate repository state

The first repository-level checkpoint selected public eval fixture content as
ordinary project evidence and reconstructed a synthetic cache-optimizer project
instead of PMA. The correction moved repository-specific scope into `pma.toml`
and added regression coverage for scanner selection. The incident and corrected
source set are recorded under "Corrected checkpoint attempt" and "Important
design finding" in [`PROJECT_STATUS.md`](../PROJECT_STATUS.md).

### Readers and writers needed one layout model

Internal default storage, named external storage, and explicit latest-directory
consumers had developed inconsistent path assumptions. The corrective pass
centralized precedence and logical labels in
[`project_layout.py`](../src/project_layout.py), with internal/external regression
coverage in [`test_project_layout.py`](../tests/test_project_layout.py). The
design rationale is captured in
[`ADR 0001`](decisions/0001-canonical-checkpoint-layout.md).

### Generated output needed mandatory isolation

Checkpoint runs contain supported text and JSON artifacts. Without an active
output-root exclusion, later scans could treat generated summaries as new
project evidence. Scanner and Git collection now receive the canonical resolved
root, while built-in and repository-specific rules exclude generated output.
The contract is covered by [`test_scanner_dogfood.py`](../tests/test_scanner_dogfood.py)
and documented in [`ADR 0003`](decisions/0003-generated-output-isolation.md).

### External storage exposed a privacy boundary

External layouts must not change project artifact selection or leak host paths
through user-facing provenance. Layout and status-note tests require logical
labels such as `external`; the release privacy scanner rejects likely user-home
paths and credentials. See [`test_project_layout.py`](../tests/test_project_layout.py),
[`test_release_privacy.py`](../tests/test_release_privacy.py), and the P0 status
record in [`PROJECT_STATUS.md`](../PROJECT_STATUS.md).

### Editable tests missed a wheel manifest defect

The clean-install rehearsal found that `checkpoint_reader.py` had not been
declared in the setuptools module list even though editable/source tests passed.
Commit `6b6d2f1` added the release rehearsal and packaging contract; every runtime
module is now compared with the wheel manifest by
[`test_packaging_metadata.py`](../tests/test_packaging_metadata.py).

### Static architecture checks found a real dependency cycle

The P2 audit found `diff_states -> semantic_diff -> diff_states`. Shared
alignment data contracts were moved into `alignment_models`, leaving both
workflows dependent on the foundation model instead of each other. The finding
is documented in [`architecture-audit.md`](architecture-audit.md), and
[`test_architecture_boundaries.py`](../tests/test_architecture_boundaries.py)
now checks the complete runtime graph for cycles.

### Benchmarking identified the main deterministic cost

Commit `be0c2bd` added reproducible synthetic profiles and stage-level timing.
The recorded P1 baseline showed scanning as the largest separately measured
deterministic stage, followed by parsing. PMA documented the result rather than
adding an unmeasured optimization. Methodology and limitations are in
[`benchmarks/README.md`](../benchmarks/README.md).

## Corrections and design decisions

These incidents became product contracts rather than remaining informal bug
history:

- one canonical layout resolver for every reader and writer;
- immutable successful history plus rollback-safe replaceable latest state;
- mandatory generated-output isolation;
- bounded checkpoint evidence instead of live repository-wide retrieval;
- conservative four-state freshness for incomplete comparison evidence;
- source distributions tested from a clean environment;
- architecture and packaging boundaries enforced from the actual source tree.

The accepted rationale and rejected alternatives are collected in the
[`docs/decisions`](decisions/README.md) index.

## Evidence and validation

The dogfooding conclusions are backed by public regression tests and deterministic
evaluation rather than a user-count claim. Current suite totals and the five
offline eval results are recorded in [`PROJECT_STATUS.md`](../PROJECT_STATUS.md).
The CI workflow runs Python 3.10–3.13 tests, deterministic evals, an offline demo,
a synthetic benchmark smoke, release privacy checks, and clean-install smoke.

## What this case does not claim

- It does not claim external adoption, production traffic, or autonomous use.
- It does not claim that the synthetic demo is a live LLM quality evaluation.
- It does not claim that old generated checkpoints represent the current tree.
- It does not disclose or summarize private projects previously used during
  development.
- It does not claim strict cross-platform atomic visibility for directory-tree
  replacement.
