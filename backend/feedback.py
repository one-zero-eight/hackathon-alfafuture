"""Feedback orchestration. Existing services own retrieval and analytical algorithms."""
import copy
import logging
import uuid

from agents import tracing
from agents.client import Agents
from agents.feedback import validate
from backend import article_fetch, config, feedback_pages as fp, feedback_store as fs, journal, pages
from backend.focus import interpret

log = logging.getLogger("backend.feedback")


class Blocked(RuntimeError):
    def __init__(self, code, message):
        self.code, self.message = code, message


def post(path, body, service):
    from backend import worker
    base = config.NEWS_SEARCH_URL if service == "news_search" else config.ANALYTICS_URL
    return worker._post(base + path, body, service)


def classifier_context(page, context):
    selected = context["id"]
    link = pages.find(page["links"], selected)
    primary = {selected} | ({link["from"], link["to"]} if link else set())
    ordered = sorted(page["widgets"], key=lambda w: w["id"] not in primary)[:80]
    ids = {w["id"] for w in ordered}
    return {"selected": context, "company": page["company"],
            "widgets": [{k: (w[k][:200] if k == "title" else w[k]) for k in ("id", "column", "title", "url") if k in w} for w in ordered],
            "links": [{k: link[k] for k in ("id", "from", "to")} for link in page["links"] if {link["from"], link["to"]} <= ids][:160]}


def ensure_sources(page, state):
    if any(not state["widget_sources"].get(w["id"]) for w in page["widgets"] if w["column"] == "news"):
        raise Blocked("sources_refresh_required", "Для старой страницы не сохранились номера источников. Сначала обновите профиль.")


def parameters(row, state):
    from backend.worker import prepare_profile
    profile, company, region = prepare_profile(row["company"], row["company_id"], row["role"], row["region"])
    line = state["effective"].get("line", row["role"])
    region = state["effective"].get("region", region)
    focus = interpret(line)
    return profile, {"company": company, "line": line, "region": region, "method": row["method"], "anonymised": bool(row["company_id"])}, focus


def analyse(row, state, news, pairs=()):
    profile, query, focus = parameters(row, state)
    profile["region"] = query["region"]
    # The complete fetched text is retained as a source; only a bounded excerpt enters analytics.
    inputs = [{**item, "summary": item.get("summary", "")[:6000]} for item in news]
    return post("/page", {"profile": profile, "role": focus.role or interpret(row["role"]).role or "CFO", "sphere": focus.sphere,
                           "news": inputs, "pairs": list(pairs)}, "analytics")


def selected_refs(page, state, context):
    if context["type"] == "page":
        ids = {w["id"] for w in page["widgets"]}
    elif context["type"] == "link":
        link = pages.find(page["links"], context["id"])
        ids = {link["from"], link["to"]}
    else:
        ids = {context["id"]}
    return {ref for wid in ids for ref in state["widget_sources"].get(wid, [])}


def question(page, state, payload):
    context = payload["context"]
    if context["type"] == "widget":
        widget = pages.find(page["widgets"], context["id"])
    else:
        ids = {w["id"] for w in page["widgets"]}
        title = "Вся страница"
        if context["type"] == "link":
            link = pages.find(page["links"], context["id"])
            ids, title = {link["from"], link["to"]}, link["text"]
        parts = [w["title"] + "\n" + w.get("details", {}).get("text", "") for w in page["widgets"] if w["id"] in ids]
        widget = {"id": context["id"], "title": title, "details": {"text": "\n\n".join(parts)[:20000]}}
    answer = post("/reply", {"question": payload["message"], "widget": widget, "facts": page.get("meta", {}).get("facts", "")}, "analytics")
    sources = fp.public_sources(state, selected_refs(page, state, context))
    return {"text": str(answer.get("text", "")), "basis": [s["title"] for s in sources], "followups": []}, sources


def allowed_news(items, state):
    seen, kept = set(), []
    for item in items:
        if item.get("source_id") in state["removed_sources"] or item.get("aid") in state["removed_aids"] or item.get("link") in state["removed_urls"]:
            continue
        identity = item.get("link") or item.get("source_id") or item.get("aid")
        if identity not in seen:
            seen.add(identity)
            kept.append(item)
    return kept


def rebuild(row, old, state, found):
    pinned = [s for s in state["sources"].values() if s.get("origin") == "human"]
    news = allowed_news([*pinned, *found["top"]], state)
    if not news:
        raise Blocked("no_news", "После применения исключений не осталось новостей. Страница сохранена.")
    # Reordering/exclusions invalidate search pair indexes; omit them rather than invent relationships.
    raw = analyse(row, state, news)
    return fp.compose(row["key"], old, raw, news, state, replace=True)


def mutate(row, old, state, intent):
    kind = intent["kind"]
    target = intent.get("target_id")
    if kind == "proposal":
        raise Blocked("analytics_dependency_unavailable", "Оценка пользовательского предложения требует аналитики #28. Страница не изменена.")
    if kind == "edit":
        widget = pages.find(old["widgets"], target)
        if widget is None or widget["column"] != "news" or any(l["from"] == target for l in old["links"]):
            raise Blocked("analytics_dependency_unavailable", "Правка требует пересмотра аналитики и решений (#28). Страница не изменена.")
        edited = copy.deepcopy(old)
        widget = pages.find(edited["widgets"], target)
        widget["details"] = {**widget.get("details", {}), "text": intent["text"]}
        widget["chat"] = {"text": intent["text"], "basis": [], "followups": []}
        widget["tags"] = {**widget.get("tags", {}), "source": "human", "confidence": "possible"}
        ref = "user:" + uuid.uuid4().hex
        state["sources"][ref] = {"source_id": ref, "title": widget["title"], "link": widget.get("url", ""),
                                 "summary": intent["text"], "origin": "human", "outlets": [],
                                 "original_sources": state["widget_sources"].get(target, [])}
        state["widget_sources"][target] = [ref]
        if target not in state["manual_ids"]:
            state["manual_ids"].append(target)
        return edited
    if kind == "remove":
        edited = copy.deepcopy(old)
        fp.remove(edited, state, target)
        return edited
    if kind == "perspective":
        for key in ("line", "region"):
            if intent.get(key) is not None:
                state["effective"][key] = intent[key]
    if not intent["refresh"] and row["method"] != "dense_xquad":
        raise Blocked("unsupported_search_method", "Допоиск доступен только для dense_xquad. Настроенный метод не изменён.")
    ensure_sources(old, state)
    _, query, _ = parameters(row, state)
    if intent["refresh"]:
        found = post("/search", query, "news_search")
        return rebuild(row, old, state, found)
    shown = [state["sources"].get(ref, {}).get("aid") for w in old["widgets"] if w["column"] == "news" for ref in state["widget_sources"].get(w["id"], [])]
    body = {**query, "kind": "topic" if kind == "extend" else kind, "text": intent["text"] or query["line"],
            "exclude_aids": sorted({aid for aid in shown if aid}), "removed_aids": state["removed_aids"]}
    if kind == "perspective":
        _, original, _ = parameters(row, fs.profile(row["key"])["feedback_state"] or fp.initial_state(old))
        body.update(page_line=original["line"], page_region=original["region"])
        found = post("/refine", body, "news_search")
        return rebuild(row, old, state, found)
    article = None
    if kind == "link":
        existing = [s for s in state["sources"].values() if intent["url"] in (s.get("link"), s.get("original_url"))]
        if existing and any(existing[0]["source_id"] in state["widget_sources"].get(w["id"], []) for w in old["widgets"] if w["column"] == "news"):
            return copy.deepcopy(old)
        article = copy.deepcopy(existing[0]) if existing else article_fetch.fetch(intent["url"])
        active_refs = {ref for w in old["widgets"] if w["column"] == "news" for ref in state["widget_sources"].get(w["id"], [])}
        if any(state["sources"].get(ref, {}).get("link") == article["link"] for ref in active_refs):
            return copy.deepcopy(old)
        state["sources"][article["source_id"]] = article
        state["removed_sources"] = [ref for ref in state["removed_sources"] if ref != article["source_id"]]
        state["removed_urls"] = [url for url in state["removed_urls"] if url not in (article["link"], article.get("original_url"))]
        body["text"] = article["title"] + "\n" + article["summary"][:6000]
    found = post("/refine", body, "news_search")
    news = allowed_news(([article] if article else []) + found["top"], state)
    if not news:
        raise Blocked("no_news", "Дополнительных новостей не найдено. Страница не изменена.")
    raw = analyse(row, state, news)
    return fp.compose(row["key"], old, raw, news, state)


def run_once():
    operation = fs.take()
    if operation is None:
        return False
    trace = journal.safe_context(operation["run_id"]) if operation["run_id"] else None
    if trace is None:
        trace = tracing.Trace(uuid.uuid4().hex, "", "backend", sender=lambda event: (_ for _ in ()).throw(RuntimeError("journal unavailable")), incomplete=True)
    intent = None
    try:
        with tracing.activate(trace), tracing.span("chat"):
            row = fs.profile(operation["profile_key"])
            page, payload = row["page"], operation["payload"]
            if row["status"] != "ready" or page["version"] != payload["page_version"]:
                raise fs.Conflict("page changed before processing")
            state = fp.initial_state(page, row["feedback_state"])
            context = classifier_context(page, payload["context"])
            inputs = {"message": payload["message"], "context": context}
            intent = validate(Agents(config.AGENTS_URL).run("feedback_intent", inputs), inputs)
            result = {"session_id": payload["session_id"], "run_id": operation["run_id"],
                      "scenario": {"kind": intent["kind"], "reason": intent["reason"]}, "patch": None, "page": None, "changes": [], "sources": []}
            if intent["kind"] == "clarify":
                result["reply"] = {"text": intent["clarification"], "basis": [], "followups": []}
                fs.complete(operation, result, status="needs_clarification")
            elif intent["kind"] == "question":
                result["reply"], result["sources"] = question(page, state, payload)
                fs.complete(operation, result)
            else:
                edited = mutate(row, page, state, intent)
                fp.compact(edited, state)
                edited["version"] = page["version"] + 1
                patch, summary = fp.changes(page, edited)
                result.update(patch=patch, page=pages.skeleton(edited), changes=summary,
                              sources=fp.public_sources(state, {r for w in edited["widgets"] for r in state["widget_sources"].get(w["id"], [])}),
                              reply={"text": "Изменения сохранены." if summary else "Новость уже есть на странице.", "basis": [], "followups": []})
                if summary or edited["company"] != page["company"] or state != row["feedback_state"]:
                    with tracing.span("publication", widget_ids=[w["id"] for w in edited["widgets"]][:200]):
                        fs.complete(operation, result, edited, state)
                else:
                    result.update(patch=None, page=None)
                    fs.complete(operation, result)
        journal.safe_finish(operation["run_id"], "completed", trace.incomplete)
    except (Blocked, fs.Conflict) as error:
        status = "blocked" if isinstance(error, Blocked) else "conflict"
        code = error.code if isinstance(error, Blocked) else "page_conflict"
        message = error.message if isinstance(error, Blocked) else "Страница изменилась. Обновите её и повторите запрос."
        fs.complete(operation, {"scenario": {"kind": intent["kind"], "reason": intent["reason"]} if intent else None,
                                "error": {"code": code, "message": message}, "reply": {"text": message, "basis": [], "followups": []}, "patch": None, "changes": []}, status=status)
        journal.safe_finish(operation["run_id"], "failed", trace.incomplete)
    except article_fetch.FetchError as error:
        messages = {"unsafe_or_unresolvable_url": "Адрес недоступен или не разрешён для загрузки.",
                    "fetch_timeout": "Превышено время загрузки статьи.", "article_too_large": "Статья превышает допустимый размер.",
                    "unsupported_content": "Нужна доступная HTML- или текстовая статья без сжатия."}
        message = messages.get(str(error), "Не удалось загрузить и прочитать статью. Страница не изменена.")
        fs.complete(operation, {"scenario": {"kind": intent["kind"], "reason": intent["reason"]} if intent else None,
                                "error": {"code": "article_fetch_failed", "message": message}, "patch": None,
                                "reply": {"text": message, "basis": [], "followups": []}, "changes": []}, status="failed")
        journal.safe_finish(operation["run_id"], "failed", trace.incomplete)
    except Exception:
        log.warning("feedback failed operation=%s", operation["id"])
        fs.complete(operation, {"error": {"code": "processing_failed", "message": "Запрос не выполнен. Страница не изменена."}, "patch": None}, status="failed")
        journal.safe_finish(operation["run_id"], "failed", trace.incomplete)
    return True
