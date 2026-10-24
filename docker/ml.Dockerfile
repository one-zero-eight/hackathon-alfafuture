# One image for news_search and analytics (both need CPU torch + bge-m3): torch is installed once. poppler reads image-only PDFs for analytics.alfa.
# CPU-only torch comes from [tool.uv.sources] in the root pyproject.toml; models (about 4.5 GB) are downloaded on first use into the hf_cache volume.
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /usr/local/bin/uv
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils && rm -rf /var/lib/apt/lists/*
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
# The workspace needs every member's pyproject.toml to resolve the lock; only the dependencies of news_search and analytics are installed.
COPY pyproject.toml uv.lock ./
COPY agents/pyproject.toml agents/pyproject.toml
COPY news_search/pyproject.toml news_search/pyproject.toml
COPY analytics/pyproject.toml analytics/pyproject.toml
COPY backend/pyproject.toml backend/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project --package alfa-news-search --package alfa-analytics
COPY agents/__init__.py agents/client.py /app/agents/
COPY news_search /app/news_search
COPY analytics /app/analytics
ENV HF_HOME=/hf_cache
HEALTHCHECK --interval=10s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=3)"]
