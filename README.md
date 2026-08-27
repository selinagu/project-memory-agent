# Project Memory Agent

Project Memory Agent is a local CLI for turning a project directory into a
structured, queryable memory checkpoint.

It scans selected artifacts from a tracked project directory, builds
deterministic parsed notes with source markers, asks an LLM to derive a
validated `ProjectState`, and stores checkpoint history in a separately
resolved output layout. You can then ask questions or generate compact re-entry
and group-update memos from the latest checkpoint.

This is the v0.1.1 code baseline: useful enough to dogfood, intentionally
small, and still explicit about its limits. The version number describes the
repository state; it does not claim that v0.1.1 has been published.

## Why it exists

Research and engineering projects often accumulate status across notes, eval
outputs, logs, and half-finished threads. The hard part is not only saving
files; it is recovering the current state:

- What is the project goal?
- What findings are confirmed versus tentative?
- What changed since the last checkpoint?
- What next actions were actually recorded?
- What evidence supports the current conclusions?

Project Memory Agent keeps that state in a structured checkpoint rather than a
chat transcript.

## Core workflow

```text
project artifacts
  -> scanner
  -> deterministic parsers
  -> combined_notes.md with SOURCE markers
  -> LLM-derived project_state.json
  -> checkpoint_summary.md and project_state_card.md
  -> progress_since_last.md
  -> pma ask / pma memo
```

The tracked project and generated checkpoint storage are separate concepts.
The backward-compatible default history layout is:

```text
.project_memory/
  latest/
  runs/<timestamp>/
```

`latest/project_state.json` is the current-state authority for query and memo
commands. Raw source artifacts are not reopened by `ask` or `memo`; evidence
comes from derived checkpoint memory and bounded SOURCE-marked snippets.

Checkpoint storage can instead be inside the project under another name or
outside it entirely. Commands resolve locations in this order:

1. An explicit `--latest-dir` for commands that consume a checkpoint.
2. A complete `--base-output-dir` and `--project-name` pair.
3. The default `<project-dir>/.project_memory` root.

Relative `--latest-dir` paths resolve under `--project-dir`, preserving the
status-note convention. Relative `--base-output-dir` paths use normal CLI
working-directory semantics. Use matching location arguments for checkpoint
generation and every command that consumes that checkpoint.

The legacy producer form remains available for compatibility:

```bash
pma checkpoint --project-dir . --output-dir ./checkpoint-artifacts
```

In legacy mode the output directory itself contains checkpoint artifacts and
does not contain `latest/` or `runs/`. Consumers read it with
`--latest-dir ./checkpoint-artifacts`. `--output-dir` cannot be combined with
the named history arguments.

## Installation

Create a Python environment and install the package in editable mode:

```bash
pip install -e .
```

For development and deterministic evals, install the optional tools:

```bash
pip install -e '.[dev]'
```

Or install runtime dependencies manually and use the development invocation:

```bash
pip install openai pydantic python-dotenv
PYTHONPATH=src python -m pma ...
```

Create a local `.env` file when using LLM-backed commands:

```text
OPENAI_API_KEY=your_api_key
```

Do not commit `.env`.

## Main commands

Create or update a checkpoint:

```bash
pma status-note --project-dir . --from-latest
pma status-note --project-dir . --from-latest --latest-dir .project_memory/latest
pma status-note --project-dir . --from-latest --write

pma checkpoint \
  --project-dir . \
  --project-name my-project \
  --base-output-dir . \
  --semantic-diff

pma freshness \
  --project-dir . \
  --project-name my-project \
  --base-output-dir .
```

Inspect checkpoint health without changing the project:

```bash
pma brief --project-dir .
pma brief --project-dir . --json

pma brief \
  --project-dir . \
  --project-name my-project \
  --base-output-dir .
```

Ask latest checkpoint memory:

```bash
pma ask "What are the confirmed findings?"
pma ask "What changed since the last checkpoint?"
pma ask --sources "What evidence supports the confirmed findings?"
```

Create a personal re-entry memo:

```bash
pma memo --type self
```

Create a latest-only group update:

```bash
pma memo --type group-update
```

Create windowed group updates:

```bash
pma memo --type group-update --last 5
pma memo --type group-update --since 2026-07-01
```

Use `--project-dir PATH` with `ask` or `memo` when you are outside the tracked
project directory. For custom storage, these commands also accept the matching
`--latest-dir` or `--base-output-dir` plus `--project-name` arguments.

`pma status-note` is a deterministic helper for maintaining checkpoint-friendly
Markdown such as `PROJECT_STATUS.md`. By default it prints a TODO template.
Pass `--from-latest` to prefill from the resolved latest checkpoint and
`--write` to write the note. Existing files are not overwritten unless
`--force` is passed. `PROJECT_STATUS.md` remains a project artifact under
`--project-dir`, even when checkpoint storage is external. Use matching layout
arguments with `--from-latest` for non-default storage.

### Checkpoint health brief

`pma brief` is a deterministic checkpoint-maintenance check, not a project
recap. It inspects the resolved latest checkpoint, reuses the existing
freshness comparison, checks whether `PROJECT_STATUS.md` was modified after the
checkpoint, and returns one maintenance recommendation. It is read-only,
OpenAI-free, does not inspect full Git diffs, and never runs checkpoint or
updates the status note. Use `--json` for the structured schema. Missing, stale,
unknown, incomplete, and invalid health outcomes are ordinary results and exit
successfully.

The two re-entry workflows remain separate:

```text
pma brief
  -> maintain the checkpoint if needed

pma memo --type self
  -> recover project content
```

Use `pma memo --type self` when you need findings, decisions, failures, open
questions, and next actions from checkpoint memory. `pma brief` intentionally
does not display those fields.

## Command semantics

| Command | Purpose | Main inputs |
|---|---|---|
| `brief` | Read-only checkpoint health and maintenance recommendation | latest completeness + freshness + status-note timing |
| `status-note` | Draft checkpoint-friendly Markdown status | optional latest checkpoint memory |
| `checkpoint` | Build latest checkpoint and history run | selected project artifacts |
| `ask` | Answer schema-aware questions | latest checkpoint memory |
| `ask --sources` | Add bounded SOURCE evidence | latest checkpoint memory + latest `combined_notes.md` snippets |
| `memo --type self` | Compact personal re-entry memo | latest checkpoint memory |
| `memo --type group-update` | Latest checkpoint group update | latest state + latest progress |
| `group-update --last N` | Last-N progress window | latest state + selected run progress files |
| `group-update --since YYYY-MM-DD` | Date-window progress update | latest state + selected run progress files |

For group-update windows, latest `ProjectState` remains the authority for
current findings, questions, and planned next actions. Historical progress
files describe the reporting period; they do not override current state.

## Repository structure

```text
src/
  checkpoint, scanner, parser, query, memo, and semantic-diff logic
evals/
  public synthetic evals and eval runners
tests/
  unit and eval-regression tests
data/examples/
  safe synthetic examples
PROJECT_STATUS.md
  current dogfooding/status record
```

Private data, generated checkpoint memory, and live eval outputs are excluded
from release scope.

## Evaluation summary

The same seven public query/memo cases are validated at multiple levels; these
are seven cases total, not 21 separate cases:

| Level | Description | Result |
|---|---|---:|
| Level 0 | Fixture rule eval over checked-in canonical outputs | 7/7 |
| Level 1 | Live-command rule eval using `pma ask` / `pma memo` | Previously 7/7; not rerun in Phase 0 |
| Level 2a | Fixture + optional LLM judge | Previously 7/7; not rerun in Phase 0 |
| Level 2b | Live-command + optional LLM judge | Previously 7/7; not rerun in Phase 0 |

Current release checks:

- Query/memo eval tests: 13 passed.
- Full test suite: 212 passed.
- Compilation passed.
- `git diff --check` passed.

See [evals/README.md](evals/README.md) for eval modes and
[PROJECT_STATUS.md](PROJECT_STATUS.md) for the current dogfooding status.

## Checkpoint scanner safety

The scanner only includes supported text-like artifact types:

- `.md`
- `.txt`
- `.log`
- `.csv`
- `.json`

It uses explicit scanner-level ignore rules rather than treating `.gitignore`
as the contract. Universal rules exclude secrets, caches, default or resolved
checkpoint output, and unsupported file types. Repository-specific scope is
declared in `pma.toml`; PMA's own configuration excludes private data,
generated eval output, and public fixture project contents that would otherwise
dominate extraction.

### Optional scanner configuration

Place an optional `pma.toml` in the project root passed to `--project-dir` to
select project-relative artifacts. Without this file, scanner behavior is
unchanged. A non-empty `include` list restricts scanning to files matching at
least one pattern; `exclude` patterns are applied afterward. An absent or empty
list adds no restriction.

```toml
[scanner]
include = ["README.md", "docs/**/*.md", "results/**/*.json"]
exclude = ["results/debug/**", "archive/**"]
```

Patterns use POSIX-style project-relative paths. `**` matches zero or more path
segments, so `docs/**/*.md` includes both `docs/overview.md` and nested Markdown
files. Configuration cannot override built-in safety ignores, and matching does
not expand the supported file types (`.md`, `.txt`, `.log`, `.csv`, and `.json`).
Malformed configuration, unknown sections, or unknown scanner keys stop the
checkpoint command before it writes checkpoint output. When the resolved
checkpoint root is inside the project, that entire generated root is excluded
before user include rules are evaluated. The `.project_memory` ignore remains
as a default/backward-compatible safety rule, but custom output names are also
excluded automatically.

### Git context

Every checkpoint run records deterministic, OpenAI-free repository metadata in
`git_context.json` and a concise rendering in `git_context.md`. These files are
stored with both the timestamped run and `latest`. Non-Git projects continue to
checkpoint normally and record an explicit unavailable state.

Git context captures only the current branch, HEAD identity, and working-tree
status categories. It does not store full diffs or summarize changes since a
previous checkpoint, and it does not yet influence `ProjectState` extraction.
For a project inside a larger repository, changed paths outside the project are
excluded and included paths are rewritten project-relative. Absolute repository
paths are never stored. Submodules may appear as changed paths, but are not
inspected recursively.

Changed Git project files are fingerprinted in `git_context.json` using their
current byte size and SHA-256 digest. Missing files and directories are recorded
without contents; symbolic links hash the encoded link-target text and are not
followed. Fingerprints cover Git-reported changes independently of scanner
extensions and `pma.toml` rules. PMA stores neither file contents nor full diffs.
The resolved generated checkpoint root is excluded from changed paths and
fingerprints whenever it lies inside the tracked project. The default
`.project_memory` path remains excluded for backward compatibility. External
storage has no effect on project Git filtering.

### Checkpoint freshness

Check whether the latest checkpoint still matches the current Git state:

```bash
pma freshness --project-dir .
pma freshness --project-dir . --json

pma freshness \
  --project-dir ./research-project \
  --base-output-dir ./pma-data \
  --project-name experiment-a
```

The deterministic, OpenAI-free command reports `current`, `stale`, `unknown`,
or `no_checkpoint`. It compares repository availability, HEAD, branch/detached
state, changed-path status categories, and schema-v2 file fingerprints. A clean
schema-v1 checkpoint can still be confirmed current, while a dirty schema-v1
checkpoint is `unknown` unless another signal proves it stale. Unhashable
directory-like changes are also treated conservatively as `unknown`.

Freshness checks are read-only: they do not update the checkpoint, create a run,
capture full diffs, or summarize changes since a prior commit. All four ordinary
freshness states exit with status code 0; use the human output or JSON `status`
field when scripting.

## Limitations

- This is a local CLI prototype, not a web app or autonomous agent.
- LLM extraction, live evals, semantic diff, and judge mode can vary by run.
- `ask` and `memo` answer from derived checkpoint memory, not arbitrary raw
  artifact retrieval.
- There is no vector database or broad RAG layer.
- The scanner does not parse `.py` source files directly in v0.1.
- `status-note` exists because checkpoint scanning reads text artifacts and
  does not infer every important milestone directly from source code changes.
- The optional query/memo judge is not default, does not read full fixture
  checkpoint context by default, and cannot override rule failures.
- Windowed group-update conflict handling is prompt-guided rather than a
  deterministic conflict detector.

## Development checks

```bash
pip install -e '.[dev]'
PYTHONPATH=src python -m unittest discover -s tests -q
PYTHONPATH=src python -m pytest -q
python -m compileall -q src tests evals/scripts
git diff --check
```
