
---

# Proposals

### A1. Sponsor attribution investigators
**Issue:** The project's title question. On the development docket 92 of 201 campaign
records have no sponsor, and the proposal currently answers that with a hand audit. The idea is to replace
the hand audit with an investigation per campaign and keeps the hand audit as the test set.

**What the agents do:** One *investigator* per campaign reads the
campaign's record, cover letter and attachment text and forms hypotheses about the sponsor. It
spawns subagents, each a child step with its own budget:

- *Attachment forensics*: PDF metadata (producer, author, creation tool), petition-platform
  fingerprints (CREDO, Change.org, Action Network export formats), email headers in cover pages,
  letterhead text from OCR.
- *Web evidence*: searches the live web and the Wayback Machine around the comment period for the
  template sentence, finds the action page that hosted it, and records the URL and snapshot date.
- *Cross-docket match*: queries our own letter index for the same template or the same signer-list
  format in other dockets, so a sponsor identified once is carried to every docket it appears in.
- *Signer-list analyst*: given the parsed, hashed signer list, writes and runs checks in a sandboxed
  code step (ZIP against listed state, claimed versus listed count, duplicate rate, towns with
  ZIPs from every region) and reports the file-level observations only.

The investigator writes a dossier: candidate sponsor, confidence, every piece of evidence with a
citation, and what it could not find. A *verifier* agent re-opens each citation and strikes
anything it cannot confirm. A *reviewer* agent compares the dossier's methodology against a
checklist and sends it back once if a check was skipped.

**On Kubernetes.** `attribute-docket` workflow: one investigator step per campaign (201 on the
development docket, 230 on the transfer docket, the top few hundred clusters on FCC), each with
four child steps, a verifier and a reviewer. Parallelism capped by a semaphore so API keys and
model rate limits are respected. Web fetches go through a shared cache so a rerun is cheap.

**Compute.** About 40 to 80 model calls per campaign across the subagents, roughly 400k to 700k
tokens. Development plus transfer dockets: 431 campaigns, about 250M tokens. FCC top 300: another
200M. Plus a sandboxed code pod per signer list (the big lists are 1,700-page PDFs).

**Evaluation.** Hold out the sponsor field on the 109 campaigns EPA names and score attribution
accuracy and citation validity. On the 92 unknowns, the hand audit (already planned) becomes the
test set. Report how often the verifier struck a claim: that number is the honesty of the system.

**Milestone fit.** MS3 (campaign evidence, sponsor audit). Replaces the MS1 "hand audit of the 92
unknown-sponsor campaigns" with "hand audit as ground truth for the investigators".

**Risk.** Attribution to the wrong group is the harm the proposal warns about, so the dashboard
shows the dossier's evidence and the verifier's verdict, never only the name.

### A2. Adversarial rewording red team that feeds fine-tuning

**Issue:** The MS1 proposal rewords letters once with an LLM at five strengths and uses them only
as a test, i.e. that the fine-tuned model should beat MinHash at each strength. The rewrites never reach
training. The idea is to use the rewrites for training as well as testing, and generate them in rounds
against the model as it improves. Two sides take turns: 
- The *generator* is the red team: LLM agents whose job is to write reworded copies of a campaign
  letter that keep its argument but escape the grouper.
- The *grouper* is the model under attack: the fine-tuned embedding model plus HDBSCAN that decides
  which letters belong to the same campaign.


**What the agents do.** An *attack planner* reads the current grouper's failures and picks
strategies. It spawns *attacker* subagents, each with one strategy and one model (paraphrase,
persona injection, sentence reordering, argument substitution, partial template plus original
text, translation round trips), each producing rewrites at the five strengths. A *fidelity judge*
checks that every rewrite still makes the template's argument and stance, so the rewrite is a true
campaign member and not a different letter; rejected rewrites are discarded. A *miner* runs the
current model, keeps the rewrites it fails on, and labels them as hard positives. A *trainer* step
fine-tunes, an *evaluator* step scores B-cubed F1 on held-out sponsors, and the loop continues
until the adversarial score plateaus or the budget is spent.

**On Kubernetes.** `redteam-round` workflow: attackers fan out on the CPU pool (they are model
calls), the judge fans out per rewrite behind KEDA, the trainer runs on the L4 pool, and the
evaluator gates whether the new checkpoint is promoted. W&B records every round, every attacker's
success rate, and the model's curve. Argo's `retryStrategy` and `activeDeadlineSeconds` keep a
runaway attacker from burning the budget.

**Compute.** Per round: 2,000 seed letters, 6 strategies, 5 strengths, 60k rewrites at about
1.5k tokens each, 90M tokens generated and another 90M judged. Eight to ten rounds: 1.5B to
2B tokens. Fine-tuning `bge-small` is minutes per round; to use the GPU pool properly, also train
`bge-base` and `bge-large` on the same data (a few GPU hours per round on L4) and report all
three, which is a real experiment on model size against adversarial rewording.

**Evaluation.** The existing one: B-cubed F1 against exact match, MinHash at 0.5 and 0.8, and the
untuned model, on the held-out sponsor, at each strength. Add: success rate of an *unseen* attacker
model, which is the proposal's "unseen LLM" criterion.

**Milestone fit.** MS3 (fine-tuning on Vertex AI with W&B, Vertex pipeline). The round is the
Vertex pipeline; the gate is the gated retraining from MS5, delivered early.

### A3. Argument graph: a knowledge graph of what the docket argues, and who argues it

**Issue:** An agency must respond to every significant comment, and today the pipeline only links a
campaign to the rule sections it argues about. The idea is to have
agents build a knowledge graph of the whole docket: the claims letters make, the provisions they
target, the authorities they cite, the campaigns and sponsors behind them, and the rebuttals
between opposing claims. The graph is what the analyst screen visualizes, and it is what A1, B2
and B3 query.

**The graph.** Node types: *provision* (a rule section, from the existing chunks), *claim* (one
assertion, deduplicated across letters), *authority* (a statute, court case, study or agency
document a letter cites, such as Rapanos or the 2015 Clean Water Rule), *campaign*, *sponsor*,
and *individual comment* (a node per comment, rendered only in aggregate). Edge types: campaign
or comment *makes* claim, with the supporting quote and record ID on the edge; claim *supports*
or *opposes* provision; claim *cites* authority; claim *rebuts* claim; sponsor *runs* campaign;
campaign *shares template with* campaign (from the grouper). Every edge carries a citation, so a
verifier can re-open it.

**What the agents do.** An *extractor* per letter (one per campaign template, one per individual
comment) emits claims as graph triples, using the existing BM25 and dense retrievers as tools to
ground each claim in a provision. A *resolver* merges claims that say the same thing in different
words, by generating candidate pairs with embeddings and spawning a *judge* subagent (a different
model) per candidate pair, and canonicalizes authorities to one node each. A *relation finder*
walks each provision's opposing claims and adds *rebuts* edges where one claim answers another. An
*analyst* step runs graph analytics: which provisions draw the most argument, weighted by comments
behind each claim; which sponsors form coalitions by making the same claims; which authorities
each side leans on; and which claims appear only in individual comments and in no campaign, since
those are the arguments a form-letter count would hide. An *auditor* subagent samples edges and
re-checks each against its citation.

**Why it is worth visualizing.** The graph on the dashboard is the docket as a debate: provisions
in the middle, claims around them colored by stance, campaigns sized by comment count, sponsors
grouped by the claims they share, rebuttal edges crossing between sides. An analyst clicks a
provision and sees every argument for and against, the campaigns and sponsors making each, the
authorities cited, and the quotes with record IDs. A1's dossier attaches to the sponsor node, and
B2's registry adds the same sponsor's edges from other dockets.

**On Kubernetes.** `graph-docket` workflow: extractors run as a KEDA-scaled worker pool off a
Pub/Sub topic (11,243 individual comments plus 201 templates on the development docket; 25,976
plus 230 on transfer); the resolver's candidate pairs are embedded on the L4 pool and judged by a
second KEDA pool; the relation finder, analyst and auditor run as steps. The graph lives in Neo4j
as a StatefulSet on the always-on pool, with the claim and edge tables mirrored in Postgres so the
API and the evaluation read the same rows. The frontend queries the graph by provision, campaign
or sponsor and renders it as an interactive force-directed view.

**Compute.** About 38,000 extractions at 3k to 4k tokens each: 130M to 150M tokens. Resolving
claims: embedding every claim is cheap, judging about 50,000 candidate pairs at 1k tokens is
50M. Relation finding, analytics and audit: 30M. Roughly 250M tokens per pair of dockets, plus a
GPU hour for the claim embeddings.

**Evaluation.** Extend the 50 hand-mapped campaigns to claim level (which claims, which provision,
which authorities) and score extraction against them; keep the top-1 section accuracy from the
current `eval`. For the resolver, hand-label 100 claim pairs as same or different and report
precision and recall of the merge. For the graph, hand-check 30 edges of each type against their
citations.

**Milestone fit.** MS3 and MS4. It turns the MS1 "link" step from a retrieval demo into the
structure the analyst screen, the copilot and the docket watch are built on.

---

## Bigger proposals

### B1. All 24 million FCC 17-108 filings, grouped and audited

**What it advances.** Scale, and the only ground truth about fraud we have. The proposal plans a
stratified sample of FCC 17-108. This processes the whole proceeding, finds its campaigns, and has
agents audit the largest against the NY AG report and Kao's cluster.

**What it is.** A sharded, map-reduce grouping on the cluster: MinHash and LSH over 24M filings on
the CPU pool (Ray on KubeRay, or plain Argo shards), embedding of the representatives and the
long tail on the L4 pool, HDBSCAN on the representatives on one high-memory node, then
assignment of the rest to the nearest representative under the endpoint's threshold. The agent
layer is A1's investigators on the top 300 to 500 clusters, plus an *auditor* agent per cluster
that reads the NY AG report and Kao's article as tools, decides whether the cluster corresponds
to a named campaign, and writes the correspondence with page citations.

**On Kubernetes.** `fcc-full` workflow: the collector shards by date window across API keys; a
MinHash shard step per window; an LSH merge; embedding shards with GPU node affinity; HDBSCAN on a
`highmem` node selector; assignment shards; then A1 and the auditor fan-out. Each stage writes
its artifact to GCS so a failed shard reruns alone.

**Compute.** Embedding 24M filings with `bge-small` at roughly 1k to 2k filings per second per L4
is about 4 to 7 GPU hours, so under an hour on eight L4s. MinHash on 24M is a few hundred CPU
hours spread over the batch pool. HDBSCAN over 500k representatives needs a 128 GB node for an
hour or two. The agent audit is 300 to 500 investigations at A1's cost, about 250M tokens. The
collector itself is the slow part at 24,000 paged calls, which is why it shards by key.

**Evaluation.** The proposal's ranking criterion, now on the whole proceeding: how many of the
NY AG's campaigns land in our top 20, and how much of Kao's 1.3M cluster we recover (B-cubed
against his cluster as the label).

**Milestone fit.** MS4 (FCC evaluation) with the infrastructure delivered in MS3.

### B2. Docket watch: from one docket to the federal comment stream

**What it advances.** Widens the goal from "given a docket" to "watch rulemaking as it happens".
Sponsors run campaigns across many dockets, so a sponsor attributed once should be recognized
everywhere, and a mass campaign is most useful to flag while the comment period is open.

**What it is.** A CronJob polls Regulations.gov for dockets with open comment periods and the
daily comment counts. A *triage* agent ranks them (volume, rate of change, mass-comment records
appearing, agency) and, within a daily budget, starts the pipeline for the ones that matter as
Argo workflows with per-docket resources. Every run writes into a **cross-docket sponsor
registry**: template fingerprints, signer-list formats and attributed sponsors, so A1's
cross-docket subagent gets stronger with every docket. A *digest* agent writes a daily summary per
watched docket (new campaigns, size, attributed sponsors, new arguments) with citations.

**On Kubernetes.** This is the proposal that needs the cluster to be a platform rather than a job
runner: CronJobs, Argo `WorkflowTemplates` parameterized by docket, KEDA pools shared across
dockets, resource quotas per namespace so one docket cannot starve another, and a budget
controller that stops spawning when the day's credit is spent.

**Compute.** Depends on how many dockets are watched. Twenty mid-size dockets over the semester,
each a fraction of the development docket, is roughly two to four development-docket runs of
A1 plus A3, so on the order of 1B tokens over the term plus the collector's API time.

**Evaluation.** The transfer docket is the first "new" docket the watch sees; report how much of
A1's attribution and A3's argument graph carries over with unseen sponsors. For the registry,
report how many sponsors are recognized from a prior docket rather than investigated again.

**Milestone fit.** MS5. It is the "beyond the milestone" item and it is what the blog post and
video are about.

### B3. Analyst copilot that investigates and drafts the response

**What it advances.** The serving layer. The analyst today gets a dashboard; this gives them an
agent with tools over everything the pipeline produced, which can answer multi-step questions and
draft the response-to-comments with every sentence cited.

**What the agents do.** A *copilot* with typed tools: SQL over campaigns, claims and dossiers; graph queries over A3's argument graph;
retrieval over letters and rule passages; the signer-check sandbox; and the ability to spawn
subagents for an investigation ("find every campaign arguing against the ditch exclusion, who
sponsors them, and whether their signer files overlap"). A *drafting* mode produces a section of
the agency's response for a provision: the arguments raised, how many comments raised them, and
representative quotes, each cited to a record ID. A *citation checker* re-queries every citation
before the draft is shown. The copilot refuses questions about a named individual by design.

**On Kubernetes.** An agent gateway deployment behind the API with an HPA; each investigation
runs as a short Argo workflow so long multi-subagent jobs do not hold an HTTP connection; results
stream back by session ID. Traces to W&B or a Langfuse deployment on the cluster.

**Compute.** 50k to 200k tokens per investigation. The evaluation set below, run five times per
model and prompt version, is the cost that matters: 200 questions, five runs, about 100M tokens
per evaluation sweep.

**Evaluation.** A 200-question set with answers derived from the hand labels and A3's argument graph
(counts, sponsors, provisions), scored for correctness and for citation validity; plus the
B-cubed and top-1 numbers the copilot's answers must agree with.

**Milestone fit.** MS4 for the copilot over the development docket, MS5 for drafting and for the
copilot over the watch.

---

## Compute summary

Token figures assume a mid-tier hosted model on Vertex AI or the Claude API; multiply by the
model's per-million-token price for dollars. GPU figures are L4 hours unless stated.

| Proposal | Model tokens | GPU and other compute | Scale knob |
| --- | --- | --- | --- |
| A1 Sponsor investigators | 250M (two dockets), +200M for FCC top 300 | Sandboxed code pods per signer list | Number of campaigns investigated |
| A2 Red team loop | 1.5B to 2B over 8 to 10 rounds | A few L4 hours per round if `bge-base` and `bge-large` are trained too | Rounds, strategies, model sizes |
| A3 Argument graph | 250M per pair of dockets | KEDA worker pools, one L4 hour, Neo4j StatefulSet | Share of individual comments extracted |
| B1 FCC full scale | 250M for the audit | 4 to 7 L4 hours for embedding, hundreds of CPU hours for MinHash, one 128 GB node for HDBSCAN | Number of clusters audited |
| B2 Docket watch | About 1B over a term | Shared pools, CronJobs | Dockets watched per day |
| B3 Analyst copilot | 100M per evaluation sweep | Always-on gateway, HPA | Questions and runs per sweep |

Together the additive three are about 2B to 2.5B tokens and a few dozen GPU hours. That is
within a course credit budget, and each proposal has a knob that scales it down without changing
what it is.



## What to pick

The additive three fit MS3 and MS4 and give the architecture its shape: Argo and KEDA on GKE,
the `agent-runner` image, the verifier step, Postgres beside Chroma. Of the bigger three, B1 is
the natural MS4 target because it uses the GPU pool and the only fraud ground truth we have, and
B3 is the MS5 target because it is what the analyst sees. B2 is the stretch, and it is the one to
describe in the blog post as where the system goes next even if only the registry and the
CronJob ship.

The architecture figure (Appendix B of the MS1 proposal) changes from "one batch run per docket
fills the store the API serves" to: a GKE platform runs per-docket workflows; agents investigate,
extract and audit inside those workflows with verifiers between them and the store; the API and
the copilot serve from the store; and the red-team loop gates which embedding model the
workflows use.
## The backbone the proposals share

Build this once, on GKE, and each proposal becomes a workflow on top of it. It also pulls the
MS5 Kubernetes work forward to MS3, which is where the feedback says the architecture should be.

| Piece | What it is | Why |
| --- | --- | --- |
| GKE cluster, three node pools | A CPU batch pool that scales to zero, an L4 GPU pool for embedding and fine-tuning, a small always-on pool for the API, the agent gateway and the stores | Batch and GPU work costs nothing while idle; the serving path stays up |
| Argo Workflows | DAGs with per-docket and per-campaign fan-out, retries with backoff, step-level artifacts, and a `budget` parameter each agent step must honour | One workflow run is one auditable record of what every agent did and spent |
| KEDA on Pub/Sub | Worker deployments that scale with queue depth, for the per-comment jobs (claim extraction, embedding) | Thousands of small jobs without a thousand pods defined by hand |
| `agent-runner` container | Takes a task spec (role, tools, model, token budget, output schema) and runs a tool-calling loop. A subagent is a child Argo step running the same image with a narrower spec | Every subagent is a pod with its own logs, trace, cost and retry, visible in Argo and W&B |
| Stores | Postgres for campaigns, claims, dossiers and audit rows; Chroma (or Qdrant on the cluster) for letters and rule passages; GCS with DVC for raw data; W&B for training runs and LLM traces | The agents read and write typed rows, so the dashboard and the evaluation read the same thing |
| Verifier step | Every agent output is schema-checked, and every factual claim carries a citation (record ID, attachment page, or URL) that a separate verifier agent re-opens and confirms before the row is written | This is how "shows the evidence" survives the move to agents |

Guardrails carried into every workflow: agents only ever see hashed signer names; agents reason
about campaigns, files and templates, never about a named person; and anything the verifier
cannot confirm is stored as "unverified" and shown that way.
