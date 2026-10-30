# rule-passages evidence

Real runs of the `rule-passages` container against the live ChromaDB service from `docker-compose.yml`.
It indexes the 2019 proposed rule (`84 FR 4154`, document 2019-00791), the document the comments on docket
`EPA-HQ-OW-2018-0149` answered, collected from the Federal Register API on 9 Oct 2026.

| File | What it shows |
| --- | --- |
| `run-cold.log` | `docker compose run --rm rule-passages` from nothing: four documents downloaded, 538 chunks of the proposed rule embedded in 22 s |
| `run-rerun.log` | The same command again: 538 chunks, 0 embedded, 0 pruned. Chunk ids and a hash of each chunk make reruns free |
| `section-outline.txt` | Every section of the proposed rule with its first page and chunk count, procedural sections marked. These are the section references a hand label can name |
| `query-letter-*.json` | Top 3 passages from BM25 and from the embedding search for three real comments, as the code returns them |
| `baseline.md` | U-28 (#45): how often BM25, embeddings and the two combined find the section a lead and copper comment passage cites, on the 158 citing passages of the 40-record sample |

## One retrieval flow, query to retrieved context

**Query.** Comment `EPA-HQ-OW-2018-0149-0390`, anonymous public comment, 729 words, HTML removed:

> The EPA and the Department of the Armys proposed rule revises the definition of the WOTUS specifically focusing on defining tributaries and adjacent wetlands. By defining these two terms, the rule significantly excludes federal protection for ephemeral streams that pool or flow with precipitation. Waters that intermittently flow would only be protected if surface water ...

**Retrieved context** (`python src/main.py query --file letter_0390.txt --method both -k 3`):

| Retriever | # | Score | Citation | Section | Heading | Passage (start) |
|---|---|---|---|---|---|---|
| bm25 | 1 | 72.02 | 84 FR 4154, p. 4177 | `III/D/1` | D. Tributaries > 1. What are the agencies proposing? | The agencies also solicit comment on other implementation tools available to determine the flow regime of a river or str... |
| bm25 | 2 | 64.49 | 84 FR 4154, p. 4173 | `III/D/1` | D. Tributaries > 1. What are the agencies proposing? | The agencies recognize that perennial or intermittent flow in certain mountain streams, for example, may result primaril... |
| bm25 | 3 | 58.64 | 84 FR 4154, p. 4173 | `III/D/1` | D. Tributaries > 1. What are the agencies proposing? | The agencies propose to define the term “perennial” to mean surface water flowing continuously year-round during a typic... |
| dense | 1 | 0.83 | 84 FR 4154, p. 4173 | `III/D/1` | D. Tributaries > 1. What are the agencies proposing? | Similarly, such a wetland would be considered “adjacent” and thus jurisdictional under this proposal given the wetland a... |
| dense | 2 | 0.83 | 84 FR 4154, p. 4173 | `III/D/1` | D. Tributaries > 1. What are the agencies proposing? | The agencies intend to distinguish flow resulting from snow fall from sustained flow resulting from melting snowpack in ... |
| dense | 3 | 0.81 | 84 FR 4154, p. 4173 | `III/D/1` | D. Tributaries > 1. What are the agencies proposing? | In this proposed rule, the agencies would retain tributaries as a category of jurisdictional waters subject to CWA juris... |

All three of the BM25 passages and all three of the embedding passages are in section III.D, Tributaries, which is what the
letter argues about (ephemeral and intermittent streams).

## Linking whole campaigns to rule sections: what the first pass showed

The same code, run on every campaign of the development docket. The data was re-pulled from the Regulations.gov
API, and it reproduces the MS1 numbers exactly:

| | MS1 | Re-pulled |
|---|---|---|
| Campaign records | 201 | 201 |
| Comments they stand for (`duplicateComments`) | 507,230 | 507,230 |
| Campaigns with no known sponsor | 92 | 92 |
| Largest campaign without a sponsor (CREDO Action, record 4291) | 66,777 | 66,777 |

A letter was found for 193 of the 201 campaigns, covering 487,999 of the 507,230 comments: 46 from the record's own
text, 141 from the first pages of an attached PDF, 6 by OCR of a scan. Eight had none we could use.

**Finding 1: procedural text swallows the results.** Nine of the 538 chunks are procedural (summary, dates,
addresses, general information). With them searchable, the top hit was one of those nine for 116 of 193 campaigns
under BM25 (52% of comment volume) and for 41 of 193 under embeddings (39% of volume). Campaign letters quote
"Docket ID", "comment" and the Administrator's name, which those short passages are made of. They are now marked
`procedural` and left out of retrieval by default. The text is still in the index, so the effect can be
reproduced with `include_procedural=True`.

**Finding 2: the two retrievers disagree, and nothing here says which is closer.** With procedural text excluded,
BM25 and the embedding search return the same top section for 8 of 193 campaigns, and share any section in their
top 3 for 66 of 193. Embeddings put 73% of comment volume on one Background section (II/B); BM25 spreads it
across III/D (23%), II/D (19%), II/B (17%), II/E (16%) and VI/K (15%).

This is a first pass with no answer key. It does not say either retriever is right. That needs hand-mapped
campaigns, so the next step is a labeling sheet of 50 campaigns (5 shared by everyone to measure agreement, 9
each), then `eval` and `sweep` on the result.

## Reproduce

```bash
# these logs are from the development docket: set DOCKET_IDS=EPA-HQ-OW-2018-0149 in .env first
docker compose up -d chromadb
docker compose run --rm rule-passages                       # collect, chunk, embed, load
docker compose run --rm rule-passages python src/main.py outline
docker compose run --rm rule-passages python src/main.py query --text "The rule removes protection for ephemeral streams and intermittent tributaries"
```
