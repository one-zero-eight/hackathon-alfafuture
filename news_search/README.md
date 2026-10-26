# news_search — поиск новостей под профиль

Класс `NewsSearch` и HTTP-обёртка. Методы: `lexical`, `dense_llm`, `dense_xquad`; допоиск `refine` к показанной странице (только `dense_xquad`). Подробно: [docs/news-search.md](../docs/news-search.md).

| Файл | Что внутри |
|---|---|
| `search.py` | класс `NewsSearch`: три метода, допоиск `refine`, фильтр новостей о самой компании |
| `scoring.py` | свежесть, xQuAD, связки, слияние рангов |
| `dedup.py` | склейка дубликатов |
| `text.py` | токены и лексическое совпадение |
| `cache.py` | кэш шагов и результатов поиска в таблице `search_cache` (PostgreSQL) и его версия в памяти для тестов |
| `embed.py` | кодировщики и кэш векторов статей |
| `corpus.py` | чтение корпуса из Postgres |
| `app.py` | HTTP: `POST /search`, `POST /refine`, `GET /methods` |
| `benchmarks/` | сравнение методов; замер допоиска (`refine_bench.py`); A/B параметров компании (`personalization_ab.py`, отчёт `personalization-ab.md`) |
| `levels.py` | уровень новости: свой регион, чужой регион, федеральный, зарубежный |

```bash
uv sync --all-packages
TEST_DATABASE_URL=postgres://… uv run pytest news_search
```
