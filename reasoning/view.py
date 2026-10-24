"""Terminal progress bar and a page that shows the news → effect → action chain."""


def bar(done: int, total: int, width: int = 24) -> str:
    n = round(width * done / total) if total else 0
    n = max(0, min(width, n))
    return "█" * n + "░" * (width - n)


def _by_id(page: dict) -> dict:
    return {w["id"]: w for w in page.get("widgets", [])}


def tree(page: dict) -> str:
    """One block per news item: the event, then the effect, then the action."""
    got = _by_id(page)
    lines = []
    for w in page.get("widgets", []):
        if w["column"] != "news":
            continue
        n = w["id"][1:]
        lines.append(w["title"][:90])
        ana, dec = got.get(f"a{n}"), got.get(f"d{n}")
        if ana:
            lines.append("  → " + ana.get("details", {}).get("text", "")[:220])
        if dec:
            lines.append("  → " + dec["title"])
        if not ana:
            lines.append("  → цепочка не собралась")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def html(page: dict) -> str:
    got = _by_id(page)
    rows = []
    for w in page.get("widgets", []):
        if w["column"] != "news":
            continue
        n = w["id"][1:]
        ana, dec = got.get(f"a{n}"), got.get(f"d{n}")
        rows.append(
            "<section>"
            f"<article><p>Новость</p><h2>{_esc(w['title'])}</h2><p>{_esc(w.get('details', {}).get('text', ''))}</p>{_pub(w)}</article>"
            "<div class=arrow>→</div>"
            f"<article><p>Что это значит</p><p>{_esc((ana or {}).get('details', {}).get('text') or 'цепочка не собралась')}</p>{_paper(ana)}</article>"
            "<div class=arrow>→</div>"
            f"<article><p>Действие</p><h2>{_esc((dec or {}).get('title') or '—')}</h2>"
            f"<p>{_esc((dec or {}).get('details', {}).get('text', ''))}</p>{_ask(dec)}</article>"
            "</section>"
        )
    body = "\n".join(rows) or "<p>Цепочек нет.</p>"
    return f"""<!doctype html>
<meta charset="utf-8">
<title>Причинная цепочка</title>
<style>
body {{ font: 16px/1.4 sans-serif; margin: 24px; background: #f4f1ea; color: #1c1a17; }}
h1 {{ font-size: 22px; }}
section {{ display: grid; grid-template-columns: 1.2fr 32px 1.3fr 32px 1fr; gap: 8px; align-items: stretch; margin: 0 0 16px; }}
article {{ background: #fff; border: 1px solid #ddd; padding: 12px 14px; }}
article p:first-child {{ margin: 0 0 6px; color: #6b6258; font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }}
h2 {{ font-size: 16px; margin: 0 0 8px; }}
.arrow {{ display: flex; align-items: center; justify-content: center; font-size: 22px; }}
</style>
<h1>Причинная цепочка: новость → последствие для компании → действие</h1>
{body}
"""


def _pub(w: dict) -> str:
    d = w.get("details") or {}
    text = ", ".join(x for x in (d.get("src"), d.get("date")) if x)
    return f"<p>Источник: {_esc(text)}</p>" if text else ""


def _paper(w: dict | None) -> str:
    url = (w or {}).get("url")
    return f'<p><a href="{_esc(url)}">Материал банка</a></p>' if url else ""


def _ask(w: dict | None) -> str:
    qs = ((w or {}).get("chat") or {}).get("followups") or []
    return f"<p>Уточнить: {_esc(qs[0])}</p>" if qs else ""


def _esc(text: str) -> str:
    return (str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
