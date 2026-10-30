# One campaign traced end to end: CREDO Action petition, record `EPA-HQ-OW-2018-0149-4291`

The campaign Figure A of the MS1 proposal is built on, followed from the raw API record to the rule sections it
is linked to. Every figure below was recomputed from files pulled from the Regulations.gov API on 9 Oct 2026.
No signer names or places are reproduced here.

## 1. The raw record

| Field | Value |
|---|---|
| Title | Mass Comment Campaign sponsoring organization unknown (email) |
| Comments it stands for (`duplicateComments`) | 66,777 |
| Received / posted | 11 Apr 2019 / 16 Apr 2019 |
| Comment text | "See Attached" |
| Attachment 1, "Mass Mail - cover page" | 1 page, 6 KB: an email forwarded to EPA on 15 Apr 2019 |
| Attachment 2, "Mass Mail (66,777)" | 1,717 pages, 6.6 MB: the signer list |

EPA's record names no sponsor. The email in attachment 1 is from CREDO Action Petitions. A missing sponsor in the
record is not a sign of fraud, which is why the app shows where each sponsor name came from.

## 2. The letter

The cover email says: "Please accept the signatures of 66,887 Americans who have signed a petition with the following
text: *The EPA's proposal to drastically weaken Clean Water Act protections is unacceptable. Abandon this proposed
rollback and return to the 2015 Clean Water Rule, which helped protect drinking water sources for 117 million
Americans.*" That sentence is the campaign's letter.

## 3. Checks on the signer file

| Check | MS1 Figure A | Re-derived |
|---|---|---|
| Signers claimed in the cover email | 66,887 | 66,887 |
| Signers listed in the file | 66,777 | 66,777 (the file's own "Total signers" line). The parser read 66,231 rows, 99.2%, so this was not recounted independently |
| Claimed minus listed | 110 | 110 |
| Signers listing Bellmead, TX | 29, with ZIPs from 10 national regions | 29, with 10 distinct first ZIP digits |
| ZIP region outside the listed state | 49 (0.07%) | 50 (0.08%) by majority state per 3-digit ZIP prefix, so a close but not identical method |

Both counts in the first and third rows come from the cover email and the file header, not from the parsed rows.
The listing of one town with ZIPs from all ten national regions is an observation about the file, not a finding
about any person.

## 4. Linked rule sections

The petition sentence through `rule-passages` (`query --method both -k 3`):

| Retriever | # | Score | Page | Section | Heading |
|---|---|---|---|---|---|
| bm25 | 1 | 15.94 | p. 4200 | `V` | V. Overview of Supporting Analyses |
| bm25 | 2 | 13.23 | p. 4201 | `V` | V. Overview of Supporting Analyses |
| bm25 | 3 | 12.43 | p. 4180 | `III/E/1` | E. Ditches > 1. What are the agencies proposing? |
| dense | 1 | 0.78 | p. 4161 | `II/B/2` | B. The Clean Water Act and Regulatory Definition of “Waters of the United States” > 2. Regulatory History |
| dense | 2 | 0.78 | p. 4161 | `II/B/2` | B. The Clean Water Act and Regulatory Definition of “Waters of the United States” > 2. Regulatory History |
| dense | 3 | 0.76 | p. 4156 | `II/B/1` | B. The Clean Water Act and Regulatory Definition of “Waters of the United States” > 1. The Clean Water Act |

## 5. The failure case

This petition does not argue about one provision, and the two retrievers answer differently. BM25 returns the
economic analysis (section V) on the strength of shared words such as "drinking water" and "protections". The
embedding search returns the Regulatory History sections, which discuss the 2015 rule the petition asks to return to.
Neither is verified: the MS1 mock describes this campaign's provision as "rule as a whole", which is why the
labeling sheet has a "nothing specific" option and why a campaign like this is left out of the top-k score.

## What this trace does not cover

The grouping step is absent: EPA had already grouped these 66,777 comments into one record, so there was nothing
for MinHash or clustering to decide. The grouping questions live in the campaigns whose letters are personalized or
reworded.
