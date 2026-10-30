# Proposal: extend Undersigned from campaigns to the whole comment record

Working draft, 12 Oct 2026.

This builds on Aadil's A3 (the argument graph) in [`docs/agentic-proposals.md`](../agentic-proposals.md): pull the claims out of each letter, link each one to the provision it targets, and keep the quote on every link. What follows is mostly a test of that idea on real dockets, plus what it would mean for MS2. His B2 (docket watch) and A1 (sponsor investigators) are the natural next steps after it.

## What we learned running MS1 at full scale

I ran the grouping stage from our MS1 plan on two full dockets over the weekend. It held up better than we expected: a plain copy detector (shared 5-word runs) groups 96% to 99% of campaign mail, and an embedding model does worse. That is a good result. The baseline handles that stage, so it does not need a trained model, and it frees the semester for the part of MS1 that turned out to be hard: linking comments to the sections of the rule they argue about.

## The idea

Keep the topic, the data and the code. Change what the system reads.

Before: who is behind a mass comment campaign, on one EPA docket.

After: for any proposed rule, which sections people argued about, who argued, and what they asked for. Grouping form letters becomes the first step of the pipeline instead of the whole product.

## The user and the gap

Intended user: someone who has to know what a comment record says before a deadline. An analyst at an advocacy group or a law clinic writing a comment, a reporter covering a rule, agency staff summarizing a docket. We have not confirmed this with a real user yet. That is the first thing to fix.

Why it matters to them:

- Agencies have to answer the comments. "An agency must consider and respond to significant comments received during the period for public comment." Perez v. Mortgage Bankers Association (2015).
- Arguments nobody raises can be lost. "The doctrine of issue exhaustion generally bars a litigant challenging agency action from raising issues in court that were not raised first with the agency." Administrative Conference Statement #19, 80 FR 60611 (2015). The same statement says courts have made exceptions, so this is a general rule and not an absolute one.

Closest existing options and what they lack:

| Option | What it does | What it lacks |
|---|---|---|
| Regulations.gov search | Keyword search over comments, one document at a time | No view by section of the rule. No counts. |
| One deep-research request to a chat model | Reads the actual letters and gets its claims right (94% to 98% checked out, none made up) | It opened 35 to 49 letters per docket and reached 29% to 54% of the organizations in the record. It cannot count. |
| Contractor tools used inside agencies | Sorting and summarizing for the agency | Not public |
| Fan and Yao, "Who Gets Heeded?" (2026) | A research paper matching comments to rule changes on EPA rules | Finished rules only, one agency. One of us should read it closely before we cite it. |

## The central challenge

More than half of what people write about a rule concerns no single provision. In a sample of 180 passages, 80 were about one provision and 100 were not (81 of those were about the rule as a whole or several parts at once). So the hard part is deciding what a link between an argument and a provision is, measuring it when there is no single right answer, and doing it for a whole docket at a cost that works.

## What I measured

Prototypes on a laptop, real dockets, seven dockets across five agencies. Labels come from the citations commenters wrote, with the citation hidden from every method. Treat these as first readings.

| Method | Right section on the first guess | Cost per 1,000 passages |
|---|---|---|
| Keyword plus embedding search | 53.0% | about $0 |
| Reranker trained on the docket's own citing letters | 65.9% | about $0 |
| Small model | 69.0% | $1.29 |
| Reranker first, large model on the hardest 40% | 74.1% | $7.70 |
| Large model | 75.4% | $19.58 |

232 test passages. Other results:

- Only 3.7% of substantive comments cite a section, so the free labels are scarce and come from a few detailed letters.
- Word files are second copies of PDFs we already read, and scanned PDFs are few. The reader misses under 1% of the text.
- One filer attached other organizations' letters as exhibits. Without an exhibit check their arguments get counted twice.

## What I tried and dropped

- Five role-playing agents to forecast which sections draw comment: same ranking as one model call at 4.7 times the cost.
- Predicting which sections change in the final rule (91 rule pairs): 0.67, no better than the agency's base rate. The comment record added nothing.
- A trained model as the centerpiece: the small model beats our reranker without any labels. Training stays in the plan for MS3 only as a comparison it has to win.

## What changes in the code

| Component | Change |
|---|---|
| data-collector, data-processor, DVC, CI, status page | None |
| campaign-builder | None. It becomes the duplicate-removal step. |
| rule-passages, ChromaDB | Index paragraphs as well as sections. Take any docket. |
| New: mirror reader | Pull a docket from the public mirror of Regulations.gov (no rate limit, attachment text included) |
| New: passage and citation stage | Split substantive comments into passages, read section citations |
| api-service, frontend | Sections endpoint and a rule page |

See `ms2-tasks.md` for how this maps onto our tickets.

## Evaluation labels: what they are

For 180 sampled passages I had two language models label independently and a third pass settle disagreements (they agreed on 87%). These are model-made labels. No person has checked them yet. One of us needs to label a blind sample of 30 so we can say how good they are, and until then nothing should be described as human-labeled.

## Who benefits, who could be harmed

- Benefit goes first to groups that already have staff reading dockets. It lowers the cost for smaller ones.
- An organization could be credited with an ask it did not make. Every quote shown has to be checked against the source letter, with a link.
- Organized commenters cite sections and individuals mostly do not, so a map by section can make the record look more organized than the public was. We report how much of the record is linked and keep a visible bin for arguments that are not about one section.
- We do not show individual people's names. Signer names stay hashed, as now.
- We do not generate comment letters for submission. Reworded letters are only a stress test of our own detector, as planned in MS1, and stay internal.
