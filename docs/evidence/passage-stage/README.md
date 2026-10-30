# passage-stage evidence

Ticket U-26 (#43). One `docker compose up --build -d` on a fresh clone, default `.env` plus an API key, 15 Oct 2026, on `main` with the rule-passages markup fix (#67). The input is the 40-record lead and copper sample.

Updated 16 Oct from a rerun on the same letters (same `letters_sha256`), with three changes since the first run:

- The last review changes to #68, which moved one link from § 141.86's count to § 141.81's.
- Lost ligatures repaired (`glyphs.py`). One letter, EPA-HQ-OW-2022-0801-0972, was saved from Word in Calibri, whose "ti", "ft", "tti" and "tf" glyphs pypdf reads as U+FFFD ("Sec�on 141.84"). The stage restores 1,336 words in it, picking the pair that makes a word the docket's letters use. Compared word by word with an exact decoding of that PDF (PyMuPDF, which keeps the four glyphs apart), 1,333 are right. The misses are "submitting" and "straightforward", which no other letter spells out, and "tie", which comes out as "fte" because the letters use FTE and never "tie". Its ten "Section 141.xx" citations now read as written.
- Word's bullets repaired. Letter EPA-HQ-OW-2022-0801-0775 writes its bullets as the private-use character U+F0B7 (Symbol font), which the page drew as a block of bars. They are now "•", so the splitter breaks that letter's bulleted lists into separate passages as it already does for other letters: 2 more passages and a few more citing ones.

Together: 831 to 833 passages, 155 to 158 citing a section, 204 to 209 links (203 to 208 resolved to a section of the rule). No passage still contains U+FFFD, a ligature character such as "ﬁ", or a private-use character.

The API evidence in `../api-service/` was recorded before the repair: it reads 204 links, so its per-section counts differ from these.

| File | What it shows |
| --- | --- |
| `run.log` | The stage's one line of output |
| `summary.json` | Counts and the checksum of the letters file read |

40 letters in, 1 skipped as an exact copy, 833 passages out. 158 passages cite a section, giving 209 links: 208 to 15 of the rule's 18 sections and 1 to `§141.42(d)`, an existing regulation outside the proposal.

Links per section:

| section_ref | links |
| --- | --- |
| `PART 141/§ 141.84` | 40 |
| `PART 141/§ 141.85` | 30 |
| `PART 141/§ 141.86` | 29 |
| `PART 141/§ 141.82` | 20 |
| `PART 141/§ 141.90` | 20 |
| `PART 141/§ 141.92` | 20 |
| `PART 141/§ 141.81` | 19 |
| `PART 141/§ 141.2` | 13 |
| `PART 141/§ 141.80` | 9 |
| `PART 141/§ 141.93` | 2 |
| `PART 141/§ 141.87` | 2 |
| `PART 142/§ 142.16` | 1 |
| `PART 142/§ 142.15` | 1 |
| `(not a section of the rule)` | 1 |
| `PART 142/§ 142.14` | 1 |
| `PART 141/§ 141.154` | 1 |

Eight links drawn at random were read against their passage. All eight cite the section they were linked to.

What this does not show: the links come from 5 of the 39 letters. Citations are concentrated in long organization letters, as the linking test found on seven dockets (3.7% of substantive comments carry a usable citation). Passages that cite nothing get no link here; that is the reader's job in MS3.

`text_masked` was checked on all 833 passages of the repaired run: none still contains a 141.x or 142.x number. Masking also hides any bare mention of a rule section number, which still matters for PDF text that garbles the word before a number in some other way.

Since containment grouping became the default (U-05), the same run groups 18 of the sample's 20
campaign letters into 2 groups. The stage reads 24 letters whole and 15 campaign members only for the
sentences not already read in their group, skips 1 exact copy, and writes 816 passages.
The 158 citing passages and their 209 links are the same ones as above. See
[`campaign-builder/containment.md`](../campaign-builder/containment.md).
