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
2. Скопируйте [.env.example](../.env.example) в `.env` в корне репозитория и впишите `LLM_API_KEY`; адреса шлюзов `LLM_BASE_URL` и `LLM_BASE_URL_BACKUP`, модель коллектора `COLLECTOR_LLM_MODEL` и метод поиска уже заданы, `POSTGRES_PASSWORD` — буквы и цифры. `LLM_ENABLED=false` выключает теги и геотеги коллектора (сбор без расходов); `TAGGING_ENABLED=false` выключает только дорогое тегирование, геотеги остаются.
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

### Снимок: дамп и векторы вместе

Чтобы первый поиск не встраивал весь корпус, вместе с дампом переносится `vectors_bgem3.npz`. Векторы привязаны к `articles.id` и верны только с дампом той же базы: у базы, собранной коллектором заново, id другие, и поиск молча сопоставит не те векторы. В git файлы не лежат (`*.dump` и `*.npz` в `.gitignore`, файл векторов больше 100 МБ) — они в релизе GitHub [`snapshot-2026-10-26`](https://github.com/one-zero-eight/hackathon-alfafuture/releases/tag/snapshot-2026-10-26): `alfa-2026-10-26b.dump` (37 МБ, 141 317 статей), `vectors_bgem3-2026-10-26b.npz` (290 МБ), `SHA256SUMS`.

**1. Скачать** в папку `snapshot/` в корне репозитория.

С `gh` (нужен `gh auth login` с доступом к репозиторию):

```bash
gh release download snapshot-2026-10-26 -R one-zero-eight/hackathon-alfafuture -D snapshot
```

Без `gh`, через `curl`. Репозиторий закрытый, поэтому нужен токен GitHub с правом чтения репозитория (classic с `repo` или fine-grained с `Contents: read`) в `GITHUB_TOKEN`:

```bash
mkdir -p snapshot && cd snapshot
R=one-zero-eight/hackathon-alfafuture TAG=snapshot-2026-10-26
curl -fsS -H "Authorization: Bearer $GITHUB_TOKEN" "https://api.github.com/repos/$R/releases/tags/$TAG" \
  | python3 -c 'import json,sys; [print(a["id"], a["name"]) for a in json.load(sys.stdin)["assets"]]' \
  | while read id name; do curl -fsSL -o "$name" -H "Authorization: Bearer $GITHUB_TOKEN" -H "Accept: application/octet-stream" "https://api.github.com/repos/$R/releases/assets/$id"; done
cd ..
```

Без `gh` и без токена: откройте страницу релиза в браузере под учётной записью с доступом к репозиторию и скачайте три файла в `snapshot/`. Если репозиторий станет открытым, подойдут и прямые ссылки `https://github.com/one-zero-eight/hackathon-alfafuture/releases/download/snapshot-2026-10-26/<файл>` (`curl -fLO` без токена).

Проверить целостность: `(cd snapshot && shasum -a 256 -c SHA256SUMS)`.

**2. Развернуть.** Быстрее всего — собирать образы, пока качается снимок (шаг 3 в [README](../README.md)), затем:

```bash
docker compose --env-file .env -f docker/compose.yaml up -d --wait postgres
docker compose --env-file .env -f docker/compose.yaml exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-owner --clean --if-exists' < snapshot/alfa-2026-10-26b.dump
docker compose --env-file .env -f docker/compose.yaml up -d --build --wait
docker compose --env-file .env -f docker/compose.yaml cp snapshot/vectors_bgem3-2026-10-26b.npz news_search:/data/vectors_bgem3.npz
docker compose --env-file .env -f docker/compose.yaml restart news_search   # фоновое встраивание начнёт с восстановленного файла
```

`--clean --if-exists` позволяет восстановить и в базу, которую коллектор уже успел создать. Проверка: `select count(*) from articles` — около 141 300. Если ключ в `.env` повторяется, действует последнее значение.

При `docker/up.sh` на macOS `news_search` работает на хосте, и файл кладётся в `.run/search_data/vectors_bgem3.npz`.

Снять новый снимок (сначала дамп, потом векторы — тогда в векторах нет статей, которых нет в дампе) и выложить его новым релизом `snapshot-<дата>`:

```bash
mkdir -p snapshot
docker compose --env-file .env -f docker/compose.yaml exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > snapshot/alfa.dump
docker compose --env-file .env -f docker/compose.yaml cp news_search:/data/vectors_bgem3.npz snapshot/vectors_bgem3.npz
```

Замер 2026-10-26 (MacBook, Docker без GPU, кэш сборки тёплый): скачивание снимка из релиза 18–21 с, восстановление дампа 1 с, старт стека 22 с, копирование векторов 1 с. Первый профиль был готов через 22 мин: вызовы LLM поиска ~2 мин, скачивание bge-m3 и встраивание 4 348 статей новее снимка ~15 мин, аналитика ~4,5 мин. Теперь модель и новые статьи `news_search` берёт фоново сразу после старта, а не в первом поиске. Сборка без кэша не замерялась.

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
