# Codebook, argument graph reader pack, version 1.0

Adapted from the 11 October linking codebook (`undersigned2/humanset/pack/CODEBOOK.md`). Same
rules of conduct: work alone, do not discuss items with the other reader until both sheets are
locked, do not use an AI tool or a search engine on the text. Fill `seconds` with the time you spent
on the item, roughly.

Five sheets, one row per item. Seed 215, stratified by section or by preamble block.

| Sheet | Items | You judge |
|---|---|---|
| `claims_<reader>.csv` | 50 | whether the quote supports the ask and stance, and whether `evidence_type` is right |
| `issues_<reader>.csv` | 30 | whether the claims grouped as one issue belong together |
| `flagged_<reader>.csv` | 30 | whether the claim the flag rests on really carries data, a legal argument or an alternative |
| `matches_<reader>.csv` | 60 | whether a response written to the issue would answer the agency's point |
| `boundaries_<reader>.csv` | 40 | whether the point sentence is the commenters' point, not the agency's response |

## Claims

| Column | Values |
|---|---|
| faithful | `faithful`: the ask states a request the quote makes, and the stance is right. `partly`: related, but it overstates, narrows, or misses the main request. `wrong`: the quote does not ask this, asks the opposite, or asks nothing |
| evidence_ok | `yes` if every listed evidence type is present in the quote and none is missing; `extra` if a listed type is not there; `missing` if the quote carries a type not listed; `both` |
| notes | anything the adjudicator should know |

Evidence types: `data` (numbers, studies, measurements the commenter supplies), `legal` (statute,
case, authority), `alternative` (a different concrete requirement), `cost`, `feasibility`,
`experience`. A number the commenter quotes from the rule is not data.

## Issues

| Column | Values |
|---|---|
| clean | `clean`: every member asks the same thing of the same provision, or takes the opposite side of the same question. `one_stray`: exactly one member does not belong. `mixed`: two or more differ, or the group is only a theme. `duplicate`: the group is fine but another issue in the sheet covers the same point |
| stray | member claim ids that do not belong |
| notes | |

## Flagged

| Column | Values |
|---|---|
| carries | `yes` if the quote offers the kind of evidence the flag names; `no` if it only names the topic (a cost table without numbers is not `data`; "EPA lacks authority" with no statute or case is not `legal`) |
| notes | |

## Matches

| Column | Values |
|---|---|
| match | `yes` if an agency paragraph answering the issue would also answer the point; `partial` if it would answer part of it; `no` |
| notes | |

## Boundaries

| Column | Values |
|---|---|
| boundary | `ok`: the sentence is what commenters said. `response`: the sentence is the agency's answer. `mixed`: both in one sentence. `not_a_point`: background or restated proposal |
| notes | |

If two values seem to fit, pick the stricter one and say why in notes. Disagreements are settled
by the two readers together, never by a model.
