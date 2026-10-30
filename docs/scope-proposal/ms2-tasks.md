# MS2 task list

Updated Mon 12 Oct. Owners can change, say so on the ticket.

Due Tue 20 Oct, 10:00 PM ET. Commit hash on Canvas from the `milestone2` branch. The 15 minute talk to Alyssa is Fri 23 Oct, and anyone can be asked about any part.

## What MS2 asks for, and where we are

| Requirement | State today | Gap | Tickets |
|---|---|---|---|
| Each component in a container, one command to run | Seven services in `docker-compose.yml` | Processor and grouping into the chain. Add the passage stage. Clean-clone test. | #4, #5, #10, #43, #23 |
| Data versioning | DVC on GCS, two dockets | Lead and copper docket, in review | #42 |
| RAG: collection, chunking, vector DB | `rule-passages` with ChromaDB, 79 tests | Add the lead and copper proposal | #44, #14 |
| One retrieval flow, query to context, with input and output | `/retrieve` works on the water rule | Redo on a real organization letter, with logs and one failure | #18 |
| App skeleton with UI calling the back end | `api-service` and `frontend` exist | Sections endpoint and a page that calls it | #46, #37, #15 |
| Setup doc and screenshot of running instances | Not done | Do it | #20, #21 |

## Tickets

| Ticket | What | Owner | Reviewer | Due |
|---|---|---|---|---|
| #4 U-04 | Processor: records to letters | Andrew | Aadil | Mon 12 |
| #5 U-05 | Grouping into representatives | Andrew | | Wed 14 |
| #42 U-25 | Lead and copper docket in DVC (PR #41) | Livia | Aidan | Tue 13 |
| #40 U-33 | Follow-ups from the reviews of #38 and #39 | Aadil, Livia | | Thu 15 |
| #10 U-10 | Compose runs the chain from a fresh clone. The gate. | Aidan, Livia | Rishi | Thu 15 |
| #43 U-26 | Passage stage: split comments, read section citations | Aidan | Aadil | Thu 15 |
| #44 U-27 | `rule-passages`: add 88 FR 84878 | Aidan | Rishi | Thu 15 |
| #14 U-14 | Two chunk sizes, BM25 against embeddings, on cited passages | Aidan | Rishi | Thu 15 |
| #47 U-30 | Hand check of the model-made labels, second reader | Rishi | Aadil | Thu 15 |
| #37 U-32 | `/retrieve`: raise the cap on k, add a merged list | Rishi | | Fri 16 |
| #45 U-28 | Baseline table for linking | Aadil | Aidan | Sat 17 |
| #46 U-29 | `GET /rules/{docket}/sections` | Rishi | Aidan | Sat 17 |
| #15 U-15 | Rule page calling the API | Rishi | Aidan | Sun 18 |
| #18 U-18 | Trace one organization letter, with logs and one failure | Andrew | Aidan | Sun 18 |
| #48 U-31 | README note: what changed since MS1 | Aidan | Livia | Sun 18 |
| #21 U-21 | README with exact run instructions | Aidan | | Sun 18 |
| #20 U-20 | Setup doc and screenshots | Livia, Rishi | Aidan | Mon 19 |
| #23 U-23 | Clean-clone test by someone who did not write the compose file | Andrew | | Mon 19 |
| #22 U-22 | Slides, then the drill | Everyone, Aidan assembles | | Mon 19 |
| #24 U-24 | Push `milestone2`, hash on Canvas | Livia | | Tue 20 |
| #12 U-12 | Processor at full scale | Andrew | | After the chain runs |

Closed or moved: #13 (clustering comparison, not needed), #16 (replaced by #47), #17 (moved to MS4).

## By person

| Person | Tickets |
|---|---|
| Aidan | #43, #44, #14, #48, #21. #10 with Livia. Assembles #22. |
| Livia | #42, #40, #20, #24. #10 with Aidan. |
| Andrew | #4, #5, #18, #23. #12 if time. |
| Rishi | #47, #37, #46, #15. #20 with Livia. |
| Aadil | #45, #40. Reviews #4 and #43. |

## Dates

| By | What should be true |
|---|---|
| Tue 13 | Processor merged. Lead and copper docket merged. |
| Thu 15 | Chain runs end to end on the 40-record sample with one command. Passage stage runs. Lead and copper rule indexed. Second hand check back. |
| Fri 16, 3:30 PM | Check-in with Alyssa. Show the chain running and the architecture diagram. |
| Sat 17 | Baseline table has numbers. Sections endpoint merged. |
| Sun 18 | Page calls the API. Retrieval example written up. README drafted. |
| Mon 19 | Clean-clone test. Setup doc and screenshots. `milestone2` branch cut. |
| Tue 20, 10 PM | Hash on Canvas |
| Fri 23 | Talk to Alyssa |

## Not in MS2

The reader that links and extracts with a model. Merging asks and conflict detection. Any training. The public mirror reader. Reading every open rule. These are MS3 and later, and the slides show them as the plan with the numbers from our tests.
