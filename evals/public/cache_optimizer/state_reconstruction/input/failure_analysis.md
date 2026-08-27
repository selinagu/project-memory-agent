# Failure Analysis

The long-context regression may be caused by cache churn. The recency window may reject keys that become useful later, causing repeated evictions and reloads.

An alternative explanation is prefetch overhead. The current benchmark does not separate eviction churn from prefetch cost.

Open question: whether the regression is mainly from cache churn or prefetch overhead.
