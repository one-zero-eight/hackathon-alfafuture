# Share of story IDs cited in each memo that were actually in its packet (hallucinated-ID check).
import json, re, glob, sys, collections
r = collections.defaultdict(lambda: [0, 0])
for f in sorted(glob.glob('p5/memos/*.md')):
    cfg, u = f.split('/')[-1][:-3].rsplit('_', 1); seen = set(json.load(open(f'p5/packets/{cfg}/seen.json'))[u])
    c = re.findall(r'A\d{4}', open(f).read()); r[cfg][0] += sum(x in seen for x in c); r[cfg][1] += len(c)
for k, (a, n) in r.items(): print(f"{k:16s} cited {n:4d}  in-packet {a / max(n, 1):.3f}")
