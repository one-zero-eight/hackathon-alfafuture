# Build context: v1/ (ingest.py reuses the feed/Google News helpers of pipeline.py).
FROM python:3.13-slim
RUN apt-get update && apt-get install -y --no-install-recommends curl ca-certificates && rm -rf /var/lib/apt/lists/*
WORKDIR /app
RUN pip install --no-cache-dir numpy "psycopg[binary]==3.3.*"
COPY ingest.py pipeline.py lib.py ./
COPY outlets50.json outlets_new.json topics_extra.txt ./
RUN mkdir cache && echo '{}' > cache/gn.json
CMD ["python", "-u", "ingest.py", "loop"]
