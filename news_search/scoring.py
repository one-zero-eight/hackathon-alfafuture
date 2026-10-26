"""Freshness, normalisation and the selection formulas shared by the search methods."""

import collections
import datetime
from email.utils import parsedate_to_datetime

import numpy as np

TOP_OUT, RRF_K, N_PAIRS = 30, 10, 20


def age_days(date, now):
    """Age of an RFC 2822 date in days; an unknown date counts as 60 days."""
    try:
        t = parsedate_to_datetime(date)
        return (now - (t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc))).days
    except Exception:
        return 60


def fresh(days):
    """Stale news is demoted, not dropped."""
    return 1.0 if days <= 30 else 0.85 if days <= 90 else 0.6 if days <= 365 else 0.3


def mean_top3(S):
    k = min(3, S.shape[1])
    return np.sort(np.partition(S, -k, axis=1)[:, -k:], axis=1).mean(1)


def norm01(x):
    x = np.asarray(x, dtype=np.float64)
    return (x - x.min()) / (x.max() - x.min() + 1e-9)


def zscore_top3(X, queries_vectors):
    """Similarity of every article to every query, z-normalised per query, then the mean of each article's 3 best queries."""
    S = X @ queries_vectors.T
    return mean_top3((S - S.mean(0)) / (S.std(0) + 1e-6))


def xquad(items, lam=0.5, k=TOP_OUT, bonus=None):
    """Greedy diversification over the query blocks (equal weights): relevance vs covering blocks not covered yet.
    bonus: a constant extra gain per item (does not fade like block coverage), e.g. for news outside the profile's region."""
    rel = norm01([it["score"] for it in items])
    P = np.clip(np.array([it["aspects"] for it in items]), 0, None)
    bonus = np.zeros(len(items)) if bonus is None else np.asarray(bonus, dtype=float)
    uncovered, chosen = np.ones(P.shape[1]) / P.shape[1], []
    for _ in range(min(k, len(items))):
        best = max(
            (i for i in range(len(items)) if i not in chosen),
            key=lambda i: (
                (1 - lam) * rel[i] + lam * float(uncovered @ P[i]) + lam * bonus[i]
            ),
        )
        chosen.append(best)
        uncovered = uncovered * (1 - P[best])
    return chosen


def pairs(items, k=N_PAIRS):
    """Related-but-not-duplicate pairs (cosine 0.6-0.8), ranked by a relevance pre-score (weights fitted offline, tag features omitted)."""
    V = np.stack([it["vec"] for it in items])
    S = V @ V.T
    rel = norm01([it["score"] for it in items])
    scored = []
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if 0.6 <= S[i, j] < 0.8:
                scored.append(
                    (
                        0.5 * min(rel[i], rel[j])
                        + 0.3 * max(rel[i], rel[j])
                        + 0.8 * float(np.exp(-(((S[i, j] - 0.7) / 0.1) ** 2))),
                        i,
                        j,
                    )
                )
    return [[i, j] for _, i, j in sorted(scored, reverse=True)[:k]]


def fuse(lists, items, now):
    """Reciprocal-rank fusion of ranked id lists, a bonus for confirmation by several outlets and methods, times freshness."""
    score = collections.defaultdict(float)
    for ranked in lists:
        for rank, i in enumerate(ranked, 1):
            score[i] += 1 / (RRF_K + rank)
    for i in score:
        it = items[i]
        bonus = 0.01 * min(len(it["outlets"]) - 1, 3) + (
            0.03 if len(it["methods"]) > 1 else 0
        )
        score[i] = (score[i] + bonus) * fresh(age_days(it["date"], now))
    return sorted(score, key=lambda i: -score[i])[:TOP_OUT], score
