# Architecture decision records

These records capture the major product and reliability decisions implemented
in PMA. Status `Accepted` means the decision describes the current architecture.

| ADR | Decision |
|---|---|
| [0001](0001-canonical-checkpoint-layout.md) | Use one canonical checkpoint-layout resolver |
| [0002](0002-history-and-latest.md) | Separate immutable successful history from replaceable latest state |
| [0003](0003-generated-output-isolation.md) | Exclude generated artifacts from repository ingestion |
| [0004](0004-bounded-evidence-retrieval.md) | Use bounded checkpoint evidence instead of repository-wide RAG |
| [0005](0005-freshness-signals.md) | Combine artifact manifests with bounded Git metadata for freshness |
| [0006](0006-opt-in-python-awareness.md) | Keep Python source awareness structural, bounded, and opt-in |
| [0007](0007-evidence-boundary.md) | Do not allow generated claims or eval gold beyond available evidence |
| [0008](0008-defer-autonomous-integrations.md) | Defer autonomous loops and external integrations |

New records should describe durable architectural or product tradeoffs, not
ordinary implementation details. Accepted records are changed by adding a new
superseding ADR rather than silently rewriting the original decision.
