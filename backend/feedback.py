"""Orchestration of the user's feedback (docs/backend.md): one queued operation = classify the request (agent feedback_intent), pick the chain
of existing services (/reply, /refine, /page), build the new page version, publish it with a patch. The services own their algorithms."""

import copy
import logging
import threading

from agents.client import Agents
from backend import (
    article_fetch,
    config,
    feedback_pages as fp,
    feedback_store as fs,
    pages,
    worker,
)
from backend.focus import interpret

log = logging.getLogger("backend.feedback")
FETCH_MESSAGES = {
    "unsafe_or_unresolvable_url": "Адрес недоступен или не разрешён для загрузки.",
    "fetch_timeout": "Превышено время загрузки статьи.",
    "article_too_large": "Статья превышает допустимый размер.",
    "unsupported_content": "Нужна открытая HTML- или текстовая статья.",
    "fetch_failed": "Не удалось загрузить статью.",
}
SUMMARY_LIMIT = 6000  # characters of an article that enter analytics; the whole text stays in the state as the source


class Blocked(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(code)
        self.code, self.message = code, message


def classifier_context(page: dict, context: dict) -> dict:
    selected = context["id"]
    link = pages.find(page["links"], selected)
    near = {selected} | ({link["from"], link["to"]} if link else set())
    ordered = sorted(page["widgets"], key=lambda w: w["id"] not in near)[:80]
    ids = {w["id"] for w in ordered}
    return {
        "selected": context,
        "company": page["company"],
        "widgets": [
            {
                "id": w["id"],
                "column": w["column"],
                "title": w["title"][:200],
                **({"url": w["url"]} if w.get("url") else {}),
            }
            for w in ordered
        ],
        "links": [
            {"id": l["id"], "from": l["from"], "to": l["to"]}
            for l in page["links"]
            if {l["from"], l["to"]} <= ids
        ][:160],
    }


def parameters(row: dict, state: dict):
    """(analytics profile, search query, focus) with the perspective in force."""
    profile, company, region = worker.prepare_profile(
        row["company"], row["company_id"], row["role"], row["region"]
    )
    line = state["effective"].get("line", row["role"])
    region = state["effective"].get("region", region)
    profile["region"] = region
    return (
        profile,
        {
            "company": company,
            "line": line,
            "region": region,
            "method": row["method"],
            "anonymised": bool(row["company_id"]),
        },
        interpret(line),
    )


def analyse(row: dict, state: dict, news: list[dict]) -> dict:
    profile, _, focus = parameters(row, state)
    inputs = [{**n, "summary": (n.get("summary") or "")[:SUMMARY_LIMIT]} for n in news]
    return worker._post(
        f"{config.ANALYTICS_URL}/page",
        {
            "profile": profile,
            "role": focus.role or "CFO",
            "sphere": focus.sphere,
            "news": inputs,
            "pairs": [],
        },
        "analytics",
    )


def ask_question(page: dict, state: dict, payload: dict):
    context = payload["context"]
    if context["type"] == "widget":
        widget = pages.find(page["widgets"], context["id"])
        refs = set(state["widget_sources"].get(context["id"], []))
    else:  # a link or the whole page: the question is answered from the widgets it covers
        link = (
            pages.find(page["links"], context["id"])
            if context["type"] == "link"
            else None
        )
        ids = {link["from"], link["to"]} if link else {w["id"] for w in page["widgets"]}
        parts = [
            w["title"] + "\n" + (w.get("details") or {}).get("text", "")
            for w in page["widgets"]
            if w["id"] in ids
        ]
        widget = {
            "id": context["id"],
            "title": link["text"] if link else "Вся страница",
            "details": {"text": "\n\n".join(parts)[:20000]},
        }
        refs = {r for wid in ids for r in state["widget_sources"].get(wid, [])}
    answer = worker._post(
        f"{config.ANALYTICS_URL}/reply",
        {
            "question": payload["message"],
            "widget": widget,
            "facts": page.get("meta", {}).get("facts", ""),
        },
        "analytics",
    )
    return {
        "text": str(answer.get("text", "")),
        "basis": answer.get("basis", []),
        "followups": [],
    }, fp.public_sources(state, refs)


def search_more(row: dict, page: dict, state: dict, intent: dict):
    """Допоиск через /refine: он всегда идёт методом dense_xquad, каким бы методом посчитан профиль. Returns (found, the user's article or None)."""
    if any(
        not state["widget_sources"].get(w["id"])
        for w in page["widgets"]
        if w["column"] == "news"
    ):
        raise Blocked(
            "sources_refresh_required",
            "Для этой страницы не сохранены источники. Обновите профиль.",
        )
    kind, article = intent["kind"], None
    if kind == "perspective":
        _, original, _ = parameters(row, {"effective": {}})
        for k in ("line", "region"):
            if intent[k]:
                state["effective"][k] = intent[k]
    _, query, _ = parameters(row, state)
    shown = {
        state["sources"][r]["aid"]
        for r in fp.shown_refs(page, state)
        if state["sources"].get(r, {}).get("aid") is not None
    }
    body = {
        **query,
        "method": "dense_xquad",
        "kind": {"extend": "topic"}.get(kind, kind),
        "text": intent["text"] or query["line"],
        "exclude_aids": sorted(shown),
        "removed_aids": state["removed_aids"],
    }
    if kind == "perspective":
        body.update(
            text=" ".join(x for x in (intent["line"], intent["region"]) if x),
            page_line=original["line"],
            page_region=original["region"],
        )
    if kind == "link":
        known = next(
            (
                s
                for s in state["sources"].values()
                if intent["url"] in (s["link"], s["original_url"])
            ),
            None,
        )
        article = copy.deepcopy(known) if known else article_fetch.fetch(intent["url"])
        if article["ref"] in fp.shown_refs(page, state):
            return None, article
        state["removed_refs"] = [
            r for r in state["removed_refs"] if r != article["ref"]
        ]
        state["removed_urls"] = [
            u
            for u in state["removed_urls"]
            if u not in (article["link"], article["original_url"])
        ]
        state["sources"][article["ref"]] = fp.source_of(article, "human")
        body["text"] = article["title"] + "\n" + article["summary"][:SUMMARY_LIMIT]
    return worker._post(
        f"{config.NEWS_SEARCH_URL}/refine", body, "news_search"
    ), article


def revise(row: dict, old: dict, state: dict, intent: dict, target: dict | None):
    """Additional analytics (#28): POST analytics/revise gets the user's wording or proposal with the page and returns widgets, links and updates."""
    profile, _, focus = parameters(row, state)
    body = {
        "kind": intent["kind"],
        "profile": profile,
        "role": focus.role or "CFO",
        "sphere": focus.sphere,
        "text": intent["text"],
        "target": target,
        "page": {
            "widgets": [
                {
                    "id": w["id"],
                    "column": w["column"],
                    "title": w["title"],
                    "text": (w.get("details") or {}).get("text", ""),
                    "source": w.get("tags", {}).get("source"),
                }
                for w in old["widgets"]
            ],
            "links": [{"from": l["from"], "to": l["to"]} for l in old["links"]],
        },
        "sources": fp.public_sources(
            state,
            {
                r
                for w in old["widgets"]
                for r in state["widget_sources"].get(w["id"], [])
            },
        ),
    }
    try:
        rev = worker._post(f"{config.ANALYTICS_URL}/revise", body, "analytics")
    except worker.ProfileError as e:
        if "HTTP 404" in str(e) or "unreachable" in str(e):
            raise Blocked(
                "analytics_unavailable",
                "Дополнительный анализ сейчас недоступен. Страница не изменена.",
            ) from e
        raise
    try:
        page = fp.apply_revision(row["key"], old, rev)
    except (ValueError, TypeError, AttributeError) as e:
        raise Blocked(
            "analytics_bad_response",
            "Аналитика вернула ответ в неверном формате. Страница не изменена.",
        ) from e
    reply = rev.get("reply") or {}
    return page, {
        "text": str(reply.get("text") or "Анализ добавлен."),
        "basis": [b for b in reply.get("basis", []) if isinstance(b, str)][:6],
        "followups": [],
    }


def mutate(row: dict, old: dict, state: dict, intent: dict):
    """(new page, reply or None)."""
    kind, target = intent["kind"], intent["target_id"]
    page = copy.deepcopy(old)
    if kind == "proposal":
        return revise(row, old, state, intent, None)
    if kind == "remove":
        if not state["widget_sources"].get(target):
            widget = pages.find(page["widgets"], target)
            if widget.get("url"):
                state["removed_urls"].append(widget["url"])
        fp.remove(page, state, target)
        return page, None
    if kind == "edit":
        widget = pages.find(page["widgets"], target)
        fp.edit_widget(page, state, target, intent["text"])
        if widget["column"] == "news" and not any(
            l["from"] == target for l in page["links"]
        ):
            return (
                page,
                None,
            )  # nothing is built on this news item: the new wording is all there is to change
        return revise(
            row, page, state, intent, pages.find(page["widgets"], target)
        )  # conclusions built on it are reviewed by analytics
    found, article = search_more(row, old, state, intent)
    if found is None:
        return page, None  # the article is already on the page
    manual = {
        r for m in state["manual_ids"] for r in state["widget_sources"].get(m, [])
    }  # shown by the user's own widgets, not analysed again
    pinned = (
        [s for s in state["sources"].values() if s["origin"] == "human"]
        if kind == "perspective"
        else []
    )
    news = [
        n
        for n in fp.allowed(
            [*([article] if article else []), *pinned, *found["top"]], state
        )
        if fp.ref_of(n) not in manual
    ]
    if not news:
        raise Blocked(
            "no_news", "Новых подходящих новостей не нашлось. Страница не изменена."
        )
    for n in news:
        state["sources"].setdefault(fp.ref_of(n), fp.source_of(n))
    # shortcut: search pair indexes refer to the search list, not to this subset, so pairs are not passed; analytics finds its own links.
    edited = fp.compose(
        row["key"],
        old,
        analyse(row, state, news),
        news,
        state,
        replace=kind == "perspective",
    )
    if article and fp.ref_of(article) not in fp.shown_refs(
        edited, state
    ):  # analytics may find nothing to conclude from the article: say so
        return edited, {
            "text": "Статья загружена, но выводов для вашей компании из неё аналитика не сделала.",
            "basis": [],
            "followups": [],
        }
    return edited, None


def failure(intent, code: str, message: str) -> dict:
    return {
        "scenario": {"kind": intent["kind"], "reason": intent["reason"]}
        if intent
        else None,
        "error": {"code": code, "message": message},
        "reply": {"text": message, "basis": [], "followups": []},
        "patch": None,
        "changes": [],
        "sources": [],
    }


def process(op: dict) -> tuple[dict, str, dict | None, dict | None]:
    """(result, status, new page, new state) of one operation."""
    row, payload = fs.profile(op["profile_key"]), op["payload"]
    page = row["page"]
    if row["status"] != "ready" or page["version"] != payload["page_version"]:
        raise fs.Conflict("page changed before processing")
    state = fp.initial_state(page, existing=row["feedback_state"])
    inputs = {
        "message": payload["message"],
        "context": classifier_context(page, payload["context"]),
    }
    intent = Agents(config.AGENTS_URL).run("feedback_intent", inputs)
    ids = {w["id"] for w in page["widgets"]}
    if (
        intent.get("target_id") and intent["target_id"] not in ids
    ):  # the agents service already checks; the page may be newer
        intent = {
            **intent,
            "kind": "clarify",
            "clarification": "Не нашёл этот блок на странице. Уточните, о каком блоке речь.",
        }
    result = {
        "session_id": payload["session_id"],
        "scenario": {"kind": intent["kind"], "reason": intent["reason"]},
        "version": page["version"],
        "patch": None,
        "changes": [],
        "sources": [],
    }
    try:
        if intent["kind"] == "clarify":
            return (
                {
                    **result,
                    "reply": {
                        "text": intent["clarification"],
                        "basis": [],
                        "followups": [],
                    },
                },
                "needs_clarification",
                None,
                None,
            )
        if intent["kind"] == "question":
            reply, sources = ask_question(page, state, payload)
            return (
                {**result, "reply": reply, "sources": sources},
                "completed",
                None,
                None,
            )
        edited, reply = mutate(row, page, state, intent)
    except Blocked as e:
        return {**result, **failure(intent, e.code, e.message)}, "blocked", None, None
    edited["version"] = page["version"] + 1
    ops, changes = fp.diff(page, edited)
    if not ops:
        return (
            {
                **result,
                "reply": {
                    "text": "Страница уже содержит это, изменений нет.",
                    "basis": [],
                    "followups": [],
                },
            },
            "completed",
            None,
            None,
        )
    refs = {
        r for w in edited["widgets"] for r in state["widget_sources"].get(w["id"], [])
    }
    result.update(
        version=edited["version"],
        patch={
            "base_version": page["version"],
            "version": edited["version"],
            "ops": ops,
        },
        changes=changes,
        sources=fp.public_sources(state, refs),
        reply=reply or {"text": "Изменения сохранены.", "basis": [], "followups": []},
    )
    return result, "completed", edited, state


def run_once() -> bool:
    op = fs.take()
    if op is None:
        return False
    try:
        result, status, page, state = process(op)
        fs.complete(op, result, status, page, state)
    except fs.Conflict:
        fs.complete(
            op,
            failure(
                None,
                "page_conflict",
                "Страница изменилась. Обновите её и повторите запрос.",
            ),
            "conflict",
        )
    except article_fetch.FetchError as e:
        fs.complete(
            op,
            failure(
                None,
                "article_fetch_failed",
                FETCH_MESSAGES.get(str(e), FETCH_MESSAGES["fetch_failed"])
                + " Страница не изменена.",
            ),
            "failed",
        )
    except Exception:
        log.exception("feedback operation %s failed", op["id"])
        fs.complete(
            op,
            failure(
                None, "processing_failed", "Запрос не выполнен. Страница не изменена."
            ),
            "failed",
        )
    return True


def run_forever(stop: threading.Event) -> None:
    since_cleanup = 0
    while not stop.is_set():
        try:
            if run_once():
                continue
            since_cleanup += 1
            if since_cleanup >= 1200:  # about an hour of idle seconds
                since_cleanup = 0
                fs.cleanup()
        except Exception:
            log.exception("feedback worker step failed")
        stop.wait(1)
