# backend — оркестрация и API интерфейса

Хранит профили и страницы, строит страницу вызовом `news_search` и `analytics`, отвечает фронту. Контракт и настройки: [docs/backend.md](../docs/backend.md).

| Файл | Что внутри |
|---|---|
| `app.py` | эндпоинты `/api/*`, чат, фоновый поток |
| `journal.py`, `journal_api.py` | журнал запусков/событий, публичный API, срок хранения и описания по запросу |
| `worker.py` | один профиль: карточка компании → поиск → аналитика → страница |
| `store.py` | таблица `profiles`, очередь, этап и счётчики новостей, кэш на сутки |
| `feedback.py`, `feedback_pages.py`, `feedback_store.py` | обратная связь (#26): очередь операций, распознавание и цепочки, состояние/источники/откат |
| `article_fetch.py` | безопасная загрузка статьи по ссылке пользователя |
| `pages.py` | скелет страницы, поиск виджетов, правки из чата |
| `companies.py` | карточка компании и список компаний из CSV банка |
| `focus.py` | разбор строки роли: должность, отрасль, тема |
| `config.py` | настройки; `NEWS_SEARCH_METHOD` выбирает метод поиска |
| `demo/seed.json` | демо-страница |
| `benchmarks/` | отчёты |

```bash
uv sync --all-packages
TEST_DATABASE_URL=postgres://… uv run pytest backend   # без переменной тесты с БД пропускаются
```

Журнал: `GET /api/runs/{run_id}`, `GET /api/profile/{key}/runs`, `POST /api/runs/{run_id}/descriptions`; ответы профиля дополнены `run_id`. Завершённые запуски хранятся 7 дней, промпты/сообщения чата в журнал не входят. Gemma-описания по запросу выключены (`TRACE_AI_ENABLED=false`) до подтверждения валюты и бюджета. Настройки и curl — в docs/backend.md.

Проверки на отдельной PostgreSQL без платного LLM:

```bash
TEST_DATABASE_URL=postgres://… uv run python -m backend.benchmarks.journal_smoke
TEST_DATABASE_URL=postgres://… PYTHONHASHSEED=0 uv run python -m backend.benchmarks.journal_bench
```
