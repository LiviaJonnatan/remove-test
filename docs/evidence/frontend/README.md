# frontend evidence

The rule page calling the API, captured on 15 Oct 2026 on a laptop after `docker compose up --build -d`
with the `.env.example` docket settings: the 40-record MS2 sample of EPA-HQ-OW-2022-0801 (lead and
copper). The collector fetched 40 records and 11 attachments, the processor wrote 40 letters with 0
failed, the campaign builder found one exact-match group of 2, and rule-passages embedded the proposal
(88 FR 84878) as 1,111 passages. The 13 Oct laptop run says 879: it predates
#67, which stopped the markup cleaner deleting text between a bare "<" and ">" in this rule. The 19 Oct VM
run says 1,108, after the outline fix in #83. The same ChromaDB also held the development docket from earlier runs, so `/health` lists
both dockets and the page was opened with `?docket=EPA-HQ-OW-2022-0801`.

| File | What it shows |
| --- | --- |
| [`../ui-calling-backend.png`](../ui-calling-backend.png) | The page at `localhost:3000/?docket=EPA-HQ-OW-2022-0801`: 88 sections, with V > B > 1 (Mandatory Full Service Line Replacement, 144 rule passages) open in the details panel. The browser's Network tab shows the call to `/api/rules/EPA-HQ-OW-2022-0801/sections` answered 200 |
| `requests.log` | The screenshot's session in the two containers' logs, a first load and the reload before the screenshot: nginx serves the page and its script, the script calls `/api/rules/EPA-HQ-OW-2022-0801/sections`, nginx forwards it to `api-service`, and the API answers 200 |

The path a request takes: the browser only knows `localhost:3000`. nginx (`frontend/nginx.conf`) serves
the built page and forwards anything under `/api/` to `api-service:8000` on the compose network, minus the
`/api` prefix. With `?docket=` in the address the page skips `/health`, so one API call fills the table.

Known limits:

- The screenshot's citing passages and letters show "—": it was taken before the API read
  passage-stage's links. The live sections endpoint now sends numbers for this sample (0 on preamble
  headings; see [`../api-service/`](../api-service/README.md)). [`citing-passages.png`](citing-passages.png)
  shows them: § 141.84 open, 39 citing passages from 5 letters, the first 20 listed from
  `/api/rules/EPA-HQ-OW-2022-0801/passages`, each linked to its letter on Regulations.gov.
- The lead and copper outline comes from rule-passages as it parses the Federal Register XML, and the
  page shows it as is. In this screenshot (15 Oct, before #83) the first top-level entry is titled
  "I. Executive Summary II. Public Participation", with a child `I/I`: two headings joined into one,
  and Part VI has no passages. #83 fixed both: the outline now runs I to XI in order with VI back.
  Part III (General Information) is absent on purpose: it is procedural, and the sections endpoint
  leaves procedural sections out.
