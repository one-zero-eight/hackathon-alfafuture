"""Backend settings from the environment (docker/compose.yaml sets them)."""
import os

METHODS = ("lexical", "dense_llm", "dense_xquad")  # NewsSearch methods, see docs/news-search.md


def _int(name, default):
    return int(os.environ.get(name, default))


DATABASE_URL = os.environ.get("DATABASE_URL", "")
NEWS_SEARCH_URL = os.environ.get("NEWS_SEARCH_URL", "http://news_search:8000").rstrip("/")
ANALYTICS_URL = os.environ.get("ANALYTICS_URL", "http://analytics:8000").rstrip("/")
# Which way of searching the news is used for every new profile. Part of the profile key: changing it computes new pages.
NEWS_SEARCH_METHOD = os.environ.get("NEWS_SEARCH_METHOD", "dense_xquad")
if NEWS_SEARCH_METHOD not in METHODS:
    raise SystemExit(f"NEWS_SEARCH_METHOD must be one of {METHODS}, got {NEWS_SEARCH_METHOD!r}")
PROFILE_TTL_HOURS = _int("PROFILE_TTL_HOURS", 24)  # a ready page younger than this answers the same request again
COMPANY_DIR = os.environ.get("COMPANY_DIR", "/company")  # df_Uid_data_hack.csv and df_Uid_payment_hack.csv (bank data, not in git)
PAPERS_DIR = os.environ.get("PAPERS_DIR", "/papers")  # Alfa-Bank PDFs, served under /api/papers
WORKER_ENABLED = os.environ.get("WORKER_ENABLED", "true").lower() != "false"
REQUEST_TIMEOUT = _int("REQUEST_TIMEOUT", 3600)  # seconds for one search or one analytics run
AGENTS_URL = os.environ.get("AGENTS_URL", "http://agents:8000").rstrip("/")  # the feedback_intent agent
