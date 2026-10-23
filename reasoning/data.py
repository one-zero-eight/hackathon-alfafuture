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
