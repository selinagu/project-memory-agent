# Contributing

PMA targets Python 3.10 and newer. Keep changes bounded by the architecture,
evidence, privacy, and publication contracts documented under `docs/`.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[dev]'
```

On Windows, activate the environment with the appropriate PowerShell or
Command Prompt script instead.

## Core checks

```bash
PYTHONPATH=src python -m unittest discover -s tests -q
PYTHONPATH=src python -m pytest -q
python -m compileall -q src tests evals/scripts benchmarks
python demo/offline/run_smoke.py --non-interactive
git diff --check
```

The CI workflow runs the full pytest suite and deterministic evals on Python
3.10, 3.11, 3.12, and 3.13.

## Deterministic evals

```bash
python evals/scripts/run_query_memo_eval.py --mode fixture --output-root evals/outputs
python evals/scripts/run_status_note_eval.py --output-root evals/outputs
python evals/scripts/run_python_source_eval.py --output-root evals/outputs
python evals/scripts/run_git_aware_state_eval.py --output-root evals/outputs
python evals/scripts/run_reliability_eval.py --output-root evals/outputs
```

Generated eval output belongs under ignored output directories. See
[evals/README.md](evals/README.md) for fixture, live, and optional judge modes.

## Demo and benchmark checks

```bash
python demo/live/validate_fixture.py
python demo/live/prepare_live_demo.py \
  --output /tmp/pma-live-demo-check \
  --update-output /tmp/pma-live-demo-update-check.md
python benchmarks/run_benchmark.py \
  --profile tiny \
  --warmups 0 \
  --repetitions 1 \
  --output /tmp/pma-benchmark-smoke
```

The offline demo and deterministic benchmark do not require OpenAI access.

## Privacy, build, and release rehearsal

```bash
python -m build --outdir dist
python evals/scripts/check_release_privacy.py \
  src benchmarks demo docs README.md PROJECT_STATUS.md \
  pyproject.toml MANIFEST.in LICENSE CHANGELOG.md dist
python evals/scripts/run_release_smoke.py
```

The release smoke builds a wheel and source distribution in a temporary
directory, installs the wheel into a clean temporary environment, and exercises
command help plus missing-checkpoint `brief`, `freshness`, and
`status-note` behavior from outside the repository. It does not publish or
call OpenAI.

## Documentation changes

- Keep the root README as a concise project homepage.
- Put CLI and storage semantics in `docs/cli.md`.
- Put scanner configuration and Python AST policy in `docs/scanner.md`.
- Put Git context and freshness behavior in `docs/freshness.md`.
- Put eval and benchmark methods in their directory READMEs.
- Record release status in `CHANGELOG.md` or `PROJECT_STATUS.md`.
- Use repository-relative Markdown links and fenced `mermaid` diagrams.
- Do not claim test counts, release state, or evaluation results without
  current repository evidence.

## Architecture and safety

Read [docs/architecture.md](docs/architecture.md) and the
[architecture decisions](docs/decisions/README.md) before changing module
boundaries, scanner scope, or checkpoint publication. Directory publication
must preserve backup/rollback protection; it is not a strict cross-platform
atomic tree switch.
