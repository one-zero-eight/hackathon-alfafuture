"""Chat client for the organizer gateway: approved models only, streaming, JSON answers, call log with usage."""
import json
import os
import re
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
APPROVED = {
    "google/gemma-4-26b-a4b-it",
    "z-ai/glm-5.3-flash",
    "qwen/qwen3.6-35b-a3b",
    "deepseek/deepseek-v4.1-flash",
    "qwen/qwen3-vl-30b-a3b-instruct",
    "moonshotai/kimi-k2.6",
}


def next_budget(budget: int, usage: dict, cap: int = 4000) -> int:
    """DeepSeek can spend the whole completion cap on reasoning and return no content. Give the next try room for the JSON."""
    details = (usage or {}).get("completion_tokens_details") or {}
    reasoning = int(details.get("reasoning_tokens") or 0)
    completion = int((usage or {}).get("completion_tokens") or 0)
    if reasoning and completion and reasoning >= completion - 5:
        return min(budget + 1200, cap)
    return budget


def env() -> dict:
    cfg = {}
    for p in (ROOT / ".env", ROOT / "reasoning" / ".env"):
        if p.exists():
            cfg.update(l.strip().split("=", 1) for l in p.read_text().splitlines() if "=" in l and not l.startswith("#"))
    return {**cfg, **os.environ}


class LLM:
    """One instance per run; every call is appended to `log_path` (model, step, tokens, seconds) for budget tracking."""

    def __init__(self, log_path: Path | None = None):
        cfg = env()
        if not cfg.get("LLM_API_KEY") or not cfg.get("LLM_BASE_URL"):
            raise RuntimeError("LLM_API_KEY and LLM_BASE_URL must be set in .env or the environment")
        self.key, self.base = cfg["LLM_API_KEY"], cfg["LLM_BASE_URL"].rstrip("/")
        self.log_path = log_path
        self.calls, self.tokens = 0, 0
        self.last_usage = {}

    def chat(self, model: str, messages: list[dict], step: str, max_tokens: int = 16000, read_timeout: float = 90) -> str:
        if model not in APPROVED:
            raise ValueError(f"model {model!r} is not on the organizer-approved list")
        # Streaming: long reasoning answers drop non-streaming connections on this gateway (seen in v1/pipeline.py)
        body = {"model": model, "messages": messages, "max_tokens": max_tokens, "stream": True,
                "stream_options": {"include_usage": True}}
        # read=90: a silent stream used to sit until the process was killed (~1 h). Two tries, then fail.
        timeout = httpx.Timeout(30.0, read=read_timeout)
        err = None
        for _ in range(2):
            t0, text, usage = time.time(), "", {}
            try:
                with httpx.stream("POST", self.base + "/chat/completions", json=body, timeout=timeout,
                                  headers={"Authorization": f"Bearer {self.key}"}) as r:
                    r.raise_for_status()
                    for line in r.iter_lines():
                        if not line.startswith("data:") or line.endswith("[DONE]"):
                            continue
                        ev = json.loads(line[5:])
                        usage = ev.get("usage") or usage
                        for ch in ev.get("choices", []):
                            text += (ch.get("delta") or {}).get("content") or ""
                err = None
                break
            except httpx.HTTPError as e:
                err = e
        if err:
            raise RuntimeError(f"LLM {model} failed on {step}: {err!r}") from err
        self.calls += 1
        self.last_usage = usage
        self.tokens += int(usage.get("total_tokens") or 0)
        if self.log_path:
            rec = {"step": step, "model": model, "seconds": round(time.time() - t0, 1), "usage": usage}
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return text

    def json(self, model: str, prompt: str, step: str, tries: int = 3, max_tokens: int = 1200, images: list[str] | None = None, read_timeout: float = 90) -> dict:
        """Reasoning models sometimes return empty or truncated answers: retry until a JSON object parses.

        images: data-URLs. A large max_tokens makes reasoning models think for minutes, so callers keep it small.
        If the whole budget was spent on reasoning and the content is empty, the next try gets a larger budget.
        """
        content: str | list = prompt
        if images:
            content = [{"type": "text", "text": prompt},
                       *({"type": "image_url", "image_url": {"url": url}} for url in images)]
        err, budget = None, max_tokens
        for _ in range(tries):
            out = self.chat(model, [{"role": "user", "content": content}], step, max_tokens=budget, read_timeout=read_timeout)
            m = re.search(r"\{.*\}", out, re.S)
            try:
                if m:
                    return json.loads(m.group(0))
                err = "no JSON object in the answer"
            except json.JSONDecodeError as e:
                err = e
            budget = next_budget(budget, self.last_usage)
        raise RuntimeError(f"{model} gave no valid JSON for {step}: {err!r}")
