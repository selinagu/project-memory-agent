# Developer context-recovery evaluation

This document reports the human timing data behind PMA's context-recovery
claim. It keeps measured human tasks separate from supplementary LLM-simulated
evaluations and automated regression suites.

## Result

Across five anonymized engineering or mathematics repositories, recorded
baseline context recovery took 107 minutes and PMA-assisted recovery took 37
minutes. Every repository-level timing pair came from tasks performed by actual
human participants, including the project developer. No LLM-generated or
LLM-estimated timing contributed to the reported reduction.

| Repository | Baseline (min) | With PMA (min) | Reduction |
|---|---:|---:|---:|
| A | 18 | 7 | 61.1% |
| B | 25 | 8 | 68.0% |
| C | 14 | 5 | 64.3% |
| D | 30 | 10 | 66.7% |
| E | 20 | 7 | 65.0% |
| **Total** | **107** | **37** | **65.42% pooled** |

The pooled reduction is:

```text
(sum(baseline) - sum(PMA)) / sum(baseline) * 100
= (107 - 37) / 107 * 100
= 65.42%
```

The simple mean of the five unrounded per-repository reductions is 65.01%.
Both measures round to 65%, so the README uses:

> Reduced context-recovery time by 65% in a small human evaluation across five
> engineering and mathematics repositories.

## Conditions and measured outcome

- **Baseline:** a human participant performed a context-recovery task without
  PMA assistance; the recorded value is the task duration in minutes.
- **PMA-assisted:** a human participant performed a context-recovery task with
  PMA available; the recorded value is the task duration in minutes.

The result measures recorded context-recovery time under those two conditions.
It does not measure overall developer productivity, implementation speed, code
quality, or long-term project outcomes.

## Protocol supported by available records

The available record establishes only that:

- five anonymized repositories were used;
- each repository was an engineering project or a mathematically complex
  project;
- all timing observations came from human-performed tasks, with the project
  developer among the participants;
- baseline and PMA-assisted recovery durations were recorded in minutes; and
- reduction was calculated from those paired repository-level durations.

The current records do not establish the total participant count, participant
backgrounds, task wording or allocation, repository selection procedure,
condition order, randomization, counterbalancing, number of repetitions,
detailed timing procedure, or whether the same person performed both
conditions for each repository. Those fields are unavailable rather than
inferred.

## Correctness rubric

No human-study correctness rubric or per-task correctness judgments were found
in the repository. The timing result should be interpreted only as recorded
context-recovery duration, not as proof that baseline and PMA answers had equal
accuracy or completeness.

A stronger future protocol should define expected findings and next actions
before timing, score both conditions blind to tool use, record omissions and
unsupported claims, and report timing only alongside correctness.

## Separation from other evaluations

- **Human timing results:** the table above contains measured task durations
  from human participants. These values alone produce the 65.42% pooled and
  65.01% unweighted mean reductions.
- **Supplementary LLM-simulated evaluations:** model-generated evaluation
  results are separate exploratory evidence. They supplied no timing values to
  the table and did not contribute to the reported 65% reduction.
- **Automated regression suites:** the [public eval suites](../evals/README.md)
  test synthetic query/memo, status-note, Python-source, Git-context, and
  reliability cases. Optional LLM judge modes assess generated outputs; they
  are not human timing observations.

The [scalability benchmarks](../benchmarks/README.md) measure deterministic
pipeline runtime on generated repositories. They do not measure human
context-recovery time or live LLM latency.

## Limitations

- Five repositories are too few to establish population-wide performance.
- Repository categories are known only at a broad level and remain anonymized.
- Total participant count, participant backgrounds, task allocation, condition
  order, randomization, counterbalancing, repetitions, variance, and
  uncertainty intervals are unavailable.
- Correctness equivalence between conditions was not documented.
- The data support a descriptive result for these five repositories, not a
  causal or general performance guarantee, and not a claim about overall
  developer productivity.
