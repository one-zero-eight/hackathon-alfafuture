"""Print how far the Alfa read and the profile run have got. Safe to run while they are working.

    .venv/bin/python -m reasoning.progress
"""
import json
import subprocess
import time
from reasoning.alfa import CACHE, OUT, pdfs, pages_text
from reasoning.data import corpus

PAGE = OUT.parent
CALLS = PAGE / "calls.jsonl"
STATUS = PAGE / "status.json"


def etime_sec(text: str) -> int:
    """ps etime: mm:ss, hh:mm:ss, or d-hh:mm:ss."""
    text = text.strip()
    days = 0
    if "-" in text:
        day, text = text.split("-", 1)
        days = int(day)
    parts = [int(p) for p in text.split(":")]
    while len(parts) < 3:
        parts.insert(0, 0)
    h, m, s = parts
    return days * 86400 + h * 3600 + m * 60 + s


def calls_for_run(rows: list[dict], elapsed: float) -> list[dict]:
    """The live process does not stamp each call. Its calls are the tail whose durations add up to the time it has been running."""
    acc, picked = 0.0, []
    for row in reversed(rows):
        picked.append(row)
        acc += float(row.get("seconds") or 0)
        if acc >= elapsed:
            break
    return list(reversed(picked))


def news_position(steps: list[str], order: list[str]) -> tuple[int, str | None]:
    """How many news items are finished, and which one is in progress. A later id wins over interleaved older calls."""
    if any(step == "verify" or step.startswith("verify") for step in steps):
        return len(order), None
    idx = {event: i for i, event in enumerate(order)}
    current = -1
    for step in steps:
        event = step.split(".")[1] if step[:4] in ("hop2", "hop3") and "." in step else ""
        if event in idx:
            current = max(current, idx[event])
    if current < 0:
        return 0, None
    return current, order[current]


def eta_min(done: int, total: int, elapsed: float) -> int | None:
    if done <= 0 or done >= total:
        return 0 if done >= total and total else None
    return round(elapsed / done * (total - done) / 60)


def live_run() -> tuple[int, str] | None:
    out = subprocess.check_output(["ps", "-ax", "-o", "etime=,command="], text=True)
    for line in out.splitlines():
        etime, _, cmd = line.strip().partition(" ")
        if cmd.startswith("/bin/bash") or "python -m reasoning.run " not in cmd:
            continue
        return etime_sec(etime), cmd.rsplit(None, 1)[-1]
    return None


def _rows() -> list[dict]:
    if not CALLS.exists():
        return []
    return [json.loads(line) for line in CALLS.read_text(encoding="utf-8").splitlines() if line.strip()]


def profile_line() -> str | None:
    live = live_run()
    if STATUS.exists() and live and time.time() - STATUS.stat().st_mtime <= live[0] + 30:
        st = json.loads(STATUS.read_text(encoding="utf-8"))
        if st.get("profile") == live[1]:
            left_s = _left(st.get("left_min"))
            return (f"{st['profile']}: новость {st['done'] + 1} из {st['total']}, готово {st['done']}, "
                    f"осталось примерно {left_s} — {st.get('title', '')}")
    if not live:
        return None
    elapsed, pid = live
    events = corpus(pid)[0][:10]
    order = [e["id"] for e in events]
    titles = {e["id"]: e["title"][:70] for e in events}
    steps = [r.get("step", "") for r in calls_for_run(_rows(), elapsed)]
    done, event = news_position(steps, order)
    if done >= len(order):
        return f"{pid}: 10 из 10 посчитаны, идёт проверка"
    title = titles.get(event, "")
    return (f"{pid}: новость {done + 1} из {len(order)}, готово {done}, прошло {round(elapsed / 60)} мин, "
            f"осталось примерно {_left(eta_min(done, len(order), elapsed))} — {title}")


def _left(left: int | None) -> str:
    if left is None:
        return "после первой новости"
    if left <= 0:
        return "меньше минуты"
    return f"{left} мин"


def main() -> None:
    cached = []
    if CACHE.exists():
        cached = [json.loads(line) for line in CACHE.read_text(encoding="utf-8").splitlines() if line.strip()]
    total = sum(len(pages_text(path)) for path in pdfs())
    print(f"alfa pages {len(cached)}/{total}")
    line = profile_line()
    if line:
        print(line)
    pages = sorted(PAGE.glob("U*.json"))
    for path in pages:
        page = json.loads(path.read_text(encoding="utf-8"))
        cols = {}
        for w in page.get("widgets", []):
            cols[w["column"]] = cols.get(w["column"], 0) + 1
        print(path.name, cols, "links", len(page.get("links", [])))
    if not pages and not line:
        print("no profile page yet")


if __name__ == "__main__":
    main()
