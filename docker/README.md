# docker — сборка и запуск

Все Dockerfile, `compose.yaml` и конфиг nginx. Контекст сборки — корень репозитория. Подробно: [docs/docker.md](../docs/docker.md).

| Файл | Что внутри |
|---|---|
| `compose.yaml` | семь сервисов и Postgres |
| `<раздел>.Dockerfile`, `ml.Dockerfile` | образы; `ml.Dockerfile` общий для news_search и analytics (один torch) |
| `nginx.conf` | раздаёт фронт, `/api` пересылает бэкенду |
| `check.sh` | проверка совместимости всех разделов перед коммитом |

```bash
docker compose --env-file .env -f docker/compose.yaml up -d --build
docker/check.sh      # тесты, сборка всех образов, запуск без портов и проверка связей
```
