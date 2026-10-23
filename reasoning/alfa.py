"""Turn Alfa-Bank analytics PDFs into short theses an LLM can cite. Any new PDF, no per-file code.

These PDFs are slide images, so a page with no text layer is rendered and read by the vision model.
A text page keeps a thesis only when its quote is a verbatim fragment of the page. An image page keeps a short quote with no second check.
"""
import base64
import hashlib
import json
import os
import subprocess
from pathlib import Path

from pypdf import PdfReader

from reasoning.llm import LLM

ROOT = Path(__file__).resolve().parent.parent
PDF_DIRS = [ROOT / "analytical-papers", ROOT / "external-docs" / "alfa"]
OUT = Path(__file__).resolve().parent / "out" / "theses.jsonl"
CACHE = OUT.with_name("alfa-cache.jsonl")
PAGES = OUT.parent / "pages"
VL = "qwen/qwen3-vl-30b-a3b-instruct"
PROMPT = """Это страница аналитики Альфа-Банка. Выпиши не больше 4 тезисов.
Верни только JSON: {"theses":[{"quote":"дословная фраза со страницы, не длиннее 15 слов","claim":"один вывод банка","indicator":null,"direction":null,"status":"observed"}]}
status — observed или forecast. direction — up, down, flat или null.
Никакого другого текста. quote — короткая фраза, как она напечатана."""


def pdfs() -> list[Path]:
    found = []
    for folder in PDF_DIRS:
        if folder.exists():
            found.extend(sorted(folder.glob("*.pdf")))
    return found


def pages_text(path: Path) -> list[tuple[int, str]]:
    # pypdf writes "wrong pointing object" straight to fd 2, past sys.stderr.
    old, devnull = os.dup(2), os.open(os.devnull, os.O_WRONLY)
    os.dup2(devnull, 2)
    try:
        reader = PdfReader(str(path))
        return [(i + 1, page.extract_text() or "") for i, page in enumerate(reader.pages)]
    finally:
        os.dup2(old, 2)
        os.close(old)
        os.close(devnull)


def render(path: Path, page: int, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    prefix = dest.parent / dest.stem
    try:
        subprocess.run(["pdftoppm", "-jpeg", "-r", "80", "-f", str(page), "-l", str(page), str(path), str(prefix)],
                       check=True, capture_output=True)
    except FileNotFoundError as e:
        raise RuntimeError("pdftoppm (poppler) is required to read image-only PDFs") from e
    got = next(dest.parent.glob(dest.stem + "-*.jpg"))
    got.replace(dest)
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
    out = {}
    for line in CACHE.read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[row["key"]] = row["theses"]
    return out


def _remember(key: str, theses: list[dict]) -> None:
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    with CACHE.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"key": key, "theses": theses}, ensure_ascii=False) + "\n")


def read_page(llm: LLM, path: Path, page: int, text: str, cache: dict) -> list[dict]:
    key = hashlib.sha256(path.read_bytes()).hexdigest()[:12] + f"-{page}"
    if key in cache:
        return cache[key]
    doc = path.stem
    if text.strip():
        ans = llm.json(VL, PROMPT + f"\n\nСТРАНИЦА {page}:\n{text[:6000]}", f"alfa.{doc}.p{page}")
        transcript = text
    else:
        jpg = render(path, page, PAGES / f"{key}.jpg")
        url = "data:image/jpeg;base64," + base64.b64encode(jpg.read_bytes()).decode()
        ans = llm.json(VL, PROMPT, f"alfa.{doc}.p{page}", max_tokens=700, images=[url], tries=2, read_timeout=120)
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


def main() -> None:
    files = pdfs()
    if not files:
        raise SystemExit("no PDFs in analytical-papers/ or external-docs/alfa/")
    plan = [(path, page, text) for path in files for page, text in pages_text(path)]
    llm, cache, rows = LLM(OUT.with_suffix(".log")), _cache(), []
    print(f"alfa 0/{len(plan)} cached {sum(1 for p, page, _ in plan if hashlib.sha256(p.read_bytes()).hexdigest()[:12] + f'-{page}' in cache)}", flush=True)
    for i, (path, page, text) in enumerate(plan, 1):
        try:
            kept = read_page(llm, path, page, text, cache)
            rows.extend(kept)
            print(f"alfa {i}/{len(plan)} {path.name} p{page}: {len(kept)} theses, total {len(rows)}", flush=True)
        except Exception as e:
            print(f"alfa {i}/{len(plan)} {path.name} p{page}: FAILED {e}", flush=True)
    OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
    print(f"alfa done {len(rows)} theses, calls {llm.calls}, tokens {llm.tokens} -> {OUT}", flush=True)


if __name__ == "__main__":
    main()
