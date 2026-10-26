# CLI guide

This guide owns installation, command behavior, checkpoint location arguments,
and on-disk layouts for Project Memory Agent (PMA).

## Installation

PMA supports Python 3.10 and newer. From the repository:

```bash
pip install -e .
```

Install development and deterministic-evaluation dependencies with:

```bash
pip install -e '.[dev]'
```

The development form without an editable install is:

```bash
pip install openai pydantic python-dotenv
PYTHONPATH=src python -m pma ...
```

LLM-backed commands load `OPENAI_API_KEY` from the environment. A local
`.env` file is supported and must not be committed.

## Core workflow

```bash
pma checkpoint --project-dir .
pma brief --project-dir .
pma ask --project-dir . "What should I work on next?"
pma freshness --project-dir .
```

`checkpoint` and `ask` use configured LLM access. `brief`, `freshness`,
and `status-note` are deterministic and do not call OpenAI.

## Commands

### `checkpoint`

```bash
pma checkpoint --project-dir .
```

Scans selected artifacts, derives a validated project state, and publishes a
new run plus `latest/`. `--project-dir` is required. The default model is
`gpt-4.1-mini`.

Named external or custom storage uses a complete pair:

```bash
pma checkpoint \
  --project-dir . \
  --project-name my-project \
  --base-output-dir ./pma-data
```

`--semantic-diff` enables an additional LLM-backed alignment step;
`--semantic-diff-model` selects its model.

### `brief`

```bash
pma brief --project-dir .
pma brief --project-dir . --json
```

Reads the latest checkpoint, reuses freshness comparison, checks status-note
timing, and returns one checkpoint-maintenance recommendation. It does not
summarize project content, run a checkpoint, or modify files. Missing, stale,
unknown, incomplete, and invalid states are ordinary results.

Use `pma memo --type self` when you want project findings and next actions;
use `pma brief` when you want checkpoint health.

### `ask`

```bash
pma ask --project-dir . "What are the confirmed findings?"
pma ask --project-dir . --sources "What evidence supports them?"
```

Answers from the latest structured checkpoint. `--sources` forces bounded
lookup in generated `SOURCE`-marked checkpoint notes; source- or
evidence-related questions may enable the same lookup automatically. The
command does not reopen arbitrary raw project artifacts.

### `memo`

```bash
pma memo --project-dir . --type self
pma memo --project-dir . --type group-update
pma memo --project-dir . --type group-update --last 5
pma memo --project-dir . --type group-update --since 2026-07-01
```

A self memo is a compact re-entry summary. A group update can use only the
latest checkpoint or a mutually exclusive `--last N` / `--since YYYY-MM-DD`
history window. Latest project state remains authoritative; historical
progress files describe the reporting window.

### `freshness`

```bash
pma freshness --project-dir .
pma freshness --project-dir . --json
```

Compares the latest checkpoint-time signals with the current project and
returns `current`, `stale`, `unknown`, or `no_checkpoint`. It is
read-only, makes no LLM call, and returns exit status 0 for those ordinary
states. See [Git context and freshness](freshness.md) for comparison rules.

### `status-note`

```bash
pma status-note --project-dir .
pma status-note --project-dir . --from-latest
pma status-note --project-dir . --from-latest --write
```

Without `--write`, the command prints a checkpoint-friendly Markdown template
or a latest-derived draft. The default output is
`<project-dir>/PROJECT_STATUS.md`. Existing output is not overwritten unless
`--force` is passed. `--output` and `--force` require `--write`;
checkpoint-location arguments require `--from-latest`.

## Checkpoint locations

Writers and consumers use one canonical resolver. Consumer commands resolve
the latest checkpoint in this order:

1. `--latest-dir PATH`
2. a complete `--base-output-dir PATH --project-name NAME` pair
3. `<project-dir>/.project_memory/latest`

Relative `--latest-dir` values resolve under `--project-dir`. Relative
`--base-output-dir` values follow the shell's working-directory semantics.
Use the same location arguments for checkpoint creation and every consumer.

The default history layout is:

```text
.project_memory/
  latest/
  runs/<UTC-microsecond-run-id>/
  failed_runs/<run-id>/
```

`latest/project_state.json` is the current-state authority. Successful runs
remain in `runs/`; failed construction is isolated in `failed_runs/` with
bounded diagnostic metadata.

### Legacy direct output

```bash
pma checkpoint --project-dir . --output-dir ./checkpoint-artifacts
pma brief --project-dir . --latest-dir ./checkpoint-artifacts
```

Legacy `--output-dir` stores artifacts directly in the requested directory,
without `latest/` or `runs/`. It cannot be combined with named-history
arguments. Replacement still preserves the previous usable output on failure.

## Offline smoke

```bash
python demo/offline/run_smoke.py --non-interactive
```

This deterministic end-to-end path needs no API key or network access. Fixed
responses replace only the two LLM boundaries. See the
[offline demo contract](../demo/offline/README.md).

## Scanner configuration

An optional `pma.toml` controls artifact scope and resource budgets. See the
[scanner guide](scanner.md).
