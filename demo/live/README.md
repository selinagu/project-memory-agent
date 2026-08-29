# PMA live demo

This is the presentation-grade demo for PMA. It uses a synthetic but realistic
repository, real PMA commands, and checked-in expectations. It is deliberately
separate from the deterministic [offline smoke test](../offline/README.md).

The story is simple: return to an unfamiliar cache-gateway project, reconstruct
its state, recover a source-backed design decision, then change the repository
and show that PMA detects stale memory.

## Demo contract

- `fixtures/atlas-cache-gateway/` is the initial evidence set.
- `fixtures/updates/PROJECT_STATUS.md` is the later repository change.
- `gold.yaml` defines required findings, sources, and forbidden claims.
- `commands.txt` is the exact presenter command sequence.
- `narration.md` contains both recording scripts and shot lists.
- `validate_fixture.py` is offline and safe for CI.
- `prepare_live_demo.py` creates a clean temporary Git repository.
- `rehearse_live_demo.py` is blocked unless live calls are explicitly confirmed.

No generated transcript or recording is committed as evidence. The README media
slots should only be populated after a human has run and reviewed the full live
workflow.

## Prepare and validate (no API calls)

From the PMA repository:

```bash
python demo/live/validate_fixture.py
python demo/live/prepare_live_demo.py
```

The prepared project is `/tmp/pma-live-demo`; its later status update is
`/tmp/pma-live-demo-update.md`. Preparation refuses unsafe destinations and only
resets a directory carrying PMA's sentinel:

```bash
python demo/live/prepare_live_demo.py --reset
```

Then open a terminal at `/tmp/pma-live-demo` and type the commands from
`demo/live/commands.txt` one at a time. `checkpoint`, `memo`, and `ask` are real
model-backed commands and require a configured `OPENAI_API_KEY`.

## Expected visible results

1. `checkpoint` reconstructs the pre-rollout goal, bounded invalidation decision,
   unvalidated high-churn blocker, and next action.
2. `brief` makes the saved state easy to scan.
3. `memo` gives a compact re-entry note without claiming rollout is complete.
4. `ask --sources` cites `PROJECT_STATUS.md`, `benchmark_results.json`, and
   `failure_analysis.md` for the bounded-invalidation decision.
5. Replacing `PROJECT_STATUS.md` makes `freshness` report stale state.
6. The final `brief` recommends creating a new checkpoint.

Model wording may vary. The claims, evidence boundary, forbidden claims, and
freshness transition are the acceptance standard—not exact prose.

## Optional guarded rehearsal

The rehearsal runner writes sanitized JSON under `/tmp` and makes no call unless
both an explicit flag and `OPENAI_API_KEY` are present:

```bash
python demo/live/rehearse_live_demo.py --confirm-live-calls --runs 3
```

Run this only when API use is intended. Review every JSON result before recording;
the lightweight checker is a guardrail, not a substitute for human evaluation.

## Recording standards

- Record a genuine terminal session; do not paste fabricated output.
- Keep the project name and key numbers readable at 1080p.
- Hide environment variables, usernames, absolute home paths, notifications, and
  unrelated windows.
- Stop and re-record if sources are wrong, stale state is missed, a forbidden
  claim appears, or the API fails.
- Use the short cut for the README preview and the narrated cut for interviews.
- Add media links only after privacy review and successful rehearsal.
