"""Lexical search over the news of one page and the bank theses: idf-weighted overlap of crude 5-letter stems."""

import math
import re
from collections import Counter

STOP = set(
    "и в во не что на с со как а то все так его но да к у же за бы по только ее было от еще нет о из ему "
    "когда даже ли если уже или ни быть был до вас вам там потом себя ей может они тут где есть для мы их чем "
    "была сам без будет тогда кто этот того потому этого какой при после над больше через эти нас про всего "
    "них много года году млн млрд руб рублей также".split()
)


def stems(text: str) -> list[str]:
    return [
        w[:5]
        for w in re.findall(r"[a-zа-я0-9]+", text.lower().replace("ё", "е"))
        if w not in STOP and len(w) > 2
    ]


class Index:
    def __init__(self, docs: dict[str, str]):
        self.docs = {k: Counter(stems(v)) for k, v in docs.items()}
        df = Counter(s for c in self.docs.values() for s in c)
        self.idf = {
            s: math.log((len(self.docs) + 1) / (n + 0.5)) for s, n in df.items()
        }

    def search(
        self, query: str, k: int = 5, exclude: set[str] = frozenset(), prefix: str = ""
    ) -> list[str]:
        q = set(stems(query))
        scored = []
        for key, c in self.docs.items():
            if key in exclude or not key.startswith(prefix):
                continue
            s = sum(self.idf[w] for w in q if w in c) / math.sqrt(sum(c.values()) + 5)
            if s > 0:
                scored.append((s, key))
        return [key for _, key in sorted(scored, reverse=True)[:k]]
