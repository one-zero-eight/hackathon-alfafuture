"""Strict validation of the feedback_intent answer. Anything unusable becomes `clarify`: no guessing, no keyword fallback."""
from urllib.parse import urlsplit

KINDS = ("question", "extend", "perspective", "edit", "remove", "link", "proposal", "clarify")
UNCLEAR = "Не удалось однозначно понять запрос. Это вопрос по странице или изменение? Уточните, к чему он относится."


def text_field(value, limit: int = 4000):
    return value.strip()[:limit] if isinstance(value, str) and value.strip() else None


def clarify(reason: str, question: str | None = None) -> dict:
    return {"kind": "clarify", "reason": reason, "target_id": None, "text": None, "url": None, "line": None, "region": None,
            "clarification": question or UNCLEAR}


def validate(out: dict, inputs: dict) -> dict:
    """The classifier's answer -> an intent whose targets and fields are checked against the page context and the message."""
    kind, reason = out.get("kind"), text_field(out.get("reason"), 300) or ""
    if kind not in KINDS:
        return clarify("unknown kind")
    if kind == "clarify":
        return clarify(reason, text_field(out.get("clarification"), 500))
    ids = {w["id"] for w in inputs["context"].get("widgets", [])}
    intent = {"kind": kind, "reason": reason, "target_id": None, "text": None, "url": None, "line": None, "region": None, "clarification": None}
    for key in ("text", "line", "region"):
        intent[key] = text_field(out.get(key), 4000 if key == "text" else 200)
    if kind in ("edit", "remove"):
        if out.get("target_id") not in ids:
            return clarify("target is not on the page")
        intent["target_id"] = out["target_id"]
    if kind in ("edit", "proposal", "extend") and not intent["text"]:
        return clarify("the request has no content")
    if kind == "perspective" and not (intent["line"] or intent["region"]):
        return clarify("no new line or region")
    if kind == "link":
        url = text_field(out.get("url"), 2000)
        parts = urlsplit(url or "")
        if not url or url not in inputs["message"] or parts.scheme not in ("http", "https") or not parts.hostname:
            return clarify("no valid link in the message")
        intent["url"] = url
    return intent
