# S1: query library L1 (filled from login parameters, no LLM per user) vs LLM needs, on max(A0, K1) doc vectors.
import json, numpy as np, r1
from r1 import QS, evaluate, enc, A0, PROF
K1 = np.load('s1/keys_k1.npy'); LIB = json.load(open('s1/library.json'))
SEC = json.load(open('p0/vocab.json'))['okved_sections']; REG = {'moscow': 'Москва', 'volga': 'Поволжье', 'siberia_fe': 'Сибирь и Дальний Восток'}
def l1(p):
    blocks = LIB['role'][p['role']] + LIB['okved'][p['okved']] + LIB['region'][p['region']] + sum((LIB['product'][x] for x in p['products']), [])
    blocks += LIB['role_okved'].get(f"{p['role']}|{p['okved']}", [])
    return [b.replace('{SECTOR}', SEC[p['okved']]).replace('{REGION}', REG[p['region']]) for b in blocks]
def score(Q): S0, S1 = enc(Q) @ A0.T, enc(Q) @ K1.T; return np.maximum(np.sort(S0, 0)[-3:].mean(0), np.sort(S1, 0)[-3:].mean(0))
assert all(len(l1(p)) >= 15 for p in PROF), 'library too thin'
ARMS = {'Q1+Q2 (LLM needs)': lambda p: score(QS['Q1'](p) + QS['Q2'](p)), 'L1 library': lambda p: score(l1(p)),
        'L1 + Q2': lambda p: score(l1(p) + QS['Q2'](p))}
for n, f in ARMS.items():
    r, _ = evaluate(f); print(f"{n:18s} andcg={r['all_andcg']} dev={r['dev_ndcg']} test={r['test_ndcg']} dev_p10={r['dev_p10']} test_p10={r['test_p10']}", flush=True)
print('example U07:', l1(PROF[6])[:3])
