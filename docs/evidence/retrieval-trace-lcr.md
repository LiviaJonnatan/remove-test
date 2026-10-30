# One organization letter traced end to end: record `EPA-HQ-OW-2022-0801-0775`

A letter from the Wisconsin Department of Natural Resources on the Lead and Copper Rule Improvements
proposal (88 FR 84878), followed from the raw API record to the rule passages retrieved for one of
its paragraphs. Everything below comes from one `docker compose up --build` on a fresh clone with
the default `.env`, rerun on 14 Oct 2026 with the rule-passages fix in #67 (1,111 rule chunks). The record is one of the 40 in `data-collector/samples/ms2_ids.txt`.

## 1. The raw record (data-collector)

| Field | Value |
|---|---|
| Title | Comment submitted by Wisconsin Department of Natural Resources (WDNR) |
| Comment text | "See attached file(s)" |
| Attachment | one PDF, titled "Comment" |
| Written to | `data/raw/EPA-HQ-OW-2022-0801/details/EPA-HQ-OW-2022-0801-0775.json` and `attachments/` |

## 2. The letter (data-processor)

The body is only a pointer, so the processor read the PDF.

| Field | Value |
|---|---|
| `letter_id` | `EPA-HQ-OW-2022-0801-0775` |
| `kind` | individual |
| `text_source` | pdf_text (no OCR needed) |
| Length | 3,412 words, 4,579 bge-small tokens |
| Written to | `data/derived/letters/EPA-HQ-OW-2022-0801/letters.parquet` |

## 3. The group (campaign-builder)

`campaign_id` is null. No other letter in the sample has the same text, which is right for an
agency's own letter.

## 4. The query

One paragraph of the letter, 134 words. In the letter it ends with a citation to
§ 141.81(g). The citation was removed before the query was sent, so retrieval had to find the
section from the argument alone.

> the Preamble which states that “Systems with P90 lead level > 0.010 mg/L: No CCT: Must complete CCT installation regardless of their subsequent P90 levels if the system has started to install CCT. " This is also an important clarification for when a small or medium system without corrosion control treatment that does not exceed the action levels for two consecutive six-month monitoring periods may stop completing the CCT steps, as it is determined by when the system “starts” to install OCCT. [§ [citation removed]]  Clarify how CCT and optimal water quality parameter (OWQP) requirements apply to systems that have installed CCT but have not previously been “deemed optimized” because they have not had an ALE. Are all systems with CCT that are not currently deemed optimized expected to be deemed optimized and

## 5. What came back (api-service, `POST /retrieve`, k=5)

Request and full response: [`retrieval-trace/retrieve.json`](retrieval-trace/retrieve.json).
The API log line for it: `"POST /retrieve HTTP/1.1" 200 OK`.

Keyword search (BM25):

| Rank | Score | Chunk | FR page | Section | Heading |
|---|---|---|---|---|---|
| 1 | 71.721 | `2023-26148:0347` | 84937 | V/E | E. Corrosion Control Treatment |
| 2 | 68.785 | `2023-26148:0853` | 85056 | PART 141/§ 141.81 | Sec. 141.81 Applicability of corrosion control treatment steps to small, medium, and large water systems. |
| 3 | 68.048 | `2023-26148:0871` | 85058 | PART 141/§ 141.81 | Sec. 141.81 Applicability of corrosion control treatment steps to small, medium, and large water systems. |
| 4 | 63.985 | `2023-26148:0854` | 85056 | PART 141/§ 141.81 | Sec. 141.81 Applicability of corrosion control treatment steps to small, medium, and large water systems. |
| 5 | 62.999 | `2023-26148:0395` | 84943 | V/F/1 | 1. Systems Required To Monitor for Water Quality Parameters |

Embedding search (bge-small, cosine):

| Rank | Score | Chunk | FR page | Section | Heading |
|---|---|---|---|---|---|
| 1 | 0.869 | `2023-26148:0347` | 84937 | V/E | E. Corrosion Control Treatment |
| 2 | 0.839 | `2023-26148:0360` | 84938 | V/E | E. Corrosion Control Treatment |
| 3 | 0.838 | `2023-26148:0355` | 84938 | V/E | E. Corrosion Control Treatment |
| 4 | 0.837 | `2023-26148:0346` | 84937 | V/E | E. Corrosion Control Treatment |
| 5 | 0.836 | `2023-26148:0859` | 85057 | PART 141/§ 141.81 | Sec. 141.81 Applicability of corrosion control treatment steps to small, medium, and large water systems. |

## 6. Where it fails

The letter cited § 141.81, the regulatory text on corrosion control treatment steps.

- **Keyword search** returns that section at ranks 2, 3 and 4. Rank 1 is the preamble's discussion of
  the same topic.
- **Embedding search** returns four chunks of preamble section V.E first and reaches the section only
  at rank 5.

Both methods find the right topic first. Neither puts the provision the commenter named first. The
preamble explains the provision in plain prose, close to how a commenter writes, and the regulatory text
is terse and full of cross-references, so the preamble wins on similarity. The paragraph also quotes the
preamble directly, which pulls the same way.

Whether rank 1 here counts as wrong depends on what a link should point to: the provision, or the
agency's discussion of it. We score against the provision the commenter cited, so this is a miss at
rank 1 for both methods. This one example is not a measurement. The comparison on all cited passages is
ticket #45.

**This run needs the rule-passages fix in #67.** Before it, the index silently lost about a fifth of the
proposal, and the same query returned the section only at keyword rank 4 and never by embedding.

## Reproduce

```bash
cp .env.example .env        # add an API_DATA_GOV_KEY
docker compose up --build -d
curl -s -X POST localhost:8000/retrieve -H 'content-type: application/json' \
  -d "$(python3 -c "import json;print(json.dumps(json.load(open('docs/evidence/retrieval-trace/retrieve.json'))['request']))")"
```
