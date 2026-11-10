# Eval: argument graph on EPA-HQ-OW-2022-0801

77 points scored by every system (73 regular). Intervals: 95% percentile bootstrap over blocks, 1000 draws, seed 215.

| System | Block recall | Point recall (top-3) | Point recall (top-2) | Catch-all (top-3) |
|---|---|---|---|---|
| pipeline | 0.3636 [0.2121, 0.5455] (12 of 33 blocks) | 0.2329 [0.1212, 0.3377] | 0.1644 [0.0701, 0.2526] | 0.0 (4 points) |
| B0 | 0.3636 [0.1818, 0.5455] (12 of 33 blocks) | 0.2192 [0.12, 0.3288] | 0.2192 [0.12, 0.3288] | 0.0 (4 points) |
| B1 | 0.4242 [0.2424, 0.6061] (14 of 33 blocks) | 0.274 [0.16, 0.3898] | 0.2192 [0.1154, 0.3333] | 0.0 (4 points) |
| B2 | 0.4242 [0.2727, 0.6061] (14 of 33 blocks) | 0.3425 [0.2154, 0.4557] | 0.2466 [0.1343, 0.3611] | 0.0 (4 points) |

| Against the pipeline, regular points | Both hit | Pipeline only | Other only | Neither | Top-3 difference |
|---|---|---|---|---|---|
| B0 | 10 | 7 | 6 | 50 | -0.0137 [-0.1163, 0.0938] |
| B1 | 14 | 3 | 6 | 50 | 0.0411 [-0.0482, 0.1487] |
| B2 | 9 | 8 | 16 | 40 | 0.1096 [-0.0353, 0.2535] |

| Significance (k = 214) | Recall on the 64 points with an explicit response |
|---|---|
| rule | 0.0469 |
| flag_all | 0.25 |
| top_k_by_n_letters | 0.0625 |
| top_k_by_passage_words | 0.1094 |

Response location of the scored points: {'same_paragraph': 30, 'next_paragraph': 34, 'none': 13}.

Compression: 0.7043 issues per claim, 1.6621 issues per passage.

Review load, rows over claims: 184 / 859 = 0.2142, fails the 20% bar: True. Distinct claims named in a row: 139 / 859 = 0.1618, fails the 20% bar: False (26 claims carry two rows, 17 rows are issue-level). By reason: {'quote_failed': 0, 'quote_fragment': 0, 'section_disagrees': 43, 'no_section': 63, 'linker_disagrees': 46, 'missing_from_output': 0, 'llm_failed': 0, 'contested_merge': 16, 'giant_issue': 1, 'judge_unsure': 15}

Linker agreement: 0.9464 (frozen test top-5: 0.902, from docs/evidence/linker-train/in-pre/metrics.json); checked: True.

Cost: {'usd_total': 29.1882, 'usd_by_step': {'extract': 17.5051, 'judge': 11.6831}, 'calls_by_step': {'extract': 40, 'judge': 45}, 'cache_read_tokens': 0, 'cache_write_tokens': 530554, 'output_tokens': 371509, 'wall_clock_s': 156.3, 'model_id': ['claude-fable-5-1'], 'backend': 'cli', 'effort': None}

## Limits

- The labels are summary level. The preamble says what commenters said and what the EPA did, with
  no excerpt and no commenter id, so a point is matched to an issue by meaning, judged by a model
  and checked by two readers on a sample.
- The EPA chose what to summarise. Comments it judged insignificant are not in the preamble, so
  point recall is a recall label only and says nothing about what else the commenters said.
- One rule, one agency. Nothing here was scored outside EPA-HQ-OW-2022-0801.
- The 3,529-page Response to Comments document (EPA-HQ-OW-2022-0801-2645) is not on disk; the
  preamble is the only label source.
- Point boundaries inside paragraphs that carry both the summary and the response are heuristic.
  The reader pack's 40-item boundary check reports the error rate.
- The intervals are bootstrap percentiles over blocks. With 34 blocks and recall concentrated in a
  few of them they are wide; they say how much the sample of blocks moves the number, not whether
  the matcher is right.

