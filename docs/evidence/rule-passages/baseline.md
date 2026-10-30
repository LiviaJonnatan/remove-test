# Baseline: finding the cited rule section (EPA-HQ-OW-2022-0801)

Built 2026-10-16 17:11 UTC by `python src/main.py baseline` (rule-passages).

**Test set.** 158 passages from 5 letters that cite at least one section of the rule (2023-26148), 15 sections in all. The query is the passage with its citations masked; the answer is the section or sections it cites.

- `passages.parquet` sha256 `e63f2419fa85012faf48d30f7340aa0b8a5d537b2696224a8c0ed2dbf88b870f`
- `links.parquet` sha256 `7d62bfa7ce8983b0c99c6be02115e728df5840a0b92d0619a0ef2299dd32e53e`

**Searched.** 1096 chunks of the rule, procedural sections left out; 281 of them are regulatory text.

**Scoring.** Found at k: one of the top k results is in a cited section. Regulatory text only: results outside the regulatory text are dropped before taking the top k. Seconds per 1,000 passages is search time on the machine that built this file, including embedding the query.

| Method | Top-1 | Top-3 | Top-1, regulatory text only | Top-3, regulatory text only | Seconds per 1,000 passages |
|---|---|---|---|---|---|
| BM25 | 29.7% | 45.6% | 63.9% | 83.5% | 2.1 |
| Embeddings (bge-small) | 14.6% | 32.9% | 63.3% | 81.6% | 51.3 |
| BM25 + embeddings, rank fusion | 20.9% | 38.6% | 68.4% | 84.8% | 56.4 |

## By letter

Passages found at top-1 / top-3, whole rule.

| Letter | Passages | BM25 | Embeddings (bge-small) | BM25 + embeddings, rank fusion |
|---|---|---|---|---|
| EPA-HQ-OW-2022-0801-0775 | 22 | 3 / 8 | 6 / 8 | 3 / 7 |
| EPA-HQ-OW-2022-0801-0849 | 9 | 3 / 4 | 2 / 3 | 4 / 4 |
| EPA-HQ-OW-2022-0801-0935 | 33 | 9 / 15 | 7 / 15 | 8 / 15 |
| EPA-HQ-OW-2022-0801-0972 | 69 | 22 / 31 | 7 / 20 | 14 / 25 |
| EPA-HQ-OW-2022-0801-1131 | 25 | 10 / 14 | 1 / 6 | 4 / 10 |
