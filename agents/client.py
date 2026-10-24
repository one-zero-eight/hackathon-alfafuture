"""Client of the agents service for the other Python services (copied next to them in their images)."""
import os
import threading

import httpx


class AgentError(RuntimeError):
    pass


class Agents:
    """agents.run("hyde", {...}) -> output dict. calls/tokens/cost add up over the instance's lifetime."""

    def __init__(self, url: str | None = None, timeout: float = 1800):
        self.url = (url or os.environ.get("AGENTS_URL", "http://agents:8000")).rstrip("/")
        self.timeout = timeout
        self.calls, self.tokens, self.cost = 0, 0, 0.0
        self._lock = threading.Lock()

    def run(self, name: str, data: dict) -> dict:
        try:
            r = httpx.post(f"{self.url}/agents/{name}", json={"input": data}, timeout=self.timeout)
        except httpx.HTTPError as e:
            raise AgentError(f"agents service unreachable: {e!r}") from e
        if r.status_code != 200:
            raise AgentError(f"agent {name}: HTTP {r.status_code}: {r.text[:300]}")
        body = r.json()
        with self._lock:
            self.calls += body["usage"]["calls"]
            self.tokens += body["usage"]["tokens"]
            self.cost += body["usage"]["cost"]
        return body["output"]
