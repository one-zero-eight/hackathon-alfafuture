"""Region of a news item without an LLM: the region of its outlet and the regions, region capitals and cities named in its text.

regions.json is built by regions_build.py from the collector's vocabulary (82 regions of Russia and their aliases), the collector's
sources.json (the region of each regional outlet) and the bank company data (city -> region). Rebuild it when those files change.
"""
import json
import os
import re

GENERIC = {"область", "край", "республика", "автономный", "автономная", "округ", "город", "г", "аобл"}
DEFAULT_PATH = os.path.join(os.path.dirname(__file__), "regions.json")


def words(text):
    return re.findall(r"[a-zа-я0-9]+", text.lower().replace("ё", "е"))


def capitalized(text):
    """Lowercased words written with a capital letter inside a sentence (a sentence-initial capital says nothing:
    «Выборы прошли» is not Выборг). shortcut: a city named first in a sentence counts only through its outlet; fine for titles
    like «В Казани…», misses «Казань получит…»; upgrade with a list of cities that are also common words if recall matters."""
    return {w.lower().replace("ё", "е") for w in re.findall(r"(?<![.!?«\"]\s)(?<!^)(?<=\s)[A-ZА-ЯЁ][a-zа-яё0-9]*", text)}


def stem(word):
    """Crude Russian stem: drop the ending letters a case form can change (Казань -> казан, Новосибирск -> новосибир)."""
    if len(word) <= 4:
        return word
    return word[:-1] if len(word) <= 6 else word[:-2]


class RegionIndex:
    def __init__(self, path=DEFAULT_PATH):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        self.outlets = data["outlets"]  # source id -> region label
        # (stems of one name, region label, capital letter needed); a multi-word name needs all its stems. Region names match in
        # any case («воронежской области», «курским»); city names only capitalized: many are common words (Выборг/выбор, Чита/читать)
        self.names = []
        for key, capital in (("regions", False), ("cities", True)):
            for label, names in data[key].items():
                for name in names:
                    stems = tuple(stem(w) for w in words(name) if w not in GENERIC and len(w) > 2)
                    if stems:
                        self.names.append((stems, label, capital))
        self.prefixes = {s for stems, _, _ in self.names for s in stems}
        self._cache = {}

    def find(self, text):
        """Region labels named in the text."""
        found, upper = set(), set()
        caps = capitalized(text)
        for w in words(text):
            for k in range(3, len(w) + 1):
                if w[:k] in self.prefixes:
                    found.add(w[:k])
                    if w in caps:
                        upper.add(w[:k])
        return {label for stems, label, capital in self.names if all(s in (upper if capital else found) for s in stems)}

    def of(self, item):
        """Regions of a corpus item: the regions named in the title and summary; if none is named, its outlet's region.
        A regional outlet often reprints news of other regions, so a named place wins over the outlet (precision 0.58 -> see benchmark)."""
        if item["aid"] not in self._cache:
            regions = self.find(item["title"] + " " + (item.get("summary") or ""))
            if not regions and item.get("source") in self.outlets:
                regions = {self.outlets[item["source"]]}
            self._cache[item["aid"]] = regions
        return self._cache[item["aid"]]
