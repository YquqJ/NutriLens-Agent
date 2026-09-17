# RAG Split and Retrieval Ablation Report

Date: 2026-09-17

## Evaluation Setup

- Dataset: 47 queries (42 positive, 5 negative)
- Positive metrics: Recall@4, Recall@8, MRR, nDCG@4
- Split strategies: `fixed` (32 chunks), `section_aware` (66 chunks)
- Retrieval modes: vector, BM25, hybrid RRF, hybrid RRF + rerank
- Golden labels: stable evidence anchors (`page_number` + normalized evidence text)

The five negative queries are recorded for out-of-domain inspection but are not included in the four positive retrieval metrics.

## Results

| Split | Mode | Recall@4 | Recall@8 | MRR | nDCG@4 |
|---|---|---:|---:|---:|---:|
| fixed | vector | 95.24% | 97.62% | 79.31% | 83.13% |
| fixed | BM25 | 92.86% | 97.62% | 80.85% | 83.26% |
| fixed | hybrid RRF | 97.62% | 97.62% | 88.10% | 90.59% |
| fixed | hybrid rerank | **97.62%** | **97.62%** | **90.28%** | **92.13%** |
| section-aware | vector | 91.27% | 96.43% | 89.05% | 88.43% |
| section-aware | BM25 | 88.89% | 90.87% | 84.92% | 84.78% |
| section-aware | hybrid RRF | 88.89% | 91.67% | 86.98% | 86.90% |
| section-aware | hybrid rerank | 89.68% | 94.05% | 88.65% | 87.62% |

## Valid Improvements

On the fixed split, replacing vector-only retrieval with hybrid retrieval and reranking produced:

- Recall@4: 95.24% -> 97.62% (+2.38 percentage points)
- Recall@8: 97.62% -> 97.62% (no change)
- MRR: 79.31% -> 90.28% (+10.97 percentage points, +13.83% relative)
- nDCG@4: 83.13% -> 92.13% (+8.99 percentage points, +10.81% relative)

The isolated reranker contribution over hybrid RRF was +2.18 percentage points MRR and +1.54 percentage points nDCG@4.

## Split Conclusion

The current section-aware implementation does not outperform fixed splitting overall. It improves vector-only ranking (MRR +9.74 percentage points versus fixed vector), but its smaller chunks reduce recall and weaken the hybrid pipeline. Fixed splitting plus hybrid reranking is the best configuration in this experiment.

This result should be reported honestly rather than described as a section-aware splitting improvement. A future experiment can test a larger section-aware chunk size, parent-child retrieval, or neighboring-chunk expansion.

## Resume Wording

Built a 47-query RAG golden dataset and an ablation framework covering vector, BM25, RRF fusion, and reranking. Hybrid retrieval plus reranking increased MRR from 79.31% to 90.28% (+10.97 percentage points) and nDCG@4 from 83.13% to 92.13% (+8.99 percentage points), with Recall@4 reaching 97.62%.
