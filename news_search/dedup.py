"""Duplicate detection for news titles: the union of cheap signals (canonical URL, exact title, Jaccard, char 4-gram TF-IDF).

Each dd_* function returns a cluster label per item; dd_hybrid merges all of them.
"""
import math
from collections import Counter, defaultdict
from urllib.parse import parse_qsl, urlencode, urlparse

from news_search.text import norm_title, toks

TRACKING = ("utm_", "from", "ref", "yclid", "fbclid")


def canon_url(url):
    parts = urlparse(url)
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.startswith(TRACKING)]
    return f"{parts.netloc.lower().removeprefix('www.')}{parts.path.rstrip('/')}?{urlencode(query)}"


class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        self.parent[self.find(a)] = self.find(b)

    def labels(self):
        return [self.find(i) for i in range(len(self.parent))]


def dd_url(items):
    first, labels = {}, []
    for i, item in enumerate(items):
        labels.append(first.setdefault(canon_url(item["link"]), i))
    return labels


def dd_title_exact(items):
    first, labels = {}, []
    for i, item in enumerate(items):
        labels.append(first.setdefault(norm_title(item["title"]), i))
    return labels


def _candidate_pairs(token_sets, skip_above=60):
    """Pairs of items sharing a token (blocking, to avoid n^2); tokens used by too many items are skipped."""
    index = defaultdict(list)
    for i, tokens in enumerate(token_sets):
        for token in tokens:
            index[token].append(i)
    pairs = set()
    for ids in index.values():
        if len(ids) > skip_above:
            continue
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                pairs.add((ids[a], ids[b]))
    return pairs


def dd_jaccard(items, threshold=0.6):
    sets = [set(toks(i["title"])) for i in items]
    uf = UnionFind(len(items))
    for a, b in _candidate_pairs(sets):
        if sets[a] and sets[b] and len(sets[a] & sets[b]) / len(sets[a] | sets[b]) >= threshold:
            uf.union(a, b)
    return uf.labels()


def _tfidf_vectors(titles):
    grams = []
    for title in titles:
        s = " " + norm_title(title) + " "
        grams.append(Counter(s[i:i + 4] for i in range(len(s) - 3)))
    df = Counter(g for c in grams for g in c)
    n = len(titles)
    vectors = []
    for counts in grams:
        v = {g: (1 + math.log(tf)) * math.log((n + 1) / (df[g] + 1)) for g, tf in counts.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        vectors.append({g: x / norm for g, x in v.items()})
    return vectors


def dd_tfidf(items, threshold=0.55):
    vectors = _tfidf_vectors([i["title"] for i in items])
    sets = [set(toks(i["title"])) for i in items]
    uf = UnionFind(len(items))
    for a, b in _candidate_pairs(sets):
        small, large = sorted((vectors[a], vectors[b]), key=len)
        if sum(x * large.get(g, 0) for g, x in small.items()) >= threshold:
            uf.union(a, b)
    return uf.labels()


def dd_hybrid(items):
    """Same canonical URL OR same title OR Jaccard >= 0.6 OR TF-IDF cosine >= 0.55."""
    uf = UnionFind(len(items))
    for labels in (dd_url(items), dd_title_exact(items), dd_jaccard(items), dd_tfidf(items)):
        for i, label in enumerate(labels):
            uf.union(i, label)
    return uf.labels()
