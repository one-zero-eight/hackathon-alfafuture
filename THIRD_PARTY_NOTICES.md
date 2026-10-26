# Сторонние компоненты

Полные деревья зависимостей: `uv.lock`, `collector/go.sum`, `frontend/package-lock.json`. Ниже то, что вызывается напрямую.

## Модели

Генеративные модели только из списка организаторов, через их шлюз (`LLM_BASE_URL`). Эмбеддеры в этот список не входят и качаются с Hugging Face.

| Модель | Где | Зачем |
|---|---|---|
| `google/gemma-4-26b-a4b-it` | agents `analytics_step`, коллектор | шаг аналитики, теги, геометки |
| `deepseek/deepseek-v4.1-flash` | agents `decision`, `queries`, `needs`, `hyde`, `reply` | решение и запросы поиска |
| `qwen/qwen3.6-35b-a3b` | agents `verify` | вторая проверка вывода |
| `z-ai/glm-5.3-flash` | agents `pick` | выбор новостей в методе `dense_llm` |
| `qwen/qwen3-vl-30b-a3b-instruct` | agents `alfa_page` | тезисы со слайдов PDF |
| `moonshotai/kimi-k2.6` | разрешена, в коде по умолчанию не вызывается | — |
| `BAAI/bge-m3` | news_search, analytics | векторы статей и ближайший тезис банка |
| `intfloat/multilingual-e5-large-instruct` | news_search, метод `dense_llm` | второй эмбеддер |

Цены шлюза на 1 млн токенов (вход / выход), как их назвали организаторы: Gemma 4,48 / 23 ₽, GLM 5,10 / 17 ₽, Qwen3.6 5,33 / 74 ₽, DeepSeek 10 / 21 ₽, Qwen3-VL 14,30 / 57,10 ₽, Kimi 51 / 270 ₽. Токены рассуждения считаются как выход.

## Библиотеки

Python (uv, Python ≥ 3.13): FastAPI 0.156.8, httpx 0.28.1, uvicorn 0.54.0, pypdf 6.1.3, sentence-transformers 6.2.0, torch (индекс pytorch-cpu), psycopg 3.3, numpy, pytest 9.1.1.

Go 1.27: gin 1.12, huma 2.39, gofeed 1.5, openai-go 3.85, godotenv 1.5, snowball 0.10, gorm 1.31 и драйвер Postgres 1.6.

Фронтенд: React 19.3, Vite 8.3, TypeScript 7, Vitest 5.

## Данные и сервисы

- CSV организаторов `df_Uid_data_hack.csv`, `df_Uid_payment_hack.csv` и PDF аналитики Альфа-Банка. В git не лежат, монтируются в контейнеры.
- RSS из `collector/sources.json` и выдача Google News. Обход сайтов целиком не делается.
- Postgres 18.6 в compose. Шлюз LLM организаторов. Hugging Face — только чтобы скачать эмбеддеры.

Готовой агентной платформы нет. Вызовы модели идут через `agents` (httpx) и через клиент OpenAI в коллекторе.

Демо-страница без профиля собирается из фикстуры бэкенда, это не внешний сервис.
