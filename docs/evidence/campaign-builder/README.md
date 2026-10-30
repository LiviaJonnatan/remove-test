# campaign-builder evidence

Ticket U-09 (#9): exact-match grouping and the B-cubed scorer, plus the minimum-length rule from #40. Captured on 12 Oct 2026 on a laptop.

| File | What it shows |
| --- | --- |
| `pytest.txt` | The 20 offline tests by name, and a clean `ruff check` |
| `exact-match-inline.log` | The grouper run on the 3,967 inline comment bodies of the development docket: 62 letters in 17 exact-match groups, 3,905 individual comments, and every group's size |

## What the run does and does not show

The letters file for this run was built from the raw detail records' `comment` field, keeping bodies longer
than 200 characters. That is a stand-in for the data-processor's `letters.parquet` (U-04), which does not
exist yet, so three things are missing:

- Letters inside campaign attachments. The 13 full-letter campaigns hold about 116,000 letters in PDFs the
  processor extracts. Those are where exact copies live; the inline bodies are mostly individually written.
- `epa_campaign_id`, EPA's grouping, which only exists for those attachment letters. Without it there is
  nothing for B-cubed to score against, so the log has no F1.
- The 50-record sample the MS2 chain runs on. When the processor writes it, the same command runs on it.

The two largest groups (14 and 13 copies) are form letters, one asking EPA to repeal the 2015 rule and one
opposing the proposal. No letter text or submitter detail is reproduced here.

## Reproduce

```bash
cd campaign-builder
uv run pytest -v
uv run python src/exact_match.py --letters <letters.parquet> --out assignments.parquet --score
```

`--score` prints B-cubed precision, recall and F1 against `epa_campaign_id` when the letters file has it.
