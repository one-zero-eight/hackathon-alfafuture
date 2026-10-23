"""Per-news causal chain: plan -> analytics (IRCoT) -> decision (playbook + TRIZ) -> verification -> page JSON.

One selected news item produces its own analytics widget and its own decision. The page is the set of those chains.
News collection and selection are inputs, not this module.
"""
import json
import time
from pathlib import Path

from reasoning.data import corpus, profiles, roles
from reasoning.search import Index

WRITER = "deepseek/deepseek-v4.1-flash"
VERIFIER = "qwen/qwen3.6-35b-a3b"  # a different family than the writer, so it is not grading its own text
OUT = Path(__file__).resolve().parent / "out"

# Fixed list: the model may apply these, it may not invent new ones. Business reading, not the engineering original.
MOVES = {
    "предварительное действие": "сделать шаг до того, как условие ухудшится",
    "дробление": "разбить одно действие на части с разными сроками или долями",
    "посредник": "переложить часть риска или операции на уже доступный инструмент банка",
    "заранее подложенная подушка": "заранее зарезервировать покрытие риска",
    "идеальный конечный результат": "как задача решается сама имеющимися ресурсами компании",
}
HORIZON = {"days": "urgent", "weeks": "urgent", "months": "medium_term", "years": "not_urgent"}
ROLE_RU = {"CEO": "Генеральный директор", "CFO": "Финансовый директор",
           "chief_accountant": "Главный бухгалтер", "treasury_head": "Руководитель казначейства"}


def norm(text: str) -> str:
    return " ".join(str(text).split())


def grounded(evidence: list, blobs: dict) -> list:
    """Keep only citations whose id exists and whose quote is a verbatim fragment of that source."""
    ok = []
    for e in evidence or []:
        blob = blobs.get(e.get("id", ""))
        quote = norm(e.get("quote", ""))
        if blob and quote and quote in blob:
            ok.append({"id": e["id"], "quote": quote})
    return ok


def plan(card: dict | None, profile: dict) -> list[str]:
    """How the event can reach this company. Rules, no LLM call."""
    card = card or {}
    kinds, et = [], card.get("event_type")
    if profile["okved"] in card.get("okved", []):
        kinds.append("direct")
    if et in ("monetary_policy", "fx") and set(profile["products"]) & {"credit", "leasing", "deposits"}:
        kinds.append("product")
    if et == "commodity_prices":
        kinds.append("resource")
    if et in ("sanctions_trade", "fx"):
        kinds.append("trade")
    return kinds or ["direct"]


def _blob(item: dict) -> str:
    return norm(" ".join(str(item.get(k, "")) for k in ("title", "text", "claim", "quote")))


def _show(ids: list, items: dict) -> str:
    return "\n".join(f"[{i}] {items[i].get('title', '')} — {_blob(items[i])[:500]}" for i in ids if i in items)


def hop2(llm, event: dict, items: dict, index: Index, profile: dict, kinds: list[str]) -> list[dict]:
    """Up to 3 iterations: write one thought, then search again with that thought. Ungrounded thoughts are dropped."""
    blobs = {i: _blob(it) for i, it in items.items()}
    notes, seen = [], {event["id"]}
    thought = event["title"]
    for n in range(3):
        hits = index.search(thought, k=2, prefix="alfa:") + index.search(thought, k=3, exclude=seen)
        hits = list(dict.fromkeys(hits))
        seen.update(hits)
        prompt = f"""Компания: ОКВЭД {profile['okved']} ({profile['okved_name']}), регион {profile['region']}, продукты банка: {', '.join(profile['products'])}.
Связь события с компанией ищется так: {', '.join(kinds)}.
Новость: {event['title']}
{event.get('text', '')}
Уже выведено: {json.dumps([x['thought'] for x in notes], ensure_ascii=False)}
Материалы:
{_show([event['id'], *hits], items)}
Напиши ОДНО следующее предложение: что это значит именно для этой компании. Не выдумывай фактов.
Верни только JSON: {{"relevant": true, "done": false, "thought": "...", "evidence": [{{"id": "A0001", "quote": "дословный фрагмент из материала"}}]}}
relevant=false, если на компанию это не влияет. quote — дословная подстрока одного материала."""
        ans = llm.json(WRITER, prompt, f"hop2.{event['id']}.{n}")
        ev = grounded(ans.get("evidence"), blobs)
        if not ans.get("relevant") or not ev:
            break
        notes.append({"thought": ans.get("thought", ""), "evidence": ev})
        thought = ans.get("thought") or thought
        if ans.get("done"):
            break
    return notes


def hop3(llm, event: dict, notes: list[dict], role: dict, triz: bool) -> dict | None:
    moves = "\n".join(f"- {k}: {v}" for k, v in MOVES.items()) if triz else "(ТРИЗ выключена — только правила роли)"
    prompt = f"""Роль: {role['title']}. Полномочия: {role['authority']}.
Правила роли:
{role['playbook']}
Приёмы (выбирай только из списка):
{moves}
Новость: {event['title']}
Аналитика: {json.dumps(notes, ensure_ascii=False)}
Дай одно решение для этой новости. Оно обязано ссылаться на аналитику. Приём ТРИЗ — только если его нет среди правил роли.
Первый символ ответа — {{. Без текста вокруг. probability и impact — целые 1..4, risks — от 2 до 4.
{{"title": "...", "text": "...", "why": "...", "move": null, "contradiction": null, "risks": [{{"name": "...", "probability": 2, "impact": 3, "mitigation": "..."}}]}}"""
    # 4000, not the default 1200: on the long role card this model spends ~1500 tokens reasoning before the JSON.
    ans = llm.json(WRITER, prompt, f"hop3.{event['id']}", max_tokens=4000)
    if not ans.get("title") or not ans.get("text"):
        return None
    if ans.get("move") not in MOVES:
        ans["move"] = None
    ans["risks"] = [r for r in ans.get("risks") or []
                    if isinstance(r.get("probability"), int) and isinstance(r.get("impact"), int)
                    and 1 <= r["probability"] <= 4 and 1 <= r["impact"] <= 4][:4]
    return ans


def verify(llm, claims: list[dict]) -> set[int]:
    """Returns indexes the other model marks unsupported. The caller already dropped bad quotes.

    One call for every claim makes this model spend the whole token cap on reasoning, so claims go in fours.
    A failed batch is kept: the quotes were already checked against the source text.
    """
    bad = set()
    for start in range(0, len(claims), 4):
        batch = claims[start:start + 4]
        prompt = ("По каждой цитате реши, следует ли из неё утверждение. "
                  "Первый символ ответа — {. Верни только JSON {\"verdicts\": [\"supported\" или \"unsupported\", ...]} "
                  "в том же порядке.\n"
                  + json.dumps([{"text": c["text"], "quote": c["quote"]} for c in batch], ensure_ascii=False))
        try:
            ans = llm.json(VERIFIER, prompt, f"verify.{start}", max_tokens=2000)
        except RuntimeError as e:
            print(f"verify {start} FAILED {e}", flush=True)
            continue
        for j, verdict in enumerate(ans.get("verdicts") or []):
            if verdict != "supported":
                bad.add(start + j)
    return bad


def _status(pid: str, done: int, total: int, event: dict, t0: float) -> None:
    spent = time.time() - t0
    left = round(spent / done * (total - done) / 60) if done else None
    OUT.mkdir(exist_ok=True)
    (OUT / "status.json").write_text(json.dumps({
        "profile": pid, "done": done, "total": total, "event": event["id"],
        "title": event["title"][:80], "elapsed_sec": round(spent), "left_min": left,
    }, ensure_ascii=False), encoding="utf-8")


def build(profile: dict, role: dict, events: list[dict], items: dict, llm, triz: bool = True, limit: int = 10) -> dict:
    index = Index({i: _blob(it) for i, it in items.items()})
    widgets, links, journal = [], [], []
    claims = []
    chosen, t0 = events[:limit], time.time()
    for n, event in enumerate(chosen, 1):
        card = items.get(event["id"], {}).get("card")
        kinds = plan(card, profile)
        _status(profile["id"], n - 1, len(chosen), event, t0)
        print(f"chain {n}/{len(chosen)} {event['id']} {event['title'][:70]}", flush=True)
        try:
            notes = hop2(llm, event, items, index, profile, kinds)
        except RuntimeError as e:
            print(f"chain {n}/{len(chosen)} analytics FAILED {e}", flush=True)
            notes = []
        decision = None
        if notes:
            try:
                decision = hop3(llm, event, notes, role, triz)
            except RuntimeError as e:
                print(f"chain {n}/{len(chosen)} decision FAILED {e}", flush=True)
        left = round((time.time() - t0) / n * (len(chosen) - n) / 60)
        print(f"chain {n}/{len(chosen)} done analytics={len(notes)} decision={bool(decision)} left ~{left} min", flush=True)
        _status(profile["id"], n, len(chosen), event, t0)
        journal.append({"event": event["id"], "plan": kinds, "notes": len(notes), "decision": bool(decision),
                        "move": (decision or {}).get("move"),
                        "evidence": [e["id"] for note in notes for e in note["evidence"]]})
        news_id = f"n{n}"
        widgets.append({"id": news_id, "column": "news", "title": event["title"],
                        "tags": {"industry": (card or {}).get("event_type", "")},
                        "details": {"text": event.get("text") or event["title"], "src": event.get("source", ""), "date": event.get("date", "")}})
        if not notes:
            continue
        src = "alfa" if any(e["id"].startswith("alfa:") for note in notes for e in note["evidence"]) else "ai"
        ana_id = f"a{n}"
        widgets.append({"id": ana_id, "column": "analytics", "title": notes[-1]["thought"][:120],
                        "tags": {"confidence": "reliable" if src == "alfa" else "probable", "source": src},
                        "details": {"text": " ".join(x["thought"] for x in notes)}})
        links.append({"id": f"l{n}a", "from": news_id, "to": ana_id, "text": notes[-1]["thought"]})
        for note in notes:
            claims.append({"widget": ana_id, "text": note["thought"], "quote": note["evidence"][0]["quote"]})
        if not decision:
            continue
        dec_id = f"d{n}"
        widgets.append({"id": dec_id, "column": "decisions", "title": decision["title"],
                        "tags": {"confidence": "possible" if decision.get("move") else "probable", "source": "ai",
                                 "urgency": HORIZON.get((card or {}).get("horizon"), "medium_term")},
                        "details": {"text": decision["text"] + (f" Приём: {decision['move']}." if decision.get("move") else "")},
                        "risks": {"steps": [decision["text"]], "bank_offer": None, "risks": decision["risks"]}})
        links.append({"id": f"l{n}d", "from": ana_id, "to": dec_id,
                      "text": decision.get("why") or decision.get("contradiction") or decision["text"]})
    bad = verify(llm, claims)
    drop = {claims[i]["widget"] for i in bad if i < len(claims)}
    if drop:
        widgets = [w for w in widgets if w["id"] not in drop and not (w["column"] == "decisions" and f"a{w['id'][1:]}" in drop)]
        links = [l for l in links if l["from"] not in drop and l["to"] not in drop]
    return {
        "version": 1,
        "company": {"name": f"Профиль {profile['id']}", "okved": f"{profile['okved']} {profile['okved_name']}",
                    "role": ROLE_RU.get(profile["role"], role["title"]), "date": "неделя 13–21 октября 2026"},
        "widgets": widgets, "links": links, "journal": journal,
    }


def run(pid: str, llm, triz: bool = True) -> dict:
    profile, role = profiles()[pid], roles()[profiles()[pid]["role"]]
    events, items = corpus(pid)
    theses = OUT / "theses.jsonl"
    if theses.exists():
        for row in theses.read_text(encoding="utf-8").splitlines():
            t = json.loads(row)
            items[t["id"]] = {"id": t["id"], "title": t["claim"], "text": t["quote"], "claim": t["claim"]}
    page = build(profile, role, events, items, llm, triz=triz)
    OUT.mkdir(exist_ok=True)
    (OUT / f"{pid}.json").write_text(json.dumps(page, ensure_ascii=False, indent=1), encoding="utf-8")
    return page
