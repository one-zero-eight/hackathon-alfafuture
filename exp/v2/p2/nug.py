# Merge two nugget runs: run-1 nuggets with a sid-overlapping run-2 nugget (Jaccard >= 0.25) are "vital".
import json
out = {}
for u in [f'U{i:02d}' for i in range(1, 17)]:
    a, b = (json.load(open(f'p2/nuggets/{r}_{u}.json')) for r in ('r1', 'r2'))
    jac = lambda x, y: len(set(x) & set(y)) / len(set(x) | set(y))
    out[u] = [n | {'vital': any(jac(n['sids'], m['sids']) >= 0.25 for m in b)} for n in a if n['sids']]
print({u: f"{sum(n['vital'] for n in v)}/{len(v)}" for u, v in out.items()})
json.dump(out, open('p2/nuggets.json', 'w'), ensure_ascii=False)
