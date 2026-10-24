# collector — сбор новостей и теги (Go)

Читает ленты и Google News, пишет в Postgres, тегирует статьи по фиксированному словарю и ставит геотеги региона (Gemma). Подробно: [docs/collector.md](../docs/collector.md).

| Путь | Что внутри |
|---|---|
| `sources.json` | список изданий: id, имя, лента, сайт, тег региона |
| `topics.txt` | темы для Google News |
| `cmd/news` | точка входа; флаг `-backfill` загружает историю |
| `internal/news/collect` | три встроенных издания с полным текстом (РБК, «Коммерсантъ», ЦБ) |
| `internal/news/ingest` | остальные ленты и Google News |
| `internal/news/tagging`, `vocabulary` | тегирование и словарь тегов |
| `internal/news/geotag` | региональные теги |
| `internal/news/store`, `httpapi`, `feed`, `gnews`, `config` | БД, HTTP API, чтение лент, настройки |
| `llm/` | клиент LLM только для этого сервиса |
| `benchmarks/` | отчёты |

```bash
go vet ./... && TEST_DATABASE_URL=postgres://… go test -count=1 ./...
```
