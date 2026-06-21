# DFlash Notes

Goal:
Reproduce DFlash speculative decoding and analyze when it works or fails.

Experiments:
- GSM8K 100 prompts: Normal 345.3s, 87.99 tok/s. DFlash 87.2s, 364.9 tok/s. Accept length 6.449.
- HumanEval 50 prompts: Normal 228.5s, 87.93 tok/s. DFlash 54.6s, 363.8 tok/s. Accept length 6.135.
- MT-Bench 50 prompts: Normal 217.9s, 87.79 tok/s. DFlash 86.5s, 221 tok/s. Accept length 4.306.
- Math500 100 prompts: Normal 752.4s, 87.53 tok/s. DFlash 149.6s, 458.8 tok/s. Accept length 7.957.

Failure Analysis:
- MT-Bench round stats: mean commit_len 3.685, accepted_draft_tokens 2.685, full-block accept 2.87%.
- Math500 round stats: mean commit_len 7.691, accepted_draft_tokens 6.691, full-block accept 18.92%.
- Early rejection positions dominate on MT-Bench.

Current Status:
Baseline reproduction is completed. Initial failure analysis is completed. Next step is deeper correlational analysis.
