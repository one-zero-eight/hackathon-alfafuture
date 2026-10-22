"""Issue coverage: fraction of gold key issues with >=1 supporting item among what the model sees.
Usage: python exp/issuecov.py <variant> ...   (uses *_news.txt if present to include card 'Related' items, else top.json[:10])"""
import re, json, os, sys, glob, numpy as np
ROOT = os.path.dirname(os.path.abspath(__file__))
issues = {}
for f in sorted(glob.glob(os.path.join(ROOT, "gold", "P*_gold.md"))):
    p = os.path.basename(f)[:2]; txt = open(f).read()
    sec = txt.split("## 2.")[0] if "## 2." in txt else txt.split("Decisions")[0]
    blocks = re.split(r"\n\*\*\d+\.|\n### |\n\d+\. \*\*", sec)[1:]
    issues[p] = [set(re.findall(r"A\d{4}", b)) for b in blocks if re.findall(r"A\d{4}", b)]
def seen(v, p):
    nf = os.path.join(ROOT, "runs", v, f"{p}_news.txt")
    if os.path.exists(nf): return set(re.findall(r"\[(A\d{4})\]", open(nf).read()))
    return set(json.load(open(os.path.join(ROOT, "runs", v, "top.json")))[p][:10])
print("issues per persona:", {p: len(x) for p, x in issues.items()})
for v in sys.argv[1:]:
    cov = [np.mean([bool(s & seen(v, p)) for s in iss]) for p, iss in sorted(issues.items())]
    print(f"{v:20} issue-cov {np.mean(cov):.2f}  per persona {[round(c,2) for c in cov]}")
