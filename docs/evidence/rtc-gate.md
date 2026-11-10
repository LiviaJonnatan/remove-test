# Can EPA's Response to Comments be joined to our records? (30 Oct 2026)

Source: EPA, "Response to Public Comments on the Lead and Copper Rule Improvements", EPA 815-R-24-029,
October 2024, regulations.gov EPA-HQ-OW-2022-0801-2645. 3,529 pages, 22.4 MB. Saved (gitignored) at
`data/raw/EPA-HQ-OW-2022-0801/rtc/rtc.pdf`, text via `pdftotext -layout`.

Format: entries are filed under EPA's topic codes (1.1 General Comments ... 5.9.2 Action Level ...). Each
entry is `Organization (Doc. #NNNN, SBC-NNNNNN)`, the commenter's excerpt, then `EPA Response:`.

| Check | Result |
|---|---|
| Commenter entries parsed | 7,510 |
| "EPA Response:" blocks | 7,886 |
| Distinct Doc # cited | 1,537 |
| Doc # that are one of our 1,589 records (Doc #1118 = EPA-HQ-OW-2022-0801-1118) | **1,537 of 1,537** |
| Excerpt verbatim in our letter text (random 300 entries, 286 with text, >= half of 8-word chunks found) | 190 of 286 |
| Excerpt with no chunk found | 95 of 286 |

All 95 misses read so far are our bug, not EPA's: the processor kept a short cover note ("Please see the
attached comments filed on behalf of NRDC ...") as the letter and skipped the attachment, because
`is_attachment_pointer` only matches a bare "see attached" sentence.

| Processor gap | Count |
|---|---|
| Records with a downloaded attachment | 355 |
| Attachment used as the letter | 205 |
| Cover-note body used instead | **134** |
| EPA response entries that cite those 134 records | **2,633 of 7,510** |
| Of EPA's 8 most-answered letters, skipped | 6 (NRDC et al. #1119 with 298 entries, #2024 with 241, ...) |

## After the processor fix (same night)

The processor now reads the attachment whenever a comment has one, keeps the body in front of it unless
the attachment already contains it, and keeps the body alone only when the attachment cannot be chosen
or read (9 records, logged as `attachment_not_used`).

| LCRI letters | Before | After |
|---|---|---|
| Letters | 1,553 | 1,553 |
| Tokens | 1,023,065 | 1,901,199 |
| Text from an attachment | 205 | 330 |
| Records with an attachment still body-only | 134 | 9 |
| Sample of 300 entries: excerpt mostly verbatim | 190 of 286 | **277 of 286** |
| Sample of 300 entries: no chunk found | 95 | 7 |

All 7,417 entries whose Doc # has a letter after the fix: 6,948 mostly verbatim (93.7%), 137 partly,
206 with no chunk found. 126 entries point at records with no letter (failed or withdrawn records).

Gate result: pass. EPA's response document gives about 6,900 comment-excerpt-to-response links that
land on exact text in our letters. Everything downstream of the processor (passages, campaigns, linker
data, the argument-graph pilot) was built on the old letters and should be rebuilt.

## Downstream rebuilt and the document parsed (31 Oct)

| LCRI stage | Old letters | Fixed letters |
|---|---|---|
| Form-letter groups (campaign-builder) | 459 letters in 48 groups | 469 in 51 |
| Passages (passage-stage) | 5,409 | 9,059 |
| Passages citing a rule section | 369 | 884 |
| Sections cited | 15 | 17 |

`response-index` parses the document: 138 topic codes, 7,889 entries on 1,543 records (97.1% of our
letters), 7,358 of 7,749 excerpts located in our letters (95.0%). 5,916 entry responses (75.0%) only
point to a code's summary response; 1,841 have more than 30 words of their own. The linker training
data and the 30 Oct argument-graph pilot still use the old letters and passages.
