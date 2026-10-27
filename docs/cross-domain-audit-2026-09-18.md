# Cross-domain overfitting audit

> 2026-09-18 review correction: treat the results below as preliminary diagnostics, not validated end-to-end performance or proof that query vocabulary is the main cause. The AlphaFold milestone file contains DOI/title mismatches; the ablation adds hand-written benchmark searches; the old AlphaFold and history runs use different node/neighbor budgets (25/8 vs 100/25). Candidate ranking is separate from production route extraction. See [the revised planner proposal](history-planner-proposal-2026-09-18.md) for evidence, fair comparison design, and the revised Web Alpha sequence. Preserve these historical measurements rather than silently relabeling them as corrected results.

## Decision

**Verdict: partly overfit.** The citation, semantic, coupling, and co-citation ranker transfers across domains, but the complete route builder is still dependent on Metalens-specific search coverage and branch vocabulary. The Web Alpha should not yet be presented as a general research-route product.

The decision is based on frozen weights and a separate Transformer/AlphaFold milestone set. No ranking weights were tuned after seeing these results.

## Fixed protocol

- Embedding model: `BAAI/bge-small-en-v1.5` via FastEmbed/ONNX.
- Citation/semantic/coupling/co-citation weights: `1.0 / 0.8 / 0.7 / 0.6`.
- Candidate search limit: 50 per configured query.
- Metrics: candidate-pool recall and Recall@10/20/50/80.
- Known upstream identity failures are excluded from active recall and retained as explicit benchmark records.

## Baseline result

| Domain/run | Candidate-pool recall | Hybrid Recall@20 | Hybrid Recall@80 |
|---|---:|---:|---:|
| Metalens aggregate | 100.0% | 71.9% | 100.0% |
| Transformer, BERT seed | 40.0% | 30.0% | 30.0% |
| Transformer, BERT/T5/ViT | 37.5% | 0.0% | 25.0% |
| AlphaFold, single seed | 68.8% | 43.8% | 68.8% |
| AlphaFold, AlphaFold2/RoseTTAFold/ESMFold | 78.6% | 28.6% | 64.3% |

The hybrid ranker improves over citation-only in both non-Metalens domains, but it cannot recover a milestone that never enters the candidate pool.

## Retrieval experiment

A bounded review/reference backfill was added to the pipeline. It searches seed-derived topic queries, collects the returned works' references, and fetches the most frequently shared references. It is recorded in provenance and uses a fixed budget.

Independent backfill measurements:

- Transformer: 6/11 active milestones (54.5%) in the expanded review/reference pool.
- AlphaFold: 13/17 active milestones (76.5%) in the expanded review/reference pool.
- Integrated AlphaFold single-seed run: 93.8% candidate-pool recall and 81.2% hybrid Recall@80.
- Integrated Transformer single-seed run: 40.0% candidate-pool recall and 30.0% hybrid Recall@80.

The difference is not enough to claim generality. Transformer history still misses early attention/sequence-to-sequence works and several later efficiency branches. OpenAlex text search is also sensitive to query wording; topic names alone are not a reliable historical query planner.

## Root causes

1. Direct citation neighborhoods are local and do not guarantee old foundations.
2. Community-generated branch queries are good for lateral expansion but weak for historical backtracking.
3. OpenAlex search relevance is not a substitute for a domain-aware review/survey search strategy.
4. A fixed node budget can discard backfilled historical works unless the selection policy reserves history capacity.
5. Upstream identity/version errors can silently look like retrieval failures; DOI/OpenAlex/alias matching is now required.

## Product gate before Web Alpha

Do not expose a general “any field” promise until a new frozen audit reaches all of:

- candidate-pool recall >= 80% on both Transformer and AlphaFold single-seed runs;
- hybrid Recall@80 >= 75% on each single-seed run;
- no silent identity failures; unresolved records remain visible to the user;
- end-to-end run remains within the 10-minute budget on the developer laptop.

The local Web Alpha can start after this gate. Before then, only CLI/evaluation work is justified. The later user-experience test should validate whether people value the route and reading list; it cannot validate missing historical papers.

## Next experiment

Implement a domain-agnostic historical query planner with two independent signals:

1. seed-topic/title queries with explicit `review`, `survey`, and `history` intents;
2. high-cited review/reference backfill with a separate history quota.

Compare it against the current pipeline on the locked benchmark without changing ranking weights. If the gate still fails, narrow the initial product promise to supported domains or require an optional field/topic hint rather than shipping a misleading general-purpose map.
