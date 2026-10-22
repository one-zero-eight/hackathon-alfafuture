# Aggregate judge outputs: per config mean +- SE over profiles (runs averaged first), Wilcoxon vs reference, Holm.
# Usage: python p5/agg.py <tag> [reference_cfg]
import sys, json, glob, re, numpy as np
from collections import defaultdict
from scipy.stats import wilcoxon
TAG = sys.argv[1]; REF = sys.argv[2] if len(sys.argv) > 2 else 'base_B3'
key = json.load(open(f'p5/judge_in/{TAG}_key.json')); per = defaultdict(lambda: defaultdict(list))
for f in glob.glob(f'p5/judge/{TAG}_*_r*.json'):
    u, r = re.search(r'_(U\d+)_(r\d)', f).groups(); J = json.load(open(f))
    for m, cfg in key[f'{u}_{r}'].items():
        j = J[m]; n = j['nuggets']
        per[cfg][u].append({'overall': j['overall'], 'nugget_cov': np.mean(n) if n else 0, 'dec_acc': j['correct'] / max(j['decisions'], 1),
                            'unsupported': j['unsupported'] / max(j['claims_checked'], 1)})
M = ['overall', 'nugget_cov', 'dec_acc', 'unsupported']
S = {c: {k: np.array([np.mean([x[k] for x in v[u]]) for u in sorted(v)]) for k in M} for c, v in per.items()}
us = {c: sorted(v) for c, v in per.items()}
print(f"{'config':14s} n " + ' '.join(f'{k:>16s}' for k in M))
pv = {}
for c in sorted(S, key=lambda c: -S[c]['overall'].mean()):
    print(f"{c:14s} {len(us[c]):2d} " + ' '.join(f"{S[c][k].mean():7.3f}±{S[c][k].std(ddof=1) / np.sqrt(len(S[c][k])):.3f}" for k in M))
    if c != REF and REF in S and us[c] == us[REF]:
        d = S[c]['overall'] - S[REF]['overall']; pv[c] = wilcoxon(d).pvalue if np.any(d) else 1.0
order = sorted(pv, key=pv.get); holm = {c: min(1, pv[c] * (len(pv) - i)) for i, c in enumerate(order)}
print(f'\nWilcoxon vs {REF} (overall, Holm-adjusted):', {c: round(p, 3) for c, p in holm.items()})
json.dump({c: {k: float(S[c][k].mean()) for k in M} for c in S}, open(f'p5/{TAG}_summary.json', 'w'), indent=1)
