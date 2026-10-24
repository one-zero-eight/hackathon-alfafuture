"""Agents service: POST /agents/{name} runs one named LLM task. Every LLM call of the project goes through here (the Go collector's tagging excepted)."""
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agents import registry
from agents.llm import USAGE, LLMError

app = FastAPI(title="Agents")


class Request(BaseModel):
    input: dict


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/agents")
def agents() -> dict:
    return {n: {"model": a.model, "fields": list(a.fields)} for n, a in registry.AGENTS.items()}


@app.get("/usage")
def usage() -> dict:
    return USAGE.snapshot()


@app.post("/agents/{name}")
def run(name: str, req: Request) -> dict:
    if name not in registry.AGENTS:
        raise HTTPException(404, f"unknown agent {name!r}")
    before = USAGE.snapshot()["by_agent"].get(name, {"calls": 0, "tokens": 0, "cost": 0.0})
    try:
        output = registry.run(name, req.input)
    except KeyError as e:
        raise HTTPException(422, f"missing input fields: {e.args[0]}")
    except LLMError as e:
        raise HTTPException(502, str(e))
    after = USAGE.snapshot()["by_agent"][name]
    # shortcut: the delta also counts parallel calls of the same agent; exact per-request usage needs request-scoped accounting
    return {"output": output, "usage": {k: after[k] - before[k] for k in before}}
