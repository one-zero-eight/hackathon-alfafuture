# Аналитика новостей для бизнес-решений

Go backend собирает RSS РБК, «Коммерсанта» и Банка России, сохраняет новости
в PostgreSQL и автоматически тегирует их разрешённой моделью из фиксированного
словаря. Другие модули читают статьи, теги, события и состояние через HTTP.

## Запуск через Docker Compose

Нужны Docker Engine и Docker Compose с поддержкой BuildKit. Команды выполняются
из корня репозитория:

```sh
cp .env.example .env
```

В локальном `.env` задайте ключ организатора, пароль БД и такой же пароль
в `DATABASE_URL`. В URL пароль нужно percent-encode, если он содержит специальные
символы. Хост БД внутри Compose — `postgres`, имя БД и пользователь — `news`.
Не добавляйте `.env` в Git.

```sh
docker compose config --quiet
docker compose up --build --detach --wait
```

Запуск сразу включает сбор и **платное автоматическое тегирование**.
HTTP опубликован на `127.0.0.1:8080`; PostgreSQL не публикует порт на хосте.
Интерактивная документация: [http://127.0.0.1:8080/docs](http://127.0.0.1:8080/docs).
Её JS/CSS загружаются с внешнего CDN; интерфейс рассчитан на desktop,
на узком мобильном экране фиксированная sidebar мешает чтению.

```sh
curl --fail-with-body http://127.0.0.1:8080/readyz
curl --fail-with-body http://127.0.0.1:8080/v1/status
curl --fail-with-body 'http://127.0.0.1:8080/v1/news?limit=20'
curl --fail-with-body http://127.0.0.1:8080/v1/tags
docker compose logs --tail=50 news
```

Остановка сохраняет данные в именованном volume:

```sh
docker compose down
```

Перезапуск использует прежние статьи, cutoff источников, результаты и бюджетную
паузу. Не удаляйте volume для обычной остановки. Изменение пароля в `.env`
не меняет пароль уже инициализированной БД; данные требуют отдельного управления.

## Запуск Go без контейнера приложения

Нужны Go 1.27.3 и PostgreSQL. Настройки этого режима находятся в `backend/.env`,
отдельно от корневого `.env` Compose:

```sh
cd backend
cp .env.example .env
# Настройте DATABASE_URL и LLM_API_KEY перед запуском.
go run ./cmd/news
```

## Проверки и контракт

Из `backend/`, с отдельной тестовой БД, пользователь которой может создавать схемы:

```sh
TEST_DATABASE_URL='postgres://news_test:news_test@127.0.0.1:55432/news_test?sslmode=disable' go test -count=1 ./...
go vet ./...
go build ./...
```

Без `TEST_DATABASE_URL` PostgreSQL-проверки явно пропускаются. При выключенных
live-флагах тесты не вызывают API организатора и издателей. Команды временной БД, race-проверок
и отдельного ограниченного LLM smoke test описаны в документации сервиса.

Экспорт OpenAPI не требует настроек, БД или ключа:

```sh
# Из backend/:
go run ./cmd/news -openapi > /tmp/news-openapi.json
```

- [Контракт HTTP, конфигурация, алгоритмы и проверки](docs/news-service.md)
- [Фиксированный словарь тегов и правила назначения](docs/tag-vocabulary.md)

Состав Compose: только реализованный сервис `news` и его PostgreSQL. Граф,
ранжирование, PDF и UI подключаются владельцами модулей отдельно.
