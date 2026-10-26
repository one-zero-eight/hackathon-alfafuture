"""Page composition and stable provenance without changing analytics algorithms."""
import copy
import re
import uuid

from backend import pages


def initial_state(page, state=None, news=()):
    state = copy.deepcopy(state or {})
    for key, default in (("sources", {}), ("widget_sources", {}), ("removed_aids", []), ("removed_urls", []), ("removed_sources", []), ("manual_ids", []), ("effective", {})):
        state.setdefault(key, default)
    # Once stable mappings exist, a later incremental journal must not be replayed over older widgets.
    if not news and state["widget_sources"] and all(state["widget_sources"].get(w["id"]) for w in page["widgets"] if w["column"] == "news"):
        return state
    by_aid = {}
    for item in news:
        ref = item.get("source_id") or (f"article:{item['aid']}" if item.get("aid") else None)
        if ref:
            state["sources"][ref] = {**copy.deepcopy(item), "source_id": ref}
            if item.get("aid"):
                by_aid[f"N{item['aid']}"] = ref
    widgets = [w for w in page["widgets"] if w["column"] == "news"]
    journal = page.get("meta", {}).get("journal", page.get("journal", []))
    event_refs = {}
    for index, widget in enumerate(widgets):
        step = journal[index] if index < len(journal) else {}
        event = step.get("event", "")
        ref = by_aid.get(event)
        if ref is None and index < len(news):
            item = news[index]
            ref = item.get("source_id") or (f"article:{item['aid']}" if item.get("aid") else None)
        if ref is None:
            refs = state["widget_sources"].get(widget["id"], [])
            ref = refs[0] if refs else None
        if ref is None and re.fullmatch(r"N[1-9]\d*", event):
            ref = "article:" + event[1:]
            state["sources"].setdefault(ref, {"source_id": ref, "aid": int(event[1:]), "title": widget["title"], "link": widget.get("url", ""), "summary": widget.get("details", {}).get("text", ""), "outlets": []})
        if ref:
            state["widget_sources"][widget["id"]] = [ref]
            event_refs[event or f"N{index}"] = ref
    for index, widget in enumerate(widgets):
        refs = state["widget_sources"].get(widget["id"], [])
        step = journal[index] if index < len(journal) else {}
        refs = list(dict.fromkeys([*refs, *(event_refs.get(e, by_aid.get(e, e)) for e in step.get("evidence", []) if e.startswith(("N", "alfa:")))]))
        # Analytics emits n1/a1/d1 chains; existing links establish the relationship after publication.
        frontier = [widget["id"]]
        visited = set()
        while frontier:
            parent = frontier.pop()
            if parent in visited:
                continue
            visited.add(parent)
            for link in page["links"]:
                if link["from"] == parent:
                    target = link["to"]
                    state["widget_sources"][target] = list(dict.fromkeys(state["widget_sources"].get(target, []) + refs))
                    frontier.append(target)
    for widget in page["widgets"]:
        if widget.get("tags", {}).get("source") == "human" and widget["id"] not in state["manual_ids"]:
            state["manual_ids"].append(widget["id"])
    return state


def changes(before, after):
    result, ops = [], []
    for collection, singular, keys in (("links", "link", ("id", "from", "to")), ("widgets", "widget", pages.WIDGET_KEYS)):
        old, new = ({w["id"]: w for w in p[collection]} for p in (before, after))
        for wid, widget in old.items():
            if wid not in new:
                ops.append({"op": f"remove_{singular}", "id": wid})
                result.append({"kind": "removed", "type": singular, "id": wid, "title": widget.get("title", "")})
        for wid, widget in new.items():
            visible = {k: widget[k] for k in keys if k in widget}
            if wid not in old:
                ops.append({"op": f"add_{singular}", singular: visible})
                result.append({"kind": "added", "type": singular, "id": wid, "title": widget.get("title", "")})
            elif widget != old[wid]:
                ops.append({"op": f"update_{singular}", "id": wid, "fields": {k: v for k, v in visible.items() if k != "id"}})
                result.append({"kind": "replaced", "type": singular, "id": wid, "title": widget.get("title", "")})
    # Add widgets before their links, remove links before their widgets.
    order = {"remove_link": 0, "remove_widget": 1, "add_widget": 2, "update_widget": 3, "add_link": 4, "update_link": 5}
    ops.sort(key=lambda op: order[op["op"]])
    return {"base_version": before["version"], "version": after["version"], "ops": ops}, result


def remove(page, state, target):
    link = pages.find(page["links"], target)
    if link:
        page["links"] = [item for item in page["links"] if item["id"] != target]
        return
    widget = pages.find(page["widgets"], target)
    if widget is None:
        raise ValueError("unknown target")
    removed = {target}
    target_refs = set(state["widget_sources"].get(target, [])) if widget["column"] == "news" else set()
    while True:
        originals = {ref for current in target_refs for ref in state["sources"].get(current, {}).get("original_sources", [])}
        if originals <= target_refs:
            break
        target_refs |= originals
    retained_refs = {ref for w in page["widgets"] if w["column"] == "news" and w["id"] != target for ref in state["widget_sources"].get(w["id"], [])}
    while True:
        more = set()
        for node in page["widgets"]:
            if node["id"] in removed or node.get("tags", {}).get("source") == "human" or node["id"] in state["manual_ids"]:
                continue
            parents = {l["from"] for l in page["links"] if l["to"] == node["id"]}
            supports = set(state["widget_sources"].get(node["id"], []))
            if parents and parents <= removed and not (supports & retained_refs):
                more.add(node["id"])
        if not more:
            break
        removed |= more
    for ref in target_refs:
        if ref not in state["removed_sources"]:
            state["removed_sources"].append(ref)
        source = state["sources"].get(ref, {})
        if source.get("aid") and source["aid"] not in state["removed_aids"]:
            state["removed_aids"].append(source["aid"])
        if source.get("link") and source["link"] not in state["removed_urls"]:
            state["removed_urls"].append(source["link"])
    if widget["column"] == "news" and widget.get("url") and widget["url"] not in state["removed_urls"]:
        state["removed_urls"].append(widget["url"])
    page["widgets"] = [w for w in page["widgets"] if w["id"] not in removed]
    page["links"] = [l for l in page["links"] if not {l["from"], l["to"]} & removed]
    state["manual_ids"] = [wid for wid in state["manual_ids"] if wid not in removed]


def compose(key, old, raw, news, state, replace=False):
    raw = copy.deepcopy(raw)
    old_state = copy.deepcopy(state)
    incoming = initial_state(raw, news=news)
    suffix = uuid.uuid4().hex[:8]
    mapping = {w["id"]: f"{key}_{w['column'][0]}{suffix}_{i}" for i, w in enumerate(raw["widgets"])}
    keep = set(old_state["manual_ids"])
    for w in old["widgets"]:
        if any(old_state["sources"].get(ref, {}).get("origin") == "human" for ref in old_state["widget_sources"].get(w["id"], [])) and w["column"] == "news":
            keep.add(w["id"])
    # Preserve supporting parents of manual content as well as the content itself.
    while True:
        parents = {l["from"] for l in old["links"] if l["to"] in keep}
        if parents <= keep:
            break
        keep |= parents
    base = copy.deepcopy(old)
    if replace:
        base["widgets"] = [w for w in base["widgets"] if w["id"] in keep]
        base["links"] = [l for l in base["links"] if {l["from"], l["to"]} <= keep]
        base["company"] = raw["company"]
    existing = {tuple(old_state["widget_sources"].get(w["id"], [])): w["id"] for w in base["widgets"] if w["column"] == "news"}
    duplicate_news = set()
    for w in raw["widgets"]:
        refs = incoming["widget_sources"].get(w["id"], [])
        if w["column"] == "news" and refs and tuple(refs) in existing:
            mapping[w["id"]] = existing[tuple(refs)]
            duplicate_news.add(w["id"])
        if w["column"] == "news" and any(incoming["sources"].get(ref, {}).get("origin") == "human" for ref in refs):
            w["tags"] = {**w.get("tags", {}), "source": "human"}
            if mapping[w["id"]] not in state["manual_ids"]:
                state["manual_ids"].append(mapping[w["id"]])
        elif w["column"] != "news":
            w["tags"] = {**w.get("tags", {}), "source": w.get("tags", {}).get("source", "ai")}
    for w in raw["widgets"]:
        original = w["id"]
        if original not in duplicate_news:
            w["id"] = mapping[original]
            base["widgets"].append(w)
        state["widget_sources"][mapping[original]] = incoming["widget_sources"].get(original, [])
    for link in raw["links"]:
        base["links"].append({**link, "id": f"{key}_l{suffix}_{len(base['links'])}", "from": mapping[link["from"]], "to": mapping[link["to"]]})
    state["sources"].update(incoming["sources"])
    base["meta"] = {**base.get("meta", {}), "journal": raw.get("journal", [])}
    return base


def public_sources(state, refs=None):
    selected = set(refs) if refs is not None else set(state["sources"])
    result = []
    for ref in sorted(selected):
        source = state["sources"].get(ref)
        if source:
            result.append({"id": ref, "title": source["title"], "url": source.get("link", ""), "origin": source.get("origin", "news")})
        elif re.fullmatch(r"alfa:.+:p\d+:t\d+", ref):
            doc, number = re.fullmatch(r"alfa:(.+):p(\d+):t\d+", ref).groups()
            result.append({"id": ref, "title": doc, "url": f"/api/papers/{doc}.pdf#page={number}", "origin": "alfa"})
    return result


def compact(page, state):
    """Old pages remain in revisions; active state keeps only active provenance and pinned inputs."""
    ids = {w["id"] for w in page["widgets"]}
    state["widget_sources"] = {wid: refs for wid, refs in state["widget_sources"].items() if wid in ids}
    state["manual_ids"] = [wid for wid in state["manual_ids"] if wid in ids]
    refs = {ref for values in state["widget_sources"].values() for ref in values}
    refs |= {ref for ref, source in state["sources"].items() if source.get("origin") == "human" and ref not in state["removed_sources"] and source.get("link") not in state["removed_urls"]}
    while True:
        originals = {ref for current in refs for ref in state["sources"].get(current, {}).get("original_sources", [])}
        if originals <= refs:
            break
        refs |= originals
    state["sources"] = {ref: source for ref, source in state["sources"].items() if ref in refs}
    return state
