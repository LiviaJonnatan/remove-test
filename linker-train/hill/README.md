# undersigned-linker

Link a passage from a public comment to the section of the proposed federal rule it argues about.

People comment on proposed rules; a few cite the section they mean ("§ 106.44"). Those citations are
the labels. Every citation, section number, paragraph id and heading reference is masked out of the
passage text (`[CITATION]`, `[NUM]`, `[PARA]`, `[PART]`, `[HEADING]`), so the section has to be read
from what the passage argues. Each rule has 11 to 39 sections.

## The task

Train a text encoder. The evaluator ranks every section of the passage's own rule by the cosine between
the passage and the section's best window, and checks whether the cited section comes first. That
ranking is fixed (`scoring.py`): it is what the project's API serves, so an encoder that wins here drops
into production with no code change. What you control is the encoder's weights and how you train them.

## Submission

A directory with `train.py` at its root. The evaluator runs it as

    python train.py --data <hill>/data --out <workdir>/model --time-limit-s <seconds>

from inside the submission directory, with the submission directory on `PYTHONPATH`, in this hill's
Python environment (numpy, pyyaml, sentence-transformers, torch). It is killed at `time_limit_s`.
Save the encoder to `--out` before then with `SentenceTransformer.save`. Only what is in `--out` when
the clock stops is scored.

The saved encoder must keep the served model's shape:
- 384 hidden size, 12 layers (the shape of `BAAI/bge-small-en-v1.5`, the starting point);
- modules exactly Transformer, Pooling, Normalize.

`max_seq_length` is set to 384 at scoring, and queries get the prefix in `scoring.QUERY_PREFIX`.

## Data (`data/`)

| Path | What |
|---|---|
| `train.json` | Labelled training passages. `masked` is what a model may read, `section` is the label, `comment` is the letter it came from (split by letter, never by passage). `raw` is the unmasked text, useful for nothing at scoring time. |
| `test.json`, `uncited.json` | Empty lists, so the project's loader (`linker.data.load`) works unchanged. |
| `rules/<docket>.json` | Each rule's regulatory text: `chunks` with `section`, `heading`, `text`. |
| `linking-extra/preamble/<docket>.json` | The agency's own discussion of each section, numbers masked, tagged with the section(s) it discusses. Ships with every proposed rule, needs no labels. |
| `linking-extra/letter_citations.json` | For each training passage, the sections its letter cites elsewhere. |

## Metric

`acc@1` on held-out passages: the share whose cited section the encoder ranks first. Ties count against
you. `acc@5`, then `mrr`, break ties. The held-out passages come from letters that are not in
`train.json`, and passages that largely repeat text from a training letter (form-letter copies) were
removed, so memorising letters does not help.

`--final` scores the project's frozen test set instead (490 passages, 145 letters), which the project
reports its numbers on. The served model gets 65.5% there.

## Rules

Fair: any training method, loss, sampling, curriculum, schedule, data from `data/` (including the
preamble and the letter citations), synthetic queries you generate locally from `data/`, starting from
any checkpoint of the required shape that is already cached on this machine.

Not fair, and pointless since the evaluator never reads them:
- reading anything outside the submission directory and `--data` (the project's other folders hold the
  held-out labels);
- calling a hosted model (API keys are removed from the environment);
- unmasking section numbers, or training on text that names the label.

## Hardware

Primary config is the device (`apple-mps`, `cpu`, or a GPU profile), the time limit, and the mode, so
scores only compare within the same hardware and budget. Run one eval at a time: two trainings at once
run out of memory on a 16 GB laptop.
