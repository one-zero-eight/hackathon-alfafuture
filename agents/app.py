"""Agents service: POST /agents/{name} runs one named LLM task. Every LLM call of the project goes through here (the Go collector's tagging excepted).

An agent = prompts/<name>.md + a model + a row in AGENTS. {field} placeholders of the prompt are filled from the input, anything else is left as is.
Gateway: streamed chat (long reasoning answers drop plain connections), main base URL then backup, approved models only.
"""
import datetime
import json
import os
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agents.calllog import CALL, emit
from agents.feedback import validate as validate_intent

PROMPTS = Path(__file__).parent / "prompts"
GEMMA = "google/gemma-4-26b-a4b-it"
DEEPSEEK, GLM, QWEN, QWEN_VL = "deepseek/deepseek-v4.1-flash", "z-ai/glm-5.3-flash", "qwen/qwen3.6-35b-a3b", "qwen/qwen3-vl-30b-a3b-instruct"
APPROVED = {GEMMA, GLM, QWEN, DEEPSEEK, QWEN_VL, "moonshotai/kimi-k2.6"}
BUDGET_STEP, BUDGET_CAP = 1200, 4000


class LLMError(RuntimeError):
    pass


# ---- gateway ----

def chat(model: str, content, max_tokens: int, read_timeout: float = 600) -> tuple[str, dict]:
    """One streamed completion. content is a prompt string or a list of message parts (text, image_url)."""
    if model not in APPROVED:
        raise ValueError(f"model {model!r} is not on the organizer-approved list")
    bases = [b.rstrip("/") for b in (os.environ.get("LLM_BASE_URL"), os.environ.get("LLM_BASE_URL_BACKUP")) if b]
    if not bases or not os.environ.get("LLM_API_KEY"):
        raise LLMError("LLM_API_KEY and LLM_BASE_URL must be set")
    body = {"model": model, "messages": [{"role": "user", "content": content}], "max_tokens": max_tokens,
            "stream": True, "stream_options": {"include_usage": True}}
    err = None
    for base in bases if len(bases) > 1 else bases * 2:  # one gateway: a second try on the same one
        text, reasoning, finish, usage, started = "", "", None, {}, time.monotonic()
        try:
            with httpx.stream("POST", base + "/chat/completions", json=body, timeout=httpx.Timeout(30.0, read=read_timeout),
                              headers={"Authorization": "Bearer " + os.environ["LLM_API_KEY"]}) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line.startswith("data:") or line.endswith("[DONE]"):
                        continue
                    event = json.loads(line[5:])
                    usage = event.get("usage") or usage
                    for choice in event.get("choices", []):
                        delta = choice.get("delta") or {}
                        text += delta.get("content") or ""
                        reasoning += delta.get("reasoning_content") or delta.get("reasoning") or ""  # the field name depends on the gateway
                        finish = choice.get("finish_reason") or finish
            emit("gateway", ok=True, model=model, gateway=urlparse(base).netloc, ms=round((time.monotonic() - started) * 1000),
                 finish_reason=finish, usage=usage, reasoning=reasoning, content=text)
            return text, usage
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            err = e
            emit("gateway", ok=False, model=model, gateway=urlparse(base).netloc, ms=round((time.monotonic() - started) * 1000),
                 error=repr(e), finish_reason=finish, usage=usage, reasoning=reasoning, content=text)  # whatever arrived before the failure
    raise LLMError(f"LLM {model} failed: {err!r}")


def next_budget(budget: int, usage: dict) -> int:
    """A reasoning model can spend the whole completion cap on thinking and return no content: give the next try more room."""
    reasoning = int(((usage or {}).get("completion_tokens_details") or {}).get("reasoning_tokens") or 0)
    completion = int((usage or {}).get("completion_tokens") or 0)
    if reasoning and completion and reasoning >= completion - 5:
        return min(budget + BUDGET_STEP, max(BUDGET_CAP, budget))
    return budget


# ---- usage accounting ----

TOTALS: dict[str, dict] = {}  # per agent since start
LOCK = threading.Lock()


def count(name: str, usage: dict, into: dict) -> None:
    row = {"calls": 1, "tokens": int(usage.get("total_tokens") or 0), "cost": float(usage.get("cost") or 0)}
    with LOCK:
        for target in (into, TOTALS.setdefault(name, {"calls": 0, "tokens": 0, "cost": 0.0})):
            for k, v in row.items():
                target[k] = target.get(k, 0) + v


# ---- agents ----

def render(name: str, **fields) -> str:
    template = (PROMPTS / f"{name}.md").read_text(encoding="utf-8").rstrip("\n")
    return re.sub(r"\{(\w+)\}", lambda m: str(fields[m.group(1)]) if m.group(1) in fields else m.group(0), template)


def where(region: str) -> str:
    return f" Регион: «{region}»." if region else ""


def strings(values) -> list[str]:
    return [x.strip() for x in values if isinstance(x, str) and x.strip()]


def dump(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def today() -> str:
    return datetime.date.today().isoformat()


def facts_line(i: dict) -> str:
    return f"Факты из карточки банка: {i['facts']}" if i.get("facts") else ""


def pick_lines(i: dict) -> str:
    return "\n".join(f"{c['id']} | {str(c.get('date', ''))[:16]} | {', '.join(c.get('outlets', [])[:3])} | {c['title']}" for c in i["candidates"])


def pick_out(out: dict, i: dict) -> dict:
    ok = {c["id"] for c in i["candidates"]}
    return {"top": [int(e["id"]) for e in out["top"] if isinstance(e, dict) and str(e.get("id", "")).isdigit() and int(e["id"]) in ok]}


@dataclass
class Agent:
    model: str
    fields: tuple[str, ...]  # required input fields
    build: Callable[[dict], str]
    key: str | None = None  # output field that must be non-empty, else the call is retried
    max_tokens: int = 32000
    read_timeout: float = 600
    images: str | None = None  # input field holding data-URL images
    finish: Callable[[dict, dict], dict] = lambda out, inp: out  # normalise the answer


AGENTS: dict[str, Agent] = {
    "feedback_intent": Agent(GEMMA, ("message", "context"), lambda i: render("feedback_intent", message=i["message"], context=dump(i["context"])),
                             key="kind", max_tokens=1500, read_timeout=60, finish=validate_intent),
    # search side
    "queries": Agent(DEEPSEEK, ("company", "line"),
                     lambda i: render("queries", today=today(), company=i["company"] + where(i.get("region", "")), line=i["line"]),
                     key="company_self", finish=lambda out, _: {b: strings(v) for b, v in out.items() if isinstance(v, list)}),
    # an anonymised bank record: no name, so company_self stays empty and regional queries are required (#37)
    "queries_anonymised": Agent(DEEPSEEK, ("company", "line"),
                                lambda i: render("queries_anonymised", today=today(), company=i["company"] + where(i.get("region", "")), line=i["line"]),
                                key="competitors_direct", finish=lambda out, _: {b: strings(v) for b, v in out.items() if isinstance(v, list)}),
    # a native Alfa-Business tip shown while the page is being built; backend derives status and goal from the bank record (CL_TYPE, products)
    "ad_tip": Agent(GEMMA, ("company", "role", "status", "goal"),
                    lambda i: render("ad_tip", company=i["company"], role=i["role"], status=i["status"], goal=i["goal"]),
                    key="text", max_tokens=800, read_timeout=45, finish=lambda out, _: {"text": " ".join(str(out["text"]).split())}),
    "needs": Agent(DEEPSEEK, ("company", "line"), lambda i: render("needs", company=i["company"], where=where(i.get("region", "")), line=i["line"]),
                   key="needs", finish=lambda out, _: {"needs": strings(out["needs"])}),
    "hyde": Agent(DEEPSEEK, ("company", "line"), lambda i: render("hyde", company=i["company"], where=where(i.get("region", "")), line=i["line"]),
                  key="headlines", finish=lambda out, _: {"headlines": strings(out["headlines"])}),
    "pick": Agent(GLM, ("company", "line", "candidates"),
                  lambda i: render("pick", today=today(), company=i["company"], line=i["line"], top=i.get("top", 30), lines=pick_lines(i)),
                  key="top", finish=pick_out),
    # analytics side
    "analytics_step": Agent(GEMMA, ("company", "kinds", "title", "thoughts", "materials"),
                            lambda i: render("analytics_step", company=i["company"], facts_line=facts_line(i),
                                             sphere_line=f"Сфера анализа: {i['sphere']}. Пиши про неё, даже если слова введены с опечаткой." if i.get("sphere") else "",
                                             kinds=", ".join(i["kinds"]), title=i["title"], text=i.get("text", ""),
                                             thoughts=dump(i["thoughts"]), materials=i["materials"]),
                            max_tokens=2500, read_timeout=90),
    "decision": Agent(DEEPSEEK, ("role", "moves", "title", "notes"),
                      lambda i: render("decision", sphere_line=f"Сфера анализа: {i['sphere']}. Решение для этой сферы, по правилам роли." if i.get("sphere") else "",
                                       facts_line=facts_line(i),
                                       role_title=i["role"]["title"], role_authority=i["role"]["authority"], role_playbook=i["role"]["playbook"],
                                       moves="\n".join(f"- {k}: {v}" for k, v in i["moves"].items()) or "(ТРИЗ выключена — только правила роли)",
                                       title=i["title"], notes=dump(i["notes"])),
                      key="title", max_tokens=4000, read_timeout=90),
    "role_brief": Agent(DEEPSEEK, ("line", "fallback_title", "fallback_playbook"),
                        lambda i: render("role_brief", line=i["line"], fallback_title=i["fallback_title"], fallback_playbook=i["fallback_playbook"]),
                        key="playbook", max_tokens=1500, read_timeout=60),
    "verify": Agent(QWEN, ("claims",), lambda i: render("verify", claims=dump([{"text": c["text"], "quote": c["quote"]} for c in i["claims"]])),
                    key="verdicts", max_tokens=2000, read_timeout=90),
    "reply": Agent(DEEPSEEK, ("question",),
                   lambda i: render("reply", facts_line=facts_line(i), title=i.get("title", ""), text=i.get("text", ""),
                                    risks=dump(i.get("risks", [])), question=i["question"]),
                   key="text", max_tokens=1200, read_timeout=90),
    "alfa_page": Agent(QWEN_VL, (), lambda i: render("alfa_page", page_text=f"\n\nСТРАНИЦА {i['page']}:\n{i['text'][:6000]}" if i.get("text") else ""),
                       max_tokens=1200, read_timeout=120, images="images"),
    "synthesis": Agent(GEMMA, ("sphere", "materials"),
                       lambda i: render("synthesis", sphere=i["sphere"], materials=i["materials"]),
                       key="text", max_tokens=2500, read_timeout=90),
    "synthesis_decision": Agent(DEEPSEEK, ("sphere", "conclusion", "facts", "role", "moves"),
                                lambda i: render("synthesis_decision", sphere=i["sphere"], conclusion=i["conclusion"],
                                                 facts=i["facts"] or "нет", role_title=i["role"]["title"],
                                                 role_authority=i["role"]["authority"], role_playbook=i["role"]["playbook"],
                                                 moves="\n".join(f"- {k}: {v}" for k, v in i["moves"].items()) or "(ТРИЗ выключена — только правила роли)"),
                                key="title", max_tokens=4000, read_timeout=90),
}


def run(name: str, data: dict, usage: dict | None = None) -> dict:
    """Run one agent, retrying empty, truncated or malformed answers up to 3 times. usage: filled with this call's calls/tokens/cost."""
    agent = AGENTS[name]
    missing = [f for f in agent.fields if f not in data]
    if missing:
        raise KeyError(", ".join(missing))
    prompt, images = agent.build(data), data.get(agent.images) if agent.images else None
    content = [{"type": "text", "text": prompt}, *({"type": "image_url", "image_url": {"url": u}} for u in images)] if images else prompt
    budget, err = agent.max_tokens, "no JSON object in the answer"
    ctx = {"call_id": uuid.uuid4().hex[:12], "agent": name}
    token, started = CALL.set(ctx), time.monotonic()
    try:
        emit("call", model=agent.model, max_tokens=agent.max_tokens, input={k: v for k, v in data.items() if k != agent.images},
             images=len(images or []), prompt=prompt)
        for attempt in range(1, 4):
            ctx["attempt"] = attempt
            text, used = chat(agent.model, content, budget, agent.read_timeout)
            count(name, used, usage if usage is not None else {})
            match, answer = re.search(r"\{.*\}", text, re.S), None
            try:
                if match:
                    answer = json.loads(match.group(0))
                    if isinstance(answer, dict) and (agent.key is None or answer.get(agent.key)):
                        output = agent.finish(answer, data)
                        emit("attempt", outcome="ok", budget=budget, usage=used, parsed=answer)
                        emit("result", ms=round((time.monotonic() - started) * 1000), output=output)
                        return output
                    err = f"missing {agent.key!r}"
            except json.JSONDecodeError as e:
                err = repr(e)
            emit("attempt", outcome="retry", reason=err, budget=budget, usage=used, parsed=answer)
            budget = next_budget(budget, used)
        raise LLMError(f"{agent.model} gave no valid JSON for {name}: {err}")
    except Exception as e:
        emit("error", ms=round((time.monotonic() - started) * 1000), error=repr(e))
        raise
    finally:
        CALL.reset(token)


# ---- HTTP ----

app = FastAPI(title="Agents")


class Request(BaseModel):
    input: dict


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/agents")
def agents() -> dict:
    return {n: {"model": a.model, "fields": list(a.fields)} for n, a in AGENTS.items()}


@app.get("/usage")
def usage() -> dict:
    with LOCK:
        total = {k: sum(row[k] for row in TOTALS.values()) for k in ("calls", "tokens", "cost")}
        return {"total": total, "by_agent": {k: dict(v) for k, v in TOTALS.items()}}


@app.post("/agents/{name}")
def run_agent(name: str, req: Request) -> dict:
    if name not in AGENTS:
        raise HTTPException(404, f"unknown agent {name!r}")
    used: dict = {}
    try:
        output = run(name, req.input, used)
    except KeyError as e:
        raise HTTPException(422, f"missing input fields: {e.args[0]}")
    except LLMError as e:
        raise HTTPException(502, str(e))
    return {"output": output, "usage": {"calls": 0, "tokens": 0, "cost": 0.0} | used}
