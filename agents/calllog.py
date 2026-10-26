"""JSON Lines log of every agent call: input, prompt, the model's reasoning, raw answer and parsed result.

One line per event, written to stdout (docker logs) and, if AGENTS_LOG_FILE is set, appended to that file. Events of one call share call_id;
run() puts call_id, agent and attempt into CALL, so chat() can log its gateway tries without knowing about agents.
Logging never raises: a broken log file must not fail an LLM call.
"""
import contextvars
import datetime
import json
import os
import sys
import threading

CALL: contextvars.ContextVar[dict | None] = contextvars.ContextVar("agent_call", default=None)
LOCK = threading.Lock()


def emit(event: str, **fields) -> None:
    try:
        row = {"ts": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds"), "event": event, **(CALL.get() or {}), **fields}
        line = json.dumps(row, ensure_ascii=False, default=str)
        with LOCK:
            sys.stdout.write(line + "\n")
            sys.stdout.flush()
            if path := os.environ.get("AGENTS_LOG_FILE"):
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line + "\n")
    except Exception:  # shortcut: errors are swallowed silently, add a counter if lost log lines ever matter
        pass
