"""The only place in the project that calls the organizer's LLM gateway.

Streaming chat (long reasoning answers drop non-streaming connections on this gateway), main gateway then backup,
approved models only, JSON answers with retries, token and cost accounting.
"""
import json
import os
import re
import threading
import time

import httpx

APPROVED = {
    "google/gemma-4-26b-a4b-it",
    "z-ai/glm-5.3-flash",
    "qwen/qwen3.6-35b-a3b",
    "deepseek/deepseek-v4.1-flash",
    "qwen/qwen3-vl-30b-a3b-instruct",
    "moonshotai/kimi-k2.6",
}
BUDGET_STEP, BUDGET_CAP = 1200, 4000


class LLMError(RuntimeError):
    pass


class Usage:
    """Totals since start, per agent name (thread-safe)."""

    def __init__(self):
        self.lock = threading.Lock()
        self.by_agent: dict[str, dict] = {}

    def add(self, agent: str, usage: dict) -> None:
        with self.lock:
            row = self.by_agent.setdefault(agent, {"calls": 0, "tokens": 0, "cost": 0.0})
            row["calls"] += 1
            row["tokens"] += int(usage.get("total_tokens") or 0)
            row["cost"] += float(usage.get("cost") or 0)

    def snapshot(self) -> dict:
        with self.lock:
            total = {"calls": 0, "tokens": 0, "cost": 0.0}
            for row in self.by_agent.values():
                for k in total:
                    total[k] += row[k]
            return {"total": total, "by_agent": {k: dict(v) for k, v in self.by_agent.items()}}


USAGE = Usage()


def _bases() -> list[str]:
    bases = [b.rstrip("/") for b in (os.environ.get("LLM_BASE_URL"), os.environ.get("LLM_BASE_URL_BACKUP")) if b]
    if not bases or not os.environ.get("LLM_API_KEY"):
        raise LLMError("LLM_API_KEY and LLM_BASE_URL must be set")
    return bases if len(bases) > 1 else bases * 2  # one gateway: a second try on the same one


def chat(model: str, content, max_tokens: int, read_timeout: float = 600) -> tuple[str, dict]:
    """One streamed completion. content is a prompt string or a list of message parts (text, image_url)."""
    if model not in APPROVED:
        raise ValueError(f"model {model!r} is not on the organizer-approved list")
    body = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens,
            "stream": True, "stream_options": {"include_usage": True}}
    timeout, err = httpx.Timeout(30.0, read=read_timeout), None
    for base in _bases():
        text, usage = "", {}
        try:
            with httpx.stream("POST", base + "/chat/completions", json=body, timeout=timeout,
                              headers={"Authorization": "Bearer " + os.environ["LLM_API_KEY"]}) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line.startswith("data:") or line.endswith("[DONE]"):
                        continue
                    event = json.loads(line[5:])
                    usage = event.get("usage") or usage
                    for choice in event.get("choices", []):
                        text += (choice.get("delta") or {}).get("content") or ""
            return text, usage
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            err = e
    raise LLMError(f"LLM {model} failed: {err!r}")


def next_budget(budget: int, usage: dict) -> int:
    """A reasoning model can spend the whole completion cap on thinking and return no content: give the next try more room."""
    reasoning = int(((usage or {}).get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
    completion = int((usage or {}).get("completion_tokens") or 0)
    if reasoning and completion and reasoning >= completion - 5:
        return min(budget + BUDGET_STEP, max(BUDGET_CAP, budget))
    return budget


def json_call(agent: str, model: str, prompt: str, *, key: str | None = None, tries: int = 3, max_tokens: int = 32000,
              read_timeout: float = 600, images: list[str] | None = None) -> dict:
    """Ask for a JSON object; retry empty, truncated or malformed answers. key: a field that must be present and non-empty."""
    content = prompt
    if images:  # data-URLs
        content = [{"type": "text", "text": prompt}, *({"type": "image_url", "image_url": {"url": u}} for u in images)]
    budget, err = max_tokens, "no JSON object in the answer"
    for _ in range(tries):
        text, usage = chat(model, content, budget, read_timeout)
        USAGE.add(agent, usage)
        match = re.search(r"\{.*\}", text, re.S)
        try:
            if match:
                answer = json.loads(match.group(0))
                if isinstance(answer, dict) and (key is None or answer.get(key)):
                    return answer
                err = f"missing {key!r}"
        except json.JSONDecodeError as e:
            err = repr(e)
        budget = next_budget(budget, usage)
    raise LLMError(f"{model} gave no valid JSON for {agent}: {err}")
