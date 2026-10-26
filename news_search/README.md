# news_search — поиск новостей под профиль

Класс `NewsSearch` и HTTP-обёртка. Методы: `lexical`, `dense_llm`, `dense_xquad`; допоиск `refine` к показанной странице (только `dense_xquad`). Подробно: [docs/news-search.md](../docs/news-search.md).

| Файл | Что внутри |
|---|---|
| `search.py` | класс `NewsSearch`: три метода, допоиск `refine`, фильтр новостей о самой компании |
| `scoring.py` | свежесть, xQuAD, связки, слияние рангов |
| `dedup.py` | склейка дубликатов |
| `text.py` | токены и лексическое совпадение |
| `cache.py` | кэш шагов и результатов поиска в таблице `search_cache` (PostgreSQL) и его версия в памяти для тестов |
| `embed.py` | кодировщики и кэш векторов статей (новые статьи встраиваются частями по 1000, файл сохраняется после каждой части) |
| `corpus.py` | чтение корпуса из Postgres |
| `region.py`, `regions.json`, `regions_build.py` | регион новости без LLM (регион издания, названия регионов и городов) для доли федеральных новостей по размеру компании в `dense_xquad`; словарь пересобирается `python news_search/regions_build.py` |
| `app.py` | HTTP: `POST /search`, `POST /refine`, `GET /methods`; фоновое встраивание новых статей (`NEWS_SEARCH_EMBED_EVERY`) |
| `benchmarks/` | сравнение методов; замер допоиска и его драйвер `refine_bench.py`; регион и `locality` (`region-boost.md`, `region_boost_bench.py`); A/B параметров компании (`personalization_ab.py`, отчёт `personalization-ab.md`); холодный поиск и суточный поток новостей (`embedding-backlog.md`) |
| `levels.py` | уровень новости: свой регион, чужой регион, федеральный, зарубежный |

```bash
uv sync --all-packages
TEST_DATABASE_URL=postgres://… uv run pytest news_search
```
