"""The agents: one named task each (prompt template + model + output check). Callers pass plain data and get a JSON object back.

Prompts live in prompts/<name>.md; {field} placeholders are filled from the input, anything else in the file is left as is.
"""
import datetime
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from agents.llm import json_call

PROMPTS = Path(__file__).parent / "prompts"
DEEPSEEK, GLM, QWEN, QWEN_VL = "deepseek/deepseek-v4.1-flash", "z-ai/glm-5.3-flash", "qwen/qwen3.6-35b-a3b", "qwen/qwen3-vl-30b-a3b-instruct"


def render(name: str, **fields) -> str:
    template = (PROMPTS / f"{name}.md").read_text(encoding="utf-8").rstrip("\n")
    return re.sub(r"\{(\w+)\}", lambda m: str(fields[m.group(1)]) if m.group(1) in fields else m.group(0), template)


def where(region: str) -> str:
    return f" Регион: «{region}»." if region else ""


def strings(values) -> list[str]:
    return [x.strip() for x in values if isinstance(x, str) and x.strip()]


@dataclass(frozen=True)
class Agent:
    model: str
    fields: tuple[str, ...]  # required input fields
    build: Callable[[dict], str]
    key: str | None = None  # output field that must be non-empty, else the call is retried
    max_tokens: int = 32000
    tries: int = 3
    read_timeout: float = 600
    images: str | None = None  # input field holding data-URL images
    finish: Callable[[dict, dict], dict] = field(default=lambda out, inp: out)


def _queries(i):  # the region is appended to the company, as in the search pipeline
    return render("queries", today=datetime.date.today().isoformat(), company=i["company"] + where(i.get("region", "")), line=i["line"])


def _queries_out(out, _):
    return {b: strings(v) for b, v in out.items() if isinstance(v, list)}


def _pick(i):
    lines = "\n".join(f"{c['id']} | {str(c.get('date', ''))[:16]} | {', '.join(c.get('outlets', [])[:3])} | {c['title']}" for c in i["candidates"])
    return render("pick", today=datetime.date.today().isoformat(), company=i["company"], line=i["line"], top=i.get("top", 30), lines=lines)


def _pick_out(out, i):
    ok = {c["id"] for c in i["candidates"]}
    return {"top": [int(e["id"]) for e in out["top"] if isinstance(e, dict) and str(e.get("id", "")).isdigit() and int(e["id"]) in ok]}


def _step(i):
    facts, sphere = i.get("facts", ""), i.get("sphere", "")
    return render("analytics_step", company=i["company"],
                  facts_line=f"Факты из карточки банка: {facts}" if facts else "",
                  sphere_line=f"Сфера анализа: {sphere}. Пиши про неё, даже если слова введены с опечаткой." if sphere else "",
                  kinds=", ".join(i["kinds"]), title=i["title"], text=i.get("text", ""),
                  thoughts=json.dumps(i["thoughts"], ensure_ascii=False), materials=i["materials"])


def _decision(i):
    sphere = i.get("sphere", "")
    moves = "\n".join(f"- {k}: {v}" for k, v in i["moves"].items()) or "(ТРИЗ выключена — только правила роли)"
    return render("decision", sphere_line=f"Сфера анализа: {sphere}. Решение для этой сферы, по правилам роли." if sphere else "",
                  role_title=i["role"]["title"], role_authority=i["role"]["authority"], role_playbook=i["role"]["playbook"],
                  moves=moves, title=i["title"], notes=json.dumps(i["notes"], ensure_ascii=False))


def _reply(i):
    facts = i.get("facts", "")
    return render("reply", facts_line=f"Факты из карточки банка: {facts}" if facts else "", title=i.get("title", ""), text=i.get("text", ""),
                  risks=json.dumps(i.get("risks", []), ensure_ascii=False), question=i["question"])


AGENTS: dict[str, Agent] = {
    # search side
    "queries": Agent(DEEPSEEK, ("company", "line"), _queries, key="company_self", finish=_queries_out),
    "needs": Agent(DEEPSEEK, ("company", "line"), lambda i: render("needs", company=i["company"], where=where(i.get("region", "")), line=i["line"]),
                   key="needs", finish=lambda out, _: {"needs": strings(out["needs"])}),
    "hyde": Agent(DEEPSEEK, ("company", "line"), lambda i: render("hyde", company=i["company"], where=where(i.get("region", "")), line=i["line"]),
                  key="headlines", finish=lambda out, _: {"headlines": strings(out["headlines"])}),
    "pick": Agent(GLM, ("company", "line", "candidates"), _pick, key="top", finish=_pick_out),
    # analytics side
    "analytics_step": Agent(DEEPSEEK, ("company", "kinds", "title", "thoughts", "materials"), _step,
                            max_tokens=2500, tries=3, read_timeout=90),
    "decision": Agent(DEEPSEEK, ("role", "moves", "title", "notes"), _decision, key="title", max_tokens=4000, read_timeout=90),
    "verify": Agent(QWEN, ("claims",), lambda i: render("verify", claims=json.dumps([{"text": c["text"], "quote": c["quote"]} for c in i["claims"]], ensure_ascii=False)),
                    key="verdicts", max_tokens=2000, read_timeout=90),
    "reply": Agent(DEEPSEEK, ("question",), _reply, key="text", max_tokens=1200, read_timeout=90),
    "alfa_page": Agent(QWEN_VL, (), lambda i: render("alfa_page", page_text=f"\n\nСТРАНИЦА {i['page']}:\n{i['text'][:6000]}" if i.get("text") else ""),
                       max_tokens=1200, read_timeout=120, images="images"),
}


def run(name: str, data: dict) -> dict:
    agent = AGENTS[name]
    missing = [f for f in agent.fields if f not in data]
    if missing:
        raise KeyError(", ".join(missing))
    out = json_call(name, agent.model, agent.build(data), key=agent.key, tries=agent.tries, max_tokens=agent.max_tokens,
                    read_timeout=agent.read_timeout, images=data.get(agent.images) if agent.images else None)
    return agent.finish(out, data)
