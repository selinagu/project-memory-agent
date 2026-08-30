# Changelog

All notable changes to Project Memory Agent are documented in this file.

## [0.1.1] - 2026-08-30

### Added

- Canonical internal and external checkpoint layouts with a shared resolver.
- Transactional, failure-safe checkpoint publication with immutable history
  and bounded failed-run diagnostics.
- Bounded, source-grounded checkpoint retrieval for `pma ask` and memo flows.
- Git and non-Git freshness signals, including generated-output isolation.
- Reliability and regression evaluation for storage, path resolution,
  freshness, retrieval, status notes, and bounded source extraction.
- Reproducible synthetic scalability benchmarks with documented budgets and
  limitations.
- Enforced architecture boundaries, design-decision records, and a
  privacy-safe dogfooding case study.
- Deterministic offline smoke and reproducible live-demo workflows.
- GitHub Actions coverage for Python 3.10 through 3.13, plus build, privacy,
  and clean-install release gates.

### Known limitations

- Normal `checkpoint` and `ask` workflows require configured LLM access.
- Bounded checkpoint retrieval is not repository-wide semantic RAG.
- PMA is a local CLI and does not run an autonomous agent loop.
- Version 0.1.1 is an early, dogfooded reliability baseline; it does not claim
  large-scale external adoption or production deployment.
