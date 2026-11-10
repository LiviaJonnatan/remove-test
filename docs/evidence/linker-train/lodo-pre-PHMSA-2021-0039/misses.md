# Misses on PHMSA-2021-0039 (27 of 100 test passages, 73.0% top-1)

## Where the true section ranked

- rank 2: 14
- rank 3-5: 7
- rank 6-10: 2
- rank >10 (not in top10): 4

## What was picked instead

- same part, not adjacent: 14
- different part: 9
- adjacent section: 4

## Confidence

median margin on hits 0.145, on misses 0.074

## Sections that absorb wrong picks

- 192.760 (Leak grading and repair.): picked wrongly 11 times
- 192.9 (What requirements apply to gathering pipelines?): picked wrongly 3 times
- 192.706 (Transmission lines: Leakage surveys.): picked wrongly 2 times
- 192.763 (Advanced Leak Detection Program.): picked wrongly 2 times
- 192.3 (Definitions.): picked wrongly 2 times
- 192.723 (Distribution systems: Leakage surveys.): picked wrongly 2 times
- 193.2523 (Minimizing emissions from blowdowns and boiloff.): picked wrongly 1 times
- 193.2624 (Leakage surveys.): picked wrongly 1 times

## Sections the model gets least often (true count >= 3)

- 191.3 (Definitions.): 0/4
- 192.703 (General.): 1/5
- 192.18 (How to notify PHMSA.): 1/4
- 192.12 (Underground natural gas storage facilities.): 2/4
- 192.723 (Distribution systems: Leakage surveys.): 4/6
- 192.705 (Transmission lines: Patrolling.): 3/4
- 192.3 (Definitions.): 5/6
- 192.760 (Leak grading and repair.): 21/25
- 192.763 (Advanced Leak Detection Program.): 24/27
- 193.2624 (Leakage surveys.): 4/4

## Most common confusions (true -> picked)

- 191.3 -> 192.760: 3   [Definitions. -> Leak grading and repair.]
- 192.18 -> 192.760: 3   [How to notify PHMSA. -> Leak grading and repair.]
- 192.703 -> 192.760: 2   [General. -> Leak grading and repair.]
- 192.12 -> 192.3: 2   [Underground natural gas storage facilities. -> Definitions.]
- 192.763 -> 192.760: 2   [Advanced Leak Detection Program. -> Leak grading and repair.]
- 192.763 -> 192.706: 1   [Advanced Leak Detection Program. -> Transmission lines: Leakage surveys.]
- 192.703 -> 193.2523: 1   [General. -> Minimizing emissions from blowdowns and boiloff.]
- 192.760 -> 193.2624: 1   [Leak grading and repair. -> Leakage surveys.]
- 191.29 -> 192.9: 1   [National Pipeline Mapping System. -> What requirements apply to gathering pipelines?]
- 192.705 -> 192.9: 1   [Transmission lines: Patrolling. -> What requirements apply to gathering pipelines?]

## 15 example misses

**true 191.29** (National Pipeline Mapping System.) · picked 192.9 (What requirements apply to gathering pipelines?) · true at rank 9 · margin 0.234

> 51 GPAC Vote Slides, at 30. 52 [CITATION] ; [CITATION] . 53 NPMS, About the NPMS, https://www.npms.phmsa.dot.gov/About.aspx (last accessed Apr. 25, 2024). 54 RSPA, “Pipeline Safety: [HEADING] ,” Public Workshop, 63 Fed. Reg. 36030 (July 1, 1998); Pipeline Safety Improvement Act of 2002, Pub. L. No. 107-355, Sec. 15. 55 NPMS, Public Viewer, https://pvnpms.phmsa.dot.gov/PublicViewer/ (last accessed  ...

**true 192.18** (How to notify PHMSA.) · picked 192.760 (Leak grading and repair.) · true at rank 5 · margin 0.212

> Operators would have to repair a grade 3 leak with 24 months of detection unless the operator schedules to replace the segment within five years of detection. A grade 3 leak would need to be re-evaluated every six months until the repair is complete. All known [HEADING] existing on the effective date of the final rule would have to be repaired within 36 months. An operator may request an extension ...

**true 192.12** (Underground natural gas storage facilities.) · picked 192.3 (Definitions.) · true at rank 22 · margin 0.190

> PHMSA proposes to define both leaks and hazardous leaks as “any release of gas from a pipeline that is uncontrolled at the time of discovery and is an existing, probable, or future hazard to persons, property, or the environment, or any uncontrolled release of gas from a pipeline that is or can be discovered using equipment, sight, sound, smell or touch.”6 The agency proposes to treat all leaks as ...

**true 192.760** (Leak grading and repair.) · picked 192.763 (Advanced Leak Detection Program.) · true at rank 3 · margin 0.170

> 3. Advanced Leak Detection technologies should not be limited to only those that can calculate volumetric flow; therefore, the Final Rule should provide for an alternative methodology to use instead of the volumetric requirement proposed in [CITATION] , if needed. 12

**true 192.12** (Underground natural gas storage facilities.) · picked 192.3 (Definitions.) · true at rank 22 · margin 0.144

> PHMSA proposes to define, for the purposes of all subparts of [PART] other than integrity management [PARA] requirements in [CITATION] and [PART] and P, a “leak or hazardous leak” as any release of gas from a pipeline that is uncontrolled at the time of discovery and is an existing, probable, or future hazard to persons (including operating personnel), property, or the environment, or any uncontro ...

**true 191.29** (National Pipeline Mapping System.) · picked 192.723 (Distribution systems: Leakage surveys.) · true at rank 30 · margin 0.137

> For the abovementioned reasons, [CITATION] of the proposed rule should be deleted in its entirety. Weather Events Under [NUM] of the proposed rule, operators will be required to inspect their systems to conduct advanced leak detection surveys within 72 hours of the cessation of an extreme weather. Due to the breadth of the term “extreme weather,” this requirement is impracticable. For example, the ...

**true 192.703** (General.) · picked 192.763 (Advanced Leak Detection Program.) · true at rank 2 · margin 0.126

> PHMSA indicates that FID equipment with a 500 ppm minimum sensitivity threshold is comparable to the equipment required in the proposed rule and allows the use of such equipment under [CITATION] for compressor stations. According to the 2022 GHGI estimate of 2020 annual methane emissions from U.S. natural gas systems, approximately 29% (66.7% of Transmission, storage, and LNG + 51% of Gathering an ...

**true 192.18** (How to notify PHMSA.) · picked 192.760 (Leak grading and repair.) · true at rank 2 · margin 0.115

> PHMSA must further evaluate the leak extent method and set parameters to ensure appropriate use. PHMSA should affirmatively approve any alternative leak flow rate quantification methods before allowing operators to use them, rather than using the [CITATION] notification process that does not require agency approval.

**true 192.705** (Transmission lines: Patrolling.) · picked 192.9 (What requirements apply to gathering pipelines?) · true at rank 7 · margin 0.110

> D. PHMSA has justified the need for expanding the NPMS to include gathering lines and should move forward with doing so. PHMSA has clearly justified the necessity of expanding NPMS reporting to include gathering lines by explaining how having this data will: [PARA] inform “the Secretary’s ability to make a determination as to whether and to what extent to regulate gathering lines,”67 including whe ...

**true 192.723** (Distribution systems: Leakage surveys.) · picked 192.9 (What requirements apply to gathering pipelines?) · true at rank 4 · margin 0.103

> 3. PHMSA’s proposed language regarding severe weather inspections for distribution systems: REA suggests the proposed new language under [CITATION] refer to [NUM] rather than create new severe weather inspection language. 4. PHMSA’s proposed requirement to include Type A, B, and C Gathering Lines in NPMS submittals: The proposed requirement for Type A, B, and C Gathering Line Operators to submit s ...

**true 192.760** (Leak grading and repair.) · picked 193.2624 (Leakage surveys.) · true at rank 4 · margin 0.102

> • Annual report should include a list of all [HEADING] being monitored rather than repaired pursuant to proposed [CITATION] (if that component of the proposal is retained). V. LNG Facilities A. Leak Surveys and Repair Joint Environmental Commenters continue to support PHMSA’s proposal to require quarterly methane [HEADING] at LNG facilities. GPAC voted to recommend repair timelines for [HEADING] t ...

**true 191.3** (Definitions.) · picked 192.760 (Leak grading and repair.) · true at rank 12 · margin 0.075

> 81 [CITATION] . 82 Proposed Rule, at 31945. 83 GPAC Voting Slides, at 31. 84 Id. 85 EPA, “Greenhouse Gas Reporting Rule: Revisions and Confidentiality Determinations for Petroleum and Natural Gas Systems,” 88 Fed. Reg. 50282, 50288 (Aug. 1, 2023). 86 EPA, “Greenhouse Gas Reporting Rule: Revisions and Confidentiality Determinations for Petroleum and Natural Gas Systems,” 88 Fed. Reg. 50282, 50298 ( ...

**true 192.703** (General.) · picked 193.2523 (Minimizing emissions from blowdowns and boiloff.) · true at rank 2 · margin 0.075

> 1 These proposals include amendments to the pipeline safety regulations covering [HEADING] , LNG facilities, and Type C gas gathering pipelines. 2 See PHMSA’s proposed regulatory text [CITATION] which exempts certain aspects of the PHMSA proposed rule if the facility is subject to certain aspects of EPA’s OOOO series regulations. EPA’s OOOO series regulations are currently undergoing revision as p ...

**true 191.3** (Definitions.) · picked 192.760 (Leak grading and repair.) · true at rank 2 · margin 0.074

> PHMSA proposes to modify [CITATION] so that the estimated cost of property damage would explicitly exclude “the cost of gas lost, the cost to acquire permits, and the cost to remove and replace non-operator infrastructure that was not damaged by the release”. Additionally, PHMSA proposes to define a “Grade 1 leak,” in part, as “[a]ny leak defined as an incident in [CITATION] .” 11

**true 192.3** (Definitions.) · picked 192.760 (Leak grading and repair.) · true at rank 2 · margin 0.072

> This proposed nuance aligns with the intent of Congress's directive in the PIPES Act of 2020, which instructs PHMSA to compel operators to repair or replace “each leaking pipe, except a pipe with a leak so small that it poses no potential hazard.” Accordingly, under our suggested modification, grade 2 and 3 level emissions that would be safely confined within the secondary containment structure wo ...

## Reading (5 Nov)

21 of 27 misses have the true section at rank 2–5; 192.760 (leak grading and repair) absorbs 11 wrong picks and is also the label for a quarter of the test passages. The 9 cross-part picks are the parallel leakage-survey sections for transmission, distribution and LNG, where the passage says "leakage surveys" and which part applies depends on the operator's system. Miss margins are half the hit margins. Same pattern as HHS with a smaller penalty: PHMSA commenters use technical nouns that separate neighbouring sections, and masking removes fewer heading phrases there (45% of passages against 69%).