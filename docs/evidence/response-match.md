# Finding where EPA answered a comment: retrieval baseline

31 Oct 2026. LCRI (EPA-HQ-OW-2022-0801). Script: `response-index/eval/match.py`. Output:
`data/derived/responses/EPA-HQ-OW-2022-0801/match/{report.json, predictions.parquet}`. No model API
calls. bge-small ran on the laptop CPU.

## Task

EPA files every commenter excerpt under one of 138 topic codes. In 75% of entries its only answer
is "Please see the EPA response to comment code X", so the answer to a comment lives in a code's
summary response. The **answer codes** for an entry are the code it is filed under plus any code its
own response points to (2,082 entries point outside their own code).

For a comment, each method ranks the 138 codes. A code's summary is cut into 150-word windows
(30-word overlap). Its score is its best window, and that window is what the product would show
as the answering paragraph.

| Input | What it is | Answer set |
|---|---|---|
| Excerpt | EPA's own excerpt of the comment, 7,309 distinct texts | answer codes of every entry with that text |
| Letter | our full text of the letter, scored window by window | every answer code of the record's entries |

The excerpt setting is an upper bound, because EPA already chose the passage. The letter setting
is what the product faces.

**Split.** A form-letter campaign is one group, and every other record is its own group. A hash of
the group id holds out one group in five: 249 of 1,139 groups, 1,465 test excerpts, and 271 test
letters. Only the ranker is fit, and only on train.

**Methods.**

| Method | Description |
|---|---|
| prior | codes by how often they answer a training entry |
| bm25 | BM25 as in `rule_passages.bm25` (vectorized form checked equal to `BM25Index`) |
| bge-small | dense embeddings |
| RRF | bm25 and bge-small fused by reciprocal rank, k = 60 |
| ranker | logistic regression on 5 features: both scores relative to the query's best, both reciprocal ranks, and the log prior |

## Results, test split

hit@k: an answer code is in the top k. recall@10: the share of a letter's answer codes in its top 10.

| Method | Excerpt hit@1 | hit@5 | hit@10 | Filed code hit@1 |
|---|---|---|---|---|
| prior | 13.9% | 33.6% | 46.4% | 13.7% |
| bm25 | 42.1% | 74.6% | 83.8% | 36.4% |
| bge-small | 43.8% | 76.8% | 84.2% | 38.8% |
| RRF | 51.4% | 81.1% | 87.4% | 44.4% |
| **ranker** | **52.7%** | **84.3%** | **90.0%** | **46.1%** |

The letter rows below leave out the three docket-wide codes (1.1 General Comments, 1.6 Summary
Information, 2.1 General Comments). Most letters carry one of them, and with them included the
prior alone gets 65.7% hit@1. 171 test letters have a provision-specific answer code.

| Method | Letter hit@1 | hit@5 | recall@10 | recall@20 |
|---|---|---|---|---|
| prior | 37.4% | 68.4% | 54.3% | 73.7% |
| bm25 | 39.2% | 72.5% | 49.8% | 70.9% |
| bge-small | 34.5% | 66.1% | 45.4% | 62.7% |
| RRF | 43.3% | 77.2% | 56.7% | 70.5% |
| **ranker** | **48.5%** | **84.8%** | **63.7%** | **82.0%** |

Unsupervised methods on all 7,309 excerpts give 40.3% (bm25), 43.8% (bge-small) and 50.6% (RRF)
hit@1, close to the test split.

## What this says

- On the letters, the frequency prior beats both retrievers on recall@10. bge-small alone is the
  worst method. Only the combination plus the prior clears the prior: 63.7% vs 54.3% recall@10 and
  82.0% vs 73.7% recall@20.
- The ranker's gain over RRF on excerpts is small (52.7% vs 51.4% hit@1, n = 1,465). On letters it
  is larger (48.5% vs 43.3%), but n is 171, so read it as a direction, not a measured gap.
- A reviewer shown 5 candidate codes finds an answer for 85% of letters, and 20 candidates cover
  82% of a letter's specific answers. So the product shape is a short list with the answering
  paragraph, checked by a person. A single automatic link is not good enough.
- Topic codes overlap: an excerpt's filed code alone is hit@1 for 46.1%, against 52.7% for any
  answer code. Some top-1 "misses" are a sibling code that EPA also points to elsewhere.

## Opus as reranker over the top 20

`response-index/eval/llm_rerank.py`. 175 held-out excerpts, the first 175 test excerpts by a hash
of the entry id. Opus 5.5 (`claude -p --model opus`) sees the comment and the ranker's top 20
codes, each as the title plus its best window, in hashed order. It returns up to 5 ids, best
first. The run cost $9.92 as reported by the CLI, about $0.057 per comment.

| Same 175 excerpts | hit@1 | hit@5 |
|---|---|---|
| ranker alone | 52.6% | 83.4% |
| **Opus over the ranker's top 20** | **78.3%** | **93.7%** |
| ceiling: an answer code in the top 20 | | 96.0% |

Per excerpt, top 1: Opus right and the ranker wrong 62 times, the reverse 17 times, both right 75,
both wrong 21. The bootstrap 95% interval on the gain in hit@1 is +17 to +35 points, and on Opus
hit@1 it is 72% to 84%. Opus never answered "none". Its top-1 misses that are in the top 20 are
mostly siblings ranked second or third: for example a schools-filtering comment filed under 18.7
with Opus picking 18.1 then 18.7.

So retrieval narrows 138 codes to 20 with 96% coverage, and the model does the reading. Without
retrieval the model cannot be asked at all, because the 138 summaries are about 200k words. Scaling
to all 7,889 entries at this rate would be roughly $450. Caching, a cheaper model or fewer
candidates are the levers, and none has been measured yet.

## Example

Tulsa Water and Sewer Department (entry 05412, a training-split entry; the ranker has 5
coefficients, so fitting on it barely matters) objects that the § 141.85(g) disturbance
notification "is not feasible as written". EPA filed it under 9.13 Post-disturbance/Replacement
Requirements. The ranker puts 9.13 first, and the window it returns reads: "The EPA acknowledges
these concerns and has made a revision to § 141.84(h)(3) to allow up to 30 days following the
completion of full service line replacements to provide notification to the owner..."

## Not measured

- **Which paragraph inside the code answers the comment.** EPA labels only the code, so the
  returned window has no label. It needs the human review queue.
- **The letter task over a whole letter.** It scores the best window, but does not yet say which
  passage of the letter raised which issue. The excerpt spans in `entries.parquet` are the labels
  for that.

## Cutting a letter into the points EPA answered

`response-index/eval/segment.py`. This step would come first in a response-drafting system. We
score it against EPA's own excerpts, which response-index located as character spans in our
letters. An EPA excerpt counts as found when a segment overlaps it with intersection over union of
0.5 or more. Precision applies the same test from the segments' side.

**Sample.** 82 held-out letters (same campaign split), each 150 to 6,000 words with 90% or more of
its entries located; median 658 words, 702 distinct EPA excerpts. One more letter returned no
usable answer.

**Baselines.** Our processed text has its whitespace flattened, so a paragraph baseline is not
possible. The baselines are single sentences and blocks of sentences packed to 82 words, EPA's
median excerpt length.

| Method | EPA excerpts found | Segment precision | F1 |
|---|---|---|---|
| every sentence | 29.6% | 4.3% | 0.08 |
| 82-word sentence blocks | 40.5% | 25.3% | 0.31 |
| Opus 5.5 over numbered sentences | **72.5%** | **53.1%** | **0.61** |

The Opus run cost $2.83. Cutting a letter is a real problem: the cheap baselines miss most excerpt
boundaries. Opus doubles their F1 but still misses about a quarter of EPA's excerpts and splits
differently from EPA about half the time. Part of that gap is a choice of grain, since EPA often
keeps a long multi-point passage as one excerpt.
