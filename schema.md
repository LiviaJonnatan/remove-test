# Record schema

Vocabulary from the Milestone 1 proposal:

- **record**: one Regulations.gov posting or one FCC ECFS filing. A record is either an individual comment or a *campaign record* standing for many copies.
- **comment**: one person's submission. An individual record is one comment; a campaign record represents `copies` comments.
- **letter**: a comment whose full text we have.
- **signer**: a name, city and ZIP from a campaign's signer list. Names are hashed with a secret key and never stored or shown in clear.
- **campaign**: the set of comments built on one template, with a sponsor where one can be recovered.

Data flows raw → letters → campaigns. Each layer is DVC-tracked as a whole folder; the md5 in its `.dvc` file is that layer's data version.

```
data/
  raw/                               DVC-tracked, as fetched
    <docket>/                        data-collector         (section 1)
    federal_register/                rule text, 11 documents as JSON + XML
    nyag/                            NY AG report PDF
  derived/                           DVC-tracked, built from raw
    letters/<docket>/                data-processor         (section 2)
    campaigns/<docket>/              campaign-builder       (section 3)
    passages/<docket>/               passage-stage          (section 3b)
    labels/                          hand labels            (section 4)
  samples/                           local only, never in git or DVC:
                                     demo letters and labeling packs
```

`data/raw/` and `data/derived/` are tracked at the folder level (one `.dvc` file per subfolder). `data/samples/` is git-ignored.

All IDs are Regulations.gov document IDs (e.g. `EPA-HQ-OW-2018-0149-0077`) or ECFS filing IDs, so files join across layers and survive re-pulls.

---

## 1. Raw layer: `data/raw/<docket>/` (data-collector)

Exactly what the API returned, plus small index files. Nothing is parsed or cleaned here.

### `comments_index.jsonl` — one line per record, from the list endpoint

| field | type | source | notes |
| --- | --- | --- | --- |
| `id` | string | `data[].id` | document ID, primary key everywhere |
| `object_id` | string | `attributes.objectId` | API-internal ID |
| `title` | string | `attributes.title` | agency-assigned; for campaign records often the campaign name |
| `posted_date` | ISO datetime | `attributes.postedDate` | when agency staff published it; **not** submission time |
| `last_modified` | ISO datetime | `attributes.lastModifiedDate` | used for pagination windows |
| `document_type` | string | `attributes.documentType` | `Public Submission` for comments |
| `agency_id` | string | `attributes.agencyId` | `EPA` |

### `details/<id>.json` — one file per record, full detail response

Stored verbatim: `{"data": {...}, "included": [...], "links": {...}}`. Attribute names below are as the API returns them (checked against real records, 9 Oct). Fields the pipeline relies on:

| path | type | notes |
| --- | --- | --- |
| `data.id` | string | document ID |
| `data.attributes.comment` | string or null | comment body typed on the web form; often just a pointer to the attachment ("Find attached comments…") |
| `data.attributes.receiveDate` | ISO datetime | when the comment arrived at the agency; **the timing field**. Can be far earlier than `postedDate` (0085: received 2018-05-01, posted 2019-02-20) |
| `data.attributes.postmarkDate` | ISO datetime or null | for mailed comments |
| `data.attributes.postedDate` | ISO datetime | when staff published it |
| `data.attributes.modifyDate` | ISO datetime | = `lastModifiedDate` on the list endpoint |
| `data.attributes.duplicateComments` | int | the agency's copy count for a campaign record; 1 for an individual comment |
| `data.attributes.title` | string | agency-assigned; carries the submitter's name or organization ("Comment submitted by …", "Anonymous public comment", "Mass Comment Campaign sponsored by …") |
| `data.attributes.organization` | string or null | **null on every record seen so far**; the organization is in `title` instead |
| `data.attributes.firstName`, `lastName` | string or null | submitter; hashed by the processor, never carried forward in clear |
| `data.attributes.city`, `stateProvinceRegion`, `zip`, `country` | string or null | submitter location |
| `data.attributes.address1`, `address2`, `email`, `phone`, `fax` | string or null | **dropped by the processor**; never leave the raw layer |
| `data.attributes.submitterRep`, `submitterRepAddress`, `submitterRepCityState` | string or null | representative, if any; dropped likewise |
| `data.attributes.commentOnDocumentId` | string | the proposed rule this comments on (`EPA-HQ-OW-2018-0149-0003` for the dev docket) |
| `data.attributes.docketId`, `agencyId`, `documentType`, `subtype` | string | `EPA-HQ-OW-2018-0149`, `EPA`, `Public Submission`, `Public Comment` |
| `data.attributes.pageCount` | int or null | pages in the attachment(s) |
| `data.attributes.trackingNbr` | string | agency tracking number |
| `data.attributes.withdrawn`, `reasonWithdrawn` | bool, string or null | |
| `data.attributes.restrictReason`, `restrictReasonType` | string or null | set when the agency withheld content |
| `data.relationships.attachments.data[]` | list of `{id, type}` | attachment IDs; the full records are in `included` |
| `included[]` where `type == "attachments"` | list | one entry per attachment **document** |
| `included[].id` | string | attachment ID |
| `included[].attributes.title` | string | usually "Comment" |
| `included[].attributes.docOrder` | int | order within the comment |
| `included[].attributes.modifyDate` | ISO datetime | |
| `included[].attributes.fileFormats[]` | list | **one attachment can have several formats of the same document** (0077: `docx` and `pdf`). Each has `fileUrl`, `format` (`pdf`, `docx`, `xlsx`, …), `size` in bytes |
| `included[].attributes.authors`, `agencyNote`, `restrictReason` | usually null | |

One real record, names redacted: `docs/evidence/data-collector/sample/EPA-HQ-OW-2018-0149-0084.json`.

### `details_index.jsonl` — one line per record, summary of the detail call

| field | type | notes |
| --- | --- | --- |
| `id` | string | |
| `receive_date` | ISO datetime or null | |
| `posted_date` | ISO datetime or null | |
| `has_body` | bool | whether `attributes.comment` is non-empty |
| `n_attachments` | int | attachment **documents** (`included` entries), not files; a document in two formats counts once here and twice in the manifest |

### `attachments/<id>/<file>` and `attachments_manifest.jsonl`

Files are saved with their original names under the comment's ID (`attachment_1.pdf`, `attachment_1.docx`, `attachment_2.pdf`, …; the number is `docOrder`). The manifest has one line per downloaded **file**, so an attachment offered in two formats appears twice with the same `attachment_id`. The processor should take one format per `attachment_id`, preferring `docx` over `pdf` for text extraction:

| field | type | notes |
| --- | --- | --- |
| `comment_id` | string | |
| `attachment_id` | string | |
| `file` | string | file name on disk |
| `format` | string | from `fileFormats[].format`: `pdf`, `docx`, `xlsx`, … |
| `size` | int or null | bytes, as reported by the API |
| `url` | string | source URL |
| `path` | string | relative to `data/raw/<docket>/` |

### `index_checkpoint.json`

`{"complete": true, "total_reported": 11444}` when the index holds every comment the API reports. A `truncated: true` checkpoint comes from a `MAX_RECORDS` smoke run and is rebuilt by the next uncapped run.

### `manifest.json` — one per docket per run

Counts (`comments_indexed`, `details_on_disk`, `attachment_files`, `attachments_downloaded_this_run`, `attachments_failed`, `api_calls_this_run`) and `collected_at`. A sharded run writes `manifest_shard_k_of_n.json` instead. The raw layer's data version is the md5 in `data/raw/<docket>.dvc`, not this file.

---

## 2. Letters layer: `data/derived/letters/<docket>/` (data-processor) — proposed

One row per **letter**. The processor expands campaign records into their individual letters where the attachment holds every letter, extracts text from attachments (PDF text, OCR for the four scanned PDFs), and hashes names.

### `letters.parquet`

| column | type | notes |
| --- | --- | --- |
| `letter_id` | string | `<record_id>` for an individual comment; `<record_id>#<n>` for a letter inside a campaign attachment, where `n` is the letter's position in the attachment in page order (not a running count from the splitter, so a splitter change shifts no ids) |
| `text_sha1` | string | SHA-1 of `text`. Hand labels record it alongside `letter_id`, so a label can be checked against the text it was made on; a splitter change then shows up as a mismatch instead of silently relabeling |
| `record_id` | string | joins to the raw layer |
| `docket_id` | string | |
| `kind` | enum | `individual`, `campaign_letter` (from a full-letter attachment), `campaign_sample` (the one representative letter the agency posted) |
| `text` | string | cleaned letter text |
| `text_source` | enum | `body`, `docx`, `pdf_text`, `ocr` |
| `attachment_id` | string or null | the attachment the text came from; null when from `body` |
| `n_tokens` | int | token count under the bge-small tokenizer (512 limit) |
| `receive_date` | datetime or null | per-letter where available, else the record's |
| `signer_hash` | string or null | HMAC-SHA256 of normalized `first last` with the secret key; null if no name |
| `city`, `state`, `zip` | string or null | ZIP is 5 digits; no street addresses anywhere |
| `epa_campaign_id` | string or null | the record id of the full-letter campaign attachment this letter was extracted from. Null for `individual` and `campaign_sample` rows, so every `campaign_letter` row has a label and nothing else does. This is the column B-cubed F1 scores against |

### `records.parquet` — one row per campaign record

| column | type | notes |
| --- | --- | --- |
| `record_id` | string | |
| `title` | string | |
| `copies_claimed` | int | agency's `duplicateComments` |
| `sponsor_epa` | string or null | sponsor as recorded by the agency, parsed from `title` ("Mass Comment Campaign sponsored by X"), since `organization` is always null |
| `sponsor_attachment` | string or null | sponsor named in the cover letter, filled in by the sponsor audit (MS3) |
| `attachment_kind` | enum | `every_letter`, `signer_list`, `sample_letter` |
| `n_letters` | int | letters actually extracted |
| `n_signers` | int | signers actually listed |
| `receive_date` | datetime | the record's date |

### `signers.parquet` — one row per signer in a signer list

| column | type | notes |
| --- | --- | --- |
| `record_id` | string | |
| `signer_hash` | string | same HMAC as in `letters` |
| `city`, `state`, `zip` | string or null | |

---

## 3. Campaigns layer: `data/derived/campaigns/<docket>/` (campaign-builder) — proposed

### `assignments.parquet` — one row per letter

| column | type | notes |
| --- | --- | --- |
| `letter_id` | string | |
| `campaign_id` | string or null | our cluster ID; null when below threshold (never a sentinel string, so a scorer grouping by `campaign_id` doesn't treat the ungrouped letters as one cluster) |
| `method` | enum | `exact`, `minhash`, `embed` — which stage grouped it |
| `similarity` | float | exact: 1.0. minhash: Jaccard with the campaign representative. containment: containment of the letter with the template the other members share |
| `personalized` | bool | differs from template by > 10% in length |

### `summary.json` — one per docket per run

`docket_id`, the grouper (`method`, `min_words`), counts (`letters`, `letters_grouped`, `groups`, `individual`), `bcubed` (`n_scored`, `precision`, `recall`, `f1`, or null when EPA grouped none of the letters), the letters file read (`letters_file`, relative to `data/`, and its `letters_sha256`) and `built_at`.

### `campaigns.parquet` — one row per campaign

| column | type | notes |
| --- | --- | --- |
| `campaign_id` | string | |
| `representative_letter_id` | string | |
| `n_letters`, `n_copies` | int | letters we have / copies including agency counts |
| `personalized_share` | float or null | null when only a sample letter exists |
| `sponsor`, `sponsor_source` | string or null, enum | `epa_record`, `attachment`, `unknown` |
| `first_receive`, `last_receive`, `peak_day` | datetime or null | |
| `zip_outside_state`, `signers_on_other_campaigns`, `claimed_minus_listed` | int or null | signer checks, where a signer list exists |
| `reading_order` | float | mean of features scored in MADs from the docket median; **not a fraud score** |
| `rule_sections` | list of string | from rule-passages |

---

## 3b. Passages layer: `data/derived/passages/<docket>/` (passage-stage)

### `passages.parquet` — one row per passage of a distinct letter

| column | type | notes |
|---|---|---|
| `passage_id` | string | `<letter_id>:p<index>`, e.g. `EPA-HQ-OW-2022-0801-0775:p004` |
| `letter_id` | string | |
| `docket_id` | string | |
| `index` | int | position in the letter, from 0. For a campaign member read only for its own sentences, position among those |
| `text` | string | whole sentences, about 120 words, at most 250 |
| `text_masked` | string | `text` with every citation replaced by `[citation removed]`, for scoring retrieval without the answer |
| `n_words` | int | |
| `n_citations` | int | section citations found, before resolving. A letter's own "section 2.4" is not counted |

### `links.parquet` — one row per (passage, cited section)

| column | type | notes |
|---|---|---|
| `passage_id` | string | |
| `letter_id` | string | |
| `docket_id` | string | |
| `section_ref` | string or null | rule-passages' key, e.g. `PART 141/§ 141.84`. Null when the cited number is not a section of the rule |
| `citation_raw` | string | as written, e.g. `§ 141.84(b)(2)` |
| `source` | string | `citation` now, `model` once the reader links uncited passages |

A passage citing two sections has two rows. The same section cited twice in one passage is one row. A
range such as `§ 141.80–141.93` gives a row for every section of the rule between its ends, with the whole
range as `citation_raw`.

### `summary.json` — one per docket per run

`docket_id`, `letters_read`, `letters_skipped_as_copies` (members with no sentence of their own), `letters_read_for_own_sentences` (members read only for what they added), `passages`, `passages_with_citation`, `links`, `links_resolved`, `links_unresolved`, `sections_cited`, `rule_sections_known`, `rule_documents`, `passage_words`, `letters_file`, `letters_sha256`, `built_at`.

## 4. Labels: `data/derived/labels/` (hand-labeled)

| file | one row per | columns |
| --- | --- | --- |
| `pairs.csv` | letter pair | `letter_id_a`, `text_sha1_a`, `letter_id_b`, `text_sha1_b`, `label` (`same`, `different`, `unsure`), `labeler`, `note` |
| `personalized.csv` | letter | `letter_id`, `text_sha1`, `label` (`personal`, `template_variant`, `noise`), `template_record_id`, `labeler`, `note` |
| `sections.csv` | campaign | `record_id`, `rule_section` (section number, or `whole`), `labeler`, `note` |

Every file gets a second-labeler pass on a shared subset so agreement can be reported. The campaign-to-section labels are produced by the offline labeling pack (#16), which exports `.jsonl` read directly by the retrieval evaluation; the pack itself lives in `data/samples/` and stays out of git.

---

## Conventions

- Timestamps in UTC ISO 8601. Regulations.gov returns Eastern time; the processor converts.
- Names never appear in any file past the raw layer. Signer hashes use HMAC-SHA256 with `SIGNER_HASH_KEY` from `.env`; the raw layer is the only place clear names exist, and it stays in the private bucket.
- Sections 2 and 3 are proposed and will be revised by their container owners; section 1 is what the collector writes today.