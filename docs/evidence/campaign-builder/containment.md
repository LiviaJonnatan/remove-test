# Containment grouping on the lead and copper docket

Ticket U-05 (#5). 16 Oct 2026, laptop. Letters are the processor's output for docket
EPA-HQ-OW-2022-0801. No letter text is reproduced here.

## How to reproduce

```
# the 40-record sample: the default .env (RECORD_IDS_FILE=/app/samples/ms2_ids.txt)
docker compose run --rm --no-deps --build data-processor
cp -r data/derived/letters/EPA-HQ-OW-2022-0801 ../sample-letters

# the whole docket: in .env, set RECORD_IDS_FILE= and MAX_RECORDS= (empty), then
dvc pull data/raw/EPA-HQ-OW-2022-0801.dvc
docker compose run --rm --no-deps --build data-processor     # about 20 minutes

cd campaign-builder
uv run python scripts/evaluate_containment.py \
    --sample ../../sample-letters/letters.parquet --ids ../data-collector/samples/ms2_ids.txt \
    --docket ../data/derived/letters/EPA-HQ-OW-2022-0801/letters.parquet
```

The script prints both tables and every check below except the reading of groups. The whole-docket run
gives 1,589 records and 1,553 letters; the other 36 are bundled campaign records that need a reviewed
plan before the processor splits them.

## The 40-record sample, where the campaigns are known

`data-collector/samples/ms2_ids.txt` marks 10 letters from each of two campaigns, 10 organization letters
and 10 individual comments. Scored with B-cubed against those two campaigns:

| Grouper | Campaign letters grouped (of 20) | Groups for them | Other letters grouped | F1 |
|---|---|---|---|---|
| Exact match | 2 | 1 | 0 | 0.20 |
| MinHash, Jaccard 0.8 | 2 | 1 | 0 | 0.20 |
| MinHash, Jaccard 0.3 | 17 | 4 | 0 | 0.65 |
| Containment 0.4 | 20 | 2 | 0 | 1.00 |
| **Containment 0.5 (default)** | **18** | **2** | **0** | **0.91** |
| Containment 0.6 | 17 | 3 | 0 | 0.75 |

The two letters missed at 0.5 are short versions of the second campaign. They hold 0.47 and 0.41 of
the template the other nine letters share. An earlier version grouped them, but only because each
letter's own phrases counted toward the template it was tested against. The threshold stays at 0.5:
20 letters are too few to set it by, and on the whole docket 0.4 and 0.5 differ by 21 letters.

Between letters of one campaign, the median Jaccard of five-word phrases is 0.24 and 0.37, and the
median containment is 0.53 and 0.70. Between letters that are not in the same campaign, containment is
at most 0.24.

## The whole docket, where there is no answer key

| Grouper | Letters grouped | Groups | Largest groups | Time |
|---|---|---|---|---|
| Exact match | 26 | 13 | 2, 2, 2, 2, 2, 2 | 0.2 s |
| MinHash, Jaccard 0.8 | 53 | 22 | 6, 4, 3, 3, 3, 2 | 1.8 s |
| Containment 0.4 | 480 | 47 | 164, 78, 52, 18, 16, 14 | 13.1 s |
| **Containment 0.5 (default)** | **459** | **48** | **160, 64, 48, 15, 14, 14** | **8.1 s** |
| Containment 0.6 | 422 | 42 | 156, 52, 46, 15, 14, 12 | 7.6 s |

Checks:

- **Each large group is one campaign.** The eight largest were read, by the sentences most members
  share. Each has one template: support for replacing all lead pipes by 2037 and its health benefits
  (160); the count of people served water above 1 and 5 ppb of lead (64); thanks for stronger rules and
  their effect on low-wealth communities (48); holding Chicago to the 10-year replacement standard (15);
  a state NAACP conference's comments (14); replacing every line in 10 years with no exceptions and at no
  cost to households, and an action level of 5 ppb (14); requiring school testing and utility-paid full
  replacement (12); a one-line request to replace lead pipes equitably and quickly (11).
- **Every grouped letter fits what the rest of its group shares.** `similarity` is a letter's
  containment of the template of the other members; the lowest of any grouped letter is 0.50. The code
  enforces this and the tests check it.
- **Some members share a template but not each other's words.** In the 64- and 48-letter groups, 15 and
  11 pairs of members share under 10% of their phrases. These are short letters that quote different
  parts of a long template; each holds at least half its own phrases from it.
- **Stable across thresholds.** Over the letters either run groups, with an ungrouped letter as a group
  of one, B-cubed F1 against 0.5 is 0.92 at 0.4 and 0.90 at 0.6.
- **The candidate shortcut loses nothing.** A run that skips no boilerplate phrase and checks every
  candidate assigns all 1,553 letters the same way.
- **Close to an independent count.** An earlier analysis of this docket's public mirror, by shared phrase
  runs, found campaigns of 142, 62 and 52 letters. Containment finds 160, 64 and 48.

## What the passage stage reads

The passage stage reads the letter each group is named after (the member holding the most of the
template) in full, and every other member only for sentences not already read in its group.

| Grouping | Letters read whole | Read for their own sentences | Skipped | Passages | Citing passages | Links to the rule |
|---|---|---|---|---|---|---|
| Exact match, whole docket | 1,540 | 1 | 12 | 5,898 | 380 | 483 |
| Containment, whole docket | 1,142 | 397 | 14 | 5,409 | 369 | 472 |
| Containment, sample | 24 | 15 | 1 | 816 | 158 | 208 |

On the whole docket, fewer passages cite the rule under containment because a template sentence with a
citation is read once per campaign rather than once per letter. The same 15 sections are cited. On the
sample, the 158 citing passages and their 209 links are the same ones the exact-match run writes, so
the retrieval baseline table does not change.

## What it fixed along the way

- A first version assigned each letter to the first letter of a group it fit. It split the largest
  campaign into five groups, because several early letters started groups before the template was
  clear. A merge pass over group templates joined them.
- Merging everything connected at once then chained a short campaign into an unrelated long one through
  middle-sized groups. Merging one pair at a time, with the template recomputed, fixed it.
- Review of #74 found four more. A pair's template was everything either letter had, so a third letter
  could join through one member's own words (on the development docket, two letters sharing 4% of their
  phrases ended up together). A letter holding two campaigns' templates bridged both. Letters dropped
  from a group could never form their own. And the passage stage read only each group's first letter,
  skipping 381 letters of their senders' own words. Templates are now the phrases most members share,
  letters are compared with templates rather than with a group's first letter, each member is tested
  against the template of the others, dropped letters are regrouped, and the passage stage reads every
  member's own sentences. Each case is a test.
