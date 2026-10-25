"""Bounded operational events shared by the HTTP services; never accepts arbitrary payloads."""
import contextlib
import contextvars
import datetime as dt
import hashlib
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

log = logging.getLogger("agents.tracing")
CURRENT = contextvars.ContextVar("trace", default=None)
PARENT = contextvars.ContextVar("trace_parent", default=None)
SECTIONS = Literal["backend", "agents", "news_search", "analytics"]
STEPS = Literal["run", "queued", "profile", "queries", "needs", "hyde", "search", "retrieval", "deduplication", "ranking", "analytics", "decision", "verification", "publication", "chat", "cache", "refine", "llm", "gateway", "description"]
COUNT_KEYS = {"before", "after", "duplicates", "own_removed", "selected", "queries", "notes", "decisions", "claims", "unsupported", "excluded", "removed", "regional"}
AGENT_NAMES = {"queries", "needs", "hyde", "pick", "analytics_step", "decision", "verify", "reply", "alfa_page", "trace_description"}
MODELS = {"google/gemma-4-26b-a4b-it", "deepseek/deepseek-v4.1-flash", "z-ai/glm-5.3-flash", "qwen/qwen3.6-35b-a3b", "qwen/qwen3-vl-30b-a3b-instruct", "moonshotai/kimi-k2.6"}
ID = r"^[0-9a-f]{32}$"


class Usage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prompt_tokens: int | None = Field(None, ge=0)
    completion_tokens: int | None = Field(None, ge=0)
    reasoning_tokens: int | None = Field(None, ge=0)
    total_tokens: int | None = Field(None, ge=0)
    cost: float | None = Field(None, ge=0, allow_inf_nan=False)


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=ID)
    span_id: str = Field(default_factory=lambda: uuid.uuid4().hex, pattern=ID)
    parent_id: str | None = Field(None, pattern=ID)
    section: SECTIONS
    step: STEPS
    timestamp: dt.datetime = Field(default_factory=lambda: dt.datetime.now(dt.timezone.utc))
    duration_ms: float | None = Field(None, ge=0, allow_inf_nan=False)
    status: Literal["started", "completed", "failed", "cached", "skipped"] = "completed"
    counts: dict[str, int] = Field(default_factory=dict)
    queries: list[str] = Field(default_factory=list, max_length=3)
    source_ids: list[str] = Field(default_factory=list, max_length=200)
    widget_ids: list[str] = Field(default_factory=list, max_length=200)
    error_code: Literal["upstream_error", "invalid_response", "interrupted", "http_error"] | None = None
    agent: str | None = None
    model: str | None = None
    attempt: int | None = Field(None, ge=1)
    usage: Usage | None = None

    @field_validator("counts")
    @classmethod
    def valid_counts(cls, value):
        if not set(value) <= COUNT_KEYS or any(v < 0 for v in value.values()):
            raise ValueError("invalid count")
        return value

    @field_validator("queries")
    @classmethod
    def valid_queries(cls, value):
        # Query samples are generated search terms, never raw profile/chat input.
        import re
        if any(len(q) > 200 or re.search(r"https?://|@|Bearer\s|sk-[a-zA-Z0-9]|\b\d{10,}\b", q, re.I) for q in value):
            raise ValueError("unsafe query sample")
        return value

    @field_validator("source_ids", "widget_ids")
    @classmethod
    def valid_references(cls, value):
        import re
        if any(not re.fullmatch(r"(?:article:\d+|[nN]\d+|alfa:[\w.-]+:p\d+:t\d+|(?:[0-9a-f]{12}_)?[nadl]\w{0,60})", x) for x in value):
            raise ValueError("invalid reference")
        return value

    @field_validator("agent", "model")
    @classmethod
    def valid_name(cls, value, info):
        if value is not None and value not in (AGENT_NAMES if info.field_name == "agent" else MODELS):
            raise ValueError("unknown name")
        return value

    @field_validator("timestamp")
    @classmethod
    def utc_time(cls, value):
        if value.tzinfo is None:
            raise ValueError("timezone is required")
        return value.astimezone(dt.timezone.utc)


@dataclass
class Trace:
    run_id: str
    capability: str
    section: str
    sender: object = None
    incomplete: bool = False
    delivery_failed: bool = False
    lock: threading.Lock = field(default_factory=threading.Lock)

    def mark_incomplete(self):
        with self.lock:
            self.incomplete = True


def company_ref(value: str) -> str:
    return hashlib.sha256(" ".join(value.lower().split()).encode()).hexdigest()


def _request(path, body, trace=None):
    url = os.environ.get("TRACE_BACKEND_URL", "").rstrip("/")
    if not url:
        raise RuntimeError("trace backend is not configured")
    headers = {"X-Trace-Capability": trace.capability} if trace else {}
    for attempt in range(2):
        try:
            response = httpx.post(url + path, json=body, headers=headers, timeout=1.0)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError):
            if attempt:
                raise RuntimeError("trace delivery failed") from None


def headers() -> dict:
    trace = CURRENT.get()
    if not trace:
        return {}
    return {"X-Run-ID": trace.run_id, "X-Trace-Capability": trace.capability,
            "X-Trace-Parent": PARENT.get() or "", "X-Trace-Incomplete": str(trace.incomplete).lower()}


def observe(response):
    if CURRENT.get() and response.headers.get("X-Trace-Incomplete") == "true":
        CURRENT.get().mark_incomplete()


def emit(step, **fields):
    trace = CURRENT.get()
    if not trace:
        return
    try:
        event = Event(section=trace.section, step=step, parent_id=PARENT.get(), **fields)
        payload = event.model_dump(mode="json")
        if trace.sender:
            trace.sender(event)
        else:
            if trace.delivery_failed:
                log.info("trace fallback %s", json.dumps(payload, ensure_ascii=False))
                return
            _request(f"/internal/trace/runs/{trace.run_id}/events", {"event": payload}, trace)
    except Exception:
        trace.mark_incomplete()
        trace.delivery_failed = True
        # Only the validated operational event is safe to write; exceptions can contain URLs/secrets.
        log.warning("trace delivery failed run=%s step=%s", trace.run_id, step)
        if "payload" in locals():
            log.info("trace fallback %s", json.dumps(payload, ensure_ascii=False))


@contextlib.contextmanager
def activate(trace, parent=None):
    token, parent_token = CURRENT.set(trace), PARENT.set(parent)
    try:
        yield trace
    finally:
        PARENT.reset(parent_token)
        CURRENT.reset(token)


@contextlib.contextmanager
def span(step, **fields):
    span_id, started = uuid.uuid4().hex, time.monotonic()
    emit(step, span_id=span_id, status="started", **{k: v for k, v in fields.items() if k not in ("usage", "counts")})
    parent = PARENT.set(span_id)
    result = dict(fields)
    try:
        yield result
    except BaseException:
        result.update(status="failed", error_code=result.get("error_code") or "upstream_error")
        raise
    finally:
        PARENT.reset(parent)
        result.setdefault("status", "completed")
        emit(step, span_id=span_id, duration_ms=(time.monotonic() - started) * 1000, **result)


def query_sample(queries):
    safe = []
    for query in queries:
        try:
            Event(section="news_search", step="queries", queries=[query])
        except ValueError:
            continue
        safe.append(query)
        if len(safe) == 3:
            break
    return safe


def usage_fields(used):
    values = {k: used[k] for k in ("prompt_tokens", "completion_tokens", "total_tokens", "cost") if used.get(k) is not None}
    reasoning = (used.get("completion_tokens_details") or {}).get("reasoning_tokens")
    if reasoning is not None:
        values["reasoning_tokens"] = reasoning
    return Usage(**values)


def install(app, section, paths):
    """HTTP context is copied into FastAPI's worker threads; child executors copy it explicitly."""
    import asyncio

    @app.middleware("http")
    async def trace_request(request, call_next):
        if request.method != "POST" or not any(request.url.path.startswith(p) for p in paths):
            return await call_next(request)
        run_id, capability = request.headers.get("X-Run-ID"), request.headers.get("X-Trace-Capability")
        owned, trace = False, None
        parent = request.headers.get("X-Trace-Parent") or None
        import re
        if run_id and capability and re.fullmatch(ID, run_id) and (parent is None or re.fullmatch(ID, parent)):
            trace = Trace(run_id, capability, section, incomplete=request.headers.get("X-Trace-Incomplete") == "true")
        elif os.environ.get("TRACE_BACKEND_URL"):
            try:
                body = await request.json()
                identity = body.get("company") or (body.get("profile") or {}).get("label") or "standalone"
                created = await asyncio.to_thread(_request, "/internal/trace/runs", {"kind": section, "company_ref": company_ref(str(identity))})
                trace = Trace(created["run_id"], created["capability"], section)
                owned = True
            except Exception:
                log.warning("standalone trace creation failed section=%s", section)
        if trace is None:
            response = await call_next(request)
            if os.environ.get("TRACE_BACKEND_URL"):
                response.headers["X-Trace-Incomplete"] = "true"
            return response
        with activate(trace, parent):
            started, span_id = time.monotonic(), uuid.uuid4().hex
            operation = {"/refine": "refine", "/reply": "chat", "/agents/trace_description": "description"}.get(request.url.path, "run")
            await asyncio.to_thread(emit, operation, span_id=span_id, status="started")
            parent_token = PARENT.set(span_id)
            status = "failed"
            try:
                response = await call_next(request)
                status = "completed" if response.status_code < 400 else "failed"
            finally:
                PARENT.reset(parent_token)
                await asyncio.to_thread(emit, operation, span_id=span_id, status=status,
                                        duration_ms=(time.monotonic() - started) * 1000,
                                        error_code="http_error" if status == "failed" else None)
                if owned:
                    try:
                        await asyncio.to_thread(_request, f"/internal/trace/runs/{trace.run_id}/finish",
                                                {"status": status, "incomplete": trace.incomplete}, trace)
                    except Exception:
                        trace.mark_incomplete()
            response.headers["X-Run-ID"] = trace.run_id
            response.headers["X-Trace-Incomplete"] = str(trace.incomplete).lower()
            return response
