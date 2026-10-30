"""BM25 keyword retrieval, the baseline every embedding result is compared against.

Okapi BM25 with the non-negative idf used by Lucene. Text is lowercased, stripped of common
English words, and reduced to a crude singular form so that "wetlands" matches "wetland".
"""

from __future__ import annotations

import heapq
import math
import re
from collections import Counter

TOKEN = re.compile(r"[a-z0-9]+(?:'[a-z]+)?")
STOPWORDS = frozenset(
    """a about above after again all also an and any are as at be because been before being
    below between both but by can could did do does doing down during each few for from further
    had has have having he her here hers him his how i if in into is it its itself just me more
    most my no nor not of off on once only or other our out over own same she should so some such
    than that the their them then there these they this those through to too under until up very
    was we were what when where which while who whom why will with would you your""".split()
)


def stem(word: str) -> str:
    """Strip a plural ending: ponds to pond, ditches to ditch, but not glass or ties to ty."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 4 and word.endswith(("ches", "shes", "sses", "xes", "zes")):
        return word[:-2]
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokenize(text: str) -> list[str]:
    return [stem(t) for t in TOKEN.findall(text.lower()) if t not in STOPWORDS]


class BM25Index:
    def __init__(self, documents: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.lengths: list[int] = []
        self.postings: dict[str, list[tuple[int, int]]] = {}
        for doc_id, text in enumerate(documents):
            tokens = tokenize(text)
            self.lengths.append(len(tokens))
            for term, tf in Counter(tokens).items():
                self.postings.setdefault(term, []).append((doc_id, tf))
        self.avg_length = sum(self.lengths) / len(self.lengths) if self.lengths else 0.0

    def idf(self, term: str) -> float:
        n = len(self.postings.get(term, ()))
        return math.log(1 + (len(self.lengths) - n + 0.5) / (n + 0.5))

    def search(self, query: str, k: int) -> list[tuple[int, float]]:
        """The k best (document index, score) pairs. Each distinct query term counts once."""
        scores: dict[int, float] = {}
        for term in set(tokenize(query)):
            idf = self.idf(term)
            for doc_id, tf in self.postings.get(term, ()):
                norm = 1 - self.b + self.b * self.lengths[doc_id] / self.avg_length
                scores[doc_id] = scores.get(doc_id, 0.0) + idf * tf * (self.k1 + 1) / (
                    tf + self.k1 * norm
                )
        return heapq.nsmallest(k, scores.items(), key=lambda item: (-item[1], item[0]))
