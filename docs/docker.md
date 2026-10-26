# 7. Docker

Все Dockerfile и compose лежат в [docker/](../docker/). Контекст сборки каждого образа — корень репозитория; лишнее исключает корневой [.dockerignore](../.dockerignore).

## Сервисы

| Сервис | Образ | Порт на хосте | Что делает |
|---|---|---|---|
| `postgres` | postgres 18.6 | 127.0.0.1:5433 | общая БД: корпус новостей и профили |
| `collector` | [collector.Dockerfile](../docker/collector.Dockerfile) (Go) | 127.0.0.1:8080 | сбор, теги ([collector.md](collector.md)) |
| `agents` | [agents.Dockerfile](../docker/agents.Dockerfile) | 127.0.0.1:8001 | вызовы LLM ([agents.md](agents.md)) |
| `news_search` | [ml.Dockerfile](../docker/ml.Dockerfile) | 127.0.0.1:8002 | поиск новостей ([news-search.md](news-search.md)) |
| `analytics` | [ml.Dockerfile](../docker/ml.Dockerfile) (общий образ) | 127.0.0.1:8003 | аналитика и решения ([analytics.md](analytics.md)) |
| `backend` | [backend.Dockerfile](../docker/backend.Dockerfile) | 127.0.0.1:8000 | оркестрация и API ([backend.md](backend.md)) |
| `frontend` | [frontend.Dockerfile](../docker/frontend.Dockerfile) | 127.0.0.1:3000 | интерфейс |

Тома: `postgres_data` (корпус), `hf_cache` (модели эмбеддеров, около 4,5 ГБ), `search_data` (кэши поиска и векторы статей), `analytics_data` (тезисы банка). Сервисы `news_search` и `analytics` используют один общий образ `alfa-ml` (torch ставится один раз; по умолчанию CPU-версия). Python-зависимости ставит uv по `uv.lock`.

## Подготовка

1. Docker с Compose v2 и 8 ГБ памяти для Docker (эмбеддеры).
2. Скопируйте [.env.example](../.env.example) в `.env` в корне репозитория: `POSTGRES_PASSWORD` (буквы и цифры), `LLM_API_KEY`, `LLM_BASE_URL`, при желании `LLM_BASE_URL_BACKUP`. `LLM_ENABLED=false` выключает теги и геотеги коллектора (сбор без расходов).
3. Для профилей по `company_id` положите файлы организаторов `df_Uid_data_hack.csv` и `df_Uid_payment_hack.csv` в локальную папку, которую `docker/compose.yaml` монтирует в `/company` сервиса `backend`; PDF Альфа-Банка — в папку, монтируемую в `/papers`. Пути заданы в `volumes` compose-файла; в git эти файлы не входят.

## Запуск

```bash
docker compose --env-file .env -f docker/compose.yaml up -d --build
docker compose --env-file .env -f docker/compose.yaml ps        # все сервисы Up, healthy
open http://127.0.0.1:3000
```

## Проверка

```bash
curl -s localhost:3000/api/page | python3 -m json.tool | head -20                      # демо-страница
curl -s localhost:8080/v1/status                                                         # collector
curl -s localhost:8001/agents | python3 -m json.tool | head                              # agents
curl -s localhost:8002/methods                                                           # news_search
curl -s -X POST localhost:3000/api/profile -H 'Content-Type: application/json' -d '{"company":"Делимобиль","role":"Глава найма"}'
curl -s localhost:3000/api/profile/<key>                                                 # queued -> running -> ready
curl -s "localhost:3000/api/page?profile=<key>"
docker compose --env-file .env -f docker/compose.yaml logs -f backend news_search analytics
```

Первый расчёт профиля занимает минуты (поиск по корпусу, десятки вызовов LLM), а при методах `dense_*` ещё и скачивание моделей. Метод поиска выбирается переменной `NEWS_SEARCH_METHOD` в `.env`.

## Готовый корпус из дампа (по желанию)

Если есть дамп корпуса, сделанный `pg_dump -Fc` версией 18 (статьи, источники, региональные метки), загрузите его в пустую БД **до** запуска остальных сервисов; коллектор потом дополнит схему сам:

```bash
docker compose --env-file .env -f docker/compose.yaml up -d postgres
docker exec -i alfa-postgres-1 pg_restore -U news -d news --no-owner --exit-on-error < <файл-дампа>
docker compose --env-file .env -f docker/compose.yaml up -d
```

Пароль БД применяется только при создании тома `postgres_data`: если том уже создан с другим `POSTGRES_PASSWORD`, смените пароль в `.env` на прежний или удалите том.

Если порты 3000, 5433, 8000–8003 или 8080 заняты, добавьте второй файл compose с `ports: !override [...]` для нужных сервисов (`-f docker/compose.yaml -f мой-порты.yaml`).

## Остановка

```bash
docker compose --env-file .env -f docker/compose.yaml down        # данные сохраняются в томах
docker compose --env-file .env -f docker/compose.yaml down -v     # ВНИМАНИЕ: удалит корпус новостей и модели
```

## Запуск на быстром устройстве

`docker/up.sh` сам выбирает устройство и запускает стек:

1. **NVIDIA GPU** (`nvidia-smi` видит карту): `docker/compose.gpu.yaml` собирает `ml.Dockerfile` с `TORCH_BACKEND=cu126`. После `uv sync` по `uv.lock` в образ ставится CUDA-колесо `torch` той же версии, контейнерам `news_search` и `analytics` выдаётся GPU. Нужны драйвер и nvidia-container-toolkit на хосте. cu126 выбран, потому что он поддерживает V100 (sm_70); работу на V100 ещё не проверяли.
2. **macOS**: Docker на Mac не видит GPU Apple, поэтому `news_search` не поднимается в контейнере: скрипт запускает его на хосте через `uv run` (устройство MPS, логи в `.run/news_search.log`, векторы в `.run/search_data`), а `docker/compose.mac.yaml` направляет бэкенд на `host.docker.internal:8002`.
3. **Иначе** обычный запуск на CPU.

Остановка: `docker/up.sh down`. На GPU `news_search/embed.py` дополнительно переводит модель в fp16 (`model.half()`), на CUDA берёт пачки по 128 текстов.

## Доставка событий запуска (#29)

Backend-образ теперь включает `agents/client.py` и `agents/tracing.py`; ML-образ — также модуль трассировки. В Compose `TRACE_BACKEND_URL=http://backend:8000` задан сервисам agents/news_search/analytics. Для news_search на хосте macOS `docker/up.sh` задаёт `http://localhost:8000`. Циклических `depends_on` не добавлено: недоступность журнала не блокирует расчёт и отмечается как неполнота.

`TRACE_AI_ENABLED` (по умолчанию false) одинаково передаётся backend и agents. Включать его можно только после подтверждения валюты шлюза и доступного дневного бюджета. Маршруты `/internal/trace/*` не проксируются nginx; backend остаётся доступен с хоста только через loopback. Не публикуйте служебный порт без аутентификации. Реальные вызовы LLM для проверки журнала не нужны: `uv run python -m backend.benchmarks.journal_smoke` использует отдельную тестовую БД, фикстуры моделей и реальные HTTP/curl.

Для #26 backend-образ дополнительно копирует `agents/feedback.py` (схему классификатора); новых зависимостей и переменных окружения нет. Полный стек проверяется прежним `docker/check.sh`. Автономный HTTP/curl smoke обратной связи: `TEST_DATABASE_URL=… uv run python -m backend.benchmarks.feedback_smoke`, только с отдельной тестовой PostgreSQL.
