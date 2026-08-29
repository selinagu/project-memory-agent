# Offline deterministic end-to-end smoke

This synthetic engineering smoke shows the product problem PMA solves: recover a
project's recorded state, ask for a source-grounded design decision, and detect
when that memory becomes stale after new work.

After installing the repository, run one command:

```bash
python demo/offline/run_smoke.py
```

CI uses the equivalent non-interactive form:

```bash
python demo/offline/run_smoke.py --non-interactive
```

The runner copies a checked-in synthetic cache-service fixture into temporary
storage, creates a real PMA checkpoint, reads it with brief, runs bounded source
lookup for ask, changes one source file, and verifies that freshness becomes
`stale`. Temporary storage is removed when the run ends, and checked-in fixture
files are never modified.

The scanner, parsers, artifact manifest, bounded Git/non-Git metadata,
checkpoint construction and publication, canonical layout, brief, bounded
source lookup, citation normalization, and freshness comparison are the real
PMA implementations. Fixed responses are injected only where checkpoint and
ask would ordinarily call an LLM. The demo does not require an API key, open a
network connection, report fake output as model quality, or present its timings
as LLM latency.

## Expected flow

```text
[1/6] Prepare a synthetic long-running project
[2/6] Create a deterministic checkpoint
[3/6] Verify memory health with brief
[4/6] Ask a source-grounded design question
[5/6] Simulate new project work
[6/6] Detect stale memory with freshness and brief
```

The answer cites `combined_notes.md SOURCE PROJECT_STATUS.md`. After the fixture
copy is changed, the final freshness result is `stale` and brief recommends a
replacement checkpoint.

## Smoke versus the live demo

This smoke is a reproducible CI walkthrough, not a substitute for live model
evaluation. In ordinary use, `pma checkpoint` and `pma ask` use configured LLM
access, while `brief` and `freshness` remain deterministic and OpenAI-free. PMA
does not claim that this fixed answer measures live answer quality. The formal
manual demo, semantic gold, and recording plan live under [`../live`](../live/README.md).
