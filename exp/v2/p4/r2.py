# Round 2 on the round-1 winner (A2-Q2-E1): query combos, cross-encoder rerank (E3), encoder bake-off (E4).
import sys, json, numpy as np
import r1
from r1 import QS, dscore, evaluate, PROF, N, CARD, D
from sentence_transformers import CrossEncoder, SentenceTransformer

def base(p, q=('Q1', 'Q2')): return dscore('A2', sum((QS[x](p) for x in q), []))
CE = None
def e3(p, top=60):  # rerank top-60 by mean of top-3 cross-encoder scores over need sentences
    global CE; CE = CE or CrossEncoder('BAAI/bge-reranker-v2-m3', max_length=384)
    s = base(p); idx = np.argsort(-s)[:top]; needs = QS['Q1'](p) + QS['Q2'](p)
    txt = [f"{D.title.iloc[i]}. {CARD[i]['event']} {CARD[i]['mechanism']}" for i in idx]
    sc = CE.predict([(n, t) for n in needs for t in txt], batch_size=64).reshape(len(needs), top)
    out = s - 10.0; out[idx] = np.sort(sc, 0)[-3:].mean(0); return out

def xquad(p, lam=0.5, top=100, k=10):  # diversify top-100 over weighted Q4 aspects
    s = base(p); idx = np.argsort(-s)[:top]; ex = r1.EXP[p['id']]; needs = ex['needs']
    QV = r1.enc(needs); X = np.maximum(r1.A0[idx], r1.A1[idx])
    asp = [(a['weight'], np.clip((QV[[j for j in a['needs'] if j < len(needs)] or [0]] @ X.T).max(0), 0, None)) for a in ex['aspects']]
    rel = (s[idx] - s[idx].min()) / (np.ptp(s[idx]) + 1e-9); unc = [1.0] * len(asp); chosen = []
    for _ in range(k):
        cand = [c for c in range(top) if c not in chosen]
        best = max(cand, key=lambda c: (1 - lam) * rel[c] + lam * sum(w * unc[a] * pa[c] for a, (w, pa) in enumerate(asp)))
        chosen.append(best); unc = [unc[a] * (1 - asp[a][1][best]) for a in range(len(asp))]
    out = s.copy(); out[idx[chosen]] = s.max() + 1 + np.arange(k, 0, -1); return out

ENC = {  # name: (model id, query prefix, doc prefix)
    'USER-bge-m3': ('deepvk/USER-bge-m3', '', ''),
    'FRIDA': ('ai-forever/FRIDA', 'search_query: ', 'search_document: '),
    'e5-large-instruct': ('intfloat/multilingual-e5-large-instruct', 'Instruct: Given a business information need, retrieve relevant news\nQuery: ', ''),
    'Qwen3-Emb-0.6B': ('Qwen/Qwen3-Embedding-0.6B', 'Instruct: Given a business information need, retrieve relevant news\nQuery: ', ''),
}
def encoder_arm(name):
    mid, qp, dp = ENC[name]; m = SentenceTransformer(mid, trust_remote_code=True)
    e = lambda t: m.encode(t, normalize_embeddings=True, batch_size=16, show_progress_bar=False)
    a0 = e([dp + f"{t}. {str(l)[:300]}" for t, l in zip(D.title, D.lead)])
    a1 = e([dp + f"{c['event']} {c['mechanism']} " + ' '.join(f"{x['okved']}:{x['effect']}" for x in c['cause_effect']) for c in CARD])
    np.save(f'p4/enc_{name}.npy', np.stack([a0, a1]))
    def fn(p):
        Q = e([qp + q for q in QS['Q1'](p) + QS['Q2'](p)]); k = 3
        return np.maximum(np.sort(Q @ a0.T, 0)[-k:].mean(0), np.sort(Q @ a1.T, 0)[-k:].mean(0))
    return fn

ARMS = {'base': base, 'Q2only': lambda p: base(p, ('Q2',)), 'Q2+Q3': lambda p: base(p, ('Q2', 'Q3')), 'Q1+Q2': lambda p: base(p, ('Q1', 'Q2')),
        'Q1+Q2+Q3': lambda p: base(p, ('Q1', 'Q2', 'Q3')), 'E3-rerank': e3, 'xQuAD': xquad}
if __name__ == '__main__':
    want = sys.argv[1:] or list(ARMS); out = {}
    for name in want:
        fn = ARMS[name] if name in ARMS else encoder_arm(name)
        r, per = evaluate(fn); out[name] = r | {'per_profile_test_ndcg': [round(x, 3) for x in per]}
        print(f"{name:18s} " + ' '.join(f"{k}={v}" for k, v in r.items() if 'ndcg' in k), flush=True)
        json.dump(out, open(f"p4/r2_{'_'.join(want)[:40]}.json", 'w'), indent=1)
