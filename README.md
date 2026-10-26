# Аналитика новостей для бизнес-решений (Альфа-Хак)

Агентная система: собирает новости, подбирает их под бизнес пользователя и объясняет, что они значат для его решений (выводы, риски, вопросы), с трассировкой до источников.

- Архитектура и правила: [docs/architecture.md](docs/architecture.md)
- Запуск всего стека: [docs/docker.md](docs/docker.md)
- Разделы: [сбор](docs/collector.md), [агенты](docs/agents.md), [поиск новостей](docs/news-search.md), [аналитика](docs/analytics.md), [backend](docs/backend.md), [frontend](docs/frontend.md)

## Тестовый стенд
https://alfa-news.alo.quest

## Быстрый старт

```bash
cp .env.example .env        # задайте POSTGRES_PASSWORD, LLM_API_KEY, LLM_BASE_URL
docker compose --env-file .env -f docker/compose.yaml up -d --build
open http://127.0.0.1:3000
```

Правила работы над проектом (для людей и ИИ-агентов): [AGENTS.md](AGENTS.md).
