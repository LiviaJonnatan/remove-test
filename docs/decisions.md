# Decisions

Why each part is built the way it is, and what we picked it over. One row per choice. Whoever makes a new
choice adds a row in the same PR, so anyone on the team can answer "why X and not Y" about any part.

## Data

| Choice | Over | Why | Where |
|---|---|---|---|
| Regulations.gov API with a data.gov key | Scraping the website | The API returns each comment's text, metadata and attachment links as JSON. One free key allows 1,000 requests an hour, and several keys rotate | `data-collector/` |
| A fixed 40-record demo sample | The first N records of a docket | The first records are early individual comments, so a 50-record sample had nothing to group or link. The 40 ids hold two personalized campaigns, ten organization letters that cite the rule and ten individuals | `data-collector/samples/` |
| Read the PDF's text layer, OCR (Tesseract) only as a fallback | OCR every page, or a vision model | Most PDFs carry text, and reading it is exact and fast. A page is OCRed only when it has no usable text and holds an image. OCR runs inside the container, so letters are never sent to an outside service | `data-processor/src/extract.py` |
| Signer names hashed with HMAC-SHA256 and a secret key | Storing names, or a plain hash | We never need a name, only whether two letters share a signer. A plain hash of a name can be reversed by hashing a list of names; a keyed one cannot without the key | `data-processor/src/records.py` |
| DVC with a Google Cloud Storage bucket | Git LFS, or files on a shared drive | The data is too big for Git. Git keeps a small pointer per dataset, the bucket keeps every version, and `dvc pull` restores the exact version a commit names | `data/raw/*.dvc` |

## Grouping form letters

| Choice | Over | Why | Where |
|---|---|---|---|
| Group copies before reading | Reading every letter | A campaign can send thousands of near-identical letters. Reading the shared text once and each sender's own words once saves the model calls | `campaign-builder/`, `passage-stage/` |
| Containment of five-word phrases (#74) | MinHash or Jaccard similarity | Personalized letters add the sender's own words around a template. Jaccard divides by the size of both letters, so the added words keep it low. Containment asks whether a letter holds the template | `campaign-builder/src/containment.py` |
| B-cubed F1 to score grouping | Pairwise accuracy | It scores each letter by how well its group matches its true campaign. Large campaigns can't dominate the score the way they do in pair counts | `campaign-builder/src/bcubed.py` |

## Retrieval (the RAG part)

| Choice | Over | Why | Where |
|---|---|---|---|
| Chunk the rule by section, about 200 words, with a sentence of overlap | Fixed-size chunks | A chunk never crosses a section, so it is about one topic and carries its `section_ref`. A link can then name a section. The overlap keeps a sentence that runs across two chunks findable | `rule-passages/src/rule_passages/chunking.py` |
| Keyword (BM25) and embedding search, fused by rank | One of them | Rules use exact legal terms ("corrosion control treatment"), where keywords win. Embeddings catch a commenter's paraphrase. The two scores are on different scales, so they are combined by rank (reciprocal rank fusion), not by score | `rule_passages/retrieve.py` |
| `bge-small-en-v1.5` through ONNX | A larger embedding model, or an embedding API | Small enough to run on a CPU in the container, with no PyTorch in the image and no per-call cost. The model is baked into the image at build | `rule-passages/`, `api-service/` |
| ChromaDB in its own container | FAISS, pgvector, Vertex AI Vector Search | Runs locally with no account, persists to a mounted folder, and filters on metadata (docket, procedural sections). A few thousand rule passages need nothing bigger | `docker-compose.yml` |
| Leave procedural sections out of retrieval | Search everything | Letters quote "how to submit comments" and the docket ID without arguing about them, so those sections won searches they should not | `chunking.py` (`is_procedural`) |

## Linking and models

| Choice | Over | Why | Where |
|---|---|---|---|
| Commenters' own citations as the answer key | Hand-labeling every passage | When a letter cites "§ 141.84", it tells us the right section. The citation is masked before scoring, so retrieval has to find the section from the argument alone | `passage-stage/` (`text_masked`) |
| Two people label the same 30 passages blind | Trusting one labeler | They agreed on 21 of 30. That sets a ceiling: a model scored against one reader cannot meaningfully beat how often two readers agree | `docs/hand-check/` (#71) |
| Models run in batch, once per docket | Calling a model on every page load | The API only reads stored results, so a request costs nothing and returns in about 0.1 s. Model cost is paid once per docket | `api-service/` |
| A small model first, the large one only when unsure (MS3) | The large model on everything | On 232 passages it kept about 94% of the large model's accuracy at about a quarter of the cost. The cutoff still has to be set on held-out data | README, Targets |
| One model call per passage | A multi-agent setup | Five role-playing agents did no better than one call and cost 4.7 times as much | README, Changes since Milestone 1 |
| Bootstrap intervals over organizations | Over passages | Passages from one letter are not independent. Resampling passages would make the intervals too narrow | README, How uncertainty is reported |

## Infrastructure

| Choice | Over | Why | Where |
|---|---|---|---|
| uv with a `pyproject.toml` and `uv.lock` per container | conda, or pip with requirements.txt | The lockfile pins every version, so each build installs the same thing. uv is much faster, needs no base environment, and is what the course template uses | each container |
| One container per stage | One big container | Each stage has its own dependencies (Tesseract, ONNX, React). A failure points at one stage, and one stage can be rerun alone | `docker-compose.yml` |
| Docker Compose with `depends_on: service_completed_successfully` | A shell script, or Kubernetes now | One command runs the stages in order, and a failed stage stops everything after it. One machine is enough for the sample. Kubernetes comes in MS5, for scaling the serving side | `docker-compose.yml` |
| Bind-mount `data/` and each stage's `src/` | Copying data and code into the image | Stages share data through `data/`, and a code edit takes effect without a rebuild. ChromaDB persists to `docker-volumes/chromadb`. The API mounts the passage files read-only | `docker-compose.yml` |
| Secrets in a gitignored `.env` and a `secrets/` folder outside the repository, given to containers at start | Baking keys into images, or committing them | An image or a commit with a key leaks it to anyone who can see it. `env_file: .env` passes the data.gov key; `../secrets`, next to the repository as in the course template, is mounted at `/secrets` for the service-account key. On a GCP VM the attached service account needs no key file | `docker-compose.yml`, `docs/setup.md` |
| The API imports rule-passages' code through a second build context | Copying the retrieval code | Retrieval and the API can't drift apart: there is one copy of the code | `docker-compose.yml` (`additional_contexts`) |
| FastAPI | Flask | Request validation from type hints (a bad request gets a 422 naming the field) and interactive docs at `/docs` | `api-service/` |
| React page behind nginx, which forwards `/api` to the API | The browser calling the API directly | One origin, so the API needs no CORS. nginx looks the API up per request, so the page loads even while the API is starting | `frontend/nginx.conf` |

## Argument graph (MS3, `argument-graph/`)

| Choice | Over | Why | Where |
|---|---|---|---|
| Two model steps, extract and judge | A third agent that flags significance | Significance is a rule on the extractor's `evidence_type`: new data, a legal argument or a concrete alternative is what that field encodes. A model that re-reads the claim to say the same thing adds cost and a second place to be wrong | `argument-graph/src/issues.py` |
| Every claim in a passage, no word caps | The 12 Oct one-ask-per-passage prompt with 18-word asks | 134 of 896 LCRI passages carry more than one ask, and 7 of the 8 unfaithful judge verdicts on 12 Oct were dropped second asks. The shortening passes cost $0.533 for cosmetics | `argument-graph/prompts/extract.md` |
| Embeddings propose pairs, the model judges them | One merge call per section (12 Oct) | The section-wide merge left 405 of 507 positions as singletons and 63% of its merges clean. Pairs give the model two claims at a time, and a cosine floor keeps the pair count bounded. B1 (cosine clustering alone) is the baseline it has to beat | `argument-graph/src/pairs.py`, `eval/baselines.py` |
| Issue label is a member's own ask | A model-written label | Cosmetic, and a paraphrase is one more thing to audit. The analyst reads a real commenter's sentence beside its quote. `GRAPH_LABEL_ISSUES=1` turns the label call on | `argument-graph/src/issues.py` |
| Issues per section, no cross-section merge | A second merge pass over sections | Cut for MS3 and recorded as a limitation: the same ask about § 141.84 and § 141.86 appears twice | `argument-graph/README.md` |
| Collision detection cut | The 12 Oct collide step | 16 of 60 "direct conflicts" were real on the Opus check. `same_issue_opposite_side` in the pair judge keeps the useful part | `argument-graph/prompts/judge.md` |
| Linker as a cross-check only | Linking uncited passages into the graph | 65.5% top-1 would put a third of uncited claims under the wrong section. Citations are the label; the linker's top 5 flags disagreements for review | `argument-graph/src/crosscheck.py` |
| Agency response nodes only in the eval | In the graph the analyst sees | The final rule does not exist when the response is being written | `argument-graph/eval/match.py` |
| Deterministic quote check with one re-ask, never a script-side cut | Trusting the model's quote, or truncating long ones | The response writer cites the quote. On 12 Oct the string check passed 99.6% first try and 100% after one re-ask; the 15 quotes the script cut to 30 words could orphan a clause | `argument-graph/src/quotes.py` |
| Count by distinct letters and by letters including copies, both shown | One count | A form letter sent 5,000 times is one argument and 5,000 signatures; the writer needs both numbers | `argument-graph/src/issues.py` |
| Two backends behind one `call()`: `claude -p` and the SDK | The SDK only | Pilots run on the laptop's Claude Code login with no key; the container needs a key. Same ledger row either way | `argument-graph/src/backends.py` |
