# agents — вызовы LLM

Единственное место, где Python-код обращается к LLM организаторов. Подробно: [docs/agents.md](../docs/agents.md).

| Файл | Что внутри |
|---|---|
| `app.py` | HTTP: `POST /agents/{имя}`, `GET /agents`, `GET /usage`, `GET /health` |
| `registry.py` | девять агентов: модель, обязательные поля, сборка запроса, проверка ответа |
| `llm.py` | потоковый клиент шлюза, резервный шлюз, список разрешённых моделей, учёт расхода |
| `client.py` | клиент для других сервисов (копируется в их образы) |
| `prompts/` | шаблоны запросов, `{поле}` подставляется из входа |
| `benchmarks/` | отчёты о стоимости и качестве |

```bash
uv sync --all-packages
uv run pytest agents                                   # офлайн
uv run uvicorn agents.app:app --port 8001              # нужны LLM_API_KEY и LLM_BASE_URL в окружении
```

Новый агент — это новый шаблон в `prompts/` и запись в `registry.py`, существующие не переписываются.
