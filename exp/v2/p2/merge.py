# Merge label runs A and B: weighted kappa, gold = mean grade, list |A-B|>=2 for adjudication.
import json, glob, numpy as np
from sklearn.metrics import cohen_kappa_score
ids = [l.split(']')[0][1:] for f in sorted(glob.glob('../../exp/chunks/chunk_*.txt')) for l in open(f) if l.startswith('[A')]
R = {}
for run in 'AB':
    R[run] = {}
    for f in sorted(glob.glob(f'p2/labels/{run}_*.json')):
        for u, d in json.load(open(f)).items(): R[run].setdefault(u, {}).update(d)
us = sorted(R['A']); a = [R['A'][u].get(i, 0) for u in us for i in ids]; b = [R['B'][u].get(i, 0) for u in us for i in ids]
print('pairs', len(a), 'kappa(lin)', round(cohen_kappa_score(a, b, weights='linear'), 3), 'binary>=2 kappa', round(cohen_kappa_score([x >= 2 for x in a], [x >= 2 for x in b]), 3))
gold = {u: {i: (R['A'][u].get(i, 0) + R['B'][u].get(i, 0)) / 2 for i in ids if R['A'][u].get(i, 0) or R['B'][u].get(i, 0)} for u in us}
adj = [(u, i, R['A'][u].get(i, 0), R['B'][u].get(i, 0)) for u in us for i in ids if abs(R['A'][u].get(i, 0) - R['B'][u].get(i, 0)) >= 2]
print('adjudicate', len(adj), 'labelled per profile', {u: sum(v >= 2 for v in gold[u].values()) for u in us})
json.dump(gold, open('p2/gold.json', 'w')); json.dump(adj, open('p2/adjudicate.json', 'w'))
