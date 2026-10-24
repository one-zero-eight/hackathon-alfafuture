"""Print how far the Alfa read and the profile run have got. Safe to run while they are working.

    .venv/bin/python -m reasoning.progress
"""
import json
import subprocess
import time
from reasoning.alfa import CACHE, OUT, pdfs, pages_text
from reasoning.data import corpus
from reasoning.view import bar

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
    left = remaining_sec(done, total, elapsed, elapsed)
    return None if left is None else round(left / 60)


def remaining_sec(done: int, total: int, marked: float, now: float) -> int | None:
    """Seconds left. `marked` is the clock when `done` items had just finished; it ticks down as `now` grows."""
    if done <= 0 or total <= 0:
        return None
    if done >= total:
        return max(0, round(marked / done * total - now))
    left = marked / done * (total - done) - (now - marked)
    return max(0, round(left))


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


def _clock(sec: int | None) -> str:
    if sec is None:
        return "после первой новости"
    if sec <= 0:
        return "дольше оценки"
    m, s = divmod(sec, 60)
    return f"{m}:{s:02d}"


def _line(pid: str, done: int, total: int, left: int | None, title: str, elapsed: int) -> str:
    head = f"{pid} [{bar(min(done, total), total)}] {min(done, total)}/{total} прошло {_clock(elapsed)}"
    if done >= total:
        return f"{head} проверка цитат"
    return f"{head} осталось {_clock(left)} новость {done + 1} — {title}"


def profile_line() -> str | None:
    live = live_run()
    if not live:
        return None
    elapsed, pid = live
    if STATUS.exists() and time.time() - STATUS.stat().st_mtime <= elapsed + 30:
        st = json.loads(STATUS.read_text(encoding="utf-8"))
        if st.get("profile") == pid:
            done, total = st["done"], st["total"]
            return _line(pid, done, total, remaining_sec(done, total, st.get("elapsed_sec") or elapsed, elapsed), st.get("title", ""), elapsed)
    events = corpus(pid)[0][:10]
    order = [e["id"] for e in events]
    titles = {e["id"]: e["title"][:70] for e in events}
    steps = [r.get("step", "") for r in calls_for_run(_rows(), elapsed)]
    done, event = news_position(steps, order)
    if done >= len(order):
        return _line(pid, len(order), len(order), 0, "", elapsed)
    return _line(pid, done, len(order), remaining_sec(done, len(order), elapsed, elapsed), titles.get(event, ""), elapsed)


def main() -> None:
    cached = []
    if CACHE.exists():
        cached = [json.loads(line) for line in CACHE.read_text(encoding="utf-8").splitlines() if line.strip()]
    total = sum(len(pages_text(path)) for path in pdfs())
    print(f"alfa pages {len(cached)}/{total}", flush=True)
    if not live_run():
        _finish()
        return
    try:
        while live_run():
            print("\033[2K\r" + (profile_line() or ""), end="", flush=True)
            time.sleep(1)
    except KeyboardInterrupt:
        print()
        return
    print()
    _finish()


def _finish() -> None:
    pages = sorted(PAGE.glob("U*.json"))
    for path in pages:
        page = json.loads(path.read_text(encoding="utf-8"))
        cols = {}
        for w in page.get("widgets", []):
            cols[w["column"]] = cols.get(w["column"], 0) + 1
        print(path.name, cols, "links", len(page.get("links", [])))
    if not pages:
        print("no profile page yet")


if __name__ == "__main__":
    main()
