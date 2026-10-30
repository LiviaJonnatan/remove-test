# Hand check of the model-made labels (U-30, #47)

Two of us labeled the same 30 passages without seeing each other's answers, using the frozen codebook
(v1.0, 11 Oct 2026). The passages come from three dockets: Title IX (ED-2021-OCR-0166), Section 1557
(HHS-OS-2022-0012) and lead and copper (EPA-HQ-OW-2022-0801). Half were drawn from passages where the two
labeling models had agreed, half from passages where a third model broke a tie, so **none of these rates is
an estimate for all comments**. Comment text and the labeling pack stay out of git. Only passage ids,
labels and reasons are here.

## Results

| | Reader A | Reader B |
|---|---|---|
| Model label accepted (same scope and same sections) | 17 of 30 (95% interval 37% to 75%) | 19 of 30 (44% to 80%) |
| where the two models had agreed | 12 of 15 | 13 of 15 |
| where a third model broke a tie | 5 of 15 | 6 of 15 |

| The two readers against each other | |
|---|---|
| Same label, scope and sections | 21 of 30 (95% interval 51% to 85%) |
| Same scope | 26 of 30, Cohen's kappa 0.75 |
| Agree whether any section applies | 28 of 30 |
| Same label where the models had agreed | 13 of 15 |
| Same label where a model broke a tie | 8 of 15 |

What it means:

- Two careful readers give the same label 70% of the time on this mix. A model scored against one reader
  cannot meaningfully beat that.
- Tie-broken model labels are poor (5 and 6 of 15 accepted). They are left out of training and of any gate.
- People mostly agree on what kind of passage it is and split on which sections. The hard half is hard for
  people too.
- Time: 3 to 6 minutes a passage for a careful reader with the rule open, faster after the first few.

Intervals for the small counts are exact binomial (Clopper-Pearson).

## The 9 passages the readers split on

These were **settled by Claude, not by a person**, on 16 Oct 2026, using the codebook, the commenters'
own citations from the sealed key, and the proposed rule's text. The settled answers are in
[`settle-9.csv`](settle-9.csv) (`final_scope`, `final_targets`), with the reason and caveat for each.

On 19 Oct 2026 both readers reviewed the 9 (`livia_agrees`, `rishi_agrees`). Both confirmed 8 and both
rejected P132, so **29 of the 30 labels are now human ground truth** and P132 has no agreed label.

The full set of 30 is [`labels-30.csv`](labels-30.csv). Its `source` column says where each label came
from: **21 are "both readers"**, the same answer from two people working blind; **8 are "settled by
Claude, confirmed by both readers"**; and **P132 is "readers rejected the settled label"**. Any score
that grades a model, or a gate that promotes one, uses the 29 and leaves P132 out. Report the 21 blind
agreements separately as the reader-agreement rate, since the 8 were confirmed after seeing a proposal.

| Passage | Docket | Reader A (Livia) | Reader B (Rishi) | Settled | Sides with | Confidence |
|---|---|---|---|---|---|---|
| P019 | HHS | PREAMBLE_ONLY | OTHER_LAW_ONLY | OTHER_LAW_ONLY | Rishi | low |
| P031 | HHS | PROVISION_SPECIFIC 92.101;92.301 | CROSS_CUTTING | PROVISION_SPECIFIC 92.301 | neither (Livia minus 92.101) | medium |
| P096 | ED | PROVISION_SPECIFIC 106.2;106.45 | PROVISION_SPECIFIC 106.45 | PROVISION_SPECIFIC 106.2;106.45 | Livia | medium |
| P102 | ED | PROVISION_SPECIFIC 106.10;106.31 | PROVISION_SPECIFIC 106.10 | PROVISION_SPECIFIC 106.10;106.31 | Livia | high |
| P113 | ED | CROSS_CUTTING | PROVISION_SPECIFIC 106.10 | PROVISION_SPECIFIC 106.10 | Rishi | low |
| P132 | EPA | PROVISION_SPECIFIC 141.80;141.93 | PROVISION_SPECIFIC 141.82 | CROSS_CUTTING | neither | low |
| P135 | EPA | PROVISION_SPECIFIC 141.85 | PROVISION_SPECIFIC 141.85;141.202 | PROVISION_SPECIFIC 141.85;141.202 | Rishi | medium |
| P164 | EPA | PROVISION_SPECIFIC 141.85 | PROVISION_SPECIFIC 141.93 | PROVISION_SPECIFIC 141.84;141.85 | neither | low |
| P177 | EPA | PREAMBLE_ONLY | OTHER_LAW_ONLY | OTHER_LAW_ONLY | Rishi | medium |

Both readers' answers are in the `livia_agrees` and `rishi_agrees` columns of `settle-9.csv`: yes on
every row except P132. Both had labeled P132 provision-specific in the blind pass; the settled label is cross-cutting because
the passage's heading falls outside the window.

### Reasons

**P019.** Proposed OTHER_LAW_ONLY. The passage compares Finnish treatment guidelines with WPATH standards. It never mentions the agency or its reasoning, so PREAMBLE_ONLY has nothing to attach to in the window. Outside guidelines used as comparison is the closest fit to OTHER_LAW_ONLY.

Caveat: Codebook gap: foreign clinical guidelines are not a statute, case or regulation. If the rest of the letter is rebutting the agency's evidence, PREAMBLE_ONLY becomes defensible.

**P031.** Proposed PROVISION_SPECIFIC 92.301. The passage is about enforcement and complaint procedures and asks the final rule to add a reference to intersectional discrimination. That is a request to change an identifiable provision, Enforcement mechanisms, so Rule 6 (wholly new requirement) does not apply. 92.101 shares the theme only (Rule 1).

Caveat: The sealed key shows the commenter's own heading named 92.301, Enforcement mechanisms. Evidence, not proof (Rule 2).

**P096.** Proposed PROVISION_SPECIFIC 106.2;106.45. The argument is that the evidence requirement and the definition of 'relevant' together create a tension. The passage quotes the definition and reasons from it, so both are substantively addressed (Rule 4).

Caveat: The sealed key shows the commenter cited 106.45(b)(6) and 106.2 in this passage.

**P102.** Proposed PROVISION_SPECIFIC 106.10;106.31. Two distinct requirements are argued: the ban on gender identity discrimination (Scope) and the requirement that schools let students use facilities consistent with gender identity (Education programs or activities). Rule 9: both get listed.

Caveat: The sealed key shows the commenter cited 106.10 and 106.31(a)(2).

**P113.** Proposed PROVISION_SPECIFIC 106.10. The first sentence argues against the language adding gender identity as a protected class, which is the Scope section. The rest is general opposition. Both scopes fit, and the codebook says to take PROVISION_SPECIFIC first when two fit.

Caveat: The weakest of the nine. Most of the passage is general opposition, so CROSS_CUTTING is a fair reading. Worth a codebook line on how much of a passage must concern the provision.

**P132.** Proposed CROSS_CUTTING. The passage proposes that small systems be required to fix the specific site after one high sample. That is a new requirement, and no existing provision is named for change (Rule 6). The two readers picked three different sections between them, which suggests none is identifiable from the window.

Caveat: The passage is item b of an outline whose heading is outside the window. If the heading names a provision, this flips to PROVISION_SPECIFIC. I could not retrieve the letter to check.

**P135.** Proposed PROVISION_SPECIFIC 141.85;141.202. Two requirements are objected to: the public education notifications (141.85) and the 24-hour Tier 1 notice, which is the Tier 1 public notice section. Rule 9.

Caveat: Checked in the proposal's regulatory text: the 24-hour notice language is in 141.202.

**P164.** Proposed PROVISION_SPECIFIC 141.84;141.85. The passage asks to replace a quoted phrase. In the proposal's regulatory text that phrase appears in 141.84 (twice), 141.85 (three times) and the definitions in 141.2 (once). It does not appear in 141.93.

Caveat: The reference excerpts did not show the phrase, so neither reader could have found it. This is a limit of the pack, not a reader error. 141.2 is arguable as a third target.

**P177.** Proposed OTHER_LAW_ONLY. The passage is about how Michigan's state rule was written and what it costs. That is another regulation used as comparison (Rules 7 and 8). It does not discuss EPA's reasoning, and OTHER_LAW_ONLY comes before CROSS_CUTTING in the order.

Caveat: The context says EPA is borrowing from Michigan's rule, so a reader could fairly see it as opposition to the federal rule as a whole.

### What the nine show about the codebook

- Three (P096, P102, P135) are one section against two. The readers agreed on the main section each time.
- Three (P019, P113, P177) are scope questions the codebook does not settle cleanly: outside guidelines that
  are not law, a passage that names a provision in one sentence and is general opposition in the rest, and a
  state rule the federal rule borrows from.
- One (P164) could not be answered from the reference excerpts. The quoted wording is only in the full rule
  text.
- One (P132) depends on a heading outside the 150-word window.
- One (P031) is a request to change a provision that one reader read as a new requirement.
