#!/usr/bin/env bash
# Starts the whole stack on the fastest device the machine has: NVIDIA GPU (CUDA image), Apple GPU (news_search on the host, MPS) or CPU.
# Usage: docker/up.sh [extra "docker compose up" args]. Stop: docker/up.sh down
set -euo pipefail
cd "$(dirname "$0")/.."
COMPOSE=(docker compose --env-file .env -f docker/compose.yaml)
RUN=.run; PID=$RUN/news_search.pid; mkdir -p $RUN

if [ "${1:-}" = down ]; then
  [ -f $PID ] && kill "$(cat $PID)" 2>/dev/null || true; rm -f $PID
  exec "${COMPOSE[@]}" down
fi

if command -v nvidia-smi >/dev/null 2>&1 && nvidia-smi -L >/dev/null 2>&1; then
  echo "device: NVIDIA GPU (CUDA image)"
  exec "${COMPOSE[@]}" -f docker/compose.gpu.yaml up -d --build "$@"
elif [ "$(uname -s)" = Darwin ]; then
  echo "device: Apple GPU (news_search on the host, MPS)"
  set -a; . ./.env; set +a
  "${COMPOSE[@]}" -f docker/compose.mac.yaml up -d --build --scale news_search=0 "$@"
  [ -f $PID ] && kill "$(cat $PID)" 2>/dev/null || true
  # Postgres and agents are published on the host ports of compose.yaml (5433, 8001)
  TRACE_BACKEND_URL=http://localhost:8000 DATABASE_URL="postgresql://${POSTGRES_USER:-news}:${POSTGRES_PASSWORD}@localhost:5433/${POSTGRES_DB:-news}" AGENTS_URL=http://localhost:8001 \
    NEWS_SEARCH_DATA="$PWD/$RUN/search_data" HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}" PYTORCH_ENABLE_MPS_FALLBACK=1 \
    nohup uv run --package alfa-news-search uvicorn news_search.app:app --port 8002 > $RUN/news_search.log 2>&1 &
  echo $! > $PID
  echo "news_search on the host: pid $(cat $PID), log $RUN/news_search.log"
else
  echo "device: CPU"
  exec "${COMPOSE[@]}" up -d --build "$@"
fi
