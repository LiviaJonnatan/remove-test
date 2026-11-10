"""The untuned starting point: save bge-small as it is. Scores what the project served before MS3."""

import argparse

from sentence_transformers import SentenceTransformer

ap = argparse.ArgumentParser()
ap.add_argument("--data")
ap.add_argument("--out", required=True)
ap.add_argument("--time-limit-s", type=int)
args = ap.parse_args()
SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu").save(args.out)
