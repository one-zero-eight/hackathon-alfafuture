"""One conclusion for a sphere from several news, then one action for this company.

The per-news chain in chain.py stays as it is. This module adds a widget after those chains.
The sphere prompt has OKVED, region and the typed sphere. The company name, revenue and bank products
are shown only to the decision agent.
"""
import logging
from collections import defaultdict

log = logging.getLogger("analytics")
HORIZONS = {"urgent", "medium_term", "not_urgent"}
TYPES = {"risk", "opportunity", "observation"}


def sphere_text(profile: dict, sphere: str) -> str:
    """What any company of this trade and region shares. No name, no revenue, no bank products."""
    parts = []
    code, name = profile.get("okved_code") or "", profile.get("okved_name") or ""
    if code or name:
        parts.append(f"ОКВЭД {code} ({name})".replace("  ", " ").strip())
    if profile.get("region"):
        parts.append(f"регион {profile['region']}")
    if profile.get("workers"):
        parts.append(f"сотрудников {profile['workers']}")
    for key, label in (("suppliers", "поставщики"), ("customers", "покупатели")):
        names = profile.get(key) or []
        if isinstance(names, str):
            names = [names]
        names = [n for n in names if n][:3]
        if names:
            parts.append(label + ": " + ", ".join(names))
    if sphere:
        parts.append(f"сфера {sphere}")
    return ", ".join(p for p in parts if p) or "сфера не указана"


def story_group(events: list[dict], pairs: list) -> list[int]:
    """Indexes of the news behind one conclusion. Pairs and shared tags connect a story; otherwise the whole page.

    One conclusion per page: the largest connected story, and only when it has at least two news.
    """
    n = len(events)
    if n < 2:
        return []
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    linked = False
    for pair in pairs or []:
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            continue
        a, b = pair
        if isinstance(a, int) and isinstance(b, int) and 0 <= a < n and 0 <= b < n and a != b:
            union(a, b)
            linked = True
    tags = [set(ev.get("tags") or []) for ev in events]
    for i in range(n):
        for j in range(i + 1, n):
            if tags[i] & tags[j]:
                union(i, j)
                linked = True
    if not linked:
        return list(range(n))
    buckets = defaultdict(list)
    for i in range(n):
        buckets[find(i)].append(i)
    multi = [group for group in buckets.values() if len(group) >= 2]
    return max(multi, key=len) if multi else []


def _risks(raw) -> list[dict]:
    return [r for r in raw or [] if isinstance(r, dict) and isinstance(r.get("probability"), int) and isinstance(r.get("impact"), int)
            and 1 <= r["probability"] <= 4 and 1 <= r["impact"] <= 4][:4]


def add_synthesis(agents, profile: dict, role: dict, sphere: str, events: list[dict], items: dict,
                  widgets: list, links: list, claims: list, triz: bool, pairs: list) -> None:
    """Append s1 (sphere conclusion) and sd1 (one company action). Quotes that are not verbatim are dropped."""
    from analytics.chain import MOVES, _ask, _blob, _show, bank_related, grounded, paper_href

    group = story_group(events, pairs)
    if len(group) < 2:
        return
    picked = [events[i] for i in group]
    ids = [ev["id"] for ev in picked]
    for i, it in items.items():
        if not str(i).startswith("alfa:"):
            continue
        body = (it.get("title") or "") + " " + (it.get("text") or "")
        if any(bank_related(ev["title"], body) for ev in picked):
            ids.append(i)
    blobs = {i: _blob(items[i]) for i in ids if i in items}
    try:
        ans = agents.run("synthesis", {"sphere": sphere_text(profile, sphere), "materials": _show(ids, items)})
    except RuntimeError as e:
        log.warning("synthesis failed: %s", e)
        return
    evidence = grounded(ans.get("evidence"), blobs)
    sources = {e["id"] for e in evidence if not str(e["id"]).startswith("alfa:")}
    if len(sources) < 2 or not ans.get("text"):
        return
    text = ans["text"]
    # The bank thesis is part of the conclusion when it shares a headline's subject, even if the model did not cite it.
    if not any(str(e["id"]).startswith("alfa:") for e in evidence):
        for i in ids:
            if not str(i).startswith("alfa:"):
                continue
            quote = " ".join(str(items[i].get("text") or "").split())
            if quote and quote in blobs.get(i, ""):
                evidence.append({"id": i, "quote": quote})
                text = text.rstrip() + " Позиция банка: " + quote
                break
    kind, horizon = ans.get("type") or "observation", ans.get("horizon") or "medium_term"
    if kind not in TYPES:
        kind = "observation"
    if horizon not in HORIZONS:
        horizon = "medium_term"
    alfa = next((e["id"] for e in evidence if str(e["id"]).startswith("alfa:")), "")
    conf = "reliable" if len(sources) >= 2 else "probable"
    widgets.append({"id": "s1", "column": "analytics", "title": text[:120],
                    "tags": {"confidence": conf, "source": "alfa" if alfa else "ai", "type": kind, "urgency": horizon},
                    "details": {"text": text}, **({"url": paper_href(alfa)} if alfa and paper_href(alfa) else {})})
    for i in group:
        links.append({"id": f"ls{i+1}", "from": f"n{i+1}", "to": "s1", "text": text})
    for e in evidence:
        claims.append({"widget": "s1", "text": text, "quote": e["quote"]})
    try:
        decision = agents.run("synthesis_decision", {
            "sphere": sphere_text(profile, sphere), "conclusion": text, "facts": profile.get("facts") or "",
            "role": role, "moves": MOVES if triz else {}})
    except RuntimeError as e:
        log.warning("synthesis decision failed: %s", e)
        return
    if not decision.get("title") or not decision.get("text"):
        return
    if decision.get("move") not in MOVES:
        decision["move"] = None
    decision["risks"] = _risks(decision.get("risks"))
    d_horizon = decision.get("horizon") if decision.get("horizon") in HORIZONS else horizon
    widget = {"id": "sd1", "column": "decisions", "title": decision["title"],
              "tags": {"confidence": "probable", "source": "ai", "urgency": d_horizon, "type": kind},
              "details": {"text": decision["text"] + (f" Приём: {decision['move']}." if decision.get("move") else "")},
              "risks": {"steps": [decision["text"]], "bank_offer": None, "risks": decision["risks"]}}
    ask = _ask(widget)
    if ask:
        widget["chat"] = {"text": decision["title"], "basis": [], "followups": [ask]}
    widgets.append(widget)
    links.append({"id": "lsd1", "from": "s1", "to": "sd1", "text": decision.get("why") or decision["text"]})
