"""Journal routes: public projection and capability-protected internal ingestion."""
import re
from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from agents import tracing
from agents.client import Agents
from backend import config, journal, store

router = APIRouter()


class Start(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["news_search", "analytics", "agents"]
    company_ref: str = Field(pattern=r"^[0-9a-f]{64}$")


class Ingest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event: tracing.Event


class Finish(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: Literal["completed", "failed"]
    incomplete: bool = False


def check(run_id, capability):
    if not re.fullmatch(tracing.ID, run_id) or not journal.authorised(run_id, capability):
        raise HTTPException(403, "invalid run capability")


@router.post("/internal/trace/runs")
def start(req: Start):
    # This route is available only on the trusted service network / loopback backend port, never through nginx.
    return journal.create(req.kind, req.company_ref)


@router.post("/internal/trace/runs/{run_id}/events")
def ingest(run_id: str, req: Ingest, capability: str = Header("", alias="X-Trace-Capability")):
    check(run_id, capability)
    journal.record(run_id, req.event)
    return {"ok": True}


@router.post("/internal/trace/runs/{run_id}/finish")
def finish(run_id: str, req: Finish, capability: str = Header("", alias="X-Trace-Capability")):
    check(run_id, capability)
    journal.finish(run_id, req.status, req.incomplete)
    return {"ok": True}


@router.get("/api/profile/{key}/runs")
def profile_runs(key: str):
    if store.status(key) is None:
        raise HTTPException(404, "profile not found")
    return {"runs": journal.runs(key)}


@router.get("/api/runs/{run_id}")
def read_run(run_id: str, after: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=200)):
    run = journal.get(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    descriptions = run.pop("descriptions")
    items = journal.events(run_id, after, limit, descriptions)
    return {**run, "events": items, "next_cursor": items[-1]["cursor"] if items else after}


@router.post("/api/runs/{run_id}/descriptions")
def descriptions(run_id: str):
    run = journal.get(run_id)
    if run is None:
        raise HTTPException(404, "run not found")
    if run["descriptions"] is not None:
        return {"run_id": run_id, "descriptions": run["descriptions"], "cached": True}
    if run["finished_at"] is None:
        raise HTTPException(409, "run is not complete")
    if not config.TRACE_AI_ENABLED:
        raise HTTPException(503, "AI descriptions disabled pending currency and daily budget confirmation")
    if not journal.claim_descriptions(run_id):
        raise HTTPException(409, "description generation already in progress")
    trace = journal.context(run_id)
    try:
        with tracing.activate(trace), tracing.span("description"):
            inputs = journal.description_input(run_id)
            answer = Agents(config.AGENTS_URL).run("trace_description", {"events": inputs}) if inputs else {"descriptions": []}
            output = journal.validate_descriptions(answer, inputs)
        journal.save_descriptions(run_id, output)
        return {"run_id": run_id, "descriptions": output, "cached": False}
    except (RuntimeError, ValueError):
        journal.save_descriptions(run_id, None)
        raise HTTPException(502, "description generation failed") from None
    finally:
        if trace and trace.incomplete:
            with store.connect() as conn:
                conn.execute("UPDATE trace_runs SET incomplete=true WHERE id=%s", (run_id,))
