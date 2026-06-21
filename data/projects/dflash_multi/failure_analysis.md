# Failure Analysis

Round-level statistics:
- MT-Bench: mean commit_len 3.685, accepted_draft_tokens 2.685, full-block accept 2.87%.
- Math500: mean commit_len 7.691, accepted_draft_tokens 6.691, full-block accept 18.92%.
- HumanEval: mean commit_len 6.112, accepted_draft_tokens 5.112, full-block accept 11.42%.

Confirmed Finding:
Early rejection positions dominate on MT-Bench.

Tentative Hypothesis:
Open-ended dialogue tasks such as MT-Bench may produce less predictable continuations than math reasoning tasks.
