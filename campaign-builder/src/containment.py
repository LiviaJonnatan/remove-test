"""Group personalized form letters by how much of one letter's wording the other contains.

A campaign letter is a template plus whatever the sender adds. Two letters from one campaign share
most of the template, but each sender's own words enlarge the union of their phrases, so Jaccard
similarity stays low: a median of 0.24 and 0.37 between letters of the two campaigns in the MS2
sample. Containment, the shared phrases over the smaller letter's phrases, ignores what a sender
added: a median of 0.53 and 0.70 in the same campaigns, and at most 0.24 between unrelated letters.

A group's template, its core, is the set of phrases held by more than half of its members. For two
letters that is the phrases both have, so neither sender's own words count toward it. Letters are
taken in letter_id order, so a run does not depend on input order. A letter joins the group whose
core it contains the most of, if that containment is at least `threshold` and neither is more than
`max_length_ratio` times as long as the other. Otherwise it starts a group of its own. Comparing
with cores rather than with a group's first letter keeps a letter that holds two campaigns'
templates from pulling both into its group: once a second letter joins, the core is the template
they share. The length guard keeps a long letter that reprints a campaign's text, such as an
exhibit volume, out of that campaign.

A first pass like this splits a large campaign: before a clear template emerges, several early
letters start groups, and later letters scatter among them. On the full lead and copper docket one
campaign came out as several groups. So a second pass works on cores. Groups whose cores fit each
other are merged one pair at a time, the closest pair first, and the merged core is recomputed
before the next merge. Then each member is tested against the core of the other members, and any
that does not fit is dropped; this is what keeps two letters joined through a third that shares a
little with each. Ungrouped letters that fit a core join it, the letters still ungrouped get a
first pass of their own, and the pass repeats until nothing changes. So every grouped letter
contains at least `threshold` of the template the rest of its campaign shares, a property the tests
check.

A group is named after the member that holds the most of its core, so the letter the passage stage
reads in full is the one closest to the template.

In the first pass, candidate groups come from an index of their members' phrases. A phrase found in
more than `common_limit` groups is boilerplate and is not used to find candidates, which keeps large
dockets fast. Containment itself is always computed on the full sets.
"""

from __future__ import annotations

from collections import Counter

import pandas as pd

from exact_match import MIN_WORDS, normalize
from minhash_grouping import shingles

THRESHOLD = 0.5
SHINGLE_SIZE = 5
MAX_LENGTH_RATIO = 4.0
COMMON_LIMIT = 200
CANDIDATES_CHECKED = 25  # representatives sharing the most phrases, checked exactly


def containment(a: set[str], b: set[str]) -> float:
    """Shared phrases over the smaller set's phrases."""
    if not a or not b:
        return 0.0
    return len(a & b) / min(len(a), len(b))


def group_containment(
    letters: pd.DataFrame,
    threshold: float = THRESHOLD,
    shingle_size: int = SHINGLE_SIZE,
    min_words: int = MIN_WORDS,
    max_length_ratio: float = MAX_LENGTH_RATIO,
    common_limit: int = COMMON_LIMIT,
) -> pd.DataFrame:
    """One row per letter, in input order: letter_id, campaign_id, method, similarity.

    campaign_id is the letter_id of the member holding the most of the group's core, or null for a
    letter that matched nothing. similarity is the containment between a letter and the core of the
    other members of its group, null when ungrouped.
    Letters under `min_words` normalized words stay ungrouped. Call once per docket.
    """
    if not 0 < threshold <= 1:
        raise ValueError("threshold must be in (0, 1]")
    if shingle_size < 1 or min_words < 1 or max_length_ratio < 1 or common_limit < 1:
        raise ValueError("shingle_size, min_words, common_limit >= 1 and max_length_ratio >= 1")
    ids = letters["letter_id"]
    if ids.isna().any() or not ids.map(lambda x: isinstance(x, str)).all():
        raise ValueError("letter_id must contain non-null strings")
    if ids.duplicated().any():
        raise ValueError("letter_id must be unique")
    if "docket_id" in letters and letters["docket_id"].nunique(dropna=False) > 1:
        raise ValueError("group one docket at a time")

    ordered = letters.sort_values("letter_id")[["letter_id", "text"]]
    texts: dict[str, set[str]] = {}
    normalized: dict[str, str] = {}
    for letter_id, text in ordered.itertuples(index=False, name=None):
        normalized[letter_id] = normalize(text if isinstance(text, str) else "")
        texts[letter_id] = shingles(normalized[letter_id], shingle_size)
    eligible = sorted(i for i in texts if len(normalized[i].split()) >= min_words)

    groups = first_pass(eligible, texts, normalized, threshold, max_length_ratio, common_limit)
    groups = merge_by_template(
        groups, texts, normalized, set(eligible), threshold, max_length_ratio, common_limit
    )

    campaign_of: dict[str, tuple[str, float]] = {}
    for group in groups:
        core = core_of(group, texts)
        # Most of the core first, then the earliest letter_id.
        name = max(group, key=lambda m: (len(texts[m] & core), [-ord(c) for c in m]))
        for letter_id in group:
            others = core_without(group, letter_id, texts)
            campaign_of[letter_id] = (name, containment(texts[letter_id], others))
    rows = []
    for letter_id in ids:
        name, score = campaign_of.get(letter_id, (None, None))
        rows.append((letter_id, name, "containment", None if score is None else round(score, 4)))
    return pd.DataFrame(rows, columns=["letter_id", "campaign_id", "method", "similarity"])


def first_pass(
    letter_ids: list[str],
    texts: dict[str, set[str]],
    normalized: dict[str, str],
    threshold: float,
    max_length_ratio: float,
    common_limit: int,
) -> list[list[str]]:
    """Each letter, in letter_id order, joins the group whose core it fits best, or starts one.

    Returns the groups of two or more letters, each sorted.
    """
    members: list[list[str]] = []
    counts: list[Counter[str]] = []
    cores: list[set[str] | None] = []  # None when a member joined since it was computed
    index: dict[str, list[int]] = {}  # phrase -> groups whose members have it
    by_text: dict[str, int] = {}  # normalized text -> group, for exact copies

    def core(k: int) -> set[str]:
        if cores[k] is None:
            cores[k] = {p for p, n in counts[k].items() if 2 * n > len(members[k])}
        return cores[k]

    for letter_id in letter_ids:
        tokens = texts[letter_id]
        best = by_text.get(normalized[letter_id])  # an exact copy: no need to compare
        if best is None:
            shared: Counter[int] = Counter()
            for phrase in tokens:
                holders = index.get(phrase)
                if holders and len(holders) <= common_limit:
                    shared.update(holders)
            best_score = 0.0
            # Most shared phrases first, then the earliest group, so ties resolve the same way.
            candidates = sorted(shared.items(), key=lambda kv: (-kv[1], kv[0]))[:CANDIDATES_CHECKED]
            for k, _ in candidates:
                if fits(tokens, core(k), threshold, max_length_ratio):
                    score = containment(tokens, core(k))
                    if score > best_score:
                        best, best_score = k, score
        if best is None:
            best = len(members)
            members.append([])
            counts.append(Counter())
            cores.append(None)
            by_text[normalized[letter_id]] = best
        members[best].append(letter_id)
        for phrase in tokens - counts[best].keys():
            index.setdefault(phrase, []).append(best)
        counts[best].update(tokens)
        cores[best] = None
    return [sorted(m) for m in members if len(m) > 1]


def core_of(group: list[str], texts: dict[str, set[str]]) -> set[str]:
    """The phrases more than half of a group's letters have: its template. For a pair, the phrases
    both have; for one letter, its own."""
    counts = Counter(phrase for letter_id in group for phrase in texts[letter_id])
    return {phrase for phrase, n in counts.items() if 2 * n > len(group)}


def core_without(group: list[str], letter_id: str, texts: dict[str, set[str]]) -> set[str]:
    """The core of the group's other members, which the letter must fit without its own help."""
    return core_of([m for m in group if m != letter_id], texts)


def fits(a: set[str], b: set[str], threshold: float, max_length_ratio: float) -> bool:
    small, large = sorted((len(a), len(b)))
    return small > 0 and large <= max_length_ratio * small and containment(a, b) >= threshold


def merge_by_template(
    groups: list[list[str]],
    texts: dict[str, set[str]],
    normalized: dict[str, str],
    eligible: set[str],
    threshold: float,
    max_length_ratio: float,
    common_limit: int,
    rounds: int = 5,
) -> list[list[str]]:
    """Merge groups that share a template, drop members that do not fit the others, add ungrouped
    letters that fit a template, and regroup the letters still left over.

    Groups merge one pair at a time, the closest pair first, and the merged group's core is
    recomputed before the next merge, so a merge must fit the template as it now stands. A union of
    everything connected at once let small groups chain into an unrelated campaign through groups in
    between. Returns the groups, each sorted, ordered by their earliest letter_id.
    """
    groups = sorted((sorted(g) for g in groups), key=lambda g: g[0])
    for _ in range(rounds):
        before = groups
        groups = prune(
            agglomerate(groups, texts, threshold, max_length_ratio),
            texts,
            threshold,
            max_length_ratio,
        )
        cores = [core_of(g, texts) for g in groups]
        grouped = {letter_id for g in groups for letter_id in g}
        for letter_id in sorted(eligible - grouped):
            best, best_score = None, 0.0
            for k, core in enumerate(cores):
                if fits(texts[letter_id], core, threshold, max_length_ratio):
                    score = containment(texts[letter_id], core)
                    if score > best_score:
                        best, best_score = k, score
            if best is not None:
                groups[best] = sorted(groups[best] + [letter_id])
        groups = prune(groups, texts, threshold, max_length_ratio)
        # Letters dropped above, or never grouped, may still form a campaign among themselves.
        grouped = {letter_id for g in groups for letter_id in g}
        left = sorted(eligible - grouped)
        groups += first_pass(left, texts, normalized, threshold, max_length_ratio, common_limit)
        groups = sorted(groups, key=lambda g: g[0])
        if groups == before:
            break
    return groups


def agglomerate(
    groups: list[list[str]], texts: dict[str, set[str]], threshold: float, max_length_ratio: float
) -> list[list[str]]:
    """Merge the closest pair of groups whose cores fit each other, until no pair does."""
    groups = [list(g) for g in groups]
    cores = [core_of(g, texts) for g in groups]
    while True:
        best, best_key = None, None
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                if fits(cores[i], cores[j], threshold, max_length_ratio):
                    key = (containment(cores[i], cores[j]), [-ord(c) for c in groups[i][0]])
                    if best_key is None or key > best_key:
                        best, best_key = (i, j), key
        if best is None:
            return groups
        i, j = best
        groups[i] = sorted(groups[i] + groups[j])
        cores[i] = core_of(groups[i], texts)
        del groups[j], cores[j]


def prune(
    groups: list[list[str]], texts: dict[str, set[str]], threshold: float, max_length_ratio: float
) -> list[list[str]]:
    """Drop members that do not fit the core of the other members; a group left with one letter
    dissolves. Testing a member against a core that includes its own phrases would let a pair, or a
    letter joined through one other member, always pass."""
    out = []
    for group in groups:
        while len(group) >= 2:
            kept = [
                m
                for m in group
                if fits(texts[m], core_without(group, m, texts), threshold, max_length_ratio)
            ]
            if len(kept) == len(group):
                break
            group = kept
        if len(group) >= 2:
            out.append(sorted(group))
    return out
