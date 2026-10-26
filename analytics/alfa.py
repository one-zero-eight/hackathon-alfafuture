"""Turn Alfa-Bank analytics PDFs into short theses an LLM can cite. Any new PDF, no per-file code.

    python -m analytics.alfa [PDF_DIR]     # default PAPERS_DIR (external-docs/analytical-papers); writes theses.jsonl

These PDFs are slide images, so a page with no text layer is rendered (poppler's pdftoppm) and read by the vision model through
the agents service. A text page keeps a thesis only when its quote is a verbatim fragment of the page. An image page keeps a
short quote with no second check. Results are cached per page, so a rerun only reads new pages.
"""

import base64
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

from agents.client import Agents

PAPERS_DIR = Path(
    os.environ.get(
        "PAPERS_DIR",
        Path(__file__).resolve().parents[1] / "external-docs" / "analytical-papers",
    )
)
DATA_DIR = Path(os.environ.get("ANALYTICS_DATA", Path(__file__).parent / "data"))
THESES = DATA_DIR / "theses.jsonl"
CACHE = DATA_DIR / "alfa-cache.jsonl"
PAGES = DATA_DIR / "pages"


def pdfs(folder: Path) -> list[Path]:
    return sorted(folder.glob("*.pdf")) if folder.exists() else []


def pages_text(path: Path) -> list[tuple[int, str]]:
    from pypdf import PdfReader

    # pypdf writes "wrong pointing object" straight to fd 2, past sys.stderr.
    old, devnull = os.dup(2), os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)
    try:
        reader = PdfReader(str(path))
        return [
            (i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)
        ]
    finally:
        os.dup2(old, 2)
        os.close(old)
        os.close(devnull)


def render(path: Path, page: int, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    prefix = dest.parent / dest.stem
    try:
        subprocess.run(
            [
                "pdftoppm",
                "-jpeg",
                "-r",
                "80",
                "-f",
                str(page),
                "-l",
                str(page),
                str(path),
                str(prefix),
            ],
            check=True,
            capture_output=True,
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            "pdftoppm (poppler) is required to read image-only PDFs"
        ) from e
    next(dest.parent.glob(dest.stem + "-*.jpg")).replace(dest)
    return dest


def keep(theses: list[dict], page_text: dict[tuple[str, int], str]) -> list[dict]:
    """Drop a thesis whose quote is not on the page it cites. Checked in code, not by the model."""
    ok = []
    for t in theses:
        blob = " ".join(page_text.get((t.get("doc", ""), t.get("page")), "").split())
        quote = " ".join(str(t.get("quote", "")).split())
        if quote and quote in blob and t.get("claim"):
            t["quote"] = quote
            ok.append(t)
    return ok


def _cache() -> dict[str, list[dict]]:
    if not CACHE.exists():
        return {}
    rows = (
        json.loads(line)
        for line in CACHE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    )
    return {row["key"]: row["theses"] for row in rows}


def _remember(key: str, theses: list[dict]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"key": key, "theses": theses}, ensure_ascii=False) + "\n")


def read_page(
    agents: Agents, path: Path, page: int, text: str, cache: dict
) -> list[dict]:
    key = hashlib.sha256(path.read_bytes()).hexdigest()[:12] + f"-{page}"
    if key in cache:
        return cache[key]
    doc = path.stem
    if text.strip():
        ans = agents.run("alfa_page", {"page": page, "text": text})
        transcript = text
    else:
        jpg = render(path, page, PAGES / f"{key}.jpg")
        ans = agents.run(
            "alfa_page",
            {
                "page": page,
                "images": [
                    "data:image/jpeg;base64,"
                    + base64.b64encode(jpg.read_bytes()).decode()
                ],
            },
        )
        transcript = None  # shortcut: no text layer to check the quote against; a second OCR would replace this
    theses = []
    for i, t in enumerate(ans.get("theses") or [], 1):
        t["doc"], t["page"] = doc, page
        t["id"] = f"alfa:{doc}:p{page}:t{i}"
        t["from_image"] = transcript is None
        theses.append(t)
    if transcript is None:
        kept = []
        for t in theses:
            quote = " ".join(str(t.get("quote", "")).split())
            if len(quote) >= 12 and t.get("claim"):
                t["quote"] = quote
                kept.append(t)
    else:
        kept = keep(theses, {(doc, page): transcript})
    _remember(key, kept)
    cache[key] = kept
    return kept


def load_theses() -> list[dict]:
    if not THESES.exists():
        return []
    return [
        json.loads(line)
        for line in THESES.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def main(folder: Path) -> None:
    files = pdfs(folder)
    if not files:
        raise SystemExit(f"no PDFs in {folder}")
    plan = [(path, page, text) for path in files for page, text in pages_text(path)]
    agents, cache, rows = Agents(), _cache(), []
    for i, (path, page, text) in enumerate(plan, 1):
        try:
            kept = read_page(agents, path, page, text, cache)
            rows.extend(kept)
            print(
                f"alfa {i}/{len(plan)} {path.name} p{page}: {len(kept)} theses, total {len(rows)}",
                flush=True,
            )
        except Exception as e:  # one unreadable page must not stop the rest
            print(f"alfa {i}/{len(plan)} {path.name} p{page}: FAILED {e}", flush=True)
    THESES.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
        encoding="utf-8",
    )
    print(
        f"alfa done: {len(rows)} theses, LLM cost {agents.cost:.2f} -> {THESES}",
        flush=True,
    )


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else PAPERS_DIR)
