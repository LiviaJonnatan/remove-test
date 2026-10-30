# api-service evidence

Real runs of the `api-service` container (`docker compose up -d --build --no-deps api-service`) against the
ChromaDB service from `docker-compose.yml`, after `docker compose run --rm rule-passages` had loaded the
538 passages of the 2019 proposed rule (`84 FR 4154`). First captured on 9 Oct 2026 (#35); re-captured on
13 Oct 2026 after `k` went up to 50 and `method="merged"` was added (#37), on 15 Oct 2026 for
`GET /rules/{docket_id}/sections` (#46), and on 16 Oct 2026 for citation counts and citing passages on
the lead and copper sample (#46, PR B). All on a laptop.

| File | What it shows |
| --- | --- |
| `startup.log` | The container's log: 538 passages loaded at startup, then the four letter-0390 requests below (`both`, `merged` with `k=3`, `merged` with `k=50`, `k=51`) with their status codes |
| `curl-session.txt` | `/health`, `POST /retrieve` with both retrievers, a merged list, `k=50` accepted, a docket the index does not hold (no hits), and a bad request (422 naming all three wrong fields, including `k` above 50) |
| `retrieve-letter-0390.json` | The full response for a real comment, `EPA-HQ-OW-2018-0149-0390` (anonymous), with `k=3` and both retrievers. Re-run on 13 Oct: same passages, same scores |
| `retrieve-letter-0390-merged.json` | The same letter with `k=3` and `method="merged"` |
| `sections-session.txt` | `/health`, then `GET /rules/EPA-HQ-OW-2018-0149/sections` printed as a tree for section III and `PART 328`, then a docket the index does not hold (404 naming the one it does) |
| `sections-EPA-HQ-OW-2018-0149.json` | The full sections response: 61 sections, 16 at the top level |
| `sections-startup.log` | The rebuilt container's log for the sections session: 538 passages loaded, then each request with its status code |
| `lead-session.txt` | `/health` (1,649 passages, both dockets), sections of the lead and copper rule with filled counts, the 2019 rule still null, then `GET /rules/.../passages` (a page of § 141.84, PART 141's total, preamble `V/B` empty, 2019 unknown, 404, 422) |
| `passages-141.84.json` | The first page of comment passages citing `PART 141/§ 141.84` (`total` 39, `limit` 2) |
| `lead-startup.log` | The rebuilt container: no links for the 2019 docket, 204 links for lead and copper, 1,649 passages loaded, then the lead-session requests |
| `pytest.txt` | The 47 offline tests, by name |

## Same answer as the rule-passages command line

`retrieve-letter-0390.json` is the API's answer for the letter used in
[`../rule-passages/query-letter-0390.json`](../rule-passages/query-letter-0390.json), which came from
`python src/main.py query` in the rule-passages container. The six hits are the same passages in the same
order with the same scores:

| Retriever | # | Passage | Score (API) | Score (command line) | Section |
|---|---|---|---|---|---|
| bm25 | 1 | `2019-00791:0187` | 72.0219 | 72.0219 | `III/D/1` |
| bm25 | 2 | `2019-00791:0159` | 64.4882 | 64.4882 | `III/D/1` |
| bm25 | 3 | `2019-00791:0158` | 58.6361 | 58.6361 | `III/D/1` |
| dense | 1 | `2019-00791:0161` | 0.8297 | 0.8297 | `III/D/1` |
| dense | 2 | `2019-00791:0160` | 0.8252 | 0.8252 | `III/D/1` |
| dense | 3 | `2019-00791:0155` | 0.8092 | 0.8092 | `III/D/1` |

So the image runs the same retrieval code and the same model as rule-passages. The API's hits also carry
`docket_id` and `document_number`, which `Hit.to_dict()` added after the command-line evidence was saved.

## Merged list

`retrieve-letter-0390-merged.json` is the same letter with `"method": "merged"`. Each retriever is searched
50 deep, and a passage scores `1 / (60 + rank)` for every list it appears in. The ranks below come from
asking the same container for `bm25` and `dense` with `k=50`:

| Merged # | Passage | Rank in BM25 | Rank in embeddings | Fused score | Section |
|---|---|---|---|---|---|
| 1 | `2019-00791:0160` | 34 | 2 | 1/94 + 1/62 = 0.0268 | `III/D/1` Tributaries |
| 2 | `2019-00791:0010` | 27 | 6 | 1/87 + 1/66 = 0.0266 | `II/A` Executive summary (its definition of a tributary) |
| 3 | `2019-00791:0157` | 9 | 26 | 1/69 + 1/86 = 0.0261 | `III/D/1` Tributaries |

On this letter the two retrievers mostly disagree. Only 8 passages are in both top-50 lists, and of the six
passages in the `both` answer only `0160` is one of them. Fusion puts those 8 first, because any passage in
both lists (at least 1/110 + 1/110 = 0.0182) beats any passage in only one (at most 1/61 = 0.0164). The
other five passages from the `both` answer come back at merged ranks 9 to 13. So a reranker reading the
merged top 30 sees every passage `both` would have returned, plus the ones both retrievers agree on.

## Sections of the rule

`sections-EPA-HQ-OW-2018-0149.json` lists 61 sections of the 2019 proposal: the 53 `section_ref`s that hold
rule text, plus 8 headings with no text of their own, such as `III/D` (Tributaries), whose text all sits
under `III/D/1`. Those get an entry because commenters cite "Section III.D". A heading comes just before
its first child, and its `rule_passages` include its children's:

| Section | Parent | Page | Rule passages | Note |
|---|---|---|---|---|
| `III` | none | 4169 | 225 | No text of its own; the sum of `III/A` to `III/J` |
| `III/D` | `III` | 4173 | 46 | No text of its own; all of it is `III/D/1` |
| `III/D/1` | `III/D` | 4173 | 46 | |
| `PART 328` | none | 4203 | 11 | One passage of its own plus the 10 of `§ 328.3`, listed once |
| `PART 328/§ 328.3` | `PART 328` | 4203 | 10 | The definition in the regulatory text |

The 16 top-level sections add up to 529 rule passages: all 538 minus the 9 procedural ones, which are
left out as in `/retrieve`. So the roll-up neither loses nor double-counts a passage. `citing_passages`
and `citing_letters` stay `null` on this docket: it has no `links.parquet`. That is still what
`lead-session.txt` shows for 2019, with `unresolved_citations` also `null`.

## Citation counts and citing passages (lead and copper)

`lead-session.txt` is the same container after passage-stage had written
`data/derived/passages/EPA-HQ-OW-2022-0801/`. ChromaDB still held the 2019 rule from earlier runs, so
`/health` lists both dockets (538 + 1,111 = 1,649 passages). The API reads 204 links for the lead sample
and none for 2019.

88 sections, `unresolved_citations` 1 (the `§141.42(d)` link in passage-stage's summary). 17 sections
have at least one citing passage (the 15 leaves the linker resolved, plus `PART 141` and `PART 142`);
71 have 0. Distinct passages and letters, rolled up into parents:

| Section | Citing passages | Citing letters | Notes |
|---|---|---|---|
| `PART 141/§ 141.84` | 39 | 5 | Same as passage-stage's 39 links |
| `PART 141/§ 141.85` | 31 | 5 | |
| `PART 141/§ 141.86` | 28 | 4 | Passage-stage evidence table: 29 links |
| `PART 141/§ 141.81` | 18 | 4 | Passage-stage evidence table: 17 links |
| `PART 141` | 153 | 5 | Every § 141.x passage, counted once |
| `PART 142` | 3 | 2 | Three leaves, one passage each |
| `V/B` | 0 | 0 | Preamble. The linker only resolves `§` / `PART` citations |
| `PART 141/§ 141.153` | 0 | 0 | A regulatory section nobody in the sample cites |

The 17 vs 18 and 29 vs 28 on § 141.81 and § 141.86 are in passage-stage's handwritten table
([`../passage-stage/README.md`](../passage-stage/README.md)); `links.parquet` has 18 and 28. Totals
still match (204 links, 1 unresolved, 15 sections cited). The API counts distinct `passage_id`s, which
on this file equal the link counts per section. The passages endpoint's `total` matches these counts:
39 for § 141.84, 153 for PART 141, 0 for `V/B`.

`passages-141.84.json` is two passages of letter `EPA-HQ-OW-2022-0801-0775` (Wisconsin DNR), citing
`§ 141.84` and `§ 141.84 (b)(3)`. The text still contains those citations: the API serves `text`, not
`text_masked`.

## Reproduce

```bash
docker compose up -d chromadb
docker compose run --rm rule-passages
docker compose run --rm passage-stage   # after campaign-builder; writes the links the counts use
docker compose up -d --build --no-deps api-service
curl -s localhost:8000/health
curl -s -X POST localhost:8000/retrieve -H 'Content-Type: application/json' \
  -d '{"text": "Requiring all lead service lines to be replaced within ten years is not achievable for small water systems", "k": 1}'
curl -s -X POST localhost:8000/retrieve -H 'Content-Type: application/json' \
  -d '{"text": "Requiring all lead service lines to be replaced within ten years is not achievable for small water systems", "k": 3, "method": "merged"}'
# development docket only: needs DOCKET_IDS=EPA-HQ-OW-2018-0149 in .env, otherwise 404
curl -s localhost:8000/rules/EPA-HQ-OW-2018-0149/sections
curl -s localhost:8000/rules/EPA-HQ-OW-2022-0801/sections
curl -sG localhost:8000/rules/EPA-HQ-OW-2022-0801/passages \
  --data-urlencode 'section_ref=PART 141/§ 141.84'
```
