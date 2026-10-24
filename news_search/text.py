"""Tokenizing and lexical matching of news titles against search queries (no dependencies, crude Russian stemming)."""
import math
import re
from collections import Counter, defaultdict

STOP = set("и в во не что он на я с со как а то все она так его но да ты к у же вы за бы по только ее мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей может они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже себе под будет ж тогда кто этот того потому этого какой совсем ним здесь этом один почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец два об другой хоть после над больше тот через эти нас про всего них какая много разве три эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой им более всегда конечно всю между новости новость россии россия рф".split())


def toks(text, k=5):
    """Lowercase words without stopwords, stemmed to their first k letters (Russian morphology without dependencies)."""
    words = re.findall(r"[a-zа-яё0-9]+", text.lower().replace("ё", "е"))
    return [w[:k] for w in words if w not in STOP and len(w) > 1]


def norm_title(title):
    return " ".join(re.findall(r"[a-zа-яё0-9]+", title.lower().replace("ё", "е")))


def match_items(items, queries, min_frac=0.6, min_hits=2, per_query=8):
    """items: [{title, summary?}] -> {query: [(share of query stems found, item index)]}, best per_query matches per query."""
    query_stems = {q: set(toks(q)) for q in queries}
    item_stems = [set(toks(i["title"] + " " + (i.get("summary") or ""))) for i in items]
    index = defaultdict(list)
    for j, stems in enumerate(item_stems):
        for stem in stems:
            index[stem].append(j)
    matches = {}
    for query, stems in query_stems.items():
        if not stems:
            continue
        hits = Counter()
        for stem in stems:
            for j in index.get(stem, ()):
                hits[j] += 1
        need = max(min_hits if len(stems) >= 2 else 1, math.ceil(min_frac * len(stems)))
        found = sorted(((h / len(stems), j) for j, h in hits.items() if h >= need), reverse=True)
        if found:
            matches[query] = found[:per_query]
    return matches
