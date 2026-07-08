# Project Memory Agent Evals

`evals/` contains public synthetic evals and lightweight runners for checking
Project Memory Agent behavior.

The public evals are intentionally synthetic and commit-safe. Private real
project cases belong under ignored paths such as `evals/private/` and
`evals/private_outputs/`.

## Public eval principles

- Eval cases describe semantic expectations, not exact full-output matches.
- Public cases should stay synthetic and safe to publish.
- Private real-project data must not be added to public evals.
- Live and judge modes may call OpenAI and are not default CI behavior.

## Eval types

- `state_reconstruction`: derive and evaluate a `ProjectState` from one
  project version.
- `progress_update`: checkpoint two project versions and evaluate
  `progress_since_last.md`.
- `query_memo`: evaluate `pma ask` and `pma memo` behavior, including
  schema-aware answers, SOURCE citation discipline, self memos, group updates,
  windows, and correction/supersession handling.

## Query/memo eval levels

Query/memo public evals currently cover seven synthetic cases.

| Level | Mode | What it does | Calls OpenAI? | Current result |
|---|---|---|---:|---:|
| Level 0 | fixture rules | Scores checked-in `fixture/stdout.md` outputs | No | 7/7 |
| Level 1 | live rules | Executes `pma ask` / `pma memo`, then scores stdout | Yes, through commands | 7/7 |
| Level 2 | fixture + judge | Scores fixtures and asks optional semantic judge | Yes, judge only | 7/7 |
| Level 2 | live + judge | Executes commands and asks optional semantic judge | Yes | 7/7 |

The query/memo eval unit tests currently pass 13 tests. The full repository
test suite currently passes 92 tests.

## Fixture mode

Fixture mode is the default deterministic regression mode:

```bash
python evals/scripts/run_query_memo_eval.py \
  --mode fixture \
  --eval-root evals/public \
  --output-root evals/outputs
```

It reads saved outputs such as `fixture/stdout.md`, applies rule checks from
`gold.yaml`, and does not execute `pma ask` / `pma memo`.

The `command` field in `gold.yaml` documents the intended command for the case
but is not executed in fixture mode.

## Live mode

Live mode runs the documented command against a copied fixture project:

```bash
PYTHONPATH=src python evals/scripts/run_query_memo_eval.py \
  --mode live \
  --eval-root evals/public \
  --output-root evals/outputs
```

The runner copies each case `input/` directory to a temporary project, injects
`--project-dir`, captures stdout/stderr/exit code, writes artifacts under the
eval output directory, and applies the same rule checks.

Because live mode executes `pma ask` / `pma memo`, it may call OpenAI via the
normal runtime configuration. Treat live results as robustness signals, not
the default CI gate.

## Optional judge mode

`--judge` adds an LLM semantic judge on top of rule checks:

```bash
PYTHONPATH=src python evals/scripts/run_query_memo_eval.py \
  --mode fixture \
  --judge \
  --judge-model gpt-4.1-mini \
  --eval-root evals/public

PYTHONPATH=src python evals/scripts/run_query_memo_eval.py \
  --mode live \
  --judge \
  --judge-model gpt-4.1-mini \
  --eval-root evals/public
```

The query/memo judge receives:

- case id
- capability
- documented command
- compact `gold.yaml` constraints
- actual output
- rule-check summary

It does not read full fixture checkpoint context by default. In v0.1, final
status is strict: a case passes only when both rule checks and the judge pass.
The judge cannot override rule failures yet.

Use `--case-id <id>` to run or judge a single query/memo case during debugging:

```bash
PYTHONPATH=src python evals/scripts/run_query_memo_eval.py \
  --mode fixture \
  --judge \
  --case-id ask_schema_basic \
  --eval-root evals/public
```

## State and progress evals

Deterministic state regression:

```bash
python evals/scripts/run_state_eval.py \
  --eval-root evals/public \
  --output-root evals/outputs
```

Deterministic progress regression:

```bash
python evals/scripts/run_progress_eval.py \
  --eval-root evals/public \
  --output-root evals/outputs
```

Live state/progress modes and optional judges may call OpenAI and require
`OPENAI_API_KEY`.

## Private evals and scanner scope

Private evals and generated outputs are ignored:

- `evals/private/`
- `evals/private_outputs/`
- `evals/outputs/`

Repo-level checkpoint scanning also excludes public fixture project contents:

- `evals/public/**/input/`
- `evals/public/**/fixture/`
- `evals/public/**/v1/`
- `evals/public/**/v2/`

This prevents synthetic fixture projects from dominating Project Memory
Agent's own repo-level `ProjectState`. Eval metadata and docs such as this file
remain intended checkpoint inputs.

The checkpoint scanner uses explicit allow/ignore rules rather than treating
`.gitignore` as its contract.

## Current public coverage

The synthetic public suite covers:

- cache optimizer state and progress cases
- robot-policy state and conflicting-finding cases
- tokenizer state and irrelevant-file-change cases
- schema-aware ask behavior
- SOURCE citation discipline
- personal self memos
- latest-only group updates
- last-N and since-date group windows
- correction/supersession and current-action field boundaries

This is focused coverage for known failure modes, not a comprehensive proof of
real-world reliability.
