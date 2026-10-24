# 2. Агенты (Python-сервис `agents`)

Единственное место, где Python-код обращается к LLM организаторов (Go-тегирование в `collector` — отдельное исключение). Код: [agents/](../agents/). Задача сервиса: принять имя агента и данные, собрать запрос, вызвать нужную модель, вернуть проверенный JSON.

## Что делает, шаг за шагом

1. Вызывающий сервис шлёт `POST /agents/{имя}` с `{"input": {...}}`.
2. Сервис проверяет, что агент существует (иначе 404) и что есть все обязательные поля (иначе 422).
3. Шаблон запроса `agents/prompts/<имя>.md` заполняется данными: подставляются только `{поля}` из входа, фигурные скобки примеров JSON остаются как есть.
4. Запрос уходит модели потоковым вызовом (длинные ответы с рассуждениями рвут обычные соединения): сначала основной шлюз, при ошибке резервный. Модель должна быть в списке разрешённых организаторами, иначе вызов отклоняется до сети.
5. Из ответа берётся JSON-объект. Если он пустой, обрезан или в нём нет нужного ключа, запрос повторяется (до 3 раз); если модель потратила весь лимит токенов на рассуждения, лимит следующей попытки увеличивается.
6. Результат приводится к ожидаемому виду (например, `pick` оставляет только известные номера) и возвращается вместе с расходом: вызовы, токены, стоимость.

## Агенты

| Имя | Модель | Вход | Выход | Кто вызывает |
|---|---|---|---|---|
| `queries` | DeepSeek-V4.1-Flash | `company`, `line`, `region?` | блоки поисковых запросов (11 блоков, ключ `company_self` обязателен) | news_search |
| `needs` | DeepSeek | `company`, `line`, `region?` | `{"needs": [20 вопросов]}` | news_search |
| `hyde` | DeepSeek | `company`, `line`, `region?` | `{"headlines": [40 заголовков]}` | news_search |
| `pick` | GLM-5.3-Flash | `company`, `line`, `candidates`, `top?` | `{"top": [номера]}` | news_search (`dense_llm`) |
| `analytics_step` | DeepSeek | `company`, `kinds`, `title`, `thoughts`, `materials`, `facts?`, `sphere?`, `text?` | одно рассуждение с цитатой | analytics |
| `decision` | DeepSeek | `role`, `moves`, `title`, `notes`, `sphere?` | решение с рисками | analytics |
| `verify` | Qwen3.6 35B | `claims` | `{"verdicts": [...]}` | analytics |
| `reply` | DeepSeek | `question`, `title?`, `text?`, `risks?`, `facts?` | ответ на вопрос по разбору | analytics |
| `alfa_page` | Qwen3-VL 30B | `page`, `text?`, `images?` | тезисы страницы PDF | `python -m analytics.alfa` |

Список с моделями и полями отдаёт `GET /agents`.

## Как добавить агента

1. Положите шаблон в `agents/prompts/<имя>.md` с плейсхолдерами `{поле}`.
2. Добавьте запись в `AGENTS` в [registry.py](../agents/registry.py): модель, обязательные поля, функцию сборки запроса, ключ, который должен быть в ответе, лимит токенов.
3. Допишите вход в тест `test_every_agent_builds_a_prompt_from_minimal_input`.

## Как пользоваться из другого сервиса

```python
from agents.client import Agents
agents = Agents()                      # адрес берётся из AGENTS_URL
out = agents.run("hyde", {"company": "Делимобиль", "line": "Закупки"})
print(out["headlines"][:3], agents.cost)   # agents.cost, agents.tokens, agents.calls копятся по экземпляру
```

`agents/client.py` копируется в образы news_search и analytics рядом с их кодом.

## Настройки и проверка

Переменные: `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_BASE_URL_BACKUP` (из корневого `.env`).

```bash
curl -s localhost:8001/agents | python3 -m json.tool
curl -s -X POST localhost:8001/agents/hyde -H 'Content-Type: application/json' -d '{"input":{"company":"Делимобиль","line":"Закупки"}}'
curl -s localhost:8001/usage        # расход с запуска сервиса, по агентам
uv run pytest agents   # офлайн, без сети
```

## Ограничения

- Расход по запросу считается как разница суммарных счётчиков агента, поэтому при параллельных вызовах одного агента он может включать чужие вызовы.
- Бюджет (500 ₽ в сутки) сервис не ограничивает, только считает: `GET /usage`.
