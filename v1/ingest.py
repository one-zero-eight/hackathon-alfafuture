"""Fill the news corpus (Postgres `articles`, same table as the Go collector in backend/) from many sources.

    python ingest.py feeds [--every 900]          # the 47 RSS feeds of outlets50.json (rbc/kommersant/cbr are left to the Go collector)
    python ingest.py gn --days 180 [--step 7]     # Google News backfill: every topic x weekly after:/before: window
    python ingest.py loop                         # daemon used by docker compose (feeds every 15 min, Google News every 6 h)
    python ingest.py gnsite --days 60 [--step 2]  # per-outlet depth: Google News site:<host> over 2-day windows

Needs DATABASE_URL (see .env.example) and the schema created by `docker compose up` (the Go service bootstraps it).
Rows are written as `completed` (v1 has no tagging); re-runs are safe: (source_id, dedup_key) is unique.
"""
import argparse, datetime, glob, hashlib, json, os, re, sys, time
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime

import psycopg

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pipeline import CFG, HERE, google_news, pull_feed  # noqa

GO_SOURCES = {"rbc", "kommersant", "cbr"}
GN_URL = "https://news.google.com/rss/search"


def parse_date(s):
    try:
        t = parsedate_to_datetime(s)
        return t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc)
    except Exception:
        return None  # the schema allows undated items


def save(conn, source_id, source_name, feed_url, items):
    """items: [{title, link, date, summary?}]; returns number of new rows."""
    now = datetime.datetime.now(datetime.timezone.utc)
    rows = []
    for it in items:
        if not it["link"].startswith(("http://", "https://")) or not it["title"]: continue
        text = (it.get("summary") or "").strip()
        # dedup_key mirrors the Go collector (sha256 of "url:<url>" when the item has no GUID)
        rows.append((source_id, hashlib.sha256(("url:" + it["link"]).encode()).hexdigest(), it["link"], it["title"],
                     parse_date(it["date"]), now, text, "rss_description" if text else ""))
    with conn.cursor() as cur:
        cur.execute("INSERT INTO sources (id, name, feed_url, collection_since, created_at, last_error) VALUES (%s,%s,%s,%s,%s,'') ON CONFLICT (id) DO NOTHING",
                    (source_id, source_name, feed_url, now - datetime.timedelta(days=365), now))
        before = cur.execute("SELECT count(*) FROM articles WHERE source_id=%s", (source_id,)).fetchone()[0]
        cur.executemany("INSERT INTO articles (source_id, dedup_key, source_item_id, url, title, published_at, collected_at, text, text_provenance, text_error, processing_status) "
                        "VALUES (%s,%s,'',%s,%s,%s,%s,%s,%s,'','completed') ON CONFLICT (source_id, dedup_key) DO NOTHING", rows)
        after = cur.execute("SELECT count(*) FROM articles WHERE source_id=%s", (source_id,)).fetchone()[0]
    conn.commit()
    return after - before


def load_outlets():
    out = {}
    for f in ("outlets50.json", "outlets_new.json"):  # the second one is optional
        p = os.path.join(HERE, f)
        if os.path.exists(p):
            for o in json.load(open(p, encoding="utf-8")): out.setdefault(o["id"], o)
    return list(out.values())


def run_feeds(conn):
    outlets = [o for o in load_outlets() if o["id"] not in GO_SOURCES]
    with ThreadPoolExecutor(12) as ex:
        fetched = list(ex.map(pull_feed, outlets))
    for o, items in zip(outlets, fetched):
        print(f"{o['id']:20} fetched {len(items):4} new {save(conn, o['id'], o['name'], o['feed'], items):4}", flush=True)


def topics():
    t = set(json.load(open(os.path.join(HERE, "cache", "gn.json"), encoding="utf-8")))  # queries already used by earlier runs
    for f in glob.glob(os.path.join(HERE, "out", "*", "queries.json")):
        t |= {q for v in json.load(open(f, encoding="utf-8")).values() for q in v}
    extra = os.path.join(HERE, "topics_extra.txt")  # optional: one topic per line
    if os.path.exists(extra):
        t |= {l.strip() for l in open(extra, encoding="utf-8") if l.strip()}
    return sorted(t)


def run_gn(conn, days, step, resume=True):
    done_f = os.path.join(HERE, "cache", "gn_done.json")  # (topic, window) pairs already fetched: lets the backfill resume
    done = set(json.load(open(done_f))) if resume and os.path.exists(done_f) else set()
    today = datetime.date.today()
    wins = [(today - datetime.timedelta(days=d + step), today - datetime.timedelta(days=d)) for d in range(0, days, step)]
    jobs = [(q, a, b) for q in topics() for a, b in wins if f"{q}|{a}" not in done]
    print(f"{len(jobs)} requests", flush=True)

    def fetch(j):
        q, a, b = j
        time.sleep(0.4)
        return j, google_news(f"{q} after:{a} before:{b}", limit=100)

    new = 0
    with ThreadPoolExecutor(4) as ex:
        for n, (j, items) in enumerate(ex.map(fetch, jobs), 1):
            by_outlet = {}
            for it in items: by_outlet.setdefault(it["outlet"], []).append(it)
            for outlet, its in by_outlet.items():  # one source per outlet: `articles` has no outlet column
                sid = "gn:" + re.sub(r"\W+", "_", outlet.lower())[:60]
                new += save(conn, sid, outlet, GN_URL, its)
            if items: done.add(f"{j[0]}|{j[1]}")  # empty answers (429 included) are retried next time
            if n % 50 == 0:
                json.dump(sorted(done), open(done_f, "w")); print(f"{n}/{len(jobs)} requests, +{new} new", flush=True)
    json.dump(sorted(done), open(done_f, "w")); print(f"done, +{new} new")


def run_gnsite(conn, days, step, resume=True):
    """Per-outlet depth: Google News `site:<host>` over short windows reaches far past what an RSS feed still holds."""
    from urllib.parse import urlparse
    done_f = os.path.join(HERE, "cache", "gnsite_done.json")
    done = set(json.load(open(done_f))) if resume and os.path.exists(done_f) else set()
    today = datetime.date.today()
    wins = [(today - datetime.timedelta(days=d + step), today - datetime.timedelta(days=d)) for d in range(0, days, step)]
    hosts = {}
    for o in load_outlets():
        h = re.sub(r"^(www|rss|feeds?|rssexport|export)\.", "", urlparse(o["feed"]).netloc.lower())
        hosts.setdefault(h, o)
    jobs = [(h, a, b) for h in hosts for a, b in wins if f"{h}|{a}" not in done]
    print(f"{len(jobs)} requests", flush=True)

    def fetch(j):
        h, a, b = j
        time.sleep(0.4)
        return j, google_news(f"site:{h} after:{a} before:{b}", limit=100)

    new = 0
    with ThreadPoolExecutor(4) as ex:
        for n, (j, items) in enumerate(ex.map(fetch, jobs), 1):
            o = hosts[j[0]]
            new += save(conn, o["id"], o["name"], o["feed"], items)
            if items: done.add(f"{j[0]}|{j[1]}")
            if n % 50 == 0:
                json.dump(sorted(done), open(done_f, "w")); print(f"{n}/{len(jobs)} requests, +{new} new", flush=True)
    json.dump(sorted(done), open(done_f, "w")); print(f"done, +{new} new")


def run_loop(conn, feeds_every, deep_every):
    """Scraper daemon: feeds every `feeds_every` s; every `deep_every` s also a rolling 3-day Google News pass (topics + per-outlet)."""
    last_deep = 0.0
    while True:
        run_feeds(conn)
        if time.time() - last_deep >= deep_every:
            run_gnsite(conn, 3, 1, resume=False)  # windows move with the date, so nothing stale is re-fetched
            run_gn(conn, 3, 3, resume=False)
            last_deep = time.time()
        time.sleep(feeds_every)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(); sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("feeds"); f.add_argument("--every", type=int, default=0, help="repeat every N seconds (0 = once)")
    g = sub.add_parser("gn"); g.add_argument("--days", type=int, default=180); g.add_argument("--step", type=int, default=7)
    h = sub.add_parser("gnsite"); h.add_argument("--days", type=int, default=60); h.add_argument("--step", type=int, default=2)
    l = sub.add_parser("loop"); l.add_argument("--feeds-every", type=int, default=900); l.add_argument("--deep-every", type=int, default=21600)
    a = ap.parse_args()
    with psycopg.connect(CFG["DATABASE_URL"]) as conn:
        if a.cmd == "feeds":
            while True:
                run_feeds(conn)
                if not a.every: break
                time.sleep(a.every)
        elif a.cmd == "loop":
            run_loop(conn, a.feeds_every, a.deep_every)
        elif a.cmd == "gnsite":
            run_gnsite(conn, a.days, a.step)
        else:
            run_gn(conn, a.days, a.step)
