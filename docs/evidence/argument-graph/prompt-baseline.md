# B3: one good prompt per section vs the harness (LCRI, § 141.84)

Run 30 Oct 2026, `argument-graph/eval/prompt_baseline.py`, model claude-fable-5-1 via `claude -p`.
Same input as the pipeline: the cited passages of § 141.84 (107 passages). One call: every passage
plus the section's opening text, asked for the response-to-comments brief (asks, stance, evidence,
supporting passages with verbatim quotes). The run was stopped after § 141.84 to cap spend, so this
compares one section only.

| System | Issues on § 141.84 | EPA points found (42 shared points) |
|---|---|---|
| Pipeline (extract + judge) | 148 | 10 (23.8%) |
| B0 passages as issues | 107 | 10 (23.8%) |
| B1 cosine clustering | 140 | 13 (31.0%) |
| B2 12 Oct Sonnet positions | 113 | 14 (33.3%) |
| **B3 one prompt** | **54** | **9 (21.4%)** |

| B3 check | Result |
|---|---|
| Quotes verbatim in the named passage (string match) | 159 of 159 |
| Quotes attributed to the wrong letter | 0 |
| Passages cited by the brief | 101 of 107 |
| Issues backed by 2+ letters | 31 |

Cost: § 141.84 cost $2.54 for the successful B3 call; a first attempt returned the wrong JSON shape
and cost $2.67. The pipeline's calls tagged § 141.84 cost $7.63. Matching B3 against EPA's points
cost $0.75. Total spent on this comparison: $7.47.

What it says: on one section with 107 passages, one prompt matches the harness on recall (one
point apart out of 42, well inside noise), quotes as faithfully, and groups into fewer issues. The
harness adds no measured accuracy at this size. Every system finds 21% to 33% of EPA's points, so
the limit is the input (passages that cite a section), not the method.
