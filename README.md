# Project Memory Agent

Project Memory Agent is a local CLI for turning a project directory into a
structured, queryable memory checkpoint.

It scans selected project artifacts, builds deterministic parsed notes with
source markers, asks an LLM to derive a validated `ProjectState`, and stores
checkpoint history under `.project_memory/`. You can then ask questions or
generate compact re-entry and group-update memos from the latest checkpoint.

This is a v0.1 prototype: useful enough to dogfood, intentionally small, and
still explicit about its limits.

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

The default history layout is:

```text
.project_memory/
  latest/
  runs/<timestamp>/
```

`latest/project_state.json` is the current-state authority for query and memo
commands. Raw source artifacts are not reopened by `ask` or `memo`; evidence
comes from derived checkpoint memory and bounded SOURCE-marked snippets.

## Installation

Create a Python environment and install the package in editable mode:

```bash
pip install -e .
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
pma checkpoint \
  --project-dir . \
  --project-name my-project \
  --base-output-dir . \
  --semantic-diff
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

Use `--project-dir PATH` with `ask` or `memo` when you are outside the target
project directory.

## Command semantics

| Command | Purpose | Main inputs |
|---|---|---|
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

The public query/memo eval stack is validated at three levels:

| Level | Description | Result |
|---|---|---:|
| Level 0 | Fixture rule eval over checked-in canonical outputs | 7/7 |
| Level 1 | Live-command rule eval using `pma ask` / `pma memo` | 7/7 |
| Level 2a | Fixture + optional LLM judge | 7/7
| Level 2b | Live-command + optional LLM judge | 7/7

Current release checks:

- Query/memo eval tests: 13 passed.
- Full test suite: 92 passed.
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
as the contract. Repo-level checkpoint scanning excludes secrets, prior
checkpoint memory, private evals, private data, generated outputs, and public
fixture project contents that would otherwise dominate extraction.

## Limitations

- This is a local CLI prototype, not a web app or autonomous agent.
- LLM extraction, live evals, semantic diff, and judge mode can vary by run.
- `ask` and `memo` answer from derived checkpoint memory, not arbitrary raw
  artifact retrieval.
- There is no vector database or broad RAG layer.
- The scanner does not parse `.py` source files directly in v0.1.
- The optional query/memo judge is not default, does not read full fixture
  checkpoint context by default, and cannot override rule failures.
- Windowed group-update conflict handling is prompt-guided rather than a
  deterministic conflict detector.

## Development checks

```bash
PYTHONPATH=src python -m unittest discover -s tests -q
python -m compileall -q src tests evals/scripts
git diff --check
```
