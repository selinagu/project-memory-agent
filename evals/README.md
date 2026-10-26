# Project Memory Agent Evals

`evals/` contains public synthetic evals and lightweight runners for checking
Project Memory Agent behavior.

The public evals are intentionally synthetic and commit-safe. Private real
project cases belong under ignored paths such as `evals/private/` and
`evals/private_outputs/`.

These suites are automated regression checks. They are separate from the small
human context-recovery timing study documented in
[`docs/developer-evaluation.md`](../docs/developer-evaluation.md), and their
results must not be reported as additional participants or repositories.

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
- `status_note`: execute deterministic `pma status-note` scenarios covering
  source precedence, canonical layout lookup, missing memory, and safe writes.
- `python_source`: scan and parse explicitly enabled Python files into bounded
  structural previews without executing project code.
- `git_aware_state`: render and validate bounded checkpoint-time Git metadata,
  non-inference rules, and metadata/SOURCE evidence separation.
- `reliability`: validate deterministic manifest freshness and conservative
  behavior for legacy non-Git checkpoints.

## Query/memo eval levels

Query/memo public evals currently cover seven synthetic cases. The same seven
cases run through the fixture, live-command, and optional judge layers; the
layer results do not represent 21 distinct cases.

| Level | Mode | What it does | Calls OpenAI? | Current result |
|---|---|---|---:|---:|
| Level 0 | fixture rules | Scores checked-in `fixture/stdout.md` outputs | No | 7/7 |
| Level 1 | live rules | Executes `pma ask` / `pma memo`, then scores stdout | Yes, through commands | Previously 7/7; not rerun in Phase 0, 1, 2, or 3 |
| Level 2 | fixture + judge | Scores fixtures and asks optional semantic judge | Yes, judge only | Previously 7/7; not rerun in Phase 0, 1, 2, or 3 |
| Level 2 | live + judge | Executes commands and asks optional semantic judge | Yes | Previously 7/7; not rerun in Phase 0, 1, 2, or 3 |

The query/memo suite remains seven cases total across its layers. Repository
test and subtest totals are reported in `PROJECT_STATUS.md` after each release
gate rather than treated as a fixed eval-case count.

## Status-note evaluation

Status-note evaluation is a separate six-case deterministic suite. It does not
call OpenAI and does not change the seven-case query/memo count.

```bash
python evals/scripts/run_status_note_eval.py \
  --eval-root evals/public/status_note \
  --output-root evals/outputs
```

The runner copies each synthetic `input/` project into a temporary directory,
injects `--project-dir`, executes `pma status-note`, evaluates stdout or stderr,
and checks any declared output-file contract. It exits nonzero if any case
fails. Use `--case-id <id>` to run one case.

The six cases cover:

- a TODO template when latest memory is absent
- progress-over-summary precedence
- checkpoint-summary fallback when progress is missing
- named canonical checkpoint layout resolution
- refusal to overwrite an existing status note without `--force`
- forced replacement with a structurally complete status note

## Python source evaluation

Python source evaluation is a separate seven-case deterministic suite. It does
not call OpenAI and is not part of either the seven query/memo cases or the six
status-note cases.

```bash
python evals/scripts/run_python_source_eval.py \
  --eval-root evals/public/python_source \
  --output-root evals/outputs
```

The runner copies each synthetic project, runs scanner and parser processing,
renders the resulting bounded artifact records and `combined_notes.md`, and
checks source markers, safe failure states, exact selected paths, redaction, and
non-execution sentinels. It exits nonzero if any case fails and accepts
`--case-id <id>` for focused runs.

The seven cases cover:

- module docstrings, imports, functions, async functions, and signatures
- class bases plus public sync/async methods
- constant, body, decorator, default, and annotation-literal redaction
- bounded syntax errors without source excerpts
- default-off Python scanning
- opt-in include/exclude scoping
- proof that top-level source side effects are not executed

## Git-aware state evaluation

Git-aware state evaluation is a separate seven-case deterministic suite. It
does not call OpenAI and is not part of the query/memo, status-note, or Python
source case counts.

```bash
python evals/scripts/run_git_aware_state_eval.py \
  --eval-root evals/public/git_aware_state \
  --output-root evals/outputs
```

The runner renders synthetic Git-context records, checks the extraction prompt
contract, and verifies that checkpoint metadata evidence is excluded from
SOURCE lookup. It exits nonzero if any case fails and accepts
`--case-id <id>` for focused runs.

The seven cases cover:

- clean repository context without roots, subjects, or fingerprints
- dirty status categories without progress claims
- changed filenames that cannot prove completion
- project-relative subdirectory scope
- bounded non-Git fallback
- deterministic 50-path and 4,000-character limits
- `CHECKPOINT_METADATA` versus SOURCE evidence separation

## Reliability evaluation

Reliability evaluation is a separate five-case deterministic suite. It does not
call OpenAI.

```bash
python evals/scripts/run_reliability_eval.py \
  --eval-root evals/public/reliability \
  --output-root evals/outputs
```

The cases cover unchanged non-Git inputs, content mutation, artifact addition,
scanner-config changes, and `unknown` for legacy checkpoints without an
`artifact_manifest.json`.

## Fixture mode

Install eval dependencies with `pip install -e '.[eval]'` before running the
scripts below.

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

Private evals and generated outputs are ignored by PMA's root `pma.toml` and
release ignore rules:

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
`.gitignore` as its contract. These eval-specific paths are project scope, not
universal scanner defaults.

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
- deterministic status-note source precedence and missing-memory behavior
- status-note canonical layout and overwrite protection
- bounded Python structural source extraction
- Python literal redaction, safe failures, opt-in scope, and non-execution
- non-Git artifact-manifest freshness and legacy uncertainty

This is focused coverage for known failure modes, not a comprehensive proof of
real-world reliability.
