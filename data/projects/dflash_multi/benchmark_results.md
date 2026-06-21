# Benchmark Results

Experiments:
- GSM8K 100 prompts: Normal 345.3s, 87.99 tok/s. DFlash 87.2s, 364.9 tok/s. Accept length 6.449.
- HumanEval 50 prompts: Normal 228.5s, 87.93 tok/s. DFlash 54.6s, 363.8 tok/s. Accept length 6.135.
- MT-Bench 50 prompts: Normal 217.9s, 87.79 tok/s. DFlash 86.5s, 221 tok/s. Accept length 4.306.
- Math500 100 prompts: Normal 752.4s, 87.53 tok/s. DFlash 149.6s, 458.8 tok/s. Accept length 7.957.

Confirmed Finding:
DFlash gives large throughput speedups compared with normal decoding on all listed benchmarks.

Observation:
Math500 has the highest accept length among the listed benchmarks. MT-Bench has the lowest accept length among the listed benchmarks.
