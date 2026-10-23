# Build context: v1/. CPU-only torch; models (~4.5 GB) are downloaded on the first run into the hf_cache volume.
FROM python:3.13-slim
WORKDIR /app
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu \
 && pip install --no-cache-dir sentence-transformers numpy "psycopg[binary]==3.3.*"
COPY pipeline.py lib.py analyze.py worker.py prompt.md ./
ENV HF_HOME=/hf_cache
CMD ["python", "-u", "worker.py"]
