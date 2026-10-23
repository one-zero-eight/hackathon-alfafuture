# Build context: the repository root (the server reuses ../mock_server unchanged).
FROM python:3.13-slim
WORKDIR /app
COPY mock_server/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt "psycopg[binary]==3.3.*"
COPY mock_server /app/mock_server
COPY v1/server/main.py /app/main.py
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
