"""Builds news_search/regions.json (see region.py). Run from the repository root: python news_search/regions_build.py"""

import csv
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VOCABULARY = os.path.join(ROOT, "collector/internal/news/vocabulary/data/v1.json")
SOURCES = os.path.join(ROOT, "collector/sources.json")
COMPANIES = os.path.join(ROOT, "external-docs/company/df_Uid_data_hack.csv")


def main():
    with open(VOCABULARY, encoding="utf-8") as f:
        tags = [t for t in json.load(f)["tags"] if t.get("kind") == "profile_region"]
    by_id = {t["id"]: t["label"] for t in tags}
    regions = {
        t["label"]: sorted(
            {t["label"], *t["aliases"], *t.get("profile_region_values", [])}
        )
        for t in tags
    }
    cities = {label: [] for label in regions}
    label_of = {v: t["label"] for t in tags for v in t.get("profile_region_values", [])}
    # bank data: city -> region; a city name found in several regions is ambiguous and left out
    seen = {}
    with open(COMPANIES, encoding="utf-8") as f:
        for row in csv.DictReader(f, delimiter=";"):
            city, region = (
                row["CITY"].removeprefix("г. ").strip(),
                label_of.get(row["REGION"]),
            )
            if city and region:
                seen.setdefault(city, set()).add(region)
    for city, labels in seen.items():
        if len(labels) == 1:
            cities[labels.pop()].append(city)
    with open(SOURCES, encoding="utf-8") as f:
        outlets = {
            s["id"]: by_id[s["region"]]
            for s in json.load(f)
            if s.get("region") in by_id
        }
    out = {
        "regions": {k: sorted(set(v)) for k, v in regions.items()},
        "cities": {k: sorted(set(v)) for k, v in cities.items()},
        "outlets": outlets,
    }
    with open(
        os.path.join(ROOT, "news_search/regions.json"), "w", encoding="utf-8"
    ) as f:
        json.dump(out, f, ensure_ascii=False, indent=0, sort_keys=True)
    print(
        f"{len(regions)} regions, {sum(map(len, out['regions'].values()))} names, {sum(map(len, out['cities'].values()))} cities, {len(outlets)} outlets"
    )


if __name__ == "__main__":
    main()
