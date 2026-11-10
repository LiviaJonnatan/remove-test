# Misses on HHS-OS-2022-0012 (52 of 100 test passages, 48.0% top-1)

## Where the true section ranked

- rank 2: 23
- rank 3-5: 13
- rank 6-10: 7
- rank >10 (not in top10): 9

## What was picked instead

- same part, not adjacent: 34
- adjacent section: 17
- different part: 1

## Confidence

median margin on hits 0.143, on misses 0.064

## Sections that absorb wrong picks

- 92.207 (Nondiscrimination in health insurance and other health-related coverage.): picked wrongly 14 times
- 92.4 (Definitions.): picked wrongly 8 times
- 92.201 (Meaningful access for limited English proficient individuals.): picked wrongly 6 times
- 92.10 (Notice of nondiscrimination.): picked wrongly 3 times
- 92.11 (Notice of availability of language assistance services and auxiliary aids and services.): picked wrongly 3 times
- 92.101 (Discrimination prohibited.): picked wrongly 3 times
- 92.8 (Policies and procedures.): picked wrongly 3 times
- 92.206 (Equal program access on the basis of sex.): picked wrongly 3 times

## Sections the model gets least often (true count >= 3)

- 92.301 (Enforcement mechanisms.): 0/3
- 92.8 (Policies and procedures.): 1/6
- 92.10 (Notice of nondiscrimination.): 1/5
- 92.2 (Application.): 1/5
- 92.206 (Equal program access on the basis of sex.): 3/12
- 92.210 (Nondiscrimination in the use of clinical algorithms in decision-making.): 4/8
- 92.201 (Meaningful access for limited English proficient individuals.): 2/4
- 92.101 (Discrimination prohibited.): 6/11
- 92.7 (Designation and responsibilities of a Section 1557 Coordinator.): 2/3
- 92.4 (Definitions.): 2/3

## Most common confusions (true -> picked)

- 92.206 -> 92.207: 7   [Equal program access on the basis of sex. -> Nondiscrimination in health insurance and other health-related coverage.]
- 92.210 -> 92.207: 3   [Nondiscrimination in the use of clinical algorithms in decision-making. -> Nondiscrimination in health insurance and other health-related coverage.]
- 92.2 -> 92.4: 3   [Application. -> Definitions.]
- 92.11 -> 92.10: 2   [Notice of availability of language assistance services and auxiliary aids and services. -> Notice of nondiscrimination.]
- 92.207 -> 92.101: 2   [Nondiscrimination in health insurance and other health-related coverage. -> Discrimination prohibited.]
- 92.101 -> 92.208: 2   [Discrimination prohibited. -> Prohibition on sex discrimination related to marital, parental, or family status.]
- 92.207 -> 92.206: 2   [Nondiscrimination in health insurance and other health-related coverage. -> Equal program access on the basis of sex.]
- 92.101 -> 92.207: 2   [Discrimination prohibited. -> Nondiscrimination in health insurance and other health-related coverage.]
- 92.8 -> 92.201: 2   [Policies and procedures. -> Meaningful access for limited English proficient individuals.]
- 92.201 -> 92.11: 2   [Meaningful access for limited English proficient individuals. -> Notice of availability of language assistance services and auxiliary aids and services.]

## 15 example misses

**true 92.9** (Training.) · picked 92.8 (Policies and procedures.) · true at rank 12 · margin 0.539

> Regarding record retention, we support the addition of a record retention policy for the reasons covered in the NPRM. We believe that maintaining records of prior incidents can help identify patterns of discrimination and better support corrective actions, particularly if a change in policy is warranted. However, we retain significant concerns about data protection with regards to any such records ...

**true 92.207** (Nondiscrimination in health insurance and other health-related coverage.) · picked 92.101 (Discrimination prohibited.) · true at rank 3 · margin 0.320

> This language should also be added to [CITATION] , [PARA] , and [PARA] . We also applaud HHS for articulating a clear and expansive explanation of discrimination [HEADING] . As explained supra in Part I.B, federal case law – including the Supreme Court’s decisions in Price Waterhouse v. Hopkins and Bostock v. Clayton County – makes clear that federal sex discrimination law includes sex stereotypes ...

**true 92.8** (Policies and procedures.) · picked 92.211 (Nondiscrimination in the delivery of health programs and activities through telehealth services.) · true at rank 13 · margin 0.302

> 87 Saeed, S. A. & Masters, R. M. (2021, July 23). Disparities in Health Care and the Digital Divide. Current Psychiatry Reports. https://doi.org/ [NUM] /s11920-021-01274-4 88 Chang, et al. (2021, June 1). Rapid Transition to Telehealth and the Digital Divide: Implications for Primary Care Access and Equity in a Post-COVID Era. The Millbank Quarterly. https://doi.org/ [NUM] /1468- [NUM] [HEADING] ( ...

**true 92.206** (Equal program access on the basis of sex.) · picked 92.207 (Nondiscrimination in health insurance and other health-related coverage.) · true at rank 4 · margin 0.277

> Ensuring that individuals are not discriminated against [HEADING] gender identity and sexual orientation when accessing health care and services or in issuance of insurance policies is an essential step in reducing the numerous health disparities among LGBTQIA+ populations. Codifying protections against discrimination is crucial in providing a basis for equitable care and evidence shows that antid ...

**true 92.2** (Application.) · picked 92.4 (Definitions.) · true at rank 2 · margin 0.218

> Accordingly, our comments on the provisions of the 2022 Proposed Rule are as follows: 2022 PROPOSED RULE SUBPART A – GENERAL PROVISIONS: Application ( [CITATION] ) The Legal Action Center supports the 2022 Proposed Rule which restores regulations recognizing § 1557’s applicability to federal health programs like Medicaid, Medicare, the ACA’s state and federal Marketplaces and the plans sold throug ...

**true 92.101** (Discrimination prohibited.) · picked 92.207 (Nondiscrimination in health insurance and other health-related coverage.) · true at rank 3 · margin 0.217

> • Explicitly include transgender status in the definition of discrimination [HEADING] at [CITATION] and throughout the regulation. While the terms “gender identity” and “transgender” are often used interchangeably, this clarification would remove potential ambiguity; • State unequivocally that Section 1557, as federal law, preempts any state or local law restricting insurance coverage or the provi ...

**true 92.201** (Meaningful access for limited English proficient individuals.) · picked 92.11 (Notice of availability of language assistance services and auxiliary aids and services.) · true at rank 4 · margin 0.213

> The agency proposes to allow covered entities to be deemed in compliance with the regulation if they provide individuals with the option on an annual basis in their preferred language to opt out of receiving a Notice of Availability. Providing individuals with the option to opt out of receiving these notices does not absolve the covered entity of providing appropriate language access [HEADING] sup ...

**true 92.2** (Application.) · picked 92.4 (Definitions.) · true at rank 4 · margin 0.190

> On May 18, 2016, the HHS Office of Civil Rights [PARA] finalized its first set of regulations implementing Section 1557 at [CITATION] For historical context, when the Americans with Disabilities Act [PARA] was enacted in 1990, it represented a watershed moment enshrining the civil rights protections of individuals with disabilities. The ADA notably omitted language addressing the field of health c ...

**true 92.2** (Application.) · picked 92.8 (Policies and procedures.) · true at rank 19 · margin 0.163

> We appreciate the agency’s efforts to attain consistent the application of the regulation. The 2020 Rule removed certain requirements related to CEs maintaining written [HEADING] . This proposal reinstates these requirements, such that CEs consistently and clearly lay out these procedures so individuals can more easily submit grievances when problems arise. Allowing individuals to voice concerns t ...

**true 92.101** (Discrimination prohibited.) · picked 92.202 (Effective communication for individuals with disabilities.) · true at rank 12 · margin 0.157

> Additionally, we appreciate the inclusion of the definition of the term “companion,” and HHS’s explanation that a companion may include a “family member, friend, or associate of an individual. . .” who is “an appropriate person with whom a covered entity should communicate.” However, we support CCD’s comments that the determination of who is appropriate must lie with the individual with a disabili ...

**true 92.101** (Discrimination prohibited.) · picked 92.208 (Prohibition on sex discrimination related to marital, parental, or family status.) · true at rank 2 · margin 0.154

> 3 For example, several court decisions make clear that Title VII’s protection against discrimination [HEADING] , including, “pregnancy . . . or related medical conditions” reach abortion. See, e.g., Doe v. C.A.R.S. Prot. Plus, Inc., 527 F.3d 358, 364 (3d Cir.), order clarified, 543 F.3d 178 (3d Cir. 2008); Turic v. Holland Hosp., Inc., 85 F.3d 1211 (6th Cir. 1996). 4 Nondiscrimination in [HEADING] ...

**true 92.210** (Nondiscrimination in the use of clinical algorithms in decision-making.) · picked 92.207 (Nondiscrimination in health insurance and other health-related coverage.) · true at rank 2 · margin 0.143

> B. The proposed rule would prohibit the discriminatory [HEADING] and crisis standards of care The discriminatory [HEADING] has no place in health care. Proposed [CITATION] would make explicit that covered entities are prohibited from discriminating through [HEADING] race, color, national origin, sex, age, or disability under [CITATION] Many clinical algorithms dictate that Black patients, for exam ...

**true 92.206** (Equal program access on the basis of sex.) · picked 92.204 (Accessibility of information and communication technology for individuals with disabilities.) · true at rank 15 · margin 0.138

> For technology to work for people with disabilities, it must be accessible from the outset.6 Unfortunately, the need for disabled people to prove their disability to assert their rights— unlike other marginalized groups—has led to a tendency of retrofitting accessibility.7 This tendency runs counter to the principles of disability justice. Retrofitting accessibility is often more expensive than bu ...

**true 92.207** (Nondiscrimination in health insurance and other health-related coverage.) · picked 92.206 (Equal program access on the basis of sex.) · true at rank 2 · margin 0.122

> Recommendation: HHS should finalize its proposal to equal program access with the clarification that covered entities are obligated to ensure equal access to their [HEADING] without discrimination [HEADING] actual or perceived sex, including pregnancy, sexual orientation, gender identity and sex characteristics. [HEADING] Coverage [HEADING] ( [CITATION] )

**true 92.202** (Effective communication for individuals with disabilities.) · picked 92.201 (Meaningful access for limited English proficient individuals.) · true at rank 10 · margin 0.122

> machine translation is particularly prone to syntactic and semantic errors that can alter meaning or render communications incomprehensible. One study investigating the error rate of Google translations from English of phrases for common medical communications found significant errors, with a substantially higher error rate for nonEuropean languages.12 Moreover, many of the translation errors cons ...

## Reading (5 Nov)

Of the 15 most confident misses, 2 are the model being wrong, 6 are the citation label pointing at a section the passage isn't about (the model's pick is the better one), and 7 are passages that genuinely argue about two overlapping sections (92.206/92.207/92.101 on sex discrimination; 92.201/92.202/92.11 on language and communication access). The confusion pairs at scale match: 92.206→92.207 (7) and 92.210→92.207 (3). Section 1557's sections overlap on the subject most commenters write about.

`[HEADING]` masking removes phrases like "on the basis of sex" and "use of clinical algorithms", which are the words that separate neighbouring sections; the test score is measured with those words removed, and a real uncited comment would keep them. `[HEADING]` appears in 69 of 100 HHS test passages (127 tokens) against 45 of 100 PHMSA passages (79), so the masking costs HHS more, though both rules' sections overlap around a hub section.

With 92.4 (Definitions) excluded as a candidate, top-1 moves from 48 to 49 of 100 while the 3 passages labelled 92.4 become unreachable; the next candidate is usually wrong too, so removing the hub section does not help.