"""Shared helpers: tokenizing, matching feed items to queries, dedup (hybrid = union of cheap signals)."""
import hashlib, math, re
from collections import Counter, defaultdict
from urllib.parse import urlparse, parse_qsl, urlencode

STOP = set("и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец два об другой хоть после над больше тот через эти нас про всего них какая много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно всю между новости новость россии россия рф".split())


def toks(text, k=5):
    """lowercase words, stopwords out, crude stem = first k chars (Russian morphology without deps)"""
    return [w[:k] for w in re.findall(r"[a-zа-яё0-9]+", text.lower().replace("ё", "е")) if w not in STOP and len(w) > 1]


def norm_title(t):
    return " ".join(re.findall(r"[a-zа-яё0-9]+", t.lower().replace("ё", "е")))


# ---------- query matching for feed items (method B) ----------
def match_items(items, queries, min_frac=0.6, min_hits=2, per_query=8):
    """items: [{title, summary, ...}]; returns {query: [(score, item_idx)]}"""
    qt = {q: set(toks(q)) for q in queries}
    it = [set(toks(i["title"] + " " + (i.get("summary") or ""))) for i in items]
    inv = defaultdict(list)
    for j, s in enumerate(it):
        for w in s:
            inv[w].append(j)
    out = {}
    for q, ts in qt.items():
        if not ts:
            continue
        hit = Counter()
        for w in ts:
            for j in inv.get(w, ()):
                hit[j] += 1
        need = max(min_hits if len(ts) >= 2 else 1, math.ceil(min_frac * len(ts)))
        c = [(h / len(ts), j) for j, h in hit.items() if h >= need]
        c.sort(reverse=True)
        if c:
            out[q] = c[:per_query]
    return out


# ---------- dedup (hybrid = union of cheap signals): each returns cluster id per item ----------
def canon_url(u):
    p = urlparse(u)
    q = [(k, v) for k, v in parse_qsl(p.query) if not k.startswith(("utm_", "from", "ref", "yclid", "fbclid"))]
    return f"{p.netloc.lower().removeprefix('www.')}{p.path.rstrip('/')}?{urlencode(q)}"


class UF:
    def __init__(self, n): self.p = list(range(n))
    def f(self, x):
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def u(self, a, b): self.p[self.f(a)] = self.f(b)


def _labels(uf, n): return [uf.f(i) for i in range(n)]


def dd_url(items):
    seen, lab = {}, []
    for i, it in enumerate(items):
        lab.append(seen.setdefault(canon_url(it["link"]), i))
    return lab


def dd_title_exact(items):
    seen, lab = {}, []
    for i, it in enumerate(items):
        lab.append(seen.setdefault(norm_title(it["title"]), i))
    return lab


def _pairs_by_tokens(sets):
    """candidate pairs sharing at least one rare-ish token (blocking to avoid n^2)"""
    inv = defaultdict(list)
    for i, s in enumerate(sets):
        for w in s:
            inv[w].append(i)
    seen = set()
    for w, ids in inv.items():
        if len(ids) > 60:  # skip very common tokens
            continue
        for a in range(len(ids)):
            for b in range(a + 1, len(ids)):
                seen.add((ids[a], ids[b]))
    return seen


def dd_jaccard(items, thr=0.6):
    sets = [set(toks(i["title"])) for i in items]
    uf = UF(len(items))
    for a, b in _pairs_by_tokens(sets):
        if sets[a] and sets[b] and len(sets[a] & sets[b]) / len(sets[a] | sets[b]) >= thr:
            uf.u(a, b)
    return _labels(uf, len(items))


def _tfidf_vecs(docs):
    grams = []
    for d in docs:
        s = " " + norm_title(d) + " "
        grams.append(Counter(s[i:i + 4] for i in range(len(s) - 3)))
    df = Counter(g for c in grams for g in c)
    n = len(docs)
    vecs = []
    for c in grams:
        v = {g: (1 + math.log(tf)) * math.log((n + 1) / (df[g] + 1)) for g, tf in c.items()}
        norm = math.sqrt(sum(x * x for x in v.values())) or 1
        vecs.append({g: x / norm for g, x in v.items()})
    return vecs


def dd_tfidf(items, thr=0.55):
    vecs = _tfidf_vecs([i["title"] for i in items])
    sets = [set(toks(i["title"])) for i in items]
    uf = UF(len(items))
    for a, b in _pairs_by_tokens(sets):
        va, vb = vecs[a], vecs[b]
        if len(va) > len(vb): va, vb = vb, va
        if sum(x * vb.get(g, 0) for g, x in va.items()) >= thr:
            uf.u(a, b)
    return _labels(uf, len(items))


def dd_hybrid(items):
    """url-canonical OR title-exact OR jaccard>=0.6 OR tfidf>=0.55 (union of cheap signals)"""
    n = len(items)
    uf = UF(n)
    for lab in (dd_url(items), dd_title_exact(items), dd_jaccard(items), dd_tfidf(items)):
        for i, l in enumerate(lab):
            uf.u(i, l)
    return _labels(uf, n)
