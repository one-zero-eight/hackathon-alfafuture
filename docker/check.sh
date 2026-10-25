#!/usr/bin/env bash
# Compatibility check of every section for the final application build. Run before each commit:  docker/check.sh
# Needs Docker, uv, Go and Node. Uses throwaway containers and a throwaway compose project; nothing is published on host ports.
set -euo pipefail
cd "$(dirname "$0")/.."
step() { printf '\n==> %s\n' "$*"; }
tmp=$(mktemp -d)
cleanup() {
  docker rm -f alfa-check-testdb >/dev/null 2>&1 || true
  [ -f "$tmp/override.yaml" ] && docker compose -p alfa-check -f docker/compose.yaml -f "$tmp/override.yaml" down -v >/dev/null 2>&1 || true
  rm -rf "$tmp"
}
trap cleanup EXIT

step "test database"
docker run -d --name alfa-check-testdb -e POSTGRES_USER=news_test -e POSTGRES_PASSWORD=news_test -e POSTGRES_DB=news_test \
  -p 127.0.0.1::5432 postgres:18.6-alpine >/dev/null
until docker exec alfa-check-testdb pg_isready -U news_test -d news_test >/dev/null 2>&1; do sleep 1; done
port=$(docker port alfa-check-testdb 5432/tcp | head -1 | sed 's/.*://')
export TEST_DATABASE_URL="postgres://news_test:news_test@127.0.0.1:${port}/news_test?sslmode=disable"

step "python: lock is current, tests of agents, news_search, analytics, backend"
uv lock --check
uv sync --all-packages --quiet
uv run pytest -q

step "collector (Go): vet and tests"
(cd collector && go vet ./... && go test -count=1 ./...)

step "frontend: tests and build"
(cd frontend && npm ci --silent && npm test && npm run build)

step "compose: build every image and start the stack (collector LLM off, no host ports)"
export POSTGRES_PASSWORD=check LLM_ENABLED=false
{ echo "services:"; for s in postgres collector agents news_search analytics backend frontend; do echo "  $s: {ports: !override []}"; done; } > "$tmp/override.yaml"
dc() { docker compose -p alfa-check -f docker/compose.yaml -f "$tmp/override.yaml" "$@"; }
dc config --quiet
dc build
dc up -d --wait --wait-timeout 300
step "smoke: UI API through the frontend proxy, backend -> postgres"
dc exec -T frontend wget -qO- http://127.0.0.1/api/page | grep -q '"widgets"'
dc exec -T agents python -c "import urllib.request as u; assert b'queries' in u.urlopen('http://127.0.0.1:8000/agents').read()"
dc exec -T news_search python -c "import urllib.request as u; assert b'dense_xquad' in u.urlopen('http://127.0.0.1:8000/methods').read()"

step "smoke: persistent journal through the frontend proxy (no LLM)"
dc exec -T backend python - <<'PYTHON'
import json
import urllib.request as u

def request(url, body=None, capability=None):
    headers = {"Content-Type": "application/json"}
    if capability:
        headers["X-Trace-Capability"] = capability
    req = u.Request(url, data=json.dumps(body).encode() if body is not None else None, headers=headers)
    with u.urlopen(req, timeout=10) as response:
        return json.load(response)

base = "http://127.0.0.1:8000/internal/trace/runs"
run = request(base, {"kind": "news_search", "company_ref": "0" * 64})
request(base + "/" + run["run_id"] + "/events", {"event": {"section": "news_search", "step": "ranking", "counts": {"selected": 1}, "source_ids": ["article:1"]}}, run["capability"])
request(base + "/" + run["run_id"] + "/finish", {"status": "completed", "incomplete": False}, run["capability"])
public = request("http://frontend/api/runs/" + run["run_id"])
assert public["status"] == "completed" and not public["incomplete"]
assert any(e["counts"].get("selected") == 1 for e in public["events"])
assert "capability" not in json.dumps(public) and "usage" not in json.dumps(public)
print("journal persisted and read through frontend proxy")
PYTHON

printf '\nAll sections are compatible.\n'
