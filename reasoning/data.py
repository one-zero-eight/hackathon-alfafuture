"""Inputs from the offline study in exp/v2: profiles, role playbooks, event cards, selection packets, gold nuggets.

News collection and selection are other modules; this pipeline starts from an already selected packet.
"""
import json
import re
from pathlib import Path

EXP = Path(__file__).resolve().parent.parent / "exp" / "v2"
PACKETS = EXP / "p5" / "packets" / "xQuAD_B3"  # best selection arm of the study (FINDINGS.md)

LEAD = re.compile(r"^\[(A\d{4})\] (\S+) \| (.+?) \(x\d+\) \| (.+)$")
SUB = re.compile(r"^\s*-?\s*\[(A\d{4})\] (.+?) — (.*)$")


def profiles() -> dict:
    return {p["id"]: p for p in json.loads((EXP / "p0" / "profiles.json").read_text())}


def roles() -> dict:
    return json.loads((EXP / "p5" / "roles.json").read_text())


def cards() -> dict:
    return {c["sid"]: c for c in map(json.loads, (EXP / "p1" / "cards.jsonl").read_text().splitlines())}


def nuggets() -> dict:
    return json.loads((EXP / "p2" / "nuggets.json").read_text())


def packet_text(pid: str) -> str:
    return (PACKETS / f"{pid}.md").read_text()


def parse_packet(text: str) -> tuple[list[dict], dict]:
    """Lead stories with their related stories, plus every item seen in the packet by ID.

    shortcut: lead text is the packet's 600-char excerpt, so quote checks run on that excerpt only; upgrade to the
    news service's stored article text once the pipeline reads from its API.
    """
    events, items, cur, in_lead = [], {}, None, False
    for line in text.splitlines():
        if m := LEAD.match(line):
            sid, date, src, title = m.groups()
            cur = {"id": sid, "date": date, "source": src, "title": title, "text": "", "related": []}
            events.append(cur)
            items[sid] = cur
            in_lead = True
        elif cur and in_lead and line.startswith("    ") and not line.strip().startswith(("Related", "-", "(graph")):
            cur["text"] = " ".join(line.split())
            in_lead = False
        elif m := SUB.match(line):
            sid, title, lead = m.groups()
            it = items.setdefault(sid, {"id": sid, "title": title, "text": " ".join(lead.split()), "related": []})
            if cur and line.strip().startswith("-"):
                cur["related"].append(sid)
            else:
                cur = None  # "other headlines" section: items without a lead story
            items[sid] = it
        elif line.startswith("OTHER RELEVANT HEADLINES"):
            cur = None
    return events, items


def corpus(pid: str) -> tuple[list[dict], dict]:
    """Events of the profile's packet and a searchable corpus: packet items plus every card of the week."""
    events, items = parse_packet(packet_text(pid))
    for sid, c in cards().items():
        it = items.setdefault(sid, {"id": sid, "title": c["event"], "text": c["mechanism"], "related": []})
        it["card"] = c
    return events, items


def okved_section(code: str) -> str:
    """OKVED2 class (the number before the dot) to the section letter the news cards use."""
    try:
        n = int(str(code).split(".")[0])
    except ValueError:
        return ""
    for hi, sec in ((3, "A"), (9, "B"), (33, "C"), (35, "D"), (39, "E"), (43, "F"), (47, "G"),
                    (53, "H"), (56, "I"), (63, "J"), (66, "K"), (68, "L"), (75, "M"), (82, "N"),
                    (84, "O"), (85, "P"), (88, "Q"), (93, "R"), (96, "S"), (98, "T"), (99, "U")):
        if n <= hi:
            return sec
    return ""


_ARTICLES: dict | None = None
_COUNT = re.compile(r"\s*\(x\d+\)$")


def articles() -> dict:
    """Real article text from the week. Publication and date exist only when a packet recorded them."""
    global _ARTICLES
    if _ARTICLES is not None:
        return _ARTICLES
    text: dict[str, str] = {}
    for path in (EXP / "p0" / "batches").glob("*.md"):
        for line in path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\[(A\d{4})\] (.*)$", line)
            if m and len(m.group(2)) > len(text.get(m.group(1), "")):
                text[m.group(1)] = m.group(2)
    meta: dict[str, tuple[str, str]] = {}
    for path in (EXP / "p5" / "packets").rglob("*.md"):
        for line in path.read_text(encoding="utf-8").splitlines():
            m = LEAD.match(line)
            if m and m.group(1) not in meta:
                meta[m.group(1)] = (m.group(2), _COUNT.sub("", m.group(3)))
    _ARTICLES = {
        sid: {"id": sid, "text": body, "date": meta.get(sid, ("", ""))[0], "source": meta.get(sid, ("", ""))[1]}
        for sid, body in text.items()
    }
    return _ARTICLES


_SKIP = {"other", "security_conflict", "weather_disaster"}
_PROCURE = ("закуп", "снабжен", "тендер", "поставк", "импорт")


def _rate(ev: str) -> bool:
    return "ключев" in ev or "банк россии" in ev or re.search(r"(?<![а-яё])цб(?![а-яё])", ev) is not None


def pick(cards_list: list[dict], library: dict, section: str, products: list[str], limit: int = 8,
         topic: str = "", words: tuple[str, ...] = ()) -> list[dict]:
    """News for one section, or for a sphere that is not a section.

    A section keeps every business event the study tagged with that letter. Procurement keeps supply stories
    and headlines about purchasing. One Bank of Russia rate story is added when the company borrows.
    """
    from reasoning.focus import _close, _words
    direct, rates = [], []
    borrows = bool(set(products) & {"credit", "leasing", "deposits"})
    asked = [w for w in words if len(w) >= 4]
    for c in cards_list:
        art = library.get(c["sid"]) or {}
        if len(art.get("text") or "") < 80:
            continue
        ev = (c.get("event") or "").lower().replace("ё", "е")
        kind = c.get("event_type")
        rate = kind == "monetary_policy" and _rate(ev)
        if topic == "procurement" and (kind == "supply_logistics" or any(s in ev for s in _PROCURE)):
            direct.append(c)
        elif topic == "rates" and rate:
            rates.append(c)
        elif asked and any(_close(w, hw) for w in asked for hw in _words(ev)):
            direct.append(c)
        elif section and section in (c.get("okved") or []) and kind not in _SKIP:
            direct.append(c)
        elif borrows and rate:
            rates.append(c)
    direct.sort(key=lambda c: c["sid"])
    rates.sort(key=lambda c: ("ключев" not in (c.get("event") or "").lower(), c["sid"]))
    chosen = direct[:limit - (1 if rates else 0)]
    if rates and len(chosen) < limit:
        chosen.append(rates[0])
    return chosen


def news_for(profile: dict, limit: int = 8) -> tuple[list[dict], dict]:
    """Selected real articles for a company card. The quote check uses the article text, not the card summary."""
    library = articles()
    rows = list(cards().values())
    products = profile.get("products") or []
    topic = profile.get("topic") or ""
    words = tuple(profile.get("focus_words") or ())
    if topic:
        chosen = pick(rows, library, "", products, limit, topic=topic)
    elif words:
        chosen = pick(rows, library, "", products, limit, words=words)
        own = [c for c in chosen if c.get("event_type") != "monetary_policy"]
        if len(own) < 2:
            chosen = pick(rows, library, profile["okved"], products, limit)
    else:
        chosen = pick(rows, library, profile.get("focus_section") or profile["okved"], products, limit)
    events, items = [], {}
    for c in chosen:
        art = library[c["sid"]]
        ev = {"id": c["sid"], "title": c["event"], "text": art["text"], "source": art.get("source") or "",
              "date": art.get("date") or "", "related": []}
        events.append(ev)
        items[c["sid"]] = {**ev, "card": c}
    print(f"новости для {profile['id']}: {len(events)}", flush=True)
    for ev in events:
        print(f"  {ev['id']} {ev['title'][:90]}", flush=True)
    return events, items
