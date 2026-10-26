"""Strict classifier output shared by the agent and backend; never executable instructions."""
import json
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

KINDS = ("question", "extend", "perspective", "edit", "remove", "link", "proposal", "clarify")


class Intent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["question", "extend", "perspective", "edit", "remove", "link", "proposal", "clarify"]
    reason: str = Field(min_length=1, max_length=300)
    target_id: str | None = Field(None, max_length=100)
    text: str = Field("", max_length=8000)
    line: str | None = Field(None, max_length=200)
    region: str | None = Field(None, max_length=200)
    url: str | None = Field(None, max_length=2048)
    refresh: bool = False
    clarification: str | None = Field(None, max_length=300)


def input_values(data):
    message, context = data["message"], data["context"]
    if not isinstance(message, str) or not message.strip() or len(message) > 8000 or not isinstance(context, dict):
        raise ValueError("invalid classifier input")
    widgets, links = context.get("widgets", []), context.get("links", [])
    if not isinstance(widgets, list) or not isinstance(links, list) or len(widgets) > 80 or len(links) > 160:
        raise ValueError("context is too large")
    for item in [*widgets, *links]:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not 1 <= len(item["id"]) <= 100:
            raise ValueError("invalid context ID")
    if len(json.dumps(context, ensure_ascii=False)) > 40000:
        raise ValueError("context is too large")
    return {"message": message, "context": context}


def validate(output, inputs):
    input_values(inputs)
    intent = Intent.model_validate(output)
    context = inputs["context"]
    allowed = {w["id"] for w in context.get("widgets", [])} | {l["id"] for l in context.get("links", [])}
    if intent.target_id is not None and intent.target_id not in allowed:
        raise ValueError("invented target")
    if intent.kind in ("edit", "remove") and intent.target_id is None:
        raise ValueError("target is required")
    if intent.kind == "link":
        known_urls = [w.get("url") for w in context.get("widgets", [])]
        requested_urls = re.findall(r'https?://[^\s<>"\'\[\]]+', inputs["message"])
        if not intent.url or (intent.url not in requested_urls and intent.url not in known_urls):
            raise ValueError("URL is not in the request or context")
    if intent.kind == "edit" and (not intent.text or intent.text not in inputs["message"]):
        raise ValueError("manual text must be copied verbatim")
    if intent.kind == "clarify" and not intent.clarification:
        raise ValueError("clarification is required")
    if intent.kind == "extend" and not intent.text.strip():
        raise ValueError("topic is required")
    if intent.kind == "perspective" and not (intent.refresh or intent.line or intent.region):
        raise ValueError("new perspective is required")
    if intent.refresh and intent.kind != "perspective":
        raise ValueError("refresh belongs to perspective")
    return intent.model_dump()
