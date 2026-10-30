"""Score a passage against every section of its rule with a sentence encoder.

A section's score is its best window's cosine with the passage, as in the linking test, so an untuned
bge-small here reproduces that test's "bge-small" row.
"""

from __future__ import annotations

import numpy as np

from linker.data import Rule, query_text


class SectionScorer:
    def __init__(self, model, batch_size: int = 64):
        self.model = model
        self.batch_size = batch_size
        self._windows: dict[str, np.ndarray] = {}

    def window_vectors(self, rule: Rule) -> np.ndarray:
        if rule.docket not in self._windows:
            self._windows[rule.docket] = self.model.encode(
                [w.text for w in rule.windows], batch_size=self.batch_size,
                normalize_embeddings=True, convert_to_numpy=True,
            )
        return self._windows[rule.docket]

    def query_vectors(self, passages: list[dict]) -> np.ndarray:
        return self.model.encode(
            [query_text(p) for p in passages], batch_size=self.batch_size,
            normalize_embeddings=True, convert_to_numpy=True,
        )

    def window_scores(self, rule: Rule, passages: list[dict]) -> np.ndarray:
        """n_passages x n_windows cosine."""
        return self.query_vectors(passages) @ self.window_vectors(rule).T

    def section_scores(self, rule: Rule, passages: list[dict]) -> np.ndarray:
        """n_passages x n_sections: each section's best window."""
        return max_by_section(self.window_scores(rule, passages), rule)

    def forget(self) -> None:
        """Drop cached window vectors after the model's weights change."""
        self._windows.clear()


def max_by_section(window_scores: np.ndarray, rule: Rule) -> np.ndarray:
    ws = np.asarray(rule.window_section)
    out = np.full((window_scores.shape[0], len(rule.sections)), -np.inf, dtype=np.float32)
    for s in range(len(rule.sections)):
        out[:, s] = window_scores[:, ws == s].max(axis=1)
    return out


def rank_of(scores: np.ndarray, label: int) -> int:
    """1-based rank of the labelled column; ties go against the label."""
    return int((scores > scores[label]).sum() + (scores == scores[label]).sum())


def rank_sections(scorer: SectionScorer, rules: dict[str, Rule], passages: list[dict]) -> dict:
    """Per passage, in input order: the label's rank, the ranked section list and the scores."""
    by_docket: dict[str, list[int]] = {}
    for i, p in enumerate(passages):
        by_docket.setdefault(p["docket"], []).append(i)
    ranks = [0] * len(passages)
    top: list[list[str]] = [[] for _ in passages]
    scores: list[np.ndarray] = [np.empty(0)] * len(passages)
    for d, idx in by_docket.items():
        rule = rules[d]
        S = scorer.section_scores(rule, [passages[i] for i in idx])
        for row, i in zip(S, idx, strict=True):
            ranks[i] = rank_of(row, rule.sections.index(passages[i]["section"]))
            order = np.argsort(-row, kind="stable")
            top[i] = [rule.sections[j] for j in order[:10]]
            scores[i] = row
    return {"ranks": ranks, "top10": top, "scores": scores}
