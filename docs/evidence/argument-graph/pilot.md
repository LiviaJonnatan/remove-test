# argument-graph pilot on the LCRI docket (EPA-HQ-OW-2022-0801)

Run 30 Oct 2026 on a laptop, branch `milestone3` at commit `2fb86d5` plus the uncommitted
`argument-graph/` folder. Backend `cli` (`claude -p --model fable`), model id reported by the CLI
`claude-fable-5-1`. Revised the same day after a code review of the eval (see "Revision after the
code review" at the end): the label parser, the metric names, the intervals, the catch-all rule and
the B0 baseline changed, and the affected points were re-judged for $1.83.

Every number below is read from `summary.json`, the ledgers, the parquet files, `eval/out/results.json`
or `eval/out/pipeline_only/results.json`, except where marked "read from the terminal": the stage
wall clocks in S0, the S1 wall clock, and the S1 floor analysis in S4, whose source tables were
overwritten by later steps. Nothing is estimated except where the word "bound" appears.

## Headline

| Item | Value |
|---|---|
| Cited passages read | 364 (from 42 letters, 15 sections) |
| Claims | 859, 2.36 per passage, quote verified by string match 859 of 859 on the first pass |
| Schema failures, re-asks, second attempts | 0, 0, 0 across 150 calls |
| Issues | 605 (116 with more than one claim); 214 carry the `evidence_type` flag |
| Point recall (top-3 candidates) against the final rule's comment summaries, 73 shared regular points | pipeline 23.3% [12.1, 33.8], B0 passages-as-issues 21.9%, B1 cosine clustering 27.4%, B2 12 Oct positions 34.2% |
| Block recall, pipeline, 199-point sample | 20 of 33 blocks (60.6%) [42.4, 75.8] |
| Significance rule recall, 166 points with an explicit response (199 sample) | 9.0%; flag-all 22.9%; top-k by letters 8.4%; top-k by passage words 12.0% |
| Review load | 184 rows over 859 claims (21.4%, above the 20% bar); 139 distinct claims named (16.2%, under it) |
| Linker agreement | cited section in the frozen linker's top 5 for 813 of 859 claims (94.6%) |
| Measured LLM spend, all ledgers | $40.23 for 150 calls: the pilot $38.40 for 139 (cap $40), the post-review re-judging $1.83 for 11 |

Intervals are 95% percentile bootstraps over preamble blocks (1,000 draws, seed 215).

The extractor and the harness did what they were built to do: every quote is verbatim, every batch
parsed, nothing fell back. The pair judge did not beat the no-model clustering baseline on point
recall, and the `evidence_type` rule is worse than flagging everything. Both gates are failed on
this evidence.

## S0: inputs

| Step | Result | Time (read from the terminal) |
|---|---|---|
| `dvc pull data/raw/EPA-HQ-OW-2022-0801.dvc` | 2,076 files, 458 MB | |
| data-processor, `MAX_RECORDS` unset | 1,589 records, 36 failed, 1,553 letters (body 1,348, pdf_text 148, ocr 39, docx 18) | 19 min 54 s, OCR dominated |
| campaign-builder | 459 letters in 48 containment groups, 1,094 individual | 16 s |
| passage-stage | 1,553 letters read, 14 skipped as copies, 5,409 passages, 369 with a citation, 485 links, 472 resolved to 15 sections, 13 unresolved | 7 s |
| cited passages with a resolved section | 364, from 42 letters | |

Cited passages by section: 141.84 107, 141.85 60, 141.92 58, 141.86 57, 141.90 47, 141.81 35,
141.82 34, 141.2 26, 141.80 19, 141.87 12, 141.93 5, 142.15 5, 142.16 5, 142.14 1, 141.154 1.
These sum to 472, not 364: a passage citing two sections counts under both, and 79 do.

`.env` has `MAX_RECORDS=50`, a cap of 50 records on the processor. The first run produced 50
letters and had to be redone with `-e MAX_RECORDS=`. Letter 0938 (Vermont DWGPD) is a 31-word stub:
its attachment is not in the raw pull. Chroma was not running, so rule context came from the
proposal text on disk (`rule_context: files`, 1,108 chunks, document 2023-26148).

## S1: smoke, 24 passages

`GRAPH_MAX_PASSAGES=24`, 1 passage of 141.154 and 23 of 141.2. The `extract` subcommand runs the
later stages too, so this smoke also judged 104 pairs.

| Measured | Value |
|---|---|
| Extract calls | 3 (5.1 s, 80.6 s, 93.1 s) |
| Claims | 52, quotes 52 of 52 first pass, 0 dropped, 0 schema failures |
| Tokens per passage | 513 cache-write, 650 output |
| Cost per passage | $0.0428 |
| Judge | 104 pairs, 6 calls, $0.7974; different 97, same_ask 5, unsure 2 |
| Total | $1.8241; wall clock 146.9 s read from the terminal (`run.log` timestamps give 148 s) |

G1 passed (quote pass 100% against the 95% gate, 0 schema failures). Bound for S3 from S1:
364 x $0.0428 = $15.58, "bound from measured S1 tokens".

S2 (SDK backend parity) was not run: there is no `ANTHROPIC_API_KEY` in `.env`.

## S3: extraction, 364 passages

| Measured | Value |
|---|---|
| Extract calls | 40 live: 3 in S1, 37 in S3. Two S1 answers were served from cache in S3; the third (`extract_141.2_001`, $0.4887) was re-called because its batch composition changed |
| Claims | 859; 9 passages returned zero claims; 293 passages returned more than one |
| Quotes | 859 of 859 verified on the first pass, all against the passage itself, 0 fragments, 0 over 60 words (mean 28.5) |
| Stance | modify 388, clarify 192, oppose 161, support 75, other 43 |
| Evidence type | alternative 261, feasibility 162, experience 96, cost 47, legal 27, data 14; 392 claims list none |
| `ask` null | 194 (115 of them with stance `oppose`) |
| Extraction cost, ledger | $17.5051 for 40 calls, 174,519 cache-write tokens, 280,279 output tokens, 2,928 model-seconds. S3's own 37 calls: $16.4784 |
| Wall clock | 7 min 23 s with 8 threads |
| Review rows from extraction | `no_section` 63, `section_disagrees` 43, `linker_disagrees` 46 |

Against the $15.58 bound: $17.51 on the extract ledger includes the three S1 calls ($1.0267), and
24 passages were paid for twice through the re-called batch ($0.4887). Net of the duplicate the
ledger is $17.02; the remaining gap is claim density, 2.36 claims per passage against 2.17 in S1.

Linker cross-check (`GRAPH_LINKER_DIR=linker-train/out/serving`, the deployed 65.5% model): the
cited section is at rank 1 for 551 claims, 2 for 165, 3 for 53, 4 for 31, 5 for 13, absent for 46.
That is 94.6% top-5 agreement, above the 90.2% on the frozen test set. These passages all carry an
explicit citation, so they are the easy case for the linker.

## S4: pairs

At the spec's defaults (cosine floor 0.60, 10 neighbours) the 859 claims produce 4,984 candidate
pairs. S1 measured $0.0077 per judged pair, so that is a $38 bound on the judge alone and over
the cap. The run used `GRAPH_PAIR_MIN=0.70` and `GRAPH_MAX_PAIRS=1300`.

| Measured | Value |
|---|---|
| Candidate pairs at 0.60 / 0.65 / 0.70 / 0.75 | 4,984 / 2,457 (k=6) / 1,396 / 469 |
| Pairs judged | 1,300 in 39 calls, 0 missing from output, 0 fallbacks |
| Verdicts | different 922, same_ask 346, same_issue_opposite_side 17, unsure 15 |
| Judge cost (S4 only) | $10.8857; with the S1 judge calls $11.6831 |
| Wall clock | 2 min 37 s |

What the 0.70 floor cost, read from the terminal during S1 (S4 overwrote S1's `pairs.parquet` and
the S1 judge answers, so this cannot be rechecked from files): 84 of 97 `different` pairs, 1 of 5
`same_ask` pairs and 1 of 2 `unsure` pairs sat below 0.70. The floor drops mostly negatives, and
some merges.

## Issues

| Measured | Value |
|---|---|
| Issues | 605 from 859 claims (0.704 issues per claim, 1.66 per passage) |
| Sizes | 1: 489, 2: 61, 3: 20, 4: 19, 5: 6, 6: 3, 7: 3, 8: 1, 10: 1, 12: 1, 13: 1 |
| Issues backed by 2 or more distinct letters | 83; by 3 or more, 33 |
| `evidence_type` flag | 214 (35.4%) |
| Contested merges | 16; giant issue 1 (I00590, 4 of the 8 claims in 141.93, one letter) |
| Campaigns | 2 campaigns (4 and 2 letters) reach 69 claims; largest `n_letters_incl_copies` is 9 |
| Review rows, all stages | 184: `no_section` 63, `linker_disagrees` 46, `section_disagrees` 43, `contested_merge` 16, `judge_unsure` 15, `giant_issue` 1 |
| Review load, two readings | rows over claims 184 / 859 = 21.4%; distinct claims named in a row 139 / 859 = 16.2% (26 claims carry two rows, 17 rows are issue-level) |

The spec's 20% bar was written as rows over claims and the pilot fails it by that reading. By
distinct claims it passes. The difference is 26 claims with two or more rows (21 flagged by both
the linker cross-check and the section check, 5 by `judge_unsure` plus another reason) and 17 rows
that name an issue rather than a claim. Both numbers are in `results.json` so the reader can pick.

Most-backed issues:

| Issue | Section | Letters | Claims | Label (medoid ask) |
|---|---|---|---|---|
| I00328 | 141.85 | 8 | 10 | Retain the 30-day deadline for notifying customers of tap sample results below the action level instead of three days |
| I00166 | 141.84 | 7 | 12 | Remove the requirement to identify previously replaced lead connectors and make the "Replaced Lead" category optional |
| I00178 | 141.84 | 6 | 7 | Allow systems to partially replace and reconnect service lines during planned infrastructure work |
| I00477 | 141.90 | 5 | 6 | Reduce the number of certifications required under the rule |
| I00535 | 141.92 | 4 | 8 | Keep the school sampling waiver but remove the requirement in § 141.92(h)(5) that qualifying monitoring occur after a date |

## S5: eval against the final rule

Labels: `eval/parse_preamble.py` on 2024-23549 found 324 headings, 35 comment blocks and 417
paragraphs (163 summary, 134 response, 120 other). The summary paragraphs yield 489 points: 408
with an explicit response (208 in the same paragraph, 200 in the next one or two) and 81 without;
28 are catch-all (B33 state reporting 13, B34 economic analysis 15). 96 of the 163 summary
paragraphs carry the response in the same paragraph, so the cut between a commenter's point and the
agency's answer is heuristic there. B32 has no points, so block recall is over the blocks with a
sampled point, 33. B05 cites § 142.50, a section with no claims, so its 22 points (9 in the sample)
cannot match by construction.

The parser was revised after the code review (below): the pre-revision run had 575 points, of
which 116 were agency sentences; 459 survived and 30 were added. The samples below are the
pre-revision seeded samples restricted to the surviving points, so no re-sampling was needed and
every retained verdict was reused.

Matching: bge-small top-3 candidate issues per point, Fable yes/no, 10 points per call
(`eval/match.py --per-call 10`). A catch-all point sees the issues of every section. The pipeline
was scored on a seeded block-stratified sample of 250 points, 199 after the revision (190 with
candidates; the 9 without are B05). At $0.15 to $0.21 per call the three baselines could not be
run on the full sample inside the cap, so all four systems were compared on a nested sample of 99
points, 77 after the revision (73 regular, 4 catch-all, 74 with candidates).

### Pipeline alone, 199 points

| Metric | Value |
|---|---|
| Point recall, top-3 (188 regular points) | 22.9% [15.0, 31.2] |
| Point recall, top-2 | 17.6% [10.3, 24.5] |
| Catch-all points (11) | 1 (9.1%) |
| Block recall | 20 of 33 (60.6%) [42.4, 75.8] |
| Points matched by at least one issue | 44 of 199 |

### Four systems, the same 77 points

| System | Issues | Block recall (33) | Point recall top-3 (73) | Top-2 | Catch-all (4) | Match rate per candidate |
|---|---|---|---|---|---|---|
| pipeline | 605 | 12 (36.4%) | 23.3% [12.1, 33.8] | 16.4% | 0 | 8.6% |
| B0 passages as issues, one per cited (passage, section) | 472 | 12 (36.4%) | 21.9% [12.0, 32.9] | 21.9% | 0 | 10.8% |
| B1 cosine clustering, threshold 0.76 | 583 | 14 (42.4%) | 27.4% [16.0, 39.0] | 21.9% | 0 | 11.3% |
| B2 12 Oct positions | 507 | 14 (42.4%) | 34.2% [21.5, 45.6] | 24.7% | 0 | 13.5% |

Paired on the 73 regular points, top-3:

| Against the pipeline | Both hit | Pipeline only | Other only | Neither | Difference, points of recall |
|---|---|---|---|---|---|
| B0 | 10 | 7 | 6 | 50 | -1.4 [-11.6, +9.4] |
| B1 | 14 | 3 | 6 | 50 | +4.1 [-4.8, +14.9] |
| B2 | 9 | 8 | 16 | 40 | +11.0 [-3.5, +25.4] |

Any system hit 35 of 77; all four hit 5.

G3 (judge beats B1 on point recall at matched compression, or on two-reader cleanliness) is
failed on recall: B1 is 4.1 points ahead on 9 discordant points, and every interval includes zero,
so the judge is not shown to be better or worse than clustering the same embeddings. It costs
$10.89 and 39 calls more. Cleanliness waits for the readers. On this evidence B1 ships and the
judge is cut, unless the reader pack shows the judge's issues are cleaner by enough to matter.

Two cautions on the comparison. The systems are judged through their labels: B0 shows the judge a
60-word passage excerpt, B2 a polished position statement, the pipeline a single medoid ask. A
longer or cleaner label is easier to match. And 73 points means one point is 1.4 percentage
points.

### Significance

| Flagging rule (k = 214) | Recall on explicit-response points, 166 (199 sample) | 64 (77 sample) |
|---|---|---|
| `evidence_type` rule, as built | 9.0% | 4.7% |
| flag all 605 issues | 22.9% | 25.0% |
| top 214 by `n_letters` | 8.4% | 6.3% |
| top 214 by passage words | 12.0% | 10.9% |

An explicit-response point is one whose paragraph carries the agency's answer or is followed by a
response paragraph (85 and 81 of the 166). The rule flags 35% of issues and catches 15 of 166
such points. Flag-all is the ceiling the matcher allows (38 of 166), and the rule sits with the two
no-model orderings. The rule is cut as a significance signal; `evidence_type` stays as a column.

### Intervals

`score.py` resamples preamble blocks with replacement, 1,000 draws, seed 215, and takes every point
of each drawn block, because the points of one block share a section and a candidate pool. The
same draws score every system, so the paired differences above get their own intervals. With
33 blocks and most hits in a few of them the intervals are wide; they bound the sampling error of
the point set, not the matcher's own error.

## Comparison with the 12 Oct Sonnet reading

| Item | 12 Oct, Sonnet | This run, Fable |
|---|---|---|
| Passages read | 896 (custom split of the largest organisation letters) | 364 (passage-stage passages with a resolved citation) |
| Claims or asks | 683 asks, at most one per passage | 859 claims, 2.36 per passage, 293 passages with more than one |
| Quotes verified first pass | 680 of 683 (99.6%) | 859 of 859 (100%) |
| Quote re-ask calls | 3 | 0 |
| Asks shortened by script | 265 shortened, 15 quotes cut to 30 words | none; no word cap |
| Positions or issues | 507 | 605 |
| With 2 or more organisations or letters | 70 | 83 |
| Collisions / opposite-side pairs | 60 marked, 16 confirmed | 17 `same_issue_opposite_side` verdicts, unaudited |
| Faithfulness | 42 of 50 (Opus judge) | reader pack of 50 built, not yet read |
| Cleanliness | 19 of 30 (Opus judge) | reader pack of 30 built, not yet read |
| Model calls | 162 | 139 (150 with the re-judging) |
| Cost | $6.10 (Sonnet $5.27, Opus $0.83) | $38.40 ($40.23 with the re-judging) |
| Point recall against the final rule | not measured; B2 here is those 507 positions, 34.2% | 23.3% on the same 73 regular points |

The 12 Oct positions out-recall this run's issues on the shared points. They were built over more
passages (896 against 364) and their labels are one-sentence statements written by the model, so
part of the gap is coverage and part is label form.

## Cost and calls

| Ledger | Calls | USD | Cache-write tokens | Output tokens | Model seconds |
|---|---|---|---|---|---|
| extract (S1 + S3) | 40 | 17.5051 | 174,519 | 280,279 | 2,928 |
| judge (S1 + S4) | 45 | 11.6831 | 356,035 | 91,230 | 1,134 |
| match, pipeline (24 pilot + 1 re-judge) | 25 | 3.9832 | 90,439 | 43,479 | 512 |
| match, B0 (10 pilot + 8 re-judge) | 18 | 3.7408 | 98,463 | 35,423 | 452 |
| match, B1 (10 + 1) | 11 | 1.7530 | 37,092 | 20,218 | 232 |
| match, B2 (10 + 1) | 11 | 1.5653 | 31,778 | 18,590 | 217 |
| Total | 150 | 40.2305 | | | |

The pilot's own 139 calls cost $38.3965 against the $40 cap. The 11 re-judging calls after the
code review cost $1.8339 (per call $0.04 to $0.25) and are the ledger rows whose tag ends in a
content hash rather than a batch number.

`cache_read_tokens` is 0 on every row: `claude -p` writes each prompt to the cache and never reads
it back. The SDK backend puts the section context before a cache breakpoint; S2 would measure the
saving. Prices are the CLI's own `total_cost_usd`. Calls across S1 to S5: 150 against the spec's
bound of 821, because points were batched 10 to a call and pairs were capped.

## Five worst errors

1. **I00478** (merge). 13 claims from 3 letters on the 10-day reporting deadline in § 141.90(a)(2).
   C000653 (submit updated sampling plans after sampling) and C000682 (reconcile the tap monitoring
   and tap sampling period definitions in § 141.2) do not ask for the deadline change and were
   joined by chained `same_ask` verdicts.
2. **C000415** (extraction). The quote is the EPA's own preamble sentence, quoted back by the
   commenter: "At this time, EPA does not expect to propose changes to the requirement for
   information to be submitted in the initial LSL inventory". Stance `oppose`, `ask` null,
   `evidence_type` `legal`. It is not a claim, and the `legal` tag flags its issue.
3. **C000737** (evidence). Quote "we recommend that EPA expand the window allowable for waivers from
   the school sampling requirements" carries `data`, `alternative` and `experience`. No number,
   study or measurement is in the quote. C000371 is the same pattern: `data` on "EPA is forcing many
   utilities to grossly accelerate their lead service line replacement rates". 3 of the 14 `data`
   claims have no digit in the quote; 8 of 27 `legal` claims have no statute, case or authority
   word.
4. **C000075, C000076** (section). "The definition of 'small water system' should be the same for
   all parts of the LCRI" and "The definition of 'connector' should be increased from two feet to
   three feet" sit under § 141.81 because that is the section the passage cited. The model answered
   `none` (63 such rows). The harness rule "the citation wins" put definitions claims in the
   corrosion-control section, where no definitions point can reach them.
5. **B27-03-02, B27-03-03** (labels). In the pre-revision labels, "The purpose of allowing water
   systems to deliver the notification by a voice phone call is to make it easier ..." (B21-20-04)
   was the agency's answer counted as a commenter's point and as a recall hit for I00328. The
   revised cut removes that sentence and 115 others that open as the agency speaking. Agency
   sentences with no such opener survive: in B27 paragraph 3, "The PN Rule includes minimum
   requirements for what kind of information must be included" and "States have the authority to
   implement their own requirements" still stand as points. The 40-item boundary check in the
   reader pack measures the remaining rate.

## Where it fails

- The pair judge adds $10.89 and 39 calls and does not beat cosine clustering on the same
  embeddings: 23.3% against 27.4% top-3 recall on 73 points, the difference inside its interval.
- The `evidence_type` rule flags 35% of issues and recalls 9% of the points the agency answered
  explicitly. `evidence_type` is too often assigned without the evidence being in the quote.
- Issues are per section; `no_section` claims (63) are forced into the cited section, so a
  definitions claim in a § 141.81 passage never meets the definitions block.
- Review load is 21.4% by rows (above the 20% bar) and 16.2% by distinct claims (under it), driven
  by section disagreement (106 rows) and the linker cross-check (46 rows).
- 13 of 33 blocks have no matched point in the 199-point sample. B23 (schools and child care, 30
  points, 13 sampled) has zero hits although 109 claims cite § 141.92. B05 cites a section with no
  claims.
- The spec's cosine floor of 0.60 is a $38 judge at Fable prices for 859 claims; the run used 0.70
  and a 1,300-pair cap.
- 9 cited passages returned zero claims; 194 claims have no `ask`.
- Two campaigns reach the cited passages (69 claims). Everything else here is organisation letters;
  "who is behind it" is campaign id and state only.
- Labels come from one rule and one agency, at summary level. 96 of 163 summary paragraphs carry
  the response in the same paragraph, and agency sentences without a recognisable opener survive
  the cut (error 5 above).
- The four-system comparison rests on 73 regular points; one point is 1.4 percentage points and
  every paired interval includes zero.

## Not done

| Step | Status |
|---|---|
| S2 SDK parity, effort choice | no `ANTHROPIC_API_KEY` in `.env`, so `cache_read_tokens` is unmeasured |
| S6 readers | pack rebuilt after the revision in `argument-graph/eval/pack/out/` (claims 50 over all 15 sections, issues 30, flagged 30, matches 60, boundaries 40, seed 215); not returned |
| Baselines on the full pipeline sample | budget; 77 shared points instead |
| Reader check of the match judge | in the pack, 60 items |
| Docker image build of `argument-graph` | not built; run with `uv run` on the laptop |
| `summary.json` fields `review_claims_distinct`, `review_claims_share` | added to `export.py`; appear on the next run, `results.json` carries them now |

## Code changes made during the pilot

| File | Change |
|---|---|
| `src/llm.py` | `raw/<tag>.json` now stores the prompt's sha1; a cached answer to a different prompt under the same tag is a miss. Tags name batch positions, and the S1 smoke had left `extract_141.2_001` and six `judge_*` answers that did not match the full run's batches |
| `eval/match.py` | points batched per call (`--per-call`, default 10), threads, `--sample N --seed` for a shared stratified point sample, re-ask when a (point, issue) pair is missing, `points_scored.parquet` written beside the matches; `eval/prompts/match.md` and `schemas/match.json` carry `point_id` |
| `eval/score.py` | `--systems`; points restricted to the intersection of every system's scored points; `points_scored` in results |
| `eval/baselines.py` | B2 wrote `PART 141` for § 142.x positions; B2 crashed when a position's member and organisation lists differed in length (one row per member now) |

## Revision after the code review

A review of the eval code and of this document found eight defects and twelve wrong or
unsupported claims. What changed, and what it did to the numbers:

| Defect | Fix | Effect |
|---|---|---|
| The point cut recognised fewer response openers than the paragraph classifier, so agency sentences became label points (18 of 575 opened as the agency speaking; more followed them) | One pattern for both: a sentence opening "The EPA <verb>" (other than received, heard, proposed, requested), also after "In addition," and the like, ends the points. Paragraphs opening "The EPA also received ..." are now summaries, not responses | 575 points to 489: 116 removed, 30 added. Pipeline sample 250 to 199, shared sample 99 to 77. Pipeline top-3 recall 21.1% to 22.9% on its sample, 22.0% to 23.3% on the shared one |
| `has_explicit_response` recorded whether the answer sat in the same paragraph, not whether the agency answered | Also true when a response paragraph follows within two paragraphs with no summary between; `response_where` column says which | Explicit points in the pipeline sample 66 to 166; rule recall 6.1% to 9.0%, flag-all 25.8% to 22.9% |
| "Bootstrap over letters" kept an issue if any of its letters was drawn, a 63% subsample that can only lose hits; its interval excluded the point estimate | Percentile bootstrap over blocks, every point of a drawn block, the same draws for every system, paired differences | [0.099, 0.198] around 0.220 became [0.121, 0.338] around 0.233 |
| `BudgetExceeded` was raised before `raw/<tag>.json` was written, so the call that crossed the cap was paid for and discarded, and a rerun raised again before any work | The answer is written first; a live call is refused once over the cap, before anything is paid; cached calls never raise | none on this run (cap not reached) |
| Catch-all points were documented as matched against every section but masked to their block's citations when it had any | The code widens for every catch-all point | B33's 13 points see all 605 issues; 5 pipeline points, 2 B1 and 2 B2 points re-judged; one pipeline point (B33-04-00, state burden) now matches: one § 142.15 issue it could already see and two § 141.90 issues it could not |
| "strict" meant matched by any of the three candidates and "top-2" the stricter one | Metrics renamed `top3` and `top2` | names only |
| `n_letters_incl_copies` added `size - 1` per campaign however many of its letters were already counted | Adds each campaign's letters not already among the members | none on this run (no issue holds two letters of one campaign; checked over all 605) |
| The reader pack trimmed quota overshoot with `head(n)` in section order, dropping every Part 142 claim from the faithfulness sheet | Trimmed at random | claims sheet covers 15 of 15 sections |
| B0 put a multi-citation passage under its first link row, the pipeline under the extractor's choice | B0 is one issue per cited (passage, section): 472 issues from 364 passages | B0 re-judged on all 77 shared points (8 calls, $1.67): top-3 27.5% to 21.9% on a different point set |
| Two pre-revision cache files had no prompt hash and were accepted on the tag alone | The hash is required; the two files were back-filled after checking that every passage id in the answer is in the stored prompt; a cached answer is also validated against the schema | none |
| `frozen_test_top5: 0.902` was a literal in `score.py` | Read from `docs/evidence/linker-train/in-pre/metrics.json` | none |

Claims corrected in this document: the stale "85 of 174 summary paragraphs" and "304 headings"
from the parser docstring (now 96 of 163 and 324); review load stated under both definitions; the
numbers read from the terminal marked as such; the section counts summing to 472 explained; B05 and
B23 point counts given as totals and sampled; "1,539 letters read" corrected to 1,553 read and 14
skipped; the extract cost broken into S1, S3 and the duplicated batch; the per-call match price
given as the measured $0.15 to $0.21 range.

The re-judging used `eval/match.py --reuse`: the previous point set minus the points the parser no
longer emits, previous verdicts kept for every point whose candidate list is unchanged, only the
rest sent to the model. 11 calls, $1.8339, all on the ledgers above.

Tests and lint after the changes: `uv run pytest -q` 46 passed, `uv run ruff check .` clean.

## Files

| Path | Content |
|---|---|
| `data/derived/graph/EPA-HQ-OW-2022-0801/` | `claims`, `pairs`, `issues`, `claim_issues`, `review` parquet, `graph.json`, `summary.json`, `ledger.jsonl`, `prompts/`, `raw/` (not in git) |
| `argument-graph/eval/out/` | `points.parquet`, `blocks.json`, `headings.json`, `pipeline/`, `B0/`, `B1/`, `B2/` (matches, points_scored, ledgers, raw), `baselines/`, `results.json`, `results.md`, `pipeline_only/` (not in git) |
| `docs/evidence/argument-graph/` | `README.md`, `run.log`, `summary.json`, `ledger-excerpt.jsonl`, `results.md`, `one-claim-end-to-end.md` (passage `EPA-HQ-OW-2022-0801-0775:p016` through claim C000440 to issue I00328; its only matched point was an agency sentence and is gone after the revision), this file |
