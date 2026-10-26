FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.9 /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 UV_PROJECT_ENVIRONMENT=/opt/venv PATH=/opt/venv/bin:$PATH
# The workspace needs every member's pyproject.toml to resolve the lock; only one package's dependencies are installed.
COPY pyproject.toml uv.lock ./
COPY agents/pyproject.toml agents/pyproject.toml
COPY news_search/pyproject.toml news_search/pyproject.toml
COPY analytics/pyproject.toml analytics/pyproject.toml
COPY backend/pyproject.toml backend/pyproject.toml
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-dev --no-install-project --package alfa-backend
COPY agents/__init__.py agents/client.py /app/agents/
COPY backend /app/backend
HEALTHCHECK --interval=10s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/health', timeout=3)"]
CMD ["uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8000"]
