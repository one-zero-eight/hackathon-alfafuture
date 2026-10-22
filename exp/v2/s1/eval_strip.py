# S1 check: does the shared "<sector>:" prefix / "для: <role>" suffix dominate similarity? Embed only "event → effect".
import json, re, numpy as np, r1, eval_lib as L
from r1 import QS, evaluate, enc, A0, ids, CARD
from sentence_transformers import SentenceTransformer
import keys as K
def core(s): s = s.split(':', 1)[1] if ':' in s.split('→')[0] else s; return re.sub(r'\s*для:\s*[^;]*', '', s).strip()
M = r1.M; KC = M.encode([core(K.key(c)) for c in CARD], normalize_embeddings=True, batch_size=32, show_progress_bar=False)
print('key core example:', core(K.key(CARD[ids.index('A0123')])))
def score(Q, X2): S0, S1 = enc(Q) @ A0.T, enc(Q) @ X2.T; return np.maximum(np.sort(S0, 0)[-3:].mean(0), np.sort(S1, 0)[-3:].mean(0))
lib = lambda p: [core(q) for q in L.l1(p)]
print('lib core example:', lib(r1.PROF[6])[:2])
ARMS = {'Q1+Q2 vs core keys': lambda p: score(QS['Q1'](p) + QS['Q2'](p), KC), 'L1 core vs core keys': lambda p: score(lib(p), KC),
        'L1 core + Q2 vs core keys': lambda p: score(lib(p) + QS['Q2'](p), KC)}
for n, f in ARMS.items():
    r, _ = evaluate(f); print(f"{n:26s} andcg={r['all_andcg']} dev={r['dev_ndcg']} test={r['test_ndcg']} dev_p10={r['dev_p10']}", flush=True)
