"""Feedback state of a profile and the page edits made from it: sources, provenance, exclusions, composing new chains, removal, patches.

State (profiles.feedback_state): sources {ref: article}, widget_sources {news widget id: [ref]}, removed_aids/removed_urls/removed_refs
(excluded articles), effective {line, region} (the perspective in force), manual_ids (widgets whose text the user wrote).
Provenance is tags.source: human (user's text or link), ai (generated), alfa (bank material); source links stay in widget_sources.
"""

import copy
import uuid

from backend import pages

ORIGINS = ("human", "ai", "alfa")


def ref_of(item: dict) -> str:
    return item.get("ref") or f"article:{item['aid']}"


def source_of(item: dict, origin: str = "search") -> dict:
    return {
        "ref": ref_of(item),
        "aid": item.get("aid"),
        "title": item.get("title", ""),
        "link": item.get("link", ""),
        "original_url": item.get("original_url", ""),
        "summary": item.get("summary", ""),
        "outlets": item.get("outlets") or [],
        "date": item.get("date", ""),
        "origin": item.get("origin", origin),
    }


def match(widget: dict, news: list[dict]):
    """The news item a news widget was written from: analytics copies its title and link into the widget."""
    return next(
        (n for n in news if widget.get("url") and n.get("link") == widget["url"]), None
    ) or next((n for n in news if n.get("title") == widget["title"]), None)


def initial_state(
    page: dict,
    news: list[dict] = (),
    line: str = "",
    region: str = "",
    existing: dict | None = None,
) -> dict:
    state = (
        copy.deepcopy(existing)
        if existing
        else {
            "sources": {},
            "widget_sources": {},
            "removed_aids": [],
            "removed_urls": [],
            "removed_refs": [],
            "effective": {},
            "manual_ids": [],
        }
    )
    for w in page["widgets"]:
        item = (
            match(w, news)
            if w["column"] == "news" and w["id"] not in state["widget_sources"]
            else None
        )
        if item:
            state["sources"].setdefault(ref_of(item), source_of(item))
            state["widget_sources"][w["id"]] = [ref_of(item)]
    return state


def public_sources(state: dict, refs) -> list[dict]:
    rows = (state["sources"].get(r) for r in sorted(set(refs)))
    return [
        {"ref": s["ref"], "title": s["title"], "url": s["link"], "origin": s["origin"]}
        for s in rows
        if s
    ]


def excluded(item: dict, state: dict) -> bool:
    return (
        ref_of(item) in state["removed_refs"]
        or item.get("aid") in state["removed_aids"]
        or item.get("link") in state["removed_urls"]
        or item.get("original_url") in state["removed_urls"]
    )


def allowed(items: list[dict], state: dict) -> list[dict]:
    seen, kept = set(), []
    for item in items:
        key = item.get("link") or ref_of(item)
        if not excluded(item, state) and key not in seen:
            seen.add(key)
            kept.append(item)
    return kept


def shown_refs(page: dict, state: dict) -> set:
    return {
        r
        for w in page["widgets"]
        if w["column"] == "news"
        for r in state["widget_sources"].get(w["id"], [])
    }


def compose(
    key: str, old: dict, raw: dict, news: list[dict], state: dict, replace: bool = False
) -> dict:
    """Old page + a fresh analytics page -> new page. Ids get a version suffix (n1 -> n1v2, the shape the journal accepts), so they never clash. replace=True drops the generated
    widgets first and keeps only the user's own (manual_ids) with the links among them."""
    page = copy.deepcopy(old)
    version = old["version"] + 1
    if replace:
        keep = {w["id"] for w in page["widgets"] if w["id"] in state["manual_ids"]}
        page["widgets"] = [w for w in page["widgets"] if w["id"] in keep]
        page["links"] = [
            l for l in page["links"] if l["from"] in keep and l["to"] in keep
        ]
        state["widget_sources"] = {
            k: v for k, v in state["widget_sources"].items() if k in keep
        }
    taken = shown_refs(page, state)
    new_ids = {w["id"]: f"{key}_{w['id']}v{version}" for w in raw["widgets"]}
    skipped = set()
    for w in raw["widgets"]:
        item = match(w, news) if w["column"] == "news" else None
        if item and ref_of(item) in taken:
            skipped.add(w["id"])
            continue
        w = copy.deepcopy(w)
        w["id"] = new_ids[w["id"]]
        if item:
            state["sources"][ref_of(item)] = source_of(item)
            state["widget_sources"][w["id"]] = [ref_of(item)]
            if item.get("origin") == "human":
                w["tags"] = {**w.get("tags", {}), "source": "human"}
        page["widgets"].append(w)
    for l in raw["links"]:
        if l["from"] in skipped or l["to"] in skipped:
            continue
        page["links"].append(
            {
                **l,
                "id": f"{key}_{l['id']}v{version}",
                "from": new_ids[l["from"]],
                "to": new_ids[l["to"]],
            }
        )
    page["version"] = version
    return page


def remove(page: dict, state: dict, target: str) -> None:
    """Remove a widget and what only it supported: generated descendants whose every parent is gone. Shared and user's widgets stay."""
    gone, changed = {target}, True
    while changed:
        changed = False
        for w in page["widgets"]:
            parents = {l["from"] for l in page["links"] if l["to"] == w["id"]}
            if (
                w["id"] in gone
                or w["id"] in state["manual_ids"]
                or w.get("tags", {}).get("source") == "human"
                or not parents
            ):
                continue
            if parents <= gone:
                gone.add(w["id"])
                changed = True
    for wid in gone:
        for ref in state["widget_sources"].pop(wid, []):
            item = state["sources"].get(ref, {})
            state["removed_refs"].append(ref)
            if item.get("aid") is not None:
                state["removed_aids"].append(item["aid"])
            state["removed_urls"] += [
                u for u in (item.get("link"), item.get("original_url")) if u
            ]
    state["manual_ids"] = [m for m in state["manual_ids"] if m not in gone]
    page["widgets"] = [w for w in page["widgets"] if w["id"] not in gone]
    page["links"] = [
        l for l in page["links"] if l["from"] not in gone and l["to"] not in gone
    ]
    for key in ("removed_refs", "removed_aids", "removed_urls"):
        state[key] = sorted(set(state[key]), key=str)


def edit_widget(page: dict, state: dict, target: str, text: str) -> None:
    """The user's own wording of a widget: it becomes a human source of its own, the original sources stay linked."""
    widget = pages.find(page["widgets"], target)
    widget["details"] = {**widget.get("details", {}), "text": text}
    widget["chat"] = {"text": text, "basis": [], "followups": []}
    widget["tags"] = {**widget.get("tags", {}), "source": "human"}
    ref = "user:" + uuid.uuid4().hex[:16]
    state["sources"][ref] = {
        "ref": ref,
        "aid": None,
        "title": widget["title"],
        "link": widget.get("url") or "",
        "original_url": "",
        "summary": text,
        "outlets": [],
        "date": "",
        "origin": "human",
        "original_refs": state["widget_sources"].get(target, []),
    }
    state["widget_sources"][target] = [ref, *state["widget_sources"].get(target, [])]
    if target not in state["manual_ids"]:
        state["manual_ids"].append(target)


REVISION_FIELDS = ("title", "details", "tags", "risks", "chat", "url")
COLUMNS = ("news", "analytics", "decisions")


def apply_revision(key: str, old: dict, rev: dict) -> dict:
    """The answer of analytics /revise (docs/backend.md) -> new page: added widgets and links get fresh ids, listed widgets are updated or removed."""
    version = old["version"] + 1
    page = copy.deepcopy(old)
    have = {w["id"] for w in page["widgets"]}
    new_ids, fresh = {}, []
    for i, w in enumerate(rev.get("widgets") or [], 1):
        if (
            w.get("column") not in COLUMNS
            or not isinstance(w.get("title"), str)
            or not isinstance(w.get("id"), str)
        ):
            raise ValueError("invalid widget in the revision")
        new_ids[w["id"]] = f"{key}_{w['column'][0]}{i}r{version}"
        fresh.append(
            {
                **{k: w[k] for k in REVISION_FIELDS if k in w},
                "column": w["column"],
                "id": new_ids[w["id"]],
            }
        )
    for u in rev.get("updates") or []:
        widget = pages.find(page["widgets"], u.get("id"))
        if widget is not None:
            widget.update(
                {
                    k: v
                    for k, v in (u.get("fields") or {}).items()
                    if k in REVISION_FIELDS
                }
            )
    gone = {i for i in rev.get("removed") or [] if i in have}
    page["widgets"] = [w for w in page["widgets"] if w["id"] not in gone] + fresh
    ends = {i: i for i in have - gone} | new_ids
    links = [
        {
            "id": f"{key}_l{i}r{version}",
            "from": ends.get(l.get("from")),
            "to": ends.get(l.get("to")),
            "text": str(l.get("text", "")),
        }
        for i, l in enumerate(rev.get("links") or [], 1)
    ]
    page["links"] = [
        l for l in page["links"] if l["from"] not in gone and l["to"] not in gone
    ] + [l for l in links if l["from"] and l["to"]]
    page["version"] = version
    return page


def diff(old: dict, new: dict) -> tuple[list[dict], list[dict]]:
    """Patch ops old -> new and a short human summary [{op, kind, id, title}]."""
    ops, summary = [], []
    sk_old, sk_new = pages.skeleton(old), pages.skeleton(new)
    ow, nw = (
        {w["id"]: w for w in sk_old["widgets"]},
        {w["id"]: w for w in sk_new["widgets"]},
    )
    ol, nl = (
        {l["id"]: l for l in sk_old["links"]},
        {l["id"]: l for l in sk_new["links"]},
    )
    full_old = {w["id"]: w for w in old["widgets"]}
    full_new = {w["id"]: w for w in new["widgets"]}
    ops += [{"op": "remove_link", "id": i} for i in ol if i not in nl]
    for i in ow:
        if i not in nw:
            ops.append({"op": "remove_widget", "id": i})
            summary.append({"op": "removed", "id": i, "title": ow[i]["title"]})
    for i, w in nw.items():
        if i not in ow:
            ops.append({"op": "add_widget", "widget": w})
            summary.append({"op": "added", "id": i, "title": w["title"]})
        elif w != ow[i] or full_old[i].get("details") != full_new[i].get("details"):
            ops.append(
                {
                    "op": "update_widget",
                    "id": i,
                    "fields": {k: v for k, v in w.items() if k != "id"},
                }
            )
            summary.append({"op": "updated", "id": i, "title": w["title"]})
    ops += [{"op": "add_link", "link": l} for i, l in nl.items() if i not in ol]
    ops += [
        {
            "op": "update_link",
            "id": i,
            "fields": {k: v for k, v in l.items() if k != "id"},
        }
        for i, l in nl.items()
        if i in ol and l != ol[i]
    ]
    return ops, summary
