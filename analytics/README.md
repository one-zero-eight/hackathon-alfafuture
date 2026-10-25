# analytics — новости → аналитика → решения

Для каждой отобранной новости строит цепочку с цитатами-доказательствами и проверкой. Подробно: [docs/analytics.md](../docs/analytics.md).

| Файл | Что внутри |
|---|---|
| `app.py` | HTTP: `POST /page`, `POST /reply`, `GET /health` |
| `chain.py` | план, шаги аналитики, решение, проверка, сборка страницы |
| `search.py` | лексический поиск по новостям страницы и тезисам банка |
| `embed.py` | bge-m3: ближайший тезис Альфа-Банка к заголовку |
| `alfa.py` | разбор PDF банка в тезисы (`python -m analytics.alfa`) |
| `data/roles.json` | правила решений для четырёх должностей |
| `benchmarks/` | отчёты о стоимости и качестве |

```bash
uv sync --all-packages
uv run pytest analytics                                # офлайн, агенты подменены
uv run python -m analytics.alfa /путь/к/pdf            # тезисы банка (тратит LLM)
```

Журнал (#29): `TRACE_BACKEND_URL` включает события обработки источников, решений и проверки; `/page` и `/reply` возвращают `X-Run-ID` и `X-Trace-Incomplete`. Контекст переносится в каждый поток цепочки и verify. JSON страницы сохранён, тексты мыслей/банковские факты в журнал не копируются. Контракт — в docs/analytics.md и docs/backend.md.
