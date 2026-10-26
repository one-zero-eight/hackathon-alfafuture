# backend — оркестрация и API интерфейса

Хранит профили и страницы, строит страницу вызовом `news_search` и `analytics`, отвечает фронту. Контракт и настройки: [docs/backend.md](../docs/backend.md).

| Файл | Что внутри |
|---|---|
| `app.py` | эндпоинты `/api/*`, чат, фоновый поток |
| `journal.py`, `journal_api.py` | журнал запусков/событий, публичный API, срок хранения и описания по запросу |
| `feedback.py`, `feedback_api.py` | очередь обратной связи, распознавание, вызовы сервисов, polling и undo |
| `feedback_store.py` | операции PostgreSQL, атомарные версии и последние 20 ревизий |
| `feedback_pages.py` | композиция страницы, происхождение, удаление зависимостей и исключения |
| `article_fetch.py` | безопасная загрузка публичной статьи в профиль с закреплением IP и лимитами |
| `worker.py` | очередь обратной связи и один профиль: карточка компании → поиск → аналитика → страница |
| `store.py` | таблица `profiles`, очередь, этап и счётчики новостей, кэш на сутки |
| `pages.py` | скелет страницы и поиск виджетов; прежние демо-заготовки не используются маршрутом чата |
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

Обратная связь #26: сообщения `POST /api/chat` получают HTTP 202 и operation_id; `GET /api/feedback/{id}` отдаёт результат, `POST /api/profile/{key}/undo` восстанавливает страницу и состояние новой версией. Контекст page использует ключ профиля. Допоиск только dense_xquad, пересмотр решений/предложений ждёт #28. Фронтенду #25 ещё нужны polling и серверный undo. Классификатор — Gemma через agents; его живое качество пока не измерено.

```bash
TEST_DATABASE_URL='postgres://…' PYTHONHASHSEED=0 uv run python -m backend.benchmarks.feedback_smoke
uv run python -m agents.benchmarks.feedback_intents  # только проверка 80 примеров, без LLM
```
