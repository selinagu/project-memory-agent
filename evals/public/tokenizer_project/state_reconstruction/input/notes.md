# Tokenizer Project Notes

Goal: implement and benchmark a BPE tokenizer.

Current stage: implementation works on basic data and benchmarking has exposed a scaling bottleneck.

The project is not yet optimized. The main risk is that pair-frequency updates are recomputed too broadly after each merge.
